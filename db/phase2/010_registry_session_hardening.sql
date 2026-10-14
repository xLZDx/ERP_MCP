-- R2/G1 S13 hardening, batch C (docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md, the three OPEN items left by B3 round 1).
-- Applies after 009. Apply ONLY to a verified disposable PostgreSQL database (checksum precondition:
-- living.record_migration). NON-GATING PROTOTYPE: not gate evidence.
--
--  C1 Registry changes need two persons. The registry is the principal registry, the target registry and the
--     verifier-key registry (the registry policy itself, enforce_registry, only ever tightens and stays single-operator).
--     A change that WIDENS the registry is applied only through propose_registry_change (operator A) and
--     approve_registry_change (operator B): B must be another person (same_person), another session (session_user, so
--     SET ROLE cannot hide it), registered and active with the operator capability, and must quote the digest of the
--     stored change. Proposal and approval are rows of two immutable tables (registry_changes,
--     registry_change_approvals: no UPDATE, DELETE, TRUNCATE) and two events (REGISTRY_CHANGE_PROPOSED,
--     REGISTRY_CHANGE_APPLIED) that name both persons. Replays are idempotent: the same proposal returns the same id,
--     a second approval by the same approver returns the stored result and never applies twice.
--     The direct functions register_principal / register_target / register_verifier_key keep their signatures. They
--     still apply, in one operator call, only what cannot widen anything: narrowing a principal (same person, no new
--     capability, not re-activated), revoking a registered target or shortening its permission, an exact repeat, and - while fewer than two distinct
--     active operator persons exist - registering operator / recovery_witness principals so that a second person can
--     exist at all (BOOTSTRAP). Everything else raises TWO_PERSON_REQUIRED. revoke_verifier_key, bump_epoch and
--     enforce_registry only narrow or tighten and stay single-operator.
--  C2 Session independence of the cosign paths. witness_cosigns and hold_cosigns record the session_user of the signer
--     (BEFORE INSERT trigger, not caller-controlled). A witness whose session maps to the same person as the session
--     that proposed the change is refused at cosign time. Whoever CONSUMES a cosign (operator_resolve,
--     operator_close_failed_verify through consume_two_person_cosign, the two-person ANCHOR_GAP release_hold) must run in
--     a session that is another person than the signer's session and than the proposing session of the change: the
--     check sits in a BEFORE UPDATE trigger on consumed_at, so it covers every present and future consumer. A cosign with
--     no recorded session (written before 010) cannot be consumed by a non-superuser session (fail closed). A superuser
--     session is exempt exactly as in assert_session_independent. kill_switch has no counter-party (single actor, no
--     cosign): nothing to compare.
--  C3 NOT implemented: see the report; the findings text names no concrete bypass and none could be reproduced.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('010', ARRAY['001','002','003','004','005','006','007','008','009']) THEN
EXECUTE $body$

-- ================================================================== C1 storage
CREATE TABLE IF NOT EXISTS change_ledger.registry_changes(
 change_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('PRINCIPAL','TARGET','VERIFIER_KEY')),
 params jsonb NOT NULL,            -- normalized; may hold key material, so it is not readable by runtime roles
 summary jsonb NOT NULL,           -- the same without secrets: what an approving operator reads
 params_digest text NOT NULL CHECK(params_digest ~ '^[a-f0-9]{64}$'),
 proposer text NOT NULL, proposer_person text, proposer_session text NOT NULL,
 proposed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS registry_changes_scope_idx ON change_ledger.registry_changes(tenant_id,company_id,params_digest);
