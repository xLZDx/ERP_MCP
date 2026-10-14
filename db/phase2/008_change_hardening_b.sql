-- R2/G1 S13 hardening, batch B (docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md items B1-B6). Applies after 007.
-- Apply ONLY to a verified disposable PostgreSQL database (checksum precondition: living.record_migration).
-- LOCK ORDER (one order for every function of the change ledger; B5):
--   0. namespace advisory locks taken by name (killswitch:..., hold:...) - always first, never after a row lock;
--   1. row locks, CLAIM TOKEN BEFORE RECORD: claim_tokens (ascending token_id / generation) then records (ascending
--      change_id; a repair's parent record after the repair's own), then the secondary rows of the locked change
--      (dispatch_permits, reservations, grants, locks, leases, holds, counters, epochs, principals) - the owner of a
--      secondary row always holds the record lock of the change first;
--   2. the CHAIN advisory lock (change_ledger.events_chain_guard) LAST: it is taken by the first append_event of a
--      transaction and kept to its end, so every API appends only after all of its row locks;
--   3. a transaction that already holds the chain lock (or may hold it) never WAITS for a row: loops (sweeps,
--      revoke_stale) lock the whole bounded batch (tokens, then records) BEFORE their first append, process each item in
--      a subtransaction and append afterwards. recover_sweep must therefore be the first ledger call of its transaction.
--   A function that writes a row and then appends must not touch another row after the append (register_principal /
--   register_target bump the epoch row first and append both events last).
--  B1 claim / validate derive grant, amount, counts, currency and the business-key hash from the STORED change
--     (change_ledger.change_budget, declared by the requester with declare_budget before approval and bound into
--     the approval digest); validate loses p_duplicate / p_budget_ok and computes the budget pre-check itself;
--     claim refuses without a RESERVED reservation row (BUDGET_EXCEEDED), checks the grant currency
--     (CURRENCY_NOT_BUDGETED) and requires execution NOT_STARTED / verification NOT_VERIFIED / dispatch not
--     DISPATCHED (FORBIDDEN_TRANSITION); a CREATE_DRAFT without a business key cannot validate or claim;
--     records.reservation_state becomes RESERVED only when the reservation row exists.
--     DELIBERATE: claim keeps its 8-argument signature for the port, but every budget argument is only a
--     cross-check against the stored declaration (NULL or different grant -> BUDGET_EXCEEDED, different
--     amount / counts -> DIGEST_MISMATCH, different key hash -> DIGEST_MISMATCH). For POST / UNPOST (no
--     declarable business key) a caller key hash still selects the key lock, as in 005.
--  B2 budget_admin: assert_scope, conflict update only inside the same (tenant, company), a REVOKED path
--     (budget_revoke), a ledger event for every limit change; person_of / same_person / epoch_value /
--     registry_enforced are no longer executable by any runtime role.
--  B3 new scopes default to an ENFORCED registry (no policy row = enforced); claim and issue_permit refuse a
--     non-clone target while the registry is not enforced; approver independence also compares the SESSION
--     identity (session_user, which SET ROLE cannot change) with the session that proposed the change; a
--     superuser session is exempt (it can rewrite the database anyway), so single-connection test fixtures work.
--  B4 ANCHOR_GAP holds opened by check_anchor persist the external (seq, hash); release_hold needs the ledger to
--     contain that exact event (history reconciled) or a two-person release (anchor_gap_cosign by a recovery
--     witness + release by an independent operator); a fresh checkpoint of the restored head no longer releases it.
--  B5 lock order (header above); sweeps lock a bounded batch first, run one subtransaction per item and record a
--     committed failure counter + event for a failing item (change_ledger.sweep_failures, SWEEP_ITEM_FAILED);
--     contract constants (claim TTL 120 s, permit TTL 60 s, T12 5 attempts / 900 s, anchor window 900 s, verify
--     bound 3) are ledger constants (sweep_constants) or an operator-set policy row (set_sweep_policy); a worker that
--     passes one is refused (NOT_ENTITLED); JSON overrides are range-validated (SCHEMA_INVALID).
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('008', ARRAY['001','002','003','004','005','006','007']) THEN
EXECUTE $body$

-- ================================================================== shared: columns, table
ALTER TABLE change_ledger.records ADD COLUMN IF NOT EXISTS requester_session text;
ALTER TABLE change_ledger.registry_policy ALTER COLUMN enforced SET DEFAULT true;

