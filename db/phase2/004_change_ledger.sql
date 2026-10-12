-- R2/G1 S13 skeleton: the change ledger of docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md
-- (revision 6, frozen) sections 3-8, scoped by (tenant, company) as the plan's S13 line requires.
-- Apply ONLY to a verified disposable PostgreSQL database, after 001-003 (checksum precondition
-- below is enforced by living.record_migration, reused unmodified from 001).
-- This is a SKELETON migration: every operation of section 6 exists as one transactional,
-- idempotent, SECURITY DEFINER function with its own guards, but branches explicitly marked
-- "SKELETON:" simplify a sub-case of the full contract (named in the comment) rather than
-- encode every clause of sections 4/4.1/4.2/8. No 1C write happens here or anywhere in this file.
-- Roles (exactly as specified, NOLOGIN, no direct DML - every mutation goes through a
-- SECURITY DEFINER function owned by change_ledger.ledger_owner):
--   ledger_owner, requester_role, approver_role, operator_role, writer_role, worker_role,
--   auditor_role.
-- Scope: change_ledger.set_scope(tenant_id, company_id) is the only entry point, mirroring
-- living.set_scope/assert_scope but keyed by company (not source) because this ledger's scope
-- tuple (S12 section 1) is (tenant, company, organization, base_fingerprint); organization and
-- base_fingerprint are carried as row columns and re-checked per call, not as GUCs, because they
-- are immutable per change (I15) rather than per session.
-- Hash chain: change_ledger.events is append-only (INSERT only, enforced by trigger + no
-- UPDATE/DELETE/TRUNCATE grant to anybody but the owner); each row's hash commits to
-- (prev_hash, seq, change_id, event_type, payload), computed under a per-(tenant,company)
-- advisory lock so seq order and hash order always agree even with concurrent writers.
-- The dispatch CAS (change_ledger.dispatch_cas) is the ONE row-level compare-and-set used by
-- both the writer's own PERMITTED->DISPATCHED transition (issue_permit's caller, via the writer
-- role) and the cancel path (T6c, via worker/operator roles): whichever UPDATE's WHERE clause
-- matches first wins, so exactly one of the two outcomes is possible (S12 T6c).
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('004', ARRAY['001','002','003']) THEN
EXECUTE $body$

-- ================================================================== roles
DO $fn$
DECLARE r text;
BEGIN
 FOREACH r IN ARRAY ARRAY['ledger_owner','requester_role','approver_role','operator_role',
                          'writer_role','worker_role','auditor_role'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE',r);
  ELSIF EXISTS(SELECT 1 FROM pg_catalog.pg_roles
               WHERE rolname=r AND (rolsuper OR rolbypassrls OR rolcanlogin)) THEN
   RAISE EXCEPTION 'LEDGER_ROLE_UNSAFE: %',r;
  END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=current_user AND rolsuper)
  AND NOT pg_catalog.pg_has_role(current_user,'ledger_owner','MEMBER') THEN
  EXECUTE format('GRANT ledger_owner TO %I',current_user);
 END IF;
END $fn$;

CREATE SCHEMA IF NOT EXISTS change_ledger;

-- ================================================================== scope infra
CREATE TABLE IF NOT EXISTS change_ledger.role_scope(
 role_name text NOT NULL CHECK(length(role_name)>0),
 tenant_id text NOT NULL, company_id text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS role_scope_uniq
 ON change_ledger.role_scope(role_name,tenant_id,company_id);

CREATE OR REPLACE FUNCTION change_ledger.caller_role() RETURNS text
LANGUAGE sql STABLE AS $fn$
 SELECT CASE WHEN coalesce(current_setting('role', true),'none') IN ('none','')
  THEN session_user::text ELSE current_setting('role') END
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.row_in_scope(t text, c text) RETURNS boolean
LANGUAGE sql STABLE AS $fn$
 SELECT t IS NOT NULL AND c IS NOT NULL
  AND t = nullif(current_setting('change_ledger.tenant_id',true),'')
  AND c = nullif(current_setting('change_ledger.company_id',true),'')
  AND EXISTS(SELECT 1 FROM change_ledger.role_scope rs
   WHERE rs.tenant_id=t AND rs.company_id=c
    AND pg_has_role(current_user, rs.role_name::name, 'USAGE'))
$fn$;

-- The only supported way to set scope; grants are checked here and re-checked by every
-- definer API under a row lock (change_ledger.recheck_scope_locked) so a mid-call revocation
-- is honoured.
CREATE OR REPLACE FUNCTION change_ledger.set_scope(t text, c text) RETURNS void
LANGUAGE plpgsql AS $fn$
DECLARE who text;
BEGIN
 IF t IS NULL OR c IS NULL OR t='' OR c='' THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 who := change_ledger.caller_role();
 IF NOT EXISTS(SELECT 1 FROM change_ledger.role_scope rs
   WHERE rs.tenant_id=t AND rs.company_id=c
    AND pg_has_role(who::name, rs.role_name::name, 'USAGE')) THEN
  RAISE EXCEPTION 'SCOPE_NOT_GRANTED';
 END IF;
 PERFORM set_config('change_ledger.tenant_id',t,true);
 PERFORM set_config('change_ledger.company_id',c,true);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.assert_scope(t text, c text) RETURNS void
LANGUAGE plpgsql STABLE AS $fn$
BEGIN
 IF t IS NULL OR c IS NULL
  OR t IS DISTINCT FROM nullif(current_setting('change_ledger.tenant_id', true), '')
  OR c IS DISTINCT FROM nullif(current_setting('change_ledger.company_id', true), '')
  OR NOT change_ledger.row_in_scope(t,c) THEN
  RAISE EXCEPTION 'SCOPE_NOT_GRANTED';
 END IF;
END $fn$;

-- Re-checked by every mutating API immediately after it takes its first row lock, so a
-- revocation that committed while the API waited for the lock is honoured (living's pattern).
CREATE OR REPLACE FUNCTION change_ledger.recheck_scope_locked(t text, c text) RETURNS void
LANGUAGE plpgsql VOLATILE AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.add_role_scope(p_role text, t text, c text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NOT pg_has_role(change_ledger.caller_role()::name,'ledger_owner','USAGE') THEN
  RAISE EXCEPTION 'NOT_OWNER';
 END IF;
 IF p_role IS NULL OR p_role='' OR t IS NULL OR c IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_role) THEN
  RAISE EXCEPTION 'ROLE_NOT_FOUND';
 END IF;
 INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id)
  VALUES(p_role,t,c) ON CONFLICT DO NOTHING;
END $fn$;

-- Shared immutability trigger (events/approvals/checkpoints/cosigns: INSERT-only objects).
CREATE OR REPLACE FUNCTION change_ledger.reject_immutable_mutation() RETURNS trigger
LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'IMMUTABLE_LEDGER'; END $fn$;

-- ================================================================== targets / base fingerprint registry (CT4)
CREATE TABLE IF NOT EXISTS change_ledger.targets(
 tenant_id text NOT NULL, company_id text NOT NULL,
 base_fingerprint text NOT NULL CHECK(length(base_fingerprint)>0),
 organization_ref text NOT NULL CHECK(length(organization_ref)>0),
 target_class text NOT NULL CHECK(target_class IN ('DISPOSABLE_CLONE','STAGING','PRODUCTION')),
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
 epoch bigint NOT NULL DEFAULT 0 CHECK(epoch>=0),
 PRIMARY KEY(tenant_id,company_id,base_fingerprint)
);

-- ================================================================== kill switch (CT9)
CREATE TABLE IF NOT EXISTS change_ledger.kill_switch_state(
 tenant_id text NOT NULL, company_id text NOT NULL,
 mode text NOT NULL DEFAULT 'OFF' CHECK(mode IN ('OFF','STOP_ADMIT','STOP_EFFECTS','REVOKE')),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_by text,
 PRIMARY KEY(tenant_id,company_id)
);

-- ================================================================== append-only event log + hash chain (CT5)
CREATE TABLE IF NOT EXISTS change_ledger.events(
 tenant_id text NOT NULL, company_id text NOT NULL,
 event_id uuid NOT NULL DEFAULT gen_random_uuid(),
 change_id uuid,
 seq bigint GENERATED ALWAYS AS IDENTITY,
 event_type text NOT NULL CHECK(length(event_type)>0),
 payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(octet_length(payload::text)<=65536),
 prev_hash text,
 hash text NOT NULL CHECK(hash ~ '^[a-f0-9]{64}$'),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,event_id),
 UNIQUE(tenant_id,company_id,seq)
);
CREATE INDEX IF NOT EXISTS events_change_idx ON change_ledger.events(tenant_id,company_id,change_id);

