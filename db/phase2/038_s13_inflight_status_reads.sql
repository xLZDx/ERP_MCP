-- Restore the missing applied-but-unverified status filter while keeping 029's richer operator projection.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('038', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','028','029','030','031','032','033','034','035','036','037']) THEN
  EXECUTE $body$
CREATE OR REPLACE FUNCTION change_ledger.list_inflight(
 t text,c text,p_limit integer DEFAULT 50,p_offset integer DEFAULT 0
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; result jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who:=change_ledger.caller_role();
 IF who IS NULL OR who='' OR NOT (
   pg_has_role(who::name,'operator_role','USAGE') OR pg_has_role(who::name,'auditor_role','USAGE')
 ) THEN RAISE EXCEPTION 'SCOPE_NOT_GRANTED'; END IF;
 IF p_limit IS NULL OR p_limit<1 OR p_limit>100 OR p_offset IS NULL OR p_offset<0 THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at,x.change_id),'[]'::jsonb)
 INTO result
 FROM (
  SELECT change_id,kind,lifecycle,authorization_state,execution_state,verification_state,
         call_ownership,reservation_state,dispatch_state,claim_generation,created_at,updated_at
  FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c
    AND r.lifecycle IN ('PROPOSED','VALIDATED')
    AND r.authorization_state IN ('NONE','APPROVED','CLAIMED')
    AND (
      r.execution_state IN ('NOT_STARTED','APPLYING','APPLY_UNKNOWN','TRIAGE_REQUIRED')
      OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')
    )
  ORDER BY r.created_at,r.change_id
  LIMIT p_limit OFFSET p_offset
 ) x;
 RETURN result;
END $fn$;
ALTER FUNCTION change_ledger.list_inflight(text,text,integer,integer) OWNER TO ledger_owner;

REVOKE ALL ON FUNCTION change_ledger.list_inflight(text,text,integer,integer)
 FROM PUBLIC,requester_role,approver_role,writer_role,worker_role,checkpoint_role;
GRANT EXECUTE ON FUNCTION change_ledger.list_inflight(text,text,integer,integer)
 TO operator_role,auditor_role;
  $body$;
 END IF;
END
$mig$;
COMMIT;
