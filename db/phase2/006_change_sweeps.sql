-- R2/G1 S13: recovery sweeps, anchor / restart holds, T17 operator closure, REVOKE voiding and writer
-- lease fencing for the change ledger of docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md
-- (revision 6, frozen). Requires 001-004 only (never 005 objects). Apply ONLY to a verified disposable
-- PostgreSQL database; the checksum precondition is enforced by living.record_migration (as in 004).
--
-- Closes these gaps of 004 (section numbers refer to the contract):
--  (1) recover_sweep: T3 expiry, T6r (APPLYING without a permit after the permit TTL), hard-deadline T9,
--      T12 durable attempt counter (5 attempts, interval with jitter, 15 min window -> TRIAGE_REQUIRED),
--      verification retry bookkeeping (bound 3: T13/T14 stuck verification, T17 retry), transient LOCK_BUSY
--      T8 attempts (max 5, interval with jitter, 15 min window, then the definite PRE_WRITE path).
--  (2) ANCHOR_GAP bounded at 15 minutes (unresolved APPLY_UNKNOWN items go to TRIAGE_REQUIRED), release only
--      with a REAL read-back checkpoint written after the hold opened plus a verified hash chain;
--      declare_anchor_gap, declare_unclean_restart / RLC_UNCLEAN hold and its release conditions.
--  (3) T17 operator closure of FAILED_VERIFY (two-person + completion-proof rules of T16).
--  (4) REVOKE-mode voiding of unclaimed approvals (inside recover_sweep) and re-enable running the sweep first.
--  (5) writer lease renewal while a call is in flight and the fence check before each call.
--
-- BEHAVIOR CHANGES of 004 functions (all CREATE OR REPLACE with the same signature and grants):
--   recover_sweep(text,text)  now delegates to the new recover_sweep(text,text,jsonb) (all transitions above);
--   release_hold              ANCHOR_GAP / RLC_UNCLEAN need machine-checked evidence; FAILED_VERIFY_HALT can no
--                             longer be released by release_hold (T17 only);
--   kill_switch               a re-enable (non-OFF -> OFF) runs recover_sweep first;
--   record_call is NOT replaced (005 replaces it): the fence (lease held and unexpired, no blocking hold) and
--                             the stored hard deadline of the call live in a BEFORE UPDATE trigger on
--                             dispatch_permits for the PERMITTED -> DISPATCHED compare-and-set.
-- Parameters of the sweep are jsonb keys (unknown keys / negative numbers are refused with SCHEMA_INVALID):
--   claim_ttl_seconds 120, permit_ttl_seconds 60, deadline_seconds 120, post_deadline_seconds 300,
--   t12_interval_seconds 180, t12_jitter_seconds 30, t12_window_seconds 900, t12_max_attempts 5,
--   verify_interval_seconds 180, verify_max_attempts 3, anchor_gap_window_seconds 900.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('006', ARRAY['001','002','003','004']) THEN
EXECUTE $body$

