-- R2/G1: isolated schema. Apply ONLY to a verified disposable PostgreSQL database.
-- Migration owner must be distinct from runtime roles. Session scope is set by a
-- trusted server after OAuth and ACL checks, never by client-provided SQL.
-- The applier MUST first run: SELECT set_config('living.migration_checksum', '<sha256 of this file>', false);
-- Revision rule: a revision_id names exactly one observation row inside a (tenant, source) scope.
-- KNOWLEDGE-TIME SEMANTICS: "known at k" means observations.recorded_at <= k, where recorded_at is the
-- DATABASE clock (clock_timestamp() in the insert trigger), never client data. recorded_at is taken at
-- INSERT but a row only becomes visible at COMMIT, so a raw recorded_at<=k filter is not stable while an
-- ingest is in flight. Stability is enforced by a settled-horizon rule: ingest_observation holds a
-- per-(tenant,source) advisory lock until commit (so at most one ingest per source is in flight and
-- ingest_seq, recorded_at and commit order agree), and as_known_at / as_effective_at call
-- living.knowledge_horizon(t,s) first and raise KNOWLEDGE_HORIZON_NOT_SETTLED for any k later than the
-- horizon. Horizon = now (taken BEFORE the in-flight probe) when no foreign ingest holds the lock,
-- else the newest committed recorded_at minus 1 microsecond (-infinity when the source has no row).
-- Consequence: a query that returns an answer never returns a different answer after a later commit.
-- Callers may query least(k, living.knowledge_horizon(t,s)). The rule needs READ COMMITTED (each
-- statement of the volatile read APIs takes a snapshot after the probe); other isolation levels are
-- rejected. Only ingest_observation is a supported writer of observations (direct INSERT by the
-- migration owner bypasses the lock and is outside the guarantee).
BEGIN;
CREATE SCHEMA IF NOT EXISTS living;
CREATE TABLE IF NOT EXISTS living.schema_migrations(
 version text PRIMARY KEY CHECK(length(version)>0),
 checksum text NOT NULL CHECK(checksum ~ '^[a-f0-9]{64}$'),
 applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 applied_by text NOT NULL DEFAULT current_user
);
-- Precondition + checksum bookkeeping: every migration calls this first.
-- Returns true when the version was newly recorded (the caller then runs its body) and false when
-- the version is already recorded with the SAME checksum (the whole file is a no-op, so re-running
-- 001/002 after 003 can never undo hardening). A different checksum raises. The checksum is the
-- session-local value the applier passes (SELECT set_config('living.migration_checksum', ...))
-- in the same session as the file; it is consumed and reset here so it cannot leak to the next file.
-- Created only when absent (or when an old void-returning version exists) so a re-run keeps the
-- owner/ACL set by 003.
DO $boot$
BEGIN
 IF to_regprocedure('living.record_migration(text,text[])') IS NOT NULL
  AND (SELECT prorettype FROM pg_catalog.pg_proc
        WHERE oid = to_regprocedure('living.record_migration(text,text[])')) <> 'boolean'::regtype THEN
  DROP FUNCTION living.record_migration(text,text[]);
 END IF;
 IF to_regprocedure('living.record_migration(text,text[])') IS NULL THEN
  EXECUTE $c$
CREATE FUNCTION living.record_migration(p_version text, p_requires text[])
RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE sum_in text; sum_old text; req text; fresh boolean;
BEGIN
 sum_in := nullif(current_setting('living.migration_checksum', true), '');
 IF p_version IS NULL OR sum_in IS NULL OR sum_in !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'MIGRATION_CHECKSUM_REQUIRED';
 END IF;
 FOREACH req IN ARRAY coalesce(p_requires, ARRAY[]::text[]) LOOP
  IF NOT EXISTS(SELECT 1 FROM living.schema_migrations WHERE version = req) THEN
   RAISE EXCEPTION 'MIGRATION_PRECONDITION_FAILED: % requires %', p_version, req;
  END IF;
 END LOOP;
 SELECT checksum INTO sum_old FROM living.schema_migrations WHERE version = p_version;
 IF FOUND THEN
  IF sum_old IS DISTINCT FROM sum_in THEN RAISE EXCEPTION 'MIGRATION_CHECKSUM_MISMATCH'; END IF;
  fresh := false;
 ELSE
  INSERT INTO living.schema_migrations(version, checksum) VALUES (p_version, sum_in);
  fresh := true;
 END IF;
 PERFORM set_config('living.migration_checksum', '', false);
 RETURN fresh;
