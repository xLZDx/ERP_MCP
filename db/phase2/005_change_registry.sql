-- R2/G1 S13 skeleton, part 2: registries and evidence for the change ledger of
-- docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md (revision 6, frozen). Applies after 004.
-- Closes these contract gaps WITHOUT editing 004 (the 004 file is untouched):
--  (1) principal registry: principal -> person, capabilities approver/operator/recovery_witness/
--      requester, active flag; person independence used by approve / issue_approval_nonce /
--      operator_resolve / witness_cosign / bind_duplicate_override instead of role-name distinctness.
--  (2) target registry (the 004 table change_ledger.targets, extended with permission_expires_at):
--      effects (claim, begin_apply, issue_permit, record_call) are limited to the registered
--      fingerprint, organization and class; refusal code TARGET_REJECTED.
--  (3) epoch dependencies: per-key epochs, bump_epoch, a change records epoch_dependencies and only
--      listed ones void it; T15 revoke_change / revoke_stale.
--  (4) signed evidence records (FIELD, MOVEMENT, VERSION, AUTH_RECEIPT, COMPLETION_PROOF,
--      OBSERVATION) + record_evidence; *_signed wrappers let verify / complete / resolve_unknown /
--      witness_cosign reference them.
--  (5) read_status and read_evidence (auditor / requester scoped, RLS on evidence_records).
--  (6) business-key duplicate detection in validate (DUPLICATE_PARKED), duplicate_override honored
--      only when an independent approver bound it, UPDATE_DRAFT key-change re-check.
--  (7) amount_consumed(document, grant) incl. repair; claim reserves only the unconsumed part of a POST.
-- 004 functions whose behavior is EXTENDED here with CREATE OR REPLACE (same signatures, same
-- grants, every 004 behavior kept, new checks only added): propose, validate, approve,
-- issue_approval_nonce, claim, begin_apply, issue_permit, record_call, witness_cosign,
-- operator_resolve.
-- COMPATIBILITY SWITCH: change_ledger.registry_policy.enforced (per tenant/company, default false =
-- LEGACY: a principal that is not registered keeps the 004 role-name rules; a registered one is held
-- to the registry). change_ledger.enforce_registry() flips it to ENFORCED, one way: then every actor
-- must be registered with the right capability, a change must declare its target class and the writer
-- must have observed the matching target (observe_target) before begin_apply.
-- SKELETON limits (named, not hidden): the evidence "signature" is a keyed SHA-256 digest over the
-- binding hash with a ledger-held key (verifier_keys.key_material, readable by nobody but the owner);
-- it stands in for the asymmetric signature of D9 which is still an open input.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('005', ARRAY['001','002','003','004']) THEN
EXECUTE $body$

-- ================================================================== table extensions
ALTER TABLE change_ledger.records ADD COLUMN IF NOT EXISTS epoch_dependencies jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE change_ledger.records ADD COLUMN IF NOT EXISTS declared_target_class text;
ALTER TABLE change_ledger.targets ADD COLUMN IF NOT EXISTS permission_expires_at timestamptz;
ALTER TABLE change_ledger.targets ADD COLUMN IF NOT EXISTS registered_by text;

CREATE TABLE IF NOT EXISTS change_ledger.epochs(
 tenant_id text NOT NULL, company_id text NOT NULL,
 epoch_key text NOT NULL CHECK(length(epoch_key) BETWEEN 1 AND 200),
 value bigint NOT NULL DEFAULT 0 CHECK(value>=0),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,epoch_key)
);

CREATE TABLE IF NOT EXISTS change_ledger.principals(
 tenant_id text NOT NULL, company_id text NOT NULL,
 principal text NOT NULL CHECK(length(principal)>0),
 person_id text NOT NULL CHECK(length(person_id)>0),
 capabilities text[] NOT NULL DEFAULT ARRAY[]::text[]
  CHECK(capabilities <@ ARRAY['approver','operator','recovery_witness','requester']::text[]),
 active boolean NOT NULL DEFAULT true,
 registered_by text, updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,principal)
);
CREATE INDEX IF NOT EXISTS principals_person_idx ON change_ledger.principals(tenant_id,company_id,person_id);

CREATE TABLE IF NOT EXISTS change_ledger.registry_policy(
 tenant_id text NOT NULL, company_id text NOT NULL,
 enforced boolean NOT NULL DEFAULT false,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_by text,
 PRIMARY KEY(tenant_id,company_id)
);

CREATE TABLE IF NOT EXISTS change_ledger.verifier_keys(
 tenant_id text NOT NULL, company_id text NOT NULL,
 key_id text NOT NULL CHECK(length(key_id)>0),
 role_name text NOT NULL CHECK(length(role_name)>0),
 key_material text NOT NULL CHECK(length(key_material)>=16),
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
 registered_by text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,key_id)
);

CREATE TABLE IF NOT EXISTS change_ledger.evidence_records(
 evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL,
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 kind text NOT NULL CHECK(kind IN ('FIELD','MOVEMENT','VERSION','AUTH_RECEIPT','COMPLETION_PROOF','OBSERVATION')),
 content_hash text NOT NULL CHECK(content_hash ~ '^[a-f0-9]{64}$'),
 observed_at timestamptz NOT NULL,
 content jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(octet_length(content::text)<=65536),
 signer_key_id text NOT NULL, signature text NOT NULL CHECK(length(signature)>0),
 binding_hash text NOT NULL CHECK(binding_hash ~ '^[a-f0-9]{64}$'),
 recorded_by text NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(change_id,kind,content_hash)
);
CREATE INDEX IF NOT EXISTS evidence_change_idx ON change_ledger.evidence_records(change_id);
DROP TRIGGER IF EXISTS evidence_immutable ON change_ledger.evidence_records;
CREATE TRIGGER evidence_immutable BEFORE UPDATE OR DELETE ON change_ledger.evidence_records
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();
DROP TRIGGER IF EXISTS evidence_no_truncate ON change_ledger.evidence_records;
CREATE TRIGGER evidence_no_truncate BEFORE TRUNCATE ON change_ledger.evidence_records
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS change_ledger.business_keys(
 change_id uuid PRIMARY KEY REFERENCES change_ledger.records(change_id),
 tenant_id text NOT NULL, company_id text NOT NULL,
 key_hash text NOT NULL CHECK(key_hash ~ '^[a-f0-9]{64}$'),
 override_of text, override_justification text,
 override_digest text NOT NULL CHECK(override_digest ~ '^[a-f0-9]{64}$'),
 override_required boolean NOT NULL DEFAULT false,
 declared_by text NOT NULL, declared_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((override_of IS NULL) = (override_justification IS NULL))
);
CREATE INDEX IF NOT EXISTS business_keys_hash_idx ON change_ledger.business_keys(tenant_id,company_id,key_hash);

CREATE TABLE IF NOT EXISTS change_ledger.override_bindings(
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 approver text NOT NULL,
 override_digest text NOT NULL CHECK(override_digest ~ '^[a-f0-9]{64}$'),
 bound_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(change_id,approver,override_digest)
);
DROP TRIGGER IF EXISTS override_bindings_immutable ON change_ledger.override_bindings;
CREATE TRIGGER override_bindings_immutable BEFORE UPDATE OR DELETE ON change_ledger.override_bindings
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS change_ledger.target_observations(
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 generation bigint NOT NULL,
 observed_fingerprint text NOT NULL, observed_class text NOT NULL,
 observed_by text NOT NULL, observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(change_id,generation)
);

