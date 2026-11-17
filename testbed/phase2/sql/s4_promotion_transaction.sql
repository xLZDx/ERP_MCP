-- S4 R2-US-016 synthetic transaction entry points.
-- Apply manually, after s4_promotion_eligibility.sql, only to a dedicated
-- s4_disposable_* database with s4.disposable_fixture=on. Not a migration.
-- No grants are made to existing application roles; fixture roles are NOLOGIN.

BEGIN;
DO $guard$
BEGIN
 IF current_setting('s4.disposable_fixture',true) IS DISTINCT FROM 'on'
    OR current_database() !~ '^s4_disposable_[a-z0-9_]+$' THEN
  RAISE EXCEPTION 'S4_DISPOSABLE_FIXTURE_REQUIRED';
 END IF;
 IF to_regclass('living.s4_model_modes') IS NULL
    OR to_regclass('living.s4_eligibility') IS NULL
    OR to_regclass('living.s4_acceptance_fingerprints') IS NULL THEN
  RAISE EXCEPTION 'S4_ELIGIBILITY_FIXTURE_REQUIRED';
 END IF;
END
$guard$;

-- Dedicated fixture-only roles; no LOGIN and no membership is granted to product roles.
DO $roles$
DECLARE r text;
BEGIN
 FOREACH r IN ARRAY ARRAY['living_s4_fixture_promoter','living_s4_fixture_verifier'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE',r);
  ELSIF EXISTS(SELECT 1 FROM pg_catalog.pg_roles
    WHERE rolname=r AND (rolsuper OR rolbypassrls OR rolcanlogin OR rolcreatedb OR rolcreaterole)) THEN
   RAISE EXCEPTION 'S4_FIXTURE_ROLE_UNSAFE: %',r;
  END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='living_s4_verifier'
    AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcanlogin) THEN
  RAISE EXCEPTION 'S4_VERIFIER_ROLE_MISSING';
 END IF;
 EXECUTE 'GRANT living_s4_verifier TO living_s4_fixture_verifier';
END
$roles$;
GRANT USAGE ON SCHEMA living TO living_s4_fixture_promoter,living_s4_fixture_verifier;
GRANT SELECT ON living.sources,living.role_scope TO living_s4_fixture_promoter,living_s4_fixture_verifier;
GRANT EXECUTE ON FUNCTION living.caller_role(),living.set_scope(text,text,text),
 living.assert_scope(text,text),living.recheck_scope_locked(text,text),
 living.row_in_scope(text,text,text)
 TO living_s4_fixture_promoter,living_s4_fixture_verifier;

CREATE TABLE living.s4_actor_bindings(
 tenant_id text NOT NULL,
 source_id text NOT NULL,
 role_name text NOT NULL CHECK(length(role_name)>0),
 subject text NOT NULL CHECK(length(subject)>0),
 duty text NOT NULL CHECK(duty IN ('REQUESTER','APPROVER')),
 bound_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,role_name,duty),
 UNIQUE(tenant_id,source_id,subject,duty),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources
);

CREATE TABLE living.s4_promotion_requests(
 tenant_id text NOT NULL,
 source_id text NOT NULL,
 acceptance_id uuid NOT NULL,
 company_id text NOT NULL,
 model_key text NOT NULL CHECK(length(model_key)>0),
 operation text NOT NULL CHECK(operation IN ('promote','rollback')),
 requested_rollback_version bigint,
 expected_version bigint NOT NULL CHECK(expected_version BETWEEN 0 AND 9223372036854775807),
 target_revision uuid NOT NULL,
 eligibility_id uuid NOT NULL,
 requester_subject text NOT NULL CHECK(length(requester_subject)>0),
 registered_by text NOT NULL CHECK(length(registered_by)>0),
 registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,source_id,acceptance_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES living.sources,
 FOREIGN KEY(tenant_id,source_id,eligibility_id)
  REFERENCES living.s4_eligibility(tenant_id,source_id,eligibility_id),
 FOREIGN KEY(tenant_id,source_id,target_revision)
  REFERENCES living.observations(tenant_id,source_id,revision_id),
 CHECK ((operation='promote' AND requested_rollback_version IS NULL)
     OR (operation='rollback' AND requested_rollback_version BETWEEN 1 AND 9223372036854775807
         AND requested_rollback_version < expected_version))
);

