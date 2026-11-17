-- S13: keep FAILED_VERIFY_HALT closed while startup recovery owns the lifecycle fence.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('033', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','028','029','030','031','032']) THEN
 EXECUTE $body$

-- Keep the existing bounded retry/evidence/hold implementation behind a lifecycle guard.
-- Migration 027 revoked application EXECUTE on this entry; preserve that closure after rename.
ALTER FUNCTION change_ledger.retry_verify_v1(text,text,uuid,uuid,uuid,uuid)
 RENAME TO retry_verify_pre_recovery_guard_v1;
REVOKE ALL ON FUNCTION change_ledger.retry_verify_pre_recovery_guard_v1(text,text,uuid,uuid,uuid,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
      checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;

CREATE FUNCTION change_ledger.retry_verify_v1(
 t text,c text,p_change_id uuid,p_field uuid,p_movement uuid,p_version uuid
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE lifecycle change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 -- Preserve the original switch -> scope -> lifecycle lock prefix.
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lifecycle FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lifecycle.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY' USING ERRCODE='P0001';
 END IF;
 RETURN change_ledger.retry_verify_pre_recovery_guard_v1(
  t,c,p_change_id,p_field,p_movement,p_version
 );
END $fn$;
ALTER FUNCTION change_ledger.retry_verify_v1(text,text,uuid,uuid,uuid,uuid) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.retry_verify_v1(text,text,uuid,uuid,uuid,uuid) FROM PUBLIC;

 $body$;
 END IF;
END $mig$;
COMMIT;

