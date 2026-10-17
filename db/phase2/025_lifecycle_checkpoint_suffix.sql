-- Bounded, read-only evidence for classifying the ledger tail after an authenticated checkpoint.
-- This does not establish anti-rollback freshness, acquire the lifecycle fence, run recovery,
-- or authorize READY. Those remain separate S13 acceptance requirements.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('025', ARRAY['001','002','003','004','005','006','007','008','009',
   '010','011','012','013','014','015','016','017','018','019','020','021','022','023','024']) THEN
 EXECUTE $body$

CREATE OR REPLACE FUNCTION change_ledger.lifecycle_checkpoint_suffix(
 t text, c text, p_checkpoint_seq bigint, p_checkpoint_hash text, p_limit integer DEFAULT 128
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE
 who text;
 head_seq bigint;
 head_hash text;
 anchor_matches boolean;
 has_more boolean;
 suffix_events jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT (pg_has_role(who::name,'worker_role','USAGE')
         OR pg_has_role(who::name,'auditor_role','USAGE')) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_checkpoint_seq IS NULL OR p_checkpoint_seq < 1
    OR p_checkpoint_hash IS NULL OR p_checkpoint_hash !~ '^[a-f0-9]{64}$'
    OR p_limit IS NULL OR p_limit < 1 OR p_limit > 128 THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;

 SELECT e.seq,e.hash INTO head_seq,head_hash
  FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c
  ORDER BY e.seq DESC LIMIT 1;
 head_seq := coalesce(head_seq,0);
 anchor_matches := EXISTS(
  SELECT 1 FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c
    AND e.seq=p_checkpoint_seq AND e.hash=p_checkpoint_hash
 );

 SELECT EXISTS(
  SELECT 1 FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.seq>p_checkpoint_seq
  ORDER BY e.seq OFFSET p_limit LIMIT 1
 ) INTO has_more;

 SELECT coalesce(jsonb_agg(q.event_json ORDER BY q.seq),'[]'::jsonb)
  INTO suffix_events
  FROM (
   SELECT e.seq,
    jsonb_build_object(
     'seq',e.seq,
     'event_id',e.event_id,
     'change_id',e.change_id,
     'event_type',e.event_type,
     'payload',e.payload,
     'hash',e.hash,
     'record',CASE WHEN r.change_id IS NULL THEN NULL ELSE jsonb_build_object(
      'execution_state',r.execution_state,
      'verification_state',r.verification_state,
      'call_ownership',r.call_ownership,
      'reservation_state',r.reservation_state,
      'dispatch_state',r.dispatch_state
     ) END
    ) AS event_json
   FROM change_ledger.events e
   LEFT JOIN change_ledger.records r
    ON r.change_id=e.change_id AND r.tenant_id=e.tenant_id AND r.company_id=e.company_id
   WHERE e.tenant_id=t AND e.company_id=c AND e.seq>p_checkpoint_seq
   ORDER BY e.seq
   LIMIT p_limit
  ) q;

 RETURN jsonb_build_object(
  'tenant_id',t,
  'company_id',c,
  'checkpoint_seq',p_checkpoint_seq,
  'checkpoint_hash',p_checkpoint_hash,
  'anchor_matches',anchor_matches,
  'head_seq',head_seq,
  'head_hash',head_hash,
  'has_more',has_more,
  'events',suffix_events
 );
END $fn$;

REVOKE ALL ON FUNCTION change_ledger.lifecycle_checkpoint_suffix(text,text,bigint,text,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role;
GRANT EXECUTE ON FUNCTION change_ledger.lifecycle_checkpoint_suffix(text,text,bigint,text,integer)
 TO worker_role,auditor_role;
ALTER FUNCTION change_ledger.lifecycle_checkpoint_suffix(text,text,bigint,text,integer)
 OWNER TO ledger_owner;

    $body$;
 END IF;
END $mig$;
COMMIT;