ALTER TABLE living.s4_actor_bindings OWNER TO living_owner;
ALTER TABLE living.s4_promotion_requests OWNER TO living_owner;
REVOKE ALL ON living.s4_actor_bindings,living.s4_promotion_requests
 FROM PUBLIC,living_worker,living_reader,living_promoter,living_publisher,
      living_s4_fixture_promoter,living_s4_fixture_verifier;
ALTER TABLE living.s4_actor_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE living.s4_actor_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE living.s4_promotion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE living.s4_promotion_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY s4_owner_all ON living.s4_actor_bindings FOR ALL TO living_owner
 USING(true) WITH CHECK(true);
CREATE POLICY s4_owner_all ON living.s4_promotion_requests FOR ALL TO living_owner
 USING(true) WITH CHECK(true);
CREATE POLICY s4_scoped_read ON living.s4_actor_bindings FOR SELECT
 USING(living.row_in_scope(tenant_id,source_id));
CREATE POLICY s4_scoped_read ON living.s4_promotion_requests FOR SELECT
 USING(living.row_in_scope(tenant_id,source_id,company_id));
GRANT SELECT ON living.s4_actor_bindings,living.s4_promotion_requests
 TO living_s4_fixture_promoter;

CREATE OR REPLACE FUNCTION living.s4_reject_request_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RAISE EXCEPTION 'S4_REQUEST_IMMUTABLE';
END $fn$;
ALTER FUNCTION living.s4_reject_request_mutation() OWNER TO living_owner;
CREATE TRIGGER s4_request_immutable BEFORE UPDATE OR DELETE ON living.s4_promotion_requests
 FOR EACH ROW EXECUTE FUNCTION living.s4_reject_request_mutation();
CREATE TRIGGER s4_request_no_truncate BEFORE TRUNCATE ON living.s4_promotion_requests
 FOR EACH STATEMENT EXECUTE FUNCTION living.s4_reject_request_mutation();

CREATE OR REPLACE FUNCTION living.s4_reject_append_only() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RAISE EXCEPTION 'S4_APPEND_ONLY';
END $fn$;
ALTER FUNCTION living.s4_reject_append_only() OWNER TO living_owner;
CREATE TRIGGER s4_actor_binding_immutable BEFORE UPDATE OR DELETE ON living.s4_actor_bindings
 FOR EACH ROW EXECUTE FUNCTION living.s4_reject_append_only();
CREATE TRIGGER s4_actor_binding_no_truncate BEFORE TRUNCATE ON living.s4_actor_bindings
 FOR EACH STATEMENT EXECUTE FUNCTION living.s4_reject_append_only();
CREATE TRIGGER s4_fingerprint_immutable BEFORE UPDATE OR DELETE ON living.s4_acceptance_fingerprints
 FOR EACH ROW EXECUTE FUNCTION living.s4_reject_append_only();
CREATE TRIGGER s4_fingerprint_no_truncate BEFORE TRUNCATE ON living.s4_acceptance_fingerprints
 FOR EACH STATEMENT EXECUTE FUNCTION living.s4_reject_append_only();

-- Canonical field framing. Null is legal only for promotion's absent rollback version.
CREATE OR REPLACE FUNCTION living.s4_frame_field(p_prefix bytea,p_value text,p_nullable boolean DEFAULT false)
RETURNS bytea LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b bytea;
BEGIN
 IF p_value IS NULL THEN
  IF NOT p_nullable THEN RAISE EXCEPTION 'S4_FINGERPRINT_NULL_FIELD'; END IF;
  RETURN p_prefix || convert_to('0','UTF8');
 END IF;
 b := convert_to(p_value,'UTF8');
 IF octet_length(b)<1 OR octet_length(b)>4096 THEN RAISE EXCEPTION 'S4_FINGERPRINT_FIELD_SIZE'; END IF;
 RETURN p_prefix || convert_to('1'||octet_length(b)::text||':','UTF8') || b;
END $fn$;

