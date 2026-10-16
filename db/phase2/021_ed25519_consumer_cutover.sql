-- R-03: prevent pre-cutover stand-in signatures from authorizing post-cutover state changes.
-- Historical read_evidence remains unchanged; this migration only tightens action-time evidence use.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('021', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020']) THEN
EXECUTE $body$

-- Action consumers share this lookup. Legacy evidence remains readable through read_evidence, but cannot
-- authorize a state transition after cutover because verifier-key algorithms are immutable after registration.
CREATE OR REPLACE FUNCTION change_ledger.evidence_ref(t text, c text, p_change_id uuid, p_evidence_id uuid, p_kind text)
RETURNS change_ledger.evidence_records LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ev change_ledger.evidence_records%ROWTYPE;
BEGIN
 IF p_evidence_id IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 SELECT e.* INTO ev FROM change_ledger.evidence_records e
  JOIN change_ledger.verifier_keys k ON k.tenant_id=e.tenant_id AND k.company_id=e.company_id
   AND k.key_id=e.signer_key_id AND k.key_algorithm='ED25519'
  WHERE e.evidence_id=p_evidence_id AND e.tenant_id=t AND e.company_id=c
   AND e.change_id=p_change_id AND e.kind=p_kind;
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 RETURN ev;
END $fn$;

-- Historical witness cosigns embed an evidence id rather than a key id. Resolve it back to the immutable
-- evidence row and require the same proof class, scope, kind, and Ed25519 signer before consuming the cosign.
CREATE OR REPLACE FUNCTION change_ledger.assert_ed25519_cosign_evidence(
 t text, c text, p_change_id uuid, p_proof jsonb
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM change_ledger.evidence_records e
   JOIN change_ledger.verifier_keys k ON k.tenant_id=e.tenant_id AND k.company_id=e.company_id
    AND k.key_id=e.signer_key_id AND k.key_algorithm='ED25519'
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.kind='COMPLETION_PROOF'
   AND e.evidence_id=CASE
    WHEN coalesce(p_proof->>'evidence_id','') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     THEN (p_proof->>'evidence_id')::uuid ELSE NULL END
   AND e.content->>'class'=p_proof->>'class'
 ) THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
END $fn$;

-- Defense in depth for the internal completion primitive: a refusal record is looked up only in caller
-- scope and only when its signer key is Ed25519 (the public signed wrapper applies the same rule above).
CREATE OR REPLACE FUNCTION change_ledger.complete(
 t text, c text, p_change_id uuid, p_generation bigint, p_outcome text,
 p_evidence jsonb, p_no_effect_proof jsonb DEFAULT NULL
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_exec text; new_res text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL OR p_outcome IS NULL
  OR p_outcome NOT IN ('SUCCESS','PRE_WRITE_REFUSAL','UNKNOWN') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN
  IF rec.execution_state IN ('APPLIED','APPLY_UNKNOWN','FAILED_APPLY','ROLLBACK_REFUSED') THEN RETURN rec.execution_state; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_outcome IN ('SUCCESS','UNKNOWN') AND rec.dispatch_state<>'DISPATCHED' THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 IF p_outcome='SUCCESS' THEN
  new_exec:='APPLIED'; new_res:='CONSUMED';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='PROVEN_FINISHED',
   attribution='PROVEN', reservation_state=new_res, updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 ELSIF p_outcome='PRE_WRITE_REFUSAL' THEN
  IF p_no_effect_proof IS NULL THEN RAISE EXCEPTION 'WRITE_REFUSED'; END IF;
  IF rec.dispatch_state<>'DISPATCHED' THEN
   UPDATE change_ledger.dispatch_permits SET state='CANCELLED_UNDISPATCHED'
    WHERE change_id=p_change_id AND generation=p_generation AND state IN ('NOT_PERMITTED','PERMITTED');
  END IF;
  new_exec:='FAILED_APPLY';
  IF rec.kind='UNPOST' AND coalesce((SELECT e.content->>'refusal_code'
     FROM change_ledger.evidence_records e
     JOIN change_ledger.verifier_keys k ON k.tenant_id=e.tenant_id AND k.company_id=e.company_id
      AND k.key_id=e.signer_key_id AND k.key_algorithm='ED25519'
     WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
      AND e.evidence_id::text=p_evidence->>'evidence_id'),'')='ROLLBACK_REFUSED' THEN
   new_exec:='ROLLBACK_REFUSED';
  END IF;
  PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
  UPDATE change_ledger.records SET execution_state=new_exec,
   dispatch_state=CASE WHEN dispatch_state='DISPATCHED' THEN dispatch_state ELSE 'CANCELLED_UNDISPATCHED' END,
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSE
  new_exec:='APPLY_UNKNOWN';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='POSSIBLY_EXECUTING',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  IF NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.change_id=p_change_id AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL) THEN
   INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
   VALUES(t,c,rec.base_fingerprint,'CALL_OWNERSHIP',p_change_id);
  END IF;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'COMPLETE_'||p_outcome,
  coalesce(p_evidence,'{}'::jsonb)||CASE WHEN new_exec='ROLLBACK_REFUSED'
   THEN jsonb_build_object('execution','ROLLBACK_REFUSED') ELSE '{}'::jsonb END);
 RETURN new_exec;
