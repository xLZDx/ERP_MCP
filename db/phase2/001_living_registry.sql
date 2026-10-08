-- R2/G1: isolated schema. Apply ONLY to a verified disposable PostgreSQL database.
-- Migration owner must be distinct from runtime roles. Session scope is set by a
-- trusted server after OAuth and ACL checks, never by client-provided SQL.
BEGIN;
CREATE SCHEMA IF NOT EXISTS living;
CREATE TABLE IF NOT EXISTS living.tenants(
 tenant_id text PRIMARY KEY CHECK(length(tenant_id)>0)
);
CREATE TABLE IF NOT EXISTS living.sources(
 tenant_id text NOT NULL REFERENCES living.tenants(tenant_id),
 source_id text NOT NULL CHECK(length(source_id)>0),
 PRIMARY KEY(tenant_id,source_id)
);
CREATE TABLE IF NOT EXISTS living.observations(
 tenant_id text NOT NULL, source_id text NOT NULL,
 observation_id uuid NOT NULL, object_id text NOT NULL,
 revision_id text NOT NULL, kind text NOT NULL
 CHECK(kind IN ('OBSERVED','SOURCE_UNAVAILABLE','GAP','ATTESTATION_REVOKED')),
 digest text, source_effective_at timestamptz,
 observed_at timestamptz NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 supersedes uuid, provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY(tenant_id,source_id,observation_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 FOREIGN KEY(tenant_id,source_id,supersedes)
 REFERENCES living.observations(tenant_id,source_id,observation_id),
 CHECK(observed_at<=recorded_at),
 CHECK(kind<>'OBSERVED' OR (digest ~ '^[a-f0-9]{64}$'))
);
CREATE INDEX IF NOT EXISTS observations_known_idx ON living.observations
 (tenant_id,source_id,recorded_at,observation_id);
CREATE INDEX IF NOT EXISTS observations_effective_idx ON living.observations
 (tenant_id,source_id,object_id,source_effective_at,recorded_at)
 WHERE source_effective_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS living.accepted_heads(
 tenant_id text NOT NULL,source_id text NOT NULL,model_key text NOT NULL,
 revision_id uuid, version bigint NOT NULL DEFAULT 0 CHECK(version>=0),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,model_key),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources
);
CREATE TABLE IF NOT EXISTS living.acceptance_events(
 tenant_id text NOT NULL,source_id text NOT NULL,acceptance_id uuid NOT NULL,
 model_key text NOT NULL,from_version bigint NOT NULL,to_version bigint NOT NULL,
 accepted_revision uuid NOT NULL,approver_subject text NOT NULL,
 independent_evidence_ref text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,acceptance_id),
 FOREIGN KEY(tenant_id,source_id,model_key)
 REFERENCES living.accepted_heads(tenant_id,source_id,model_key),
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
 payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY(tenant_id,source_id,job_id),
 UNIQUE(tenant_id,source_id,idempotency_key),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 CHECK((lease_owner IS NULL AND lease_until IS NULL)
    OR (lease_owner IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS living.cursors(
 tenant_id text NOT NULL,source_id text NOT NULL,connection_id text NOT NULL,
 cursor_value text NOT NULL,version bigint NOT NULL DEFAULT 0,
 scope_epoch bigint NOT NULL CHECK(scope_epoch>=0),
 PRIMARY KEY(tenant_id,source_id,connection_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources
);
CREATE TABLE IF NOT EXISTS living.outbox(
 tenant_id text NOT NULL,source_id text NOT NULL,connection_id text NOT NULL,
 event_id text NOT NULL, event_digest text NOT NULL CHECK(event_digest ~ '^[a-f0-9]{64}$'),
 content jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,connection_id,event_id),
 FOREIGN KEY(tenant_id,source_id,connection_id)
 REFERENCES living.cursors(tenant_id,source_id,connection_id)
);
CREATE OR REPLACE FUNCTION living.reject_immutable_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_LEDGER'; END $$;
DROP TRIGGER IF EXISTS observations_immutable ON living.observations;
CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE ON living.observations
 FOR EACH ROW EXECUTE FUNCTION living.reject_immutable_mutation();
DROP TRIGGER IF EXISTS acceptance_immutable ON living.acceptance_events;
CREATE TRIGGER acceptance_immutable BEFORE UPDATE OR DELETE ON living.acceptance_events
 FOR EACH ROW EXECUTE FUNCTION living.reject_immutable_mutation();
CREATE OR REPLACE FUNCTION living.as_known_at(t text,s text,k timestamptz)
RETURNS SETOF living.observations LANGUAGE sql STABLE AS $$
 SELECT DISTINCT ON (object_id) *
 FROM living.observations
 WHERE tenant_id=t AND source_id=s AND recorded_at<=k
 ORDER BY object_id,recorded_at DESC,observation_id DESC
$$;
CREATE OR REPLACE FUNCTION living.as_effective_at(t text,s text,v timestamptz,k timestamptz)
RETURNS SETOF living.observations LANGUAGE sql STABLE AS $$
 SELECT DISTINCT ON (object_id) *
 FROM living.observations
 WHERE tenant_id=t AND source_id=s AND recorded_at<=k
   AND source_effective_at IS NOT NULL AND source_effective_at<=v
 ORDER BY object_id,source_effective_at DESC,recorded_at DESC,observation_id DESC
$$;
CREATE OR REPLACE FUNCTION living.promote_head(
 t text,s text,m text,expected_version bigint,new_revision uuid,
 acceptance uuid,approver text,evidence text
) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE new_version bigint;
BEGIN
 IF approver IS NULL OR length(approver)=0 OR evidence IS NULL OR length(evidence)=0 THEN
  RAISE EXCEPTION 'INDEPENDENT_APPROVAL_REQUIRED';
 END IF;
 UPDATE living.accepted_heads SET revision_id=new_revision,version=version+1,
  updated_at=clock_timestamp()
 WHERE tenant_id=t AND source_id=s AND model_key=m AND version=expected_version
 RETURNING version INTO new_version;
 IF new_version IS NULL THEN RAISE EXCEPTION 'STALE_ACCEPTED_HEAD'; END IF;
 INSERT INTO living.acceptance_events(
 tenant_id,source_id,acceptance_id,model_key,from_version,to_version,
 accepted_revision,approver_subject,independent_evidence_ref)
 VALUES(t,s,acceptance,m,expected_version,new_version,new_revision,approver,evidence);
 RETURN new_version;
END $$;
-- All tenant-owned tables require trusted server-side per-transaction scope.
DO $$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'sources','observations','accepted_heads','acceptance_events','jobs','cursors','outbox'
 ] LOOP
  EXECUTE format('ALTER TABLE living.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE living.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format(
   'CREATE POLICY tenant_scope ON living.%I USING (tenant_id = nullif(current_setting(''living.tenant_id'',true),'''')) WITH CHECK (tenant_id = nullif(current_setting(''living.tenant_id'',true),''''))',tbl);
 END LOOP;
END $$;
-- No permission grants to existing R1 runtime roles. Define dedicated R2
-- least-privilege roles/grants through a separate reviewed provisioning step.
COMMIT;