CREATE OR REPLACE FUNCTION living.s4_fingerprint_v1(
 p_tenant text,p_source text,p_company text,p_model text,p_operation text,
 p_rollback_version bigint,p_expected_version bigint,p_target_revision uuid,
 p_requester text,p_approver text,p_attestation uuid,p_evidence_ref text,
 p_artifact_version text,p_content_sha256 text
) RETURNS text LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b bytea; value text; fields text[]; n integer;
BEGIN
 IF p_operation NOT IN ('promote','rollback') OR p_operation IS NULL
    OR (p_operation='promote' AND p_rollback_version IS NOT NULL)
    OR (p_operation='rollback' AND (p_rollback_version IS NULL OR p_rollback_version<1
       OR p_expected_version IS NULL OR p_rollback_version>=p_expected_version))
    OR p_expected_version IS NULL OR p_expected_version<0
    OR p_target_revision IS NULL OR p_attestation IS NULL
    OR p_content_sha256 IS NULL OR p_content_sha256 !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'S4_FINGERPRINT_INVALID';
 END IF;
 fields := ARRAY[p_tenant,p_source,p_company,p_model,p_operation,
   CASE WHEN p_rollback_version IS NULL THEN NULL ELSE p_rollback_version::text END,
   p_expected_version::text,p_target_revision::text,p_requester,p_approver,
   p_attestation::text,p_evidence_ref,p_artifact_version,p_content_sha256];
 b := convert_to('erp-mcp:promotion-request:v1','UTF8') || decode('00','hex');
 FOR n IN 1..array_length(fields,1) LOOP
  b := living.s4_frame_field(b,fields[n],n=6);
  IF octet_length(b)>65536 THEN RAISE EXCEPTION 'S4_FINGERPRINT_TOO_LARGE'; END IF;
 END LOOP;
 RETURN encode(sha256(b),'hex');
END $fn$;

CREATE OR REPLACE FUNCTION living.s4_parse_uuid_v1(p_value text)
RETURNS uuid LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF p_value IS NULL OR p_value !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
  RAISE EXCEPTION 'S4_UUID_NOT_CANONICAL';
 END IF;
 RETURN p_value::uuid;
END $fn$;

-- Owner fixture registration of a role->stable subject binding. It is append-only and refuses
-- ambiguous reuse. The role must be a real, non-superuser DB role; runtime inputs cannot supply
-- an actor identity to promotion itself.
CREATE OR REPLACE FUNCTION living.s4_bind_actor(
 t text,s text,p_role text,p_subject text,p_duty text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; st text; prior living.s4_actor_bindings%ROWTYPE;
BEGIN
 who:=living.caller_role();
 IF who IS NULL OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=who)
    OR NOT pg_has_role(who::name,'living_owner','USAGE') THEN RAISE EXCEPTION 'NOT_OWNER'; END IF;
 IF t IS NULL OR s IS NULL OR p_role IS NULL OR p_subject IS NULL OR p_subject=''
    OR p_duty NOT IN ('REQUESTER','APPROVER') OR p_duty IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_role AND NOT rolsuper AND NOT rolbypassrls) THEN
  RAISE EXCEPTION 'ACTOR_ROLE_INVALID';
 END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND OR st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SOURCE_NOT_ACTIVE'; END IF;
 SELECT * INTO prior FROM living.s4_actor_bindings
  WHERE tenant_id=t AND source_id=s AND role_name=p_role AND duty=p_duty FOR UPDATE;
 IF FOUND THEN
  IF prior.subject=p_subject THEN RETURN; END IF;
  RAISE EXCEPTION 'ACTOR_BINDING_IMMUTABLE';
 END IF;
 IF EXISTS(SELECT 1 FROM living.s4_actor_bindings WHERE tenant_id=t AND source_id=s
    AND subject=p_subject AND duty=p_duty) THEN RAISE EXCEPTION 'ACTOR_SUBJECT_AMBIGUOUS'; END IF;
 INSERT INTO living.s4_actor_bindings(tenant_id,source_id,role_name,subject,duty)
  VALUES(t,s,p_role,p_subject,p_duty);
END $fn$;