-- Computes hash = sha256(prev_hash || ':' || seq || ':' || change_id || ':' || event_type ||
-- ':' || payload) under a per-(tenant,company) advisory xact lock, so seq assignment (IDENTITY,
-- which is NOT itself serialized across sessions) and hash chaining always agree with the
-- actually-committed prior row, matching the whole-file chain invariant tested by
-- tests/phase2/test_g1_restore.py-style checks for 001-003.
CREATE OR REPLACE FUNCTION change_ledger.events_chain_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE prior text;
BEGIN
 IF NEW.tenant_id IS NULL OR NEW.company_id IS NULL THEN RAISE EXCEPTION 'INVALID_ARGUMENT'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id||':'||NEW.company_id,0));
 SELECT hash INTO prior FROM change_ledger.events
  WHERE tenant_id=NEW.tenant_id AND company_id=NEW.company_id
  ORDER BY seq DESC LIMIT 1;
 NEW.prev_hash := prior;
 NEW.hash := encode(sha256(convert_to(
  coalesce(prior,'') || ':' || NEW.change_id::text || ':' || NEW.event_type || ':' ||
  NEW.payload::text,'UTF8')),'hex');
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS events_chain ON change_ledger.events;
CREATE TRIGGER events_chain BEFORE INSERT ON change_ledger.events
 FOR EACH ROW EXECUTE FUNCTION change_ledger.events_chain_guard();
DROP TRIGGER IF EXISTS events_immutable ON change_ledger.events;
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON change_ledger.events
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();
DROP TRIGGER IF EXISTS events_no_truncate ON change_ledger.events;
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON change_ledger.events
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

-- Internal helper: every definer function appends its own events through this (never a raw
-- INSERT from outside the function body), so every state transition is on the chain.
CREATE OR REPLACE FUNCTION change_ledger.append_event(
 t text, c text, p_change_id uuid, p_event_type text, p_payload jsonb
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE eid uuid;
BEGIN
 INSERT INTO change_ledger.events(tenant_id,company_id,change_id,event_type,payload)
 VALUES(t,c,p_change_id,p_event_type,coalesce(p_payload,'{}'::jsonb))
 RETURNING event_id INTO eid;
 RETURN eid;
END $fn$;

-- ================================================================== change record (S12 section 4 dimensions)
CREATE TABLE IF NOT EXISTS change_ledger.records(
 change_id uuid PRIMARY KEY,
 tenant_id text NOT NULL, company_id text NOT NULL,
 base_fingerprint text NOT NULL, organization_ref text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('CREATE_DRAFT','UPDATE_DRAFT','POST','UNPOST')),
 requester text NOT NULL CHECK(length(requester)>0),
 request_id text NOT NULL CHECK(length(request_id)>0),
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 target_ref text, target_version text,
 parent_change_id uuid REFERENCES change_ledger.records(change_id),
 repair_for uuid REFERENCES change_ledger.records(change_id),
 claim_generation bigint NOT NULL DEFAULT 0 CHECK(claim_generation>=0),
 lifecycle text NOT NULL DEFAULT 'PROPOSED'
  CHECK(lifecycle IN ('PROPOSED','VALIDATED','REJECTED','EXPIRED_QUEUED','DUPLICATE_PARKED')),
 authorization_state text NOT NULL DEFAULT 'NONE'
  CHECK(authorization_state IN ('NONE','APPROVED','CLAIMED','VOIDED','REVOKED','EXPIRED')),
 execution_state text NOT NULL DEFAULT 'NOT_STARTED'
  CHECK(execution_state IN ('NOT_STARTED','APPLYING','APPLY_UNKNOWN','APPLIED','FAILED_APPLY',
   'TRIAGE_REQUIRED','ROLLBACK_REFUSED')),
 verification_state text NOT NULL DEFAULT 'NOT_VERIFIED'
  CHECK(verification_state IN ('NOT_VERIFIED','VERIFIED','FAILED_VERIFY')),
 call_ownership text NOT NULL DEFAULT 'NONE'
  CHECK(call_ownership IN ('NONE','PROVEN_FINISHED','POSSIBLY_EXECUTING')),
 attribution text NOT NULL DEFAULT 'NOT_APPLICABLE'
  CHECK(attribution IN ('NOT_APPLICABLE','PROVEN','UNPROVEN_OPERATOR_ATTESTED')),
 effect_known text CHECK(effect_known IN ('YES','NO','UNKNOWN')),
 reservation_state text NOT NULL DEFAULT 'NONE'
  CHECK(reservation_state IN ('NONE','RESERVED','CONSUMED','RELEASED')),
 dispatch_state text NOT NULL DEFAULT 'NOT_PERMITTED'
  CHECK(dispatch_state IN ('NOT_PERMITTED','PERMITTED','CANCELLED_UNDISPATCHED','DISPATCHED')),
 auth_epoch_at_proposal bigint NOT NULL,
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,company_id,base_fingerprint) REFERENCES change_ledger.targets,
 CHECK(expires_at>created_at)
);
-- Logical key (T1): (requester, kind, scope tuple, request_id) is unique; same key with a
-- different payload_digest is IDEMPODENCY_CONFLICT at the application layer (checked in
-- change_ledger.propose before the INSERT, which this index then also enforces mechanically).
CREATE UNIQUE INDEX IF NOT EXISTS records_logical_key
 ON change_ledger.records(tenant_id,company_id,requester,kind,base_fingerprint,
  organization_ref,request_id);
CREATE INDEX IF NOT EXISTS records_scope_idx ON change_ledger.records(tenant_id,company_id);

