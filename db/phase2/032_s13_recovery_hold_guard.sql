-- S13: prevent generic hold release while startup recovery owns the lifecycle fence.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('032', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','030','031']) THEN
 EXECUTE $body$

-- Keep the original proof, row-plan and hold-release implementation behind the guarded entry.
-- Migration 027 already revoked application EXECUTE on this function; retain that closure after
-- renaming so no caller can bypass the recovery-state check.
ALTER FUNCTION change_ledger.release_hold_v1(text,text,uuid,jsonb)
 RENAME TO release_hold_pre_recovery_guard_v1;
REVOKE ALL ON FUNCTION change_ledger.release_hold_pre_recovery_guard_v1(text,text,uuid,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
      checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;

CREATE FUNCTION change_ledger.release_hold_v1(
 t text,c text,p_hold_id uuid,p_release_evidence jsonb
) RETURNS timestamptz
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE lifecycle change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 -- Preserve the exact ranked prefix used by the original function before locking lifecycle state.
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lifecycle FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lifecycle.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY' USING ERRCODE='P0001';
 END IF;
 RETURN change_ledger.release_hold_pre_recovery_guard_v1(
  t,c,p_hold_id,p_release_evidence
 );
END $fn$;
ALTER FUNCTION change_ledger.release_hold_v1(text,text,uuid,jsonb) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.release_hold_v1(text,text,uuid,jsonb) FROM PUBLIC;

 $body$;
 END IF;
END $mig$;
COMMIT;

