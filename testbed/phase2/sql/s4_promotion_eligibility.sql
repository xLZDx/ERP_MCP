-- S4 R2-US-016: disposable-only durable promotion eligibility foundation.
-- This is intentionally outside db/phase2 and is NOT a normal migration.
-- Manually select a dedicated s4_disposable_* database and set s4.disposable_fixture=on for this
-- psql session before applying. No schema is applied by this file or by application startup.
-- This foundation does not enable new promotions: it adds durable records, a fail-closed
-- legacy write fence, and eligibility administration. A later reviewed adapter must add the
-- atomic promotion/read-back entry point before enrolled models can be changed.

BEGIN;

DO $guard$
BEGIN
 IF current_setting('s4.disposable_fixture', true) IS DISTINCT FROM 'on'
    OR current_database() !~ '^s4_disposable_[a-z0-9_]+$' THEN
  RAISE EXCEPTION 'S4_DISPOSABLE_FIXTURE_REQUIRED';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='living_owner') THEN
  RAISE EXCEPTION 'LIVING_SCHEMA_NOT_INSTALLED';
 END IF;
END
$guard$;

CREATE TABLE living.s4_model_modes(
 tenant_id text NOT NULL,
 source_id text NOT NULL,
 model_key text NOT NULL CHECK (length(model_key)>0),
 mode text NOT NULL CHECK (mode IN ('ENROLLED','PAUSED')),
 changed_by text NOT NULL CHECK (length(changed_by)>0),
 changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,model_key),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources
);

CREATE TABLE living.s4_eligibility(
 tenant_id text NOT NULL,
 source_id text NOT NULL,
 eligibility_id uuid NOT NULL,
 company_id text NOT NULL CHECK(length(company_id)>0),
 attestation_id uuid NOT NULL,
 revision_id uuid NOT NULL,
 artifact_version text NOT NULL CHECK(length(artifact_version)>0),
 content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL CHECK(state IN ('ELIGIBLE','REVOKED')),
 registered_by text NOT NULL CHECK(length(registered_by)>0),
 registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 revoked_by text,
 revoked_at timestamptz,
 PRIMARY KEY(tenant_id,source_id,eligibility_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 FOREIGN KEY(tenant_id,source_id,attestation_id)
  REFERENCES living.attestations(tenant_id,source_id,attestation_id),
 FOREIGN KEY(tenant_id,source_id,revision_id)
  REFERENCES living.observations(tenant_id,source_id,revision_id),
 CHECK ((state='ELIGIBLE' AND revoked_by IS NULL AND revoked_at IS NULL)
     OR (state='REVOKED' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL))
);

-- This table is a companion to the existing acceptance_events key. Existing rows are
-- intentionally not backfilled: absence means historical/unverified, never exact replay.
CREATE TABLE living.s4_acceptance_fingerprints(
 tenant_id text NOT NULL,
 source_id text NOT NULL,
 acceptance_id uuid NOT NULL,
 format text NOT NULL CHECK(format='promotion-request-v1'),
 request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[a-f0-9]{64}$'),
 eligibility_id uuid NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,acceptance_id),
 FOREIGN KEY(tenant_id,source_id,acceptance_id)
  REFERENCES living.acceptance_events(tenant_id,source_id,acceptance_id),
 FOREIGN KEY(tenant_id,source_id,eligibility_id)
  REFERENCES living.s4_eligibility(tenant_id,source_id,eligibility_id)
);

-- All direct access is closed. Reads go through RLS; mutations are SECURITY DEFINER APIs.
REVOKE ALL ON living.s4_model_modes, living.s4_eligibility,
 living.s4_acceptance_fingerprints FROM PUBLIC, living_worker, living_reader,
 living_promoter, living_publisher;
ALTER TABLE living.s4_model_modes OWNER TO living_owner;
ALTER TABLE living.s4_eligibility OWNER TO living_owner;
ALTER TABLE living.s4_acceptance_fingerprints OWNER TO living_owner;
ALTER TABLE living.s4_model_modes ENABLE ROW LEVEL SECURITY;
ALTER TABLE living.s4_model_modes FORCE ROW LEVEL SECURITY;
ALTER TABLE living.s4_eligibility ENABLE ROW LEVEL SECURITY;
ALTER TABLE living.s4_eligibility FORCE ROW LEVEL SECURITY;
ALTER TABLE living.s4_acceptance_fingerprints ENABLE ROW LEVEL SECURITY;
ALTER TABLE living.s4_acceptance_fingerprints FORCE ROW LEVEL SECURITY;
CREATE POLICY s4_owner_all ON living.s4_model_modes FOR ALL TO living_owner
 USING (true) WITH CHECK (true);