-- Owner/verifier-provisioned immutable request envelope. requester role is resolved against the
-- trusted fixture binding; no free-form requester subject is accepted by the transaction API.
CREATE OR REPLACE FUNCTION living.s4_register_request(
 t text,s text,p_acceptance text,p_company text,p_model text,p_operation text,
 p_rollback_version bigint,p_expected_version bigint,p_target_revision text,
 p_eligibility uuid,p_requester_role text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; st text; src_company text; requester text; el living.s4_eligibility%ROWTYPE;
        old living.s4_promotion_requests%ROWTYPE; acceptance_uuid uuid; target_uuid uuid;
BEGIN
 who:=living.caller_role();
 IF who IS NULL OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=who)
    OR NOT pg_has_role(who::name,'living_owner','USAGE') THEN RAISE EXCEPTION 'NOT_OWNER'; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'S4_READ_COMMITTED_REQUIRED'; END IF;
 IF t IS NULL OR s IS NULL OR p_company IS NULL OR p_company=''
    OR p_model IS NULL OR p_model='' OR p_operation NOT IN ('promote','rollback') OR p_operation IS NULL
    OR p_expected_version IS NULL OR p_expected_version<0
    OR p_eligibility IS NULL OR p_requester_role IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 acceptance_uuid:=living.s4_parse_uuid_v1(p_acceptance);
 target_uuid:=living.s4_parse_uuid_v1(p_target_revision);
 IF (p_operation='promote' AND p_rollback_version IS NOT NULL)
    OR (p_operation='rollback' AND (p_rollback_version IS NULL OR p_rollback_version<1
      OR p_rollback_version>=p_expected_version)) THEN RAISE EXCEPTION 'ROLLBACK_VERSION_INVALID'; END IF;
 SELECT status,company_id INTO st,src_company FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND OR st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SOURCE_NOT_ACTIVE'; END IF;
 IF src_company IS NOT NULL AND src_company<>p_company THEN
  RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_requester_role) THEN
  RAISE EXCEPTION 'REQUESTER_ROLE_INVALID';
 END IF;
 SELECT subject INTO requester FROM living.s4_actor_bindings
  WHERE tenant_id=t AND source_id=s AND role_name=p_requester_role AND duty='REQUESTER';
 IF requester IS NULL THEN RAISE EXCEPTION 'REQUESTER_BINDING_MISSING'; END IF;
 IF NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
    AND rs.company_id=p_company AND pg_has_role(p_requester_role::name,rs.role_name::name,'USAGE')) THEN
  RAISE EXCEPTION 'REQUESTER_COMPANY_SCOPE_MISMATCH';
 END IF;
 SELECT * INTO el FROM living.s4_eligibility WHERE tenant_id=t AND source_id=s
  AND eligibility_id=p_eligibility FOR UPDATE;
 IF NOT FOUND OR el.state<>'ELIGIBLE' OR el.company_id<>p_company OR el.revision_id<>target_uuid THEN
  RAISE EXCEPTION 'ELIGIBILITY_NOT_VALID';
 END IF;
 IF EXISTS(SELECT 1 FROM living.s4_promotion_requests WHERE tenant_id=t AND source_id=s
    AND acceptance_id=acceptance_uuid) THEN
  SELECT * INTO old FROM living.s4_promotion_requests WHERE tenant_id=t AND source_id=s
   AND acceptance_id=acceptance_uuid;
  IF old.company_id=p_company AND old.model_key=p_model AND old.operation=p_operation
    AND old.requested_rollback_version IS NOT DISTINCT FROM p_rollback_version
    AND old.expected_version=p_expected_version AND old.target_revision=target_uuid
    AND old.eligibility_id=p_eligibility AND old.requester_subject=requester THEN RETURN acceptance_uuid; END IF;
  RAISE EXCEPTION 'ACCEPTANCE_REQUEST_ID_REUSED';
 END IF;
 INSERT INTO living.s4_promotion_requests(tenant_id,source_id,acceptance_id,company_id,model_key,
   operation,requested_rollback_version,expected_version,target_revision,eligibility_id,
   requester_subject,registered_by)
 VALUES(t,s,acceptance_uuid,p_company,p_model,p_operation,p_rollback_version,p_expected_version,
   target_uuid,p_eligibility,requester,who);
 RETURN acceptance_uuid;
END $fn$;

CREATE OR REPLACE FUNCTION living.s4_resolve_approver(t text,s text,p_role text)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE result text; n integer;
BEGIN
 SELECT count(*),min(subject) INTO n,result FROM living.s4_actor_bindings
  WHERE tenant_id=t AND source_id=s AND role_name=p_role AND duty='APPROVER';
 IF n<>1 OR result IS NULL THEN RAISE EXCEPTION 'APPROVER_BINDING_MISSING_OR_AMBIGUOUS'; END IF;
 RETURN result;
END $fn$;