CREATE TABLE IF NOT EXISTS change_ledger.registry_change_approvals(
 change_id uuid PRIMARY KEY REFERENCES change_ledger.registry_changes(change_id),
 tenant_id text NOT NULL, company_id text NOT NULL,
 approver text NOT NULL, approver_person text, approver_session text NOT NULL,
 proposer text NOT NULL, proposer_person text, proposer_session text NOT NULL,
 params_digest text NOT NULL CHECK(params_digest ~ '^[a-f0-9]{64}$'),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY['registry_changes','registry_change_approvals'] LOOP
  EXECUTE format('ALTER TABLE change_ledger.%I OWNER TO ledger_owner',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS owner_all ON change_ledger.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS scope_read ON change_ledger.%I',tbl);
  EXECUTE format('CREATE POLICY owner_all ON change_ledger.%I FOR ALL TO ledger_owner USING (true) WITH CHECK (true)',tbl);
  EXECUTE format('CREATE POLICY scope_read ON change_ledger.%I FOR SELECT USING (change_ledger.row_in_scope(tenant_id,company_id))',tbl);
  EXECUTE format('DROP TRIGGER IF EXISTS %I ON change_ledger.%I',tbl||'_immutable',tbl);
  EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON change_ledger.%I FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation()',tbl||'_immutable',tbl);
  EXECUTE format('DROP TRIGGER IF EXISTS %I ON change_ledger.%I',tbl||'_no_truncate',tbl);
  EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON change_ledger.%I FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation()',tbl||'_no_truncate',tbl);
 END LOOP;
END $fn$;
GRANT SELECT(change_id,tenant_id,company_id,kind,summary,params_digest,proposer,proposer_person,proposer_session,
 proposed_at,expires_at) ON change_ledger.registry_changes TO operator_role, auditor_role;
GRANT SELECT ON change_ledger.registry_change_approvals TO operator_role, auditor_role;

-- ================================================================== C1 normalization (one definition per kind)
CREATE OR REPLACE FUNCTION change_ledger.registry_ts_text(p timestamptz) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT to_char(p AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.registry_normalize(p_kind text, p jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE caps text[]; cls text; ts timestamptz; exp_txt text;
BEGIN
 IF p IS NULL OR jsonb_typeof(p) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF p_kind='PRINCIPAL' THEN
  IF jsonb_typeof(p->'principal') IS DISTINCT FROM 'string' OR p->>'principal'=''
   OR jsonb_typeof(p->'person_id') IS DISTINCT FROM 'string' OR p->>'person_id'=''
   OR jsonb_typeof(p->'capabilities') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p->'active') IS DISTINCT FROM 'boolean' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(p->'capabilities') e WHERE jsonb_typeof(e) IS DISTINCT FROM 'string') THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  caps := ARRAY(SELECT DISTINCT x FROM jsonb_array_elements_text(p->'capabilities') x ORDER BY x);
  IF NOT (caps <@ ARRAY['approver','operator','recovery_witness','requester']::text[]) THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p->>'principal') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  RETURN jsonb_build_object('principal',p->>'principal','person_id',p->>'person_id','capabilities',to_jsonb(caps),
   'active',(p->>'active')::boolean);
 ELSIF p_kind='TARGET' THEN
  IF jsonb_typeof(p->'base') IS DISTINCT FROM 'string' OR p->>'base'=''
   OR jsonb_typeof(p->'organization') IS DISTINCT FROM 'string' OR p->>'organization'=''
   OR jsonb_typeof(p->'class') IS DISTINCT FROM 'string'
   OR jsonb_typeof(p->'status') IS DISTINCT FROM 'string' OR p->>'status' NOT IN ('ACTIVE','REVOKED')
   OR coalesce(jsonb_typeof(p->'permission_expires_at'),'null') NOT IN ('string','null') THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  cls := change_ledger.norm_target_class(p->>'class');
  IF cls IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  exp_txt := NULL;
  IF jsonb_typeof(p->'permission_expires_at')='string' THEN
   BEGIN
    ts := (p->>'permission_expires_at')::timestamptz;
   EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'SCHEMA_INVALID';
   END;
   exp_txt := change_ledger.registry_ts_text(ts);
  END IF;
  RETURN jsonb_build_object('base',p->>'base','organization',p->>'organization','class',cls,'status',p->>'status',
   'permission_expires_at',to_jsonb(exp_txt));
 ELSIF p_kind='VERIFIER_KEY' THEN
  IF jsonb_typeof(p->'key_id') IS DISTINCT FROM 'string' OR p->>'key_id'=''
   OR jsonb_typeof(p->'role_name') IS DISTINCT FROM 'string'
   OR jsonb_typeof(p->'key_material') IS DISTINCT FROM 'string' OR length(p->>'key_material')<16
   OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p->>'role_name') THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  RETURN jsonb_build_object('key_id',p->>'key_id','role_name',p->>'role_name','key_material',p->>'key_material');
 END IF;
 RAISE EXCEPTION 'SCHEMA_INVALID';
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.registry_summary(p_kind text, p_norm jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT CASE WHEN p_kind='VERIFIER_KEY'
  THEN (p_norm - 'key_material') || jsonb_build_object('key_material_sha256',
        encode(sha256(convert_to(p_norm->>'key_material','UTF8')),'hex'))
  ELSE p_norm END
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.registry_change_digest(t text, c text, p_kind text, p_norm jsonb) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT encode(sha256(convert_to('S13-REGISTRY-CHANGE-1:'||t||':'||c||':'||p_kind||':'||p_norm::text,'UTF8')),'hex')
$fn$;

-- ================================================================== C1 cores (what a registry change does)
CREATE OR REPLACE FUNCTION change_ledger.register_principal_core(
 t text, c text, p_principal text, p_person_id text, p_capabilities text[], p_active boolean, who text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE v bigint;
BEGIN
 INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities,active,registered_by)
 VALUES(t,c,p_principal,p_person_id,p_capabilities,p_active,who)
 ON CONFLICT(tenant_id,company_id,principal) DO UPDATE SET person_id=EXCLUDED.person_id,
  capabilities=EXCLUDED.capabilities, active=EXCLUDED.active, registered_by=EXCLUDED.registered_by,
  updated_at=clock_timestamp();
 v := change_ledger.epoch_row_bump(t,c,'principal:'||p_principal);        -- row locks first, chain last
 PERFORM change_ledger.append_event(t,c,NULL,'PRINCIPAL_REGISTERED',
  jsonb_build_object('principal',p_principal,'person_id',p_person_id,'capabilities',to_jsonb(p_capabilities),
   'active',p_active,'by',who));
 PERFORM change_ledger.append_event(t,c,NULL,'EPOCH_BUMPED',
  jsonb_build_object('key','principal:'||p_principal,'value',v));
 RETURN v;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_target_core(
 t text, c text, p_base text, p_org text, p_class text, p_status text, p_permission_expires_at timestamptz, who text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE v bigint;
BEGIN
 INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class,
  status,permission_expires_at,registered_by)
 VALUES(t,c,p_base,p_org,p_class,p_status,p_permission_expires_at,who)
 ON CONFLICT(tenant_id,company_id,base_fingerprint) DO UPDATE SET organization_ref=EXCLUDED.organization_ref,
  target_class=EXCLUDED.target_class, status=EXCLUDED.status,
  permission_expires_at=EXCLUDED.permission_expires_at, registered_by=EXCLUDED.registered_by,
  epoch=change_ledger.targets.epoch+1;
 v := change_ledger.epoch_row_bump(t,c,'target:'||p_base);
 PERFORM change_ledger.append_event(t,c,NULL,'TARGET_REGISTERED',
  jsonb_build_object('base',p_base,'organization',p_org,'class',p_class,'status',p_status,'by',who));
 PERFORM change_ledger.append_event(t,c,NULL,'EPOCH_BUMPED',
  jsonb_build_object('key','target:'||p_base,'value',v));
 RETURN v;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_verifier_key_core(
 t text, c text, p_key_id text, p_role_name text, p_key_material text, who text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ex change_ledger.verifier_keys%ROWTYPE;
BEGIN
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

-- ================================================================== C1 the single-operator rule: only what cannot widen
CREATE OR REPLACE FUNCTION change_ledger.registry_operator_persons(t text, c text) RETURNS integer
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT count(DISTINCT p.person_id)::integer FROM change_ledger.principals p
  WHERE p.tenant_id=t AND p.company_id=c AND p.active AND 'operator'=ANY(p.capabilities)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.registry_single_ok(t text, c text, p_kind text, n jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE pr change_ledger.principals%ROWTYPE; tg change_ledger.targets%ROWTYPE; vk change_ledger.verifier_keys%ROWTYPE;
 caps text[]; act boolean; found_row boolean; exp_ts timestamptz;
BEGIN
 IF p_kind='PRINCIPAL' THEN
  caps := ARRAY(SELECT jsonb_array_elements_text(n->'capabilities'));
  act := (n->>'active')::boolean;
  SELECT * INTO pr FROM change_ledger.principals x WHERE x.tenant_id=t AND x.company_id=c AND x.principal=n->>'principal';
  found_row := FOUND;
  -- narrowing: the same person, no capability that was not there, not re-activated
  -- but an active operator or recovery witness keeps those capabilities and stays active: removing one is a
  -- two-person change, otherwise one operator could drop the second person and reopen the bootstrap rule below
  IF found_row AND pr.person_id=n->>'person_id' AND caps <@ pr.capabilities AND (NOT act OR pr.active)
   AND (NOT pr.active OR NOT (pr.capabilities && ARRAY['operator','recovery_witness']::text[])
        OR (act AND caps @> ARRAY(SELECT x FROM unnest(pr.capabilities) x
                                   WHERE x = ANY(ARRAY['operator','recovery_witness']::text[])))) THEN RETURN true; END IF;
  -- BOOTSTRAP: fewer than two operator persons exist, so a second one may be added by the only one
  IF act AND cardinality(caps)>0 AND caps <@ ARRAY['operator','recovery_witness']::text[]
   AND (NOT found_row OR pr.person_id=n->>'person_id')
   AND change_ledger.registry_operator_persons(t,c)<2 THEN RETURN true; END IF;
  RETURN false;
 ELSIF p_kind='TARGET' THEN
  SELECT * INTO tg FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=n->>'base';
  IF NOT FOUND THEN RETURN false; END IF;
  IF tg.organization_ref IS DISTINCT FROM n->>'organization' OR tg.target_class IS DISTINCT FROM n->>'class' THEN RETURN false; END IF;
  IF n->>'status'='REVOKED' THEN RETURN true; END IF;                                   -- revocation
  exp_ts := (n->>'permission_expires_at')::timestamptz;
  -- an exact repeat, or the same active target with a permission that expires no later than before
  RETURN tg.status='ACTIVE' AND (tg.permission_expires_at IS NOT DISTINCT FROM exp_ts
   OR (exp_ts IS NOT NULL AND (tg.permission_expires_at IS NULL OR exp_ts<=tg.permission_expires_at)));
 ELSIF p_kind='VERIFIER_KEY' THEN
  SELECT * INTO vk FROM change_ledger.verifier_keys x WHERE x.tenant_id=t AND x.company_id=c AND x.key_id=n->>'key_id';
  RETURN FOUND AND vk.role_name=n->>'role_name' AND vk.key_material=n->>'key_material';
 END IF;
 RETURN false;
END $fn$;

-- ================================================================== C1 direct functions (same signatures)
CREATE OR REPLACE FUNCTION change_ledger.register_principal(
 t text, c text, p_principal text, p_person_id text, p_capabilities text[], p_active boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; n jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 n := change_ledger.registry_normalize('PRINCIPAL',jsonb_build_object('principal',p_principal,'person_id',p_person_id,
   'capabilities',to_jsonb(p_capabilities),'active',p_active));
 IF NOT change_ledger.registry_single_ok(t,c,'PRINCIPAL',n) THEN RAISE EXCEPTION 'TWO_PERSON_REQUIRED'; END IF;
 RETURN change_ledger.register_principal_core(t,c,p_principal,p_person_id,p_capabilities,p_active,who);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_target(
 t text, c text, p_base text, p_org text, p_class text, p_status text, p_permission_expires_at timestamptz
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; n jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 n := change_ledger.registry_normalize('TARGET',jsonb_build_object('base',p_base,'organization',p_org,'class',p_class,
   'status',p_status,'permission_expires_at',to_jsonb(change_ledger.registry_ts_text(p_permission_expires_at))));
 IF NOT change_ledger.registry_single_ok(t,c,'TARGET',n) THEN RAISE EXCEPTION 'TWO_PERSON_REQUIRED'; END IF;
 RETURN change_ledger.register_target_core(t,c,p_base,p_org,n->>'class',p_status,p_permission_expires_at,who);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_verifier_key(
 t text, c text, p_key_id text, p_role_name text, p_key_material text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; n jsonb; ex change_ledger.verifier_keys%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 n := change_ledger.registry_normalize('VERIFIER_KEY',jsonb_build_object('key_id',p_key_id,'role_name',p_role_name,
   'key_material',p_key_material));
 -- the 005 contract: a registered key id with other material or role is FORBIDDEN_TRANSITION, not a two-person matter
 SELECT * INTO ex FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND AND (ex.key_material IS DISTINCT FROM p_key_material OR ex.role_name IS DISTINCT FROM p_role_name) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF NOT change_ledger.registry_single_ok(t,c,'VERIFIER_KEY',n) THEN RAISE EXCEPTION 'TWO_PERSON_REQUIRED'; END IF;
 PERFORM change_ledger.register_verifier_key_core(t,c,p_key_id,p_role_name,p_key_material,who);
END $fn$;

-- ================================================================== C1 propose / approve
CREATE OR REPLACE FUNCTION change_ledger.propose_registry_change(t text, c text, p_kind text, p_params jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; n jsonb; dg text; cid uuid; ex change_ledger.registry_changes%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_kind IS NULL OR p_kind NOT IN ('PRINCIPAL','TARGET','VERIFIER_KEY') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'operator');
 n := change_ledger.registry_normalize(p_kind,p_params);
 dg := change_ledger.registry_change_digest(t,c,p_kind,n);
 -- replay: the same operator (person) proposing the same change again gets the open proposal back
 SELECT * INTO ex FROM change_ledger.registry_changes x WHERE x.tenant_id=t AND x.company_id=c AND x.params_digest=dg
   AND x.expires_at>clock_timestamp() AND change_ledger.same_person(t,c,x.proposer,who)
   AND NOT EXISTS(SELECT 1 FROM change_ledger.registry_change_approvals a WHERE a.change_id=x.change_id)
  ORDER BY x.proposed_at DESC LIMIT 1;
 IF FOUND THEN RETURN ex.change_id; END IF;
 INSERT INTO change_ledger.registry_changes(tenant_id,company_id,kind,params,summary,params_digest,proposer,
  proposer_person,proposer_session,expires_at)
 VALUES(t,c,p_kind,n,change_ledger.registry_summary(p_kind,n),dg,who,change_ledger.person_of(t,c,who),
  session_user::text,clock_timestamp()+interval '24 hours') RETURNING change_id INTO cid;
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_CHANGE_PROPOSED',
  jsonb_build_object('registry_change_id',cid,'kind',p_kind,'digest',dg,'proposer',who,
   'proposer_person',change_ledger.person_of(t,c,who),'proposer_session',session_user::text,
   'summary',change_ledger.registry_summary(p_kind,n)));
 RETURN cid;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.approve_registry_change(t text, c text, p_change_id uuid, p_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; rc change_ledger.registry_changes%ROWTYPE; ap change_ledger.registry_change_approvals%ROWTYPE;
 v bigint; n jsonb; caps text[];
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_change_id IS NULL OR p_digest IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rc FROM change_ledger.registry_changes x WHERE x.change_id=p_change_id AND x.tenant_id=t AND x.company_id=c
  FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF p_digest IS DISTINCT FROM rc.params_digest THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 SELECT * INTO ap FROM change_ledger.registry_change_approvals a WHERE a.change_id=p_change_id;
 IF FOUND THEN                                                    -- replay: never applied twice
  IF change_ledger.same_person(t,c,ap.approver,who) THEN
   RETURN jsonb_build_object('registry_change_id',p_change_id,'kind',rc.kind,'digest',rc.params_digest,'epoch',NULL::bigint,
    'replay',true);
  END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF rc.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'operator');
 PERFORM change_ledger.assert_capability(t,c,rc.proposer,'operator');          -- the proposer must still be an operator
 PERFORM change_ledger.assert_independent(t,c,who,rc.proposer);
 PERFORM change_ledger.assert_session_independent(t,c,rc.proposer_session);
 n := rc.params;
 INSERT INTO change_ledger.registry_change_approvals(change_id,tenant_id,company_id,approver,approver_person,
  approver_session,proposer,proposer_person,proposer_session,params_digest)
 VALUES(p_change_id,t,c,who,change_ledger.person_of(t,c,who),session_user::text,rc.proposer,rc.proposer_person,
  rc.proposer_session,rc.params_digest);
 IF rc.kind='PRINCIPAL' THEN
  caps := ARRAY(SELECT jsonb_array_elements_text(n->'capabilities'));
  v := change_ledger.register_principal_core(t,c,n->>'principal',n->>'person_id',caps,(n->>'active')::boolean,who);
 ELSIF rc.kind='TARGET' THEN
  v := change_ledger.register_target_core(t,c,n->>'base',n->>'organization',n->>'class',n->>'status',
   (n->>'permission_expires_at')::timestamptz,who);
 ELSE
  PERFORM change_ledger.register_verifier_key_core(t,c,n->>'key_id',n->>'role_name',n->>'key_material',who);
  v := NULL;
 END IF;
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_CHANGE_APPLIED',
  jsonb_build_object('registry_change_id',p_change_id,'kind',rc.kind,'digest',rc.params_digest,
   'proposer',rc.proposer,'proposer_person',rc.proposer_person,'proposer_session',rc.proposer_session,
   'approver',who,'approver_person',change_ledger.person_of(t,c,who),'approver_session',session_user::text,
   'summary',change_ledger.registry_summary(rc.kind,n)));
 RETURN jsonb_build_object('registry_change_id',p_change_id,'kind',rc.kind,'digest',rc.params_digest,'epoch',v,'replay',false);
END $fn$;

-- ================================================================== C2 cosign session recording and independence
ALTER TABLE change_ledger.witness_cosigns ADD COLUMN IF NOT EXISTS signer_session text;
ALTER TABLE change_ledger.hold_cosigns ADD COLUMN IF NOT EXISTS signer_session text;

CREATE OR REPLACE FUNCTION change_ledger.cosign_session_is_exempt() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname=session_user AND r.rolsuper)
$fn$;

-- the signer's session is recorded by the database, never taken from the caller; a witness in the session of the
-- person that proposed the change is refused
CREATE OR REPLACE FUNCTION change_ledger.witness_cosign_session_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE r change_ledger.records%ROWTYPE;
BEGIN
 NEW.signer_session := session_user::text;
 SELECT * INTO r FROM change_ledger.records x WHERE x.change_id=NEW.change_id;
 IF FOUND THEN PERFORM change_ledger.assert_session_independent(r.tenant_id,r.company_id,r.requester_session); END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS witness_cosigns_session_guard ON change_ledger.witness_cosigns;
CREATE TRIGGER witness_cosigns_session_guard BEFORE INSERT ON change_ledger.witness_cosigns
 FOR EACH ROW EXECUTE FUNCTION change_ledger.witness_cosign_session_guard();

CREATE OR REPLACE FUNCTION change_ledger.hold_cosign_session_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 NEW.signer_session := session_user::text;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS hold_cosigns_session_guard ON change_ledger.hold_cosigns;
CREATE TRIGGER hold_cosigns_session_guard BEFORE INSERT ON change_ledger.hold_cosigns
 FOR EACH ROW EXECUTE FUNCTION change_ledger.hold_cosign_session_guard();

-- consumption: the session that consumes must be another person than the signer's session and than the proposing
-- session of the change
CREATE OR REPLACE FUNCTION change_ledger.witness_cosign_consume_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE r change_ledger.records%ROWTYPE;
BEGIN
 IF OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL THEN RETURN NEW; END IF;
 IF change_ledger.cosign_session_is_exempt() THEN RETURN NEW; END IF;
 SELECT * INTO r FROM change_ledger.records x WHERE x.change_id=NEW.change_id;
 IF OLD.signer_session IS NULL THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
 IF change_ledger.same_person(r.tenant_id,r.company_id,session_user::text,OLD.signer_session) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_session_independent(r.tenant_id,r.company_id,r.requester_session);
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS witness_cosigns_consume_guard ON change_ledger.witness_cosigns;
CREATE TRIGGER witness_cosigns_consume_guard BEFORE UPDATE OF consumed_at ON change_ledger.witness_cosigns
 FOR EACH ROW EXECUTE FUNCTION change_ledger.witness_cosign_consume_guard();

CREATE OR REPLACE FUNCTION change_ledger.hold_cosign_consume_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL THEN RETURN NEW; END IF;
 IF change_ledger.cosign_session_is_exempt() THEN RETURN NEW; END IF;
 IF OLD.signer_session IS NULL OR change_ledger.same_person(OLD.tenant_id,OLD.company_id,session_user::text,OLD.signer_session) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS hold_cosigns_consume_guard ON change_ledger.hold_cosigns;
CREATE TRIGGER hold_cosigns_consume_guard BEFORE UPDATE OF consumed_at ON change_ledger.hold_cosigns
 FOR EACH ROW EXECUTE FUNCTION change_ledger.hold_cosign_consume_guard();

-- ================================================================== wiring, ownership, privileges (keep last)
DO $fn$
DECLARE f record;
BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='change_ledger' LOOP
  EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp',f.sig);
  EXECUTE format('ALTER FUNCTION %s OWNER TO ledger_owner',f.sig);
 END LOOP;
END $fn$;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA change_ledger FROM PUBLIC;

GRANT EXECUTE ON FUNCTION change_ledger.propose_registry_change(text,text,text,jsonb),
 change_ledger.approve_registry_change(text,text,uuid,text) TO operator_role;

$body$;
END IF;
END $mig$;
COMMIT;