CREATE POLICY s4_owner_all ON living.s4_eligibility FOR ALL TO living_owner
 USING (true) WITH CHECK (true);
CREATE POLICY s4_owner_all ON living.s4_acceptance_fingerprints FOR ALL TO living_owner
 USING (true) WITH CHECK (true);
CREATE POLICY s4_scoped_read ON living.s4_model_modes FOR SELECT
 USING (living.row_in_scope(tenant_id,source_id));
CREATE POLICY s4_scoped_read ON living.s4_eligibility FOR SELECT
 USING (living.row_in_scope(tenant_id,source_id,company_id));
CREATE POLICY s4_scoped_read ON living.s4_acceptance_fingerprints FOR SELECT
 USING (living.row_in_scope(tenant_id,source_id));
GRANT SELECT ON living.s4_model_modes, living.s4_eligibility,
 living.s4_acceptance_fingerprints TO living_promoter;

-- Owner-managed enrollment/pause. Source lock serializes transitions with legacy writes.
-- There is no delete or transition to unenrolled; absence of a mode row is the only
-- representation of never-enrolled. PAUSED -> ENROLLED is an explicit re-enable.
CREATE OR REPLACE FUNCTION living.s4_set_model_mode(
 t text, s text, m text, p_mode text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; src_status text; prior text;
BEGIN
 who := living.caller_role();
 IF who IS NULL OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=who)
    OR NOT pg_has_role(who::name,'living_owner','USAGE') THEN
  RAISE EXCEPTION 'NOT_OWNER';
 END IF;
 IF t IS NULL OR s IS NULL OR m IS NULL OR m='' OR p_mode IS NULL
    OR p_mode NOT IN ('ENROLLED','PAUSED') THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 SELECT status INTO src_status FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 SELECT mode INTO prior FROM living.s4_model_modes
  WHERE tenant_id=t AND source_id=s AND model_key=m FOR UPDATE;
 IF prior IS NULL THEN
  INSERT INTO living.s4_model_modes(tenant_id,source_id,model_key,mode,changed_by)
   VALUES(t,s,m,p_mode,who);
 ELSE
  UPDATE living.s4_model_modes SET mode=p_mode,changed_by=who,changed_at=clock_timestamp()
   WHERE tenant_id=t AND source_id=s AND model_key=m;
 END IF;
END $fn$;