-- ================================================================== locks, lease, holds (section 4.1)
CREATE TABLE IF NOT EXISTS change_ledger.target_locks(
 tenant_id text NOT NULL, company_id text NOT NULL,
 base_fingerprint text NOT NULL, target_ref text NOT NULL,
 owner_change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 acquired_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,base_fingerprint,target_ref)
);
CREATE TABLE IF NOT EXISTS change_ledger.key_locks(
 tenant_id text NOT NULL, company_id text NOT NULL,
 base_fingerprint text NOT NULL, key_hash text NOT NULL CHECK(key_hash ~ '^[a-f0-9]{64}$'),
 owner_change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 acquired_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,base_fingerprint,key_hash)
);
CREATE TABLE IF NOT EXISTS change_ledger.writer_leases(
 tenant_id text NOT NULL, company_id text NOT NULL, base_fingerprint text NOT NULL,
 owner_change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 acquired_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,base_fingerprint)
);
CREATE TABLE IF NOT EXISTS change_ledger.holds(
 hold_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL, base_fingerprint text NOT NULL,
 cause text NOT NULL CHECK(cause IN ('CALL_OWNERSHIP','ANCHOR_GAP','FAILED_VERIFY_HALT','RLC_UNCLEAN')),
 change_id uuid REFERENCES change_ledger.records(change_id),
 opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 released_at timestamptz,
 release_evidence jsonb
);
CREATE INDEX IF NOT EXISTS holds_open_idx ON change_ledger.holds(tenant_id,company_id,base_fingerprint)
 WHERE released_at IS NULL;

-- Repair handoff (S12 section 4.2): moves a target lock from one owner to another in the
-- caller's own transaction, atomically with whatever else that transaction does; the caller
-- (claim for T5 repair claim, or the common handback rule) is responsible for proving the
-- expected current owner first. Returns false (no exception) when the expected owner does not
-- match, so the caller can raise its own contract-specific code.
CREATE OR REPLACE FUNCTION change_ledger.handoff_target_lock(
 t text, c text, bf text, p_target text, p_expected_owner uuid, p_new_owner uuid
) RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE n integer;
BEGIN
 UPDATE change_ledger.target_locks SET owner_change_id=p_new_owner
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=bf AND target_ref=p_target
   AND owner_change_id=p_expected_owner;
 GET DIAGNOSTICS n = ROW_COUNT;
 RETURN n=1;
END $fn$;

-- ================================================================== claim tokens (section 4, T5)
CREATE TABLE IF NOT EXISTS change_ledger.claim_tokens(
 token_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 generation bigint NOT NULL CHECK(generation>0),
 state text NOT NULL DEFAULT 'ISSUED' CHECK(state IN ('ISSUED','CONSUMED','SUPERSEDED','REVOKED')),
 issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(change_id,generation)
);

-- ================================================================== dispatch permits + CAS (T6p/T6c, S12-M01)
CREATE TABLE IF NOT EXISTS change_ledger.dispatch_permits(
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 generation bigint NOT NULL,
 state text NOT NULL DEFAULT 'NOT_PERMITTED'
  CHECK(state IN ('NOT_PERMITTED','PERMITTED','CANCELLED_UNDISPATCHED','DISPATCHED')),
 checkpoint_seq bigint,
 issued_at timestamptz,
 expires_at timestamptz,
 PRIMARY KEY(change_id,generation)
);

-- The ONE row-level compare-and-set for the dispatch dimension: used by issue_permit's caller
-- (the writer, moving PERMITTED -> DISPATCHED immediately before its 1C call) and by the cancel
-- path (T6c, moving PERMITTED -> CANCELLED_UNDISPATCHED). Whichever UPDATE commits first wins
-- the row; the other sees 0 rows changed and returns false. Never raises.
CREATE OR REPLACE FUNCTION change_ledger.dispatch_cas(
 p_change_id uuid, p_generation bigint, p_from text, p_to text
) RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE n integer;
BEGIN
 UPDATE change_ledger.dispatch_permits SET state=p_to
  WHERE change_id=p_change_id AND generation=p_generation AND state=p_from;
 GET DIAGNOSTICS n = ROW_COUNT;
 RETURN n=1;
END $fn$;

