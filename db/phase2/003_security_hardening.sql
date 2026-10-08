-- R2/G1 security hardening: living_* roles, grants, role_scope-backed RLS, definer APIs.
-- Touches only the living schema and the four living_* roles. Apply ONLY to a verified
-- disposable PostgreSQL database; the applier sets living.migration_checksum first (see 001).
-- Applier must be superuser or hold CREATEROLE (roles are created NOLOGIN, NOBYPASSRLS).
-- Known limits: GUC names are free-form, so a runtime role can SET its own living.* values,
-- but every policy and definer API also joins the caller to role_scope, so the effective
-- reach is limited to the scopes granted to that role. Default privileges are changed only
-- for living_owner; functions created later by another role need their own REVOKE.
-- Per-person identity: independence in promote_head is checked on ROLE MEMBERSHIP, not on the
-- role name. Give every human/service its OWN NOLOGIN-or-login role that is a member of exactly
-- one duty role (living_worker XOR living_promoter XOR living_publisher). A login that is a member
-- of both living_worker and living_promoter is rejected as an approver (APPROVER_NOT_INDEPENDENT),
-- and an approver that equals / is a member of / contains the attestation observer or proposer
-- role is rejected too. A proposer that is free text and not a role is compared by name only.
-- Whole-file guard: re-running this file (or 001/002 after it) never changes the hardened state.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('003', ARRAY['001','002']) THEN
EXECUTE $body$

DO $fn$
DECLARE r text;
BEGIN
 FOREACH r IN ARRAY ARRAY['living_owner','living_worker','living_reader','living_promoter',
                          'living_publisher'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE',r);
  ELSIF EXISTS(SELECT 1 FROM pg_catalog.pg_roles
               WHERE rolname=r AND (rolsuper OR rolbypassrls OR rolcanlogin)) THEN
   RAISE EXCEPTION 'LIVING_ROLE_UNSAFE: %',r;
  END IF;
 END LOOP;
 -- A non-superuser applier needs membership of living_owner to transfer ownership.
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=current_user AND rolsuper)
  AND NOT pg_catalog.pg_has_role(current_user,'living_owner','MEMBER') THEN
  EXECUTE format('GRANT living_owner TO %I',current_user);
 END IF;
END $fn$;

-- Grant map: which (tenant, source[, company]) a role may enter through set_scope().
CREATE TABLE IF NOT EXISTS living.role_scope(
 role_name text NOT NULL CHECK(length(role_name)>0),
 tenant_id text NOT NULL, source_id text NOT NULL, company_id text,
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources
);
CREATE UNIQUE INDEX IF NOT EXISTS role_scope_uniq
 ON living.role_scope(role_name,tenant_id,source_id,coalesce(company_id,''));
-- Independent evidence for promotions. observer = authenticated recorder; proposer = who proposed.
CREATE TABLE IF NOT EXISTS living.attestations(
 tenant_id text NOT NULL, source_id text NOT NULL, attestation_id uuid NOT NULL,
 revision_id uuid NOT NULL, proposer_subject text NOT NULL CHECK(length(proposer_subject)>0),
 observer_subject text NOT NULL CHECK(length(observer_subject)>0),
 evidence_ref text NOT NULL CHECK(length(evidence_ref)>0),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,attestation_id),
 UNIQUE(tenant_id,source_id,revision_id,evidence_ref),
 FOREIGN KEY(tenant_id,source_id,revision_id)
 REFERENCES living.observations(tenant_id,source_id,revision_id)
);
DROP TRIGGER IF EXISTS attestations_immutable ON living.attestations;
CREATE TRIGGER attestations_immutable BEFORE UPDATE OR DELETE ON living.attestations
 FOR EACH ROW EXECUTE FUNCTION living.reject_immutable_mutation();
DROP TRIGGER IF EXISTS attestations_no_truncate ON living.attestations;
CREATE TRIGGER attestations_no_truncate BEFORE TRUNCATE ON living.attestations
 FOR EACH STATEMENT EXECUTE FUNCTION living.reject_immutable_mutation();

