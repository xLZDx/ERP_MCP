-- R2/G1 S13 hardening, batch A (docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md items A1-A8). Applies after 006.
-- Apply ONLY to a verified disposable PostgreSQL database (checksum precondition: living.record_migration).
--  A1 signed evidence is the only completion/verification path: the raw complete / resolve_unknown / verify /
--     witness_cosign functions lose EXECUTE for every runtime role (they stay as internals of the signed wrappers);
--     record_evidence checks content_hash = sha256(jsonb text of the content) and binds generation and call_id;
--     outcomes and verdicts are derived from typed record content; retry_verify, verify_inconclusive and
--     complete_lock_busy take evidence ids; operator_resolve needs a signed OBSERVATION whose effect_present
--     equals the resolution.
--  A2 approve / issue_approval_nonce need authorization in (NONE, VOIDED, REVOKED) and execution NOT_STARTED.
--  A3 verify refuses FAILED_VERIFY -> VERIFIED; the FAILED_VERIFY_HALT insert is idempotent.
--  A4 T11 / T16-absent on a repair hand the target lock back to the parent.
--  A5 NULL comparisons fail closed (IS DISTINCT FROM, SCHEMA_INVALID on NULL inputs).
--  A6 dedicated checkpoint_role identity; record_checkpoint verifies a keyed-hash signature (stand-in for the D9
--     Ed25519 signer) against a registered checkpoint_role key and marks the row verified; issue_permit accepts only
--     verified rows; attach_permit_signature checks the key and the signature.
--  A7 the approval digest is computed in SQL (approval_digest) from the stored change; approve compares it and
--     read_status returns it with its inputs. DELIBERATE DIFFERENCES from the offline proposal.approval_digest:
--     the SQL skeleton stores only the opaque payload_digest (offline: the canonical payload), has no stored
--     business_state_digest (the declared business key digest stands in), and carries repair_for and
--     declared_target_class additionally; the digest is bound to rule table version S11-RULES-2026-10-12.
--  A8 consume_two_person_cosign compares persons (same_person) and checks operator / recovery_witness capabilities.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('007', ARRAY['001','002','003','004','005','006']) THEN
EXECUTE $body$

-- ================================================================== roles / columns
DO $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='checkpoint_role') THEN
  CREATE ROLE checkpoint_role NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
 ELSIF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='checkpoint_role' AND (rolsuper OR rolbypassrls OR rolcanlogin)) THEN
  RAISE EXCEPTION 'LEDGER_ROLE_UNSAFE: checkpoint_role';
 END IF;
END $fn$;

ALTER TABLE change_ledger.evidence_records ADD COLUMN IF NOT EXISTS generation bigint;
ALTER TABLE change_ledger.evidence_records ADD COLUMN IF NOT EXISTS call_id uuid;
ALTER TABLE change_ledger.checkpoints ADD COLUMN IF NOT EXISTS written_by text;
ALTER TABLE change_ledger.checkpoints ADD COLUMN IF NOT EXISTS verified boolean NOT NULL DEFAULT false;