CREATE TABLE IF NOT EXISTS change_ledger.change_budget(
 change_id uuid PRIMARY KEY REFERENCES change_ledger.records(change_id),
 tenant_id text NOT NULL, company_id text NOT NULL,
 grant_id uuid NOT NULL REFERENCES change_ledger.grants(grant_id),
 currency text NOT NULL CHECK(length(currency)=3),
 amount numeric(18,2) NOT NULL CHECK(amount>=0),
 counts_create_update boolean NOT NULL DEFAULT false,
 counts_post boolean NOT NULL DEFAULT false,
 declared_by text NOT NULL, declared_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE change_ledger.change_budget OWNER TO ledger_owner;
ALTER TABLE change_ledger.change_budget ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_ledger.change_budget FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS owner_all ON change_ledger.change_budget;
CREATE POLICY owner_all ON change_ledger.change_budget FOR ALL TO ledger_owner USING (true) WITH CHECK (true);

-- ================================================================== B3 registry default and session identity
CREATE OR REPLACE FUNCTION change_ledger.registry_enforced(t text, c text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT coalesce((SELECT p.enforced FROM change_ledger.registry_policy p
  WHERE p.tenant_id=t AND p.company_id=c),true)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.enforce_registry(t text, c text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; had boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 SELECT p.enforced INTO had FROM change_ledger.registry_policy p WHERE p.tenant_id=t AND p.company_id=c;
 IF had IS TRUE THEN RETURN true; END IF;
 INSERT INTO change_ledger.registry_policy(tenant_id,company_id,enforced,updated_by) VALUES(t,c,true,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET enforced=true, updated_by=who, updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_ENFORCED',jsonb_build_object('by',who));
 RETURN true;
END $fn$;

-- The session that opened the connection cannot be changed by SET ROLE: a non-superuser session that proposed a
-- change can never approve it through another role it is a member of (nor can an alias person of that session).
CREATE OR REPLACE FUNCTION change_ledger.assert_session_independent(t text, c text, p_requester_session text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
 IF p_requester_session IS NULL THEN RETURN; END IF;
 IF EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname=session_user AND r.rolsuper) THEN RETURN; END IF;
 IF change_ledger.same_person(t,c,session_user::text,p_requester_session) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
END $fn$;

-- claim / issue_permit: only a disposable clone may run with a registry that is not enforced
CREATE OR REPLACE FUNCTION change_ledger.assert_registry_for_effect(t text, c text, p_base text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE tc text;
BEGIN
 SELECT g.target_class INTO tc FROM change_ledger.targets g
  WHERE g.tenant_id=t AND g.company_id=c AND g.base_fingerprint=p_base;
 IF tc IS DISTINCT FROM 'DISPOSABLE_CLONE' AND NOT change_ledger.registry_enforced(t,c) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
END $fn$;

-- ================================================================== B1 budget declaration and pre-check
-- The effective amount of the change against its grant (a POST reserves only the part not yet consumed).
CREATE OR REPLACE FUNCTION change_ledger.budget_precheck(t text, c text, p_rec change_ledger.records,
 p_lock boolean, p_window boolean) RETURNS numeric
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cb change_ledger.change_budget%ROWTYPE; g change_ledger.grants%ROWTYPE; eff numeric;
 used_amount numeric; used_cu integer; used_post integer; tref text;
BEGIN
 SELECT * INTO cb FROM change_ledger.change_budget b WHERE b.change_id=p_rec.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF p_lock THEN
  SELECT * INTO g FROM change_ledger.grants x WHERE x.grant_id=cb.grant_id AND x.tenant_id=t AND x.company_id=c FOR UPDATE;
 ELSE
  SELECT * INTO g FROM change_ledger.grants x WHERE x.grant_id=cb.grant_id AND x.tenant_id=t AND x.company_id=c;
 END IF;
 IF NOT FOUND OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF g.currency IS DISTINCT FROM cb.currency THEN RAISE EXCEPTION 'CURRENCY_NOT_BUDGETED'; END IF;
 IF p_window AND (clock_timestamp()<g.window_start OR clock_timestamp()>=g.window_end) THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 tref := coalesce(p_rec.target_ref,p_rec.change_id::text);
 eff := cb.amount;
 IF p_rec.kind='POST' THEN
  eff := greatest(eff - change_ledger.amount_consumed(t,c,tref,cb.grant_id),0);
 END IF;
 SELECT coalesce(sum(r.amount),0),
        count(*) FILTER (WHERE r.counts_create_update), count(*) FILTER (WHERE r.counts_post)
  INTO used_amount, used_cu, used_post
  FROM change_ledger.reservations r
  WHERE r.grant_id=cb.grant_id AND r.state IN ('RESERVED','CONSUMED') AND r.change_id<>p_rec.change_id;
 IF used_amount+eff > g.amount_limit
  OR used_cu+(CASE WHEN cb.counts_create_update THEN 1 ELSE 0 END) > g.count_limit
  OR used_post+(CASE WHEN cb.counts_post THEN 1 ELSE 0 END) > g.post_count_limit THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 RETURN eff;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.declare_budget(
 t text, c text, p_change_id uuid, p_grant_id uuid, p_currency text, p_amount numeric,
 p_counts_create_update boolean, p_counts_post boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; g change_ledger.grants%ROWTYPE; lc text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 IF p_change_id IS NULL OR p_grant_id IS NULL OR p_currency IS NULL OR length(p_currency)<>3
  OR p_amount IS NULL OR p_amount<0 OR p_counts_create_update IS NULL OR p_counts_post IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';   -- the budget is inside the approved digest
 END IF;
 SELECT * INTO g FROM change_ledger.grants x WHERE x.grant_id=p_grant_id AND x.tenant_id=t AND x.company_id=c;
 IF NOT FOUND OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF g.currency<>p_currency THEN RAISE EXCEPTION 'CURRENCY_NOT_BUDGETED'; END IF;
 INSERT INTO change_ledger.change_budget(change_id,tenant_id,company_id,grant_id,currency,amount,
  counts_create_update,counts_post,declared_by)
 VALUES(p_change_id,t,c,p_grant_id,p_currency,p_amount,p_counts_create_update,p_counts_post,change_ledger.caller_role())
 ON CONFLICT(change_id) DO UPDATE SET grant_id=EXCLUDED.grant_id, currency=EXCLUDED.currency,
  amount=EXCLUDED.amount, counts_create_update=EXCLUDED.counts_create_update,
  counts_post=EXCLUDED.counts_post, declared_by=EXCLUDED.declared_by, declared_at=clock_timestamp();
 lc := rec.lifecycle;
 IF rec.lifecycle='VALIDATED' THEN
  UPDATE change_ledger.records SET lifecycle='PROPOSED', updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  lc := 'PROPOSED';
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'BUDGET_DECLARED',
  jsonb_build_object('grant_id',p_grant_id,'currency',p_currency,'amount',p_amount::text,
   'counts_create_update',p_counts_create_update,'counts_post',p_counts_post));
 RETURN lc;
END $fn$;

-- the approval digest also binds the declared budget
CREATE OR REPLACE FUNCTION change_ledger.approval_digest(p_change_id uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; bsd text; eff jsonb; bud jsonb;
BEGIN
 SELECT * INTO rec FROM change_ledger.records WHERE change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT encode(sha256(convert_to(b.key_hash||':'||coalesce(b.override_digest,''),'UTF8')),'hex')
  INTO bsd FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 SELECT jsonb_build_object('grant_id',x.grant_id,'currency',x.currency,'amount',x.amount::text,
  'counts_create_update',x.counts_create_update,'counts_post',x.counts_post)
  INTO bud FROM change_ledger.change_budget x WHERE x.change_id=p_change_id;
 eff := change_ledger.allowed_effects(rec.kind);
 RETURN encode(sha256(convert_to(jsonb_build_object(
  'digest_version','S12-APPROVAL-SQL-1','change_id',rec.change_id,'kind',rec.kind,
  'tenant',rec.tenant_id,'company',rec.company_id,'organization',rec.organization_ref,
  'base_fingerprint',rec.base_fingerprint,'payload_digest',rec.payload_digest,
  'target_ref',rec.target_ref,'target_version',rec.target_version,
  'parent_change_id',rec.parent_change_id,'repair_for',rec.repair_for,
  'declared_target_class',rec.declared_target_class,'business_state_digest',bsd,
  'budget',bud,
  'allowed_effects',eff,'rule_table_version','S11-RULES-2026-10-12',
  'epoch_dependencies',(SELECT coalesce(jsonb_object_agg(k,v),'{}'::jsonb) FROM jsonb_each(rec.epoch_dependencies) e(k,v)
                         WHERE k NOT LIKE 'principal:%'),
  'expires_at',to_char(rec.expires_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))::text,'UTF8')),'hex');
END $fn$;

-- propose: + the session that proposed (B3)
CREATE OR REPLACE FUNCTION change_ledger.propose(
 t text, c text, p_change_id uuid, p_kind text, p_base_fingerprint text, p_organization_ref text,
 p_requester text, p_request_id text, p_payload_digest text, p_target_ref text,
 p_target_version text, p_parent_change_id uuid, p_expires_at timestamptz,
 p_repair_for uuid DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE existing change_ledger.records%ROWTYPE; tgt_epoch bigint; tgt_status text; tgt_org text; tgt_exp timestamptz;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_kind IS NULL OR p_base_fingerprint IS NULL
  OR p_organization_ref IS NULL OR p_requester IS NULL OR p_request_id IS NULL
  OR p_payload_digest IS NULL OR p_expires_at IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_repair_for IS NOT NULL AND (p_kind<>'UNPOST' OR p_parent_change_id IS DISTINCT FROM p_repair_for) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT status, epoch, organization_ref, permission_expires_at INTO tgt_status, tgt_epoch, tgt_org, tgt_exp
  FROM change_ledger.targets
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=p_base_fingerprint FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tgt_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_org IS DISTINCT FROM p_organization_ref THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_exp IS NOT NULL AND tgt_exp<=clock_timestamp() THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.assert_capability(t,c,p_requester,'requester');
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
  payload_digest,target_ref,target_version,parent_change_id,repair_for,auth_epoch_at_proposal,expires_at,
  epoch_dependencies,requester_session)
 VALUES(p_change_id,t,c,p_base_fingerprint,p_organization_ref,p_kind,p_requester,p_request_id,
  p_payload_digest,p_target_ref,p_target_version,p_parent_change_id,p_repair_for,tgt_epoch,p_expires_at,
  jsonb_build_object('target:'||p_base_fingerprint,change_ledger.epoch_value(t,c,'target:'||p_base_fingerprint),
   'principal:'||p_requester,change_ledger.epoch_value(t,c,'principal:'||p_requester)),
  session_user::text);
 PERFORM change_ledger.append_event(t,c,p_change_id,'PROPOSED',
  jsonb_build_object('kind',p_kind,'payload_digest',p_payload_digest));
 RETURN p_change_id;
END $fn$;

-- validate: no caller flags. The budget pre-check and the duplicate check come from the stored change.
DROP FUNCTION IF EXISTS change_ledger.validate(text,text,uuid,boolean,boolean);
CREATE OR REPLACE FUNCTION change_ledger.validate(t text, c text, p_change_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; bk change_ledger.business_keys%ROWTYPE; colls text[];
 dup boolean := false; ovr boolean := false; have_bk boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.lifecycle = 'VALIDATED' THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle = 'DUPLICATE_PARKED' THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle <> 'PROPOSED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 have_bk := FOUND;
 IF NOT have_bk AND rec.kind='CREATE_DRAFT' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;   -- key lock is mandatory
 PERFORM change_ledger.budget_precheck(t,c,rec,false,false);
 IF have_bk AND rec.kind IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(t||':'||c||':'||rec.base_fingerprint||':'||bk.key_hash,1));
  SELECT coalesce(array_agg(o.change_id::text ORDER BY o.created_at),ARRAY[]::text[]) INTO colls
   FROM change_ledger.records o JOIN change_ledger.business_keys ob ON ob.change_id=o.change_id
   WHERE o.tenant_id=t AND o.company_id=c AND o.base_fingerprint=rec.base_fingerprint
    AND o.organization_ref=rec.organization_ref AND o.change_id<>rec.change_id
    AND ob.key_hash=bk.key_hash AND o.lifecycle='VALIDATED'
    AND o.authorization_state NOT IN ('VOIDED','REVOKED','EXPIRED')
    AND o.execution_state NOT IN ('FAILED_APPLY','ROLLBACK_REFUSED')
    AND NOT (rec.kind='UPDATE_DRAFT' AND rec.target_ref IS NOT NULL
             AND o.target_ref IS NOT DISTINCT FROM rec.target_ref);
  IF cardinality(colls)>0 THEN
   IF bk.override_of IS NOT NULL AND cardinality(colls)=1 AND bk.override_of=colls[1] THEN
    ovr := true;
    UPDATE change_ledger.business_keys SET override_required=true WHERE change_id=p_change_id;
   ELSE
    dup := true;
   END IF;
  END IF;
 END IF;
 UPDATE change_ledger.records SET
  lifecycle=CASE WHEN dup THEN 'DUPLICATE_PARKED' ELSE 'VALIDATED' END,
  updated_at=clock_timestamp()
 WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
 RETURNING lifecycle INTO rec.lifecycle;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VALIDATED',
  jsonb_build_object('lifecycle',rec.lifecycle,'override_pending',ovr));
 RETURN rec.lifecycle;
END $fn$;

-- nonce / approve: + session independence (B3)
CREATE OR REPLACE FUNCTION change_ledger.issue_approval_nonce(t text, c text, p_change_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; n text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF who IS NOT DISTINCT FROM rec.requester OR pg_has_role(who::name, rec.requester::name, 'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 IF rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED') OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'approver');
 PERFORM change_ledger.assert_independent(t,c,who,rec.requester);
 PERFORM change_ledger.assert_session_independent(t,c,rec.requester_session);
 n := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
 INSERT INTO change_ledger.approval_nonces(nonce,change_id,approver,expires_at)
 VALUES(n,p_change_id,who,clock_timestamp()+interval '10 minutes');
 RETURN n;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.approve(
 t text, c text, p_change_id uuid, p_nonce text, p_digest text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_approver text; nrow change_ledger.approval_nonces%ROWTYPE;
 aid uuid; bk change_ledger.business_keys%ROWTYPE; parent_req text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_digest IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 v_approver := change_ledger.caller_role();
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle <> 'VALIDATED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED') OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF v_approver IS NOT DISTINCT FROM rec.requester
  OR pg_has_role(v_approver::name, rec.requester::name, 'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,v_approver,'approver');
 PERFORM change_ledger.assert_independent(t,c,v_approver,rec.requester);
 PERFORM change_ledger.assert_session_independent(t,c,rec.requester_session);
 IF rec.repair_for IS NOT NULL THEN
  SELECT p.requester INTO parent_req FROM change_ledger.records p WHERE p.change_id=rec.repair_for;
  IF change_ledger.same_person(t,c,v_approver,parent_req) THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
 END IF;
 IF p_digest IS DISTINCT FROM change_ledger.approval_digest(p_change_id) THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 SELECT * INTO nrow FROM change_ledger.approval_nonces n
  WHERE n.nonce=p_nonce AND n.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.approver IS DISTINCT FROM v_approver THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 IF nrow.expires_at<=clock_timestamp() THEN
  UPDATE change_ledger.approval_nonces n SET state='EXPIRED' WHERE n.nonce=p_nonce;
  RAISE EXCEPTION 'APPROVAL_EXPIRED';
 END IF;
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF FOUND AND bk.override_required AND NOT EXISTS(SELECT 1 FROM change_ledger.override_bindings ob
   WHERE ob.change_id=p_change_id AND ob.approver=v_approver AND ob.override_digest=bk.override_digest) THEN
  RAISE EXCEPTION 'DUPLICATE_SUSPECTED';
 END IF;
 UPDATE change_ledger.approval_nonces n SET state='CONSUMED' WHERE n.nonce=p_nonce;
 INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision)
 VALUES(p_change_id,v_approver,p_nonce,p_digest,'APPROVE') RETURNING approval_id INTO aid;
 UPDATE change_ledger.records SET authorization_state='APPROVED',
  epoch_dependencies=epoch_dependencies || jsonb_build_object('principal:'||v_approver,
   change_ledger.epoch_value(t,c,'principal:'||v_approver)),
  updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVED',
  jsonb_build_object('approval_id',aid,'digest',p_digest));
 RETURN aid;
END $fn$;

-- ================================================================== B1 / B3 claim
CREATE OR REPLACE FUNCTION change_ledger.claim(
 t text, c text, p_change_id uuid, p_key_hash text, p_grant_id uuid, p_amount numeric,
 p_counts_create_update boolean, p_counts_post boolean
) RETURNS change_ledger.claim_tokens LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_requester text; gen bigint;
 tok change_ledger.claim_tokens%ROWTYPE; parent change_ledger.records%ROWTYPE; tref text;
 bk change_ledger.business_keys%ROWTYPE; cb change_ledger.change_budget%ROWTYPE; key_h text; eff_amount numeric;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 v_requester := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF v_requester IS DISTINCT FROM rec.requester THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.execution_state<>'NOT_STARTED' OR rec.verification_state<>'NOT_VERIFIED' OR rec.dispatch_state='DISPATCHED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF rec.authorization_state IN ('VOIDED','REVOKED') THEN RAISE EXCEPTION 'APPROVAL_VOIDED'; END IF;
 IF rec.authorization_state <> 'APPROVED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 IF change_ledger.blocking_hold(t,c,rec.base_fingerprint,rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 PERFORM change_ledger.assert_registry_for_effect(t,c,rec.base_fingerprint);
 -- the business key comes from the stored declaration; a caller value is only a cross-check
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF FOUND THEN
  IF p_key_hash IS NOT NULL AND p_key_hash IS DISTINCT FROM bk.key_hash THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
  key_h := bk.key_hash;
 ELSIF rec.kind='CREATE_DRAFT' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 ELSE
  key_h := p_key_hash;
 END IF;
 -- budget inputs come from the stored declaration; the arguments are only a cross-check
 SELECT * INTO cb FROM change_ledger.change_budget b WHERE b.change_id=p_change_id;
 IF NOT FOUND OR p_grant_id IS DISTINCT FROM cb.grant_id THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF p_amount IS DISTINCT FROM cb.amount
  OR coalesce(p_counts_create_update,false) IS DISTINCT FROM cb.counts_create_update
  OR coalesce(p_counts_post,false) IS DISTINCT FROM cb.counts_post THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 tref := coalesce(rec.target_ref,p_change_id::text);
 IF rec.repair_for IS NOT NULL THEN
  SELECT * INTO parent FROM change_ledger.records WHERE tenant_id=t AND company_id=c
   AND change_id=rec.repair_for FOR UPDATE;
  IF NOT FOUND OR parent.verification_state<>'FAILED_VERIFY' OR parent.effect_known IS DISTINCT FROM 'YES'
   OR parent.target_ref IS DISTINCT FROM rec.target_ref
   OR parent.base_fingerprint<>rec.base_fingerprint
   OR NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=rec.base_fingerprint AND h.cause='FAILED_VERIFY_HALT'
     AND h.change_id=rec.repair_for AND h.released_at IS NULL) THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 ELSIF rec.parent_change_id IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.records
    WHERE change_id=rec.parent_change_id AND verification_state='VERIFIED') THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 END IF;
 BEGIN
  eff_amount := change_ledger.budget_precheck(t,c,rec,true,true);
  INSERT INTO change_ledger.reservations(change_id,grant_id,amount,counts_create_update,counts_post)
  VALUES(p_change_id,cb.grant_id,eff_amount,cb.counts_create_update,cb.counts_post)
  ON CONFLICT(change_id) DO UPDATE SET grant_id=EXCLUDED.grant_id, amount=EXCLUDED.amount,
   counts_create_update=EXCLUDED.counts_create_update, counts_post=EXCLUDED.counts_post,
   state='RESERVED', reserved_at=clock_timestamp()
   WHERE change_ledger.reservations.state='RELEASED';
  IF NOT EXISTS(SELECT 1 FROM change_ledger.reservations r WHERE r.change_id=p_change_id AND r.state='RESERVED') THEN
   RAISE EXCEPTION 'BUDGET_EXCEEDED';
  END IF;
  IF rec.repair_for IS NOT NULL THEN
   IF NOT change_ledger.handoff_target_lock(t,c,rec.base_fingerprint,tref,rec.repair_for,p_change_id) THEN
    RAISE EXCEPTION 'LOCK_BUSY';
   END IF;
  ELSE
   INSERT INTO change_ledger.target_locks(tenant_id,company_id,base_fingerprint,target_ref,owner_change_id)
   VALUES(t,c,rec.base_fingerprint,tref,p_change_id);
  END IF;
  IF key_h IS NOT NULL THEN
   INSERT INTO change_ledger.key_locks(tenant_id,company_id,base_fingerprint,key_hash,owner_change_id)
   VALUES(t,c,rec.base_fingerprint,key_h,p_change_id);
  END IF;
  INSERT INTO change_ledger.writer_leases(tenant_id,company_id,base_fingerprint,owner_change_id)
  VALUES(t,c,rec.base_fingerprint,p_change_id);
 EXCEPTION WHEN unique_violation THEN
  RAISE EXCEPTION 'LOCK_BUSY';
 END;
 gen := rec.claim_generation + 1;
 UPDATE change_ledger.records SET authorization_state='CLAIMED', execution_state='NOT_STARTED',
  claim_generation=gen, reservation_state='RESERVED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 INSERT INTO change_ledger.claim_tokens(change_id,generation) VALUES(p_change_id,gen)
  RETURNING * INTO tok;
 PERFORM change_ledger.append_event(t,c,p_change_id,'CLAIMED',
  jsonb_build_object('generation',gen,'token_id',tok.token_id));
 RETURN tok;
END $fn$;

-- ================================================================== B3 issue_permit: registry gate
CREATE OR REPLACE FUNCTION change_ledger.issue_permit(
 t text, c text, p_change_id uuid, p_generation bigint
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
 cp_seq bigint; applying_seq bigint; digest text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 PERFORM change_ledger.assert_registry_for_effect(t,c,rec.base_fingerprint);
 SELECT max(e.seq) INTO applying_seq FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.event_type='APPLYING';
 SELECT k.seq INTO cp_seq FROM change_ledger.checkpoints k
  JOIN change_ledger.events e ON e.tenant_id=k.tenant_id AND e.company_id=k.company_id
   AND e.seq=k.ledger_seq AND e.hash=k.head_hash
  WHERE k.tenant_id=t AND k.company_id=c AND k.sink_kind='REAL' AND k.read_back_confirmed
   AND k.verified AND k.written_by IS NOT NULL
   AND k.ledger_seq>=applying_seq
  ORDER BY k.seq DESC LIMIT 1;
 IF cp_seq IS NULL THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 digest := encode(sha256(convert_to(p_change_id::text||':'||p_generation::text||':'||cp_seq::text,
  'UTF8')),'hex');
 UPDATE change_ledger.dispatch_permits SET state='PERMITTED', checkpoint_seq=cp_seq,
  permit_digest=digest, issued_at=clock_timestamp(),
  expires_at=clock_timestamp()+interval '60 seconds'
  WHERE change_id=p_change_id AND generation=p_generation AND state='NOT_PERMITTED'
 RETURNING * INTO dp;
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 UPDATE change_ledger.records SET dispatch_state='PERMITTED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PERMITTED',
  jsonb_build_object('generation',p_generation,'checkpoint_seq',cp_seq));
 RETURN jsonb_build_object('change_id',dp.change_id,'generation',dp.generation,
  'permit_digest',dp.permit_digest,'checkpoint_seq',dp.checkpoint_seq,
  'expires_at',to_char(dp.expires_at,'YYYY-MM-DD"T"HH24:MI:SS.US'));
END $fn$;

-- ================================================================== B2 budget_admin
CREATE OR REPLACE FUNCTION change_ledger.budget_admin(
 t text, c text, p_grant_id uuid, p_currency text, p_amount_limit numeric, p_count_limit integer,
 p_post_count_limit integer, p_window_start timestamptz, p_window_end timestamptz
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; ex change_ledger.grants%ROWTYPE; gid uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT pg_has_role(who::name,'operator_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_currency IS NULL OR length(p_currency)<>3 OR p_amount_limit IS NULL OR p_amount_limit<0
  OR p_count_limit IS NULL OR p_count_limit<0 OR p_post_count_limit IS NULL OR p_post_count_limit<0
  OR p_window_start IS NULL OR p_window_end IS NULL OR p_window_end<=p_window_start THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 gid := coalesce(p_grant_id,gen_random_uuid());
 SELECT * INTO ex FROM change_ledger.grants g WHERE g.grant_id=gid FOR UPDATE;
 IF FOUND THEN
  IF ex.tenant_id IS DISTINCT FROM t OR ex.company_id IS DISTINCT FROM c THEN
   RAISE EXCEPTION 'SCOPE_NOT_GRANTED';      -- never touch (or confirm) another scope's grant
  END IF;
  IF ex.status<>'ACTIVE' OR ex.currency<>p_currency THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
  UPDATE change_ledger.grants g SET amount_limit=p_amount_limit, count_limit=p_count_limit,
   post_count_limit=p_post_count_limit, window_start=p_window_start, window_end=p_window_end
   WHERE g.grant_id=gid AND g.tenant_id=t AND g.company_id=c;
 ELSE
  INSERT INTO change_ledger.grants(grant_id,tenant_id,company_id,currency,amount_limit,count_limit,
   post_count_limit,window_start,window_end)
  VALUES(gid,t,c,p_currency,p_amount_limit,p_count_limit,p_post_count_limit,p_window_start,p_window_end);
 END IF;
 PERFORM change_ledger.append_event(t,c,NULL,'BUDGET_GRANT_SET',
  jsonb_build_object('grant_id',gid,'currency',p_currency,'amount_limit',p_amount_limit::text,
   'count_limit',p_count_limit,'post_count_limit',p_post_count_limit,'window_start',p_window_start,
   'window_end',p_window_end,'update',ex.grant_id IS NOT NULL,
   'previous',CASE WHEN ex.grant_id IS NULL THEN NULL ELSE jsonb_build_object('amount_limit',ex.amount_limit::text,
     'count_limit',ex.count_limit,'post_count_limit',ex.post_count_limit,'window_start',ex.window_start,
     'window_end',ex.window_end) END,
   'by',who));
 RETURN gid;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.budget_revoke(t text, c text, p_grant_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; ex change_ledger.grants%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT pg_has_role(who::name,'operator_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_grant_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO ex FROM change_ledger.grants g WHERE g.grant_id=p_grant_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF ex.tenant_id IS DISTINCT FROM t OR ex.company_id IS DISTINCT FROM c THEN RAISE EXCEPTION 'SCOPE_NOT_GRANTED'; END IF;
 IF ex.status='REVOKED' THEN RETURN 'REVOKED'; END IF;
 UPDATE change_ledger.grants g SET status='REVOKED' WHERE g.grant_id=p_grant_id;
 PERFORM change_ledger.append_event(t,c,NULL,'BUDGET_GRANT_REVOKED',
  jsonb_build_object('grant_id',p_grant_id,'by',who));
 RETURN 'REVOKED';
END $fn$;

-- ================================================================== B4 anchor gap bound to the external head
ALTER TABLE change_ledger.holds ADD COLUMN IF NOT EXISTS ext_seq bigint;
ALTER TABLE change_ledger.holds ADD COLUMN IF NOT EXISTS ext_head_hash text;

-- Witness side of the two-person ANCHOR_GAP release: an independent recovery witness states that the lost history
-- was reconciled out of band (evidence class a or b, bound to the external head the hold remembers).
CREATE TABLE IF NOT EXISTS change_ledger.hold_cosigns(
 cosign_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id text NOT NULL, company_id text NOT NULL,
 hold_id uuid NOT NULL REFERENCES change_ledger.holds(hold_id),
 signer text NOT NULL, evidence jsonb NOT NULL,
 signed_at timestamptz NOT NULL DEFAULT clock_timestamp(), consumed_at timestamptz
);

CREATE OR REPLACE FUNCTION change_ledger.check_anchor(t text, c text, p_ext_seq bigint, p_ext_head_hash text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE ok boolean; opened integer := 0; b record;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_ext_seq IS NULL OR p_ext_seq<1 OR p_ext_head_hash IS NULL OR p_ext_head_hash !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.seq=p_ext_seq AND e.hash=p_ext_head_hash) INTO ok;
 IF NOT ok THEN
  -- an open hold without an external head (declared gap) or with a lower one remembers the newest anchored head
  UPDATE change_ledger.holds h SET ext_seq=p_ext_seq, ext_head_hash=p_ext_head_hash
   WHERE h.tenant_id=t AND h.company_id=c AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
    AND (h.ext_seq IS NULL OR h.ext_seq<p_ext_seq);
  FOR b IN SELECT g.base_fingerprint FROM change_ledger.targets g WHERE g.tenant_id=t AND g.company_id=c
    AND NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
      AND h.base_fingerprint=g.base_fingerprint AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL)
    ORDER BY g.base_fingerprint LOOP
   INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,ext_seq,ext_head_hash)
   VALUES(t,c,b.base_fingerprint,'ANCHOR_GAP',p_ext_seq,p_ext_head_hash);
   opened := opened+1;
  END LOOP;
  PERFORM change_ledger.append_event(t,c,NULL,'ANCHOR_GAP',
   jsonb_build_object('ext_seq',p_ext_seq,'ext_head_hash',p_ext_head_hash));
 END IF;
 RETURN jsonb_build_object('ok',ok,'holds_opened',opened);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.anchor_gap_cosign(t text, c text, p_hold_id uuid, p_evidence jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE h change_ledger.holds%ROWTYPE; signer text; cid uuid;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 signer := change_ledger.caller_role();
 IF p_hold_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO h FROM change_ledger.holds x WHERE x.hold_id=p_hold_id AND x.tenant_id=t AND x.company_id=c;
 IF NOT FOUND THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 IF h.cause<>'ANCHOR_GAP' OR h.released_at IS NOT NULL OR h.ext_seq IS NULL THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_evidence IS NULL OR jsonb_typeof(p_evidence)<>'object'
  OR coalesce(p_evidence->>'class','') NOT IN ('a','b')
  OR jsonb_typeof(p_evidence->'reconciliation') IS DISTINCT FROM 'string'
  OR length(coalesce(p_evidence->>'reconciliation',''))=0
  OR p_evidence->'ext_seq' IS DISTINCT FROM to_jsonb(h.ext_seq)
  OR p_evidence->>'ext_head_hash' IS DISTINCT FROM h.ext_head_hash THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,signer,'recovery_witness');
 INSERT INTO change_ledger.hold_cosigns(tenant_id,company_id,hold_id,signer,evidence)
 VALUES(t,c,p_hold_id,signer,p_evidence) RETURNING cosign_id INTO cid;
 RETURN cid;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.release_hold(
 t text, c text, p_hold_id uuid, p_release_evidence jsonb
) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE h change_ledger.holds%ROWTYPE; ts timestamptz; cp bigint; two boolean := false;
 who text; cs change_ledger.hold_cosigns%ROWTYPE; cos_text text;
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
  IF h.ext_seq IS NOT NULL AND p_release_evidence ? 'two_person_cosign' THEN
   -- operator path with evidence: an independent witness cosigned the reconciliation of the lost head
   cos_text := p_release_evidence->>'two_person_cosign';
   IF cos_text IS NULL OR cos_text !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
    RAISE EXCEPTION 'SCHEMA_INVALID';
   END IF;
   SELECT * INTO cs FROM change_ledger.hold_cosigns w
    WHERE w.cosign_id=cos_text::uuid AND w.hold_id=p_hold_id AND w.consumed_at IS NULL FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'COMPLETION_PROOF_MISSING'; END IF;
   who := change_ledger.caller_role();
   IF change_ledger.same_person(t,c,who,cs.signer) THEN RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT'; END IF;
   PERFORM change_ledger.assert_capability(t,c,who,'operator');
   PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
   IF change_ledger.registry_enforced(t,c)
    AND (change_ledger.person_of(t,c,who) IS NULL OR change_ledger.person_of(t,c,cs.signer) IS NULL) THEN
    RAISE EXCEPTION 'NOT_ENTITLED';
   END IF;
   IF NOT change_ledger.chain_ok(t,c) THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
   UPDATE change_ledger.hold_cosigns w SET consumed_at=clock_timestamp() WHERE w.cosign_id=cs.cosign_id;
   two := true;
  ELSE
   IF p_release_evidence->'store_accepted' IS DISTINCT FROM 'true'::jsonb THEN
    RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
   END IF;
   -- B4: the ledger must contain the externally anchored event itself (history reconciled); a checkpoint of the
   -- restored (older) head proves nothing about the lost head
   IF h.ext_seq IS NOT NULL AND NOT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t
     AND e.company_id=c AND e.seq=h.ext_seq AND e.hash=h.ext_head_hash) THEN
    RAISE EXCEPTION 'AUDIT_UNAVAILABLE';
   END IF;
   SELECT k.seq INTO cp FROM change_ledger.checkpoints k
    JOIN change_ledger.events e ON e.tenant_id=k.tenant_id AND e.company_id=k.company_id
     AND e.seq=k.ledger_seq AND e.hash=k.head_hash
    WHERE k.tenant_id=t AND k.company_id=c AND k.sink_kind='REAL' AND k.read_back_confirmed
     AND k.written_at>=h.opened_at ORDER BY k.seq DESC LIMIT 1;
   IF cp IS NULL THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
   IF NOT change_ledger.chain_ok(t,c) THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
  END IF;
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
  jsonb_build_object('hold_id',p_hold_id,'cause',h.cause,'two_person',two));
 RETURN ts;
END $fn$;

-- ================================================================== B5 constants, policy, validation
CREATE OR REPLACE FUNCTION change_ledger.sweep_constants() RETURNS jsonb
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT '{"claim_ttl_seconds":120,"permit_ttl_seconds":60,"t12_window_seconds":900,"t12_max_attempts":5,
  "anchor_gap_window_seconds":900,"verify_max_attempts":3}'::jsonb
$fn$;

-- cadence knobs a worker may still tune (they only move WHEN a due item is looked at, never a contract bound)
CREATE OR REPLACE FUNCTION change_ledger.sweep_tunables() RETURNS jsonb
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT '{"deadline_seconds":120,"post_deadline_seconds":300,"t12_interval_seconds":180,"t12_jitter_seconds":30,
  "verify_interval_seconds":180,"batch_size":100}'::jsonb