-- ================================================================== budget grants + reservations (CT13)
CREATE TABLE IF NOT EXISTS change_ledger.grants(
 grant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL, currency text NOT NULL CHECK(length(currency)=3),
 amount_limit numeric(18,2) NOT NULL CHECK(amount_limit>=0),
 count_limit integer NOT NULL CHECK(count_limit>=0),
 post_count_limit integer NOT NULL CHECK(post_count_limit>=0),
 window_start timestamptz NOT NULL, window_end timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
 CHECK(window_end>window_start)
);
CREATE TABLE IF NOT EXISTS change_ledger.reservations(
 change_id uuid PRIMARY KEY REFERENCES change_ledger.records(change_id),
 grant_id uuid NOT NULL REFERENCES change_ledger.grants(grant_id),
 amount numeric(18,2) NOT NULL DEFAULT 0 CHECK(amount>=0),
 counts_create_update boolean NOT NULL DEFAULT false,
 counts_post boolean NOT NULL DEFAULT false,
 state text NOT NULL DEFAULT 'RESERVED' CHECK(state IN ('RESERVED','CONSUMED','RELEASED')),
 reserved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- ================================================================== approvals (section 2/4, T4)
CREATE TABLE IF NOT EXISTS change_ledger.approval_nonces(
 nonce text PRIMARY KEY, change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 approver text NOT NULL,
 state text NOT NULL DEFAULT 'ISSUED' CHECK(state IN ('ISSUED','CONSUMED','EXPIRED')),
 issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS change_ledger.approvals(
 approval_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 approver text NOT NULL, nonce text NOT NULL REFERENCES change_ledger.approval_nonces(nonce),
 digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
 decision text NOT NULL CHECK(decision IN ('APPROVE','REJECT')),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DROP TRIGGER IF EXISTS approvals_immutable ON change_ledger.approvals;
CREATE TRIGGER approvals_immutable BEFORE UPDATE OR DELETE ON change_ledger.approvals
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

-- Two-person operator_resolve (T16): a witness co-signs first, under their OWN authenticated
-- identity; operator_resolve then consumes exactly one unconsumed cosign whose signer differs
-- from the operator caller (section 2: the operator and the witness are never the same person).
CREATE TABLE IF NOT EXISTS change_ledger.witness_cosigns(
 cosign_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 signer text NOT NULL,
 completion_proof jsonb NOT NULL,
 signed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 consumed_at timestamptz
);
DROP TRIGGER IF EXISTS witness_cosigns_no_delete ON change_ledger.witness_cosigns;
CREATE TRIGGER witness_cosigns_no_delete BEFORE DELETE ON change_ledger.witness_cosigns
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

-- ================================================================== checkpoints (CT5, R-04)
CREATE TABLE IF NOT EXISTS change_ledger.checkpoints(
 tenant_id text NOT NULL, company_id text NOT NULL,
 seq bigint GENERATED ALWAYS AS IDENTITY,
 head_hash text NOT NULL CHECK(head_hash ~ '^[a-f0-9]{64}$'),
 signer_key_id text NOT NULL CHECK(length(signer_key_id)>0),
 signature text NOT NULL CHECK(length(signature)>0),
 written_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,seq)
);
DROP TRIGGER IF EXISTS checkpoints_immutable ON change_ledger.checkpoints;
CREATE TRIGGER checkpoints_immutable BEFORE UPDATE OR DELETE ON change_ledger.checkpoints
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();

-- ================================================================== operations (section 6)

-- T1: propose. Idempotent on logical_key: same key + same digest returns the existing change_id;
-- same key + different digest raises IDEMPOTENCY_CONFLICT (S12 T1 note).
CREATE OR REPLACE FUNCTION change_ledger.propose(
 t text, c text, p_change_id uuid, p_kind text, p_base_fingerprint text, p_organization_ref text,
 p_requester text, p_request_id text, p_payload_digest text, p_target_ref text,
 p_target_version text, p_parent_change_id uuid, p_expires_at timestamptz
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE existing change_ledger.records%ROWTYPE; epoch bigint; tgt_status text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_kind IS NULL OR p_base_fingerprint IS NULL
  OR p_organization_ref IS NULL OR p_requester IS NULL OR p_request_id IS NULL
  OR p_payload_digest IS NULL OR p_expires_at IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT status, epoch INTO tgt_status, epoch FROM change_ledger.targets
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=p_base_fingerprint FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tgt_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 SELECT * INTO existing FROM change_ledger.records
  WHERE tenant_id=t AND company_id=c AND requester=p_requester AND kind=p_kind
   AND base_fingerprint=p_base_fingerprint AND organization_ref=p_organization_ref
   AND request_id=p_request_id;
 IF FOUND THEN
  IF existing.payload_digest IS DISTINCT FROM p_payload_digest THEN
   RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
  END IF;
  RETURN existing.change_id;
 END IF;
 INSERT INTO change_ledger.records(
  change_id,tenant_id,company_id,base_fingerprint,organization_ref,kind,requester,request_id,
  payload_digest,target_ref,target_version,parent_change_id,auth_epoch_at_proposal,expires_at)
 VALUES(p_change_id,t,c,p_base_fingerprint,p_organization_ref,p_kind,p_requester,p_request_id,
  p_payload_digest,p_target_ref,p_target_version,p_parent_change_id,epoch,p_expires_at);
 PERFORM change_ledger.append_event(t,c,p_change_id,'PROPOSED',
  jsonb_build_object('kind',p_kind,'payload_digest',p_payload_digest));
 RETURN p_change_id;
END $fn$;

-- T2: validate. SKELETON: business-key duplicate detection and budget pre-check are left to the
-- caller-supplied p_duplicate flag / p_budget_ok flag (the real policy engine is S12 scope, not
-- this migration); this function only records the resulting lifecycle transition idempotently.
CREATE OR REPLACE FUNCTION change_ledger.validate(
 t text, c text, p_change_id uuid, p_duplicate boolean, p_budget_ok boolean
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle = 'VALIDATED' THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle = 'DUPLICATE_PARKED' THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle <> 'PROPOSED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF NOT p_budget_ok THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 UPDATE change_ledger.records SET
  lifecycle=CASE WHEN p_duplicate THEN 'DUPLICATE_PARKED' ELSE 'VALIDATED' END,
  updated_at=clock_timestamp()
 WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
 RETURNING lifecycle INTO rec.lifecycle;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VALIDATED',
  jsonb_build_object('lifecycle',rec.lifecycle));
 RETURN rec.lifecycle;
END $fn$;

-- T4/T3: approve / reject. approver_role only; approver must differ from requester (identity
-- check on the authenticated caller, never a parameter, per section 2); the nonce is consumed
-- exactly once.
CREATE OR REPLACE FUNCTION change_ledger.approve(
 t text, c text, p_change_id uuid, p_nonce text, p_digest text
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; approver text; nonce change_ledger.approval_nonces%ROWTYPE;
 aid uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 approver := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle <> 'VALIDATED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF approver IS NOT DISTINCT FROM rec.requester
  OR pg_has_role(approver::name, rec.requester::name, 'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 SELECT * INTO nonce FROM change_ledger.approval_nonces
  WHERE nonce=p_nonce AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nonce.state<>'ISSUED' THEN RAISE EXCEPTION 'APPROVAL_NONCE_INVALID'; END IF;
 IF nonce.expires_at<=clock_timestamp() THEN
  UPDATE change_ledger.approval_nonces SET state='EXPIRED' WHERE nonce=p_nonce;
  RAISE EXCEPTION 'APPROVAL_EXPIRED';
 END IF;
 UPDATE change_ledger.approval_nonces SET state='CONSUMED' WHERE nonce=p_nonce;
 INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision)
 VALUES(p_change_id,approver,p_nonce,p_digest,'APPROVE') RETURNING approval_id INTO aid;
 UPDATE change_ledger.records SET authorization_state='APPROVED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVED',
  jsonb_build_object('approval_id',aid,'digest',p_digest));
 RETURN aid;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.reject(
 t text, c text, p_change_id uuid, p_nonce text
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; approver text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 approver := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 UPDATE change_ledger.approval_nonces SET state='CONSUMED'
  WHERE nonce=p_nonce AND change_id=p_change_id AND state='ISSUED';
 INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision)
 VALUES(p_change_id,approver,p_nonce,repeat('0',64),'REJECT');
 UPDATE change_ledger.records SET lifecycle='REJECTED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'REJECTED','{}'::jsonb);
 RETURN 'REJECTED';
END $fn$;

-- T5: claim. requester_role only (own changes). Acquires target lock, key lock and writer
-- lease, reserves budget, all in this one transaction; bumps claim_generation. SKELETON: the
-- repair-UNPOST exception of section 4.2 is handled by change_ledger.claim_repair below rather
-- than inlined here, to keep the common path readable; both share handoff_target_lock.
CREATE OR REPLACE FUNCTION change_ledger.claim(
 t text, c text, p_change_id uuid, p_key_hash text, p_grant_id uuid, p_amount numeric,
 p_counts_create_update boolean, p_counts_post boolean
) RETURNS change_ledger.claim_tokens LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; requester text; gen bigint; tok change_ledger.claim_tokens%ROWTYPE;
 g change_ledger.grants%ROWTYPE; switch text; open_hold boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 requester := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF requester IS DISTINCT FROM rec.requester THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state <> 'APPROVED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 SELECT mode INTO switch FROM change_ledger.kill_switch_state WHERE tenant_id=t AND company_id=c;
 IF coalesce(switch,'OFF') IN ('STOP_ADMIT','STOP_EFFECTS','REVOKE') THEN
  RAISE EXCEPTION 'KILL_SWITCH_ACTIVE';
 END IF;
 SELECT EXISTS(SELECT 1 FROM change_ledger.holds
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=rec.base_fingerprint
   AND released_at IS NULL) INTO open_hold;
 IF open_hold THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 IF rec.parent_change_id IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.records
    WHERE change_id=rec.parent_change_id AND verification_state='VERIFIED') THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 END IF;
 IF p_grant_id IS NOT NULL THEN
  SELECT * INTO g FROM change_ledger.grants WHERE grant_id=p_grant_id FOR UPDATE;
  IF NOT FOUND OR g.status<>'ACTIVE' OR clock_timestamp()<g.window_start
   OR clock_timestamp()>=g.window_end THEN
   RAISE EXCEPTION 'BUDGET_EXCEEDED';
  END IF;
  INSERT INTO change_ledger.reservations(change_id,grant_id,amount,counts_create_update,counts_post)
  VALUES(p_change_id,p_grant_id,coalesce(p_amount,0),coalesce(p_counts_create_update,false),
   coalesce(p_counts_post,false));
 END IF;
 INSERT INTO change_ledger.target_locks(tenant_id,company_id,base_fingerprint,target_ref,owner_change_id)
 VALUES(t,c,rec.base_fingerprint,coalesce(rec.target_ref,p_change_id::text),p_change_id);
 IF p_key_hash IS NOT NULL THEN
  INSERT INTO change_ledger.key_locks(tenant_id,company_id,base_fingerprint,key_hash,owner_change_id)
  VALUES(t,c,rec.base_fingerprint,p_key_hash,p_change_id);
 END IF;
 INSERT INTO change_ledger.writer_leases(tenant_id,company_id,base_fingerprint,owner_change_id)
 VALUES(t,c,rec.base_fingerprint,p_change_id);
 gen := rec.claim_generation + 1;
 UPDATE change_ledger.records SET authorization_state='CLAIMED', execution_state='NOT_STARTED',
  claim_generation=gen, reservation_state=CASE WHEN p_grant_id IS NOT NULL THEN 'RESERVED'
   ELSE reservation_state END, updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 INSERT INTO change_ledger.claim_tokens(change_id,generation) VALUES(p_change_id,gen)
  RETURNING * INTO tok;
 PERFORM change_ledger.append_event(t,c,p_change_id,'CLAIMED',
  jsonb_build_object('generation',gen,'token_id',tok.token_id));
 RETURN tok;
END $fn$;

-- T5x / repair handback common path: releases locks/lease/reservation and supersedes the
-- token. For a change with repair_for set, the target lock is handed back to the parent
-- (section 4.2 common handback rule) instead of being dropped.
CREATE OR REPLACE FUNCTION change_ledger.release_claim(
 t text, c text, p_token_id uuid
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE; caller text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 caller := change_ledger.caller_role();
 SELECT * INTO tok FROM change_ledger.claim_tokens WHERE token_id=p_token_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=tok.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF caller IS DISTINCT FROM rec.requester AND NOT pg_has_role(caller::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF tok.state<>'ISSUED' THEN RETURN tok.state; END IF;
 UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE token_id=p_token_id;
 IF rec.repair_for IS NOT NULL THEN
  PERFORM change_ledger.handoff_target_lock(t,c,rec.base_fingerprint,
   coalesce(rec.target_ref,rec.change_id::text), rec.change_id, rec.repair_for);
 ELSE
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint
   AND target_ref=coalesce(rec.target_ref,rec.change_id::text) AND owner_change_id=rec.change_id;
 END IF;
 DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=rec.change_id;
 DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=rec.change_id;
 UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=rec.change_id AND state='RESERVED';
 UPDATE change_ledger.records SET
  authorization_state=CASE WHEN rec.expires_at<=clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
  execution_state='NOT_STARTED',
  reservation_state=CASE WHEN reservation_state='RESERVED' THEN 'RELEASED' ELSE reservation_state END,
  updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'CLAIM_RELEASED','{}'::jsonb);
 RETURN 'SUPERSEDED';
END $fn$;

-- T6: begin_apply. One atomic section: re-checks target version/epoch, commits the APPLYING
-- event and a NOT_PERMITTED dispatch row in the same transaction (the permit comes later, T6p).
CREATE OR REPLACE FUNCTION change_ledger.begin_apply(
 t text, c text, p_token_id uuid, p_call_id uuid, p_writer_host text, p_onec_session text
) RETURNS change_ledger.claim_tokens LANGUAGE plpgsql AS $fn$
DECLARE tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO tok FROM change_ledger.claim_tokens WHERE token_id=p_token_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=tok.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tok.generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF tok.state='CONSUMED' THEN
  -- Replay: return the existing ticket while still current and not yet DISPATCHED.
  IF rec.dispatch_state<>'DISPATCHED' THEN RETURN tok; END IF;
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 IF tok.state<>'ISSUED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.authorization_state<>'CLAIMED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 UPDATE change_ledger.claim_tokens SET state='CONSUMED' WHERE token_id=p_token_id;
 UPDATE change_ledger.records SET execution_state='APPLYING', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
 INSERT INTO change_ledger.dispatch_permits(change_id,generation,state)
 VALUES(rec.change_id,tok.generation,'NOT_PERMITTED')
 ON CONFLICT(change_id,generation) DO NOTHING;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'APPLYING',
  jsonb_build_object('call_id',p_call_id,'writer_host',p_writer_host,'onec_session',p_onec_session));
 RETURN tok;
END $fn$;

-- T6p: issue_permit. Requires a checkpoint already written (checked by checkpoint_seq
-- existing) covering this head; sets dispatch = PERMITTED. The writer then runs its own
-- PERMITTED -> DISPATCHED CAS (change_ledger.dispatch_cas) immediately before the 1C call.
CREATE OR REPLACE FUNCTION change_ledger.issue_permit(
 t text, c text, p_change_id uuid, p_generation bigint, p_checkpoint_seq bigint
) RETURNS change_ledger.dispatch_permits LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE; switch text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT mode INTO switch FROM change_ledger.kill_switch_state WHERE tenant_id=t AND company_id=c;
 IF coalesce(switch,'OFF') IN ('STOP_ADMIT','STOP_EFFECTS','REVOKE') THEN
  RAISE EXCEPTION 'KILL_SWITCH_ACTIVE';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.checkpoints
   WHERE tenant_id=t AND company_id=c AND seq=p_checkpoint_seq) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 UPDATE change_ledger.dispatch_permits SET state='PERMITTED', checkpoint_seq=p_checkpoint_seq,
  issued_at=clock_timestamp(), expires_at=clock_timestamp()+interval '60 seconds'
  WHERE change_id=p_change_id AND generation=p_generation AND state='NOT_PERMITTED'
 RETURNING * INTO dp;
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 UPDATE change_ledger.records SET dispatch_state='PERMITTED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PERMITTED',
  jsonb_build_object('generation',p_generation,'checkpoint_seq',p_checkpoint_seq));
 RETURN dp;