-- ================================================================== signing helpers (keyed-hash stand-in for D9)
DROP FUNCTION IF EXISTS change_ledger.evidence_binding(uuid,text,text,timestamptz);
CREATE OR REPLACE FUNCTION change_ledger.evidence_binding(p_change_id uuid, p_kind text, p_content_hash text,
 p_observed_at timestamptz, p_generation bigint, p_call_id uuid) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT encode(sha256(convert_to(p_change_id::text||':'||p_kind||':'||p_content_hash||':'||
  to_char(p_observed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')||':'||
  coalesce(p_generation::text,'')||':'||coalesce(p_call_id::text,''),'UTF8')),'hex')
$fn$;

-- sha256 of the PostgreSQL canonical text of the jsonb content: the value record_evidence requires as content_hash.
CREATE OR REPLACE FUNCTION change_ledger.canonical_content_hash(p_content jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT encode(sha256(convert_to(p_content::text,'UTF8')),'hex')
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.checkpoint_payload(t text, c text, p_ledger_seq bigint, p_head_hash text,
 p_signed_at timestamptz, p_key_id text, p_sink_kind text, p_sink_id text) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT 'change-ledger-checkpoint|v2|'||t||'|'||c||'|'||p_ledger_seq::text||'|'||p_head_hash||'|'||
  to_char(p_signed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'|'||p_key_id||'|'||p_sink_kind||'|'||p_sink_id
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.keyed_signature(p_key_material text, p_payload text) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT encode(sha256(convert_to(p_key_material||':'||p_payload,'UTF8')),'hex')
$fn$;

-- ================================================================== A7 approval digest
CREATE OR REPLACE FUNCTION change_ledger.allowed_effects(p_kind text) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT CASE WHEN p_kind='POST' THEN to_jsonb(ARRAY[E'НДСПредъявленный',
  E'Хозрасчетный']) ELSE '[]'::jsonb END
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.approval_digest(p_change_id uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; bsd text; eff jsonb;
BEGIN
 SELECT * INTO rec FROM change_ledger.records WHERE change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT encode(sha256(convert_to(b.key_hash||':'||coalesce(b.override_digest,''),'UTF8')),'hex')
  INTO bsd FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 eff := change_ledger.allowed_effects(rec.kind);
 RETURN encode(sha256(convert_to(jsonb_build_object(
  'digest_version','S12-APPROVAL-SQL-1','change_id',rec.change_id,'kind',rec.kind,
  'tenant',rec.tenant_id,'company',rec.company_id,'organization',rec.organization_ref,
  'base_fingerprint',rec.base_fingerprint,'payload_digest',rec.payload_digest,
  'target_ref',rec.target_ref,'target_version',rec.target_version,
  'parent_change_id',rec.parent_change_id,'repair_for',rec.repair_for,
  'declared_target_class',rec.declared_target_class,'business_state_digest',bsd,
  'allowed_effects',eff,'rule_table_version','S11-RULES-2026-10-12',
  'epoch_dependencies',(SELECT coalesce(jsonb_object_agg(k,v),'{}'::jsonb) FROM jsonb_each(rec.epoch_dependencies) e(k,v)
                         WHERE k NOT LIKE 'principal:%'),
  'expires_at',to_char(rec.expires_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))::text,'UTF8')),'hex');
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.read_status(t text, c text, p_change_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; ap record; bk change_ledger.business_keys%ROWTYPE; dg text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF NOT (pg_has_role(who::name,'auditor_role','USAGE') OR pg_has_role(who::name,'approver_role','USAGE')
         OR who IS NOT DISTINCT FROM rec.requester) THEN
  RAISE EXCEPTION 'CHANGE_NOT_FOUND';
 END IF;
 SELECT a.approval_id, a.approver, a.digest INTO ap FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 SELECT * INTO bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 dg := change_ledger.approval_digest(p_change_id);
 RETURN jsonb_build_object('change_id',rec.change_id,'kind',rec.kind,'requester',rec.requester,
  'tenant_id',rec.tenant_id,'company_id',rec.company_id,
  'base_fingerprint',rec.base_fingerprint,'organization_ref',rec.organization_ref,
  'target_ref',rec.target_ref,'target_version',rec.target_version,'parent_change_id',rec.parent_change_id,
  'repair_for',rec.repair_for,'payload_digest',rec.payload_digest,
  'lifecycle',rec.lifecycle,'authorization',rec.authorization_state,'execution',rec.execution_state,
  'verification',rec.verification_state,'call_ownership',rec.call_ownership,'attribution',rec.attribution,
  'effect_known',rec.effect_known,'reservation',rec.reservation_state,'dispatch',rec.dispatch_state,
  'claim_generation',rec.claim_generation,'expires_at',rec.expires_at,
  'epoch_dependencies',rec.epoch_dependencies,
  'epoch_current',change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies),
  'declared_target_class',rec.declared_target_class,
  'rule_table_version','S11-RULES-2026-10-12',
  'allowed_effects',change_ledger.allowed_effects(rec.kind),
  'business_key_hash',bk.key_hash,
  'approval_digest',dg,'approved_digest',ap.digest,
  'approval_id',ap.approval_id,'approver',ap.approver,
  'open_holds',(SELECT count(*) FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=rec.base_fingerprint AND h.released_at IS NULL),
  'evidence_count',(SELECT count(*) FROM change_ledger.evidence_records e WHERE e.change_id=p_change_id));
END $fn$;

-- ================================================================== A2 / A7 / A5: nonce and approve
CREATE OR REPLACE FUNCTION change_ledger.issue_approval_nonce(t text, c text, p_change_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; n text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF who IS NOT DISTINCT FROM rec.requester OR pg_has_role(who::name, rec.requester::name, 'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 IF rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED') OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'approver');
 PERFORM change_ledger.assert_independent(t,c,who,rec.requester);
 n := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
 INSERT INTO change_ledger.approval_nonces(nonce,change_id,approver,expires_at)
 VALUES(n,p_change_id,who,clock_timestamp()+interval '10 minutes');
 RETURN n;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.approve(
 t text, c text, p_change_id uuid, p_nonce text, p_digest text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_approver text; nrow change_ledger.approval_nonces%ROWTYPE;
 aid uuid; bk change_ledger.business_keys%ROWTYPE; parent_req text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_digest IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 v_approver := change_ledger.caller_role();
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle <> 'VALIDATED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED') OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
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
 IF p_digest IS DISTINCT FROM change_ledger.approval_digest(p_change_id) THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
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
  RAISE EXCEPTION 'DUPLICATE_SUSPECTED';
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

-- ================================================================== A1 record_evidence
DROP FUNCTION IF EXISTS change_ledger.record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text);
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
 IF p_signature IS DISTINCT FROM change_ledger.keyed_signature(vk.key_material,want) THEN
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
  IF jsonb_typeof(p_content->'result_returned')<>'boolean' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 ELSIF p_kind='OBSERVATION' THEN
  IF p_content ? 'effect_present' AND jsonb_typeof(p_content->'effect_present')<>'boolean' THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 ELSIF p_kind IN ('FIELD','MOVEMENT','VERSION') THEN
  IF jsonb_typeof(p_content->'matches')<>'boolean' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
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

-- ================================================================== A1 typed evidence helpers
-- The writer's own signed completion record (proof class a) for this call and generation, typed by outcome.
CREATE OR REPLACE FUNCTION change_ledger.typed_completion(t text, c text, p_change_id uuid, p_generation bigint,
 p_completion uuid, p_outcome text, p_codes text[]) RETURNS change_ledger.evidence_records
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ev change_ledger.evidence_records; dp_call uuid; np jsonb;
BEGIN
 ev := change_ledger.evidence_ref(t,c,p_change_id,p_completion,'COMPLETION_PROOF');
 IF ev.content->>'class' IS DISTINCT FROM 'a' OR NOT pg_has_role(ev.recorded_by::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 IF ev.generation IS DISTINCT FROM p_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT dp.call_id INTO dp_call FROM change_ledger.dispatch_permits dp
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation;
 IF NOT FOUND OR ev.call_id IS DISTINCT FROM dp_call THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF p_outcome='SUCCESS' THEN
  IF ev.content->'result_returned' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 ELSIF p_outcome='PRE_WRITE_REFUSAL' THEN
  np := ev.content->'no_effect_proof';
  IF ev.content->'result_returned' IS DISTINCT FROM 'false'::jsonb
   OR ev.content->>'stage' IS DISTINCT FROM 'PRE_WRITE'
   OR ev.content->>'refusal_code' IS NULL OR NOT (ev.content->>'refusal_code' = ANY(p_codes))
   OR np IS NULL OR jsonb_typeof(np)<>'object' OR np='{}'::jsonb THEN
   RAISE EXCEPTION 'WRITE_REFUSED';
  END IF;
 END IF;
 RETURN ev;
END $fn$;

-- Verdict of FIELD / MOVEMENT / VERSION records of the current generation (never a caller flag).
CREATE OR REPLACE FUNCTION change_ledger.derive_verdict(t text, c text, p_rec change_ledger.records,
 p_field uuid, p_movement uuid, p_version uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE f change_ledger.evidence_records; m change_ledger.evidence_records; v change_ledger.evidence_records;
 effect_at timestamptz; any_false boolean := false; all_true boolean := true; r change_ledger.evidence_records;
BEGIN
 IF p_field IS NOT NULL THEN f := change_ledger.evidence_ref(t,c,p_rec.change_id,p_field,'FIELD'); END IF;
 IF p_movement IS NOT NULL THEN m := change_ledger.evidence_ref(t,c,p_rec.change_id,p_movement,'MOVEMENT'); END IF;
 IF p_version IS NOT NULL THEN v := change_ledger.evidence_ref(t,c,p_rec.change_id,p_version,'VERSION'); END IF;
 FOREACH r IN ARRAY ARRAY[f,m,v] LOOP
  IF r.evidence_id IS NULL THEN all_true := false; CONTINUE; END IF;
  IF r.generation IS DISTINCT FROM p_rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
  IF r.content->'matches' = 'false'::jsonb THEN any_false := true; all_true := false;
  ELSIF r.content->'matches' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 END LOOP;
 IF NOT any_false AND NOT all_true THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF all_true THEN
  SELECT max(e.recorded_at) INTO effect_at FROM change_ledger.events e
   WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_rec.change_id
    AND e.event_type IN ('COMPLETE_SUCCESS','RESOLVE_UNKNOWN','OPERATOR_RESOLVE');
  IF f.observed_at<effect_at OR m.observed_at<effect_at OR v.observed_at<effect_at THEN
   RAISE EXCEPTION 'VERIFY_FAILED';
  END IF;
 END IF;
 RETURN jsonb_build_object('passed',all_true,'refs',jsonb_build_object('field',f.evidence_id,
  'movement',m.evidence_id,'version',v.evidence_id));
END $fn$;

-- ================================================================== A1/A5 complete (internal) and signed wrapper
CREATE OR REPLACE FUNCTION change_ledger.complete(
 t text, c text, p_change_id uuid, p_generation bigint, p_outcome text,
 p_evidence jsonb, p_no_effect_proof jsonb DEFAULT NULL
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_exec text; new_res text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL OR p_outcome IS NULL
  OR p_outcome NOT IN ('SUCCESS','PRE_WRITE_REFUSAL','UNKNOWN') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN
  IF rec.execution_state IN ('APPLIED','APPLY_UNKNOWN','FAILED_APPLY') THEN RETURN rec.execution_state; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_outcome IN ('SUCCESS','UNKNOWN') AND rec.dispatch_state<>'DISPATCHED' THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 IF p_outcome='SUCCESS' THEN
  new_exec:='APPLIED'; new_res:='CONSUMED';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='PROVEN_FINISHED',
   attribution='PROVEN', reservation_state=new_res, updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 ELSIF p_outcome='PRE_WRITE_REFUSAL' THEN
  IF p_no_effect_proof IS NULL THEN RAISE EXCEPTION 'WRITE_REFUSED'; END IF;
  IF rec.dispatch_state<>'DISPATCHED' THEN
   UPDATE change_ledger.dispatch_permits SET state='CANCELLED_UNDISPATCHED'
    WHERE change_id=p_change_id AND generation=p_generation AND state IN ('NOT_PERMITTED','PERMITTED');
  END IF;
  new_exec:='FAILED_APPLY';
  PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
  UPDATE change_ledger.records SET execution_state=new_exec,
   dispatch_state=CASE WHEN dispatch_state='DISPATCHED' THEN dispatch_state ELSE 'CANCELLED_UNDISPATCHED' END,
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSE
  new_exec:='APPLY_UNKNOWN';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='POSSIBLY_EXECUTING',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  IF NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.change_id=p_change_id AND h.cause='CALL_OWNERSHIP'
    AND h.released_at IS NULL) THEN
   INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
   VALUES(t,c,rec.base_fingerprint,'CALL_OWNERSHIP',p_change_id);
  END IF;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'COMPLETE_'||p_outcome,coalesce(p_evidence,'{}'::jsonb));
 RETURN new_exec;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.complete_signed(
 t text, c text, p_change_id uuid, p_generation bigint, p_outcome text, p_completion uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ev change_ledger.evidence_records; ref jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL OR p_outcome IS NULL
  OR p_outcome NOT IN ('SUCCESS','PRE_WRITE_REFUSAL','UNKNOWN') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_outcome<>'UNKNOWN' OR p_completion IS NOT NULL THEN
  ev := change_ledger.typed_completion(t,c,p_change_id,p_generation,p_completion,p_outcome,
   ARRAY['STALE_VERSION','DUPLICATE_SUSPECTED','ROLLBACK_REFUSED','WRITE_REFUSED']);
  ref := jsonb_build_object('evidence_id',ev.evidence_id,'content_hash',ev.content_hash);
 END IF;
 RETURN change_ledger.complete(t,c,p_change_id,p_generation,p_outcome,coalesce(ref,'{}'::jsonb),
  CASE WHEN p_outcome='PRE_WRITE_REFUSAL' THEN ev.content->'no_effect_proof' ELSE NULL END);
END $fn$;

DROP FUNCTION IF EXISTS change_ledger.complete_lock_busy(text,text,uuid,bigint,jsonb,jsonb,jsonb);
CREATE OR REPLACE FUNCTION change_ledger.complete_lock_busy(
 t text, c text, p_change_id uuid, p_generation bigint, p_completion uuid,
 p_params jsonb DEFAULT '{}'::jsonb
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE p jsonb; rec change_ledger.records%ROWTYPE; k change_ledger.sweep_counters%ROWTYPE; due_in double precision;
 ev change_ledger.evidence_records; ref jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 p := change_ledger.sweep_params(p_params,
  '{"lock_busy_max_attempts":5,"lock_busy_interval_seconds":180,"lock_busy_jitter_seconds":30,
    "lock_busy_window_seconds":900}'::jsonb);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN
  IF rec.execution_state='FAILED_APPLY' THEN RETURN rec.execution_state; END IF;
  IF rec.execution_state='NOT_STARTED' AND rec.authorization_state='APPROVED' THEN RETURN 'APPROVED'; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_completion IS NULL THEN RAISE EXCEPTION 'WRITE_REFUSED'; END IF;
 ev := change_ledger.typed_completion(t,c,p_change_id,p_generation,p_completion,'PRE_WRITE_REFUSAL',
  ARRAY['LOCK_BUSY']);
 ref := jsonb_build_object('evidence_id',ev.evidence_id,'content_hash',ev.content_hash);
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'LOCK_BUSY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=p_change_id AND kind='LOCK_BUSY' FOR UPDATE;
 IF k.closed_at IS NULL AND k.attempts<(p->>'lock_busy_max_attempts')::integer
  AND k.started_at+make_interval(secs=>(p->>'lock_busy_window_seconds')::double precision)>clock_timestamp() THEN
  due_in := (p->>'lock_busy_interval_seconds')::double precision
            + random()*(p->>'lock_busy_jitter_seconds')::double precision;
  UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp(),
   next_attempt_at=clock_timestamp()+make_interval(secs=>due_in)
   WHERE subject_id=p_change_id AND kind='LOCK_BUSY' RETURNING * INTO k;
  UPDATE change_ledger.dispatch_permits SET state='CANCELLED_UNDISPATCHED'
   WHERE change_id=p_change_id AND generation=p_generation AND state IN ('NOT_PERMITTED','PERMITTED');
  UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE change_id=p_change_id AND generation=p_generation;
  PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
  UPDATE change_ledger.records SET
   authorization_state=CASE WHEN rec.expires_at<=clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
   execution_state='NOT_STARTED', dispatch_state='NOT_PERMITTED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  PERFORM change_ledger.append_event(t,c,p_change_id,'LOCK_BUSY_RETRY',
   jsonb_build_object('attempt',k.attempts,'next_attempt_at',k.next_attempt_at,'evidence',ref));
  RETURN 'APPROVED';
 END IF;
 UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason='DEFINITE'
  WHERE subject_id=p_change_id AND kind='LOCK_BUSY' AND closed_at IS NULL;
 RETURN change_ledger.complete(t,c,p_change_id,p_generation,'PRE_WRITE_REFUSAL',ref,ev.content->'no_effect_proof');
END $fn$;

-- ================================================================== A1/A4/A5 resolve_unknown
CREATE OR REPLACE FUNCTION change_ledger.release_or_handback_target(t text, c text, p_rec change_ledger.records)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE tref text;
BEGIN
 tref := coalesce(p_rec.target_ref, p_rec.change_id::text);
 IF p_rec.repair_for IS NOT NULL THEN
  IF NOT change_ledger.handoff_target_lock(t,c,p_rec.base_fingerprint,tref,p_rec.change_id,p_rec.repair_for) THEN
   RAISE EXCEPTION 'LOCK_BUSY';
  END IF;
 ELSE
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=p_rec.base_fingerprint AND target_ref=tref AND owner_change_id=p_rec.change_id;
 END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.resolve_unknown(
 t text, c text, p_change_id uuid, p_observation jsonb, p_found boolean, p_attributed boolean DEFAULT false
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_exec text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_observation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'APPLY_UNKNOWN' THEN
  IF rec.execution_state IN ('APPLIED','FAILED_APPLY','TRIAGE_REQUIRED') THEN RETURN rec.execution_state; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_found IS NULL OR p_found THEN
  new_exec:='TRIAGE_REQUIRED';
  UPDATE change_ledger.records SET execution_state=new_exec, updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSE
  IF coalesce(p_observation->'completion_proof'->>'class','') NOT IN ('a','b') THEN
   RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
  END IF;
  new_exec:='FAILED_APPLY';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='PROVEN_FINISHED',
   updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.holds SET released_at=clock_timestamp(), release_evidence=p_observation
   WHERE change_id=p_change_id AND cause='CALL_OWNERSHIP' AND released_at IS NULL;
  PERFORM change_ledger.release_or_handback_target(t,c,rec);
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
  UPDATE change_ledger.records SET reservation_state='RELEASED' WHERE tenant_id=t AND company_id=c
   AND change_id=p_change_id AND reservation_state='RESERVED';
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'RESOLVE_UNKNOWN',
  jsonb_build_object('found',p_found,'attributed_claim',p_attributed,'observation',p_observation));
 RETURN new_exec;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.resolve_unknown_signed(
 t text, c text, p_change_id uuid, p_observation uuid, p_completion uuid, p_found boolean, p_attributed boolean DEFAULT false
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE obs change_ledger.evidence_records; cp change_ledger.evidence_records; body jsonb; derived boolean;
 rec change_ledger.records%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 obs := change_ledger.evidence_ref(t,c,p_change_id,p_observation,'OBSERVATION');
 IF obs.generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 derived := CASE WHEN jsonb_typeof(obs.content->'effect_present')='boolean'
                 THEN (obs.content->>'effect_present')::boolean END;
 IF p_found IS DISTINCT FROM derived THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 body := jsonb_build_object('observation_evidence',obs.evidence_id);
 IF p_completion IS NOT NULL THEN
  cp := change_ledger.evidence_ref(t,c,p_change_id,p_completion,'COMPLETION_PROOF');
  IF cp.generation IS DISTINCT FROM rec.claim_generation OR cp.call_id IS DISTINCT FROM obs.call_id THEN
   RAISE EXCEPTION 'TICKET_SUPERSEDED';
  END IF;
  body := body || jsonb_build_object('completion_proof',
   jsonb_build_object('class',cp.content->>'class','evidence_id',cp.evidence_id));
 END IF;
 RETURN change_ledger.resolve_unknown(t,c,p_change_id,body,derived,p_attributed);
END $fn$;

-- ================================================================== A1/A3/A5 verify
CREATE OR REPLACE FUNCTION change_ledger.verify(
 t text, c text, p_change_id uuid, p_evidence jsonb, p_passed boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_ver text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_passed IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'APPLIED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF rec.verification_state='VERIFIED' THEN RETURN rec.verification_state; END IF;
 IF rec.verification_state<>'NOT_VERIFIED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF p_evidence IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 new_ver := CASE WHEN p_passed THEN 'VERIFIED' ELSE 'FAILED_VERIFY' END;
 UPDATE change_ledger.records SET verification_state=new_ver,
  effect_known=CASE WHEN p_passed THEN effect_known ELSE 'YES' END, updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF p_passed THEN
  IF rec.repair_for IS NOT NULL THEN
   UPDATE change_ledger.holds SET released_at=clock_timestamp(),
    release_evidence=jsonb_build_object('released_by_repair',p_change_id)
    WHERE tenant_id=t AND company_id=c AND change_id=rec.repair_for AND cause='FAILED_VERIFY_HALT'
     AND released_at IS NULL;
  END IF;
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 ELSIF NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL) THEN
  INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
  VALUES(t,c,rec.base_fingerprint,'FAILED_VERIFY_HALT',p_change_id);
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_'||new_ver,coalesce(p_evidence,'{}'::jsonb));
 RETURN new_ver;
END $fn$;

DROP FUNCTION IF EXISTS change_ledger.verify_signed(text,text,uuid,uuid,uuid,uuid,boolean);
CREATE OR REPLACE FUNCTION change_ledger.verify_signed(
 t text, c text, p_change_id uuid, p_field uuid, p_movement uuid, p_version uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; d jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF rec.verification_state='VERIFIED' THEN RETURN rec.verification_state; END IF;
 IF rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 d := change_ledger.derive_verdict(t,c,rec,p_field,p_movement,p_version);
 RETURN change_ledger.verify(t,c,p_change_id,d->'refs',(d->>'passed')::boolean);
END $fn$;

DROP FUNCTION IF EXISTS change_ledger.retry_verify(text,text,uuid,jsonb,boolean);
CREATE OR REPLACE FUNCTION change_ledger.retry_verify(
 t text, c text, p_change_id uuid, p_field uuid, p_movement uuid, p_version uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; k change_ledger.sweep_counters%ROWTYPE; owner_id uuid; d jsonb;
 p_passed boolean; p_evidence jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.verification_state<>'FAILED_VERIFY' OR NOT EXISTS(SELECT 1 FROM change_ledger.holds h
   WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT'
    AND h.released_at IS NULL) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 d := change_ledger.derive_verdict(t,c,rec,p_field,p_movement,p_version);
 p_passed := (d->>'passed')::boolean; p_evidence := d->'refs';
 SELECT tl.owner_change_id INTO owner_id FROM change_ledger.target_locks tl
  WHERE tl.tenant_id=t AND tl.company_id=c AND tl.base_fingerprint=rec.base_fingerprint
   AND tl.target_ref=coalesce(rec.target_ref,rec.change_id::text);
 IF owner_id IS NOT NULL AND owner_id<>p_change_id THEN RAISE EXCEPTION 'LOCK_BUSY'; END IF;
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'VERIFY_RETRY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=p_change_id AND kind='VERIFY_RETRY' FOR UPDATE;
 IF k.attempts>=3 THEN RAISE EXCEPTION 'VERIFY_FAILED'; END IF;
 UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp()
  WHERE subject_id=p_change_id AND kind='VERIFY_RETRY' RETURNING * INTO k;
 IF p_passed THEN
  UPDATE change_ledger.records SET verification_state='VERIFIED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.holds SET released_at=clock_timestamp(),
   release_evidence=jsonb_build_object('retry_verify',k.attempts,'evidence',p_evidence)
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND cause='FAILED_VERIFY_HALT'
    AND released_at IS NULL;
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason='VERIFIED'
   WHERE subject_id=p_change_id AND kind='VERIFY_RETRY';
  PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_PASSED',
   jsonb_build_object('attempt',k.attempts)||jsonb_build_object('evidence',p_evidence));
  RETURN 'VERIFIED';
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_FAILED',
  jsonb_build_object('attempt',k.attempts)||jsonb_build_object('evidence',p_evidence));
 RETURN 'FAILED_VERIFY';
END $fn$;

DROP FUNCTION IF EXISTS change_ledger.verify_inconclusive(text,text,uuid,jsonb,integer);
CREATE OR REPLACE FUNCTION change_ledger.verify_inconclusive(
 t text, c text, p_change_id uuid, p_observation uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; obs change_ledger.evidence_records;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 obs := change_ledger.evidence_ref(t,c,p_change_id,p_observation,'OBSERVATION');
 IF obs.generation IS DISTINCT FROM rec.claim_generation
  OR obs.content->'inconclusive' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 RETURN change_ledger.verify_attempt_internal(t,c,p_change_id,'WORKER_INCONCLUSIVE',3,180);
END $fn$;

-- ================================================================== A1/A4/A5 operator_resolve
CREATE OR REPLACE FUNCTION change_ledger.operator_resolve(
 t text, c text, p_change_id uuid, p_cosign_id uuid, p_present boolean, p_attributed boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_operator text; cs change_ledger.witness_cosigns%ROWTYPE;
 approver_subject text; new_exec text; obs change_ledger.evidence_records;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_present IS NULL OR p_attributed IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
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
 -- the verdict is the signed observation of this generation, never the caller's flag
 SELECT * INTO obs FROM change_ledger.evidence_records e
  WHERE e.change_id=p_change_id AND e.kind='OBSERVATION' AND e.generation=rec.claim_generation
   AND jsonb_typeof(e.content->'effect_present')='boolean'
   AND (e.content->>'effect_present')::boolean=p_present
  ORDER BY e.recorded_at DESC LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
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
  PERFORM change_ledger.release_or_handback_target(t,c,rec);
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
  jsonb_build_object('present',p_present,'attributed',p_attributed,'cosign_id',p_cosign_id,
   'observation_evidence',obs.evidence_id));
 RETURN new_exec;
END $fn$;

-- ================================================================== A8 consume_two_person_cosign
CREATE OR REPLACE FUNCTION change_ledger.consume_two_person_cosign(
 p_rec change_ledger.records, p_operator text, p_cosign_id uuid
) RETURNS change_ledger.witness_cosigns LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cs change_ledger.witness_cosigns%ROWTYPE; approver_subject text; t text := p_rec.tenant_id; c text := p_rec.company_id;
BEGIN
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_rec.change_id AND w.consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 IF coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 SELECT a.approver INTO approver_subject FROM change_ledger.approvals a
  WHERE a.change_id=p_rec.change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 IF change_ledger.same_person(t,c,p_operator,cs.signer)
  OR change_ledger.same_person(t,c,p_operator,p_rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,p_rec.requester)
  OR (change_ledger.same_person(t,c,p_operator,approver_subject)
      AND change_ledger.same_person(t,c,cs.signer,approver_subject)) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,p_operator,'operator');
 PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
 IF change_ledger.registry_enforced(t,c) AND (change_ledger.person_of(t,c,p_operator) IS NULL
  OR change_ledger.person_of(t,c,cs.signer) IS NULL OR change_ledger.person_of(t,c,p_rec.requester) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 UPDATE change_ledger.witness_cosigns w SET consumed_at=clock_timestamp() WHERE w.cosign_id=p_cosign_id;
 RETURN cs;
END $fn$;

-- ================================================================== A5/A6 issue_permit, checkpoint gate
CREATE OR REPLACE FUNCTION change_ledger.issue_permit(
 t text, c text, p_change_id uuid, p_generation bigint
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
 cp_seq bigint; applying_seq bigint; digest text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 SELECT max(e.seq) INTO applying_seq FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.event_type='APPLYING';
 SELECT k.seq INTO cp_seq FROM change_ledger.checkpoints k
  JOIN change_ledger.events e ON e.tenant_id=k.tenant_id AND e.company_id=k.company_id
   AND e.seq=k.ledger_seq AND e.hash=k.head_hash
  WHERE k.tenant_id=t AND k.company_id=c AND k.sink_kind='REAL' AND k.read_back_confirmed
   AND k.verified AND k.written_by IS NOT NULL
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
 IF p_signature IS DISTINCT FROM change_ledger.keyed_signature(vk.key_material,
   change_ledger.checkpoint_payload(t,c,p_ledger_seq,p_head_hash,p_signed_at,p_signer_key_id,p_sink_kind,p_sink_id)) THEN
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
 IF p_signature IS DISTINCT FROM change_ledger.keyed_signature(vk.key_material,'change-ledger-permit|v1|'||dg) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 UPDATE change_ledger.dispatch_permits SET signer_key_id=p_key_id, signature=p_signature
  WHERE change_id=p_change_id AND generation=p_generation AND state='PERMITTED';
 GET DIAGNOSTICS n = ROW_COUNT;
 IF n=0 THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
END $fn$;

-- ================================================================== wiring, ownership, privileges
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

GRANT USAGE ON SCHEMA change_ledger TO checkpoint_role;
GRANT EXECUTE ON FUNCTION change_ledger.caller_role(), change_ledger.row_in_scope(text,text),
 change_ledger.set_scope(text,text), change_ledger.ledger_head(text,text) TO checkpoint_role;
GRANT EXECUTE ON FUNCTION change_ledger.canonical_content_hash(jsonb), change_ledger.keyed_signature(text,text),
 change_ledger.checkpoint_payload(text,text,bigint,text,timestamptz,text,text,text),
 change_ledger.evidence_binding(uuid,text,text,timestamptz,bigint,uuid)
 TO requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role, checkpoint_role;

-- A1: the raw variants are internals of the signed wrappers; no runtime role may call them
REVOKE EXECUTE ON FUNCTION change_ledger.complete(text,text,uuid,bigint,text,jsonb,jsonb),
 change_ledger.resolve_unknown(text,text,uuid,jsonb,boolean,boolean),
 change_ledger.verify(text,text,uuid,jsonb,boolean),
 change_ledger.witness_cosign(text,text,uuid,jsonb)
 FROM requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role, checkpoint_role;
-- A6: only the checkpoint identity writes checkpoints and signs permits
REVOKE EXECUTE ON FUNCTION
 change_ledger.record_checkpoint(text,text,bigint,text,text,text,text,text,timestamptz,boolean),
 change_ledger.attach_permit_signature(text,text,uuid,bigint,text,text)
 FROM requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.record_checkpoint(text,text,bigint,text,text,text,text,text,timestamptz,boolean),
 change_ledger.attach_permit_signature(text,text,uuid,bigint,text,text) TO checkpoint_role;

GRANT EXECUTE ON FUNCTION
 change_ledger.record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid)
 TO worker_role, writer_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.verify_signed(text,text,uuid,uuid,uuid,uuid),
 change_ledger.retry_verify(text,text,uuid,uuid,uuid,uuid),
 change_ledger.verify_inconclusive(text,text,uuid,uuid) TO worker_role;
GRANT EXECUTE ON FUNCTION change_ledger.complete_lock_busy(text,text,uuid,bigint,uuid,jsonb) TO writer_role;

$body$;
END IF;
END $mig$;
COMMIT;
