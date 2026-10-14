-- R2/G1 S13 hardening, batch E: three open items (A7-B01, C-M03, B6-h). Applies after 011. Apply ONLY to a verified
-- disposable PostgreSQL database (checksum precondition: living.record_migration). NON-GATING PROTOTYPE: not gate
-- evidence; no real 1C write.
--
--  E1 (A7-B01) The writer dispatch is coupled to verify_dispatch_payload INSIDE the ledger. 009 left record_call (the
--     PERMITTED -> DISPATCHED compare-and-set) uncoupled to avoid a port signature change. Now verify_dispatch_payload
--     (same signature, now VOLATILE) records an immutable marker (change_dispatch_verifications) per
--     (change_id, generation, payload_digest) when it returns true: the payload the writer is about to send recomputed to
--     the approved payload_digest under the current claim generation. record_call - and, as a backstop for any other
--     path, a BEFORE UPDATE trigger on dispatch_permits that fires whenever a permit becomes DISPATCHED - calls
--     assert_dispatch_verified: a marker for the CURRENT claim generation and the CURRENT payload_digest must exist and
--     assert_approval_current must still pass (stored envelope still hashes to the approved digest and still binds the
--     change). Otherwise the transition is refused with FORBIDDEN_TRANSITION (no marker) or the existing
--     APPROVAL_VOIDED / DIGEST_MISMATCH of assert_approval_current; the permit stays PERMITTED, so the writer can verify
--     and retry within the permit TTL. No new error code: FORBIDDEN_TRANSITION is the ledger's conventional "this
--     transition is not allowed from here". The marker event DISPATCH_PAYLOAD_VERIFIED carries digests only, never the
--     payload text. Replay of verify_dispatch_payload is idempotent (one marker, one event). Port signatures unchanged.
--     NAMED LIMIT: the ledger proves that the writer asked for verification of a payload that matches the approved
--     digest; it cannot prove that the bytes the writer finally sends to 1C are the bytes it verified.
--  E2 (C-M03) The approver's session is recorded on the approval: approvals.approver_session is filled by a BEFORE
--     INSERT trigger from session_user (never caller-supplied; same technique as witness_cosigns.signer_session in 010).
--     The consume guard of witness cosigns (010; it covers operator_resolve and operator_close_failed_verify through
--     consume_two_person_cosign, and every future consumer) now also refuses a consuming session that is the same
--     person (same_person on session_user vs approvals.approver_session) as the session of ANY approval of the change.
--     A superuser session is exempt exactly as in assert_session_independent. A change with no approval is not
--     affected. An approval written before 012 has no recorded session and fails closed for a non-superuser consumer
--     (only on this new comparison). hold_cosigns (ANCHOR_GAP release) concern holds, not approvals: nothing to compare.
--  E3 (B6-h) The sweep tick of the stuck-verification stage (verify_attempt_internal with reason SWEEP_STUCK) counts
--     only if at least the minimum spacing elapsed since the previous counted attempt of that change. The spacing is the
--     ledger constant verify_min_tick_seconds (default 5, in sweep_constants); the operator policy may raise it up to
--     3600 but set_sweep_policy refuses anything below 1, and verify_tick_min_spacing() never returns less than 1
--     second whatever a row says. The next due time of the counter is also floored by the spacing, so a worker-tuned
--     verify_interval_seconds of 0 can no longer burn verify_max_attempts by sweeping often. Real signed inconclusive
--     observations (verify_inconclusive) are attempts by evidence, not ticks, and are not spaced. NAMED LIMIT: the
--     other timer-driven counters (T12, LOCK_BUSY) keep their own intervals and are not changed here.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('012', ARRAY['001','002','003','004','005','006','007','008','009','010','011']) THEN
EXECUTE $body$

-- ================================================================== E1 storage: the dispatch verification marker
CREATE TABLE IF NOT EXISTS change_ledger.change_dispatch_verifications(
 verification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL,
 change_id uuid NOT NULL,
 generation bigint NOT NULL,
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 verified_by text NOT NULL, verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(change_id, generation, payload_digest),
 FOREIGN KEY(tenant_id,company_id,change_id) REFERENCES change_ledger.records(tenant_id,company_id,change_id)
);
ALTER TABLE change_ledger.change_dispatch_verifications OWNER TO ledger_owner;
ALTER TABLE change_ledger.change_dispatch_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_ledger.change_dispatch_verifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS owner_all ON change_ledger.change_dispatch_verifications;
DROP POLICY IF EXISTS scope_read ON change_ledger.change_dispatch_verifications;
CREATE POLICY owner_all ON change_ledger.change_dispatch_verifications FOR ALL TO ledger_owner USING (true) WITH CHECK (true);
CREATE POLICY scope_read ON change_ledger.change_dispatch_verifications FOR SELECT
 USING (change_ledger.row_in_scope(tenant_id,company_id));