END $fn$;

-- T7/T8/T9: complete. writer_role only. The outcome is chosen by the evidence class, never by
-- a caller flag (S12 section 6): p_outcome in {SUCCESS, PRE_WRITE_REFUSAL, UNKNOWN}; a
-- PRE_WRITE_REFUSAL carries p_no_effect_proof (required, S12-M02).
CREATE OR REPLACE FUNCTION change_ledger.complete(
 t text, c text, p_change_id uuid, p_generation bigint, p_outcome text,
 p_evidence jsonb, p_no_effect_proof jsonb DEFAULT NULL
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_exec text; new_res text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_outcome NOT IN ('SUCCESS','PRE_WRITE_REFUSAL','UNKNOWN') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN
  IF rec.execution_state IN ('APPLIED','APPLY_UNKNOWN','FAILED_APPLY') THEN RETURN rec.execution_state; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_outcome='SUCCESS' THEN
  new_exec:='APPLIED'; new_res:='CONSUMED';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='PROVEN_FINISHED',
   attribution='PROVEN', reservation_state=new_res, updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
 ELSIF p_outcome='PRE_WRITE_REFUSAL' THEN
  IF p_no_effect_proof IS NULL THEN RAISE EXCEPTION 'WRITE_REFUSED'; END IF;
  new_exec:='FAILED_APPLY'; new_res:='RELEASED';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state=new_res,
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 ELSE
  new_exec:='APPLY_UNKNOWN'; new_res:=rec.reservation_state;
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='POSSIBLY_EXECUTING',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
  VALUES(t,c,rec.base_fingerprint,'CALL_OWNERSHIP',p_change_id);
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'COMPLETE_'||p_outcome,coalesce(p_evidence,'{}'::jsonb));
 RETURN new_exec;
