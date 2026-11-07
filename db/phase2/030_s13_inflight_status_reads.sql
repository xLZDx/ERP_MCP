BEGIN;

-- Read-only operator/auditor projections. Never return proposal payload or evidence content.
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

CREATE OR REPLACE FUNCTION change_ledger.operator_status(
 t text,c text,p_change_id uuid
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; result jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who:=change_ledger.caller_role();
 IF who IS NULL OR who='' OR NOT (
   pg_has_role(who::name,'operator_role','USAGE') OR pg_has_role(who::name,'auditor_role','USAGE')
 ) THEN RAISE EXCEPTION 'SCOPE_NOT_GRANTED'; END IF;
 SELECT jsonb_build_object(
  'change_id',r.change_id,'kind',r.kind,'lifecycle',r.lifecycle,
  'authorization',r.authorization_state,'execution',r.execution_state,
  'verification',r.verification_state,'call_ownership',r.call_ownership,
  'reservation',r.reservation_state,'dispatch',r.dispatch_state,
  'claim_generation',r.claim_generation,'expires_at',r.expires_at,
  'created_at',r.created_at,'updated_at',r.updated_at
 ) INTO result
 FROM change_ledger.records r
 WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF result IS NULL THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 RETURN result;
END $fn$;
ALTER FUNCTION change_ledger.operator_status(text,text,uuid) OWNER TO ledger_owner;

REVOKE ALL ON FUNCTION change_ledger.list_inflight(text,text,integer,integer),
 change_ledger.operator_status(text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,writer_role,worker_role,checkpoint_role;
GRANT EXECUTE ON FUNCTION change_ledger.list_inflight(text,text,integer,integer),
 change_ledger.operator_status(text,text,uuid)
 TO operator_role,auditor_role;

COMMIT;