-- RLS helpers (SECURITY INVOKER: evaluated as the reading role, join on current_user).
CREATE OR REPLACE FUNCTION living.row_in_scope(t text, s text, comp text DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE AS $fn$
 SELECT t IS NOT NULL AND s IS NOT NULL
  AND t = nullif(current_setting('living.tenant_id',true),'')
  AND s = nullif(current_setting('living.source_id',true),'')
  AND EXISTS(SELECT 1 FROM living.role_scope rs
   WHERE rs.tenant_id=t AND rs.source_id=s
    AND pg_has_role(current_user, rs.role_name::name, 'USAGE')
    AND (rs.company_id IS NULL
         OR (rs.company_id = nullif(current_setting('living.company_id',true),'')
             AND (comp IS NULL OR comp = rs.company_id))))
$fn$;
CREATE OR REPLACE FUNCTION living.tenant_in_scope(t text) RETURNS boolean
LANGUAGE sql STABLE AS $fn$
 SELECT t IS NOT NULL AND t = nullif(current_setting('living.tenant_id',true),'')
  AND EXISTS(SELECT 1 FROM living.role_scope rs
   WHERE rs.tenant_id=t AND pg_has_role(current_user, rs.role_name::name, 'USAGE'))
$fn$;

-- Context entry point: the ONLY supported way to set scope. Validates the caller's grant,
-- source status and epoch; settings are transaction-local (set_config ..., true == SET LOCAL).
CREATE OR REPLACE FUNCTION living.set_scope(t text, s text, p_company text DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE who text; src_company text; src_status text; src_epoch bigint;
BEGIN
 IF t IS NULL OR s IS NULL OR t='' OR s='' THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 who := living.caller_role();
 SELECT company_id,status,scope_epoch INTO src_company,src_status,src_epoch
  FROM living.sources WHERE tenant_id=t AND source_id=s;
 IF NOT FOUND THEN RAISE EXCEPTION 'SCOPE_NOT_GRANTED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM living.role_scope rs
   WHERE rs.tenant_id=t AND rs.source_id=s
    AND pg_has_role(who::name, rs.role_name::name, 'USAGE')
    AND (rs.company_id IS NULL OR rs.company_id IS NOT DISTINCT FROM p_company)
    AND (src_company IS NULL OR rs.company_id IS NULL OR rs.company_id = src_company)) THEN
  RAISE EXCEPTION 'SCOPE_NOT_GRANTED';
 END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 PERFORM set_config('living.tenant_id',t,true);
 PERFORM set_config('living.source_id',s,true);
 PERFORM set_config('living.company_id',coalesce(p_company,''),true);
 PERFORM set_config('living.scope_epoch',src_epoch::text,true);
 RETURN src_epoch;
END $fn$;

-- Replaces the 001 GUC-only guard: GUCs must match the arguments, the caller must hold a grant,
-- and the epoch captured by set_scope must still be the source's current epoch.
CREATE OR REPLACE FUNCTION living.assert_scope(t text, s text) RETURNS void
LANGUAGE plpgsql STABLE AS $fn$
DECLARE who text; src_status text; src_epoch bigint;
BEGIN
 IF t IS NULL OR s IS NULL
  OR t IS DISTINCT FROM nullif(current_setting('living.tenant_id', true), '')
  OR s IS DISTINCT FROM nullif(current_setting('living.source_id', true), '') THEN
  RAISE EXCEPTION 'SCOPE_NOT_SET';
 END IF;
 who := living.caller_role();
 IF NOT EXISTS(SELECT 1 FROM living.role_scope rs
   WHERE rs.tenant_id=t AND rs.source_id=s
    AND pg_has_role(who::name, rs.role_name::name, 'USAGE')
    AND (rs.company_id IS NULL
         OR rs.company_id = nullif(current_setting('living.company_id',true),''))) THEN
  RAISE EXCEPTION 'SCOPE_NOT_GRANTED';
 END IF;
 SELECT status,scope_epoch INTO src_status,src_epoch FROM living.sources
  WHERE tenant_id=t AND source_id=s;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE'
  OR src_epoch::text IS DISTINCT FROM nullif(current_setting('living.scope_epoch',true),'') THEN
  RAISE EXCEPTION 'SCOPE_REVOKED';
 END IF;
END $fn$;

-- Head changes are accepted only from definer code running as living_owner.
CREATE OR REPLACE FUNCTION living.accepted_heads_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.revision_id IS NOT NULL OR NEW.version<>0 THEN RAISE EXCEPTION 'HEAD_CHANGE_FORBIDDEN'; END IF;
 ELSIF NEW.revision_id IS DISTINCT FROM OLD.revision_id OR NEW.version IS DISTINCT FROM OLD.version THEN
  IF current_user <> 'living_owner'
   OR coalesce(current_setting('living.promoting', true),'') <> 'on' THEN
   RAISE EXCEPTION 'HEAD_CHANGE_FORBIDDEN';
  END IF;
 END IF;
 RETURN NEW;
END $fn$;

CREATE OR REPLACE FUNCTION living.record_attestation(
 t text, s text, p_attestation_id uuid, p_revision uuid, p_proposer text, p_evidence text
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE st text; observer text;
BEGIN
 PERFORM living.assert_scope(t,s);
 observer := living.caller_role();
 IF p_attestation_id IS NULL OR p_revision IS NULL OR p_proposer IS NULL OR p_proposer=''
  OR p_evidence IS NULL OR p_evidence='' THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 INSERT INTO living.attestations(tenant_id,source_id,attestation_id,revision_id,
  proposer_subject,observer_subject,evidence_ref)
 VALUES(t,s,p_attestation_id,p_revision,p_proposer,observer,p_evidence)
 ON CONFLICT DO NOTHING;
 IF NOT FOUND AND NOT EXISTS(SELECT 1 FROM living.attestations
   WHERE tenant_id=t AND source_id=s AND attestation_id=p_attestation_id
    AND revision_id=p_revision AND proposer_subject=p_proposer
    AND observer_subject=observer AND evidence_ref=p_evidence) THEN
  RAISE EXCEPTION 'CONFLICTING_ATTESTATION';
 END IF;
 RETURN p_attestation_id;
END $fn$;

-- Final promote_head: approver = authenticated caller (never a parameter), must be a
-- living_promoter member, must differ from the attestation observer and proposer, and the
-- evidence row must exist for the exact revision. Lock order: source -> head.
CREATE OR REPLACE FUNCTION living.promote_head(
 t text,s text,m text,expected_version bigint,new_revision uuid,
 acceptance uuid,evidence text
) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE new_version bigint; approver text; st text; obs text; prop text; rev_kind text;
 ev living.acceptance_events%ROWTYPE; sess_super boolean;
BEGIN
 PERFORM living.assert_scope(t,s);
 approver := living.caller_role();
 IF approver IS NULL OR approver='' OR evidence IS NULL OR evidence=''
  OR new_revision IS NULL OR acceptance IS NULL OR expected_version IS NULL OR m IS NULL THEN
  RAISE EXCEPTION 'INDEPENDENT_APPROVAL_REQUIRED';
 END IF;
 IF NOT pg_has_role(approver::name,'living_promoter','USAGE') THEN
  RAISE EXCEPTION 'NOT_A_PROMOTER';
 END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 -- Replay: same acceptance_id with identical arguments returns the recorded version.
 SELECT * INTO ev FROM living.acceptance_events
  WHERE tenant_id=t AND source_id=s AND acceptance_id=acceptance;
 IF FOUND THEN
  IF ev.model_key=m AND ev.from_version=expected_version AND ev.accepted_revision=new_revision
   AND ev.approver_subject=approver AND ev.independent_evidence_ref=evidence THEN
   RETURN ev.to_version;
  END IF;
  RAISE EXCEPTION 'ACCEPTANCE_ID_REUSED';
 END IF;
 -- One identity must not hold both duties (e.g. a login in living_worker AND living_promoter
 -- that reaches this role via SET ROLE): check the approver role and the session login.
 -- (A superuser login is skipped for the session-level test only: pg_has_role is always true for it.)
 SELECT coalesce(rolsuper,false) INTO sess_super FROM pg_catalog.pg_roles WHERE rolname=session_user;
 IF pg_has_role(approver::name,'living_worker','MEMBER')
  OR (NOT sess_super AND pg_has_role(session_user,'living_worker','MEMBER')) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 SELECT kind INTO rev_kind FROM living.observations
  WHERE tenant_id=t AND source_id=s AND revision_id=new_revision;
 IF rev_kind IS DISTINCT FROM 'OBSERVED' THEN RAISE EXCEPTION 'REVISION_NOT_OBSERVED'; END IF;
 SELECT observer_subject,proposer_subject INTO obs,prop FROM living.attestations
  WHERE tenant_id=t AND source_id=s AND revision_id=new_revision AND evidence_ref=evidence;
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_NOT_FOUND'; END IF;
 IF approver IS NOT DISTINCT FROM obs OR approver IS NOT DISTINCT FROM prop
  OR (NOT sess_super AND (session_user::text IS NOT DISTINCT FROM obs
                          OR session_user::text IS NOT DISTINCT FROM prop))
  OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r
    WHERE r.rolname IN (obs,prop)
     AND (pg_has_role(approver::name, r.oid, 'MEMBER')
          OR pg_has_role(r.oid, approver::name, 'MEMBER')
          OR (NOT sess_super AND pg_has_role(session_user, r.oid, 'MEMBER')))) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
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

-- Owner-only administration. EXECUTE is granted to nobody but living_owner (and its members);
-- each function also checks the caller, so a stray GRANT alone does not open it.
CREATE OR REPLACE FUNCTION living.add_role_scope(
 p_role text, t text, s text, p_company text DEFAULT NULL
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NOT pg_has_role(living.caller_role()::name,'living_owner','USAGE') THEN
  RAISE EXCEPTION 'NOT_OWNER';
 END IF;
 IF p_role IS NULL OR p_role='' OR t IS NULL OR s IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_role) THEN
  RAISE EXCEPTION 'ROLE_NOT_FOUND';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM living.sources WHERE tenant_id=t AND source_id=s) THEN
  RAISE EXCEPTION 'SOURCE_NOT_FOUND';
 END IF;
 INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id)
  VALUES(p_role,t,s,p_company) ON CONFLICT DO NOTHING;
