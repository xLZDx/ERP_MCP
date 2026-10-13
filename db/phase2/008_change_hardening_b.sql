-- R2/G1 S13 hardening, batch B (docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md items B1-B6). Applies after 007.
-- Apply ONLY to a verified disposable PostgreSQL database (checksum precondition: living.record_migration).
-- Lock order: see section B5 (added later)
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