-- Eligibility registration is limited to a separately provisioned verifier duty role.
-- Membership is the synthetic adapter trust boundary; without it registration fails closed.
-- The verifier must have already authenticated the immutable artifact bytes and pinning policy.
CREATE OR REPLACE FUNCTION living.s4_register_eligibility(
 t text, s text, p_eligibility uuid, p_company text, p_attestation uuid,
 p_revision uuid, p_artifact_version text, p_content_sha256 text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; src_status text; src_company text; att living.attestations%ROWTYPE;
        rev_digest text; current_company text; existing living.s4_eligibility%ROWTYPE;
BEGIN
 who := living.caller_role();
 IF who IS NULL OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=who) THEN
  RAISE EXCEPTION 'S4_VERIFIER_NOT_PROVISIONED';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='living_s4_verifier') THEN
  RAISE EXCEPTION 'S4_VERIFIER_NOT_PROVISIONED';
 END IF;
 IF NOT pg_has_role(who::name,'living_s4_verifier','USAGE') THEN
  RAISE EXCEPTION 'S4_VERIFIER_NOT_PROVISIONED';
 END IF;
 IF t IS NULL OR s IS NULL OR p_eligibility IS NULL OR p_company IS NULL OR p_company=''
    OR p_attestation IS NULL OR p_revision IS NULL OR p_artifact_version IS NULL
    OR p_artifact_version='' OR p_content_sha256 IS NULL
    OR p_content_sha256 !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 SELECT status,company_id INTO src_status,src_company FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 current_company := nullif(current_setting('living.company_id',true),'');
 IF current_company IS DISTINCT FROM p_company
    OR (src_company IS NOT NULL AND src_company IS DISTINCT FROM p_company)
    OR NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
       AND rs.company_id=p_company AND pg_has_role(who::name,rs.role_name::name,'USAGE')) THEN
  RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
 END IF;
 PERFORM living.recheck_scope_locked(t,s);
 SELECT * INTO att FROM living.attestations
  WHERE tenant_id=t AND source_id=s AND attestation_id=p_attestation FOR UPDATE;
 IF NOT FOUND OR att.revision_id IS DISTINCT FROM p_revision OR att.decision IS DISTINCT FROM 'APPROVE'
    OR att.revoked_at IS NOT NULL OR att.expires_at IS NULL OR att.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'ATTESTATION_NOT_ELIGIBLE';
 END IF;
 SELECT digest INTO rev_digest FROM living.observations
  WHERE tenant_id=t AND source_id=s AND revision_id=p_revision AND kind='OBSERVED';
 IF NOT FOUND OR att.evidence_digest IS DISTINCT FROM
    encode(sha256(convert_to(rev_digest||':'||att.evidence_ref,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'ATTESTATION_DIGEST_INVALID';
 END IF;
 SELECT * INTO existing FROM living.s4_eligibility
  WHERE tenant_id=t AND source_id=s AND eligibility_id=p_eligibility FOR UPDATE;
 IF FOUND THEN
  IF existing.company_id=p_company AND existing.attestation_id=p_attestation
    AND existing.revision_id=p_revision AND existing.artifact_version=p_artifact_version
    AND existing.content_sha256=p_content_sha256 AND existing.state='ELIGIBLE' THEN
   RETURN p_eligibility;
  END IF;
  RAISE EXCEPTION 'ELIGIBILITY_ID_REUSED';
 END IF;
 INSERT INTO living.s4_eligibility(tenant_id,source_id,eligibility_id,company_id,
  attestation_id,revision_id,artifact_version,content_sha256,state,registered_by)
 VALUES(t,s,p_eligibility,p_company,p_attestation,p_revision,p_artifact_version,
  p_content_sha256,'ELIGIBLE',who);
 RETURN p_eligibility;
END $fn$;

CREATE OR REPLACE FUNCTION living.s4_revoke_eligibility(
 t text, s text, p_eligibility uuid
) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; src_status text; el living.s4_eligibility%ROWTYPE; result timestamptz;
BEGIN
 who := living.caller_role();
 IF who IS NULL OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=who)
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='living_s4_verifier') THEN
  RAISE EXCEPTION 'S4_VERIFIER_NOT_PROVISIONED';
 END IF;
 IF NOT pg_has_role(who::name,'living_s4_verifier','USAGE') THEN
  RAISE EXCEPTION 'S4_VERIFIER_NOT_PROVISIONED';
 END IF;
 IF t IS NULL OR s IS NULL OR p_eligibility IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 SELECT status INTO src_status FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 PERFORM living.recheck_scope_locked(t,s);
 SELECT * INTO el FROM living.s4_eligibility
  WHERE tenant_id=t AND source_id=s AND eligibility_id=p_eligibility FOR UPDATE;
 IF NOT FOUND OR nullif(current_setting('living.company_id',true),'') IS DISTINCT FROM el.company_id
    OR NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
       AND rs.company_id=el.company_id AND pg_has_role(who::name,rs.role_name::name,'USAGE')) THEN
  RAISE EXCEPTION 'ELIGIBILITY_NOT_FOUND';
 END IF;
 IF el.state='REVOKED' THEN RETURN el.revoked_at; END IF;
 UPDATE living.s4_eligibility SET state='REVOKED',revoked_by=who,revoked_at=clock_timestamp()
  WHERE tenant_id=t AND source_id=s AND eligibility_id=p_eligibility
  RETURNING revoked_at INTO result;
 RETURN result;
END $fn$;

