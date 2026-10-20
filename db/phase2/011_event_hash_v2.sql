-- R2/G1 S13 hardening, finding B6 item (m) of docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md: version 2 of the ledger
-- EVENT HASH formula. Applies after 010. Apply ONLY to a verified disposable PostgreSQL database (checksum
-- precondition: living.record_migration). NON-GATING PROTOTYPE: not gate evidence. The statement "no real data and no
-- external anchors exist" is the precondition of the rehash below; the migration refuses to run over a chain that
-- does not verify under the old formula.
--
-- WHY. The v1 hash committed to (prev_hash, seq, change_id, event_type, payload) only. tenant_id, company_id, event_id
-- and recorded_at were stored next to the hash but not covered, so a row relabelled to another scope (when two chains
-- hold identical content), a row whose event_id was swapped, or a row whose recorded time was moved (the time every
-- TTL/sweep decision reads) verified clean.
--
-- THE v2 FORMULA (the single implementation is change_ledger.event_hash_v2; the trigger, verify_chain and this
-- migration all call it, and an external verifier can recompute it from the stored columns):
--   hash = hex(sha256(utf8(
--     'change-ledger-event|v2|' || coalesce(prev_hash,'') || '|' || seq || '|' ||
--     length(tenant_id) || ':' || tenant_id || '|' || length(company_id) || ':' || company_id || '|' ||
--     event_id || '|' || coalesce(change_id,'') || '|' ||
--     length(event_type) || ':' || event_type || '|' ||
--     to_char(recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') || '|' || payload::text )))
--   The leading 'v2' is the hash_version, so a v1 row cannot be passed off as v2 or the other way round. The free-text
--   fields (tenant, company, event_type) are length-prefixed so that no choice of ':' or '|' inside them can shift a
--   boundary; the payload is last (its canonical jsonb text may contain anything). recorded_at is rendered as fixed
--   format UTC text with microseconds (the full timestamptz precision), independent of the session TimeZone.
--
-- WHERE IT IS COMPUTED. The hash is computed in the BEFORE INSERT trigger change_ledger.events_chain_guard (004, last
-- defined in 008), not in append_event: append_event is only the INSERT wrapper of every definer function, and the
-- trigger is the one place that holds the chain lock and the prior head, so a direct INSERT cannot get a different
-- formula. This file replaces the trigger function (it now also forces hash_version=2, a caller value is ignored) and
-- verify_chain (it recomputes by the stored hash_version; version 2 is the only accepted formula: a row of any other
-- version is reported as bad_seq, i.e. an unknown formula is never trusted). append_event is unchanged.
--
-- MIGRATION OF EXISTING ROWS. events.hash_version is added with DEFAULT 1, so every existing row is a v1 row. Then
-- ONE ordered pass per (tenant, company) chain, in seq order, first verifies the row under the v1 formula (a chain that
-- is already broken stops the migration: EVENT_CHAIN_BROKEN_BEFORE_REHASH, nothing is blessed) and then rewrites
-- prev_hash, hash and hash_version=2 from the NEW prior hash, so the chain continues (seq, event_id, change_id,
-- event_type, payload, recorded_at, tenant, company are never touched). The update is a rewrite of immutable rows, so
-- the mechanism is the smallest one that keeps the immutability trigger honest: inside this migration's transaction
-- the table owner runs ALTER TABLE ... DISABLE TRIGGER events_immutable, does the pass, and ENABLEs it again
-- (restored to the default 'O' state). The DDL is transactional (an error anywhere rolls the trigger state back), it
-- takes SHARE ROW EXCLUSIVE on events (no concurrent writer can append during the pass), it needs no session setting
-- and no security-definer maintenance function, so nothing is left behind that could rewrite the log later. The
-- row count of the pass is compared with the table count (EVENT_REHASH_INCOMPLETE), which also catches a migration
-- user whose RLS view hides rows. Finally the column default becomes 2.
--
-- CHECKPOINTS AND ANCHORS (they store head hashes and are immutable too). A checkpoint row carries a SIGNATURE over its
-- payload, and the payload contains head_hash (checkpoint_payload, 007). Rewriting head_hash would leave a stored
-- signature that no longer matches its payload, and re-signing needs the external signer, which a migration must not
-- impersonate. So existing checkpoint rows are NOT rewritten: they stay byte-identical as signed evidence of the v1
-- head, get checkpoints.hash_version=1 (new rows default to 2), and are INVALIDATED as ledger anchors: every consumer
-- (issue_permit, release_hold ANCHOR_GAP) already requires e.hash=k.head_hash of the event at k.ledger_seq, which a v1
-- head can no longer satisfy against a v2 chain, so after this migration the next permit needs a fresh checkpoint of
-- the v2 head (CHECKPOINT_UNAVAILABLE until then). verify_chain does not read checkpoints, so it stays green.
-- check_anchor compares an externally supplied (seq, hash) with the ledger: an anchor recorded under v1 is reported as
-- ANCHOR_GAP (opens the hold) until it is re-issued from the v2 head; none exist (prototype). holds.ext_head_hash of an
-- already open ANCHOR_GAP hold keeps its v1 value and can then only be released through the two-person path. Permits
-- already PERMITTED when this runs lose their checkpoint backing the same way (they expire in 60 seconds).
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('011', ARRAY['001','002','003','004','005','006','007','008','009','010']) THEN
EXECUTE $body$

-- ================================================================== storage
ALTER TABLE change_ledger.events ADD COLUMN IF NOT EXISTS hash_version smallint NOT NULL DEFAULT 1
 CONSTRAINT events_hash_version_check CHECK(hash_version IN (1,2));
ALTER TABLE change_ledger.checkpoints ADD COLUMN IF NOT EXISTS hash_version smallint NOT NULL DEFAULT 1
 CONSTRAINT checkpoints_hash_version_check CHECK(hash_version IN (1,2));

-- ================================================================== the v2 formula (single implementation)
CREATE OR REPLACE FUNCTION change_ledger.event_hash_v2(
 p_prev text, p_seq bigint, p_tenant text, p_company text, p_event_id uuid, p_change_id uuid,
 p_event_type text, p_payload jsonb, p_recorded_at timestamptz
) RETURNS text LANGUAGE sql STABLE AS $fn$
 SELECT encode(sha256(convert_to(
  'change-ledger-event|v2|' || coalesce(p_prev,'') || '|' || p_seq::text || '|' ||
  length(p_tenant)::text || ':' || p_tenant || '|' || length(p_company)::text || ':' || p_company || '|' ||
  p_event_id::text || '|' || coalesce(p_change_id::text,'') || '|' ||
  length(p_event_type)::text || ':' || p_event_type || '|' ||
  to_char(p_recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') || '|' || p_payload::text,
  'UTF8')),'hex')
$fn$;

-- ================================================================== one ordered rehash pass (v1 -> v2)
DO $fn$
DECLARE s record; r record; prior_old text; prior_new text; expect bigint; h1 text; h2 text;
 done bigint := 0; total bigint;
BEGIN
 ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable;
 FOR s IN SELECT DISTINCT e.tenant_id, e.company_id FROM change_ledger.events e ORDER BY 1,2 LOOP
  prior_old := NULL; prior_new := NULL; expect := 1;
  FOR r IN SELECT * FROM change_ledger.events e WHERE e.tenant_id=s.tenant_id AND e.company_id=s.company_id
    ORDER BY e.seq LOOP
   h1 := encode(sha256(convert_to(coalesce(prior_old,'') || ':' || r.seq::text || ':' ||
    coalesce(r.change_id::text,'') || ':' || r.event_type || ':' || r.payload::text,'UTF8')),'hex');
   IF r.hash_version<>1 OR r.seq<>expect OR r.prev_hash IS DISTINCT FROM prior_old OR r.hash<>h1 THEN
    RAISE EXCEPTION 'EVENT_CHAIN_BROKEN_BEFORE_REHASH: tenant=% company=% seq=%',s.tenant_id,s.company_id,r.seq;
   END IF;
   h2 := change_ledger.event_hash_v2(prior_new,r.seq,r.tenant_id,r.company_id,r.event_id,r.change_id,
    r.event_type,r.payload,r.recorded_at);
   UPDATE change_ledger.events e SET prev_hash=prior_new, hash=h2, hash_version=2
    WHERE e.tenant_id=r.tenant_id AND e.company_id=r.company_id AND e.seq=r.seq;
   prior_old := r.hash; prior_new := h2; expect := expect+1; done := done+1;
  END LOOP;
 END LOOP;
 SELECT count(*) INTO total FROM change_ledger.events;
 IF total<>done THEN RAISE EXCEPTION 'EVENT_REHASH_INCOMPLETE: % of % rows',done,total; END IF;
 ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable;
END $fn$;
ALTER TABLE change_ledger.events ALTER COLUMN hash_version SET DEFAULT 2;
ALTER TABLE change_ledger.checkpoints ALTER COLUMN hash_version SET DEFAULT 2;

-- ================================================================== chain trigger and verifier on v2
CREATE OR REPLACE FUNCTION change_ledger.events_chain_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE prior text; prior_seq bigint;
BEGIN
 IF NEW.tenant_id IS NULL OR NEW.company_id IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 PERFORM change_ledger.take_lock('chain', NEW.tenant_id||':'||NEW.company_id);
 SELECT hash, seq INTO prior, prior_seq FROM change_ledger.events
  WHERE tenant_id=NEW.tenant_id AND company_id=NEW.company_id
  ORDER BY seq DESC LIMIT 1;
 NEW.seq := coalesce(prior_seq,0)+1;
 NEW.prev_hash := prior;
 NEW.hash_version := 2;
 NEW.hash := change_ledger.event_hash_v2(prior, NEW.seq, NEW.tenant_id, NEW.company_id, NEW.event_id,
  NEW.change_id, NEW.event_type, NEW.payload, NEW.recorded_at);
 RETURN NEW;
END $fn$;

-- verify_chain: recomputes every event hash of this scope from ALL stored fields it covers (tenant, company, event id,
-- recorded time included) and checks the prev_hash linkage and the 1..n seq continuity. Returns {ok, count, bad_seq};
-- bad_seq is the first row that does not verify (null when ok). Only hash_version 2 is a known formula.
CREATE OR REPLACE FUNCTION change_ledger.verify_chain(t text, c text) RETURNS jsonb
LANGUAGE plpgsql AS $fn$
DECLARE r record; prior text := NULL; expect bigint := 1; cnt bigint := 0; h text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 FOR r IN SELECT * FROM change_ledger.events WHERE tenant_id=t AND company_id=c ORDER BY seq LOOP
  h := CASE WHEN r.hash_version=2 THEN change_ledger.event_hash_v2(prior, r.seq, r.tenant_id, r.company_id,
        r.event_id, r.change_id, r.event_type, r.payload, r.recorded_at) END;
  IF r.seq<>expect OR r.prev_hash IS DISTINCT FROM prior OR h IS NULL OR r.hash<>h THEN
   RETURN jsonb_build_object('ok',false,'count',cnt,'bad_seq',r.seq);
  END IF;
  prior := r.hash; expect := expect+1; cnt := cnt+1;
 END LOOP;
 RETURN jsonb_build_object('ok',true,'count',cnt,'bad_seq',NULL);
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

-- the formula is a pure function: an auditor can recompute any event hash from the stored columns
GRANT EXECUTE ON FUNCTION change_ledger.event_hash_v2(text,bigint,text,text,uuid,uuid,text,jsonb,timestamptz)
 TO auditor_role;

$body$;
END IF;
END $mig$;
COMMIT;
