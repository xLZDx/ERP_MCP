-- R2/G1 S13 hardening, batch F: ONE invariant for every change of the DISPATCHED state (GPT-PM F-02, conditions E-03 and
-- E-04). Applies after 012. Apply ONLY to a verified disposable PostgreSQL database (checksum precondition:
-- living.record_migration). NON-GATING PROTOTYPE: not gate evidence; no real 1C write.
--
-- Problem. 012 guarded exactly one door: UPDATE OF state on dispatch_permits (trigger dispatch_permits_verified_guard ->
-- assert_dispatch_verified). Two more doors led to the same fact "this change was dispatched": a permit created already
-- in a state other than NOT_PERMITTED (INSERT), and records.dispatch_state itself (UPDATE / INSERT), which record_call
-- writes after the permit CAS but which nothing checked. The invariant now holds at every door, in the table itself
-- (triggers, not roles), so it also stops the table owner and a superuser session that does not disable triggers:
--
--   I-DISPATCHED  A change is DISPATCHED only if (a) its permit of the CURRENT claim generation is DISPATCHED, (b) that
--                 permit got there from PERMITTED and passed assert_dispatch_verified (012: marker for the current
--                 generation and payload digest + approval still current), and (c) records.dispatch_state follows the
--                 permit, never leads it.
--
--  F1 dispatch_permits BEFORE INSERT (dispatch_permits_insert_guard): a new permit must be NOT_PERMITTED (begin_apply is
--     the only inserter and always writes NOT_PERMITTED). Anything else is refused with FORBIDDEN_TRANSITION.
--  F2 dispatch_permits BEFORE UPDATE OF state: the 012 guard function is replaced (same trigger, same name). Besides the
--     012 verification it now refuses (i) a permit becoming DISPATCHED from any state but PERMITTED (012 accepted
--     NOT_PERMITTED or CANCELLED_UNDISPATCHED -> DISPATCHED once a marker existed, bypassing issue_permit, the
--     checkpoint, the TTL and the fence of 006) and (ii) a DISPATCHED permit leaving DISPATCHED (a re-dispatch of the same
--     call would be possible). No existing function does either: dispatch_cas moves only PERMITTED -> DISPATCHED /
--     CANCELLED_UNDISPATCHED and every cancel path restricts its WHERE to NOT_PERMITTED / PERMITTED.
--  F3 records BEFORE UPDATE (records_dispatch_state_guard, only when dispatch_state changes): records.dispatch_state may
--     become
--       DISPATCHED only if claim_generation and payload_digest are unchanged by the same statement, the permit of the
--                  current claim generation is DISPATCHED, and assert_dispatch_verified (the 012 function, reused, not
--                  copied) accepts it;
--       PERMITTED  only if the permit of the current claim generation is PERMITTED (issue_permit updates the permit
--                  first and the record second, so the existing path satisfies this; a record can no longer lead its
--                  permit, and a DISPATCHED record can no longer fall back to PERMITTED).
--     The other values (NOT_PERMITTED, CANCELLED_UNDISPATCHED) are written by the cancel / reset paths, which are not an
--     entry to dispatch, and are not restricted here. The trigger is BEFORE UPDATE with a WHEN condition on the column
--     value rather than UPDATE OF dispatch_state, so a change made by any other trigger is covered as well.
--     Functions that write the column and keep working unchanged: issue_permit (PERMITTED), record_call (DISPATCHED),
--     cancel_permit / permit_not_issued / the sweeps / the LOCK_BUSY retry / complete (NOT_PERMITTED,
--     CANCELLED_UNDISPATCHED or an unchanged DISPATCHED).
--  F4 records BEFORE INSERT (records_insert_dispatch_guard): a new change must carry the default dispatch_state
--     NOT_PERMITTED (propose never sets the column). Safe: no function and no test inserts any other value.
--
-- TRUSTED BOUNDARY (named limits). The triggers are not role based: a runtime role cannot reach them (it has no DML on
-- these tables), and the table owner / a superuser running plain DML is stopped too. They are NOT a defence against a
-- principal that is allowed to change the catalog: the table owner (ALTER TABLE ... DISABLE TRIGGER, DROP TRIGGER, a
-- CREATE OR REPLACE of the guard functions) and a superuser (the same, plus SET session_replication_role = replica, plus
-- pg_restore --disable-triggers / a data-only restore into a schema whose triggers already exist, which loads rows through
-- these very triggers). That trust is the same one the whole ledger rests on (events_immutable, 011) and is stated, not
-- hidden. F3 ties records to the permit table; it cannot prove the permit row itself was not forged by that same
-- trusted principal (for example a permit set to PERMITTED by hand without a checkpoint): the permit-to-PERMITTED door
-- is out of the scope of this batch. A full schema + data pg_restore creates triggers after the data and is unaffected.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('013', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012']) THEN
EXECUTE $body$

-- ================================================================== F1: a permit is born NOT_PERMITTED
CREATE OR REPLACE FUNCTION change_ledger.dispatch_permit_insert_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NEW.state IS DISTINCT FROM 'NOT_PERMITTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';        -- fail closed: a permit never starts as PERMITTED / DISPATCHED / cancelled
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS dispatch_permits_insert_guard ON change_ledger.dispatch_permits;
CREATE TRIGGER dispatch_permits_insert_guard BEFORE INSERT ON change_ledger.dispatch_permits
 FOR EACH ROW EXECUTE FUNCTION change_ledger.dispatch_permit_insert_guard();

-- ================================================================== F2: the permit transition guard (012 body + two refusals)
CREATE OR REPLACE FUNCTION change_ledger.dispatch_permit_verified_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF OLD.state='DISPATCHED' AND NEW.state IS DISTINCT FROM 'DISPATCHED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';        -- DISPATCHED is terminal for a permit: no second dispatch of the same call
 END IF;
 IF NEW.state='DISPATCHED' AND OLD.state IS DISTINCT FROM 'DISPATCHED' THEN
  IF OLD.state IS DISTINCT FROM 'PERMITTED' THEN
   RAISE EXCEPTION 'FORBIDDEN_TRANSITION';       -- only an issued permit can be dispatched
  END IF;
  PERFORM change_ledger.assert_dispatch_verified(NEW.change_id,NEW.generation);
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS dispatch_permits_verified_guard ON change_ledger.dispatch_permits;
CREATE TRIGGER dispatch_permits_verified_guard BEFORE UPDATE OF state ON change_ledger.dispatch_permits
 FOR EACH ROW EXECUTE FUNCTION change_ledger.dispatch_permit_verified_guard();

-- ================================================================== F3: records.dispatch_state follows the permit
CREATE OR REPLACE FUNCTION change_ledger.records_dispatch_state_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE pst text;
BEGIN
 IF NEW.dispatch_state IS NOT DISTINCT FROM OLD.dispatch_state THEN RETURN NEW; END IF;
 IF NEW.dispatch_state IN ('PERMITTED','DISPATCHED') THEN
  IF NEW.claim_generation IS DISTINCT FROM OLD.claim_generation
   OR NEW.payload_digest IS DISTINCT FROM OLD.payload_digest THEN
   RAISE EXCEPTION 'FORBIDDEN_TRANSITION';       -- the generation / digest being proven cannot move in the same statement
  END IF;
  SELECT dp.state INTO pst FROM change_ledger.dispatch_permits dp
   WHERE dp.change_id=NEW.change_id AND dp.generation=NEW.claim_generation;
  IF NEW.dispatch_state='PERMITTED' THEN
   IF pst IS DISTINCT FROM 'PERMITTED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
  ELSE
   IF pst IS DISTINCT FROM 'DISPATCHED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
   PERFORM change_ledger.assert_dispatch_verified(NEW.change_id,NEW.claim_generation);   -- the 012 gate, not a copy
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS records_dispatch_state_guard ON change_ledger.records;
CREATE TRIGGER records_dispatch_state_guard BEFORE UPDATE ON change_ledger.records
 FOR EACH ROW WHEN (OLD.dispatch_state IS DISTINCT FROM NEW.dispatch_state)
 EXECUTE FUNCTION change_ledger.records_dispatch_state_guard();

-- ================================================================== F4: a new change starts NOT_PERMITTED
CREATE OR REPLACE FUNCTION change_ledger.records_insert_dispatch_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NEW.dispatch_state IS DISTINCT FROM 'NOT_PERMITTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';        -- a change is never born PERMITTED / DISPATCHED / cancelled
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS records_insert_dispatch_guard ON change_ledger.records;
CREATE TRIGGER records_insert_dispatch_guard BEFORE INSERT ON change_ledger.records
 FOR EACH ROW EXECUTE FUNCTION change_ledger.records_insert_dispatch_guard();

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