-- ================================================================== storage
-- Durable attempt counters. subject_id is the change_id, or the hold_id for the ANCHOR_GAP bound marker.
CREATE TABLE IF NOT EXISTS change_ledger.sweep_counters(
 tenant_id text NOT NULL, company_id text NOT NULL,
 subject_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('RESOLVE','VERIFY','VERIFY_RETRY','LOCK_BUSY','ANCHOR_GAP')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 last_attempt_at timestamptz,
 next_attempt_at timestamptz,
 closed_at timestamptz,
 close_reason text,
 PRIMARY KEY(subject_id,kind)
);
-- One row per recover_sweep run (evidence for the RLC_UNCLEAN resume procedure).
CREATE TABLE IF NOT EXISTS change_ledger.sweep_runs(
 tenant_id text NOT NULL, company_id text NOT NULL,
 run_id uuid NOT NULL DEFAULT gen_random_uuid(),
 started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
 changed integer NOT NULL CHECK(changed>=0),
 PRIMARY KEY(run_id)
);
-- The hard deadline of a dispatched call (section 6 begin_apply ownership row: "hard deadline").
CREATE TABLE IF NOT EXISTS change_ledger.call_deadlines(
 tenant_id text NOT NULL, company_id text NOT NULL,
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 generation bigint NOT NULL, call_id uuid NOT NULL,
 dispatched_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 deadline_seconds integer NOT NULL CHECK(deadline_seconds>0),
 hard_deadline_at timestamptz NOT NULL,
 PRIMARY KEY(change_id,generation)
);
-- T17 operator closure record (one per change, immutable meaning: the FAILED_VERIFY change is closed).
CREATE TABLE IF NOT EXISTS change_ledger.change_closures(
 tenant_id text NOT NULL, company_id text NOT NULL,
 change_id uuid PRIMARY KEY REFERENCES change_ledger.records(change_id),
 closed_by text NOT NULL, witness text NOT NULL, cosign_id uuid NOT NULL,
 effect_present boolean NOT NULL, completion_proof jsonb NOT NULL,
 closed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DROP TRIGGER IF EXISTS change_closures_immutable ON change_ledger.change_closures;
CREATE TRIGGER change_closures_immutable BEFORE UPDATE OR DELETE ON change_ledger.change_closures
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

-- Writer lease renewal (5): NULL expiry = initial lease that has never been renewed (valid).
ALTER TABLE change_ledger.writer_leases ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE change_ledger.writer_leases ADD COLUMN IF NOT EXISTS renewed_at timestamptz;
ALTER TABLE change_ledger.writer_leases ADD COLUMN IF NOT EXISTS renew_count integer NOT NULL DEFAULT 0;

-- ================================================================== internal helpers (never granted)
CREATE OR REPLACE FUNCTION change_ledger.sweep_params(p_params jsonb, p_defaults jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE k text; v jsonb;
BEGIN
 IF p_params IS NULL THEN RETURN p_defaults; END IF;
 IF jsonb_typeof(p_params)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 FOR k, v IN SELECT * FROM jsonb_each(p_params) LOOP
  IF NOT (p_defaults ? k) OR jsonb_typeof(v)<>'number' OR (v#>>'{}')::numeric<0 THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 END LOOP;
 RETURN p_defaults || p_params;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.chain_ok(t text, c text) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT coalesce((change_ledger.verify_chain(t,c)->>'ok')::boolean,false)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.call_deadline_seconds(p_kind text) RETURNS integer
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT CASE WHEN p_kind='POST' THEN 300 ELSE 120 END
$fn$;

-- Shared lease + hold part of the fence (section 6/7): the lease must be held by this change and not
-- lapsed; no blocking hold on the base (a repair UNPOST excepts only its own parent's halt).
CREATE OR REPLACE FUNCTION change_ledger.fence_assert(t text, c text, p_rec change_ledger.records, p_check_hold boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM change_ledger.writer_leases wl
   WHERE wl.tenant_id=t AND wl.company_id=c AND wl.base_fingerprint=p_rec.base_fingerprint
    AND wl.owner_change_id=p_rec.change_id
    AND (wl.lease_expires_at IS NULL OR wl.lease_expires_at>clock_timestamp())) THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 IF p_check_hold AND change_ledger.blocking_hold(t,c,p_rec.base_fingerprint,p_rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
END $fn$;

-- T5x (and REVOKE: T5x + approval voided) without a caller check; used by the sweep, which may be
-- driven by the operator's re-enable. Returns false when the token is not a live claim any more.
CREATE OR REPLACE FUNCTION change_ledger.release_claim_internal(t text, c text, p_token_id uuid, p_void boolean)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE;
BEGIN
 SELECT * INTO tok FROM change_ledger.claim_tokens WHERE token_id=p_token_id FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=tok.change_id FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF tok.state<>'ISSUED' OR rec.authorization_state<>'CLAIMED' OR rec.execution_state<>'NOT_STARTED'
  OR tok.generation<>rec.claim_generation THEN
  RETURN false;
 END IF;
 UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE token_id=p_token_id;
 PERFORM change_ledger.release_zero_effect(t,c,rec.change_id);
 UPDATE change_ledger.records SET
  authorization_state=CASE WHEN p_void THEN 'VOIDED'
                           WHEN rec.expires_at<=clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
  execution_state='NOT_STARTED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'CLAIM_RELEASED',
  jsonb_build_object('cause',CASE WHEN p_void THEN 'REVOKE' ELSE 'SWEEP' END));
 RETURN true;
END $fn$;

-- T6r: APPLYING whose permit was never issued (no PERMITTED event, so no call was ever possible).
-- Proof of no dispatch is the successful CAS NOT_PERMITTED -> CANCELLED_UNDISPATCHED under the row lock.
CREATE OR REPLACE FUNCTION change_ledger.permit_not_issued_internal(t text, c text, p_change_id uuid, p_ttl_seconds double precision)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; started timestamptz;
BEGIN
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR rec.execution_state<>'APPLYING' THEN RETURN false; END IF;
 SELECT max(e.recorded_at) INTO started FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.event_type='APPLYING';
 IF started IS NULL OR started+make_interval(secs=>p_ttl_seconds)>clock_timestamp() THEN RETURN false; END IF;
 IF NOT change_ledger.dispatch_cas(p_change_id,rec.claim_generation,'NOT_PERMITTED','CANCELLED_UNDISPATCHED') THEN
  RETURN false;
 END IF;
 UPDATE change_ledger.claim_tokens SET state='SUPERSEDED'
  WHERE change_id=p_change_id AND generation=rec.claim_generation;
 PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
 UPDATE change_ledger.records SET
  authorization_state=CASE WHEN rec.expires_at<=clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
  execution_state='NOT_STARTED', dispatch_state='CANCELLED_UNDISPATCHED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PERMIT_NOT_ISSUED',
  jsonb_build_object('generation',rec.claim_generation));
 RETURN true;
END $fn$;

-- T12: APPLY_UNKNOWN -> TRIAGE_REQUIRED. Hold, lease, locks and reservation are kept until T16.
CREATE OR REPLACE FUNCTION change_ledger.triage_internal(t text, c text, p_change_id uuid, p_reason text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cnt integer;
BEGIN
 UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND execution_state='APPLY_UNKNOWN';
 GET DIAGNOSTICS cnt = ROW_COUNT;
 IF cnt=0 THEN RETURN false; END IF;
 UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason=p_reason
  WHERE subject_id=p_change_id AND kind='RESOLVE' AND closed_at IS NULL;
 PERFORM change_ledger.append_event(t,c,p_change_id,'TRIAGE_REQUIRED',
  jsonb_build_object('reason',p_reason,'alert',true));
 RETURN true;
END $fn$;

-- Verification attempt bookkeeping (T13/T14, bound p_max). The attempt that reaches the bound without a
-- verdict ends in FAILED_VERIFY with effect_known = UNKNOWN (nothing could be observed) and a
-- FAILED_VERIFY_HALT hold; the effect is recorded (APPLIED), so reservation and target lock are kept.
CREATE OR REPLACE FUNCTION change_ledger.verify_attempt_internal(
 t text, c text, p_change_id uuid, p_reason text, p_max integer, p_interval double precision
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE k change_ledger.sweep_counters%ROWTYPE; exhausted boolean := false;
BEGIN
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'VERIFY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=p_change_id AND kind='VERIFY' FOR UPDATE;
 IF k.closed_at IS NOT NULL THEN RETURN jsonb_build_object('attempts',k.attempts,'exhausted',true); END IF;
 UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp(),
  next_attempt_at=clock_timestamp()+make_interval(secs=>p_interval)
  WHERE subject_id=p_change_id AND kind='VERIFY' RETURNING * INTO k;
 IF k.attempts>=p_max THEN
  exhausted := true;
  UPDATE change_ledger.records SET verification_state='FAILED_VERIFY', effect_known='UNKNOWN',
   updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  IF NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL) THEN
   INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
   SELECT t,c,r.base_fingerprint,'FAILED_VERIFY_HALT',r.change_id FROM change_ledger.records r
    WHERE r.change_id=p_change_id;
  END IF;
  UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason='EXHAUSTED'
   WHERE subject_id=p_change_id AND kind='VERIFY';
  PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_EXHAUSTED',
   jsonb_build_object('reason',p_reason,'attempts',k.attempts,'alert',true));
 ELSE
  PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_ATTEMPT',
   jsonb_build_object('reason',p_reason,'attempt',k.attempts));
 END IF;
 RETURN jsonb_build_object('attempts',k.attempts,'exhausted',exhausted);
END $fn$;

-- Opens one hold of p_cause per base (or the named base) that has none open; idempotent.
CREATE OR REPLACE FUNCTION change_ledger.open_hold_internal(
 t text, c text, p_base text, p_cause text, p_event text, p_detail jsonb
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE b record; opened integer := 0;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('hold:'||t||':'||c||':'||p_cause,0));
 IF p_base IS NOT NULL AND NOT EXISTS(SELECT 1 FROM change_ledger.targets g WHERE g.tenant_id=t
   AND g.company_id=c AND g.base_fingerprint=p_base) THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 FOR b IN SELECT g.base_fingerprint FROM change_ledger.targets g
   WHERE g.tenant_id=t AND g.company_id=c AND (p_base IS NULL OR g.base_fingerprint=p_base)
    AND NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
      AND h.base_fingerprint=g.base_fingerprint AND h.cause=p_cause AND h.released_at IS NULL)
   ORDER BY g.base_fingerprint LOOP
  INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause)
  VALUES(t,c,b.base_fingerprint,p_cause);
  opened := opened+1;
 END LOOP;
 IF opened>0 THEN
  PERFORM change_ledger.append_event(t,c,NULL,p_event,
   coalesce(p_detail,'{}'::jsonb)||jsonb_build_object('cause',p_cause,'bases_held',opened));
 END IF;
 RETURN opened;
