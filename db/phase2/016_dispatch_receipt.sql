-- R2/G1 S13, simulated lane of the change ledger (simulation program P4, GPT-PM F-01): the receipt of the bytes the (simulated)
-- 1C RECEIVED is signed by the clone itself and verified INSIDE the ledger. Applies after 015. Apply ONLY to a verified
-- disposable PostgreSQL database (checksum precondition: living.record_migration). NON-GATING PROTOTYPE: not gate evidence;
-- no real 1C write. Every key and signature of the test lane is synthetic.
--
-- DESIGN.
--  1. Purpose-bound key. The clone's Ed25519 public key is registered in the 015 registry (verifier_keys) with the role
--     'receipt_role', a NOLOGIN role created here that no runtime actor is a member of. A receipt key therefore can never
--     sign evidence (record_evidence needs the caller to hold the key's role), checkpoints or permits (checkpoint_role),
--     and no other key is accepted for a receipt (role_name must be 'receipt_role').
--  2. Receipt-required marker (opt-in, so every existing flow keeps working unchanged): require_dispatch_receipt marks ONE
--     dispatch (change_id, claim generation) before it is dispatched. A marker row is immutable.
--  3. record_dispatch_receipt(t, c, change_id, generation, key_id, received_payload_sha256, new_version, signature): after
--     the dispatch (records.dispatch_state DISPATCHED) the writer forwards the clone's receipt. The ledger rebuilds the
--     signed text 'change-ledger-receipt|v1|<change_id>|<dispatch_id>|<sha256>|<new_version>' from ITS OWN dispatch id (the
--     call_id of the permit of that generation), so a receipt of another dispatch or change never verifies. It checks the
--     signature (change_ledger.signature_ok, one verification) and that received_payload_sha256 equals the payload digest
--     recorded by verify_dispatch_payload for that generation (change_dispatch_verifications) and the approved
--     records.payload_digest. One receipt per (change, generation); an exact replay returns the same id.
--  4. Completion gate: a BEFORE UPDATE trigger on records refuses execution_state -> APPLIED when the current generation
--     carries a marker and has no stored receipt (or the receipt no longer matches the approved digest). Being a trigger it
--     covers complete, complete_signed and every other path to APPLIED.
--  Error codes (no new ones): EVIDENCE_UNSIGNED (missing key / wrong role / bad signature / missing receipt), DIGEST_MISMATCH
--  (received digest differs from the verified / approved digest), PERMIT_MISSING (not dispatched), TICKET_SUPERSEDED,
--  NOT_ENTITLED, SCHEMA_INVALID, CHANGE_NOT_FOUND, FORBIDDEN_TRANSITION.
--
-- NAMED LIMITS.
--  * The marker is opt-in: a dispatch without a marker completes as before (legacy lane). Whoever may call
--    require_dispatch_receipt (the requester or a writer) could also leave it out; this is a simulation-lane control, not a
--    defence against a trusted writer.
--  * records.payload_digest is the 009 digest of the typed payload, not the sha256 of wire bytes: the simulation passes that
--    digest as the clone's "received" digest. The ledger cannot prove the bytes the clone really received.
--  * The trusted boundary of 013 applies (table owner / superuser can alter the trigger).
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('016', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015']) THEN
EXECUTE $body$

-- ================================================================== the purpose role
DO $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='receipt_role') THEN
  CREATE ROLE receipt_role NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
 ELSIF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='receipt_role' AND (rolsuper OR rolbypassrls OR rolcanlogin)) THEN
  RAISE EXCEPTION 'LEDGER_ROLE_UNSAFE: receipt_role';
 END IF;
END $fn$;

-- ================================================================== storage
CREATE TABLE IF NOT EXISTS change_ledger.dispatch_receipt_requirements(
 tenant_id text NOT NULL, company_id text NOT NULL,
 change_id uuid NOT NULL,
 generation bigint NOT NULL,
 required_by text NOT NULL, required_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(change_id, generation),
 FOREIGN KEY(tenant_id,company_id,change_id) REFERENCES change_ledger.records(tenant_id,company_id,change_id)
);
CREATE TABLE IF NOT EXISTS change_ledger.dispatch_receipts(
 receipt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL,
 change_id uuid NOT NULL,
 generation bigint NOT NULL,
 dispatch_id uuid NOT NULL,
 received_payload_sha256 text NOT NULL CHECK(received_payload_sha256 ~ '^[a-f0-9]{64}$'),
 new_version text NOT NULL,
 signer_key_id text NOT NULL,
 signature text NOT NULL CHECK(signature ~ '^[0-9a-f]{128}$'),
 recorded_by text NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(change_id, generation),
 FOREIGN KEY(tenant_id,company_id,change_id) REFERENCES change_ledger.records(tenant_id,company_id,change_id)
);
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY['dispatch_receipt_requirements','dispatch_receipts'] LOOP
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
  EXECUTE format('GRANT SELECT ON change_ledger.%I TO auditor_role',tbl);
 END LOOP;
