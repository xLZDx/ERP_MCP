-- S13: keep permit state stable while startup recovery owns the lifecycle fence.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('035', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','028','029','030','031','032','033','034']) THEN
 EXECUTE $body$

-- Keep the existing bounded permit/resource cancellation behind the recovery-state guard.
ALTER FUNCTION change_ledger.cancel_permit_v1(text,text,uuid,bigint)
 RENAME TO cancel_permit_pre_recovery_guard_v1;
REVOKE ALL ON FUNCTION change_ledger.cancel_permit_pre_recovery_guard_v1(text,text,uuid,bigint)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
      checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;

CREATE FUNCTION change_ledger.cancel_permit_v1(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE lifecycle change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 -- Preserve the original scope -> lifecycle lock prefix.
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lifecycle FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lifecycle.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY' USING ERRCODE='P0001';
 END IF;
 RETURN change_ledger.cancel_permit_pre_recovery_guard_v1(
  t,c,p_change_id,p_generation
 );
END $fn$;
ALTER FUNCTION change_ledger.cancel_permit_v1(text,text,uuid,bigint) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.cancel_permit_v1(text,text,uuid,bigint) FROM PUBLIC;

 $body$;
 END IF;
END $mig$;
COMMIT;