END $fn$;

-- Same two-person and completion-proof rules as T16 (S12-M05): an unconsumed witness cosign for this change,
-- carrying an independent completion proof of class a or b; operator, witness and requester must be
-- distinct, and the approver may be only one of the two signers. Marks the cosign consumed.
CREATE OR REPLACE FUNCTION change_ledger.consume_two_person_cosign(
 p_rec change_ledger.records, p_operator text, p_cosign_id uuid
) RETURNS change_ledger.witness_cosigns LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cs change_ledger.witness_cosigns%ROWTYPE; approver_subject text;
BEGIN
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_rec.change_id AND w.consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 IF coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 SELECT a.approver INTO approver_subject FROM change_ledger.approvals a
  WHERE a.change_id=p_rec.change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 IF p_operator IS NOT DISTINCT FROM cs.signer
  OR p_operator IS NOT DISTINCT FROM p_rec.requester
  OR cs.signer IS NOT DISTINCT FROM p_rec.requester
  OR (p_operator IS NOT DISTINCT FROM approver_subject AND cs.signer IS NOT DISTINCT FROM approver_subject) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 UPDATE change_ledger.witness_cosigns w SET consumed_at=clock_timestamp() WHERE w.cosign_id=p_cosign_id;
 RETURN cs;
END $fn$;

-- T8 transient-refusal gate: a change that went back to APPROVED after LOCK_BUSY cannot be claimed again
-- before the counter's next_attempt_at (interval with jitter). Mechanical, so claim() stays untouched.
CREATE OR REPLACE FUNCTION change_ledger.records_lock_busy_gate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NEW.authorization_state='CLAIMED' AND OLD.authorization_state IS DISTINCT FROM 'CLAIMED' THEN
  IF EXISTS(SELECT 1 FROM change_ledger.sweep_counters k WHERE k.subject_id=NEW.change_id
    AND k.kind='LOCK_BUSY' AND k.closed_at IS NULL AND k.next_attempt_at>clock_timestamp()) THEN
   RAISE EXCEPTION 'LOCK_BUSY';
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS records_lock_busy_gate ON change_ledger.records;
CREATE TRIGGER records_lock_busy_gate BEFORE UPDATE OF authorization_state ON change_ledger.records
 FOR EACH ROW EXECUTE FUNCTION change_ledger.records_lock_busy_gate();