END $fn$;

-- recover_sweep: worker_role, ledger-driven, idempotent. SKELETON: handles claim TTL (T5x) and
-- permit TTL (T6r/T6c via dispatch_cas) expiry; approval TTL (T3 expire) and stuck-verification
-- retry scheduling are left as straightforward extensions of the same pattern and are not all
-- enumerated here.
CREATE OR REPLACE FUNCTION change_ledger.recover_sweep(t text, c text) RETURNS integer
LANGUAGE plpgsql AS $fn$
DECLARE n integer := 0; tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE;
 dp change_ledger.dispatch_permits%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 FOR tok IN SELECT ct.* FROM change_ledger.claim_tokens ct
   JOIN change_ledger.records r ON r.change_id=ct.change_id
  WHERE r.tenant_id=t AND r.company_id=c AND ct.state='ISSUED'
   AND ct.issued_at<=clock_timestamp()-interval '120 seconds' LOOP
  PERFORM change_ledger.release_claim(t,c,tok.token_id);
  n := n+1;
 END LOOP;
 FOR dp IN SELECT * FROM change_ledger.dispatch_permits
  WHERE state='PERMITTED' AND expires_at<=clock_timestamp() LOOP
  IF change_ledger.dispatch_cas(dp.change_id,dp.generation,'PERMITTED','CANCELLED_UNDISPATCHED') THEN
   SELECT * INTO rec FROM change_ledger.records WHERE change_id=dp.change_id FOR UPDATE;
   UPDATE change_ledger.records SET authorization_state='APPROVED', execution_state='NOT_STARTED',
    dispatch_state='CANCELLED_UNDISPATCHED', updated_at=clock_timestamp()
    WHERE change_id=dp.change_id;
   PERFORM change_ledger.append_event(t,c,dp.change_id,'PERMIT_CANCELLED','{}'::jsonb);
   n := n+1;
  END IF;
 END LOOP;
 RETURN n;
END $fn$;

-- T10/T11/T12: resolve_unknown. worker_role only. p_found distinguishes T10 (found, needs
-- p_attributed) from T11 (absent); TRIAGE_REQUIRED (T12) is reached either explicitly
-- (p_found=NULL meaning "not yet resolvable") or when found-but-unattributed.
CREATE OR REPLACE FUNCTION change_ledger.resolve_unknown(
 t text, c text, p_change_id uuid, p_observation jsonb, p_found boolean, p_attributed boolean DEFAULT false
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_exec text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'APPLY_UNKNOWN' THEN
  IF rec.execution_state IN ('APPLIED','FAILED_APPLY','TRIAGE_REQUIRED') THEN RETURN rec.execution_state; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_found IS NULL THEN
  new_exec:='TRIAGE_REQUIRED';
  UPDATE change_ledger.records SET execution_state=new_exec, updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSIF p_found AND p_attributed THEN
  new_exec:='APPLIED';
  UPDATE change_ledger.records SET execution_state=new_exec, attribution='PROVEN',
   call_ownership='PROVEN_FINISHED', reservation_state='CONSUMED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
  UPDATE change_ledger.holds SET released_at=clock_timestamp(), release_evidence=p_observation
   WHERE change_id=p_change_id AND cause='CALL_OWNERSHIP' AND released_at IS NULL;
 ELSIF p_found AND NOT p_attributed THEN
  new_exec:='TRIAGE_REQUIRED';
  UPDATE change_ledger.records SET execution_state=new_exec, updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSE
  new_exec:='FAILED_APPLY';
  UPDATE change_ledger.records SET execution_state=new_exec, call_ownership='PROVEN_FINISHED',
   reservation_state='RELEASED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
  UPDATE change_ledger.holds SET released_at=clock_timestamp(), release_evidence=p_observation
   WHERE change_id=p_change_id AND cause='CALL_OWNERSHIP' AND released_at IS NULL;
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'RESOLVE_UNKNOWN',
  jsonb_build_object('found',p_found,'attributed',p_attributed,'observation',p_observation));
 RETURN new_exec;
END $fn$;