$fn$;

CREATE TABLE IF NOT EXISTS change_ledger.sweep_policy(
 tenant_id text NOT NULL, company_id text NOT NULL,
 params jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(params)='object'),
 updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id)
);
CREATE TABLE IF NOT EXISTS change_ledger.sweep_failures(
 tenant_id text NOT NULL, company_id text NOT NULL,
 subject_id uuid NOT NULL, stage text NOT NULL,
 failures integer NOT NULL DEFAULT 1, last_sqlstate text, last_error text,
 first_at timestamptz NOT NULL DEFAULT clock_timestamp(), last_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(subject_id,stage)
);

CREATE OR REPLACE FUNCTION change_ledger.sweep_effective(t text, c text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
 SELECT change_ledger.sweep_constants()
  || coalesce((SELECT sp.params FROM change_ledger.sweep_policy sp WHERE sp.tenant_id=t AND sp.company_id=c),'{}'::jsonb)
$fn$;

-- Range-checked jsonb overrides: every value is a number inside [0, 1e7] (counts and sizes integral, batch_size >= 1),
-- so no later cast can raise 22P02 / 22003; anything else is SCHEMA_INVALID.
CREATE OR REPLACE FUNCTION change_ledger.sweep_params(p_params jsonb, p_defaults jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE k text; v jsonb; num numeric;
BEGIN
 IF p_params IS NULL THEN RETURN p_defaults; END IF;
 IF jsonb_typeof(p_params)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 FOR k, v IN SELECT * FROM jsonb_each(p_params) LOOP
  IF NOT (p_defaults ? k) THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF jsonb_typeof(v)<>'number' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  num := (v#>>'{}')::numeric;
  IF num<0 OR num>10000000 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF (k LIKE '%\_attempts' OR k LIKE '%\_size') AND num<>trunc(num) THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
  IF k='batch_size' AND (num<1 OR num>500) THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 END LOOP;
 RETURN p_defaults || p_params;
END $fn$;

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
   ('t12_max_attempts',1,50),('anchor_gap_window_seconds',60,86400),('verify_max_attempts',1,20)
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

-- committed failure accounting of one sweep item (called from the exception handler of its subtransaction)
CREATE OR REPLACE FUNCTION change_ledger.sweep_item_failed(t text, c text, p_subject uuid, p_stage text,
 p_sqlstate text, p_msg text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE cid uuid;
BEGIN
 INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
 VALUES(t,c,p_subject,p_stage,p_sqlstate,left(coalesce(p_msg,''),300))
 ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
  last_sqlstate=EXCLUDED.last_sqlstate, last_error=EXCLUDED.last_error, last_at=clock_timestamp();
 SELECT r.change_id INTO cid FROM change_ledger.records r WHERE r.change_id=p_subject;
 PERFORM change_ledger.append_event(t,c,cid,'SWEEP_ITEM_FAILED',
  jsonb_build_object('stage',p_stage,'subject',p_subject,'sqlstate',p_sqlstate,'error',left(coalesce(p_msg,''),300),
   'alert',true));
END $fn$;

-- ================================================================== B5 token before record, row locks before the chain
CREATE OR REPLACE FUNCTION change_ledger.cancel_permit(
 t text, c text, p_change_id uuid, p_generation bigint
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id ORDER BY ct.generation FOR UPDATE;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF NOT change_ledger.dispatch_cas(p_change_id,p_generation,'PERMITTED','CANCELLED_UNDISPATCHED') THEN
  RETURN false;
 END IF;
 UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE change_id=p_change_id AND generation=p_generation;
 PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
 UPDATE change_ledger.records SET
  authorization_state=CASE WHEN rec.expires_at<=clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
  execution_state='NOT_STARTED', dispatch_state='CANCELLED_UNDISPATCHED', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PERMIT_CANCELLED',
  jsonb_build_object('generation',p_generation));
 RETURN true;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.permit_not_issued_internal(t text, c text, p_change_id uuid, p_ttl_seconds double precision)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; started timestamptz;
BEGIN
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id ORDER BY ct.generation FOR UPDATE;
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

CREATE OR REPLACE FUNCTION change_ledger.complete_lock_busy(
 t text, c text, p_change_id uuid, p_generation bigint, p_completion uuid,
 p_params jsonb DEFAULT '{}'::jsonb
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE p jsonb; rec change_ledger.records%ROWTYPE; k change_ledger.sweep_counters%ROWTYPE; due_in double precision;
 ev change_ledger.evidence_records; ref jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 p := change_ledger.sweep_params(p_params,
  '{"lock_busy_max_attempts":5,"lock_busy_interval_seconds":180,"lock_busy_jitter_seconds":30,
    "lock_busy_window_seconds":900}'::jsonb);
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id ORDER BY ct.generation FOR UPDATE;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN
  IF rec.execution_state='FAILED_APPLY' THEN RETURN rec.execution_state; END IF;
  IF rec.execution_state='NOT_STARTED' AND rec.authorization_state='APPROVED' THEN RETURN 'APPROVED'; END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_completion IS NULL THEN RAISE EXCEPTION 'WRITE_REFUSED'; END IF;
 ev := change_ledger.typed_completion(t,c,p_change_id,p_generation,p_completion,'PRE_WRITE_REFUSAL',
  ARRAY['LOCK_BUSY']);
 ref := jsonb_build_object('evidence_id',ev.evidence_id,'content_hash',ev.content_hash);
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
   jsonb_build_object('attempt',k.attempts,'next_attempt_at',k.next_attempt_at,'evidence',ref));
  RETURN 'APPROVED';
 END IF;
 UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(), close_reason='DEFINITE'
  WHERE subject_id=p_change_id AND kind='LOCK_BUSY' AND closed_at IS NULL;
 RETURN change_ledger.complete(t,c,p_change_id,p_generation,'PRE_WRITE_REFUSAL',ref,ev.content->'no_effect_proof');
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_core(t text, c text, p_change_id uuid, p_cause text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; new_auth text;
BEGIN
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id ORDER BY ct.generation FOR UPDATE;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.authorization_state IN ('VOIDED','REVOKED') THEN RETURN rec.authorization_state; END IF;
 IF rec.authorization_state NOT IN ('APPROVED','CLAIMED') OR rec.execution_state<>'NOT_STARTED'
  OR rec.dispatch_state IN ('PERMITTED','DISPATCHED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF p_cause='EPOCH_DEPENDENCY' AND change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';   -- unrelated epoch changes never void
 END IF;
 new_auth := CASE WHEN p_cause='EPOCH_DEPENDENCY' THEN 'VOIDED' ELSE 'REVOKED' END;
 IF rec.authorization_state='CLAIMED' THEN
  UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE change_id=p_change_id AND state='ISSUED';
  PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
 END IF;
 UPDATE change_ledger.records SET authorization_state=new_auth, execution_state='NOT_STARTED',
  updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'REVOKED',
  jsonb_build_object('cause',p_cause,'authorization',new_auth,'was_claimed',rec.authorization_state='CLAIMED'));
 RETURN new_auth;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_stale(t text, c text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n integer := 0; cid uuid; ids uuid[];
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
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
   PERFORM change_ledger.revoke_core(t,c,cid,'EPOCH_DEPENDENCY');
   n := n+1;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'REVOKE_STALE',SQLSTATE,SQLERRM);
  END;
 END LOOP;
 RETURN n;
END $fn$;

-- the epoch ROW is bumped first; the event is appended by the caller after all of its row writes
CREATE OR REPLACE FUNCTION change_ledger.epoch_row_bump(t text, c text, k text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE v bigint;
BEGIN
 INSERT INTO change_ledger.epochs(tenant_id,company_id,epoch_key,value) VALUES(t,c,k,1)
 ON CONFLICT(tenant_id,company_id,epoch_key) DO UPDATE SET value=change_ledger.epochs.value+1,
  updated_at=clock_timestamp()
 RETURNING value INTO v;
 RETURN v;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.bump_epoch_internal(t text, c text, k text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE v bigint;
BEGIN
 v := change_ledger.epoch_row_bump(t,c,k);
 PERFORM change_ledger.append_event(t,c,NULL,'EPOCH_BUMPED',jsonb_build_object('key',k,'value',v));
 RETURN v;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_principal(
 t text, c text, p_principal text, p_person_id text, p_capabilities text[], p_active boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; v bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_principal IS NULL OR p_principal='' OR p_person_id IS NULL OR p_person_id=''
  OR p_capabilities IS NULL OR p_active IS NULL
  OR NOT (p_capabilities <@ ARRAY['approver','operator','recovery_witness','requester']::text[]) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_principal) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities,active,registered_by)
 VALUES(t,c,p_principal,p_person_id,p_capabilities,p_active,who)
 ON CONFLICT(tenant_id,company_id,principal) DO UPDATE SET person_id=EXCLUDED.person_id,
  capabilities=EXCLUDED.capabilities, active=EXCLUDED.active, registered_by=EXCLUDED.registered_by,
  updated_at=clock_timestamp();
 v := change_ledger.epoch_row_bump(t,c,'principal:'||p_principal);        -- row locks first, chain last
 PERFORM change_ledger.append_event(t,c,NULL,'PRINCIPAL_REGISTERED',
  jsonb_build_object('principal',p_principal,'person_id',p_person_id,'capabilities',to_jsonb(p_capabilities),
   'active',p_active,'by',who));
 PERFORM change_ledger.append_event(t,c,NULL,'EPOCH_BUMPED',
  jsonb_build_object('key','principal:'||p_principal,'value',v));
 RETURN v;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_target(
 t text, c text, p_base text, p_org text, p_class text, p_status text, p_permission_expires_at timestamptz
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE who text; cls text; v bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 cls := change_ledger.norm_target_class(p_class);
 IF p_base IS NULL OR p_base='' OR p_org IS NULL OR p_org='' OR cls IS NULL
  OR p_status IS NULL OR p_status NOT IN ('ACTIVE','REVOKED') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class,
  status,permission_expires_at,registered_by)
 VALUES(t,c,p_base,p_org,cls,p_status,p_permission_expires_at,who)
 ON CONFLICT(tenant_id,company_id,base_fingerprint) DO UPDATE SET organization_ref=EXCLUDED.organization_ref,
  target_class=EXCLUDED.target_class, status=EXCLUDED.status,
  permission_expires_at=EXCLUDED.permission_expires_at, registered_by=EXCLUDED.registered_by,
  epoch=change_ledger.targets.epoch+1;
 v := change_ledger.epoch_row_bump(t,c,'target:'||p_base);
 PERFORM change_ledger.append_event(t,c,NULL,'TARGET_REGISTERED',
  jsonb_build_object('base',p_base,'organization',p_org,'class',cls,'status',p_status,'by',who));
 PERFORM change_ledger.append_event(t,c,NULL,'EPOCH_BUMPED',
  jsonb_build_object('key','target:'||p_base,'value',v));
 RETURN v;
END $fn$;

-- ================================================================== B5 recover_sweep: bounded batch, locks first
-- Phase 1 selects a bounded batch per stage (healthy items before items that failed before) and locks ALL of it
-- (tokens, then records) before the first append; phase 2 runs one subtransaction per item. A failing item is
-- rolled back alone, counted in sweep_failures and announced by SWEEP_ITEM_FAILED; the sweep continues.
CREATE OR REPLACE FUNCTION change_ledger.recover_sweep(t text, c text, p_params jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
 p jsonb; v_mode text; v_start timestamptz := clock_timestamp(); n integer := 0; bsz integer;
 cid uuid; tokid uuid; gen bigint; x record; rec change_ledger.records%ROWTYPE; ctr change_ledger.sweep_counters%ROWTYPE;
 dl timestamptz; disp timestamptz; started timestamptz; cnt integer; due_in double precision; vres jsonb;
 c_t5x uuid[]; c_t6c uuid[]; c_t6r uuid[]; c_t9 uuid[]; c_t3 uuid[]; c_void uuid[] := '{}'; c_t12 uuid[];
 c_gap uuid[]; c_ver uuid[]; ids uuid[];
 a_t5x uuid[] := '{}'; a_t6c uuid[] := '{}'; a_t6r uuid[] := '{}'; a_t9 uuid[] := '{}'; a_t3 uuid[] := '{}';
 a_void uuid[] := '{}'; a_t12a uuid[] := '{}'; a_t12 uuid[] := '{}'; a_gap uuid[] := '{}';
 a_vdue uuid[] := '{}'; a_vexh uuid[] := '{}'; a_fail jsonb := '[]'::jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
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
    AND (v_mode='REVOKE' OR ct.issued_at<=clock_timestamp()-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f WHERE f.subject_id=r.change_id AND f.stage='T5x'),0),
    ct.issued_at LIMIT bsz) s;
 SELECT coalesce(array_agg(s.change_id),'{}'::uuid[]) INTO c_t6c FROM (
  SELECT dp.change_id FROM change_ledger.dispatch_permits dp JOIN change_ledger.records r ON r.change_id=dp.change_id
   WHERE r.tenant_id=t AND r.company_id=c AND dp.state='PERMITTED' AND dp.expires_at<=clock_timestamp()
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
 ids := c_t5x||c_t6c||c_t6r||c_t9||c_t3||c_void||c_t12||c_gap||c_ver;
 PERFORM 1 FROM change_ledger.claim_tokens ct WHERE ct.change_id = ANY(ids) ORDER BY ct.token_id FOR UPDATE;
 PERFORM 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c AND r.change_id = ANY(ids)
  ORDER BY r.change_id FOR UPDATE;

 -- ---------------- phase 2: one subtransaction per item
 -- T5x: claim TTL elapsed (any mode: REVOKE releases every live claim and voids its approval).
 FOREACH cid IN ARRAY c_t5x LOOP
  BEGIN
   SELECT ct.token_id INTO tokid FROM change_ledger.claim_tokens ct WHERE ct.change_id=cid AND ct.state='ISSUED'
    AND (v_mode='REVOKE' OR ct.issued_at<=clock_timestamp()-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision));
   IF tokid IS NOT NULL THEN
    IF change_ledger.release_claim_internal(t,c,tokid,v_mode='REVOKE') THEN
     DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='T5x';
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
    AND dp.state='PERMITTED' AND dp.expires_at<=clock_timestamp();
   IF gen IS NOT NULL THEN
    IF change_ledger.cancel_permit(t,c,cid,gen) THEN
     DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='T6c';
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
   IF change_ledger.permit_not_issued_internal(t,c,cid,(p->>'permit_ttl_seconds')::double precision) THEN
    DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='T6r';
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
     DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='T9';
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
    DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='T3';
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
    DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='VOID';
    n := n+1; a_void := a_void||rec.change_id;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'VOID',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','VOID','subject',cid));
  END;
 END LOOP;

 -- T12: durable attempt counter for APPLY_UNKNOWN (max attempts / window are ledger constants or policy).
 FOREACH cid IN ARRAY c_t12 LOOP
  BEGIN
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND rec.execution_state='APPLY_UNKNOWN' THEN
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
       PERFORM change_ledger.triage_internal(t,c,rec.change_id,'ATTEMPTS');
       a_t12 := a_t12||rec.change_id;
      ELSIF ctr.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp() THEN
       PERFORM change_ledger.triage_internal(t,c,rec.change_id,'WINDOW');
       a_t12 := a_t12||rec.change_id;
      ELSE
       PERFORM change_ledger.append_event(t,c,rec.change_id,'RESOLVE_ATTEMPT',
        jsonb_build_object('attempt',ctr.attempts,'next_attempt_at',ctr.next_attempt_at));
       a_t12a := a_t12a||rec.change_id;
      END IF;
     ELSIF ctr.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=clock_timestamp() THEN
      IF change_ledger.triage_internal(t,c,rec.change_id,'WINDOW') THEN
       n := n+1; a_t12 := a_t12||rec.change_id;
      END IF;
     END IF;
    END IF;
    DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='T12';
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
   INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,closed_at,close_reason)
   VALUES(t,c,x.hold_id,'ANCHOR_GAP',x.opened_at,clock_timestamp(),'BOUND_EXCEEDED')
   ON CONFLICT(subject_id,kind) DO NOTHING;
   GET DIAGNOSTICS cnt = ROW_COUNT;
   IF cnt=1 THEN
    PERFORM change_ledger.append_event(t,c,NULL,'ANCHOR_GAP_BOUND_EXCEEDED',
     jsonb_build_object('hold_id',x.hold_id,'base_fingerprint',x.base_fingerprint,'alert',true));
    n := n+1;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,x.hold_id,'GAP_BOUND',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','GAP_BOUND','subject',x.hold_id));
  END;
 END LOOP;
 FOREACH cid IN ARRAY c_gap LOOP
  BEGIN
   IF change_ledger.triage_internal(t,c,cid,'ANCHOR_GAP_WINDOW') THEN
    DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='GAP';
    n := n+1; a_gap := a_gap||cid;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'GAP',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','GAP','subject',cid));
  END;
 END LOOP;

 -- T13/T14 stuck verification: APPLIED but not verified. The bound (verify_max_attempts) is a ledger constant
 -- or the operator's policy; the bound reached without a verdict ends in FAILED_VERIFY / UNKNOWN + halt.
 FOREACH cid IN ARRAY c_ver LOOP
  BEGIN
   SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=cid FOR UPDATE;
   IF FOUND AND rec.execution_state='APPLIED' AND rec.verification_state='NOT_VERIFIED' THEN
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
     n := n+1;
     IF (vres->>'exhausted')::boolean THEN a_vexh := a_vexh||rec.change_id; ELSE a_vdue := a_vdue||rec.change_id; END IF;
    END IF;
    DELETE FROM change_ledger.sweep_failures WHERE subject_id=cid AND stage='VERIFY';
   END IF;
  EXCEPTION WHEN OTHERS THEN
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'VERIFY',SQLSTATE,SQLERRM);
   a_fail := a_fail||jsonb_build_array(jsonb_build_object('stage','VERIFY','subject',cid));
  END;
 END LOOP;

 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,started_at,finished_at,changed)
 VALUES(t,c,v_start,clock_timestamp(),n);
 RETURN jsonb_build_object('changed',n,'T5x',to_jsonb(a_t5x),'T6c',to_jsonb(a_t6c),'T6r',to_jsonb(a_t6r),
  'T9',to_jsonb(a_t9),'T3',to_jsonb(a_t3),'VOIDED',to_jsonb(a_void),'T12_ATTEMPT',to_jsonb(a_t12a),
  'T12',to_jsonb(a_t12),'ANCHOR_GAP_TRIAGE',to_jsonb(a_gap),'VERIFY_DUE',to_jsonb(a_vdue),
  'VERIFY_EXHAUSTED',to_jsonb(a_vexh),'FAILED',a_fail);
END $fn$;

-- ownership, RLS and privileges of the B4 / B5 objects
DO $fn$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY['hold_cosigns','sweep_policy','sweep_failures'] LOOP
  EXECUTE format('ALTER TABLE change_ledger.%I OWNER TO ledger_owner',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('DROP POLICY IF EXISTS owner_all ON change_ledger.%I',tbl);
  EXECUTE format('DROP POLICY IF EXISTS scope_isolation ON change_ledger.%I',tbl);
  EXECUTE format('CREATE POLICY owner_all ON change_ledger.%I FOR ALL TO ledger_owner USING (true) WITH CHECK (true)',tbl);
  EXECUTE format('CREATE POLICY scope_isolation ON change_ledger.%I FOR ALL USING (change_ledger.row_in_scope(tenant_id,company_id)) WITH CHECK (change_ledger.row_in_scope(tenant_id,company_id))',tbl);
  EXECUTE format('GRANT SELECT ON change_ledger.%I TO auditor_role, worker_role, operator_role',tbl);
 END LOOP;
END $fn$;
GRANT EXECUTE ON FUNCTION change_ledger.set_sweep_policy(text,text,jsonb),
 change_ledger.anchor_gap_cosign(text,text,uuid,jsonb) TO operator_role;

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

GRANT EXECUTE ON FUNCTION change_ledger.validate(text,text,uuid),
 change_ledger.declare_budget(text,text,uuid,uuid,text,numeric,boolean,boolean) TO requester_role;
GRANT EXECUTE ON FUNCTION change_ledger.budget_revoke(text,text,uuid) TO operator_role;
-- B2: the identity / registry helpers are internals (they were executable by every runtime role)
REVOKE EXECUTE ON FUNCTION change_ledger.person_of(text,text,text), change_ledger.same_person(text,text,text,text),
 change_ledger.epoch_value(text,text,text), change_ledger.registry_enforced(text,text)
 FROM requester_role, approver_role, operator_role, writer_role, worker_role, auditor_role, checkpoint_role;

$body$;
END IF;
END $mig$;
COMMIT;