-- ================================================================== (1) recover_sweep
-- Order: claims (T5x; REVOKE: + voided), permit TTL (T6c), permit never issued (T6r), hard deadline (T9),
-- expiry (T3), REVOKE voiding of unclaimed approvals, T12 counter, ANCHOR_GAP bound, verification counters.
-- Returns {"changed": n, "T5x": [ids], ...}. Idempotent: a second run without elapsed time changes nothing.
CREATE OR REPLACE FUNCTION change_ledger.recover_sweep(t text, c text, p_params jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
 p jsonb; v_mode text; v_start timestamptz := clock_timestamp(); n integer := 0;
 x record; y record; rec change_ledger.records%ROWTYPE; k change_ledger.sweep_counters%ROWTYPE;
 dl timestamptz; disp timestamptz; started timestamptz; cnt integer; due_in double precision;
 a_t5x uuid[] := '{}'; a_t6c uuid[] := '{}'; a_t6r uuid[] := '{}'; a_t9 uuid[] := '{}'; a_t3 uuid[] := '{}';
 a_void uuid[] := '{}'; a_t12a uuid[] := '{}'; a_t12 uuid[] := '{}'; a_gap uuid[] := '{}';
 a_vdue uuid[] := '{}'; a_vexh uuid[] := '{}'; v jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 p := change_ledger.sweep_params(p_params, '{"claim_ttl_seconds":120,"permit_ttl_seconds":60,
  "deadline_seconds":120,"post_deadline_seconds":300,"t12_interval_seconds":180,"t12_jitter_seconds":30,
  "t12_window_seconds":900,"t12_max_attempts":5,"verify_interval_seconds":180,"verify_max_attempts":3,
  "anchor_gap_window_seconds":900}'::jsonb);
 SELECT coalesce(max(ks.mode),'OFF') INTO v_mode FROM change_ledger.kill_switch_state ks
  WHERE ks.tenant_id=t AND ks.company_id=c;

 -- T5x: claim TTL elapsed (any mode: REVOKE releases every live claim and voids its approval).
 FOR x IN SELECT ct.token_id, ct.change_id FROM change_ledger.claim_tokens ct
   JOIN change_ledger.records r ON r.change_id=ct.change_id
  WHERE r.tenant_id=t AND r.company_id=c AND ct.state='ISSUED'
   AND (v_mode='REVOKE'
        OR ct.issued_at<=clock_timestamp()-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision))
  ORDER BY ct.issued_at LOOP
  IF change_ledger.release_claim_internal(t,c,x.token_id,v_mode='REVOKE') THEN
   n := n+1; a_t5x := a_t5x||x.change_id;
  END IF;
 END LOOP;

 -- T6c: permit TTL elapsed, undispatched (the cancel CAS decides).
 FOR x IN SELECT dp.change_id, dp.generation FROM change_ledger.dispatch_permits dp
   JOIN change_ledger.records r ON r.change_id=dp.change_id
  WHERE r.tenant_id=t AND r.company_id=c AND dp.state='PERMITTED' AND dp.expires_at<=clock_timestamp()
  ORDER BY dp.expires_at LOOP
  IF change_ledger.cancel_permit(t,c,x.change_id,x.generation) THEN n := n+1; a_t6c := a_t6c||x.change_id; END IF;
 END LOOP;

 -- T6r: APPLYING and the permit of the current generation was never issued, after the permit TTL.
 FOR x IN SELECT r.change_id FROM change_ledger.records r
   JOIN change_ledger.dispatch_permits dp ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
  WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='NOT_PERMITTED'
  ORDER BY r.updated_at LOOP
  IF change_ledger.permit_not_issued_internal(t,c,x.change_id,(p->>'permit_ttl_seconds')::double precision) THEN
   n := n+1; a_t6r := a_t6r||x.change_id;
  END IF;
 END LOOP;

 -- T9: DISPATCHED call past its hard deadline -> APPLY_UNKNOWN + CALL_OWNERSHIP hold (conservative; the
 -- deadline only starts the completion determination, it never proves anything).
 FOR x IN SELECT r.change_id FROM change_ledger.records r
   JOIN change_ledger.dispatch_permits dp ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
  WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='DISPATCHED'
  ORDER BY r.updated_at LOOP
  SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=x.change_id FOR UPDATE;
  IF rec.execution_state<>'APPLYING' OR NOT EXISTS(SELECT 1 FROM change_ledger.dispatch_permits dp
    WHERE dp.change_id=rec.change_id AND dp.generation=rec.claim_generation AND dp.state='DISPATCHED') THEN
   CONTINUE;
  END IF;
  SELECT cd.hard_deadline_at INTO dl FROM change_ledger.call_deadlines cd
   WHERE cd.change_id=rec.change_id AND cd.generation=rec.claim_generation;
  IF dl IS NULL THEN  -- dispatched before 006 recorded deadlines: derive it from the DISPATCHED event
   SELECT max(e.recorded_at) INTO disp FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
    AND e.change_id=rec.change_id AND e.event_type='DISPATCHED';
   dl := coalesce(disp,rec.updated_at)+make_interval(secs=>
    CASE WHEN rec.kind='POST' THEN (p->>'post_deadline_seconds')::double precision
         ELSE (p->>'deadline_seconds')::double precision END);
  END IF;
  IF dl>clock_timestamp() THEN CONTINUE; END IF;
  UPDATE change_ledger.records SET execution_state='APPLY_UNKNOWN', call_ownership='POSSIBLY_EXECUTING',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
  IF NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.change_id=rec.change_id AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL) THEN
   INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
   VALUES(t,c,rec.base_fingerprint,'CALL_OWNERSHIP',rec.change_id);
  END IF;
  PERFORM change_ledger.append_event(t,c,rec.change_id,'HARD_DEADLINE_UNKNOWN',
   jsonb_build_object('generation',rec.claim_generation,'hard_deadline_at',dl));
  n := n+1; a_t9 := a_t9||rec.change_id;
 END LOOP;

 -- T3: expiry of PROPOSED / VALIDATED / APPROVED changes (terminal, no effect possible, no reservation).
 FOR x IN SELECT r.change_id FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.expires_at<=clock_timestamp()
   AND r.execution_state='NOT_STARTED' AND r.lifecycle IN ('PROPOSED','VALIDATED')
   AND r.authorization_state IN ('NONE','APPROVED','EXPIRED') ORDER BY r.created_at LOOP
  SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=x.change_id FOR UPDATE;
  IF rec.expires_at>clock_timestamp() OR rec.execution_state<>'NOT_STARTED'
   OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED')
   OR rec.authorization_state NOT IN ('NONE','APPROVED','EXPIRED') THEN
   CONTINUE;
  END IF;
  UPDATE change_ledger.records SET lifecycle='EXPIRED_QUEUED', authorization_state='EXPIRED',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
  PERFORM change_ledger.append_event(t,c,rec.change_id,'EXPIRED',
   jsonb_build_object('lifecycle_from',rec.lifecycle,'authorization_from',rec.authorization_state));
  n := n+1; a_t3 := a_t3||rec.change_id;
 END LOOP;

 -- REVOKE: unclaimed approvals are voided (claimed ones were released and voided above).
 IF v_mode='REVOKE' THEN
  FOR x IN SELECT r.change_id FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.authorization_state='APPROVED'
    AND r.execution_state='NOT_STARTED' ORDER BY r.created_at LOOP
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
    AND change_id=x.change_id FOR UPDATE;
   IF rec.authorization_state<>'APPROVED' OR rec.execution_state<>'NOT_STARTED' THEN CONTINUE; END IF;
   UPDATE change_ledger.records SET authorization_state='VOIDED', updated_at=clock_timestamp()
    WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
   PERFORM change_ledger.append_event(t,c,rec.change_id,'APPROVAL_VOIDED',jsonb_build_object('cause','REVOKE'));
   n := n+1; a_void := a_void||rec.change_id;
  END LOOP;
 END IF;

 -- T12: durable attempt counter for APPLY_UNKNOWN. The first attempt is due one interval after the
 -- unknown outcome; each due attempt is counted and listed for the worker; the max-th attempt, or the
 -- window elapsing, ends in TRIAGE_REQUIRED (alert event). A resolved change simply leaves this loop.
 FOR x IN SELECT r.change_id FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLY_UNKNOWN' ORDER BY r.updated_at LOOP
  SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=x.change_id FOR UPDATE;
  IF rec.execution_state<>'APPLY_UNKNOWN' THEN CONTINUE; END IF;
  SELECT max(e.recorded_at) INTO started FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.change_id=rec.change_id AND e.event_type IN ('COMPLETE_UNKNOWN','HARD_DEADLINE_UNKNOWN');
  started := coalesce(started,rec.updated_at);
  due_in := (p->>'t12_interval_seconds')::double precision
            + random()*(p->>'t12_jitter_seconds')::double precision;
  INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,next_attempt_at)
  VALUES(t,c,rec.change_id,'RESOLVE',started,started+make_interval(secs=>due_in))
  ON CONFLICT(subject_id,kind) DO NOTHING;
  SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=rec.change_id AND kind='RESOLVE' FOR UPDATE;
  IF k.closed_at IS NOT NULL THEN CONTINUE; END IF;
  IF k.next_attempt_at<=clock_timestamp() THEN
   UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp(),
    next_attempt_at=clock_timestamp()+make_interval(secs=>due_in)
    WHERE subject_id=rec.change_id AND kind='RESOLVE' RETURNING * INTO k;
   n := n+1;
   IF k.attempts>=(p->>'t12_max_attempts')::integer THEN
    PERFORM change_ledger.triage_internal(t,c,rec.change_id,'ATTEMPTS');
    a_t12 := a_t12||rec.change_id;
   ELSIF k.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp() THEN
    PERFORM change_ledger.triage_internal(t,c,rec.change_id,'WINDOW');
    a_t12 := a_t12||rec.change_id;
   ELSE
    PERFORM change_ledger.append_event(t,c,rec.change_id,'RESOLVE_ATTEMPT',
     jsonb_build_object('attempt',k.attempts,'next_attempt_at',k.next_attempt_at));
    a_t12a := a_t12a||rec.change_id;
   END IF;
  ELSIF k.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp() THEN
   IF change_ledger.triage_internal(t,c,rec.change_id,'WINDOW') THEN
    n := n+1; a_t12 := a_t12||rec.change_id;
   END IF;
  END IF;
 END LOOP;

 -- ANCHOR_GAP bound: after the window the hold stays (fail closed) and every unresolved item of the
 -- base (APPLY_UNKNOWN) goes to TRIAGE_REQUIRED; the bound is announced once per hold.
 FOR x IN SELECT h.hold_id, h.base_fingerprint, h.opened_at FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
   AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=clock_timestamp()
  ORDER BY h.opened_at LOOP
  INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,closed_at,close_reason)
  VALUES(t,c,x.hold_id,'ANCHOR_GAP',x.opened_at,clock_timestamp(),'BOUND_EXCEEDED')
  ON CONFLICT(subject_id,kind) DO NOTHING;
  GET DIAGNOSTICS cnt = ROW_COUNT;
  IF cnt=1 THEN
   PERFORM change_ledger.append_event(t,c,NULL,'ANCHOR_GAP_BOUND_EXCEEDED',
    jsonb_build_object('hold_id',x.hold_id,'base_fingerprint',x.base_fingerprint,'alert',true));
   n := n+1;
  END IF;
  FOR y IN SELECT r.change_id FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND r.base_fingerprint=x.base_fingerprint AND r.execution_state='APPLY_UNKNOWN' ORDER BY r.updated_at LOOP
   PERFORM 1 FROM change_ledger.records r WHERE r.change_id=y.change_id FOR UPDATE;
   IF change_ledger.triage_internal(t,c,y.change_id,'ANCHOR_GAP_WINDOW') THEN
    n := n+1; a_gap := a_gap||y.change_id;
   END IF;
  END LOOP;
 END LOOP;

 -- T13/T14 stuck verification: APPLIED but not verified. Each due attempt is counted (bound
 -- verify_max_attempts); the bound reached without a verdict ends in FAILED_VERIFY / UNKNOWN + halt.
 FOR x IN SELECT r.change_id FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED'
  ORDER BY r.updated_at LOOP
  SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=x.change_id FOR UPDATE;
  IF rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED' THEN CONTINUE; END IF;
  SELECT max(e.recorded_at) INTO started FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.change_id=rec.change_id AND e.event_type IN ('COMPLETE_SUCCESS','RESOLVE_UNKNOWN','OPERATOR_RESOLVE');
  started := coalesce(started,rec.updated_at);
  INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,next_attempt_at)
  VALUES(t,c,rec.change_id,'VERIFY',started,
   started+make_interval(secs=>(p->>'verify_interval_seconds')::double precision))
  ON CONFLICT(subject_id,kind) DO NOTHING;
  SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=rec.change_id AND kind='VERIFY' FOR UPDATE;
  IF k.closed_at IS NOT NULL OR k.next_attempt_at>clock_timestamp() THEN CONTINUE; END IF;
  v := change_ledger.verify_attempt_internal(t,c,rec.change_id,'SWEEP_STUCK',
   (p->>'verify_max_attempts')::integer,(p->>'verify_interval_seconds')::double precision);
  n := n+1;
  IF (v->>'exhausted')::boolean THEN a_vexh := a_vexh||rec.change_id; ELSE a_vdue := a_vdue||rec.change_id; END IF;
 END LOOP;

 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,started_at,finished_at,changed)
 VALUES(t,c,v_start,clock_timestamp(),n);
 RETURN jsonb_build_object('changed',n,'T5x',to_jsonb(a_t5x),'T6c',to_jsonb(a_t6c),'T6r',to_jsonb(a_t6r),
  'T9',to_jsonb(a_t9),'T3',to_jsonb(a_t3),'VOIDED',to_jsonb(a_void),'T12_ATTEMPT',to_jsonb(a_t12a),
  'T12',to_jsonb(a_t12),'ANCHOR_GAP_TRIAGE',to_jsonb(a_gap),'VERIFY_DUE',to_jsonb(a_vdue),
  'VERIFY_EXHAUSTED',to_jsonb(a_vexh));