-- witness_cosign: records an independent completion-proof signature under the caller's OWN
-- authenticated identity, for a later operator_resolve to consume (two-person rule, T16).
CREATE OR REPLACE FUNCTION change_ledger.witness_cosign(
 t text, c text, p_change_id uuid, p_completion_proof jsonb
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE cid uuid; signer text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 signer := change_ledger.caller_role();
 IF NOT EXISTS(SELECT 1 FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=p_change_id) THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF p_completion_proof IS NULL THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 INSERT INTO change_ledger.witness_cosigns(change_id,signer,completion_proof)
 VALUES(p_change_id,signer,p_completion_proof) RETURNING cosign_id INTO cid;
 RETURN cid;
END $fn$;

-- T16: operator_resolve. operator_role caller; requires an unconsumed witness cosign signed by
-- a DIFFERENT identity than both the caller and the change's requester/approver (section 2,
-- S12-M05). Without a valid, unconsumed cosign: COMPLETION_PROOF_MISSING, nothing released.
CREATE OR REPLACE FUNCTION change_ledger.operator_resolve(
 t text, c text, p_change_id uuid, p_cosign_id uuid, p_present boolean, p_attributed boolean
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; operator text; cosign change_ledger.witness_cosigns%ROWTYPE;
 approver_subject text; new_exec text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 operator := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'TRIAGE_REQUIRED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT * INTO cosign FROM change_ledger.witness_cosigns
  WHERE cosign_id=p_cosign_id AND change_id=p_change_id AND consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 SELECT approver INTO approver_subject FROM change_ledger.approvals
  WHERE change_id=p_change_id AND decision='APPROVE' ORDER BY approved_at DESC LIMIT 1;
 IF operator IS NOT DISTINCT FROM cosign.signer
  OR operator IS NOT DISTINCT FROM rec.requester
  OR cosign.signer IS NOT DISTINCT FROM rec.requester
  OR (operator IS NOT DISTINCT FROM approver_subject AND cosign.signer IS NOT DISTINCT FROM approver_subject)
 THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 UPDATE change_ledger.witness_cosigns SET consumed_at=clock_timestamp() WHERE cosign_id=p_cosign_id;
 IF NOT p_present THEN
  new_exec:='FAILED_APPLY';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state='RELEASED',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
 ELSE
  new_exec:='APPLIED';
  UPDATE change_ledger.records SET execution_state=new_exec, reservation_state='CONSUMED',
   attribution=CASE WHEN p_attributed THEN 'PROVEN' ELSE 'UNPROVEN_OPERATOR_ATTESTED' END,
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
 END IF;
 UPDATE change_ledger.holds SET released_at=clock_timestamp(),
  release_evidence=cosign.completion_proof
  WHERE change_id=p_change_id AND cause='CALL_OWNERSHIP' AND released_at IS NULL;
 PERFORM change_ledger.append_event(t,c,p_change_id,'OPERATOR_RESOLVE',
  jsonb_build_object('present',p_present,'attributed',p_attributed,'cosign_id',p_cosign_id));
 RETURN new_exec;
END $fn$;

-- release_hold: operator_role only; never releases CALL_OWNERSHIP without completion proof
-- (that path is operator_resolve, not this function).
CREATE OR REPLACE FUNCTION change_ledger.release_hold(
 t text, c text, p_hold_id uuid, p_release_evidence jsonb
) RETURNS timestamptz LANGUAGE plpgsql AS $fn$
DECLARE h change_ledger.holds%ROWTYPE; ts timestamptz;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO h FROM change_ledger.holds WHERE hold_id=p_hold_id AND tenant_id=t AND company_id=c
  FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 IF h.cause='CALL_OWNERSHIP' THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 IF h.released_at IS NOT NULL THEN RETURN h.released_at; END IF;
 IF p_release_evidence IS NULL THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
 UPDATE change_ledger.holds SET released_at=clock_timestamp(), release_evidence=p_release_evidence
  WHERE hold_id=p_hold_id RETURNING released_at INTO ts;
 PERFORM change_ledger.append_event(t,c,h.change_id,'HOLD_RELEASED',
  jsonb_build_object('hold_id',p_hold_id,'cause',h.cause));
 RETURN ts;
END $fn$;

-- T13/T14: verify. worker_role only.
CREATE OR REPLACE FUNCTION change_ledger.verify(
 t text, c text, p_change_id uuid, p_evidence jsonb, p_passed boolean
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_ver text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.execution_state<>'APPLIED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF rec.verification_state='VERIFIED' THEN RETURN rec.verification_state; END IF;
 IF p_evidence IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 new_ver := CASE WHEN p_passed THEN 'VERIFIED' ELSE 'FAILED_VERIFY' END;
 UPDATE change_ledger.records SET verification_state=new_ver,
  effect_known=CASE WHEN p_passed THEN effect_known ELSE 'YES' END, updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF p_passed THEN
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 ELSE
  INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id)
  VALUES(t,c,rec.base_fingerprint,'FAILED_VERIFY_HALT',p_change_id);
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_'||new_ver,coalesce(p_evidence,'{}'::jsonb));
 RETURN new_ver;
END $fn$;

-- kill_switch: operator_role only. Modes are ordered OFF < STOP_ADMIT < STOP_EFFECTS < REVOKE;
-- this function only records the mode (durable, independent of checkpoints/anchor per CT9);
-- every other operation above reads it fresh under its own row lock.
CREATE OR REPLACE FUNCTION change_ledger.kill_switch(
 t text, c text, p_mode text
) RETURNS text LANGUAGE plpgsql AS $fn$
DECLARE who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_mode NOT IN ('OFF','STOP_ADMIT','STOP_EFFECTS','REVOKE') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 who := change_ledger.caller_role();
 INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode,updated_by)
 VALUES(t,c,p_mode,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET mode=p_mode, updated_by=who,
  updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'KILL_SWITCH',jsonb_build_object('mode',p_mode,'by',who));
 RETURN p_mode;
END $fn$;

-- budget_reserve/consume/release: internal only (never granted to requester/approver/operator
-- roles); claim() already performs the reservation inline, so these exist for the recover_sweep
-- / correction paths that adjust a reservation outside the claim transaction (CT13 re-post,
-- correction delta).
CREATE OR REPLACE FUNCTION change_ledger.budget_reserve(
 t text, c text, p_change_id uuid, p_grant_id uuid, p_amount numeric
) RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE g change_ledger.grants%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO g FROM change_ledger.grants WHERE grant_id=p_grant_id FOR UPDATE;
 IF NOT FOUND OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 INSERT INTO change_ledger.reservations(change_id,grant_id,amount)
 VALUES(p_change_id,p_grant_id,coalesce(p_amount,0))
 ON CONFLICT(change_id) DO UPDATE SET amount=EXCLUDED.amount WHERE change_ledger.reservations.state='RESERVED';
 RETURN p_grant_id;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.budget_consume(t text, c text, p_change_id uuid) RETURNS void
LANGUAGE plpgsql AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.budget_release(t text, c text, p_change_id uuid) RETURNS void
LANGUAGE plpgsql AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
END $fn$;