END $fn$;
  $c$;
 END IF;
END $boot$;
-- Whole-file guard: the body below runs only when 001 is not yet recorded.
DO $mig$
BEGIN
IF living.record_migration('001', ARRAY[]::text[]) THEN
EXECUTE $body$

CREATE TABLE IF NOT EXISTS living.tenants(
 tenant_id text PRIMARY KEY CHECK(length(tenant_id)>0)
);
CREATE TABLE IF NOT EXISTS living.sources(
 tenant_id text NOT NULL REFERENCES living.tenants(tenant_id),
 source_id text NOT NULL CHECK(length(source_id)>0),
 company_id text,
 scope_epoch bigint NOT NULL DEFAULT 0 CHECK(scope_epoch>=0),
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SUSPENDED','REVOKED')),
 PRIMARY KEY(tenant_id,source_id)
);
-- Any status change bumps scope_epoch so fenced writers holding the old epoch are rejected.
CREATE OR REPLACE FUNCTION living.sources_epoch_bump() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
 IF NEW.status IS DISTINCT FROM OLD.status AND NEW.scope_epoch IS NOT DISTINCT FROM OLD.scope_epoch THEN
  NEW.scope_epoch := OLD.scope_epoch + 1;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS sources_epoch_bump ON living.sources;
CREATE TRIGGER sources_epoch_bump BEFORE UPDATE ON living.sources
 FOR EACH ROW EXECUTE FUNCTION living.sources_epoch_bump();