END $fn$;

-- Legacy signature of 004 (integer count), now running every transition above with the defaults.
CREATE OR REPLACE FUNCTION change_ledger.recover_sweep(t text, c text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 RETURN (change_ledger.recover_sweep(t,c,'{}'::jsonb)->>'changed')::integer;
END $fn$;

-- T8 transient LOCK_BUSY at stage PRE_WRITE: back to APPROVED with a durable attempt counter (max 5,
-- interval with jitter, 15 min window; a claim before next_attempt_at is refused by records_lock_busy_gate),
-- then the definite PRE_WRITE path of complete() (FAILED_APPLY). The no-effect proof is mandatory (S12-M02).
CREATE OR REPLACE FUNCTION change_ledger.complete_lock_busy(
 t text, c text, p_change_id uuid, p_generation bigint, p_evidence jsonb, p_no_effect_proof jsonb,
 p_params jsonb DEFAULT '{}'::jsonb
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE p jsonb; rec change_ledger.records%ROWTYPE; k change_ledger.sweep_counters%ROWTYPE; due_in double precision;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 p := change_ledger.sweep_params(p_params,
  '{"lock_busy_max_attempts":5,"lock_busy_interval_seconds":180,"lock_busy_jitter_seconds":30,
    "lock_busy_window_seconds":900}'::jsonb);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN
  IF rec.execution_state='FAILED_APPLY' THEN RETURN rec.execution_state; END IF;
  IF rec.execution_state='NOT_STARTED' AND rec.authorization_state='APPROVED' THEN RETURN 'APPROVED'; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_no_effect_proof IS NULL THEN RAISE EXCEPTION 'WRITE_REFUSED'; END IF;
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'LOCK_BUSY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=p_change_id AND kind='LOCK_BUSY' FOR UPDATE;
 IF k.closed_at IS NULL AND k.attempts<(p->>'lock_busy_max_attempts')::integer
  AND k.started_at+make_interval(secs=>(p->>'lock_busy_window_seconds')::double precision)>clock_timestamp() THEN
  due_in := (p->>'lock_busy_interval_seconds')::double precision
            + random()*(p->>'lock_busy_jitter_seconds')::double precision;
  UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp(),
   next_attempt_at=clock_timestamp()+make_interval(secs=>due_in)
   WHERE subject_id=p_change_id AND kind='LOCK_BUSY' RETURNING * INTO k;
  UPDATE change_ledger.dispatch_permits SET state='CANCELLED_UNDISPATCHED'
   WHERE change_id=p_change_id AND generation=p_generation AND state IN ('NOT_PERMITTED','PERMITTED');
  UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE change_id=p_change_id AND generation=p_generation;
  PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
  UPDATE change_ledger.records SET
   authorization_state=CASE WHEN rec.expires_at<=clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
   execution_state='NOT_STARTED', dispatch_state='NOT_PERMITTED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  PERFORM change_ledger.append_event(t,c,p_change_id,'LOCK_BUSY_RETRY',
   jsonb_build_object('attempt',k.attempts,'next_attempt_at',k.next_attempt_at,
    'evidence',coalesce(p_evidence,'{}'::jsonb)));
  RETURN 'APPROVED';
 END IF;
 UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason='DEFINITE'
  WHERE subject_id=p_change_id AND kind='LOCK_BUSY' AND closed_at IS NULL;
 RETURN change_ledger.complete(t,c,p_change_id,p_generation,'PRE_WRITE_REFUSAL',p_evidence,p_no_effect_proof);
END $fn$;

-- Worker-driven verification bookkeeping: an inconclusive verification attempt (reader unhealthy, partial
-- observation) is counted; the bound-th attempt ends in FAILED_VERIFY / effect_known UNKNOWN + halt (T14).
CREATE OR REPLACE FUNCTION change_ledger.verify_inconclusive(
 t text, c text, p_change_id uuid, p_evidence jsonb, p_max_attempts integer DEFAULT 3
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_max_attempts IS NULL OR p_max_attempts<1 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_evidence IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 RETURN change_ledger.verify_attempt_internal(t,c,p_change_id,'WORKER_INCONCLUSIVE',p_max_attempts,180);
END $fn$;

-- T17 retry verify (bound 3, owner = the worker): a FAILED_VERIFY change whose own halt is still open
-- can be re-verified. A pass releases the halt and the target lock; the fourth call is refused.
CREATE OR REPLACE FUNCTION change_ledger.retry_verify(
 t text, c text, p_change_id uuid, p_evidence jsonb, p_passed boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; k change_ledger.sweep_counters%ROWTYPE; owner_id uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.verification_state<>'FAILED_VERIFY' OR NOT EXISTS(SELECT 1 FROM change_ledger.holds h
   WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT'
    AND h.released_at IS NULL) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_evidence IS NULL OR p_passed IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 SELECT tl.owner_change_id INTO owner_id FROM change_ledger.target_locks tl
  WHERE tl.tenant_id=t AND tl.company_id=c AND tl.base_fingerprint=rec.base_fingerprint
   AND tl.target_ref=coalesce(rec.target_ref,rec.change_id::text);
 IF owner_id IS NOT NULL AND owner_id<>p_change_id THEN RAISE EXCEPTION 'LOCK_BUSY'; END IF;
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'VERIFY_RETRY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=p_change_id AND kind='VERIFY_RETRY' FOR UPDATE;
 IF k.attempts>=3 THEN RAISE EXCEPTION 'VERIFY_FAILED'; END IF;
 UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp()
  WHERE subject_id=p_change_id AND kind='VERIFY_RETRY' RETURNING * INTO k;
 IF p_passed THEN
  UPDATE change_ledger.records SET verification_state='VERIFIED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.holds SET released_at=clock_timestamp(),
   release_evidence=jsonb_build_object('retry_verify',k.attempts,'evidence',p_evidence)
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND cause='FAILED_VERIFY_HALT'
    AND released_at IS NULL;
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason='VERIFIED'
   WHERE subject_id=p_change_id AND kind='VERIFY_RETRY';
  PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_PASSED',
   jsonb_build_object('attempt',k.attempts)||jsonb_build_object('evidence',p_evidence));
  RETURN 'VERIFIED';
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_FAILED',
  jsonb_build_object('attempt',k.attempts)||jsonb_build_object('evidence',p_evidence));
 RETURN 'FAILED_VERIFY';
END $fn$;

-- ================================================================== (2) anchor gap / unclean restart
-- A checkpoint cannot be written (CT5): opens ANCHOR_GAP on the base (or every base of the scope). Idempotent.
CREATE OR REPLACE FUNCTION change_ledger.declare_anchor_gap(t text, c text, p_base text, p_detail jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 RETURN change_ledger.open_hold_internal(t,c,p_base,'ANCHOR_GAP','ANCHOR_GAP',
  coalesce(p_detail,'{}'::jsonb)||jsonb_build_object('source','DECLARED'));
END $fn$;

-- The service found that the previous run did not stop cleanly: RLC_UNCLEAN hold (blocks claim,
-- begin_apply and dispatch) until the S13 resume procedure releases it (release_hold). Idempotent.
CREATE OR REPLACE FUNCTION change_ledger.declare_unclean_restart(t text, c text, p_base text, p_detail jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 RETURN change_ledger.open_hold_internal(t,c,p_base,'RLC_UNCLEAN','UNCLEAN_RESTART',p_detail);
END $fn$;

-- release_hold (operator): CALL_OWNERSHIP never (operator_resolve/resolve_unknown with completion proof);
-- FAILED_VERIFY_HALT never (T17: retry_verify / operator_close_failed_verify / the repair's T13);
-- ANCHOR_GAP: evidence {"store_accepted":true} AND a REAL read-back checkpoint written after the hold opened
-- whose head equals the ledger event at its seq AND a verified hash chain;
-- RLC_UNCLEAN: evidence {"resume_procedure":"S13_RESUME","completed":true} AND a recover_sweep run that started
-- after the hold opened AND no APPLYING change on the base AND a verified hash chain.
CREATE OR REPLACE FUNCTION change_ledger.release_hold(
 t text, c text, p_hold_id uuid, p_release_evidence jsonb
) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE h change_ledger.holds%ROWTYPE; ts timestamptz; cp bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO h FROM change_ledger.holds WHERE hold_id=p_hold_id AND tenant_id=t AND company_id=c
  FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 IF h.cause='CALL_OWNERSHIP' THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 IF h.released_at IS NOT NULL THEN RETURN h.released_at; END IF;
 IF h.cause='FAILED_VERIFY_HALT' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF p_release_evidence IS NULL OR jsonb_typeof(p_release_evidence)<>'object' THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 IF h.cause='ANCHOR_GAP' THEN
  IF p_release_evidence->'store_accepted' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
  END IF;
  SELECT k.seq INTO cp FROM change_ledger.checkpoints k
   JOIN change_ledger.events e ON e.tenant_id=k.tenant_id AND e.company_id=k.company_id
    AND e.seq=k.ledger_seq AND e.hash=k.head_hash
   WHERE k.tenant_id=t AND k.company_id=c AND k.sink_kind='REAL' AND k.read_back_confirmed
    AND k.written_at>=h.opened_at ORDER BY k.seq DESC LIMIT 1;
  IF cp IS NULL THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
  IF NOT change_ledger.chain_ok(t,c) THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
 ELSIF h.cause='RLC_UNCLEAN' THEN
  IF p_release_evidence->>'resume_procedure' IS DISTINCT FROM 'S13_RESUME'
   OR p_release_evidence->'completed' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM change_ledger.sweep_runs s WHERE s.tenant_id=t AND s.company_id=c
    AND s.started_at>=h.opened_at)
   OR EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND r.base_fingerprint=h.base_fingerprint AND r.execution_state='APPLYING') THEN
   RAISE EXCEPTION 'BASE_HOLD';
  END IF;
  IF NOT change_ledger.chain_ok(t,c) THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
 END IF;
 UPDATE change_ledger.holds SET released_at=clock_timestamp(), release_evidence=p_release_evidence
  WHERE hold_id=p_hold_id RETURNING released_at INTO ts;
 PERFORM change_ledger.append_event(t,c,h.change_id,'HOLD_RELEASED',
  jsonb_build_object('hold_id',p_hold_id,'cause',h.cause));
 RETURN ts;
END $fn$;

-- ================================================================== (3) T17 operator closure
-- A FAILED_VERIFY change whose own halt is open is closed by the operator with a witness cosign carrying an
-- independent completion proof (class a or b), under the two-person rules of T16. The change stays
-- FAILED_VERIFY as history (change_closures marks the closure); the halt, the target lock and the key lock
-- are released. p_effect_present = true keeps the reservation CONSUMED; false (refund) needs effect_known
-- other than YES and releases it - never a silent refund. A repair that owns the target lock blocks it.
CREATE OR REPLACE FUNCTION change_ledger.operator_close_failed_verify(
 t text, c text, p_change_id uuid, p_cosign_id uuid, p_effect_present boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_operator text; cs change_ledger.witness_cosigns%ROWTYPE;
 owner_id uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 v_operator := change_ledger.caller_role();
 IF p_effect_present IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.verification_state<>'FAILED_VERIFY'
  OR EXISTS(SELECT 1 FROM change_ledger.change_closures cc WHERE cc.change_id=p_change_id)
  OR NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF NOT p_effect_present AND rec.effect_known IS NOT DISTINCT FROM 'YES' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 SELECT tl.owner_change_id INTO owner_id FROM change_ledger.target_locks tl
  WHERE tl.tenant_id=t AND tl.company_id=c AND tl.base_fingerprint=rec.base_fingerprint
   AND tl.target_ref=coalesce(rec.target_ref,rec.change_id::text);
 IF owner_id IS NOT NULL AND owner_id<>p_change_id THEN RAISE EXCEPTION 'LOCK_BUSY'; END IF;
 cs := change_ledger.consume_two_person_cosign(rec,v_operator,p_cosign_id);
 UPDATE change_ledger.holds SET released_at=clock_timestamp(),
  release_evidence=jsonb_build_object('closed_by_operator',v_operator,'witness',cs.signer,
   'completion_proof',cs.completion_proof)
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND cause='FAILED_VERIFY_HALT'
   AND released_at IS NULL;
 DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 IF p_effect_present THEN
  UPDATE change_ledger.records SET effect_known='YES', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSE
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state<>'RELEASED';
  UPDATE change_ledger.records SET effect_known='NO', reservation_state='RELEASED',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 END IF;
 INSERT INTO change_ledger.change_closures(tenant_id,company_id,change_id,closed_by,witness,cosign_id,
  effect_present,completion_proof)
 VALUES(t,c,p_change_id,v_operator,cs.signer,p_cosign_id,p_effect_present,cs.completion_proof);
 PERFORM change_ledger.append_event(t,c,p_change_id,'FAILED_VERIFY_CLOSED',
  jsonb_build_object('effect_present',p_effect_present,'cosign_id',p_cosign_id));
 RETURN 'CLOSED';
END $fn$;

-- ================================================================== (4) kill switch: re-enable sweeps first
-- Same contract as 004 (durable mode record) plus: a re-enable (a non-OFF mode set to OFF) runs recover_sweep
-- first, in the same transaction, so REVOKE-voided approvals, expired claims and stuck items are settled
-- before effects can resume. A failing sweep keeps the switch on.
CREATE OR REPLACE FUNCTION change_ledger.kill_switch(
 t text, c text, p_mode text
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; cur text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_mode NOT IN ('OFF','STOP_ADMIT','STOP_EFFECTS','REVOKE') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 who := change_ledger.caller_role();
 PERFORM pg_advisory_xact_lock(hashtextextended('killswitch:'||t||':'||c,0));
 SELECT ks.mode INTO cur FROM change_ledger.kill_switch_state ks WHERE ks.tenant_id=t AND ks.company_id=c;
 IF p_mode='OFF' AND coalesce(cur,'OFF')<>'OFF' THEN
  PERFORM change_ledger.recover_sweep(t,c,'{}'::jsonb);
 END IF;
 INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode,updated_by)
 VALUES(t,c,p_mode,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET mode=p_mode, updated_by=who,
  updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'KILL_SWITCH',jsonb_build_object('mode',p_mode,'by',who));
 RETURN p_mode;
END $fn$;

-- ================================================================== (5) writer lease renewal and fence
-- Renewal while a call is in flight (permit PERMITTED or DISPATCHED, current generation). A lease whose
-- expiry already passed is lost (fencing): it cannot be renewed and fence_check / record_call refuse it.
CREATE OR REPLACE FUNCTION change_ledger.renew_writer_lease(
 t text, c text, p_change_id uuid, p_generation bigint, p_ttl_seconds integer DEFAULT 300
) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; exp_at timestamptz; n integer;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_ttl_seconds IS NULL OR p_ttl_seconds<1 OR p_ttl_seconds>3600 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.dispatch_permits dp WHERE dp.change_id=p_change_id
   AND dp.generation=p_generation AND dp.state IN ('PERMITTED','DISPATCHED')) THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 exp_at := clock_timestamp()+make_interval(secs=>p_ttl_seconds);
 UPDATE change_ledger.writer_leases SET lease_expires_at=exp_at, renewed_at=clock_timestamp(),
  renew_count=renew_count+1
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=rec.base_fingerprint
   AND owner_change_id=p_change_id AND (lease_expires_at IS NULL OR lease_expires_at>clock_timestamp());
 GET DIAGNOSTICS n = ROW_COUNT;
 IF n=0 THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'LEASE_RENEWED',
  jsonb_build_object('generation',p_generation,'lease_expires_at',exp_at));
 RETURN exp_at;
END $fn$;

-- Fence check the writer runs before EACH call: current generation, permit of this call_id still usable
-- (PERMITTED unexpired with the switch off and no blocking hold, or already DISPATCHED = the call itself),
-- and the lease held and unexpired. Raises the typed refusal; returns {"ok":true,...} otherwise.
CREATE OR REPLACE FUNCTION change_ledger.fence_check(
 t text, c text, p_change_id uuid, p_generation bigint, p_call_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE; lease_exp timestamptz;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits WHERE change_id=p_change_id AND generation=p_generation;
 IF NOT FOUND OR dp.call_id IS DISTINCT FROM p_call_id OR dp.state='NOT_PERMITTED' THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 IF dp.state='CANCELLED_UNDISPATCHED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF dp.state='PERMITTED' THEN
  PERFORM change_ledger.assert_switch_off(t,c);
  IF dp.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 END IF;
 PERFORM change_ledger.fence_assert(t,c,rec,dp.state='PERMITTED');
 SELECT wl.lease_expires_at INTO lease_exp FROM change_ledger.writer_leases wl
  WHERE wl.tenant_id=t AND wl.company_id=c AND wl.base_fingerprint=rec.base_fingerprint
   AND wl.owner_change_id=p_change_id;
 RETURN jsonb_build_object('ok',true,'generation',p_generation,'permit_state',dp.state,
  'lease_expires_at',lease_exp);
END $fn$;

-- The fence on the ONE dispatch compare-and-set, as a trigger so it composes with every version of
-- record_call (004's, 005's target-effect guard, ...): the PERMITTED -> DISPATCHED update is refused unless
-- the lease is held and unexpired (TICKET_SUPERSEDED) and no blocking hold is open (BASE_HOLD; a repair
-- UNPOST excepts only its parent's halt). When the CAS is allowed, the hard deadline of the call
-- (120 s, POST 300 s) is stored for the sweep's T9. The switch and the permit TTL stay in record_call.
CREATE OR REPLACE FUNCTION change_ledger.dispatch_fence_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; secs integer;
BEGIN
 IF OLD.state='PERMITTED' AND NEW.state='DISPATCHED' THEN
  SELECT * INTO rec FROM change_ledger.records WHERE change_id=NEW.change_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
  PERFORM change_ledger.fence_assert(rec.tenant_id,rec.company_id,rec,true);
  secs := change_ledger.call_deadline_seconds(rec.kind);
  INSERT INTO change_ledger.call_deadlines(tenant_id,company_id,change_id,generation,call_id,
   deadline_seconds,hard_deadline_at)
  VALUES(rec.tenant_id,rec.company_id,NEW.change_id,NEW.generation,NEW.call_id,secs,
   clock_timestamp()+make_interval(secs=>secs))
  ON CONFLICT(change_id,generation) DO NOTHING;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS dispatch_permits_fence ON change_ledger.dispatch_permits;
CREATE TRIGGER dispatch_permits_fence BEFORE UPDATE OF state ON change_ledger.dispatch_permits
 FOR EACH ROW EXECUTE FUNCTION change_ledger.dispatch_fence_guard();

-- ================================================================== ownership, privileges, RLS
DO $fn$
DECLARE o record;
BEGIN
 FOR o IN SELECT c.oid::regclass AS rel FROM pg_catalog.pg_class c
   JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='change_ledger' AND c.relkind IN ('r','p')
 LOOP EXECUTE format('ALTER TABLE %s OWNER TO ledger_owner',o.rel); END LOOP;
 FOR o IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='change_ledger'
 LOOP EXECUTE format('ALTER FUNCTION %s OWNER TO ledger_owner',o.sig); END LOOP;
END $fn$;

REVOKE ALL ON ALL TABLES IN SCHEMA change_ledger FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA change_ledger FROM PUBLIC;

GRANT SELECT ON change_ledger.sweep_counters, change_ledger.sweep_runs, change_ledger.call_deadlines,
 change_ledger.change_closures TO auditor_role, worker_role, operator_role;

GRANT EXECUTE ON FUNCTION
 change_ledger.recover_sweep(text,text,jsonb),
 change_ledger.verify_inconclusive(text,text,uuid,jsonb,integer),
 change_ledger.retry_verify(text,text,uuid,jsonb,boolean),
 change_ledger.declare_anchor_gap(text,text,text,jsonb),
 change_ledger.declare_unclean_restart(text,text,text,jsonb)
 TO worker_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.declare_anchor_gap(text,text,text,jsonb),
 change_ledger.declare_unclean_restart(text,text,text,jsonb),
 change_ledger.operator_close_failed_verify(text,text,uuid,uuid,boolean)
 TO operator_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.complete_lock_busy(text,text,uuid,bigint,jsonb,jsonb,jsonb),
 change_ledger.renew_writer_lease(text,text,uuid,bigint,integer),
 change_ledger.fence_check(text,text,uuid,bigint,uuid),
 change_ledger.declare_anchor_gap(text,text,text,jsonb)
 TO writer_role;

DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY['sweep_counters','sweep_runs','call_deadlines','change_closures'] LOOP
  EXECUTE format('ALTER TABLE change_ledger.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS owner_all ON change_ledger.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS scope_isolation ON change_ledger.%I',tbl);
  EXECUTE format('CREATE POLICY owner_all ON change_ledger.%I FOR ALL TO ledger_owner USING (true) WITH CHECK (true)',tbl);
  EXECUTE format('CREATE POLICY scope_isolation ON change_ledger.%I FOR ALL USING (change_ledger.row_in_scope(tenant_id,company_id)) WITH CHECK (change_ledger.row_in_scope(tenant_id,company_id))',tbl);
 END LOOP;
END $fn$;

$body$;
END IF;
END $mig$;
COMMIT;