-- budget_admin: operator_role only; grant management (CT13).
CREATE OR REPLACE FUNCTION change_ledger.budget_admin(
 t text, c text, p_grant_id uuid, p_currency text, p_amount_limit numeric, p_count_limit integer,
 p_post_count_limit integer, p_window_start timestamptz, p_window_end timestamptz
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF NOT pg_has_role(change_ledger.caller_role()::name,'operator_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 INSERT INTO change_ledger.grants(
  grant_id,tenant_id,company_id,currency,amount_limit,count_limit,post_count_limit,
  window_start,window_end)
 VALUES(coalesce(p_grant_id,gen_random_uuid()),t,c,p_currency,p_amount_limit,p_count_limit,
  p_post_count_limit,p_window_start,p_window_end)
 ON CONFLICT(grant_id) DO UPDATE SET amount_limit=EXCLUDED.amount_limit,
  count_limit=EXCLUDED.count_limit, post_count_limit=EXCLUDED.post_count_limit,
  window_start=EXCLUDED.window_start, window_end=EXCLUDED.window_end
 RETURNING grant_id INTO p_grant_id;
 RETURN p_grant_id;
END $fn$;

-- write_checkpoint: internal helper used by the Python checkpoint sink wiring (not part of
-- section 6's caller matrix; called by the service identity that owns the external anchor
-- round-trip, mapped here to writer_role per CT5's "written to an external store, then read
-- back by the ledger").
CREATE OR REPLACE FUNCTION change_ledger.record_checkpoint(
 t text, c text, p_head_hash text, p_signer_key_id text, p_signature text
) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE s bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 INSERT INTO change_ledger.checkpoints(tenant_id,company_id,head_hash,signer_key_id,signature)
 VALUES(t,c,p_head_hash,p_signer_key_id,p_signature) RETURNING seq INTO s;
 RETURN s;
END $fn$;

-- ================================================================== definer wiring + privileges
DO $fn$
DECLARE f record;
BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='change_ledger' AND p.proname IN (
   'set_scope','assert_scope','recheck_scope_locked','add_role_scope','append_event',
   'handoff_target_lock','dispatch_cas','propose','validate','approve','reject','claim',
   'release_claim','begin_apply','issue_permit','complete','recover_sweep','resolve_unknown',
   'witness_cosign','operator_resolve','release_hold','verify','kill_switch','budget_reserve',
   'budget_consume','budget_release','budget_admin','record_checkpoint','events_chain_guard',
   'reject_immutable_mutation','caller_role','row_in_scope')
 LOOP
  EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp',f.sig);
 END LOOP;
END $fn$;

DO $fn$
DECLARE o record;
BEGIN
 EXECUTE 'GRANT USAGE, CREATE ON SCHEMA change_ledger TO ledger_owner';
 FOR o IN SELECT c.oid::regclass AS rel FROM pg_catalog.pg_class c
   JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='change_ledger' AND c.relkind IN ('r','p')
 LOOP EXECUTE format('ALTER TABLE %s OWNER TO ledger_owner',o.rel); END LOOP;
 FOR o IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='change_ledger'
 LOOP EXECUTE format('ALTER FUNCTION %s OWNER TO ledger_owner',o.sig); END LOOP;
END $fn$;

REVOKE ALL ON SCHEMA change_ledger FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA change_ledger FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA change_ledger FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA change_ledger FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner IN SCHEMA change_ledger REVOKE ALL ON TABLES FROM PUBLIC;

GRANT USAGE ON SCHEMA change_ledger
 TO requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role;

-- Scope + identity: every runtime role needs these.
GRANT EXECUTE ON FUNCTION change_ledger.caller_role(), change_ledger.row_in_scope(text,text),
 change_ledger.set_scope(text,text)
 TO requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role;

-- No direct DML for any runtime role (mirrors living's baseline): read access is RLS-filtered
-- SELECT only, every write goes through a definer function.
GRANT SELECT ON change_ledger.records, change_ledger.target_locks, change_ledger.key_locks,
 change_ledger.writer_leases, change_ledger.holds, change_ledger.claim_tokens,
 change_ledger.dispatch_permits, change_ledger.reservations, change_ledger.grants,
 change_ledger.approvals, change_ledger.approval_nonces, change_ledger.checkpoints,
 change_ledger.events, change_ledger.kill_switch_state, change_ledger.targets
 TO auditor_role;
GRANT SELECT ON change_ledger.records, change_ledger.target_locks, change_ledger.key_locks,
 change_ledger.writer_leases, change_ledger.holds, change_ledger.claim_tokens
 TO requester_role, approver_role, operator_role, writer_role, worker_role;

GRANT EXECUTE ON FUNCTION
 change_ledger.propose(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz),
 change_ledger.validate(text,text,uuid,boolean,boolean),
 change_ledger.claim(text,text,uuid,text,uuid,numeric,boolean,boolean),
 change_ledger.release_claim(text,text,uuid),
 change_ledger.begin_apply(text,text,uuid,uuid,text,text)
 TO requester_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.approve(text,text,uuid,text,text), change_ledger.reject(text,text,uuid,text)
 TO approver_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.kill_switch(text,text,text), change_ledger.release_hold(text,text,uuid,jsonb),
 change_ledger.budget_admin(text,text,uuid,text,numeric,integer,integer,timestamptz,timestamptz),
 change_ledger.operator_resolve(text,text,uuid,uuid,boolean,boolean),
 change_ledger.witness_cosign(text,text,uuid,jsonb)
 TO operator_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.issue_permit(text,text,uuid,bigint,bigint), change_ledger.complete(text,text,uuid,bigint,text,jsonb,jsonb),
 change_ledger.record_checkpoint(text,text,text,text,text), change_ledger.dispatch_cas(uuid,bigint,text,text),
 change_ledger.begin_apply(text,text,uuid,uuid,text,text)
 TO writer_role;
GRANT EXECUTE ON FUNCTION
 change_ledger.recover_sweep(text,text), change_ledger.resolve_unknown(text,text,uuid,jsonb,boolean,boolean),
 change_ledger.verify(text,text,uuid,jsonb,boolean), change_ledger.release_claim(text,text,uuid),
 change_ledger.dispatch_cas(uuid,bigint,text,text)
 TO worker_role;

-- ================================================================== RLS
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'records','target_locks','key_locks','writer_leases','holds','claim_tokens',
  'dispatch_permits','reservations','grants','approvals','approval_nonces','checkpoints',
  'events','kill_switch_state','targets','witness_cosigns','role_scope'
 ] LOOP
  EXECUTE format('ALTER TABLE change_ledger.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS owner_all ON change_ledger.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS scope_isolation ON change_ledger.%I',tbl);
  EXECUTE format('CREATE POLICY owner_all ON change_ledger.%I FOR ALL TO ledger_owner USING (true) WITH CHECK (true)',tbl);
 END LOOP;
 -- Tables scoped directly by (tenant_id, company_id).
 FOREACH tbl IN ARRAY ARRAY[
  'records','target_locks','key_locks','writer_leases','holds','checkpoints','events',
  'kill_switch_state','targets'
 ] LOOP
  EXECUTE format('CREATE POLICY scope_isolation ON change_ledger.%I FOR ALL USING (change_ledger.row_in_scope(tenant_id,company_id)) WITH CHECK (change_ledger.row_in_scope(tenant_id,company_id))',tbl);
 END LOOP;
 -- role_scope: a role sees only its own grants.
 CREATE POLICY scope_isolation ON change_ledger.role_scope FOR SELECT
  USING (pg_has_role(current_user, role_name::name, 'USAGE'));
END $fn$;
-- Tables keyed by change_id only: scoped by joining to records (RLS on records is enough to hide
-- other tenants' rows from a direct unfiltered SELECT once FORCE ROW LEVEL SECURITY applies the
-- join; here we restate the predicate directly since these tables have no tenant/company columns
-- of their own).
CREATE POLICY scope_isolation ON change_ledger.claim_tokens FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=claim_tokens.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));
CREATE POLICY scope_isolation ON change_ledger.dispatch_permits FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=dispatch_permits.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));
CREATE POLICY scope_isolation ON change_ledger.reservations FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=reservations.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));
CREATE POLICY scope_isolation ON change_ledger.grants FOR ALL
 USING (change_ledger.row_in_scope(tenant_id,company_id))
 WITH CHECK (change_ledger.row_in_scope(tenant_id,company_id));
CREATE POLICY scope_isolation ON change_ledger.approvals FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=approvals.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));
CREATE POLICY scope_isolation ON change_ledger.approval_nonces FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=approval_nonces.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));
CREATE POLICY scope_isolation ON change_ledger.witness_cosigns FOR ALL USING (
 EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=witness_cosigns.change_id
  AND change_ledger.row_in_scope(r.tenant_id,r.company_id)));

$body$;
END IF;
END $mig$;
COMMIT;