END $fn$;

-- ================================================================== the signed text (the clone builds the same string)
CREATE OR REPLACE FUNCTION change_ledger.dispatch_receipt_text(p_change_id uuid, p_dispatch_id uuid, p_sha text, p_version text)
RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
 SELECT 'change-ledger-receipt|v1|'||p_change_id::text||'|'||p_dispatch_id::text||'|'||p_sha||'|'||p_version
$fn$;

-- ================================================================== marker
CREATE OR REPLACE FUNCTION change_ledger.require_dispatch_receipt(t text, c text, p_change_id uuid, p_generation bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF who IS DISTINCT FROM rec.requester AND NOT pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' OR rec.dispatch_state='DISPATCHED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 INSERT INTO change_ledger.dispatch_receipt_requirements(tenant_id,company_id,change_id,generation,required_by)
 VALUES(t,c,p_change_id,p_generation,who) ON CONFLICT(change_id,generation) DO NOTHING;
END $fn$;

-- ================================================================== the receipt
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
  OR p_new_version IS NULL OR p_new_version='' OR position('|' in p_new_version)>0 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF who IS DISTINCT FROM rec.requester AND NOT pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT dp.call_id INTO did FROM change_ledger.dispatch_permits dp
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation AND dp.state='DISPATCHED';
 IF NOT FOUND OR rec.dispatch_state<>'DISPATCHED' THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'receipt_role' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,                          -- one verification
   change_ledger.dispatch_receipt_text(p_change_id,did,p_received_sha,p_new_version),p_signature) THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 IF p_received_sha IS DISTINCT FROM rec.payload_digest OR NOT EXISTS(
   SELECT 1 FROM change_ledger.change_dispatch_verifications v WHERE v.change_id=p_change_id
    AND v.generation=p_generation AND v.payload_digest=p_received_sha) THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';             -- the clone received other bytes than the approved / verified payload
 END IF;
 SELECT * INTO ex FROM change_ledger.dispatch_receipts r WHERE r.change_id=p_change_id AND r.generation=p_generation;
 IF FOUND THEN
  IF ex.received_payload_sha256=p_received_sha AND ex.new_version=p_new_version AND ex.signature=p_signature THEN
   RETURN ex.receipt_id;                         -- exact replay: idempotent
  END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 INSERT INTO change_ledger.dispatch_receipts(tenant_id,company_id,change_id,generation,dispatch_id,received_payload_sha256,
  new_version,signer_key_id,signature,recorded_by)
 VALUES(t,c,p_change_id,p_generation,did,p_received_sha,p_new_version,p_key_id,p_signature,who)
 RETURNING receipt_id INTO rid;
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_RECEIPT_RECORDED',
  jsonb_build_object('receipt_id',rid,'generation',p_generation,'dispatch_id',did,'received_payload_sha256',p_received_sha,
   'new_version',p_new_version,'key_id',p_key_id));
 RETURN rid;
END $fn$;

-- ================================================================== completion gate (every path to APPLIED)
CREATE OR REPLACE FUNCTION change_ledger.records_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF EXISTS(SELECT 1 FROM change_ledger.dispatch_receipt_requirements q
   WHERE q.change_id=NEW.change_id AND q.generation=NEW.claim_generation)
  AND NOT EXISTS(SELECT 1 FROM change_ledger.dispatch_receipts r WHERE r.change_id=NEW.change_id
   AND r.generation=NEW.claim_generation AND r.received_payload_sha256=NEW.payload_digest) THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';           -- a receipt-required dispatch cannot complete without a matching receipt
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS records_receipt_guard ON change_ledger.records;
CREATE TRIGGER records_receipt_guard BEFORE UPDATE ON change_ledger.records
 FOR EACH ROW WHEN (NEW.execution_state='APPLIED' AND OLD.execution_state IS DISTINCT FROM 'APPLIED')
 EXECUTE FUNCTION change_ledger.records_receipt_guard();

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

-- the two entry points are called by the writer (or the requester of the change); everything else stays internal
GRANT EXECUTE ON FUNCTION change_ledger.require_dispatch_receipt(text,text,uuid,bigint),
 change_ledger.record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text) TO writer_role, requester_role;

$body$;
END IF;
END $mig$;
COMMIT;