DROP TRIGGER IF EXISTS change_dispatch_verifications_immutable ON change_ledger.change_dispatch_verifications;
CREATE TRIGGER change_dispatch_verifications_immutable BEFORE UPDATE OR DELETE ON change_ledger.change_dispatch_verifications
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();
DROP TRIGGER IF EXISTS change_dispatch_verifications_no_truncate ON change_ledger.change_dispatch_verifications;
CREATE TRIGGER change_dispatch_verifications_no_truncate BEFORE TRUNCATE ON change_ledger.change_dispatch_verifications
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation();
GRANT SELECT ON change_ledger.change_dispatch_verifications TO auditor_role;

-- the gate itself: marker for the current generation and payload digest + the approval still current
CREATE OR REPLACE FUNCTION change_ledger.assert_dispatch_verified(p_change_id uuid, p_generation bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
BEGIN
 SELECT * INTO rec FROM change_ledger.records r WHERE r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation OR NOT EXISTS(
   SELECT 1 FROM change_ledger.change_dispatch_verifications v WHERE v.change_id=p_change_id
    AND v.generation=p_generation AND v.payload_digest=rec.payload_digest) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';     -- dispatch without verify_dispatch_payload of this generation
 END IF;
 PERFORM change_ledger.assert_approval_current(rec.tenant_id,rec.company_id,rec);
END $fn$;

-- backstop: whatever path moves a permit to DISPATCHED must pass the same gate
CREATE OR REPLACE FUNCTION change_ledger.dispatch_permit_verified_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NEW.state='DISPATCHED' AND OLD.state IS DISTINCT FROM 'DISPATCHED' THEN
  PERFORM change_ledger.assert_dispatch_verified(NEW.change_id,NEW.generation);
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS dispatch_permits_verified_guard ON change_ledger.dispatch_permits;
CREATE TRIGGER dispatch_permits_verified_guard BEFORE UPDATE OF state ON change_ledger.dispatch_permits
 FOR EACH ROW EXECUTE FUNCTION change_ledger.dispatch_permit_verified_guard();

-- verify_dispatch_payload (009 body) + the immutable marker; VOLATILE now (it writes). Same signature and grants.
CREATE OR REPLACE FUNCTION change_ledger.verify_dispatch_payload(
 t text, c text, p_change_id uuid, p_generation bigint, p_payload text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; pl jsonb; vid uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF who IS DISTINCT FROM rec.requester AND NOT pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.authorization_state<>'CLAIMED' OR rec.execution_state<>'APPLYING' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_approval_current(t,c,rec);
 BEGIN
  pl := coalesce(p_payload,'{}')::jsonb;
 EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END;
 IF jsonb_typeof(pl)='null' THEN pl := '{}'::jsonb; END IF;
 IF jsonb_typeof(pl)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF change_ledger.payload_digest_of(pl,rec.target_version) IS DISTINCT FROM rec.payload_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';          -- payload substituted after approval: dispatch is refused
 END IF;
 INSERT INTO change_ledger.change_dispatch_verifications(tenant_id,company_id,change_id,generation,payload_digest,verified_by)
 VALUES(t,c,p_change_id,p_generation,rec.payload_digest,who)
 ON CONFLICT(change_id,generation,payload_digest) DO NOTHING
 RETURNING verification_id INTO vid;
 IF vid IS NOT NULL THEN                       -- first verification only: a replay writes nothing
  PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_PAYLOAD_VERIFIED',
   jsonb_build_object('generation',p_generation,'payload_digest',rec.payload_digest,'verification_id',vid));
 END IF;
 RETURN true;
END $fn$;

-- record_call (005 body) + the verification gate right before the compare-and-set
CREATE OR REPLACE FUNCTION change_ledger.record_call(
 t text, c text, p_change_id uuid, p_generation bigint, p_call_id uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits WHERE change_id=p_change_id AND generation=p_generation;
 IF NOT FOUND OR dp.call_id IS DISTINCT FROM p_call_id THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF dp.state='NOT_PERMITTED' THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 IF dp.state='PERMITTED' THEN
  PERFORM change_ledger.assert_switch_off(t,c);
  PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
  IF dp.expires_at<=clock_timestamp() THEN RETURN false; END IF;
  PERFORM change_ledger.assert_dispatch_verified(p_change_id,p_generation);   -- A7-B01
 END IF;
 IF NOT change_ledger.dispatch_cas(p_change_id,p_generation,'PERMITTED','DISPATCHED') THEN
  RETURN false;
 END IF;
 UPDATE change_ledger.records SET dispatch_state='DISPATCHED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCHED',
  jsonb_build_object('generation',p_generation,'call_id',p_call_id));
 RETURN true;
END $fn$;

-- ================================================================== E2 approver session on the approval
ALTER TABLE change_ledger.approvals ADD COLUMN IF NOT EXISTS approver_session text;

CREATE OR REPLACE FUNCTION change_ledger.approval_session_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 NEW.approver_session := session_user::text;     -- never taken from the caller
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS approvals_session_guard ON change_ledger.approvals;
CREATE TRIGGER approvals_session_guard BEFORE INSERT ON change_ledger.approvals
 FOR EACH ROW EXECUTE FUNCTION change_ledger.approval_session_guard();

-- consume guard of 010 + the approver's session
CREATE OR REPLACE FUNCTION change_ledger.witness_cosign_consume_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE r change_ledger.records%ROWTYPE; ap record;
BEGIN
 IF OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL THEN RETURN NEW; END IF;
 IF change_ledger.cosign_session_is_exempt() THEN RETURN NEW; END IF;
 SELECT * INTO r FROM change_ledger.records x WHERE x.change_id=NEW.change_id;
 IF OLD.signer_session IS NULL THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
 IF change_ledger.same_person(r.tenant_id,r.company_id,session_user::text,OLD.signer_session) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_session_independent(r.tenant_id,r.company_id,r.requester_session);
 FOR ap IN SELECT a.approver_session FROM change_ledger.approvals a
   WHERE a.change_id=NEW.change_id AND a.decision='APPROVE' LOOP
  IF ap.approver_session IS NULL
   OR change_ledger.same_person(r.tenant_id,r.company_id,session_user::text,ap.approver_session) THEN
   RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';   -- the approver's session (or an approval without one) cannot resolve
  END IF;
 END LOOP;
 RETURN NEW;
END $fn$;

-- ================================================================== E3 minimum spacing of counted verification ticks
CREATE OR REPLACE FUNCTION change_ledger.sweep_constants() RETURNS jsonb
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT '{"claim_ttl_seconds":120,"permit_ttl_seconds":60,"t12_window_seconds":900,"t12_max_attempts":5,
  "anchor_gap_window_seconds":900,"verify_max_attempts":3,"verify_min_tick_seconds":5}'::jsonb
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.verify_tick_min_spacing(t text, c text) RETURNS double precision
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT greatest(1::double precision,
  coalesce((change_ledger.sweep_effective(t,c)->>'verify_min_tick_seconds')::double precision, 5::double precision))
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.set_sweep_policy(t text, c text, p_params jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; pk text; pv jsonb; num numeric; prev jsonb; lo_v numeric; hi_v numeric; merged jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_params IS NULL OR jsonb_typeof(p_params)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 FOR pk, pv IN SELECT * FROM jsonb_each(p_params) LOOP
  IF NOT (change_ledger.sweep_constants() ? pk) OR jsonb_typeof(pv)<>'number' THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  num := (pv#>>'{}')::numeric;
  SELECT r.lo, r.hi INTO lo_v, hi_v FROM (VALUES
   ('claim_ttl_seconds',10,3600),('permit_ttl_seconds',10,600),('t12_window_seconds',60,86400),
   ('t12_max_attempts',1,50),('anchor_gap_window_seconds',60,86400),('verify_max_attempts',1,20),
   ('verify_min_tick_seconds',1,3600)
  ) AS r(kk,lo,hi) WHERE r.kk=pk;
  IF num<lo_v OR num>hi_v OR ((pk LIKE '%\_attempts') AND num<>trunc(num)) THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 END LOOP;
 SELECT sp.params INTO prev FROM change_ledger.sweep_policy sp WHERE sp.tenant_id=t AND sp.company_id=c FOR UPDATE;
 merged := coalesce(prev,'{}'::jsonb) || p_params;
 INSERT INTO change_ledger.sweep_policy(tenant_id,company_id,params,updated_by) VALUES(t,c,merged,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET params=EXCLUDED.params, updated_by=who,
  updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'SWEEP_POLICY_SET',
  jsonb_build_object('previous',coalesce(prev,'{}'::jsonb),'params',merged,'by',who));
 RETURN merged;
END $fn$;

-- verify_attempt_internal (006 body): a SWEEP_STUCK tick inside the minimum spacing is not counted, and the next due
-- time is never earlier than the spacing, whatever interval the caller passes
CREATE OR REPLACE FUNCTION change_ledger.verify_attempt_internal(
 t text, c text, p_change_id uuid, p_reason text, p_max integer, p_interval double precision
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE k change_ledger.sweep_counters%ROWTYPE; exhausted boolean := false; spacing double precision;
BEGIN
 spacing := change_ledger.verify_tick_min_spacing(t,c);
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'VERIFY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters WHERE subject_id=p_change_id AND kind='VERIFY' FOR UPDATE;
 IF k.closed_at IS NOT NULL THEN RETURN jsonb_build_object('attempts',k.attempts,'exhausted',true); END IF;
 IF p_reason='SWEEP_STUCK' AND k.last_attempt_at IS NOT NULL
  AND clock_timestamp() < k.last_attempt_at + make_interval(secs=>spacing) THEN
  RETURN jsonb_build_object('attempts',k.attempts,'exhausted',false,'throttled',true);   -- not a counted tick
 END IF;
 UPDATE change_ledger.sweep_counters SET attempts=attempts+1, last_attempt_at=clock_timestamp(),
  next_attempt_at=clock_timestamp()+make_interval(secs=>greatest(p_interval,spacing))
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

-- ================================================================== wiring, ownership, privileges (keep last)
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
