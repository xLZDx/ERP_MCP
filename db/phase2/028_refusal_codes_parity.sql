-- S12/S13 additive contract closure. Apply only through the controlled migration runner.
BEGIN;

CREATE TABLE IF NOT EXISTS change_ledger.refusal_code_registry (
 code text PRIMARY KEY CHECK (code ~ '^[A-Z][A-Z0-9_]*$')
);
ALTER TABLE change_ledger.refusal_code_registry OWNER TO ledger_owner;
INSERT INTO change_ledger.refusal_code_registry(code) VALUES
 ('SCHEMA_INVALID'),('SHAPE_NOT_QUALIFIED'),('SCOPE_MISMATCH'),('REF_OUT_OF_SCOPE'),
 ('NOT_ENTITLED'),('APPROVER_NOT_INDEPENDENT'),('APPROVAL_MISSING'),('APPROVAL_EXPIRED'),
 ('APPROVAL_VOIDED'),('APPROVAL_NONCE_INVALID'),('COMPLETION_PROOF_MISSING'),('ATTRIBUTION_UNPROVEN'),
 ('PERMIT_MISSING'),('TICKET_SUPERSEDED'),('DIGEST_MISMATCH'),('STALE_VERSION'),('IDEMPOTENCY_CONFLICT'),
 ('DUPLICATE_SUSPECTED'),('EPOCH_CHANGED'),('TARGET_REJECTED'),('KILL_SWITCH_ACTIVE'),('BASE_HOLD'),
 ('PARENT_NOT_VERIFIED'),('CLAIM_EXPIRED'),('BUDGET_EXCEEDED'),('CURRENCY_NOT_BUDGETED'),
 ('AUDIT_UNAVAILABLE'),('CHECKPOINT_UNAVAILABLE'),('LOCK_BUSY'),('WRITE_REFUSED'),('APPLY_UNKNOWN'),
 ('TRIAGE_REQUIRED'),('ROLLBACK_REFUSED'),('VERIFY_FAILED'),('MARKER_UNTRUSTED'),('EVIDENCE_UNSIGNED'),
 ('AMOUNT_INCONSISTENT'),('PERIOD_CLOSED'),('GRANT_EXHAUSTED')
ON CONFLICT (code) DO NOTHING;
DO $check$
BEGIN
 IF (SELECT count(*) FROM change_ledger.refusal_code_registry) <> 39
    OR EXISTS (
      (SELECT code FROM change_ledger.refusal_code_registry
       EXCEPT SELECT code FROM (VALUES
        ('SCHEMA_INVALID'),('SHAPE_NOT_QUALIFIED'),('SCOPE_MISMATCH'),('REF_OUT_OF_SCOPE'),
        ('NOT_ENTITLED'),('APPROVER_NOT_INDEPENDENT'),('APPROVAL_MISSING'),('APPROVAL_EXPIRED'),
        ('APPROVAL_VOIDED'),('APPROVAL_NONCE_INVALID'),('COMPLETION_PROOF_MISSING'),('ATTRIBUTION_UNPROVEN'),
        ('PERMIT_MISSING'),('TICKET_SUPERSEDED'),('DIGEST_MISMATCH'),('STALE_VERSION'),('IDEMPOTENCY_CONFLICT'),
        ('DUPLICATE_SUSPECTED'),('EPOCH_CHANGED'),('TARGET_REJECTED'),('KILL_SWITCH_ACTIVE'),('BASE_HOLD'),
        ('PARENT_NOT_VERIFIED'),('CLAIM_EXPIRED'),('BUDGET_EXCEEDED'),('CURRENCY_NOT_BUDGETED'),
        ('AUDIT_UNAVAILABLE'),('CHECKPOINT_UNAVAILABLE'),('LOCK_BUSY'),('WRITE_REFUSED'),('APPLY_UNKNOWN'),
        ('TRIAGE_REQUIRED'),('ROLLBACK_REFUSED'),('VERIFY_FAILED'),('MARKER_UNTRUSTED'),('EVIDENCE_UNSIGNED'),
        ('AMOUNT_INCONSISTENT'),('PERIOD_CLOSED'),('GRANT_EXHAUSTED')
       ) expected(code))
      UNION ALL
      (SELECT code FROM (VALUES
        ('SCHEMA_INVALID'),('SHAPE_NOT_QUALIFIED'),('SCOPE_MISMATCH'),('REF_OUT_OF_SCOPE'),
        ('NOT_ENTITLED'),('APPROVER_NOT_INDEPENDENT'),('APPROVAL_MISSING'),('APPROVAL_EXPIRED'),
        ('APPROVAL_VOIDED'),('APPROVAL_NONCE_INVALID'),('COMPLETION_PROOF_MISSING'),('ATTRIBUTION_UNPROVEN'),
        ('PERMIT_MISSING'),('TICKET_SUPERSEDED'),('DIGEST_MISMATCH'),('STALE_VERSION'),('IDEMPOTENCY_CONFLICT'),
        ('DUPLICATE_SUSPECTED'),('EPOCH_CHANGED'),('TARGET_REJECTED'),('KILL_SWITCH_ACTIVE'),('BASE_HOLD'),
        ('PARENT_NOT_VERIFIED'),('CLAIM_EXPIRED'),('BUDGET_EXCEEDED'),('CURRENCY_NOT_BUDGETED'),
        ('AUDIT_UNAVAILABLE'),('CHECKPOINT_UNAVAILABLE'),('LOCK_BUSY'),('WRITE_REFUSED'),('APPLY_UNKNOWN'),
        ('TRIAGE_REQUIRED'),('ROLLBACK_REFUSED'),('VERIFY_FAILED'),('MARKER_UNTRUSTED'),('EVIDENCE_UNSIGNED'),
        ('AMOUNT_INCONSISTENT'),('PERIOD_CLOSED'),('GRANT_EXHAUSTED')
       ) expected(code)
       EXCEPT SELECT code FROM change_ledger.refusal_code_registry)
    ) THEN
  RAISE EXCEPTION 'REFUSAL_CODE_REGISTRY_DRIFT';
 END IF;
