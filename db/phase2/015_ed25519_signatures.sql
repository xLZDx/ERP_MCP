-- R2/G1 S13, simulated lane of the change ledger (simulation program P1b-2): REAL Ed25519 signatures replace the keyed-hash
-- stand-in for evidence, checkpoints and permit signatures. Applies after 014. Apply ONLY to a verified disposable
-- PostgreSQL database (checksum precondition: living.record_migration). NON-GATING PROTOTYPE: not gate evidence. Every key
-- and signature of the test lane is synthetic (lane TEST); the verifier of 014 is a test-lane mechanism, not an audited
-- crypto library.
--
-- DESIGN.
--  1. change_ledger.verifier_keys gains key_algorithm text NOT NULL CHECK IN ('KEYED_HASH_STANDIN','ED25519'). Every row that
--     exists when 015 applies is 'KEYED_HASH_STANDIN' (ADD COLUMN default); the column default is then switched to 'ED25519',
--     so every NEW row is Ed25519 unless a writer states the legacy algorithm explicitly. For an ED25519 row key_material is
--     the PUBLIC key as 64 lowercase hex characters (public data, not a secret; it stays unreadable by runtime roles exactly
--     like the stand-in material, except that the new column key_algorithm itself is readable by the auditor). A CHECK
--     constraint (verifier_keys_ed25519_material_chk) makes a malformed Ed25519 row impossible even for the table owner.
--  2. One dispatcher, change_ledger.signature_ok(key_algorithm, key_material, payload_text, signature_hex) RETURNS boolean,
--     is the ONLY signature comparison. ED25519: the signature must be 128 lowercase hex characters and the key 64 (otherwise
--     false WITHOUT running the 0.1-0.5 s verifier), then ed25519_verify(decode(key,'hex'), convert_to(payload,'UTF8'),
--     decode(sig,'hex')). KEYED_HASH_STANDIN: the old comparison, signature = keyed_signature(key_material, payload).
--     Unknown algorithm or any NULL: false. The three check sites (record_evidence, record_checkpoint,
--     attach_permit_signature) call it and keep their old error codes (EVIDENCE_UNSIGNED, CHECKPOINT_UNAVAILABLE,
--     CHECKPOINT_UNAVAILABLE) and their old order of checks. The signing payload strings are unchanged: evidence_binding
--     text, checkpoint_payload text, 'change-ledger-permit|v1|'||permit_digest. complete_signed, verify_signed,
--     resolve_unknown_signed and witness_cosign_signed take already recorded evidence ids and never verify a signature
--     themselves, so each ledger call performs AT MOST ONE Ed25519 verification (one per signature carried by the call).
--  3. NEW registrations accept only Ed25519. The algorithm is inferred from the material (64 lowercase hex characters =
--     ED25519, which must also decode to a curve point; anything else = the legacy stand-in). The stand-in is refused with
--     SCHEMA_INVALID unless session_user is a superuser (the same exemption test as the cosign paths of 010,
--     cosign_session_is_exempt), which keeps legacy fixtures arrangeable. The rule sits in registry_normalize (every
--     entry: register_verifier_key, propose_registry_change) and again in register_verifier_key_core (the single writer,
--     also reached by approve_registry_change). revoke_verifier_key and the two-person rules of 010 are untouched. The
--     VERIFIER_KEY_REGISTERED event gains an 'algorithm' member.
--  4. LEGACY ROWS keep working: a KEYED_HASH_STANDIN row verifies through the dispatcher exactly as before.
--
-- NAMED LIMITS.
--  * The algorithm is inferred from the shape of the material. A legacy stand-in secret that happens to be 64 lowercase hex
--    characters would be read as an Ed25519 key (and refused if it is not a curve point); a legacy fixture must therefore
--    use another shape. register_verifier_key with an EXISTING legacy row repeated by a non-superuser is refused with
--    SCHEMA_INVALID (the exact repeat of a stand-in key is no longer a no-op for a normal operator).
--  * A superuser session can still register or insert stand-in keys (legacy fixtures); that is a trusted-boundary fact, not
--    a defence claim, as in 013.
--  * Verification cost: ed25519_verify is pure PL/pgSQL numeric arithmetic (0.1-0.5 s each). Replays of record_evidence
--    verify again (one per call) because the signature check precedes the idempotent insert.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('015', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014']) THEN
EXECUTE $body$

-- ================================================================== storage
ALTER TABLE change_ledger.verifier_keys
 ADD COLUMN IF NOT EXISTS key_algorithm text NOT NULL DEFAULT 'KEYED_HASH_STANDIN'
  CHECK(key_algorithm IN ('KEYED_HASH_STANDIN','ED25519'));
ALTER TABLE change_ledger.verifier_keys ALTER COLUMN key_algorithm SET DEFAULT 'ED25519';
ALTER TABLE change_ledger.verifier_keys DROP CONSTRAINT IF EXISTS verifier_keys_ed25519_material_chk;
ALTER TABLE change_ledger.verifier_keys ADD CONSTRAINT verifier_keys_ed25519_material_chk
 CHECK(key_algorithm <> 'ED25519' OR key_material ~ '^[0-9a-f]{64}$');
GRANT SELECT(key_algorithm) ON change_ledger.verifier_keys TO auditor_role;

-- ================================================================== the dispatcher (the only signature comparison)
CREATE OR REPLACE FUNCTION change_ledger.signature_ok(p_key_algorithm text, p_key_material text, p_payload text,
 p_signature text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
 IF p_key_algorithm IS NULL OR p_key_material IS NULL OR p_payload IS NULL OR p_signature IS NULL THEN RETURN false; END IF;
 IF p_key_algorithm = 'ED25519' THEN
  IF p_signature !~ '^[0-9a-f]{128}$' OR p_key_material !~ '^[0-9a-f]{64}$' THEN RETURN false; END IF;   -- no verifier run
  RETURN change_ledger.ed25519_verify(pg_catalog.decode(p_key_material,'hex'),
   pg_catalog.convert_to(p_payload,'UTF8'), pg_catalog.decode(p_signature,'hex'));
 ELSIF p_key_algorithm = 'KEYED_HASH_STANDIN' THEN
  RETURN p_signature = change_ledger.keyed_signature(p_key_material, p_payload);                          -- legacy path
 END IF;
 RETURN false;
END $fn$;

-- ================================================================== new registrations: Ed25519 only
CREATE OR REPLACE FUNCTION change_ledger.verifier_key_algorithm(p_key_material text) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT CASE WHEN p_key_material ~ '^[0-9a-f]{64}$' THEN 'ED25519' ELSE 'KEYED_HASH_STANDIN' END
$fn$;

-- raises SCHEMA_INVALID unless the material may be registered by this session: an Ed25519 public key that decodes to a
-- curve point, or (superuser sessions only) a legacy stand-in secret
CREATE OR REPLACE FUNCTION change_ledger.assert_verifier_key_registrable(p_key_material text) RETURNS void
LANGUAGE plpgsql AS $fn$
BEGIN
 IF p_key_material IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF change_ledger.verifier_key_algorithm(p_key_material) = 'ED25519' THEN
  IF change_ledger.ed25519_decompress(pg_catalog.decode(p_key_material,'hex')) IS NULL THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';           -- 64 hex characters that are not a curve point can never verify anything
  END IF;
  IF change_ledger.ed25519_is_small_order(pg_catalog.decode(p_key_material,'hex')) THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';           -- a small-order key (e.g. the neutral point) is never a usable signing key
  END IF;
 ELSIF NOT change_ledger.cosign_session_is_exempt() THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';            -- the keyed-hash stand-in is not accepted for new keys
 END IF;
END $fn$;

-- registry_normalize: the 010 body, VERIFIER_KEY branch extended by the registrable check
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
  PERFORM change_ledger.assert_verifier_key_registrable(p->>'key_material');
  RETURN jsonb_build_object('key_id',p->>'key_id','role_name',p->>'role_name','key_material',p->>'key_material');
 END IF;
 RAISE EXCEPTION 'SCHEMA_INVALID';
END $fn$;

-- register_verifier_key_core: the 010 body, the algorithm is stored and a new row must be registrable
CREATE OR REPLACE FUNCTION change_ledger.register_verifier_key_core(
 t text, c text, p_key_id text, p_role_name text, p_key_material text, who text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ex change_ledger.verifier_keys%ROWTYPE; alg text;
BEGIN
 SELECT * INTO ex FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND THEN
  IF ex.key_material IS DISTINCT FROM p_key_material OR ex.role_name IS DISTINCT FROM p_role_name THEN
   RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
  END IF;
  RETURN;
 END IF;
 PERFORM change_ledger.assert_verifier_key_registrable(p_key_material);
 alg := change_ledger.verifier_key_algorithm(p_key_material);
 INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,key_algorithm,registered_by)
 VALUES(t,c,p_key_id,p_role_name,p_key_material,alg,who);
 PERFORM change_ledger.append_event(t,c,NULL,'VERIFIER_KEY_REGISTERED',
  jsonb_build_object('key_id',p_key_id,'role',p_role_name,'algorithm',alg,'by',who));
END $fn$;

-- ================================================================== the three check sites (007 bodies, one dispatcher call each)
CREATE OR REPLACE FUNCTION change_ledger.record_evidence(
 t text, c text, p_change_id uuid, p_kind text, p_content_hash text, p_observed_at timestamptz,
 p_content jsonb, p_key_id text, p_binding_hash text, p_signature text, p_generation bigint, p_call_id uuid
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; rec change_ledger.records%ROWTYPE; vk change_ledger.verifier_keys%ROWTYPE; want text;
 eid uuid; cls text; is_worker boolean; is_writer boolean; dp_call uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF p_change_id IS NULL OR p_kind IS NULL OR p_kind NOT IN ('FIELD','MOVEMENT','VERSION','AUTH_RECEIPT','COMPLETION_PROOF','OBSERVATION')
  OR p_content_hash IS NULL OR p_content_hash !~ '^[a-f0-9]{64}$' OR p_observed_at IS NULL
  OR p_content IS NULL OR jsonb_typeof(p_content)<>'object' THEN
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
 IF p_content_hash IS DISTINCT FROM change_ledger.canonical_content_hash(p_content) THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 want := change_ledger.evidence_binding(p_change_id,p_kind,p_content_hash,p_observed_at,p_generation,p_call_id);
 IF p_binding_hash IS DISTINCT FROM want THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,want,p_signature) THEN     -- one verification
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 IF p_observed_at > clock_timestamp()+interval '5 minutes' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF p_kind<>'AUTH_RECEIPT' THEN
  IF p_generation IS NULL OR p_call_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
  SELECT dp.call_id INTO dp_call FROM change_ledger.dispatch_permits dp
   WHERE dp.change_id=p_change_id AND dp.generation=p_generation;
  IF NOT FOUND OR dp_call IS DISTINCT FROM p_call_id THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 END IF;
 IF p_kind IN ('COMPLETION_PROOF','OBSERVATION') THEN
  IF (p_content->>'generation') IS DISTINCT FROM p_generation::text
   OR (p_content->>'call_id') IS DISTINCT FROM p_call_id::text THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 END IF;
 IF p_kind='COMPLETION_PROOF' THEN
  cls := p_content->>'class';
  IF cls IS NULL OR cls NOT IN ('a','b') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF (cls='a' AND NOT is_writer) OR (cls='b' AND NOT is_worker) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
  IF jsonb_typeof(p_content->'result_returned') IS DISTINCT FROM 'boolean' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 ELSIF p_kind='OBSERVATION' THEN
  IF p_content ? 'effect_present' AND jsonb_typeof(p_content->'effect_present')<>'boolean' THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 ELSIF p_kind IN ('FIELD','MOVEMENT','VERSION') THEN
  IF jsonb_typeof(p_content->'matches') IS DISTINCT FROM 'boolean' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 ELSIF p_kind='AUTH_RECEIPT' THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.approvals a WHERE a.change_id=p_change_id
    AND a.approval_id::text = p_content->>'approval_id') THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 END IF;
 INSERT INTO change_ledger.evidence_records(tenant_id,company_id,change_id,kind,content_hash,observed_at,
  content,signer_key_id,signature,binding_hash,recorded_by,generation,call_id)
 VALUES(t,c,p_change_id,p_kind,p_content_hash,p_observed_at,p_content,p_key_id,
  p_signature,want,who,p_generation,p_call_id)
 ON CONFLICT(change_id,kind,content_hash) DO NOTHING
 RETURNING evidence_id INTO eid;
 IF eid IS NULL THEN
  SELECT e.evidence_id INTO eid FROM change_ledger.evidence_records e
   WHERE e.change_id=p_change_id AND e.kind=p_kind AND e.content_hash=p_content_hash;
  RETURN eid;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'EVIDENCE_RECORDED',
  jsonb_build_object('evidence_id',eid,'kind',p_kind,'content_hash',p_content_hash,'key_id',p_key_id,
   'generation',p_generation,'call_id',p_call_id));
 RETURN eid;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.record_checkpoint(
 t text, c text, p_ledger_seq bigint, p_head_hash text, p_sink_kind text, p_sink_id text,
 p_signer_key_id text, p_signature text, p_signed_at timestamptz, p_read_back boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE s bigint; who text; vk change_ledger.verifier_keys%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT pg_has_role(who::name,'checkpoint_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_ledger_seq IS NULL OR p_head_hash IS NULL OR p_head_hash !~ '^[a-f0-9]{64}$' OR p_sink_id IS NULL
  OR p_sink_id='' OR p_signer_key_id IS NULL OR p_signature IS NULL OR p_signed_at IS NULL
  OR p_read_back IS NULL OR p_sink_kind IS NULL OR p_sink_kind NOT IN ('REAL','TEST') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT p_read_back THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_signer_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
  OR NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,                              -- one verification
   change_ledger.checkpoint_payload(t,c,p_ledger_seq,p_head_hash,p_signed_at,p_signer_key_id,p_sink_kind,p_sink_id),
   p_signature) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 INSERT INTO change_ledger.checkpoints(tenant_id,company_id,ledger_seq,head_hash,sink_kind,
  sink_id,signer_key_id,signature,signed_at,read_back_confirmed,written_by,verified)
 VALUES(t,c,p_ledger_seq,p_head_hash,p_sink_kind,p_sink_id,p_signer_key_id,p_signature,
  p_signed_at,true,who,true)
 RETURNING seq INTO s;
 RETURN s;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.attach_permit_signature(
 t text, c text, p_change_id uuid, p_generation bigint, p_key_id text, p_signature text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n integer; who text; vk change_ledger.verifier_keys%ROWTYPE; dg text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT pg_has_role(who::name,'checkpoint_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_change_id IS NULL OR p_generation IS NULL OR p_key_id IS NULL OR p_signature IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
  OR NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 SELECT dp.permit_digest INTO dg FROM change_ledger.dispatch_permits dp
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation AND dp.state='PERMITTED';
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,'change-ledger-permit|v1|'||dg,p_signature) THEN   -- one verification
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 UPDATE change_ledger.dispatch_permits SET signer_key_id=p_key_id, signature=p_signature
  WHERE change_id=p_change_id AND generation=p_generation AND state='PERMITTED';
 GET DIAGNOSTICS n = ROW_COUNT;
 IF n=0 THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
END $fn$;

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

-- no new GRANT: signature_ok, verifier_key_algorithm and assert_verifier_key_registrable are internal; the definer
-- functions that call them run as ledger_owner. The grants of record_evidence / record_checkpoint /
-- attach_permit_signature / register_verifier_key are unchanged (same signatures, CREATE OR REPLACE keeps them).

$body$;
END IF;
END $mig$;
COMMIT;
