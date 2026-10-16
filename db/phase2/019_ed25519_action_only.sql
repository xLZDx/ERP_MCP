-- R-03 prototype: require Ed25519 for new signed actions while preserving the internal legacy verifier branch.
-- NON-GATING prototype only. No live keys, deployed key inventory, or production writer is asserted by this migration.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('019', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018']) THEN
EXECUTE $body$

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
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
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
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
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
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,'change-ledger-permit|v1|'||dg,p_signature) THEN   -- one verification
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 UPDATE change_ledger.dispatch_permits SET signer_key_id=p_key_id, signature=p_signature
  WHERE change_id=p_change_id AND generation=p_generation AND state='PERMITTED';
 GET DIAGNOSTICS n = ROW_COUNT;
 IF n=0 THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.record_dispatch_receipt(
 t text, c text, p_change_id uuid, p_generation bigint, p_key_id text, p_received_sha text, p_new_version text,
 p_signature text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; vk change_ledger.verifier_keys%ROWTYPE; did uuid; rid uuid;
        ex change_ledger.dispatch_receipts%ROWTYPE; verified_wire_sha text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF p_change_id IS NULL OR p_generation IS NULL OR p_key_id IS NULL OR p_key_id='' OR p_signature IS NULL
  OR p_received_sha IS NULL OR p_received_sha !~ '^[a-f0-9]{64}$'
  OR p_new_version IS NULL OR p_new_version='' OR position('|' in p_new_version)>0 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF who IS DISTINCT FROM rec.requester AND NOT pg_has_role(who::name,'writer_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state <> 'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT dp.call_id INTO did FROM change_ledger.dispatch_permits dp
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation AND dp.state='DISPATCHED';
 IF NOT FOUND OR rec.dispatch_state<>'DISPATCHED' THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'receipt_role' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,
   change_ledger.dispatch_receipt_text(p_change_id,did,p_received_sha,p_new_version),p_signature) THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 SELECT v.wire_payload_sha256 INTO verified_wire_sha FROM change_ledger.change_dispatch_verifications v
  WHERE v.change_id=p_change_id AND v.generation=p_generation AND v.payload_digest=rec.payload_digest
    AND v.wire_payload_sha256 IS NOT NULL;
 IF NOT FOUND OR verified_wire_sha IS NULL OR verified_wire_sha IS DISTINCT FROM p_received_sha THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 SELECT * INTO ex FROM change_ledger.dispatch_receipts r WHERE r.change_id=p_change_id AND r.generation=p_generation;
 IF FOUND THEN
  IF ex.received_payload_sha256=p_received_sha AND ex.new_version=p_new_version AND ex.signature=p_signature THEN RETURN ex.receipt_id; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 INSERT INTO change_ledger.dispatch_receipts(tenant_id,company_id,change_id,generation,dispatch_id,received_payload_sha256,
  new_version,signer_key_id,signature,recorded_by)
 VALUES(t,c,p_change_id,p_generation,did,p_received_sha,p_new_version,p_key_id,p_signature,who) RETURNING receipt_id INTO rid;
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_RECEIPT_RECORDED',
  jsonb_build_object('receipt_id',rid,'generation',p_generation,'dispatch_id',did,
   'received_payload_sha256',p_received_sha,'new_version',p_new_version,'key_id',p_key_id));
 RETURN rid;
END $fn$;

-- Keep the existing SECURITY DEFINER/search_path/owner/Public ACL policy for replaced functions.
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

$body$;
END IF;
END $mig$;
COMMIT;