CREATE TABLE IF NOT EXISTS living.observations(
 tenant_id text NOT NULL, source_id text NOT NULL,
 observation_id uuid NOT NULL, object_id text NOT NULL,
 revision_id uuid NOT NULL, kind text NOT NULL
 CHECK(kind IN ('OBSERVED','SOURCE_UNAVAILABLE','GAP','ATTESTATION_REVOKED')),
 digest text, source_effective_at timestamptz,
 observed_at timestamptz NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 ingest_seq bigint GENERATED ALWAYS AS IDENTITY,
 supersedes uuid, provenance jsonb NOT NULL DEFAULT '{}'::jsonb
 CHECK(octet_length(provenance::text)<=65536),
 PRIMARY KEY(tenant_id,source_id,observation_id),
 UNIQUE(tenant_id,source_id,revision_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 FOREIGN KEY(tenant_id,source_id,supersedes)
 REFERENCES living.observations(tenant_id,source_id,observation_id),
 CHECK(observed_at<=recorded_at),
 CHECK(kind<>'OBSERVED' OR (digest IS NOT NULL AND digest ~ '^[a-f0-9]{64}$'))
);
CREATE INDEX IF NOT EXISTS observations_known_idx ON living.observations
 (tenant_id,source_id,recorded_at,ingest_seq);
CREATE INDEX IF NOT EXISTS observations_effective_idx ON living.observations
 (tenant_id,source_id,object_id,source_effective_at,recorded_at,ingest_seq);
-- recorded_at is server-authoritative: a client-supplied (backdated) value is overwritten.
CREATE OR REPLACE FUNCTION living.observations_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE parent_object text;
BEGIN
 NEW.recorded_at := clock_timestamp();
 IF NEW.supersedes IS NOT NULL THEN
  SELECT object_id INTO parent_object FROM living.observations
   WHERE tenant_id=NEW.tenant_id AND source_id=NEW.source_id AND observation_id=NEW.supersedes;
  IF parent_object IS DISTINCT FROM NEW.object_id THEN
   RAISE EXCEPTION 'SUPERSEDES_OBJECT_MISMATCH';
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS observations_before_insert ON living.observations;
CREATE TRIGGER observations_before_insert BEFORE INSERT ON living.observations
 FOR EACH ROW EXECUTE FUNCTION living.observations_before_insert();

CREATE TABLE IF NOT EXISTS living.accepted_heads(
 tenant_id text NOT NULL,source_id text NOT NULL,model_key text NOT NULL,
 revision_id uuid, version bigint NOT NULL DEFAULT 0 CHECK(version>=0),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,model_key),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 FOREIGN KEY(tenant_id,source_id,revision_id)
 REFERENCES living.observations(tenant_id,source_id,revision_id)
);
CREATE TABLE IF NOT EXISTS living.acceptance_events(
 tenant_id text NOT NULL,source_id text NOT NULL,acceptance_id uuid NOT NULL,
 model_key text NOT NULL,from_version bigint NOT NULL,to_version bigint NOT NULL,
 accepted_revision uuid NOT NULL,approver_subject text NOT NULL,
 independent_evidence_ref text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,acceptance_id),
 UNIQUE(tenant_id,source_id,model_key,to_version),
 FOREIGN KEY(tenant_id,source_id,model_key)
 REFERENCES living.accepted_heads(tenant_id,source_id,model_key),
 FOREIGN KEY(tenant_id,source_id,accepted_revision)
 REFERENCES living.observations(tenant_id,source_id,revision_id),
 CHECK(to_version=from_version+1),
 CHECK(length(independent_evidence_ref)>0),
 CHECK(length(approver_subject)>0)
);
CREATE TABLE IF NOT EXISTS living.jobs(
 tenant_id text NOT NULL,source_id text NOT NULL,job_id uuid NOT NULL,
 job_kind text NOT NULL,request_digest text NOT NULL
 CHECK(request_digest ~ '^[a-f0-9]{64}$'),
 idempotency_key text NOT NULL,
 state text NOT NULL DEFAULT 'PENDING'
 CHECK(state IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 lease_owner text,lease_until timestamptz,
 fence bigint NOT NULL DEFAULT 0 CHECK(fence>=0),
 scope_epoch bigint NOT NULL CHECK(scope_epoch>=0),
 attempt integer NOT NULL DEFAULT 0 CHECK(attempt>=0),
 max_attempts integer NOT NULL DEFAULT 5 CHECK(max_attempts>0),
 next_run_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 last_error text,
 payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(octet_length(payload::text)<=65536),
 PRIMARY KEY(tenant_id,source_id,job_id),
 UNIQUE(tenant_id,source_id,idempotency_key),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 CHECK((state='RUNNING' AND lease_owner IS NOT NULL AND lease_until IS NOT NULL)
    OR (state<>'RUNNING' AND lease_owner IS NULL AND lease_until IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_running_per_source
 ON living.jobs(tenant_id,source_id) WHERE state='RUNNING';
CREATE TABLE IF NOT EXISTS living.cursors(
 tenant_id text NOT NULL,source_id text NOT NULL,connection_id text NOT NULL,
 cursor_value text NOT NULL,version bigint NOT NULL DEFAULT 0 CHECK(version>=0),
 scope_epoch bigint NOT NULL CHECK(scope_epoch>=0),
 -- sha256 of the last committed page (prior cursor, new cursor, events); replay is allowed only for an identical page.
 last_page_digest text CHECK(last_page_digest IS NULL OR last_page_digest ~ '^[a-f0-9]{64}$'),
 PRIMARY KEY(tenant_id,source_id,connection_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources
);
CREATE TABLE IF NOT EXISTS living.outbox(
 tenant_id text NOT NULL,source_id text NOT NULL,connection_id text NOT NULL,
 event_id text NOT NULL, event_digest text NOT NULL CHECK(event_digest ~ '^[a-f0-9]{64}$'),
 content jsonb NOT NULL CHECK(octet_length(content::text)<=262144),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 seq bigint GENERATED ALWAYS AS IDENTITY,
 status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DELIVERED','FAILED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 PRIMARY KEY(tenant_id,source_id,connection_id,event_id),
 UNIQUE(seq),
 FOREIGN KEY(tenant_id,source_id,connection_id)
 REFERENCES living.cursors(tenant_id,source_id,connection_id)
);

-- Immutability: row-level UPDATE/DELETE and statement-level TRUNCATE are rejected.
CREATE OR REPLACE FUNCTION living.reject_immutable_mutation() RETURNS trigger
LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'IMMUTABLE_LEDGER'; END $fn$;
DROP TRIGGER IF EXISTS observations_immutable ON living.observations;
CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE ON living.observations
 FOR EACH ROW EXECUTE FUNCTION living.reject_immutable_mutation();
DROP TRIGGER IF EXISTS acceptance_immutable ON living.acceptance_events;
CREATE TRIGGER acceptance_immutable BEFORE UPDATE OR DELETE ON living.acceptance_events
 FOR EACH ROW EXECUTE FUNCTION living.reject_immutable_mutation();
DROP TRIGGER IF EXISTS observations_no_truncate ON living.observations;
CREATE TRIGGER observations_no_truncate BEFORE TRUNCATE ON living.observations
 FOR EACH STATEMENT EXECUTE FUNCTION living.reject_immutable_mutation();
DROP TRIGGER IF EXISTS acceptance_no_truncate ON living.acceptance_events;
CREATE TRIGGER acceptance_no_truncate BEFORE TRUNCATE ON living.acceptance_events
 FOR EACH STATEMENT EXECUTE FUNCTION living.reject_immutable_mutation();
DROP TRIGGER IF EXISTS outbox_no_truncate ON living.outbox;
CREATE TRIGGER outbox_no_truncate BEFORE TRUNCATE ON living.outbox
 FOR EACH STATEMENT EXECUTE FUNCTION living.reject_immutable_mutation();
-- Outbox: only delivery bookkeeping (status, attempts) may change.
CREATE OR REPLACE FUNCTION living.outbox_guard_update() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
 IF NEW.content IS DISTINCT FROM OLD.content
  OR NEW.event_digest IS DISTINCT FROM OLD.event_digest
  OR NEW.event_id IS DISTINCT FROM OLD.event_id
  OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
  OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
  OR NEW.source_id IS DISTINCT FROM OLD.source_id
  OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
  RAISE EXCEPTION 'IMMUTABLE_OUTBOX_CONTENT';
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS outbox_immutable_content ON living.outbox;
CREATE TRIGGER outbox_immutable_content BEFORE UPDATE ON living.outbox
 FOR EACH ROW EXECUTE FUNCTION living.outbox_guard_update();

-- Scope guard used by every mutating API. This draft only checks the transaction GUCs;
-- 003 replaces it with a role_scope grant check. NULL-safe: unset scope always fails.
CREATE OR REPLACE FUNCTION living.assert_scope(t text, s text) RETURNS void
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
 IF t IS NULL OR s IS NULL
  OR t IS DISTINCT FROM nullif(current_setting('living.tenant_id', true), '')
  OR s IS DISTINCT FROM nullif(current_setting('living.source_id', true), '') THEN
  RAISE EXCEPTION 'SCOPE_NOT_SET';
 END IF;
END $fn$;

-- Authenticated caller identity: the SET ROLE value when present, else session_user.
-- Not changed by SECURITY DEFINER switching, so definer APIs can see who called them.
CREATE OR REPLACE FUNCTION living.caller_role() RETURNS text LANGUAGE sql STABLE AS $fn$
 SELECT CASE WHEN coalesce(current_setting('role', true),'none') IN ('none','')
  THEN session_user::text ELSE current_setting('role') END
$fn$;
-- Heads change only inside promote_head (which raises living.promoting for its own transaction).
-- 003 hardens this guard with a current_user check (definer owner only).
CREATE OR REPLACE FUNCTION living.accepted_heads_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.revision_id IS NOT NULL OR NEW.version<>0 THEN RAISE EXCEPTION 'HEAD_CHANGE_FORBIDDEN'; END IF;
 ELSIF NEW.revision_id IS DISTINCT FROM OLD.revision_id OR NEW.version IS DISTINCT FROM OLD.version THEN
  IF coalesce(current_setting('living.promoting', true),'') <> 'on' THEN
   RAISE EXCEPTION 'HEAD_CHANGE_FORBIDDEN';
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS accepted_heads_guard ON living.accepted_heads;
CREATE TRIGGER accepted_heads_guard BEFORE INSERT OR UPDATE ON living.accepted_heads
 FOR EACH ROW EXECUTE FUNCTION living.accepted_heads_guard();

-- Settled knowledge horizon (see the header). VOLATILE on purpose: the clock is read BEFORE the
-- in-flight probe, and the caller's next statement then takes a fresh snapshot AFTER the probe.
-- The probe looks at the advisory lock ingest_observation holds (pg_locks, no lock is taken here).
CREATE OR REPLACE FUNCTION living.knowledge_horizon(t text,s text) RETURNS timestamptz
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE c timestamptz; key bigint; inflight boolean; newest timestamptz;
BEGIN
 c := clock_timestamp();
 key := hashtextextended('ingest:'||t||'/'||s,0);
 SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks l
   WHERE l.locktype='advisory' AND l.granted AND l.objsubid=1
    AND l.pid IS DISTINCT FROM pg_backend_pid()
    AND l.database=(SELECT d.oid FROM pg_catalog.pg_database d WHERE d.datname=current_database())
    AND l.classid::bigint=((key >> 32) & 4294967295) AND l.objid::bigint=(key & 4294967295))
  INTO inflight;
 IF NOT inflight THEN RETURN c; END IF;
 SELECT max(o.recorded_at) INTO newest FROM living.observations o
  WHERE o.tenant_id=t AND o.source_id=s;
 IF newest IS NULL THEN RETURN '-infinity'::timestamptz; END IF;
 RETURN newest - interval '1 microsecond';
END $fn$;
CREATE OR REPLACE FUNCTION living.assert_knowledge_settled(t text,s text,k timestamptz) RETURNS void
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF current_setting('transaction_isolation') <> 'read committed'
  OR k > living.knowledge_horizon(t,s) THEN
  RAISE EXCEPTION 'KNOWLEDGE_HORIZON_NOT_SETTLED';
 END IF;
END $fn$;

-- Bitemporal reads. Ordering tiebreak is ingest_seq (server-assigned), never client data.
-- as_known_at: per object the latest OBSERVED row known at k; `available` is false when a later
-- non-OBSERVED row (GAP / SOURCE_UNAVAILABLE / ATTESTATION_REVOKED) exists, but never hides the OBSERVED row.
-- Objects that never had an OBSERVED row are returned as their latest row with available=false.
CREATE OR REPLACE FUNCTION living.as_known_at(t text,s text,k timestamptz)
RETURNS TABLE(
 tenant_id text, source_id text, observation_id uuid, object_id text, revision_id uuid,
 kind text, digest text, source_effective_at timestamptz, observed_at timestamptz,
 recorded_at timestamptz, ingest_seq bigint, supersedes uuid,
 available boolean, latest_kind text, revoked boolean)
LANGUAGE plpgsql VOLATILE STRICT AS $fn$
#variable_conflict use_column
BEGIN
 PERFORM living.assert_knowledge_settled(t,s,k);
 RETURN QUERY
 WITH r AS (
  SELECT o.tenant_id, o.source_id, o.observation_id, o.object_id, o.revision_id, o.kind,
   o.digest, o.source_effective_at, o.observed_at, o.recorded_at, o.ingest_seq, o.supersedes,
   row_number() OVER (PARTITION BY o.object_id
    ORDER BY o.ingest_seq DESC) AS rn_all,
   row_number() OVER (PARTITION BY o.object_id
    ORDER BY (o.kind='OBSERVED') DESC, o.ingest_seq DESC) AS rn_head
  FROM living.observations o
  WHERE o.tenant_id=t AND o.source_id=s AND o.recorded_at<=k),
 lat AS (SELECT r1.object_id, r1.kind FROM r r1 WHERE r1.rn_all=1)
 SELECT r.tenant_id, r.source_id, r.observation_id, r.object_id, r.revision_id, r.kind,
  r.digest, r.source_effective_at, r.observed_at, r.recorded_at, r.ingest_seq, r.supersedes,
  (lat.kind='OBSERVED') AS available, lat.kind AS latest_kind,
  EXISTS(SELECT 1 FROM r rv WHERE rv.object_id=r.object_id AND rv.kind='ATTESTATION_REVOKED'
   AND rv.ingest_seq>r.ingest_seq) AS revoked
 FROM r JOIN lat ON lat.object_id=r.object_id
 WHERE r.rn_head=1
 ORDER BY r.object_id;
END $fn$;
-- as_effective_at: per object the OBSERVED row with the greatest source_effective_at<=v among rows
-- known at k (effective_unknown=false), PLUS the latest OBSERVED row whose source_effective_at is
-- NULL (effective_unknown=true) so undated rows are flagged, never silently dropped.
CREATE OR REPLACE FUNCTION living.as_effective_at(t text,s text,v timestamptz,k timestamptz)
RETURNS TABLE(
 tenant_id text, source_id text, observation_id uuid, object_id text, revision_id uuid,
 kind text, digest text, source_effective_at timestamptz, observed_at timestamptz,
 recorded_at timestamptz, ingest_seq bigint, supersedes uuid,
 effective_unknown boolean, revoked boolean)
LANGUAGE plpgsql VOLATILE STRICT AS $fn$
#variable_conflict use_column
BEGIN
 PERFORM living.assert_knowledge_settled(t,s,k);
 RETURN QUERY
 WITH known AS (
  SELECT o.tenant_id, o.source_id, o.observation_id, o.object_id, o.revision_id, o.kind,
   o.digest, o.source_effective_at, o.observed_at, o.recorded_at, o.ingest_seq, o.supersedes
  FROM living.observations o
  WHERE o.tenant_id=t AND o.source_id=s AND o.recorded_at<=k),
 picked AS (
  (SELECT DISTINCT ON (q.object_id) q.*, false AS effective_unknown
   FROM known q
   WHERE q.kind='OBSERVED' AND q.source_effective_at IS NOT NULL AND q.source_effective_at<=v
   ORDER BY q.object_id,q.source_effective_at DESC,q.ingest_seq DESC)
  UNION ALL
  (SELECT DISTINCT ON (q.object_id) q.*, true AS effective_unknown
   FROM known q
   WHERE q.kind='OBSERVED' AND q.source_effective_at IS NULL
   ORDER BY q.object_id,q.ingest_seq DESC))
 SELECT p.tenant_id, p.source_id, p.observation_id, p.object_id, p.revision_id, p.kind, p.digest,
  p.source_effective_at, p.observed_at, p.recorded_at, p.ingest_seq, p.supersedes,
  p.effective_unknown,
  EXISTS(SELECT 1 FROM known rv WHERE rv.object_id=p.object_id AND rv.kind='ATTESTATION_REVOKED'
   AND rv.ingest_seq>p.ingest_seq) AS revoked
 FROM picked p
 ORDER BY p.object_id, p.effective_unknown;
END $fn$;
-- revoked: an ATTESTATION_REVOKED row for the same object recorded (<=k) after the returned row;
-- it applies in every slice regardless of source_effective_at. provenance is never returned here.

-- Idempotent ingest: same revision + same content returns the existing row; any divergence raises.
CREATE OR REPLACE FUNCTION living.ingest_observation(
 t text,s text,p_observation_id uuid,p_object_id text,p_revision_id uuid,p_kind text,
 p_digest text,p_source_effective_at timestamptz,p_observed_at timestamptz,
 p_supersedes uuid DEFAULT NULL,p_provenance jsonb DEFAULT '{}'::jsonb
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE st text; ex living.observations%ROWTYPE;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF p_observation_id IS NULL OR p_object_id IS NULL OR p_object_id='' OR p_revision_id IS NULL
  OR p_kind IS NULL OR p_observed_at IS NULL OR p_provenance IS NULL THEN
  RAISE EXCEPTION 'INVALID_OBSERVATION';
 END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 -- Per-(tenant,source) ingest-order lock, held to commit: ingest_seq, recorded_at and commit
 -- order agree for a source, so "known at k" is a true prefix of the ingest_seq order.
 PERFORM pg_advisory_xact_lock(hashtextextended('ingest:'||t||'/'||s,0));
 SELECT * INTO ex FROM living.observations
  WHERE tenant_id=t AND source_id=s AND revision_id=p_revision_id;
 IF FOUND THEN
  IF ex.digest IS DISTINCT FROM p_digest THEN RAISE EXCEPTION 'CONFLICTING_DIGEST'; END IF;
  IF ex.object_id IS DISTINCT FROM p_object_id OR ex.kind IS DISTINCT FROM p_kind THEN
   RAISE EXCEPTION 'REVISION_REUSED';
  END IF;
  IF ex.source_effective_at IS DISTINCT FROM p_source_effective_at
   OR ex.observed_at IS DISTINCT FROM p_observed_at
   OR ex.supersedes IS DISTINCT FROM p_supersedes
   OR ex.provenance IS DISTINCT FROM p_provenance THEN
   RAISE EXCEPTION 'CONFLICTING_OBSERVATION';
  END IF;
  RETURN ex.observation_id;
 END IF;
 INSERT INTO living.observations(tenant_id,source_id,observation_id,object_id,revision_id,kind,
  digest,source_effective_at,observed_at,supersedes,provenance)
 VALUES(t,s,p_observation_id,p_object_id,p_revision_id,p_kind,p_digest,
  p_source_effective_at,p_observed_at,p_supersedes,p_provenance);
 RETURN p_observation_id;
END $fn$;

-- Creation helpers (idempotent).
CREATE OR REPLACE FUNCTION living.create_head(t text,s text,m text) RETURNS bigint
LANGUAGE plpgsql AS $fn$
DECLARE st text; v bigint;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF m IS NULL OR m='' THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 INSERT INTO living.accepted_heads(tenant_id,source_id,model_key) VALUES(t,s,m)
  ON CONFLICT DO NOTHING;
 SELECT version INTO v FROM living.accepted_heads WHERE tenant_id=t AND source_id=s AND model_key=m;
 RETURN v;
END $fn$;
CREATE OR REPLACE FUNCTION living.create_cursor(t text,s text,c text,initial_cursor text)
RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE st text; ep bigint; v bigint;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF c IS NULL OR c='' OR initial_cursor IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 SELECT status,scope_epoch INTO st,ep FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 INSERT INTO living.cursors(tenant_id,source_id,connection_id,cursor_value,scope_epoch)
  VALUES(t,s,c,initial_cursor,ep) ON CONFLICT DO NOTHING;
 SELECT version INTO v FROM living.cursors WHERE tenant_id=t AND source_id=s AND connection_id=c;
 RETURN v;
END $fn$;

-- Idempotent enqueue: same idempotency_key + same request_digest returns the existing job.
CREATE OR REPLACE FUNCTION living.enqueue_job(
 t text,s text,p_job_id uuid,p_job_kind text,p_request_digest text,p_idempotency_key text,
 p_payload jsonb DEFAULT '{}'::jsonb
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE st text; ep bigint; ex living.jobs%ROWTYPE;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF p_job_id IS NULL OR p_job_kind IS NULL OR p_job_kind='' OR p_idempotency_key IS NULL
  OR p_idempotency_key='' OR p_payload IS NULL
  OR p_request_digest IS NULL OR p_request_digest !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'INVALID_JOB';
 END IF;
 SELECT status,scope_epoch INTO st,ep FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(t||'/'||s||'/'||p_idempotency_key,0));
 SELECT * INTO ex FROM living.jobs
  WHERE tenant_id=t AND source_id=s AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
  IF ex.request_digest IS DISTINCT FROM p_request_digest THEN
   RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
  END IF;
  -- A job queued under an older scope epoch is never replayed as current work.
  IF ex.scope_epoch IS DISTINCT FROM ep THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
  RETURN ex.job_id;
 END IF;
 INSERT INTO living.jobs(tenant_id,source_id,job_id,job_kind,request_digest,idempotency_key,
  scope_epoch,payload)
 VALUES(t,s,p_job_id,p_job_kind,p_request_digest,p_idempotency_key,ep,p_payload);
 RETURN p_job_id;
END $fn$;

-- Draft promotion (basic). The approver is the authenticated caller, never a parameter.
-- 003 replaces this (same signature) with the attestation-backed, role-restricted version.
CREATE OR REPLACE FUNCTION living.promote_head(
 t text,s text,m text,expected_version bigint,new_revision uuid,
 acceptance uuid,evidence text
) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE new_version bigint; approver text;
BEGIN
 PERFORM living.assert_scope(t,s);
 approver := living.caller_role();
 IF approver IS NULL OR length(approver)=0 OR evidence IS NULL OR length(evidence)=0
  OR new_revision IS NULL OR acceptance IS NULL OR expected_version IS NULL OR m IS NULL THEN
  RAISE EXCEPTION 'INDEPENDENT_APPROVAL_REQUIRED';
 END IF;
 PERFORM set_config('living.promoting','on',true);
 UPDATE living.accepted_heads SET revision_id=new_revision,version=version+1,
  updated_at=clock_timestamp()
 WHERE tenant_id=t AND source_id=s AND model_key=m AND version=expected_version
 RETURNING version INTO new_version;
 PERFORM set_config('living.promoting','off',true);
 IF new_version IS NULL THEN RAISE EXCEPTION 'STALE_ACCEPTED_HEAD'; END IF;
 INSERT INTO living.acceptance_events(
 tenant_id,source_id,acceptance_id,model_key,from_version,to_version,
 accepted_revision,approver_subject,independent_evidence_ref)
 VALUES(t,s,acceptance,m,expected_version,new_version,new_revision,approver,evidence);
 RETURN new_version;
END $fn$;

-- All tenant-owned tables require trusted server-side per-transaction scope.
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'sources','observations','accepted_heads','acceptance_events','jobs','cursors','outbox'
 ] LOOP
  EXECUTE format('ALTER TABLE living.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE living.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON living.%I',tbl);
  EXECUTE format(
   'CREATE POLICY tenant_scope ON living.%I USING (tenant_id = nullif(current_setting(''living.tenant_id'',true),'''')) WITH CHECK (tenant_id = nullif(current_setting(''living.tenant_id'',true),''''))',tbl);
 END LOOP;
END $fn$;
-- No permission grants to existing R1 runtime roles. Roles/grants live in 003.
$body$;
END IF;
END $mig$;
COMMIT;
