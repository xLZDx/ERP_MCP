-- R2/G1 S13, NON-GATING synthetic lane. Carry receipt requirements across claims, reject late
-- receipts, and prevent a receipt public key from being registered for another purpose.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('017', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016']) THEN
EXECUTE $body$

-- Refuse an upgrade if pre-existing rows already reuse a receipt public key for another purpose.
DO $fn$
BEGIN
 IF EXISTS (SELECT 1 FROM change_ledger.verifier_keys k WHERE k.key_algorithm='ED25519'
   GROUP BY k.key_material HAVING bool_or(k.role_name='receipt_role')
    AND bool_or(k.role_name<>'receipt_role')) THEN
  RAISE EXCEPTION 'KEY_ROLE_CONFLICT';
 END IF;
END $fn$;

-- A receipt requirement belongs to the change, not to a disposable claim generation.
CREATE OR REPLACE FUNCTION change_ledger.carry_dispatch_receipt_requirement() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NEW.claim_generation = OLD.claim_generation + 1 THEN
  INSERT INTO change_ledger.dispatch_receipt_requirements
   (tenant_id,company_id,change_id,generation,required_by,required_at)
  SELECT tenant_id,company_id,change_id,NEW.claim_generation,required_by,clock_timestamp()
   FROM change_ledger.dispatch_receipt_requirements
   WHERE change_id=NEW.change_id AND generation=OLD.claim_generation
  ON CONFLICT(change_id,generation) DO NOTHING;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS records_receipt_requirement_carry ON change_ledger.records;
CREATE TRIGGER records_receipt_requirement_carry AFTER UPDATE OF claim_generation ON change_ledger.records
 FOR EACH ROW EXECUTE FUNCTION change_ledger.carry_dispatch_receipt_requirement();

-- Serialize registrations for a public key so concurrent inserts cannot bypass this purpose boundary.
CREATE OR REPLACE FUNCTION change_ledger.verifier_key_receipt_role_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NEW.key_algorithm='ED25519' THEN
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(NEW.key_material, 17017));
  IF EXISTS (SELECT 1 FROM change_ledger.verifier_keys k
    WHERE k.key_material=NEW.key_material AND k.key_algorithm='ED25519'
      AND k.role_name <> NEW.role_name
      AND (k.role_name='receipt_role' OR NEW.role_name='receipt_role')) THEN
   RAISE EXCEPTION 'KEY_ROLE_CONFLICT';
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS verifier_keys_receipt_role_guard ON change_ledger.verifier_keys;
CREATE TRIGGER verifier_keys_receipt_role_guard BEFORE INSERT OR UPDATE OF key_material,key_algorithm,role_name
 ON change_ledger.verifier_keys FOR EACH ROW EXECUTE FUNCTION change_ledger.verifier_key_receipt_role_guard();

-- Refuse an otherwise valid signature after the dispatch has left its active APPLYING state.
CREATE OR REPLACE FUNCTION change_ledger.record_dispatch_receipt(
 t text, c text, p_change_id uuid, p_generation bigint, p_key_id text, p_received_sha text, p_new_version text,
 p_signature text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; vk change_ledger.verifier_keys%ROWTYPE; did uuid; rid uuid;
 ex change_ledger.dispatch_receipts%ROWTYPE;
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
 IF p_received_sha IS DISTINCT FROM rec.payload_digest OR NOT EXISTS(
   SELECT 1 FROM change_ledger.change_dispatch_verifications v WHERE v.change_id=p_change_id
    AND v.generation=p_generation AND v.payload_digest=p_received_sha) THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 SELECT * INTO ex FROM change_ledger.dispatch_receipts r WHERE r.change_id=p_change_id AND r.generation=p_generation;
 IF FOUND THEN
  IF ex.received_payload_sha256=p_received_sha AND ex.new_version=p_new_version AND ex.signature=p_signature THEN RETURN ex.receipt_id; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 INSERT INTO change_ledger.dispatch_receipts(tenant_id,company_id,change_id,generation,dispatch_id,received_payload_sha256,
  new_version,signer_key_id,signature,recorded_by)
 VALUES(t,c,p_change_id,p_generation,did,p_received_sha,p_new_version,p_key_id,p_signature,who) RETURNING receipt_id INTO rid;
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_RECEIPT_RECORDED',
  jsonb_build_object('receipt_id',rid,'generation',p_generation,'dispatch_id',did,'received_payload_sha256',p_received_sha,
   'new_version',p_new_version,'key_id',p_key_id));
 RETURN rid;
END $fn$;

-- Final wiring mirrors 016: SECURITY DEFINER, fixed search_path, ledger ownership, no PUBLIC execute.
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
GRANT EXECUTE ON FUNCTION change_ledger.record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text)
 TO writer_role, requester_role;

$body$;
END IF;
END $mig$;
COMMIT;
