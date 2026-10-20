-- S13 synthetic prototype: keep the kill switch active until bounded recovery is complete.
-- Additive, transactional migration; no production or external-writer outcome is asserted.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('020', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019']) THEN
EXECUTE $body$

CREATE OR REPLACE FUNCTION change_ledger.revoke_stale(t text, c text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n integer := 0; cid uuid; ids uuid[]; result_state text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM pg_catalog.pg_advisory_xact_lock(5, pg_catalog.hashtext('sweep:'||t||':'||c));
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO ids FROM (
  SELECT x.change_id FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.authorization_state IN ('APPROVED','CLAIMED')
    AND x.execution_state='NOT_STARTED' AND x.dispatch_state NOT IN ('PERMITTED','DISPATCHED')
    AND NOT change_ledger.epoch_deps_current(t,c,x.epoch_dependencies)
   ORDER BY x.created_at LIMIT 200) s;
 -- the whole bounded batch is locked (tokens, then records) before the first append
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id = ANY(ids) ORDER BY ct.token_id FOR UPDATE;
 PERFORM 1 FROM change_ledger.records r WHERE r.change_id = ANY(ids) ORDER BY r.change_id FOR UPDATE;
 FOREACH cid IN ARRAY ids LOOP
  BEGIN
   result_state := change_ledger.revoke_core(t,c,cid,'EPOCH_DEPENDENCY');
   IF result_state IN ('REVOKED','VOIDED') THEN
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='REVOKE_STALE';
    n := n+1;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'REVOKE_STALE',SQLSTATE,SQLERRM);
  END;
 END LOOP;
 RETURN n;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.recover_sweep(t text, c text, p_params jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
 p jsonb; v_mode text; v_start timestamptz := clock_timestamp(); n integer := 0; bsz integer; nexp integer := 0;
 run_id uuid; selected_gap_bound integer := 0; has_more_eligible boolean := false; has_unresolved boolean := false;
 failed_count integer := 0; failure_count bigint := 0; t12_clear boolean; verify_clear boolean;
 cid uuid; tokid uuid; gen bigint; x record; rec change_ledger.records%ROWTYPE; ctr change_ledger.sweep_counters%ROWTYPE;
 dl timestamptz; disp timestamptz; started timestamptz; cnt integer; due_in double precision; vres jsonb;
 c_t5x uuid[]; c_t6c uuid[]; c_t6r uuid[]; c_t9 uuid[]; c_t3 uuid[]; c_void uuid[] := '{}'; c_t12 uuid[];
 c_gap uuid[]; c_ver uuid[]; ids uuid[];
 a_t5x uuid[] := '{}'; a_t6c uuid[] := '{}'; a_t6r uuid[] := '{}'; a_t9 uuid[] := '{}'; a_t3 uuid[] := '{}';
 a_void uuid[] := '{}'; a_t12a uuid[] := '{}'; a_t12 uuid[] := '{}'; a_gap uuid[] := '{}';
 a_vdue uuid[] := '{}'; a_vexh uuid[] := '{}'; a_fail jsonb := '[]'::jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 -- Scope-specific lock serializes recovery sweeps; kill_switch holds its lock before calling this function.
 PERFORM pg_catalog.pg_advisory_xact_lock(5, pg_catalog.hashtext('sweep:'||t||':'||c));
 p := change_ledger.sweep_params(p_params, change_ledger.sweep_tunables() || change_ledger.sweep_constants());
 IF p_params IS NOT NULL AND p_params ?| ARRAY['claim_ttl_seconds','permit_ttl_seconds','t12_window_seconds',
   't12_max_attempts','anchor_gap_window_seconds','verify_max_attempts'] THEN
  RAISE EXCEPTION 'NOT_ENTITLED';        -- contract constants: ledger constants or the operator's policy row only
 END IF;
 p := p || change_ledger.sweep_effective(t,c);
 bsz := (p->>'batch_size')::integer;
 SELECT coalesce(max(ks.mode),'OFF') INTO v_mode FROM change_ledger.kill_switch_state ks
  WHERE ks.tenant_id=t AND ks.company_id=c;

 -- ---------------- phase 1: choose the batch, lock it (tokens first, then records), no append yet
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t5x FROM (
  SELECT r.change_id FROM change_ledger.claim_tokens ct JOIN change_ledger.records r ON r.change_id=ct.change_id
   WHERE r.tenant_id=t AND r.company_id=c AND ct.state='ISSUED'
    AND (v_mode<>'OFF' OR ct.issued_at<=clock_timestamp()-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision))   -- B6c
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='T5x'),0),
    ct.issued_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t6c FROM (
  SELECT dp.change_id FROM change_ledger.dispatch_permits dp JOIN change_ledger.records r ON r.change_id=dp.change_id
   WHERE r.tenant_id=t AND r.company_id=c AND dp.state='PERMITTED' AND (dp.expires_at<=clock_timestamp() OR v_mode<>'OFF')   -- B6c
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=dp.change_id AND f.stage='T6c'),0),
    dp.expires_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t6r FROM (
  SELECT r.change_id FROM change_ledger.records r
   JOIN change_ledger.dispatch_permits dp ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='NOT_PERMITTED'
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='T6r'),0),
    r.updated_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t9 FROM (
  SELECT r.change_id FROM change_ledger.records r
   JOIN change_ledger.dispatch_permits dp ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='DISPATCHED'
    AND coalesce((SELECT cd.hard_deadline_at FROM change_ledger.call_deadlines cd
      WHERE cd.change_id=r.change_id AND cd.generation=r.claim_generation),
     coalesce((SELECT max(e.recorded_at) FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
       AND e.change_id=r.change_id AND e.event_type='DISPATCHED'),r.updated_at)
     +make_interval(secs=>CASE WHEN r.kind='POST' THEN (p->>'post_deadline_seconds')::double precision
                               ELSE (p->>'deadline_seconds')::double precision END))<=clock_timestamp()
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='T9'),0),
    r.updated_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t3 FROM (
  SELECT r.change_id FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.expires_at<=clock_timestamp()
    AND r.execution_state='NOT_STARTED' AND r.lifecycle IN ('PROPOSED','VALIDATED')
    AND r.authorization_state IN ('NONE','APPROVED','EXPIRED')
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='T3'),0),
    r.created_at LIMIT bsz) s;
 IF v_mode='REVOKE' THEN
  SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_void FROM (
   SELECT r.change_id FROM change_ledger.records r
    WHERE r.tenant_id=t AND r.company_id=c AND r.authorization_state='APPROVED' AND r.execution_state='NOT_STARTED'
    ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='VOID'),0),
     r.created_at LIMIT bsz) s;
 END IF;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t12 FROM (
  SELECT r.change_id FROM change_ledger.records r
   LEFT JOIN change_ledger.sweep_counters k ON k.subject_id=r.change_id AND k.kind='RESOLVE'
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLY_UNKNOWN'
    AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND (k.next_attempt_at<=clock_timestamp()
      OR k.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp())))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='T12'),0),
    r.updated_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_gap FROM (
  SELECT r.change_id FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLY_UNKNOWN'
    AND EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=r.base_fingerprint AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
     AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=clock_timestamp())
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='GAP'),0),
    r.updated_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_ver FROM (
  SELECT r.change_id FROM change_ledger.records r
   LEFT JOIN change_ledger.sweep_counters k ON k.subject_id=r.change_id AND k.kind='VERIFY'
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED'
    AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND k.next_attempt_at<=clock_timestamp()))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='VERIFY'),0),
    r.updated_at LIMIT bsz) s;
 -- B6d: expired approval nonces are persisted as EXPIRED (before any append: a nonce row is never waited for
 -- while the chain lock is held); rows locked by an in-flight approve are skipped
 UPDATE change_ledger.approval_nonces an SET state='EXPIRED' WHERE an.nonce IN (
  SELECT n.nonce FROM change_ledger.approval_nonces n JOIN change_ledger.records r ON r.change_id=n.change_id
   WHERE r.tenant_id=t AND r.company_id=c AND n.state='ISSUED' AND n.expires_at<=clock_timestamp()
   ORDER BY n.nonce LIMIT bsz FOR UPDATE OF n SKIP LOCKED);
 GET DIAGNOSTICS nexp = ROW_COUNT;
 ids := c_t5x||c_t6c||c_t6r||c_t9||c_t3||c_void||c_t12||c_gap||c_ver;
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id = ANY(ids) ORDER BY ct.token_id FOR UPDATE;
 PERFORM 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c AND r.change_id = ANY(ids)
  ORDER BY r.change_id FOR UPDATE;

 -- ---------------- phase 2: one subtransaction per item
 -- T5x: claim TTL elapsed (any mode: REVOKE releases every live claim and voids its approval).
 FOREACH cid IN ARRAY c_t5x LOOP
  BEGIN
   SELECT ct.token_id INTO tokid FROM change_ledger.claim_tokens ct WHERE ct.change_id=cid AND ct.state='ISSUED'
    AND (v_mode<>'OFF' OR ct.issued_at<=clock_timestamp()-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision));
   IF tokid IS NOT NULL THEN
    IF change_ledger.release_claim_internal(t,c,tokid,v_mode='REVOKE') THEN
     DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='T5x';
     n := n+1; a_t5x := a_t5x||cid;
    END IF;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'T5x',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','T5x','subject',cid));
  END;
 END LOOP;

 -- T6c: permit TTL elapsed, undispatched (the cancel CAS decides).
 FOREACH cid IN ARRAY c_t6c LOOP
  BEGIN
   SELECT dp.generation INTO gen FROM change_ledger.dispatch_permits dp WHERE dp.change_id=cid
    AND dp.state='PERMITTED' AND (dp.expires_at<=clock_timestamp() OR v_mode<>'OFF');
   IF gen IS NOT NULL THEN
    IF change_ledger.cancel_permit(t,c,cid,gen) THEN
     DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='T6c';
     n := n+1; a_t6c := a_t6c||cid;
    END IF;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'T6c',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','T6c','subject',cid));
  END;
 END LOOP;

 -- T6r: APPLYING and the permit of the current generation was never issued, after the permit TTL.
 FOREACH cid IN ARRAY c_t6r LOOP
  BEGIN
   IF change_ledger.permit_not_issued_internal(t,c,cid,
       CASE WHEN v_mode<>'OFF' THEN -1 ELSE (p->>'permit_ttl_seconds')::double precision END) THEN   -- B6c: no wait under a stop
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='T6r';
    n := n+1; a_t6r := a_t6r||cid;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'T6r',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','T6r','subject',cid));
  END;
 END LOOP;

 -- T9: DISPATCHED call past its hard deadline -> APPLY_UNKNOWN + CALL_OWNERSHIP hold (conservative).
 FOREACH cid IN ARRAY c_t9 LOOP
  BEGIN
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND rec.execution_state='APPLYING' AND EXISTS(SELECT 1 FROM change_ledger.dispatch_permits dp
     WHERE dp.change_id=rec.change_id AND dp.generation=rec.claim_generation AND dp.state='DISPATCHED') THEN
    SELECT cd.hard_deadline_at INTO dl FROM change_ledger.call_deadlines cd
     WHERE cd.change_id=rec.change_id AND cd.generation=rec.claim_generation;
    IF dl IS NULL THEN
     SELECT max(e.recorded_at) INTO disp FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
      AND e.change_id=rec.change_id AND e.event_type='DISPATCHED';
     dl := coalesce(disp,rec.updated_at)+make_interval(secs=>
      CASE WHEN rec.kind='POST' THEN (p->>'post_deadline_seconds')::double precision
           ELSE (p->>'deadline_seconds')::double precision END);
    END IF;
    IF dl<=clock_timestamp() THEN
     UPDATE change_ledger.records SET execution_state='APPLY_UNKNOWN', call_ownership='POSSIBLY_EXECUTING',
      updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
     IF NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
       AND h.change_id=rec.change_id AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL) THEN
      INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
      VALUES(t,c,rec.base_fingerprint,'CALL_OWNERSHIP',rec.change_id);
     END IF;
     PERFORM change_ledger.append_event(t,c,rec.change_id,'HARD_DEADLINE_UNKNOWN',
      jsonb_build_object('generation',rec.claim_generation,'hard_deadline_at',dl));
     DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='T9';
     n := n+1; a_t9 := a_t9||rec.change_id;
    END IF;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'T9',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','T9','subject',cid));
  END;
 END LOOP;

 -- T3: expiry of PROPOSED / VALIDATED / APPROVED changes (terminal, no effect possible, no reservation).
 FOREACH cid IN ARRAY c_t3 LOOP
  BEGIN
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND rec.expires_at<=clock_timestamp() AND rec.execution_state='NOT_STARTED'
    AND rec.lifecycle IN ('PROPOSED','VALIDATED') AND rec.authorization_state IN ('NONE','APPROVED','EXPIRED') THEN
    UPDATE change_ledger.records SET lifecycle='EXPIRED_QUEUED', authorization_state='EXPIRED',
     updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
    PERFORM change_ledger.append_event(t,c,rec.change_id,'EXPIRED',
     jsonb_build_object('lifecycle_from',rec.lifecycle,'authorization_from',rec.authorization_state));
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='T3';
    n := n+1; a_t3 := a_t3||rec.change_id;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'T3',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','T3','subject',cid));
  END;
 END LOOP;

 -- REVOKE: unclaimed approvals are voided (claimed ones were released and voided above).
 FOREACH cid IN ARRAY c_void LOOP
  BEGIN
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND rec.authorization_state='APPROVED' AND rec.execution_state='NOT_STARTED' THEN
    UPDATE change_ledger.records SET authorization_state='VOIDED', updated_at=clock_timestamp()
     WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
    PERFORM change_ledger.append_event(t,c,rec.change_id,'APPROVAL_VOIDED',jsonb_build_object('cause','REVOKE'));
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='VOID';
    n := n+1; a_void := a_void||rec.change_id;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'VOID',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','VOID','subject',cid));
  END;
 END LOOP;

 -- T12: clear failures only after durable attempt, terminal triage, or confirmed non-APPLY_UNKNOWN state.
 FOREACH cid IN ARRAY c_t12 LOOP
  BEGIN
   t12_clear := false;
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND rec.execution_state<>'APPLY_UNKNOWN' THEN
    t12_clear := true;
   ELSIF FOUND AND rec.execution_state='APPLY_UNKNOWN' THEN
    SELECT max(e.recorded_at) INTO started FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
     AND e.change_id=rec.change_id AND e.event_type IN ('COMPLETE_UNKNOWN','HARD_DEADLINE_UNKNOWN');
    started := coalesce(started,rec.updated_at);
    due_in := (p->>'t12_interval_seconds')::double precision
              + random()*(p->>'t12_jitter_seconds')::double precision;
    INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,next_attempt_at)
    VALUES(t,c,rec.change_id,'RESOLVE',started,started+make_interval(secs=>due_in))
    ON CONFLICT(subject_id,kind) DO NOTHING;
    SELECT * INTO ctr FROM change_ledger.sweep_counters WHERE subject_id=rec.change_id AND kind='RESOLVE' FOR UPDATE;
    IF ctr.closed_at IS NULL THEN
     IF ctr.next_attempt_at<=clock_timestamp() THEN
      UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp(),
       next_attempt_at=clock_timestamp()+make_interval(secs=>due_in)
       WHERE subject_id=rec.change_id AND kind='RESOLVE' RETURNING * INTO ctr;
      n := n+1;
      IF ctr.attempts>=(p->>'t12_max_attempts')::integer THEN
       IF change_ledger.triage_internal(t,c,rec.change_id,'ATTEMPTS') THEN t12_clear := true; END IF;
       a_t12 := a_t12||rec.change_id;
      ELSIF ctr.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp() THEN
       IF change_ledger.triage_internal(t,c,rec.change_id,'WINDOW') THEN t12_clear := true; END IF;
       a_t12 := a_t12||rec.change_id;
      ELSE
       PERFORM change_ledger.append_event(t,c,rec.change_id,'RESOLVE_ATTEMPT',
        jsonb_build_object('attempt',ctr.attempts,'next_attempt_at',ctr.next_attempt_at));
       t12_clear := true; a_t12a := a_t12a||rec.change_id;
      END IF;
     ELSIF ctr.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp() THEN
      IF change_ledger.triage_internal(t,c,rec.change_id,'WINDOW') THEN
       t12_clear := true; n := n+1; a_t12 := a_t12||rec.change_id;
      END IF;
     END IF;
    END IF;
   END IF;
   IF t12_clear THEN
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='T12';
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'T12',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','T12','subject',cid));
  END;
 END LOOP;

 -- ANCHOR_GAP bound: after the window the hold stays (fail closed) and every unresolved item of the base goes to
 -- TRIAGE_REQUIRED; the bound is announced once per hold.
 FOR x IN SELECT h.hold_id, h.base_fingerprint, h.opened_at FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
   AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=clock_timestamp()
  ORDER BY h.opened_at LIMIT bsz LOOP
  BEGIN
   selected_gap_bound := selected_gap_bound+1;
   INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,closed_at,close_reason)
   VALUES(t,c,x.hold_id,'ANCHOR_GAP',x.opened_at,clock_timestamp(),'BOUND_EXCEEDED')
   ON CONFLICT(subject_id,kind) DO NOTHING;
   GET DIAGNOSTICS cnt = ROW_COUNT;
   IF cnt=1 THEN n := n+1; END IF;
   IF EXISTS(SELECT 1 FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
     AND sc.subject_id=x.hold_id AND sc.kind='ANCHOR_GAP' AND sc.closed_at IS NOT NULL AND sc.close_reason='BOUND_EXCEEDED') THEN
    IF NOT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
      AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=x.hold_id::text) THEN
     PERFORM change_ledger.append_event(t,c,NULL,'ANCHOR_GAP_BOUND_EXCEEDED',
      jsonb_build_object('hold_id',x.hold_id,'base_fingerprint',x.base_fingerprint,'alert',true));
    END IF;
    IF EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
      AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=x.hold_id::text) THEN
     DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=x.hold_id AND stage='GAP_BOUND';
    END IF;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,x.hold_id,'GAP_BOUND',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','GAP_BOUND','subject',x.hold_id));
  END;
 END LOOP;
 FOREACH cid IN ARRAY c_gap LOOP
  BEGIN
   IF change_ledger.triage_internal(t,c,cid,'ANCHOR_GAP_WINDOW') THEN
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='GAP';
    n := n+1; a_gap := a_gap||cid;
   ELSIF EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
     AND r.change_id=cid AND r.execution_state<>'APPLY_UNKNOWN') THEN
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='GAP';
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'GAP',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','GAP','subject',cid));
  END;
 END LOOP;

 -- T13/T14 stuck verification: clear failure only after a durable attempt or confirmed terminal transition.
 FOREACH cid IN ARRAY c_ver LOOP
  BEGIN
   verify_clear := false;
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND (rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED') THEN
    verify_clear := true;
   ELSIF FOUND AND rec.execution_state='APPLIED' AND rec.verification_state='NOT_VERIFIED' THEN
    SELECT max(e.recorded_at) INTO started FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
     AND e.change_id=rec.change_id AND e.event_type IN ('COMPLETE_SUCCESS','RESOLVE_UNKNOWN','OPERATOR_RESOLVE');
    started := coalesce(started,rec.updated_at);
    INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,next_attempt_at)
    VALUES(t,c,rec.change_id,'VERIFY',started,
     started+make_interval(secs=>(p->>'verify_interval_seconds')::double precision))
    ON CONFLICT(subject_id,kind) DO NOTHING;
    SELECT * INTO ctr FROM change_ledger.sweep_counters WHERE subject_id=rec.change_id AND kind='VERIFY' FOR UPDATE;
    IF ctr.closed_at IS NULL AND ctr.next_attempt_at<=clock_timestamp() THEN
     vres := change_ledger.verify_attempt_internal(t,c,rec.change_id,'SWEEP_STUCK',
      (p->>'verify_max_attempts')::integer,(p->>'verify_interval_seconds')::double precision);
     n := n+1; verify_clear := true;
     IF (vres->>'exhausted')::boolean THEN a_vexh := a_vexh||rec.change_id; ELSE a_vdue := a_vdue||rec.change_id; END IF;
    END IF;
   END IF;
   IF verify_clear THEN
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c AND subject_id=cid AND stage='VERIFY';
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'VERIFY',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','VERIFY','subject',cid));
  END;
 END LOOP;

 SELECT coalesce(cardinality(c_t5x),0)>=bsz OR coalesce(cardinality(c_t6c),0)>=bsz
   OR coalesce(cardinality(c_t6r),0)>=bsz OR coalesce(cardinality(c_t9),0)>=bsz
   OR coalesce(cardinality(c_t3),0)>=bsz OR coalesce(cardinality(c_void),0)>=bsz
   OR coalesce(cardinality(c_t12),0)>=bsz OR coalesce(cardinality(c_gap),0)>=bsz
   OR coalesce(cardinality(c_ver),0)>=bsz OR selected_gap_bound>=bsz
   OR EXISTS(
    SELECT 1 FROM change_ledger.claim_tokens ct JOIN change_ledger.records r ON r.change_id=ct.change_id
     WHERE r.tenant_id=t AND r.company_id=c AND ct.state='ISSUED'
      AND (v_mode<>'OFF' OR ct.issued_at<=clock_timestamp()-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision))
    UNION ALL SELECT 1 FROM change_ledger.dispatch_permits dp JOIN change_ledger.records r ON r.change_id=dp.change_id
     WHERE r.tenant_id=t AND r.company_id=c AND dp.state='PERMITTED' AND (dp.expires_at<=clock_timestamp() OR v_mode<>'OFF')
    UNION ALL SELECT 1 FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
     ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
     WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='NOT_PERMITTED'
    UNION ALL SELECT 1 FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
     ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
     WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='DISPATCHED'
      AND coalesce((SELECT cd.hard_deadline_at FROM change_ledger.call_deadlines cd WHERE cd.change_id=r.change_id
       AND cd.generation=r.claim_generation), coalesce((SELECT max(e.recorded_at) FROM change_ledger.events e
       WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=r.change_id AND e.event_type='DISPATCHED'),r.updated_at)
       +make_interval(secs=>CASE WHEN r.kind='POST' THEN (p->>'post_deadline_seconds')::double precision
                                  ELSE (p->>'deadline_seconds')::double precision END))<=clock_timestamp()
    UNION ALL SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c AND r.expires_at<=clock_timestamp()
     AND r.execution_state='NOT_STARTED' AND r.lifecycle IN ('PROPOSED','VALIDATED')
     AND r.authorization_state IN ('NONE','APPROVED','EXPIRED')
    UNION ALL SELECT 1 FROM change_ledger.records r WHERE v_mode='REVOKE' AND r.tenant_id=t AND r.company_id=c
     AND r.authorization_state='APPROVED' AND r.execution_state='NOT_STARTED'
    UNION ALL SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.sweep_counters k
     ON k.subject_id=r.change_id AND k.kind='RESOLVE' WHERE r.tenant_id=t AND r.company_id=c
     AND r.execution_state='APPLY_UNKNOWN' AND (k.subject_id IS NULL OR (k.closed_at IS NULL
      AND (k.next_attempt_at<=clock_timestamp() OR k.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp())))
    UNION ALL SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
     AND r.execution_state='APPLY_UNKNOWN' AND EXISTS(SELECT 1 FROM change_ledger.holds h
      WHERE h.tenant_id=t AND h.company_id=c AND h.base_fingerprint=r.base_fingerprint AND h.cause='ANCHOR_GAP'
       AND h.released_at IS NULL AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=clock_timestamp())
    UNION ALL SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c AND h.cause='ANCHOR_GAP'
     AND h.released_at IS NULL AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=clock_timestamp()
    UNION ALL SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.sweep_counters k
     ON k.subject_id=r.change_id AND k.kind='VERIFY' WHERE r.tenant_id=t AND r.company_id=c
     AND r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED'
     AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND k.next_attempt_at<=clock_timestamp()))
   ) INTO has_more_eligible;
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN') OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c AND h.released_at IS NULL
    AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN')) INTO has_unresolved;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c;
 failed_count := jsonb_array_length(a_fail);
 INSERT INTO change_ledger.sweep_runs AS sr(tenant_id,company_id,started_at,finished_at,changed)
 VALUES(t,c,v_start,clock_timestamp(),n) RETURNING sr.run_id INTO run_id;
 RETURN jsonb_build_object('changed',n,'T5x',to_jsonb(a_t5x),'T6c',to_jsonb(a_t6c),'T6r',to_jsonb(a_t6r),
  'T9',to_jsonb(a_t9),'T3',to_jsonb(a_t3),'VOIDED',to_jsonb(a_void),'T12_ATTEMPT',to_jsonb(a_t12a),
  'T12',to_jsonb(a_t12),'ANCHOR_GAP_TRIAGE',to_jsonb(a_gap),'VERIFY_DUE',to_jsonb(a_vdue),
  'VERIFY_EXHAUSTED',to_jsonb(a_vexh),'FAILED',a_fail,'NONCES_EXPIRED',nexp,'run_id',run_id,
  'selected_counts',jsonb_build_object('T5x',cardinality(c_t5x),'T6c',cardinality(c_t6c),'T6r',cardinality(c_t6r),
   'T9',cardinality(c_t9),'T3',cardinality(c_t3),'VOID',cardinality(c_void),'T12',cardinality(c_t12),
   'GAP',cardinality(c_gap),'GAP_BOUND',selected_gap_bound,'VERIFY',cardinality(c_ver)),
  'has_more_eligible',has_more_eligible,'has_unresolved',has_unresolved,'failed_count',failed_count,'sweep_failure_count',failure_count);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.kill_switch(
 t text, c text, p_mode text
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; cur text; report jsonb; effective text; blocked boolean; failed_count integer; failure_count bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_mode NOT IN ('OFF','STOP_ADMIT','STOP_EFFECTS','REVOKE') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 who := change_ledger.caller_role();
 PERFORM change_ledger.take_lock('killswitch', t||':'||c);
 SELECT ks.mode INTO cur FROM change_ledger.kill_switch_state ks WHERE ks.tenant_id=t AND ks.company_id=c;
 IF p_mode='OFF' AND coalesce(cur,'OFF')<>'OFF' THEN
  report := change_ledger.recover_sweep(t,c,'{}'::jsonb);
  failed_count := coalesce((report->>'failed_count')::integer,jsonb_array_length(coalesce(report->'FAILED','[]'::jsonb)));
  failure_count := coalesce((report->>'sweep_failure_count')::bigint,0);
  blocked := failed_count>0 OR failure_count>0 OR coalesce((report->>'has_more_eligible')::boolean,true)
    OR coalesce((report->>'has_unresolved')::boolean,true);
  IF blocked THEN
   effective := cur;
   PERFORM change_ledger.append_event(t,c,NULL,'KILL_SWITCH',jsonb_build_object('mode',effective,
    'requested_mode',p_mode,'effective_mode',effective,'outcome','BLOCKED','by',who,'run_id',report->>'run_id',
    'failed_count',failed_count,'sweep_failure_count',failure_count,
    'has_more_eligible',coalesce((report->>'has_more_eligible')::boolean,true),
    'has_unresolved',coalesce((report->>'has_unresolved')::boolean,true),
    'selected_counts',coalesce(report->'selected_counts','{}'::jsonb)));
   RETURN effective;
  END IF;
 END IF;
 INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode,updated_by)
 VALUES(t,c,p_mode,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET mode=p_mode, updated_by=who,
  updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'KILL_SWITCH',jsonb_build_object('mode',p_mode,'by',who));
 RETURN p_mode;
END $fn$;

DO $fn$
DECLARE f record;
BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='change_ledger' AND p.proname IN ('revoke_stale','recover_sweep','kill_switch') LOOP
  EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp',f.sig);
  EXECUTE format('ALTER FUNCTION %s OWNER TO ledger_owner',f.sig);
 END LOOP;
END $fn$;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA change_ledger FROM PUBLIC;

$body$;
END IF;
END $mig$;
COMMIT;
