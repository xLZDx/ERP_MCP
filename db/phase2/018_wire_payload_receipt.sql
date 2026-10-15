-- R2/G1 S14 synthetic lane: bind clone-signed receipts to the exact canonical JSON bytes verified
-- before dispatch. NON-GATING prototype; no migration is run by this change and no real 1C is touched.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('018', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017']) THEN
EXECUTE $body$

-- Keep the typed approval digest, add an independent digest for exact canonical bytes.
ALTER TABLE change_ledger.change_dispatch_verifications
 ADD COLUMN IF NOT EXISTS wire_payload_sha256 text
 CHECK (wire_payload_sha256 IS NULL OR wire_payload_sha256 ~ '^[a-f0-9]{64}$');

-- Historical verification rows have no byte-level evidence. Do not backfill them or let their
-- old uniqueness constraint prevent a fresh, byte-bound verification of the same generation.
ALTER TABLE change_ledger.change_dispatch_verifications
 DROP CONSTRAINT IF EXISTS change_dispatch_verifications_change_id_generation_payload_digest_key;
CREATE UNIQUE INDEX IF NOT EXISTS change_dispatch_verifications_wire_uq
 ON change_ledger.change_dispatch_verifications(change_id,generation,payload_digest)
 WHERE wire_payload_sha256 IS NOT NULL;

CREATE OR REPLACE FUNCTION change_ledger.assert_dispatch_verified(p_change_id uuid, p_generation bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
BEGIN
 SELECT * INTO rec FROM change_ledger.records r WHERE r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation OR NOT EXISTS(
   SELECT 1 FROM change_ledger.change_dispatch_verifications v WHERE v.change_id=p_change_id
    AND v.generation=p_generation AND v.payload_digest=rec.payload_digest
    AND v.wire_payload_sha256 IS NOT NULL) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_approval_current(rec.tenant_id,rec.company_id,rec);
END $fn$;

-- The canonical JSON bytes checked here are exactly the bytes the synthetic clone receives.
-- A NULL POST/UNPOST payload has the canonical wire representation {}.
CREATE OR REPLACE FUNCTION change_ledger.verify_dispatch_payload(
 t text, c text, p_change_id uuid, p_generation bigint, p_payload text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; pl jsonb; canonical_payload text; wire_sha text;
        existing_sha text; vid uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF who IS DISTINCT FROM rec.requester AND NOT pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.authorization_state<>'CLAIMED' OR rec.execution_state<>'APPLYING' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_approval_current(t,c,rec);
 BEGIN
  pl := coalesce(p_payload,'{}')::jsonb;
 EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END;
 IF jsonb_typeof(pl)='null' THEN pl := '{}'::jsonb; END IF;
 IF jsonb_typeof(pl)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 canonical_payload := change_ledger.canon_json(pl);
 IF p_payload IS NOT NULL AND p_payload IS DISTINCT FROM canonical_payload THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';  -- no alternative byte encoding can stand for the approved wire body
 END IF;
 IF change_ledger.payload_digest_of(pl,rec.target_version) IS DISTINCT FROM rec.payload_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 wire_sha := change_ledger.text_digest(canonical_payload);

 SELECT v.wire_payload_sha256 INTO existing_sha FROM change_ledger.change_dispatch_verifications v
  WHERE v.change_id=p_change_id AND v.generation=p_generation AND v.payload_digest=rec.payload_digest
    AND v.wire_payload_sha256 IS NOT NULL;
 IF FOUND THEN
  IF existing_sha IS DISTINCT FROM wire_sha THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
  RETURN true;  -- exact canonical payload replay
 END IF;

 INSERT INTO change_ledger.change_dispatch_verifications
  (tenant_id,company_id,change_id,generation,payload_digest,wire_payload_sha256,verified_by)
 VALUES(t,c,p_change_id,p_generation,rec.payload_digest,wire_sha,who)
 RETURNING verification_id INTO vid;
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_PAYLOAD_VERIFIED',
  jsonb_build_object('generation',p_generation,'payload_digest',rec.payload_digest,
                     'wire_payload_sha256',wire_sha,'verification_id',vid));
 RETURN true;
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

-- APPLIED requires the clone receipt to match this generation's immutable byte-verification record.
CREATE OR REPLACE FUNCTION change_ledger.records_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF EXISTS(SELECT 1 FROM change_ledger.dispatch_receipt_requirements q
   WHERE q.change_id=NEW.change_id AND q.generation=NEW.claim_generation)
  AND NOT EXISTS(
   SELECT 1 FROM change_ledger.dispatch_receipts r
   JOIN change_ledger.change_dispatch_verifications v
    ON v.change_id=r.change_id AND v.generation=r.generation AND v.payload_digest=NEW.payload_digest
   WHERE r.change_id=NEW.change_id AND r.generation=NEW.claim_generation
    AND v.wire_payload_sha256 IS NOT NULL AND r.received_payload_sha256=v.wire_payload_sha256) THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS records_receipt_guard ON change_ledger.records;
CREATE TRIGGER records_receipt_guard BEFORE UPDATE ON change_ledger.records
 FOR EACH ROW WHEN (NEW.execution_state='APPLIED' AND OLD.execution_state IS DISTINCT FROM 'APPLIED')
 EXECUTE FUNCTION change_ledger.records_receipt_guard();

-- Keep S13's fixed SECURITY DEFINER/search_path/owner/Public ACL policy for the new migration functions.
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
GRANT EXECUTE ON FUNCTION change_ledger.verify_dispatch_payload(text,text,uuid,bigint,text),
 change_ledger.record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text) TO writer_role, requester_role;

$body$;
END IF;
END $mig$;
COMMIT;