END $fn$;

-- operator_resolve consumes both a cosign completion proof and a direct observation lookup; gate both.
CREATE OR REPLACE FUNCTION change_ledger.operator_resolve(
 t text, c text, p_change_id uuid, p_cosign_id uuid, p_present boolean, p_attributed boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_operator text; cs change_ledger.witness_cosigns%ROWTYPE;
 approver_subject text; new_exec text; obs change_ledger.evidence_records;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_present IS NULL OR p_attributed IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 v_operator := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'TRIAGE_REQUIRED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_change_id AND w.consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 IF coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 PERFORM change_ledger.assert_ed25519_cosign_evidence(t,c,p_change_id,cs.completion_proof);
 SELECT a.approver INTO approver_subject FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 IF change_ledger.same_person(t,c,v_operator,cs.signer)
  OR change_ledger.same_person(t,c,v_operator,rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,rec.requester)
  OR (change_ledger.same_person(t,c,v_operator,approver_subject)
      AND change_ledger.same_person(t,c,cs.signer,approver_subject))
 THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,v_operator,'operator');
 PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
 IF change_ledger.registry_enforced(t,c) AND (change_ledger.person_of(t,c,v_operator) IS NULL
  OR change_ledger.person_of(t,c,cs.signer) IS NULL OR change_ledger.person_of(t,c,rec.requester) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_present AND p_attributed AND coalesce((cs.completion_proof->>'attribution_proof')::boolean,false) IS NOT TRUE THEN
  RAISE EXCEPTION 'ATTRIBUTION_UNPROVEN';
 END IF;
 -- The verdict is the signed observation of this generation, never the caller's flag.
 SELECT e.* INTO obs FROM change_ledger.evidence_records e
  JOIN change_ledger.verifier_keys k ON k.tenant_id=e.tenant_id AND k.company_id=e.company_id
   AND k.key_id=e.signer_key_id AND k.key_algorithm='ED25519'
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.kind='OBSERVATION' AND e.generation=rec.claim_generation
   AND jsonb_typeof(e.content->'effect_present')='boolean'
   AND (e.content->>'effect_present')::boolean=p_present
  ORDER BY e.recorded_at DESC LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 UPDATE change_ledger.witness_cosigns w SET consumed_at=clock_timestamp() WHERE w.cosign_id=p_cosign_id;
 DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 IF NOT p_present THEN
  new_exec:='FAILED_APPLY';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state='RELEASED',
   call_ownership='PROVEN_FINISHED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
  PERFORM change_ledger.release_or_handback_target(t,c,rec);
 ELSE
  new_exec:='APPLIED';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state='CONSUMED',
   call_ownership='PROVEN_FINISHED',
   attribution=CASE WHEN p_attributed THEN 'PROVEN' ELSE 'UNPROVEN_OPERATOR_ATTESTED' END,
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
 END IF;
 UPDATE change_ledger.holds SET released_at=clock_timestamp(),
  release_evidence=cs.completion_proof
  WHERE change_id=p_change_id AND cause='CALL_OWNERSHIP' AND released_at IS NULL;
 PERFORM change_ledger.append_event(t,c,p_change_id,'OPERATOR_RESOLVE',
  jsonb_build_object('present',p_present,'attributed',p_attributed,'cosign_id',p_cosign_id,
   'observation_evidence',obs.evidence_id));
 RETURN new_exec;
END $fn$;

-- Keep the internal two-person helper safe if called by any existing definer path.
CREATE OR REPLACE FUNCTION change_ledger.consume_two_person_cosign(
 p_rec change_ledger.records, p_operator text, p_cosign_id uuid
) RETURNS change_ledger.witness_cosigns LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cs change_ledger.witness_cosigns%ROWTYPE; approver_subject text;
 t text := p_rec.tenant_id; c text := p_rec.company_id;
BEGIN
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_rec.change_id AND w.consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND OR coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 PERFORM change_ledger.assert_ed25519_cosign_evidence(t,c,p_rec.change_id,cs.completion_proof);
 SELECT a.approver INTO approver_subject FROM change_ledger.approvals a
  WHERE a.change_id=p_rec.change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 IF change_ledger.same_person(t,c,p_operator,cs.signer)
  OR change_ledger.same_person(t,c,p_operator,p_rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,p_rec.requester)
  OR (change_ledger.same_person(t,c,p_operator,approver_subject)
      AND change_ledger.same_person(t,c,cs.signer,approver_subject)) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,p_operator,'operator');
 PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
 IF change_ledger.registry_enforced(t,c) AND (change_ledger.person_of(t,c,p_operator) IS NULL
  OR change_ledger.person_of(t,c,cs.signer) IS NULL OR change_ledger.person_of(t,c,p_rec.requester) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 UPDATE change_ledger.witness_cosigns w SET consumed_at=clock_timestamp() WHERE w.cosign_id=p_cosign_id;
 RETURN cs;
END $fn$;

-- The dispatch permit has no tenant columns; bind both lookup and mutation to its scoped parent record.
CREATE OR REPLACE FUNCTION change_ledger.attach_permit_signature(
 t text, c text, p_change_id uuid, p_generation bigint, p_key_id text, p_signature text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n integer; who text; vk change_ledger.verifier_keys%ROWTYPE; dg text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT pg_has_role(who::name,'checkpoint_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_change_id IS NULL OR p_generation IS NULL OR p_key_id IS NULL OR p_signature IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
  OR NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 SELECT dp.permit_digest INTO dg FROM change_ledger.dispatch_permits dp
  JOIN change_ledger.records r ON r.change_id=dp.change_id AND r.tenant_id=t AND r.company_id=c
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation AND dp.state='PERMITTED';
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,'change-ledger-permit|v1|'||dg,p_signature) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 UPDATE change_ledger.dispatch_permits dp SET signer_key_id=p_key_id, signature=p_signature
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation AND dp.state='PERMITTED'
   AND EXISTS(SELECT 1 FROM change_ledger.records r
    WHERE r.change_id=dp.change_id AND r.tenant_id=t AND r.company_id=c);
 GET DIAGNOSTICS n = ROW_COUNT;
 IF n=0 THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
END $fn$;

-- Match the established 019 policy: definer/search_path/owner on every function, with no PUBLIC execution.
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

$body$;
END IF;
END $mig$;
COMMIT;