-- ================================================================== registry helpers
CREATE OR REPLACE FUNCTION change_ledger.registry_enforced(t text, c text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT coalesce((SELECT p.enforced FROM change_ledger.registry_policy p
  WHERE p.tenant_id=t AND p.company_id=c),false)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.person_of(t text, c text, p text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT pr.person_id FROM change_ledger.principals pr
  WHERE pr.tenant_id=t AND pr.company_id=c AND pr.principal=p
$fn$;

-- Two principals are the same actor when they are the same subject or map to the same person.
CREATE OR REPLACE FUNCTION change_ledger.same_person(t text, c text, a text, b text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT a IS NOT DISTINCT FROM b
  OR (change_ledger.person_of(t,c,a) IS NOT NULL
      AND change_ledger.person_of(t,c,a) IS NOT DISTINCT FROM change_ledger.person_of(t,c,b))
$fn$;

-- A registered principal must be active and hold the capability; an unregistered one is refused
-- only when the registry is ENFORCED (LEGACY keeps the 004 role-based entitlement).
CREATE OR REPLACE FUNCTION change_ledger.assert_capability(t text, c text, p text, cap text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE pr change_ledger.principals%ROWTYPE;
BEGIN
 SELECT * INTO pr FROM change_ledger.principals x WHERE x.tenant_id=t AND x.company_id=c AND x.principal=p;
 IF FOUND THEN
  IF NOT pr.active OR NOT (cap = ANY(pr.capabilities)) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 ELSIF change_ledger.registry_enforced(t,c) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.assert_independent(t text, c text, a text, b text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF change_ledger.same_person(t,c,a,b) THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
 IF change_ledger.registry_enforced(t,c)
  AND (change_ledger.person_of(t,c,a) IS NULL OR change_ledger.person_of(t,c,b) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.is_operator(who text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT pg_catalog.pg_has_role(who::name,'operator_role','USAGE')
$fn$;

-- ================================================================== epochs
CREATE OR REPLACE FUNCTION change_ledger.epoch_value(t text, c text, k text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT coalesce((SELECT e.value FROM change_ledger.epochs e
  WHERE e.tenant_id=t AND e.company_id=c AND e.epoch_key=k),0)
$fn$;

-- True when every listed dependency still has the recorded value (unlisted keys never matter).
CREATE OR REPLACE FUNCTION change_ledger.epoch_deps_current(t text, c text, deps jsonb) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT NOT EXISTS(SELECT 1 FROM jsonb_each_text(coalesce(deps,'{}'::jsonb)) d
  WHERE change_ledger.epoch_value(t,c,d.key) <> d.value::bigint)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.bump_epoch_internal(t text, c text, k text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE v bigint;
BEGIN
 INSERT INTO change_ledger.epochs(tenant_id,company_id,epoch_key,value) VALUES(t,c,k,1)
 ON CONFLICT(tenant_id,company_id,epoch_key) DO UPDATE SET value=change_ledger.epochs.value+1,
  updated_at=clock_timestamp()
 RETURNING value INTO v;
 PERFORM change_ledger.append_event(t,c,NULL,'EPOCH_BUMPED',jsonb_build_object('key',k,'value',v));
 RETURN v;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.bump_epoch(t text, c text, p_key text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF NOT change_ledger.is_operator(change_ledger.caller_role()) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 200 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 RETURN change_ledger.bump_epoch_internal(t,c,p_key);
END $fn$;

-- ================================================================== registry administration (operator)
CREATE OR REPLACE FUNCTION change_ledger.register_principal(
 t text, c text, p_principal text, p_person_id text, p_capabilities text[], p_active boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_principal IS NULL OR p_principal='' OR p_person_id IS NULL OR p_person_id=''
  OR p_capabilities IS NULL OR p_active IS NULL
  OR NOT (p_capabilities <@ ARRAY['approver','operator','recovery_witness','requester']::text[]) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_principal) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities,active,registered_by)
 VALUES(t,c,p_principal,p_person_id,p_capabilities,p_active,who)
 ON CONFLICT(tenant_id,company_id,principal) DO UPDATE SET person_id=EXCLUDED.person_id,
  capabilities=EXCLUDED.capabilities, active=EXCLUDED.active, registered_by=EXCLUDED.registered_by,
  updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'PRINCIPAL_REGISTERED',
  jsonb_build_object('principal',p_principal,'person_id',p_person_id,'capabilities',to_jsonb(p_capabilities),
   'active',p_active,'by',who));
 RETURN change_ledger.bump_epoch_internal(t,c,'principal:'||p_principal);
END $fn$;

-- One-way switch: after this an unregistered actor is refused everywhere.
CREATE OR REPLACE FUNCTION change_ledger.enforce_registry(t text, c text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF change_ledger.registry_enforced(t,c) THEN RETURN true; END IF;
 INSERT INTO change_ledger.registry_policy(tenant_id,company_id,enforced,updated_by) VALUES(t,c,true,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET enforced=true, updated_by=who, updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_ENFORCED',jsonb_build_object('by',who));
 RETURN true;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.norm_target_class(p text) RETURNS text
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT CASE upper(p) WHEN 'CLONE' THEN 'DISPOSABLE_CLONE' WHEN 'DISPOSABLE_CLONE' THEN 'DISPOSABLE_CLONE'
  WHEN 'STAGING' THEN 'STAGING' WHEN 'PROD' THEN 'PRODUCTION' WHEN 'PRODUCTION' THEN 'PRODUCTION' ELSE NULL END
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_target(
 t text, c text, p_base text, p_org text, p_class text, p_status text, p_permission_expires_at timestamptz
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; cls text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 cls := change_ledger.norm_target_class(p_class);
 IF p_base IS NULL OR p_base='' OR p_org IS NULL OR p_org='' OR cls IS NULL
  OR p_status IS NULL OR p_status NOT IN ('ACTIVE','REVOKED') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class,
  status,permission_expires_at,registered_by)
 VALUES(t,c,p_base,p_org,cls,p_status,p_permission_expires_at,who)
 ON CONFLICT(tenant_id,company_id,base_fingerprint) DO UPDATE SET organization_ref=EXCLUDED.organization_ref,
  target_class=EXCLUDED.target_class, status=EXCLUDED.status,
  permission_expires_at=EXCLUDED.permission_expires_at, registered_by=EXCLUDED.registered_by,
  epoch=change_ledger.targets.epoch+1;
 PERFORM change_ledger.append_event(t,c,NULL,'TARGET_REGISTERED',
  jsonb_build_object('base',p_base,'organization',p_org,'class',cls,'status',p_status,'by',who));
 RETURN change_ledger.bump_epoch_internal(t,c,'target:'||p_base);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_verifier_key(
 t text, c text, p_key_id text, p_role_name text, p_key_material text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; ex change_ledger.verifier_keys%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_key_id IS NULL OR p_key_id='' OR p_role_name IS NULL OR p_key_material IS NULL
  OR length(p_key_material)<16
  OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_role_name) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO ex FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND THEN
  IF ex.key_material IS DISTINCT FROM p_key_material OR ex.role_name IS DISTINCT FROM p_role_name THEN
   RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
  END IF;
  RETURN;
 END IF;
 INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,registered_by)
 VALUES(t,c,p_key_id,p_role_name,p_key_material,who);
 PERFORM change_ledger.append_event(t,c,NULL,'VERIFIER_KEY_REGISTERED',
  jsonb_build_object('key_id',p_key_id,'role',p_role_name,'by',who));
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_verifier_key(t text, c text, p_key_id text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; n integer;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 UPDATE change_ledger.verifier_keys k SET status='REVOKED'
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id AND k.status='ACTIVE';
 GET DIAGNOSTICS n = ROW_COUNT;
 IF n=1 THEN
  PERFORM change_ledger.append_event(t,c,NULL,'VERIFIER_KEY_REVOKED',jsonb_build_object('key_id',p_key_id,'by',who));
 END IF;
END $fn$;

-- ================================================================== target effect guard (CT4)
-- Effects are limited to the registered fingerprint, organization and class. LEGACY: a change that
-- declared no class is checked against fingerprint/organization/status/permission only; ENFORCED: the
-- class declaration is mandatory.
CREATE OR REPLACE FUNCTION change_ledger.assert_target_effect(
 t text, c text, p_base text, p_org text, p_declared_class text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE tg change_ledger.targets%ROWTYPE;
BEGIN
 SELECT * INTO tg FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base;
 IF NOT FOUND OR tg.status<>'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tg.permission_expires_at IS NOT NULL AND tg.permission_expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 IF tg.organization_ref IS DISTINCT FROM p_org THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF p_declared_class IS NULL THEN
  IF change_ledger.registry_enforced(t,c) THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 ELSIF p_declared_class IS DISTINCT FROM tg.target_class THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.declare_target_class(t text, c text, p_change_id uuid, p_class text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; cls text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 cls := change_ledger.norm_target_class(p_class);
 IF cls IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,cls);
 UPDATE change_ledger.records SET declared_target_class=cls, updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'TARGET_CLASS_DECLARED',jsonb_build_object('class',cls));
 RETURN cls;
END $fn$;

-- The writer authenticates the base by connecting and reports what it found; a mismatch with the
-- registry is refused. ENFORCED begin_apply requires a matching observation for the current generation.
CREATE OR REPLACE FUNCTION change_ledger.observe_target(
 t text, c text, p_token_id uuid, p_fingerprint text, p_class text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE; cls text; tg change_ledger.targets%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO tok FROM change_ledger.claim_tokens WHERE token_id=p_token_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=tok.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tok.generation<>rec.claim_generation OR tok.state<>'ISSUED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 cls := change_ledger.norm_target_class(p_class);
 IF cls IS NULL OR p_fingerprint IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO tg FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=rec.base_fingerprint;
 IF NOT FOUND OR p_fingerprint IS DISTINCT FROM tg.base_fingerprint OR cls IS DISTINCT FROM tg.target_class THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,
  coalesce(rec.declared_target_class,cls));
 INSERT INTO change_ledger.target_observations(change_id,generation,observed_fingerprint,observed_class,observed_by)
 VALUES(rec.change_id,tok.generation,p_fingerprint,cls,change_ledger.caller_role())
 ON CONFLICT(change_id,generation) DO NOTHING;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'TARGET_OBSERVED',
  jsonb_build_object('generation',tok.generation,'class',cls));
 RETURN true;
END $fn$;

-- ================================================================== epoch dependencies on a change
CREATE OR REPLACE FUNCTION change_ledger.add_epoch_dependency(t text, c text, p_change_id uuid, p_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; deps jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 200 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';   -- the approval digest covers epoch_dependencies
 END IF;
 IF rec.epoch_dependencies ? p_key THEN RETURN rec.epoch_dependencies; END IF;
 deps := rec.epoch_dependencies || jsonb_build_object(p_key,change_ledger.epoch_value(t,c,p_key));
 UPDATE change_ledger.records SET epoch_dependencies=deps, updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'EPOCH_DEPENDENCY_ADDED',jsonb_build_object('key',p_key));
 RETURN deps;
END $fn$;

-- T15 core: voids/revokes an APPROVED or CLAIMED (pre-dispatch) change and releases lock, lease and
-- reservation (a repair hands the target lock back to its failed parent, section 4.2).
CREATE OR REPLACE FUNCTION change_ledger.revoke_core(t text, c text, p_change_id uuid, p_cause text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_auth text;
BEGIN
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.authorization_state IN ('VOIDED','REVOKED') THEN RETURN rec.authorization_state; END IF;
 IF rec.authorization_state NOT IN ('APPROVED','CLAIMED') OR rec.execution_state<>'NOT_STARTED'
  OR rec.dispatch_state IN ('PERMITTED','DISPATCHED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_cause='EPOCH_DEPENDENCY' AND change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';   -- unrelated epoch changes never void
 END IF;
 new_auth := CASE WHEN p_cause='EPOCH_DEPENDENCY' THEN 'VOIDED' ELSE 'REVOKED' END;
 IF rec.authorization_state='CLAIMED' THEN
  UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE change_id=p_change_id AND state='ISSUED';
  PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
 END IF;
 UPDATE change_ledger.records SET authorization_state=new_auth, execution_state='NOT_STARTED',
  updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'REVOKED',
  jsonb_build_object('cause',p_cause,'authorization',new_auth,'was_claimed',rec.authorization_state='CLAIMED'));
 RETURN new_auth;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_change(t text, c text, p_change_id uuid, p_cause text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF p_cause IS NULL OR p_cause NOT IN ('SESSION_REVOKED','ROLE_REVOKED','APPROVER_REVOKED','EPOCH_DEPENDENCY') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT change_ledger.is_operator(who) AND p_cause<>'EPOCH_DEPENDENCY' THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 RETURN change_ledger.revoke_core(t,c,p_change_id,p_cause);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_stale(t text, c text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n integer := 0; r record;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 FOR r IN SELECT x.change_id FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.authorization_state IN ('APPROVED','CLAIMED')
    AND x.execution_state='NOT_STARTED' AND x.dispatch_state NOT IN ('PERMITTED','DISPATCHED')
    AND NOT change_ledger.epoch_deps_current(t,c,x.epoch_dependencies)
   ORDER BY x.created_at LOOP
  PERFORM change_ledger.revoke_core(t,c,r.change_id,'EPOCH_DEPENDENCY');
  n := n+1;
 END LOOP;
 RETURN n;
END $fn$;

-- ================================================================== business key / duplicates (R-07)
CREATE OR REPLACE FUNCTION change_ledger.declare_business_key(
 t text, c text, p_change_id uuid, p_key_hash text, p_override_of text DEFAULT NULL,
 p_justification text DEFAULT NULL
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; ex change_ledger.business_keys%ROWTYPE; dg text; prior text;
 key_changed boolean; had_ex boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 IF p_key_hash IS NULL OR p_key_hash !~ '^[a-f0-9]{64}$'
  OR (p_override_of IS NULL) <> (p_justification IS NULL)
  OR (p_override_of IS NOT NULL AND (p_override_of='' OR p_justification='')) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.kind NOT IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';   -- the key and the override are inside the approved digest
 END IF;
 dg := encode(sha256(convert_to(p_change_id::text||':'||p_key_hash||':'||coalesce(p_override_of,'')||':'||
   coalesce(p_justification,''),'UTF8')),'hex');
 SELECT * INTO ex FROM change_ledger.business_keys WHERE change_id=p_change_id;
 had_ex := FOUND;
 IF had_ex AND ex.override_digest=dg THEN RETURN rec.lifecycle; END IF;   -- idempotent
 -- UPDATE_DRAFT: does the key differ from the key last used for the same document?
 SELECT b.key_hash INTO prior FROM change_ledger.business_keys b
  JOIN change_ledger.records o ON o.change_id=b.change_id
  WHERE o.tenant_id=t AND o.company_id=c AND o.target_ref IS NOT DISTINCT FROM rec.target_ref
   AND rec.target_ref IS NOT NULL AND o.change_id<>p_change_id
  ORDER BY o.created_at DESC LIMIT 1;
 key_changed := (had_ex AND ex.key_hash IS DISTINCT FROM p_key_hash)
  OR (prior IS NOT NULL AND prior IS DISTINCT FROM p_key_hash);
 INSERT INTO change_ledger.business_keys(change_id,tenant_id,company_id,key_hash,override_of,
  override_justification,override_digest,override_required,declared_by)
 VALUES(p_change_id,t,c,p_key_hash,p_override_of,p_justification,dg,false,change_ledger.caller_role())
 ON CONFLICT(change_id) DO UPDATE SET key_hash=EXCLUDED.key_hash, override_of=EXCLUDED.override_of,
  override_justification=EXCLUDED.override_justification, override_digest=EXCLUDED.override_digest,
  override_required=false, declared_at=clock_timestamp();
 IF rec.lifecycle='VALIDATED' THEN
  -- a key (or override) change invalidates the earlier duplicate check: validate must run again
  UPDATE change_ledger.records SET lifecycle='PROPOSED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'BUSINESS_KEY_DECLARED',
  jsonb_build_object('key_changed',coalesce(key_changed,false),'override',p_override_of IS NOT NULL,
   'revalidate',rec.lifecycle='VALIDATED'));
 RETURN CASE WHEN rec.lifecycle='VALIDATED' THEN 'PROPOSED' ELSE rec.lifecycle END;
END $fn$;

-- The approver binds the exact override (change, key, duplicate_of, justification) before approving.
CREATE OR REPLACE FUNCTION change_ledger.bind_duplicate_override(t text, c text, p_change_id uuid, p_override_digest text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; bk change_ledger.business_keys%ROWTYPE; who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle<>'VALIDATED' OR rec.authorization_state<>'NONE' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF pg_has_role(who::name, rec.requester::name, 'MEMBER') THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'approver');
 PERFORM change_ledger.assert_independent(t,c,who,rec.requester);
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF NOT FOUND OR NOT bk.override_required OR p_override_digest IS DISTINCT FROM bk.override_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 INSERT INTO change_ledger.override_bindings(change_id,approver,override_digest)
 VALUES(p_change_id,who,bk.override_digest) ON CONFLICT DO NOTHING;
 PERFORM change_ledger.append_event(t,c,p_change_id,'OVERRIDE_BOUND',jsonb_build_object('approver',who));
 RETURN true;
END $fn$;

-- ================================================================== amount_consumed (CT13, section 8)
-- Net amount of POST effects still standing on the document under the grant: CONSUMED POST
-- reservations, minus those whose effect was reversed by an APPLIED UNPOST (plain or repair). The
-- failed parent of a repair stays CONSUMED as history; the repair's APPLIED reconciles it here.
CREATE OR REPLACE FUNCTION change_ledger.amount_consumed(t text, c text, p_document text, p_grant_id uuid)
RETURNS numeric LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE v numeric;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT coalesce(sum(r.amount),0) INTO v
  FROM change_ledger.reservations r JOIN change_ledger.records p ON p.change_id=r.change_id
  WHERE p.tenant_id=t AND p.company_id=c AND p.target_ref=p_document AND p.kind='POST'
   AND r.grant_id=p_grant_id AND r.state='CONSUMED'
   AND NOT EXISTS(SELECT 1 FROM change_ledger.records u
    WHERE u.tenant_id=t AND u.company_id=c AND u.kind='UNPOST' AND u.execution_state='APPLIED'
     AND (u.repair_for=p.change_id OR u.parent_change_id=p.change_id));
 RETURN v;
END $fn$;

-- ================================================================== signed evidence (section 9)
CREATE OR REPLACE FUNCTION change_ledger.evidence_binding(p_change_id uuid, p_kind text, p_content_hash text,
 p_observed_at timestamptz) RETURNS text
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT encode(sha256(convert_to(p_change_id::text||':'||p_kind||':'||p_content_hash||':'||
  to_char(p_observed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'UTF8')),'hex')
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.record_evidence(
 t text, c text, p_change_id uuid, p_kind text, p_content_hash text, p_observed_at timestamptz,
 p_content jsonb, p_key_id text, p_binding_hash text, p_signature text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; rec change_ledger.records%ROWTYPE; vk change_ledger.verifier_keys%ROWTYPE; want text;
 eid uuid; cls text; is_worker boolean; is_writer boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF p_kind IS NULL OR p_kind NOT IN ('FIELD','MOVEMENT','VERSION','AUTH_RECEIPT','COMPLETION_PROOF','OBSERVATION')
  OR p_content_hash IS NULL OR p_content_hash !~ '^[a-f0-9]{64}$' OR p_observed_at IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 is_worker := pg_has_role(who::name,'worker_role','USAGE');
 is_writer := pg_has_role(who::name,'writer_role','USAGE');
 IF NOT (is_worker OR (is_writer AND p_kind='COMPLETION_PROOF')) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_key_id IS NULL OR p_key_id='' OR p_signature IS NULL OR p_signature='' OR p_binding_hash IS NULL THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 want := change_ledger.evidence_binding(p_change_id,p_kind,p_content_hash,p_observed_at);
 IF p_binding_hash IS DISTINCT FROM want THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_signature IS DISTINCT FROM encode(sha256(convert_to(vk.key_material||':'||want,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 IF p_observed_at > clock_timestamp()+interval '5 minutes' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF p_kind='COMPLETION_PROOF' THEN
  cls := p_content->>'class';
  -- proof class a is the writer's own record, class b the worker's host observation (section 4);
  -- class c (forced termination) stays disabled.
  IF cls IS NULL OR cls NOT IN ('a','b') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF (cls='a' AND NOT is_writer) OR (cls='b' AND NOT is_worker) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 ELSIF p_kind='AUTH_RECEIPT' THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.approvals a WHERE a.change_id=p_change_id
    AND a.approval_id::text = p_content->>'approval_id') THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 END IF;
 INSERT INTO change_ledger.evidence_records(tenant_id,company_id,change_id,kind,content_hash,observed_at,
  content,signer_key_id,signature,binding_hash,recorded_by)
 VALUES(t,c,p_change_id,p_kind,p_content_hash,p_observed_at,coalesce(p_content,'{}'::jsonb),p_key_id,
  p_signature,want,who)
 ON CONFLICT(change_id,kind,content_hash) DO NOTHING
 RETURNING evidence_id INTO eid;
 IF eid IS NULL THEN
  SELECT e.evidence_id INTO eid FROM change_ledger.evidence_records e
   WHERE e.change_id=p_change_id AND e.kind=p_kind AND e.content_hash=p_content_hash;
  RETURN eid;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'EVIDENCE_RECORDED',
  jsonb_build_object('evidence_id',eid,'kind',p_kind,'content_hash',p_content_hash,'key_id',p_key_id));
 RETURN eid;
END $fn$;

-- Loads a signed record that must exist, belong to this change and scope, and have the given kind.
CREATE OR REPLACE FUNCTION change_ledger.evidence_ref(t text, c text, p_change_id uuid, p_evidence_id uuid, p_kind text)
RETURNS change_ledger.evidence_records LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ev change_ledger.evidence_records%ROWTYPE;
BEGIN
 IF p_evidence_id IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 SELECT * INTO ev FROM change_ledger.evidence_records e
  WHERE e.evidence_id=p_evidence_id AND e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.kind=p_kind;
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 RETURN ev;
END $fn$;

-- T13/T14 referencing signed records: VERIFIED needs field, movement and version evidence read AFTER the effect.
CREATE OR REPLACE FUNCTION change_ledger.verify_signed(
 t text, c text, p_change_id uuid, p_field uuid, p_movement uuid, p_version uuid, p_passed boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; f change_ledger.evidence_records; m change_ledger.evidence_records;
 v change_ledger.evidence_records; effect_at timestamptz; refs jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF rec.verification_state='VERIFIED' THEN RETURN rec.verification_state; END IF;
 IF rec.execution_state<>'APPLIED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF p_passed IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF p_passed OR p_field IS NOT NULL THEN f := change_ledger.evidence_ref(t,c,p_change_id,p_field,'FIELD'); END IF;
 IF p_passed OR p_movement IS NOT NULL THEN m := change_ledger.evidence_ref(t,c,p_change_id,p_movement,'MOVEMENT'); END IF;
 IF p_passed OR p_version IS NOT NULL THEN v := change_ledger.evidence_ref(t,c,p_change_id,p_version,'VERSION'); END IF;
 SELECT max(e.recorded_at) INTO effect_at FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.event_type IN ('COMPLETE_SUCCESS','RESOLVE_UNKNOWN','OPERATOR_RESOLVE');
 IF p_passed AND (f.observed_at<effect_at OR m.observed_at<effect_at OR v.observed_at<effect_at) THEN
  RAISE EXCEPTION 'VERIFY_FAILED';   -- a read that predates the effect proves nothing
 END IF;
 refs := jsonb_build_object('field',f.evidence_id,'movement',m.evidence_id,'version',v.evidence_id);
 RETURN change_ledger.verify(t,c,p_change_id,refs,p_passed);
END $fn$;

-- T7/T8/T9 referencing the writer's signed completion record (proof class a).
CREATE OR REPLACE FUNCTION change_ledger.complete_signed(
 t text, c text, p_change_id uuid, p_generation bigint, p_outcome text, p_completion uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ev change_ledger.evidence_records; ref jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_outcome IS NULL OR p_outcome NOT IN ('SUCCESS','PRE_WRITE_REFUSAL','UNKNOWN') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_outcome<>'UNKNOWN' OR p_completion IS NOT NULL THEN
  ev := change_ledger.evidence_ref(t,c,p_change_id,p_completion,'COMPLETION_PROOF');
  IF ev.content->>'class' IS DISTINCT FROM 'a' OR NOT pg_has_role(ev.recorded_by::name,'writer_role','USAGE') THEN
   RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
  END IF;
  ref := jsonb_build_object('evidence_id',ev.evidence_id,'content_hash',ev.content_hash);
 END IF;
 RETURN change_ledger.complete(t,c,p_change_id,p_generation,p_outcome,coalesce(ref,'{}'::jsonb),
  CASE WHEN p_outcome='PRE_WRITE_REFUSAL' THEN ref ELSE NULL END);
END $fn$;

-- T10/T11/T12 referencing signed observation / completion-proof records.
CREATE OR REPLACE FUNCTION change_ledger.resolve_unknown_signed(
 t text, c text, p_change_id uuid, p_observation uuid, p_completion uuid, p_found boolean, p_attributed boolean DEFAULT false
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE obs change_ledger.evidence_records; cp change_ledger.evidence_records; body jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 obs := change_ledger.evidence_ref(t,c,p_change_id,p_observation,'OBSERVATION');
 body := jsonb_build_object('observation_evidence',obs.evidence_id);
 IF p_completion IS NOT NULL THEN
  cp := change_ledger.evidence_ref(t,c,p_change_id,p_completion,'COMPLETION_PROOF');
  body := body || jsonb_build_object('completion_proof',
   jsonb_build_object('class',cp.content->>'class','evidence_id',cp.evidence_id));
 END IF;
 RETURN change_ledger.resolve_unknown(t,c,p_change_id,body,p_found,p_attributed);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.witness_cosign_signed(t text, c text, p_change_id uuid, p_completion uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cp change_ledger.evidence_records;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 cp := change_ledger.evidence_ref(t,c,p_change_id,p_completion,'COMPLETION_PROOF');
 RETURN change_ledger.witness_cosign(t,c,p_change_id,jsonb_build_object('class',cp.content->>'class',
  'evidence_id',cp.evidence_id,'attribution_proof',coalesce((cp.content->>'attribution_proof')::boolean,false)));
END $fn$;

-- ================================================================== reads (section 2: auditor / requester)
CREATE OR REPLACE FUNCTION change_ledger.read_status(t text, c text, p_change_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; ap record;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF NOT (pg_has_role(who::name,'auditor_role','USAGE') OR pg_has_role(who::name,'approver_role','USAGE')
         OR who IS NOT DISTINCT FROM rec.requester) THEN
  RAISE EXCEPTION 'CHANGE_NOT_FOUND';   -- another requester's change is not leaked
 END IF;
 SELECT a.approval_id, a.approver INTO ap FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 RETURN jsonb_build_object('change_id',rec.change_id,'kind',rec.kind,'requester',rec.requester,
  'base_fingerprint',rec.base_fingerprint,'organization_ref',rec.organization_ref,
  'lifecycle',rec.lifecycle,'authorization',rec.authorization_state,'execution',rec.execution_state,
  'verification',rec.verification_state,'call_ownership',rec.call_ownership,'attribution',rec.attribution,
  'effect_known',rec.effect_known,'reservation',rec.reservation_state,'dispatch',rec.dispatch_state,
  'claim_generation',rec.claim_generation,'expires_at',rec.expires_at,
  'epoch_dependencies',rec.epoch_dependencies,
  'epoch_current',change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies),
  'declared_target_class',rec.declared_target_class,
  'approval_id',ap.approval_id,'approver',ap.approver,
  'open_holds',(SELECT count(*) FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=rec.base_fingerprint AND h.released_at IS NULL),
  'evidence_count',(SELECT count(*) FROM change_ledger.evidence_records e WHERE e.change_id=p_change_id));
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.read_evidence(t text, c text, p_change_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF NOT (pg_has_role(who::name,'auditor_role','USAGE') OR who IS NOT DISTINCT FROM rec.requester) THEN
  RAISE EXCEPTION 'CHANGE_NOT_FOUND';
 END IF;
 RETURN coalesce((SELECT jsonb_agg(jsonb_build_object('evidence_id',e.evidence_id,'kind',e.kind,
   'content_hash',e.content_hash,'observed_at',e.observed_at,'content',e.content,
   'signer_key_id',e.signer_key_id,'signature',e.signature,'binding_hash',e.binding_hash,
   'recorded_by',e.recorded_by) ORDER BY e.recorded_at, e.evidence_id)
  FROM change_ledger.evidence_records e WHERE e.change_id=p_change_id),'[]'::jsonb);
END $fn$;

-- ================================================================== extended 004 operations
-- propose: + registered organization, permission expiry, requester capability, epoch snapshot.
CREATE OR REPLACE FUNCTION change_ledger.propose(
 t text, c text, p_change_id uuid, p_kind text, p_base_fingerprint text, p_organization_ref text,
 p_requester text, p_request_id text, p_payload_digest text, p_target_ref text,
 p_target_version text, p_parent_change_id uuid, p_expires_at timestamptz,
 p_repair_for uuid DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE existing change_ledger.records%ROWTYPE; tgt_epoch bigint; tgt_status text; tgt_org text; tgt_exp timestamptz;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_kind IS NULL OR p_base_fingerprint IS NULL
  OR p_organization_ref IS NULL OR p_requester IS NULL OR p_request_id IS NULL
  OR p_payload_digest IS NULL OR p_expires_at IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_repair_for IS NOT NULL AND (p_kind<>'UNPOST' OR p_parent_change_id IS DISTINCT FROM p_repair_for) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT status, epoch, organization_ref, permission_expires_at INTO tgt_status, tgt_epoch, tgt_org, tgt_exp
  FROM change_ledger.targets
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=p_base_fingerprint FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tgt_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_org IS DISTINCT FROM p_organization_ref THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_exp IS NOT NULL AND tgt_exp<=clock_timestamp() THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.assert_capability(t,c,p_requester,'requester');
 SELECT * INTO existing FROM change_ledger.records
  WHERE tenant_id=t AND company_id=c AND requester=p_requester AND kind=p_kind
   AND base_fingerprint=p_base_fingerprint AND organization_ref=p_organization_ref
   AND request_id=p_request_id;
 IF FOUND THEN
  IF existing.payload_digest IS DISTINCT FROM p_payload_digest THEN
   RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
  END IF;
  RETURN existing.change_id;
 END IF;
 INSERT INTO change_ledger.records(
  change_id,tenant_id,company_id,base_fingerprint,organization_ref,kind,requester,request_id,
  payload_digest,target_ref,target_version,parent_change_id,repair_for,auth_epoch_at_proposal,expires_at,
  epoch_dependencies)
 VALUES(p_change_id,t,c,p_base_fingerprint,p_organization_ref,p_kind,p_requester,p_request_id,
  p_payload_digest,p_target_ref,p_target_version,p_parent_change_id,p_repair_for,tgt_epoch,p_expires_at,
  jsonb_build_object('target:'||p_base_fingerprint,change_ledger.epoch_value(t,c,'target:'||p_base_fingerprint),
   'principal:'||p_requester,change_ledger.epoch_value(t,c,'principal:'||p_requester)));
 PERFORM change_ledger.append_event(t,c,p_change_id,'PROPOSED',
  jsonb_build_object('kind',p_kind,'payload_digest',p_payload_digest));
 RETURN p_change_id;
END $fn$;

-- validate: + server-side business-key duplicate detection. The 004 caller flag p_duplicate still
-- parks (it can never un-park); a declared key colliding with another live VALIDATED change parks
-- unless a matching duplicate_override is declared (then approve needs the approver's binding).
CREATE OR REPLACE FUNCTION change_ledger.validate(
 t text, c text, p_change_id uuid, p_duplicate boolean, p_budget_ok boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; bk change_ledger.business_keys%ROWTYPE; colls text[];
 dup boolean; ovr boolean := false;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.lifecycle = 'VALIDATED' THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle = 'DUPLICATE_PARKED' THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle <> 'PROPOSED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF NOT p_budget_ok THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 dup := coalesce(p_duplicate,false);
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF FOUND AND rec.kind IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN
  -- serialize concurrent validations of the same business key: the second sees the first
  PERFORM pg_advisory_xact_lock(hashtextextended(t||':'||c||':'||rec.base_fingerprint||':'||bk.key_hash,1));
  SELECT coalesce(array_agg(o.change_id::text ORDER BY o.created_at),ARRAY[]::text[]) INTO colls
   FROM change_ledger.records o JOIN change_ledger.business_keys ob ON ob.change_id=o.change_id
   WHERE o.tenant_id=t AND o.company_id=c AND o.base_fingerprint=rec.base_fingerprint
    AND o.organization_ref=rec.organization_ref AND o.change_id<>rec.change_id
    AND ob.key_hash=bk.key_hash AND o.lifecycle='VALIDATED'
    AND o.authorization_state NOT IN ('VOIDED','REVOKED','EXPIRED')
    AND o.execution_state NOT IN ('FAILED_APPLY','ROLLBACK_REFUSED')
    AND NOT (rec.kind='UPDATE_DRAFT' AND rec.target_ref IS NOT NULL
             AND o.target_ref IS NOT DISTINCT FROM rec.target_ref);
  IF cardinality(colls)>0 THEN
   IF bk.override_of IS NOT NULL AND cardinality(colls)=1 AND bk.override_of=colls[1] THEN
    ovr := true;
    UPDATE change_ledger.business_keys SET override_required=true WHERE change_id=p_change_id;
   ELSE
    dup := true;
   END IF;
  END IF;
 END IF;
 UPDATE change_ledger.records SET
  lifecycle=CASE WHEN dup THEN 'DUPLICATE_PARKED' ELSE 'VALIDATED' END,
  updated_at=clock_timestamp()
 WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
 RETURNING lifecycle INTO rec.lifecycle;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VALIDATED',
  jsonb_build_object('lifecycle',rec.lifecycle,'override_pending',ovr));
 RETURN rec.lifecycle;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.issue_approval_nonce(t text, c text, p_change_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; n text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF who IS NOT DISTINCT FROM rec.requester OR pg_has_role(who::name, rec.requester::name, 'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'approver');
 PERFORM change_ledger.assert_independent(t,c,who,rec.requester);
 n := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
 INSERT INTO change_ledger.approval_nonces(nonce,change_id,approver,expires_at)
 VALUES(n,p_change_id,who,clock_timestamp()+interval '10 minutes');
 RETURN n;
END $fn$;

-- approve: person independence (requester and, for a repair, the failed parent's requester),
-- approver capability, epoch dependencies unchanged, approver-bound duplicate override; the
-- approver's own principal epoch joins the change's dependencies.
CREATE OR REPLACE FUNCTION change_ledger.approve(
 t text, c text, p_change_id uuid, p_nonce text, p_digest text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_approver text; nrow change_ledger.approval_nonces%ROWTYPE;
 aid uuid; bk change_ledger.business_keys%ROWTYPE; parent_req text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 v_approver := change_ledger.caller_role();
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle <> 'VALIDATED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF rec.authorization_state='APPROVED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF v_approver IS NOT DISTINCT FROM rec.requester
  OR pg_has_role(v_approver::name, rec.requester::name, 'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,v_approver,'approver');
 PERFORM change_ledger.assert_independent(t,c,v_approver,rec.requester);
 IF rec.repair_for IS NOT NULL THEN
  SELECT p.requester INTO parent_req FROM change_ledger.records p WHERE p.change_id=rec.repair_for;
  IF change_ledger.same_person(t,c,v_approver,parent_req) THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
 END IF;
 IF p_digest IS DISTINCT FROM rec.payload_digest THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 SELECT * INTO nrow FROM change_ledger.approval_nonces n
  WHERE n.nonce=p_nonce AND n.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.approver IS DISTINCT FROM v_approver THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 IF nrow.expires_at<=clock_timestamp() THEN
  UPDATE change_ledger.approval_nonces n SET state='EXPIRED' WHERE n.nonce=p_nonce;
  RAISE EXCEPTION 'APPROVAL_EXPIRED';
 END IF;
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF FOUND AND bk.override_required AND NOT EXISTS(SELECT 1 FROM change_ledger.override_bindings ob
   WHERE ob.change_id=p_change_id AND ob.approver=v_approver AND ob.override_digest=bk.override_digest) THEN
  RAISE EXCEPTION 'DUPLICATE_SUSPECTED';   -- the override is honored only when this approver bound it
 END IF;
 UPDATE change_ledger.approval_nonces n SET state='CONSUMED' WHERE n.nonce=p_nonce;
 INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision)
 VALUES(p_change_id,v_approver,p_nonce,p_digest,'APPROVE') RETURNING approval_id INTO aid;
 UPDATE change_ledger.records SET authorization_state='APPROVED',
  epoch_dependencies=epoch_dependencies || jsonb_build_object('principal:'||v_approver,
   change_ledger.epoch_value(t,c,'principal:'||v_approver)),
  updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVED',
  jsonb_build_object('approval_id',aid,'digest',p_digest));
 RETURN aid;
END $fn$;

-- claim: + APPROVAL_VOIDED, epoch dependencies, target effect guard, declared business key bound to
-- the key lock, and a POST reserves only the part of its amount not already consumed on the document.
CREATE OR REPLACE FUNCTION change_ledger.claim(
 t text, c text, p_change_id uuid, p_key_hash text, p_grant_id uuid, p_amount numeric,
 p_counts_create_update boolean, p_counts_post boolean
) RETURNS change_ledger.claim_tokens LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_requester text; gen bigint;
 tok change_ledger.claim_tokens%ROWTYPE; g change_ledger.grants%ROWTYPE;
 parent change_ledger.records%ROWTYPE; tref text; used_amount numeric; used_cu integer; used_post integer;
 bk change_ledger.business_keys%ROWTYPE; key_h text; eff_amount numeric;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 v_requester := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF v_requester IS DISTINCT FROM rec.requester THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state IN ('VOIDED','REVOKED') THEN RAISE EXCEPTION 'APPROVAL_VOIDED'; END IF;
 IF rec.authorization_state <> 'APPROVED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 IF change_ledger.blocking_hold(t,c,rec.base_fingerprint,rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 key_h := p_key_hash;
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF FOUND THEN
  IF key_h IS NULL THEN key_h := bk.key_hash;
  ELSIF key_h IS DISTINCT FROM bk.key_hash THEN RAISE EXCEPTION 'DIGEST_MISMATCH';
  END IF;
 END IF;
 tref := coalesce(rec.target_ref,p_change_id::text);
 IF rec.repair_for IS NOT NULL THEN
  SELECT * INTO parent FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=rec.repair_for FOR UPDATE;
  IF NOT FOUND OR parent.verification_state<>'FAILED_VERIFY' OR parent.effect_known IS DISTINCT FROM 'YES'
   OR parent.target_ref IS DISTINCT FROM rec.target_ref
   OR parent.base_fingerprint<>rec.base_fingerprint
   OR NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=rec.base_fingerprint AND h.cause='FAILED_VERIFY_HALT'
     AND h.change_id=rec.repair_for AND h.released_at IS NULL) THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 ELSIF rec.parent_change_id IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.records
    WHERE change_id=rec.parent_change_id AND verification_state='VERIFIED') THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 END IF;
 BEGIN
  IF p_grant_id IS NOT NULL THEN
   SELECT * INTO g FROM change_ledger.grants WHERE grant_id=p_grant_id AND tenant_id=t AND company_id=c
    FOR UPDATE;
   IF NOT FOUND OR g.status<>'ACTIVE' OR clock_timestamp()<g.window_start
    OR clock_timestamp()>=g.window_end THEN
    RAISE EXCEPTION 'BUDGET_EXCEEDED';
   END IF;
   eff_amount := coalesce(p_amount,0);
   IF rec.kind='POST' THEN
    eff_amount := greatest(eff_amount - change_ledger.amount_consumed(t,c,tref,p_grant_id),0);
   END IF;
   SELECT coalesce(sum(r.amount),0),
          count(*) FILTER (WHERE r.counts_create_update), count(*) FILTER (WHERE r.counts_post)
    INTO used_amount, used_cu, used_post
    FROM change_ledger.reservations r
    WHERE r.grant_id=p_grant_id AND r.state IN ('RESERVED','CONSUMED') AND r.change_id<>p_change_id;
   IF used_amount+eff_amount > g.amount_limit
    OR used_cu+(CASE WHEN coalesce(p_counts_create_update,false) THEN 1 ELSE 0 END) > g.count_limit
    OR used_post+(CASE WHEN coalesce(p_counts_post,false) THEN 1 ELSE 0 END) > g.post_count_limit THEN
    RAISE EXCEPTION 'BUDGET_EXCEEDED';
   END IF;
   INSERT INTO change_ledger.reservations(change_id,grant_id,amount,counts_create_update,counts_post)
   VALUES(p_change_id,p_grant_id,eff_amount,coalesce(p_counts_create_update,false),
    coalesce(p_counts_post,false))
   ON CONFLICT(change_id) DO UPDATE SET grant_id=EXCLUDED.grant_id, amount=EXCLUDED.amount,
    counts_create_update=EXCLUDED.counts_create_update, counts_post=EXCLUDED.counts_post,
    state='RESERVED', reserved_at=clock_timestamp()
    WHERE change_ledger.reservations.state='RELEASED';
  END IF;
  IF rec.repair_for IS NOT NULL THEN
   IF NOT change_ledger.handoff_target_lock(t,c,rec.base_fingerprint,tref,rec.repair_for,p_change_id) THEN
    RAISE EXCEPTION 'LOCK_BUSY';
   END IF;
  ELSE
   INSERT INTO change_ledger.target_locks(tenant_id,company_id,base_fingerprint,target_ref,owner_change_id)
   VALUES(t,c,rec.base_fingerprint,tref,p_change_id);
  END IF;
  IF key_h IS NOT NULL THEN
   INSERT INTO change_ledger.key_locks(tenant_id,company_id,base_fingerprint,key_hash,owner_change_id)
   VALUES(t,c,rec.base_fingerprint,key_h,p_change_id);
  END IF;
  INSERT INTO change_ledger.writer_leases(tenant_id,company_id,base_fingerprint,owner_change_id)
  VALUES(t,c,rec.base_fingerprint,p_change_id);
 EXCEPTION WHEN unique_violation THEN
  RAISE EXCEPTION 'LOCK_BUSY';
 END;
 gen := rec.claim_generation + 1;
 UPDATE change_ledger.records SET authorization_state='CLAIMED', execution_state='NOT_STARTED',
  claim_generation=gen, reservation_state=CASE WHEN p_grant_id IS NOT NULL THEN 'RESERVED'
   ELSE reservation_state END, updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 INSERT INTO change_ledger.claim_tokens(change_id,generation) VALUES(p_change_id,gen)
  RETURNING * INTO tok;
 PERFORM change_ledger.append_event(t,c,p_change_id,'CLAIMED',
  jsonb_build_object('generation',gen,'token_id',tok.token_id));
 RETURN tok;
END $fn$;

-- begin_apply: + epoch dependencies equal the claim epoch, target effect guard, and (ENFORCED) a
-- matching observe_target record of this generation.
CREATE OR REPLACE FUNCTION change_ledger.begin_apply(
 t text, c text, p_token_id uuid, p_call_id uuid, p_writer_host text, p_onec_session text
) RETURNS change_ledger.claim_tokens LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE; caller text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 caller := change_ledger.caller_role();
 SELECT * INTO tok FROM change_ledger.claim_tokens WHERE token_id=p_token_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=tok.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF caller IS DISTINCT FROM rec.requester AND NOT pg_has_role(caller::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF tok.generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF tok.state='CONSUMED' THEN
  IF rec.dispatch_state<>'DISPATCHED' THEN RETURN tok; END IF;
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 IF tok.state<>'ISSUED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.authorization_state<>'CLAIMED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 IF change_ledger.blocking_hold(t,c,rec.base_fingerprint,rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 IF change_ledger.registry_enforced(t,c) AND NOT EXISTS(SELECT 1 FROM change_ledger.target_observations o
   WHERE o.change_id=rec.change_id AND o.generation=tok.generation
    AND o.observed_fingerprint=rec.base_fingerprint) THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 UPDATE change_ledger.claim_tokens SET state='CONSUMED' WHERE token_id=p_token_id;
 UPDATE change_ledger.records SET execution_state='APPLYING', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
 INSERT INTO change_ledger.dispatch_permits(change_id,generation,state,call_id)
 VALUES(rec.change_id,tok.generation,'NOT_PERMITTED',p_call_id)
 ON CONFLICT(change_id,generation) DO NOTHING;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'APPLYING',
  jsonb_build_object('call_id',p_call_id,'writer_host',p_writer_host,'onec_session',p_onec_session));
 RETURN tok;
END $fn$;

-- issue_permit: + target effect guard (a target revoked or expired after begin_apply gets no permit).
CREATE OR REPLACE FUNCTION change_ledger.issue_permit(
 t text, c text, p_change_id uuid, p_generation bigint
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
 cp_seq bigint; applying_seq bigint; digest text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 SELECT max(e.seq) INTO applying_seq FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.event_type='APPLYING';
 SELECT k.seq INTO cp_seq FROM change_ledger.checkpoints k
  JOIN change_ledger.events e ON e.tenant_id=k.tenant_id AND e.company_id=k.company_id
   AND e.seq=k.ledger_seq AND e.hash=k.head_hash
  WHERE k.tenant_id=t AND k.company_id=c AND k.sink_kind='REAL' AND k.read_back_confirmed
   AND k.ledger_seq>=applying_seq
  ORDER BY k.seq DESC LIMIT 1;
 IF cp_seq IS NULL THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 digest := encode(sha256(convert_to(p_change_id::text||':'||p_generation::text||':'||cp_seq::text,
  'UTF8')),'hex');
 UPDATE change_ledger.dispatch_permits SET state='PERMITTED', checkpoint_seq=cp_seq,
  permit_digest=digest, issued_at=clock_timestamp(),
  expires_at=clock_timestamp()+interval '60 seconds'
  WHERE change_id=p_change_id AND generation=p_generation AND state='NOT_PERMITTED'
 RETURNING * INTO dp;
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 UPDATE change_ledger.records SET dispatch_state='PERMITTED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PERMITTED',
  jsonb_build_object('generation',p_generation,'checkpoint_seq',cp_seq));
 RETURN jsonb_build_object('change_id',dp.change_id,'generation',dp.generation,
  'permit_digest',dp.permit_digest,'checkpoint_seq',dp.checkpoint_seq,
  'expires_at',to_char(dp.expires_at,'YYYY-MM-DD"T"HH24:MI:SS.US'));
END $fn$;

-- record_call: + target effect guard inside the PERMITTED branch (the writer's own check before DISPATCHED).
CREATE OR REPLACE FUNCTION change_ledger.record_call(
 t text, c text, p_change_id uuid, p_generation bigint, p_call_id uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits WHERE change_id=p_change_id AND generation=p_generation;
 IF NOT FOUND OR dp.call_id IS DISTINCT FROM p_call_id THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF dp.state='NOT_PERMITTED' THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF dp.state='PERMITTED' THEN
  PERFORM change_ledger.assert_switch_off(t,c);
  PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
  IF dp.expires_at<=clock_timestamp() THEN RETURN false; END IF;
 END IF;
 IF NOT change_ledger.dispatch_cas(p_change_id,p_generation,'PERMITTED','DISPATCHED') THEN
  RETURN false;
 END IF;
 UPDATE change_ledger.records SET dispatch_state='DISPATCHED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCHED',
  jsonb_build_object('generation',p_generation,'call_id',p_call_id));
 RETURN true;
END $fn$;

-- witness_cosign: + recovery_witness capability of the signer.
CREATE OR REPLACE FUNCTION change_ledger.witness_cosign(
 t text, c text, p_change_id uuid, p_completion_proof jsonb
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cid uuid; signer text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 signer := change_ledger.caller_role();
 IF NOT EXISTS(SELECT 1 FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=p_change_id) THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF p_completion_proof IS NULL THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 PERFORM change_ledger.assert_capability(t,c,signer,'recovery_witness');
 INSERT INTO change_ledger.witness_cosigns(change_id,signer,completion_proof)
 VALUES(p_change_id,signer,p_completion_proof) RETURNING cosign_id INTO cid;
 RETURN cid;
END $fn$;

-- operator_resolve: operator, witness, requester and approver are compared as PERSONS (aliases of one
-- person count as one), operator / recovery_witness capabilities are required of registered actors.
CREATE OR REPLACE FUNCTION change_ledger.operator_resolve(
 t text, c text, p_change_id uuid, p_cosign_id uuid, p_present boolean, p_attributed boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_operator text; cs change_ledger.witness_cosigns%ROWTYPE;
 approver_subject text; new_exec text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 v_operator := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'TRIAGE_REQUIRED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_change_id AND w.consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 IF coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 SELECT a.approver INTO approver_subject FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 IF change_ledger.same_person(t,c,v_operator,cs.signer)
  OR change_ledger.same_person(t,c,v_operator,rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,rec.requester)
  OR (change_ledger.same_person(t,c,v_operator,approver_subject)
      AND change_ledger.same_person(t,c,cs.signer,approver_subject))
 THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,v_operator,'operator');
 PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
 IF change_ledger.registry_enforced(t,c) AND (change_ledger.person_of(t,c,v_operator) IS NULL
  OR change_ledger.person_of(t,c,cs.signer) IS NULL OR change_ledger.person_of(t,c,rec.requester) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_present AND p_attributed AND coalesce((cs.completion_proof->>'attribution_proof')::boolean,false) IS NOT TRUE THEN
  RAISE EXCEPTION 'ATTRIBUTION_UNPROVEN';
 END IF;
 UPDATE change_ledger.witness_cosigns w SET consumed_at=clock_timestamp() WHERE w.cosign_id=p_cosign_id;
 DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 IF NOT p_present THEN
  new_exec:='FAILED_APPLY';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state='RELEASED',
   call_ownership='PROVEN_FINISHED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 ELSE
  new_exec:='APPLIED';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state='CONSUMED',
   call_ownership='PROVEN_FINISHED',
   attribution=CASE WHEN p_attributed THEN 'PROVEN' ELSE 'UNPROVEN_OPERATOR_ATTESTED' END,
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
 END IF;
 UPDATE change_ledger.holds SET released_at=clock_timestamp(),
  release_evidence=cs.completion_proof
  WHERE change_id=p_change_id AND cause='CALL_OWNERSHIP' AND released_at IS NULL;
 PERFORM change_ledger.append_event(t,c,p_change_id,'OPERATOR_RESOLVE',
  jsonb_build_object('present',p_present,'attributed',p_attributed,'cosign_id',p_cosign_id));
 RETURN new_exec;
END $fn$;

-- ================================================================== definer wiring + privileges
DO $fn$
DECLARE f record;
BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='change_ledger'
 LOOP
  EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp',f.sig);
 END LOOP;
END $fn$;

DO $fn$
DECLARE o record;
BEGIN
 FOR o IN SELECT c.oid::regclass AS rel FROM pg_catalog.pg_class c
   JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='change_ledger' AND c.relkind IN ('r','p')
 LOOP EXECUTE format('ALTER TABLE %s OWNER TO ledger_owner',o.rel); END LOOP;
 FOR o IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='change_ledger'
 LOOP EXECUTE format('ALTER FUNCTION %s OWNER TO ledger_owner',o.sig); END LOOP;
END $fn$;

REVOKE ALL ON ALL TABLES IN SCHEMA change_ledger FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA change_ledger FROM PUBLIC;

-- Read access (RLS-filtered): the auditor reads the registries and records; the requester reads its
-- own evidence rows (policy below). No runtime role has any DML on any table.
GRANT SELECT ON change_ledger.epochs, change_ledger.principals, change_ledger.registry_policy,
 change_ledger.evidence_records, change_ledger.business_keys, change_ledger.override_bindings,
 change_ledger.target_observations TO auditor_role;
GRANT SELECT(tenant_id,company_id,key_id,role_name,status,created_at) ON change_ledger.verifier_keys TO auditor_role;
GRANT SELECT ON change_ledger.evidence_records TO requester_role;

-- Pure helpers used inside RLS policies / by every role.
GRANT EXECUTE ON FUNCTION change_ledger.person_of(text,text,text), change_ledger.same_person(text,text,text,text),
 change_ledger.epoch_value(text,text,text), change_ledger.registry_enforced(text,text)
 TO requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role;

GRANT EXECUTE ON FUNCTION
 change_ledger.declare_business_key(text,text,uuid,text,text,text),
 change_ledger.declare_target_class(text,text,uuid,text),
 change_ledger.add_epoch_dependency(text,text,uuid,text)
 TO requester_role;
GRANT EXECUTE ON FUNCTION change_ledger.bind_duplicate_override(text,text,uuid,text) TO approver_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.register_principal(text,text,text,text,text[],boolean),
 change_ledger.enforce_registry(text,text),
 change_ledger.register_target(text,text,text,text,text,text,timestamptz),
 change_ledger.register_verifier_key(text,text,text,text,text),
 change_ledger.revoke_verifier_key(text,text,text),
 change_ledger.bump_epoch(text,text,text),
 change_ledger.revoke_change(text,text,uuid,text)
 TO operator_role;
GRANT EXECUTE ON FUNCTION change_ledger.revoke_change(text,text,uuid,text), change_ledger.revoke_stale(text,text),
 change_ledger.record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text),
 change_ledger.verify_signed(text,text,uuid,uuid,uuid,uuid,boolean),
 change_ledger.resolve_unknown_signed(text,text,uuid,uuid,uuid,boolean,boolean)
 TO worker_role;
GRANT EXECUTE ON FUNCTION change_ledger.record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text),
 change_ledger.complete_signed(text,text,uuid,bigint,text,uuid),
 change_ledger.observe_target(text,text,uuid,text,text)
 TO writer_role;
GRANT EXECUTE ON FUNCTION change_ledger.witness_cosign_signed(text,text,uuid,uuid) TO operator_role;
GRANT EXECUTE ON FUNCTION change_ledger.read_status(text,text,uuid) TO requester_role, approver_role, auditor_role;
GRANT EXECUTE ON FUNCTION change_ledger.read_evidence(text,text,uuid) TO requester_role, auditor_role;
GRANT EXECUTE ON FUNCTION change_ledger.amount_consumed(text,text,text,uuid)
 TO operator_role, worker_role, auditor_role;

-- ================================================================== RLS
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY['epochs','principals','registry_policy','verifier_keys','evidence_records',
  'business_keys','override_bindings','target_observations'] LOOP
  EXECUTE format('ALTER TABLE change_ledger.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS owner_all ON change_ledger.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS scope_isolation ON change_ledger.%I',tbl);
  EXECUTE format('CREATE POLICY owner_all ON change_ledger.%I FOR ALL TO ledger_owner USING (true) WITH CHECK (true)',tbl);
 END LOOP;
 FOREACH tbl IN ARRAY ARRAY['epochs','principals','registry_policy','verifier_keys','business_keys'] LOOP
  EXECUTE format('CREATE POLICY scope_isolation ON change_ledger.%I FOR ALL USING (change_ledger.row_in_scope(tenant_id,company_id)) WITH CHECK (change_ledger.row_in_scope(tenant_id,company_id))',tbl);
 END LOOP;
END $fn$;
-- Evidence: in scope AND (auditor, or the requester of the change).
CREATE POLICY scope_isolation ON change_ledger.evidence_records FOR ALL USING (
 change_ledger.row_in_scope(tenant_id,company_id)
 AND (pg_has_role(current_user,'auditor_role','USAGE')
  OR EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=evidence_records.change_id
     AND r.requester=current_user::text)));
CREATE POLICY scope_isolation ON change_ledger.override_bindings FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=override_bindings.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));
CREATE POLICY scope_isolation ON change_ledger.target_observations FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=target_observations.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));

$body$;
END IF;
END $mig$;
COMMIT;
