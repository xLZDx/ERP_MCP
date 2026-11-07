BEGIN;

-- Live database budget snapshot. This is advisory; claim/reservation routines remain the atomic gate.
CREATE OR REPLACE FUNCTION change_ledger.budget_snapshot(t text,c text,p_grant_id uuid,
 p_amount numeric,p_currency text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE g change_ledger.grants%ROWTYPE; reserved_amount numeric; remaining numeric; check_code text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_amount IS NULL OR pg_catalog.lower(p_amount::text) IN ('nan','infinity','-infinity')
    OR p_amount<0 OR p_currency IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO g FROM change_ledger.grants x
 WHERE x.grant_id=p_grant_id AND x.tenant_id=t AND x.company_id=c;
 IF NOT FOUND OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF pg_catalog.lower(g.amount_limit::text) IN ('nan','infinity','-infinity') THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 IF g.currency IS DISTINCT FROM p_currency THEN RAISE EXCEPTION 'CURRENCY_NOT_BUDGETED'; END IF;
 IF statement_timestamp()<g.window_start OR statement_timestamp()>=g.window_end THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 SELECT coalesce(sum(r.amount),0) INTO reserved_amount FROM change_ledger.reservations r
 WHERE r.grant_id=p_grant_id AND r.state IN ('RESERVED','CONSUMED');
 IF pg_catalog.lower(reserved_amount::text) IN ('nan','infinity','-infinity') THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 remaining:=g.amount_limit-reserved_amount;
 check_code:=CASE WHEN p_amount>0 AND remaining<=0 THEN 'EXHAUSTED'
                  WHEN p_amount>remaining THEN 'EXCEEDED' ELSE 'OK' END;
 RETURN jsonb_build_object('grant_id',p_grant_id,'currency',g.currency,'limit',g.amount_limit,
  'reserved_and_consumed',reserved_amount,'remaining',remaining,'check',check_code,
  'observed_at',statement_timestamp());
END $fn$;
ALTER FUNCTION change_ledger.budget_snapshot(text,text,uuid,numeric,text) OWNER TO ledger_owner;

REVOKE ALL ON FUNCTION change_ledger.budget_snapshot(text,text,uuid,numeric,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION change_ledger.budget_snapshot(text,text,uuid,numeric,text) TO operator_role,auditor_role;
COMMIT;