-- Verify the current authenticated caller's fixture role and source scope.
CREATE OR REPLACE FUNCTION living.s4_assert_fixture_promoter(t text,s text)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; company text; source_company text;
BEGIN
 who:=living.caller_role();
 IF who IS NULL OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='living_s4_fixture_promoter')
    OR NOT pg_has_role(who::name,'living_s4_fixture_promoter','USAGE') THEN RAISE EXCEPTION 'NOT_S4_FIXTURE_PROMOTER'; END IF;
 company:=nullif(current_setting('living.company_id',true),'');
 IF company IS NULL THEN RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH'; END IF;
 SELECT company_id INTO source_company FROM living.sources WHERE tenant_id=t AND source_id=s;
 IF NOT FOUND OR (source_company IS NOT NULL AND source_company<>company)
    OR NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
      AND rs.company_id=company AND pg_has_role(who::name,rs.role_name::name,'USAGE')) THEN
  RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
 END IF;
 PERFORM living.assert_scope(t,s);
 RETURN living.s4_resolve_approver(t,s,who);
END $fn$;

CREATE OR REPLACE FUNCTION living.s4_request_digest(
 p living.s4_promotion_requests,p_approver text,p_e living.s4_eligibility
) RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a living.attestations%ROWTYPE;
BEGIN
 SELECT * INTO a FROM living.attestations WHERE tenant_id=p.tenant_id AND source_id=p.source_id
  AND attestation_id=p_e.attestation_id;
 IF NOT FOUND OR a.revision_id<>p.target_revision THEN RAISE EXCEPTION 'S4_ATTESTATION_BINDING_INVALID'; END IF;
 RETURN living.s4_fingerprint_v1(p.tenant_id,p.source_id,p.company_id,p.model_key,p.operation,
  p.requested_rollback_version,p.expected_version,p.target_revision,p.requester_subject,p_approver,
  p_e.attestation_id,a.evidence_ref,p_e.artifact_version,p_e.content_sha256);
END $fn$;