-- Replace the existing legacy path with the same contract plus an enrollment check before
-- replay. Otherwise an old acceptance_id could return success without reaching the head trigger.
CREATE OR REPLACE FUNCTION living.promote_head(
 t text,s text,m text,expected_version bigint,new_revision uuid,
 acceptance uuid,evidence text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE new_version bigint; approver text; st text; obs text; prop text; rev_kind text;
 ev living.acceptance_events%ROWTYPE; sess_super boolean; att living.attestations%ROWTYPE;
 rev_digest text; s4_mode text;
BEGIN
 PERFORM living.assert_scope(t,s);
 approver := living.caller_role();
 IF approver IS NULL OR approver='' OR evidence IS NULL OR evidence=''
  OR new_revision IS NULL OR acceptance IS NULL OR expected_version IS NULL OR m IS NULL THEN
  RAISE EXCEPTION 'INDEPENDENT_APPROVAL_REQUIRED';
 END IF;
 IF NOT pg_has_role(approver::name,'living_promoter','USAGE') THEN RAISE EXCEPTION 'NOT_A_PROMOTER'; END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 PERFORM living.recheck_scope_locked(t,s);
 IF st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 SELECT mode INTO s4_mode FROM living.s4_model_modes
  WHERE tenant_id=t AND source_id=s AND model_key=m;
 IF s4_mode IS NOT NULL THEN RAISE EXCEPTION 'S4_MODEL_ENROLLED'; END IF;
 SELECT * INTO ev FROM living.acceptance_events
  WHERE tenant_id=t AND source_id=s AND acceptance_id=acceptance;
 IF FOUND THEN
  IF ev.model_key=m AND ev.from_version=expected_version AND ev.accepted_revision=new_revision
   AND ev.approver_subject=approver AND ev.independent_evidence_ref=evidence THEN
   RETURN ev.to_version;
  END IF;
  RAISE EXCEPTION 'ACCEPTANCE_ID_REUSED';
 END IF;
 SELECT coalesce(rolsuper,false) INTO sess_super FROM pg_catalog.pg_roles WHERE rolname=session_user;
 IF pg_has_role(approver::name,'living_worker','MEMBER')
  OR (NOT sess_super AND pg_has_role(session_user,'living_worker','MEMBER')) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 SELECT kind,digest INTO rev_kind,rev_digest FROM living.observations
  WHERE tenant_id=t AND source_id=s AND revision_id=new_revision;
 IF rev_kind IS DISTINCT FROM 'OBSERVED' THEN RAISE EXCEPTION 'REVISION_NOT_OBSERVED'; END IF;
 SELECT * INTO att FROM living.attestations
  WHERE tenant_id=t AND source_id=s AND revision_id=new_revision AND evidence_ref=evidence;
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_NOT_FOUND'; END IF;
 obs := att.observer_subject; prop := att.proposer_subject;
 IF approver IS NOT DISTINCT FROM obs OR approver IS NOT DISTINCT FROM prop
  OR (NOT sess_super AND (session_user::text IS NOT DISTINCT FROM obs OR session_user::text IS NOT DISTINCT FROM prop))
  OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname IN (obs,prop)
    AND (pg_has_role(approver::name,r.oid,'MEMBER') OR pg_has_role(r.oid,approver::name,'MEMBER')
      OR (NOT sess_super AND pg_has_role(session_user,r.oid,'MEMBER')))) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 IF att.decision IS DISTINCT FROM 'APPROVE' THEN RAISE EXCEPTION 'EVIDENCE_NOT_APPROVED'; END IF;
 IF att.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'EVIDENCE_REVOKED'; END IF;
 IF att.expires_at IS NULL OR att.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'EVIDENCE_EXPIRED'; END IF;
 IF att.evidence_digest IS DISTINCT FROM encode(sha256(convert_to(rev_digest||':'||evidence,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'EVIDENCE_DIGEST_MISMATCH';
 END IF;
 IF NOT living.is_trusted_reviewer(t,s,obs) THEN RAISE EXCEPTION 'REVIEWER_NOT_TRUSTED'; END IF;
 PERFORM set_config('living.promoting','on',true);
 UPDATE living.accepted_heads SET revision_id=new_revision,version=version+1,updated_at=clock_timestamp()
  WHERE tenant_id=t AND source_id=s AND model_key=m AND version=expected_version
  RETURNING version INTO new_version;
 PERFORM set_config('living.promoting','off',true);
 IF new_version IS NULL THEN RAISE EXCEPTION 'STALE_ACCEPTED_HEAD'; END IF;
 INSERT INTO living.acceptance_events(tenant_id,source_id,acceptance_id,model_key,from_version,to_version,
  accepted_revision,approver_subject,independent_evidence_ref)
 VALUES(t,s,acceptance,m,expected_version,new_version,new_revision,approver,evidence);
 RETURN new_version;
END $fn$;

-- Preserve the existing head guard and privileges. A new row UPDATE trigger would take
-- the head lock before the source lock for a direct update, reversing the procedure's order.
ALTER FUNCTION living.promote_head(text,text,text,bigint,uuid,uuid,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_set_model_mode(text,text,text,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_register_eligibility(text,text,uuid,text,uuid,uuid,text,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_revoke_eligibility(text,text,uuid) OWNER TO living_owner;
REVOKE ALL ON FUNCTION living.s4_set_model_mode(text,text,text,text),
 living.s4_register_eligibility(text,text,uuid,text,uuid,uuid,text,text),
 living.s4_revoke_eligibility(text,text,uuid)
 FROM PUBLIC,living_worker,living_reader,living_promoter,living_publisher;
GRANT EXECUTE ON FUNCTION living.s4_set_model_mode(text,text,text,text) TO living_owner;
-- Deliberately no verifier grant until disposable role provisioning and byte verification
-- are supplied by the selected testbed harness. Runtime production roles receive no S4 API.

COMMIT;