END $fn$;

-- Re-point cursors and PENDING jobs of a source at its current scope_epoch after an epoch bump.
-- Runs under the source lock; RUNNING jobs are left alone (they fail their fence check).
CREATE OR REPLACE FUNCTION living.rebase_scope(t text, s text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ep bigint; st text; n_cur integer; n_job integer;
BEGIN
 IF NOT pg_has_role(living.caller_role()::name,'living_owner','USAGE') THEN
  RAISE EXCEPTION 'NOT_OWNER';
 END IF;
 IF t IS NULL OR s IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 SELECT status,scope_epoch INTO st,ep FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 UPDATE living.cursors SET scope_epoch=ep
  WHERE tenant_id=t AND source_id=s AND scope_epoch IS DISTINCT FROM ep;
 GET DIAGNOSTICS n_cur = ROW_COUNT;
 UPDATE living.jobs SET scope_epoch=ep
  WHERE tenant_id=t AND source_id=s AND state='PENDING' AND scope_epoch IS DISTINCT FROM ep;
 GET DIAGNOSTICS n_job = ROW_COUNT;
 RETURN n_cur + n_job;
END $fn$;

-- Outbox delivery: lease columns, guarded transitions, claim / finish APIs for living_publisher.
ALTER TABLE living.outbox ADD COLUMN IF NOT EXISTS lease_owner text;
ALTER TABLE living.outbox ADD COLUMN IF NOT EXISTS lease_until timestamptz;
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
 IF OLD.status IN ('DELIVERED','FAILED') AND NEW.status IS DISTINCT FROM OLD.status THEN
  RAISE EXCEPTION 'OUTBOX_INVALID_TRANSITION';
 END IF;
 IF NEW.attempts < OLD.attempts THEN RAISE EXCEPTION 'OUTBOX_INVALID_TRANSITION'; END IF;
 RETURN NEW;
END $fn$;

-- Claims up to p_limit PENDING events (FOR UPDATE SKIP LOCKED, seq order) with a lease and
-- attempts+1. Events whose lease expired become claimable again; exhausted ones turn FAILED.
-- Source lock is FOR SHARE here ONLY (many publishers in parallel); this API never upgrades it,
-- so use it as the only living API in its transaction.
CREATE OR REPLACE FUNCTION living.claim_outbox(
 t text, s text, p_publisher text, p_limit integer, p_lease_seconds integer,
 p_max_attempts integer DEFAULT 5
) RETURNS SETOF living.outbox LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE st text;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF p_publisher IS NULL OR p_publisher='' OR p_limit IS NULL OR p_limit<1 OR p_limit>1000
  OR p_lease_seconds IS NULL OR p_lease_seconds<1 OR p_lease_seconds>300
  OR p_max_attempts IS NULL OR p_max_attempts<1 OR p_max_attempts>20 THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 UPDATE living.outbox SET status='FAILED', lease_owner=NULL, lease_until=NULL
  WHERE tenant_id=t AND source_id=s AND status='PENDING' AND attempts>=p_max_attempts
   AND (lease_until IS NULL OR lease_until<=clock_timestamp());
 RETURN QUERY
 WITH c AS (
  SELECT ob.tenant_id, ob.source_id, ob.connection_id, ob.event_id FROM living.outbox ob
  WHERE ob.tenant_id=t AND ob.source_id=s AND ob.status='PENDING'
   AND ob.attempts<p_max_attempts
   AND (ob.lease_until IS NULL OR ob.lease_until<=clock_timestamp())
  ORDER BY ob.seq LIMIT p_limit FOR UPDATE SKIP LOCKED)
 UPDATE living.outbox o SET attempts=o.attempts+1, lease_owner=p_publisher,
  lease_until=clock_timestamp()+make_interval(secs=>p_lease_seconds)
 FROM c
 WHERE o.tenant_id=c.tenant_id AND o.source_id=c.source_id
  AND o.connection_id=c.connection_id AND o.event_id=c.event_id
 RETURNING o.*;
END $fn$;

-- Completes one claimed event: delivered -> DELIVERED; failed -> PENDING again (or FAILED once
-- attempts reach p_max_attempts). Requires the live lease held by p_publisher.
CREATE OR REPLACE FUNCTION living.finish_outbox(
 t text, s text, c text, p_event_id text, p_publisher text, p_delivered boolean,
 p_max_attempts integer DEFAULT 5
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE st text; ob living.outbox%ROWTYPE;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF c IS NULL OR p_event_id IS NULL OR p_publisher IS NULL OR p_delivered IS NULL
  OR p_max_attempts IS NULL OR p_max_attempts<1 THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 SELECT * INTO ob FROM living.outbox
  WHERE tenant_id=t AND source_id=s AND connection_id=c AND event_id=p_event_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'OUTBOX_EVENT_NOT_FOUND'; END IF;
 IF ob.status IS DISTINCT FROM 'PENDING' THEN RAISE EXCEPTION 'OUTBOX_INVALID_TRANSITION'; END IF;
 IF ob.lease_owner IS DISTINCT FROM p_publisher OR ob.lease_until IS NULL
  OR ob.lease_until<=clock_timestamp() THEN
  RAISE EXCEPTION 'STALE_OUTBOX_LEASE';
 END IF;
 UPDATE living.outbox SET lease_owner=NULL, lease_until=NULL,
  status=CASE WHEN p_delivered THEN 'DELIVERED'
              WHEN attempts>=p_max_attempts THEN 'FAILED' ELSE 'PENDING' END
 WHERE tenant_id=t AND source_id=s AND connection_id=c AND event_id=p_event_id;
END $fn$;

-- Definer APIs run as living_owner with a pinned search_path.
DO $fn$
DECLARE f record;
BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='living' AND p.proname IN (
   'set_scope','assert_scope','enqueue_job','acquire_job','renew_lease','finish_job',
   'reap_expired_jobs','commit_cursor_page','ingest_observation','create_cursor','create_head',
   'promote_head','record_attestation','add_role_scope','rebase_scope','claim_outbox',
   'finish_outbox')
 LOOP
  EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp',f.sig);
 END LOOP;
END $fn$;

-- Ownership of every living object moves to the non-login, non-bypass owner role.
DO $fn$
DECLARE o record;
BEGIN
 -- The schema itself stays with the applier (a schema owner change needs CREATE on the
 -- database); living_owner only needs USAGE+CREATE on the schema to own its objects.
 EXECUTE 'GRANT USAGE, CREATE ON SCHEMA living TO living_owner';
 FOR o IN SELECT c.oid::regclass AS rel FROM pg_catalog.pg_class c
   JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='living' AND c.relkind IN ('r','p')
 LOOP EXECUTE format('ALTER TABLE %s OWNER TO living_owner',o.rel); END LOOP;
 FOR o IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='living'
 LOOP EXECUTE format('ALTER FUNCTION %s OWNER TO living_owner',o.sig); END LOOP;
END $fn$;

-- Privilege baseline: nothing for PUBLIC.
REVOKE ALL ON SCHEMA living FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA living FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA living FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA living FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE living_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE living_owner IN SCHEMA living REVOKE ALL ON TABLES FROM PUBLIC;

GRANT USAGE ON SCHEMA living TO living_worker, living_reader, living_promoter, living_publisher;
-- role_scope and the owner-only admin APIs: no direct DML for anybody but living_owner.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON living.role_scope
 FROM PUBLIC, living_worker, living_reader, living_promoter, living_publisher;
REVOKE EXECUTE ON FUNCTION living.add_role_scope(text,text,text,text),
 living.rebase_scope(text,text)
 FROM PUBLIC, living_worker, living_reader, living_promoter, living_publisher;
GRANT EXECUTE ON FUNCTION living.add_role_scope(text,text,text,text),
 living.rebase_scope(text,text) TO living_owner;
-- Runtime roles get read access only (RLS-filtered); every write goes through definer functions.
GRANT SELECT ON living.tenants, living.sources, living.accepted_heads, living.acceptance_events,
 living.role_scope TO living_worker, living_reader, living_promoter;
GRANT SELECT ON living.tenants, living.sources, living.role_scope TO living_publisher;
GRANT EXECUTE ON FUNCTION living.caller_role(), living.row_in_scope(text,text,text),
 living.tenant_in_scope(text), living.set_scope(text,text,text),
 living.claim_outbox(text,text,text,integer,integer,integer),
 living.finish_outbox(text,text,text,text,text,boolean,integer)
 TO living_publisher;
GRANT SELECT ON living.jobs, living.cursors, living.outbox, living.attestations,
 living.observations TO living_worker;
GRANT SELECT ON living.attestations TO living_promoter;
-- Readers/promoters never see provenance (column-level grant).
GRANT SELECT(tenant_id,source_id,observation_id,object_id,revision_id,kind,digest,
 source_effective_at,observed_at,recorded_at,ingest_seq,supersedes)
 ON living.observations TO living_reader, living_promoter;

GRANT EXECUTE ON FUNCTION living.caller_role(), living.row_in_scope(text,text,text),
 living.tenant_in_scope(text), living.set_scope(text,text,text),
 living.as_known_at(text,text,timestamptz),
 living.as_effective_at(text,text,timestamptz,timestamptz)
 TO living_worker, living_reader, living_promoter;
GRANT EXECUTE ON FUNCTION
 living.enqueue_job(text,text,uuid,text,text,text,jsonb),
 living.reap_expired_jobs(text,text),
 living.acquire_job(text,text,uuid,text,integer),
 living.renew_lease(text,text,uuid,text,bigint,integer),
 living.finish_job(text,text,uuid,text,bigint,text,text),
 living.commit_cursor_page(text,text,text,uuid,text,bigint,text,bigint,bigint,text,jsonb),
 living.ingest_observation(text,text,uuid,text,uuid,text,text,timestamptz,timestamptz,uuid,jsonb),
 living.create_cursor(text,text,text,text),
 living.record_attestation(text,text,uuid,uuid,text,text)
 TO living_worker;
GRANT EXECUTE ON FUNCTION
 living.promote_head(text,text,text,bigint,uuid,uuid,text),
 living.create_head(text,text,text)
 TO living_promoter;

-- RLS: tenants and every scoped table; owner role keeps full access for definer code.
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'tenants','sources','observations','accepted_heads','acceptance_events','jobs','cursors',
  'outbox','attestations','role_scope'
 ] LOOP
  EXECUTE format('ALTER TABLE living.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE living.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON living.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS scope_isolation ON living.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS owner_all ON living.%I',tbl);
  EXECUTE format('CREATE POLICY owner_all ON living.%I FOR ALL TO living_owner USING (true) WITH CHECK (true)',tbl);
 END LOOP;
 CREATE POLICY scope_isolation ON living.tenants FOR ALL
  USING (living.tenant_in_scope(tenant_id)) WITH CHECK (living.tenant_in_scope(tenant_id));
 CREATE POLICY scope_isolation ON living.sources FOR ALL
  USING (living.row_in_scope(tenant_id,source_id,company_id))
  WITH CHECK (living.row_in_scope(tenant_id,source_id,company_id));
 FOREACH tbl IN ARRAY ARRAY[
  'observations','accepted_heads','acceptance_events','jobs','cursors','outbox','attestations'
 ] LOOP
  EXECUTE format('CREATE POLICY scope_isolation ON living.%I FOR ALL USING (living.row_in_scope(tenant_id,source_id)) WITH CHECK (living.row_in_scope(tenant_id,source_id))',tbl);
 END LOOP;
 -- A role sees only its own grants.
 CREATE POLICY scope_isolation ON living.role_scope FOR SELECT
  USING (pg_has_role(current_user, role_name::name, 'USAGE'));
END $fn$;
$body$;
END IF;
END $mig$;
COMMIT;