-- Atomic synthetic promote/rollback. The acceptance event and fingerprint companion are in the
-- same transaction as the head CAS. Timeouts/cancellation propagate as errors: callers must read
-- back after reconnect and must never dispatch again based only on a timeout.
CREATE OR REPLACE FUNCTION living.s4_promote_v1(t text,s text,p_acceptance uuid)
RETURNS TABLE(outcome text,to_version bigint,request_sha256 text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; approver text; st text; mode_now text; req living.s4_promotion_requests%ROWTYPE;
        el living.s4_eligibility%ROWTYPE; head living.accepted_heads%ROWTYPE;
        att living.attestations%ROWTYPE; digest_value text; ev living.acceptance_events%ROWTYPE;
        fp living.s4_acceptance_fingerprints%ROWTYPE; rev_digest text; rev_kind text;
        event_evidence text; sess_super boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'S4_READ_COMMITTED_REQUIRED'; END IF;
 who:=living.caller_role(); approver:=living.s4_assert_fixture_promoter(t,s);
 IF p_acceptance IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND OR st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SOURCE_NOT_ACTIVE'; END IF;
 PERFORM living.recheck_scope_locked(t,s);
 -- Existing event classification comes first: historical rows remain historical, and an exact
 -- committed replay stays resolvable even after its eligibility record is later revoked.
 SELECT * INTO ev FROM living.acceptance_events WHERE tenant_id=t AND source_id=s
  AND acceptance_id=p_acceptance;
 IF FOUND THEN
  SELECT * INTO fp FROM living.s4_acceptance_fingerprints WHERE tenant_id=t AND source_id=s
   AND acceptance_id=p_acceptance;
  IF NOT FOUND THEN RETURN QUERY SELECT 'HISTORICAL_EVENT',NULL::bigint,NULL::text; RETURN; END IF;
  SELECT * INTO req FROM living.s4_promotion_requests WHERE tenant_id=t AND source_id=s
   AND acceptance_id=p_acceptance;
  IF NOT FOUND THEN RAISE EXCEPTION 'S4_REQUEST_MISSING_FOR_FINGERPRINT'; END IF;
  SELECT * INTO el FROM living.s4_eligibility WHERE tenant_id=t AND source_id=s
   AND eligibility_id=req.eligibility_id FOR UPDATE;
  IF NOT FOUND OR el.company_id<>req.company_id OR el.revision_id<>req.target_revision THEN
   RAISE EXCEPTION 'S4_ELIGIBILITY_MISSING_FOR_FINGERPRINT';
  END IF;
  IF nullif(current_setting('living.company_id',true),'') IS DISTINCT FROM req.company_id THEN
   RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
    AND rs.company_id=req.company_id AND pg_has_role(who::name,rs.role_name::name,'USAGE')) THEN
   RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
  END IF;
  digest_value:=living.s4_request_digest(req,approver,el);
  SELECT evidence_ref INTO STRICT event_evidence FROM living.attestations
   WHERE tenant_id=t AND source_id=s AND attestation_id=el.attestation_id;
  IF ev.model_key=req.model_key AND ev.from_version=req.expected_version
     AND ev.accepted_revision=req.target_revision AND ev.approver_subject=approver
     AND ev.independent_evidence_ref=event_evidence AND fp.format='promotion-request-v1'
     AND fp.request_sha256=digest_value THEN
   RETURN QUERY SELECT 'EXACT_COMMIT',ev.to_version,fp.request_sha256; RETURN;
  END IF;
  RETURN QUERY SELECT 'CONFLICTING_USE',NULL::bigint,NULL::text; RETURN;
 END IF;
 SELECT * INTO req FROM living.s4_promotion_requests
  WHERE tenant_id=t AND source_id=s AND acceptance_id=p_acceptance;
 IF NOT FOUND THEN RAISE EXCEPTION 'S4_REQUEST_NOT_FOUND'; END IF;
 IF nullif(current_setting('living.company_id',true),'') IS DISTINCT FROM req.company_id
    OR NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
      AND rs.company_id=req.company_id AND pg_has_role(who::name,rs.role_name::name,'USAGE')) THEN
  RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
 END IF;
 SELECT mode INTO mode_now FROM living.s4_model_modes
  WHERE tenant_id=t AND source_id=s AND model_key=req.model_key;
 IF mode_now IS DISTINCT FROM 'ENROLLED' THEN RAISE EXCEPTION 'S4_MODEL_NOT_ENROLLED_OR_PAUSED'; END IF;
 -- Eligibility revocation and registration take the same source lock. Lock order: source, eligibility, head.
 SELECT * INTO el FROM living.s4_eligibility WHERE tenant_id=t AND source_id=s
  AND eligibility_id=req.eligibility_id FOR UPDATE;
 IF NOT FOUND OR el.state<>'ELIGIBLE' OR el.company_id<>req.company_id
    OR el.revision_id<>req.target_revision THEN RAISE EXCEPTION 'ELIGIBILITY_NOT_VALID'; END IF;
 SELECT * INTO att FROM living.attestations WHERE tenant_id=t AND source_id=s
  AND attestation_id=el.attestation_id;
 IF NOT FOUND OR att.revision_id<>req.target_revision OR att.decision<>'APPROVE'
    OR att.revoked_at IS NOT NULL OR att.expires_at IS NULL OR att.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'ATTESTATION_NOT_VALID';
 END IF;
 SELECT o.kind,o.digest INTO rev_kind,rev_digest FROM living.observations o WHERE o.tenant_id=t AND o.source_id=s
  AND o.revision_id=req.target_revision;
 IF NOT FOUND OR rev_kind<>'OBSERVED' OR att.evidence_digest IS DISTINCT FROM
   encode(sha256(convert_to(rev_digest||':'||att.evidence_ref,'UTF8')),'hex') THEN RAISE EXCEPTION 'EVIDENCE_DIGEST_INVALID'; END IF;
 IF NOT living.is_trusted_reviewer(t,s,att.observer_subject) THEN RAISE EXCEPTION 'REVIEWER_NOT_TRUSTED'; END IF;
 SELECT coalesce(rolsuper,false) INTO sess_super FROM pg_catalog.pg_roles WHERE rolname=session_user;
 IF approver=att.observer_subject OR approver=att.proposer_subject OR approver=req.requester_subject
    OR pg_has_role(who::name,'living_worker','MEMBER')
    OR (NOT sess_super AND pg_has_role(session_user,'living_worker','MEMBER'))
    OR (NOT sess_super AND (session_user::text=att.observer_subject OR session_user::text=att.proposer_subject))
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname IN (att.observer_subject,att.proposer_subject)
       AND (pg_has_role(who::name,r.oid,'MEMBER') OR pg_has_role(r.oid,who::name,'MEMBER')
         OR (NOT sess_super AND pg_has_role(session_user,r.oid,'MEMBER')))) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 digest_value:=living.s4_request_digest(req,approver,el);
 IF req.operation='rollback' THEN
  IF NOT EXISTS(SELECT 1 FROM living.acceptance_events AS history
    WHERE history.tenant_id=t AND history.source_id=s AND history.model_key=req.model_key
    AND history.to_version=req.requested_rollback_version
    AND history.accepted_revision=req.target_revision) THEN RAISE EXCEPTION 'ROLLBACK_TARGET_NOT_ACCEPTED'; END IF;
 END IF;
 SELECT * INTO head FROM living.accepted_heads WHERE tenant_id=t AND source_id=s
  AND model_key=req.model_key FOR UPDATE;
 IF NOT FOUND OR head.version<>req.expected_version THEN RAISE EXCEPTION 'STALE_ACCEPTED_HEAD'; END IF;
 PERFORM set_config('living.promoting','on',true);
 UPDATE living.accepted_heads SET revision_id=req.target_revision,version=version+1,updated_at=clock_timestamp()
  WHERE tenant_id=t AND source_id=s AND model_key=req.model_key AND version=req.expected_version
  RETURNING version INTO to_version;
 PERFORM set_config('living.promoting','off',true);
 IF to_version IS NULL THEN RAISE EXCEPTION 'STALE_ACCEPTED_HEAD'; END IF;
 INSERT INTO living.acceptance_events(tenant_id,source_id,acceptance_id,model_key,from_version,to_version,
  accepted_revision,approver_subject,independent_evidence_ref)
 VALUES(t,s,p_acceptance,req.model_key,req.expected_version,to_version,req.target_revision,
  approver,att.evidence_ref);
 INSERT INTO living.s4_acceptance_fingerprints(tenant_id,source_id,acceptance_id,format,
  request_sha256,eligibility_id)
 VALUES(t,s,p_acceptance,'promotion-request-v1',digest_value,el.eligibility_id);
 RETURN QUERY SELECT 'COMMITTED',to_version,digest_value;