END $check$;

-- Keep the exact 027 admission arithmetic, with only the S12 exhausted-grant distinction added.
CREATE OR REPLACE FUNCTION change_ledger.budget_precheck(
 t text,c text,p_rec change_ledger.records,p_lock boolean,p_window boolean
) RETURNS numeric LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE cb change_ledger.change_budget%ROWTYPE; g change_ledger.grants%ROWTYPE; eff numeric;
        used_amount numeric; consumed_amount numeric; used_cu integer; used_post integer; tref text;
BEGIN
 SELECT * INTO cb FROM change_ledger.change_budget b WHERE b.change_id=p_rec.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF p_lock THEN
  SELECT * INTO g FROM change_ledger.grants x
   WHERE x.grant_id=cb.grant_id AND x.tenant_id=t AND x.company_id=c FOR UPDATE;
 ELSE
  SELECT * INTO g FROM change_ledger.grants x
   WHERE x.grant_id=cb.grant_id AND x.tenant_id=t AND x.company_id=c;
 END IF;
 IF NOT FOUND OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF pg_catalog.lower(cb.amount::text) IN ('nan','infinity','-infinity')
   OR pg_catalog.lower(g.amount_limit::text) IN ('nan','infinity','-infinity') THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 IF g.currency IS DISTINCT FROM cb.currency THEN RAISE EXCEPTION 'CURRENCY_NOT_BUDGETED'; END IF;
 IF p_window AND (pg_catalog.clock_timestamp()<g.window_start
   OR pg_catalog.clock_timestamp()>=g.window_end) THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 tref:=coalesce(p_rec.target_ref,p_rec.change_id::text);
 eff:=cb.amount;
 IF p_rec.kind='POST' THEN
  consumed_amount:=change_ledger.amount_consumed(t,c,tref,cb.grant_id);
  IF pg_catalog.lower(consumed_amount::text) IN ('nan','infinity','-infinity') THEN
   RAISE EXCEPTION 'BUDGET_EXCEEDED';
  END IF;
  eff:=greatest(eff-consumed_amount,0);
 END IF;
 SELECT coalesce(sum(r.amount),0),
        count(*) FILTER (WHERE r.counts_create_update),count(*) FILTER (WHERE r.counts_post)
  INTO used_amount,used_cu,used_post
  FROM change_ledger.reservations r
  WHERE r.grant_id=cb.grant_id AND r.state IN ('RESERVED','CONSUMED')
    AND r.change_id<>p_rec.change_id;
 IF pg_catalog.lower(used_amount::text) IN ('nan','infinity','-infinity') THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 IF eff>0 AND used_amount>=g.amount_limit THEN RAISE EXCEPTION 'GRANT_EXHAUSTED'; END IF;
 IF used_amount+eff>g.amount_limit
  OR used_cu+(CASE WHEN cb.counts_create_update THEN 1 ELSE 0 END)>g.count_limit
  OR used_post+(CASE WHEN cb.counts_post THEN 1 ELSE 0 END)>g.post_count_limit THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 RETURN eff;
END $fn$;
ALTER FUNCTION change_ledger.budget_precheck(text,text,change_ledger.records,boolean,boolean)
 OWNER TO ledger_owner;

REVOKE ALL ON TABLE change_ledger.refusal_code_registry FROM PUBLIC,requester_role,approver_role,
 operator_role,writer_role,worker_role,auditor_role,checkpoint_role;
COMMIT;
