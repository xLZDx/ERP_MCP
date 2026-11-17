-- Revalidate approval principal epochs under locks at each effect gate.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('039', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','030','031','032','033','034','035','036','037','038']) THEN
  EXECUTE $body$
CREATE OR REPLACE FUNCTION change_ledger.assert_approval_current(
 t text, c text, p_rec change_ledger.records
) RETURNS void LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
 ap change_ledger.approvals%ROWTYPE;
 env change_ledger.approval_envelopes%ROWTYPE;
 ej jsonb;
 principal_dep record;
 current_epoch bigint;
 principal_active boolean;
 keys text[] := ARRAY['digest_version','change_id','kind','scope','payload_digest','target_ref','target_version',
                      'parent_change_id','repair_for'];
BEGIN
 FOR principal_dep IN
  SELECT d.key, d.value::bigint AS expected_epoch
  FROM jsonb_each_text(coalesce(p_rec.epoch_dependencies,'{}'::jsonb)) d
  WHERE d.key LIKE 'principal:%'
  ORDER BY d.key
 LOOP
  SELECT p.active INTO principal_active
  FROM change_ledger.principals p
  WHERE p.tenant_id=t AND p.company_id=c
    AND p.principal=substring(principal_dep.key FROM 11)
  FOR SHARE;
  IF NOT FOUND OR principal_active IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'EPOCH_CHANGED';
  END IF;

  SELECT e.value INTO current_epoch
  FROM change_ledger.epochs e
  WHERE e.tenant_id=t AND e.company_id=c AND e.epoch_key=principal_dep.key
  FOR SHARE;
  IF NOT FOUND THEN current_epoch := 0; END IF;
  IF current_epoch IS DISTINCT FROM principal_dep.expected_epoch THEN
   RAISE EXCEPTION 'EPOCH_CHANGED';
  END IF;
 END LOOP;

 SELECT * INTO ap FROM change_ledger.approvals a WHERE a.change_id=p_rec.change_id AND a.decision='APPROVE'
  ORDER BY a.approved_at DESC, a.approval_id DESC LIMIT 1;
 IF NOT FOUND OR ap.digest_version IS DISTINCT FROM 'S12-APPROVAL-2' OR ap.envelope_id IS NULL THEN
  RAISE EXCEPTION 'APPROVAL_VOIDED';
 END IF;
 SELECT * INTO env FROM change_ledger.approval_envelopes e WHERE e.envelope_id=ap.envelope_id
  AND e.change_id=p_rec.change_id AND e.tenant_id=t AND e.company_id=c;
 IF NOT FOUND OR change_ledger.text_digest(env.canonical_text) IS DISTINCT FROM ap.digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 ej := env.canonical_text::jsonb;
 IF change_ledger.envelope_subset(ej,keys)
    IS DISTINCT FROM change_ledger.envelope_subset(change_ledger.envelope_expected(p_rec,env.approval_nonce),keys)
  OR change_ledger.envelope_payload_digest(ej) IS DISTINCT FROM p_rec.payload_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
END $fn$;
  $body$;
 END IF;
END
$mig$;
COMMIT;