END $fn$;

-- Recovery query: source-row serialization point plus a separate VOLATILE function command under
-- READ COMMITTED ensures the later event lookup sees commits that finished while waiting for lock.
-- Any timeout/cancel/authority error propagates; absence is reported only after the lock+fresh read.
CREATE OR REPLACE FUNCTION living.s4_readback_v1(t text,s text,p_acceptance uuid)
RETURNS TABLE(outcome text,to_version bigint,request_sha256 text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; approver text; st text; ev living.acceptance_events%ROWTYPE;
        fp living.s4_acceptance_fingerprints%ROWTYPE; req living.s4_promotion_requests%ROWTYPE;
        el living.s4_eligibility%ROWTYPE; att living.attestations%ROWTYPE; calculated text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'S4_READ_COMMITTED_REQUIRED'; END IF;
 who:=living.caller_role(); approver:=living.s4_assert_fixture_promoter(t,s);
 IF p_acceptance IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 SELECT status INTO st FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND OR st IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SOURCE_NOT_ACTIVE'; END IF;
 PERFORM living.recheck_scope_locked(t,s);
 -- Separate SELECT after the lock is essential at READ COMMITTED; never infer NO_COMMIT on timeout.
 SELECT * INTO ev FROM living.acceptance_events WHERE tenant_id=t AND source_id=s
  AND acceptance_id=p_acceptance;
 IF NOT FOUND THEN RETURN QUERY SELECT 'NO_COMMIT',NULL::bigint,NULL::text; RETURN; END IF;
 SELECT * INTO fp FROM living.s4_acceptance_fingerprints WHERE tenant_id=t AND source_id=s
  AND acceptance_id=p_acceptance;
 IF NOT FOUND THEN RETURN QUERY SELECT 'HISTORICAL_EVENT',NULL::bigint,NULL::text; RETURN; END IF;
 SELECT * INTO req FROM living.s4_promotion_requests WHERE tenant_id=t AND source_id=s
  AND acceptance_id=p_acceptance;
 IF NOT FOUND THEN RAISE EXCEPTION 'S4_REQUEST_MISSING_FOR_FINGERPRINT'; END IF;
 IF nullif(current_setting('living.company_id',true),'') IS DISTINCT FROM req.company_id
    OR NOT EXISTS(SELECT 1 FROM living.role_scope rs WHERE rs.tenant_id=t AND rs.source_id=s
      AND rs.company_id=req.company_id AND pg_has_role(who::name,rs.role_name::name,'USAGE')) THEN
  RAISE EXCEPTION 'COMPANY_SCOPE_MISMATCH';
 END IF;
 SELECT * INTO el FROM living.s4_eligibility WHERE tenant_id=t AND source_id=s
  AND eligibility_id=req.eligibility_id;
 IF NOT FOUND OR el.company_id<>req.company_id OR el.revision_id<>req.target_revision THEN
  RAISE EXCEPTION 'S4_ELIGIBILITY_MISSING_FOR_FINGERPRINT';
 END IF;
 SELECT * INTO att FROM living.attestations WHERE tenant_id=t AND source_id=s
  AND attestation_id=el.attestation_id;
 IF NOT FOUND OR ev.independent_evidence_ref<>att.evidence_ref THEN
  RAISE EXCEPTION 'S4_EVENT_EVIDENCE_MISMATCH';
 END IF;
 calculated:=living.s4_request_digest(req,approver,el);
  IF ev.model_key=req.model_key AND ev.from_version=req.expected_version
     AND ev.accepted_revision=req.target_revision AND ev.approver_subject=approver
     AND fp.format='promotion-request-v1' AND fp.request_sha256=calculated THEN
  RETURN QUERY SELECT 'EXACT_COMMIT',ev.to_version,fp.request_sha256;
 ELSE
  RETURN QUERY SELECT 'CONFLICTING_USE',NULL::bigint,NULL::text;
 END IF;
END $fn$;

ALTER FUNCTION living.s4_frame_field(bytea,text,boolean) OWNER TO living_owner;
ALTER FUNCTION living.s4_fingerprint_v1(text,text,text,text,text,bigint,bigint,uuid,text,text,uuid,text,text,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_parse_uuid_v1(text) OWNER TO living_owner;
ALTER FUNCTION living.s4_bind_actor(text,text,text,text,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_register_request(text,text,text,text,text,text,bigint,bigint,text,uuid,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_resolve_approver(text,text,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_assert_fixture_promoter(text,text) OWNER TO living_owner;
ALTER FUNCTION living.s4_request_digest(living.s4_promotion_requests,text,living.s4_eligibility) OWNER TO living_owner;
ALTER FUNCTION living.s4_promote_v1(text,text,uuid) OWNER TO living_owner;
ALTER FUNCTION living.s4_readback_v1(text,text,uuid) OWNER TO living_owner;
ALTER FUNCTION living.s4_reject_append_only() OWNER TO living_owner;

REVOKE ALL ON FUNCTION living.s4_frame_field(bytea,text,boolean),
 living.s4_fingerprint_v1(text,text,text,text,text,bigint,bigint,uuid,text,text,uuid,text,text,text),
 living.s4_bind_actor(text,text,text,text,text),
 living.s4_parse_uuid_v1(text),
 living.s4_register_request(text,text,text,text,text,text,bigint,bigint,text,uuid,text),
 living.s4_resolve_approver(text,text,text),living.s4_assert_fixture_promoter(text,text),
 living.s4_request_digest(living.s4_promotion_requests,text,living.s4_eligibility),
 living.s4_promote_v1(text,text,uuid),living.s4_readback_v1(text,text,uuid),
 living.s4_reject_request_mutation(),living.s4_reject_append_only()
 FROM PUBLIC,living_worker,living_reader,living_promoter,
 living_publisher,living_s4_fixture_promoter,living_s4_fixture_verifier;
GRANT EXECUTE ON FUNCTION living.s4_bind_actor(text,text,text,text,text),
 living.s4_register_request(text,text,text,text,text,text,bigint,bigint,text,uuid,text)
 TO living_owner;
GRANT EXECUTE ON FUNCTION living.s4_register_eligibility(text,text,uuid,text,uuid,uuid,text,text),
 living.s4_revoke_eligibility(text,text,uuid) TO living_s4_fixture_verifier;
GRANT EXECUTE ON FUNCTION living.s4_promote_v1(text,text,uuid),
 living.s4_readback_v1(text,text,uuid) TO living_s4_fixture_promoter;

COMMIT;
