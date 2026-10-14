-- R2/G1 S13 A7 follow-up: S12-APPROVAL-2, the shared canonical approval digest
-- (docs/phase2/S12_APPROVAL_DIGEST_2_SPEC.md; GPT-PM ruling e5d92b7a, Option 2). Applies after 008.
-- Apply ONLY to a verified disposable PostgreSQL database (checksum precondition: living.record_migration).
-- NON-GATING PROTOTYPE: not gate evidence; no real 1C write.
--
--  1. The canonical approval text is stored by the ledger (change_ledger.approval_envelopes), one immutable row per
--     (change_id, approval_nonce): no UPDATE, DELETE or TRUNCATE. approval_digest = sha256 of the stored text bytes
--     (UTF-8), computed live from the stored text. jsonb::text is never the contract: the text is produced by one
--     trusted service (change.proposal.approval_canonical_text) and the ledger only accepts a text that is
--     byte-identical to its own canonical re-serialization (change_ledger.canon_json: sorted keys, compact separators,
--     ASCII-only with \uXXXX escapes, integers only).
--  2. The closed field list (20 top-level keys) is compared with the stored change when the text is stored AND when
--     approve runs: every field the ledger holds (identity, scope, payload_digest, target, lineage, declared class,
--     allowed effects, declared budget, duplicate override pair, rule table version, epoch pairs, expires_at, nonce)
--     must equal the stored change, so a material change after preview makes approve fail with DIGEST_MISMATCH
--     (a new nonce + a new text is required). The payload itself is recomputed: sha256(canon({payload, target_version}))
--     must equal payload_digest.
--  3. approve compares only the version-2 digest and records approvals.digest_version / envelope_id. Approvals made
--     under S12-APPROVAL-SQL-1 keep that label (column default) and cannot authorize anything: unclaimed approved
--     changes are voided by this migration and claim / begin_apply / issue_permit / verify_dispatch_payload refuse
--     an approval that is not a version-2 approval (APPROVAL_VOIDED).
--  4. begin_apply and issue_permit recompute the payload digest from the stored envelope and compare the identity
--     and payload binding fields (assert_approval_current); verify_dispatch_payload lets the writer check the exact
--     payload it is about to send against the stored envelope.
-- NAMED LIMITS (also in the spec): business_state_digest and preview_digest are opaque 64-hex values bound by the
-- stored text; the ledger holds no observed 1C state or preview to recompute them from. record_call (the dispatch
-- CAS) is not coupled to verify_dispatch_payload (that would change the port signature); the real writer must call
-- it before dispatch. The approval type and the kill-switch epoch stay outside the envelope.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('009', ARRAY['001','002','003','004','005','006','007','008']) THEN
EXECUTE $body$

-- ================================================================== storage
ALTER TABLE change_ledger.approvals ADD COLUMN IF NOT EXISTS digest_version text NOT NULL DEFAULT 'S12-APPROVAL-SQL-1';
ALTER TABLE change_ledger.approvals ADD COLUMN IF NOT EXISTS envelope_id uuid;
ALTER TABLE change_ledger.approvals DROP CONSTRAINT IF EXISTS approvals_digest_version_chk;
ALTER TABLE change_ledger.approvals ADD CONSTRAINT approvals_digest_version_chk
 CHECK(digest_version IN ('S12-APPROVAL-SQL-1','S12-APPROVAL-2'));

CREATE TABLE IF NOT EXISTS change_ledger.approval_envelopes(
 envelope_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 seq bigint GENERATED ALWAYS AS IDENTITY,
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id),
 tenant_id text NOT NULL, company_id text NOT NULL,
 approval_nonce text NOT NULL REFERENCES change_ledger.approval_nonces(nonce),
 digest_version text NOT NULL CHECK(digest_version='S12-APPROVAL-2'),
 canonical_text text NOT NULL CHECK(length(canonical_text)>0 AND octet_length(canonical_text)<=262144),
 stored_by text NOT NULL, stored_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(change_id, approval_nonce)
);
ALTER TABLE change_ledger.approval_envelopes OWNER TO ledger_owner;
ALTER TABLE change_ledger.approval_envelopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_ledger.approval_envelopes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS owner_all ON change_ledger.approval_envelopes;
CREATE POLICY owner_all ON change_ledger.approval_envelopes FOR ALL TO ledger_owner USING (true) WITH CHECK (true);
DROP TRIGGER IF EXISTS approval_envelopes_immutable ON change_ledger.approval_envelopes;
CREATE TRIGGER approval_envelopes_immutable BEFORE UPDATE OR DELETE ON change_ledger.approval_envelopes
 FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation();
DROP TRIGGER IF EXISTS approval_envelopes_no_truncate ON change_ledger.approval_envelopes;
CREATE TRIGGER approval_envelopes_no_truncate BEFORE TRUNCATE ON change_ledger.approval_envelopes
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation();
ALTER TABLE change_ledger.approval_envelopes ADD CONSTRAINT approval_envelopes_scope_fk
 FOREIGN KEY(tenant_id,company_id,change_id) REFERENCES change_ledger.records(tenant_id,company_id,change_id);

-- ================================================================== canonical JSON (equal to the offline canonical_json)
CREATE OR REPLACE FUNCTION change_ledger.canon_string(s text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE o text := '"'; i int; n int; ch text; cp int; bs text := chr(92); v int;
BEGIN
 n := char_length(s);
 FOR i IN 1..n LOOP
  ch := substr(s,i,1); cp := ascii(ch);
  IF cp = 34 THEN o := o||bs||'"';
  ELSIF cp = 92 THEN o := o||bs||bs;
  ELSIF cp = 10 THEN o := o||bs||'n';
  ELSIF cp = 13 THEN o := o||bs||'r';
  ELSIF cp = 9 THEN o := o||bs||'t';
  ELSIF cp = 8 THEN o := o||bs||'b';
  ELSIF cp = 12 THEN o := o||bs||'f';
  ELSIF cp BETWEEN 32 AND 126 THEN o := o||ch;
  ELSIF cp < 65536 THEN o := o||bs||'u'||lpad(to_hex(cp),4,'0');
  ELSE
   v := cp - 65536;
   o := o||bs||'u'||to_hex(55296+(v>>10))||bs||'u'||lpad(to_hex(56320+(v&1023)),4,'0');
  END IF;
 END LOOP;
 RETURN o||'"';
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.canon_json(v jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE ty text := jsonb_typeof(v); r text;
BEGIN
 IF ty IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF ty = 'null' THEN RETURN 'null'; END IF;
 IF ty = 'boolean' THEN RETURN v::text; END IF;
 IF ty = 'string' THEN RETURN change_ledger.canon_string(v #>> '{}'); END IF;
 IF ty = 'number' THEN
  IF v::text !~ '^-?(0|[1-9][0-9]*)$' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;   -- no floats in the contract
  RETURN v::text;
 END IF;
 IF ty = 'array' THEN
  SELECT '['||coalesce(string_agg(change_ledger.canon_json(e.val),',' ORDER BY e.ord),'')||']' INTO r
   FROM jsonb_array_elements(v) WITH ORDINALITY e(val,ord);
  RETURN r;
 END IF;
 SELECT '{'||coalesce(string_agg(change_ledger.canon_string(e.k)||':'||change_ledger.canon_json(e.val),',' ORDER BY e.k COLLATE "C"),'')||'}'
  INTO r FROM jsonb_each(v) e(k,val);
 RETURN r;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.text_digest(p_text text) RETURNS text
LANGUAGE sql STABLE AS $fn$
 SELECT encode(sha256(convert_to(p_text,'UTF8')),'hex')
$fn$;

-- payload digest (CT2): sha256 of canonical {"payload": <payload or {}>, "target_version": <tv or null>}
CREATE OR REPLACE FUNCTION change_ledger.payload_digest_of(p_payload jsonb, p_target_version text) RETURNS text
LANGUAGE sql STABLE AS $fn$
 SELECT change_ledger.text_digest(change_ledger.canon_json(
  jsonb_build_object('payload',coalesce(p_payload,'{}'::jsonb),'target_version',p_target_version)))
$fn$;

-- ================================================================== envelope: expected fields and checks
-- Everything the ledger itself holds, in the shape of the closed field list. payload, business_state_digest and
-- preview_digest are not held by the ledger (named limit) and are only shape-checked.
CREATE OR REPLACE FUNCTION change_ledger.envelope_expected(p_rec change_ledger.records, p_nonce text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $fn$
DECLARE cb change_ledger.change_budget%ROWTYPE; bk change_ledger.business_keys%ROWTYPE;
 bud jsonb := 'null'::jsonb; dov jsonb := 'null'::jsonb; deps jsonb;
BEGIN
 SELECT * INTO cb FROM change_ledger.change_budget b WHERE b.change_id=p_rec.change_id;
 IF FOUND THEN
  bud := jsonb_build_object('grant_id',cb.grant_id,'currency',cb.currency,'amount',trim_scale(cb.amount)::text,
   'counts_create_update',cb.counts_create_update,'counts_post',cb.counts_post);
 END IF;
 SELECT * INTO bk FROM change_ledger.business_keys b WHERE b.change_id=p_rec.change_id;
 IF FOUND AND bk.override_of IS NOT NULL THEN
  dov := jsonb_build_object('duplicate_of_change_or_ref',bk.override_of,'justification',bk.override_justification);
 END IF;
 -- sorted [key, epoch] pairs; principal entries are excluded (the approver's entry is added by approve itself)
 SELECT coalesce(jsonb_agg(jsonb_build_array(e.k,e.v) ORDER BY e.k COLLATE "C"),'[]'::jsonb) INTO deps
  FROM jsonb_each(p_rec.epoch_dependencies) e(k,v) WHERE e.k NOT LIKE 'principal:%';
 RETURN jsonb_build_object(
  'digest_version','S12-APPROVAL-2','change_id',p_rec.change_id,'kind',p_rec.kind,
  'scope',jsonb_build_object('tenant',p_rec.tenant_id,'company',p_rec.company_id,
   'organization',p_rec.organization_ref,'base_fingerprint',p_rec.base_fingerprint),
  'payload_digest',p_rec.payload_digest,'target_ref',p_rec.target_ref,'target_version',p_rec.target_version,
  'parent_change_id',p_rec.parent_change_id,'repair_for',p_rec.repair_for,
  'declared_target_class',p_rec.declared_target_class,
  'allowed_effects',change_ledger.allowed_effects(p_rec.kind),'budget',bud,'duplicate_override',dov,
  'rule_table_version','S11-RULES-2026-10-12','epoch_dependencies',deps,
  'expires_at',to_char(p_rec.expires_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'approval_nonce',p_nonce);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.envelope_subset(p_env jsonb, p_keys text[]) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT coalesce(jsonb_object_agg(e.k,e.v),'{}'::jsonb) FROM jsonb_each(p_env) e(k,v) WHERE e.k = ANY(p_keys)
$fn$;

-- the envelope payload as an object (JSON null = the kinds that carry none = {}); recompute against payload_digest
CREATE OR REPLACE FUNCTION change_ledger.envelope_payload_digest(p_env jsonb) RETURNS text
LANGUAGE plpgsql STABLE AS $fn$
DECLARE pl jsonb := p_env->'payload';
BEGIN
 IF pl IS NULL OR jsonb_typeof(pl) NOT IN ('null','object') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF jsonb_typeof(pl)='null' THEN pl := '{}'::jsonb; END IF;
 RETURN change_ledger.payload_digest_of(pl, p_env->>'target_version');
END $fn$;

-- full check (store and approve): closed key set + every ledger-held field + payload recompute
CREATE OR REPLACE FUNCTION change_ledger.envelope_check(p_rec change_ledger.records, p_env jsonb, p_nonce text)
RETURNS void LANGUAGE plpgsql STABLE AS $fn$
DECLARE pv jsonb; bsd jsonb;
BEGIN
 IF p_env IS NULL OR jsonb_typeof(p_env)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 pv := p_env->'preview_digest'; bsd := p_env->'business_state_digest';
 IF pv IS NULL OR jsonb_typeof(pv)<>'string' OR (pv #>> '{}') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF bsd IS NULL OR jsonb_typeof(bsd) NOT IN ('null','string')
  OR (jsonb_typeof(bsd)='string' AND (bsd #>> '{}') !~ '^[a-f0-9]{64}$') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_env->'payload' IS NULL OR jsonb_typeof(p_env->'payload') NOT IN ('null','object') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 -- operation-specific payload rule (as ChangeProposal): drafts carry an object, POST / UNPOST carry JSON null
 IF jsonb_typeof(p_env->'payload') IS DISTINCT FROM
    (CASE WHEN p_rec.kind IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN 'object' ELSE 'null' END) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF (p_env - 'payload' - 'business_state_digest' - 'preview_digest')
    IS DISTINCT FROM change_ledger.envelope_expected(p_rec,p_nonce) THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';          -- stale preview or substituted field
 END IF;
 IF change_ledger.envelope_payload_digest(p_env) IS DISTINCT FROM p_rec.payload_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';          -- payload does not recompute to the digest
 END IF;
END $fn$;

-- dispatch-time gate: the approval must be a version-2 approval whose stored text still hashes to the approved
-- digest, still binds this change's identity / scope / target / lineage / payload digest, and whose payload still
-- recomputes to payload_digest.
CREATE OR REPLACE FUNCTION change_ledger.assert_approval_current(t text, c text, p_rec change_ledger.records)
RETURNS void LANGUAGE plpgsql STABLE AS $fn$
DECLARE ap change_ledger.approvals%ROWTYPE; env change_ledger.approval_envelopes%ROWTYPE; ej jsonb;
 keys text[] := ARRAY['digest_version','change_id','kind','scope','payload_digest','target_ref','target_version',
                      'parent_change_id','repair_for'];
BEGIN
 SELECT * INTO ap FROM change_ledger.approvals a WHERE a.change_id=p_rec.change_id AND a.decision='APPROVE'
  ORDER BY a.approved_at DESC, a.approval_id DESC LIMIT 1;
 IF NOT FOUND OR ap.digest_version IS DISTINCT FROM 'S12-APPROVAL-2' OR ap.envelope_id IS NULL THEN
  RAISE EXCEPTION 'APPROVAL_VOIDED';          -- an S12-APPROVAL-SQL-1 approval authorizes nothing
 END IF;
 SELECT * INTO env FROM change_ledger.approval_envelopes e WHERE e.envelope_id=ap.envelope_id
  AND e.change_id=p_rec.change_id AND e.tenant_id=t AND e.company_id=c;
 IF NOT FOUND OR change_ledger.text_digest(env.canonical_text) IS DISTINCT FROM ap.digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 ej := env.canonical_text::jsonb;
 IF change_ledger.envelope_subset(ej,keys)
    IS DISTINCT FROM change_ledger.envelope_subset(change_ledger.envelope_expected(p_rec,env.approval_nonce),keys)
  OR change_ledger.envelope_payload_digest(ej) IS DISTINCT FROM p_rec.payload_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
END $fn$;

-- ================================================================== approval digest (live from the stored text)
CREATE OR REPLACE FUNCTION change_ledger.approval_digest(p_change_id uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $fn$
DECLARE txt text;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM change_ledger.records WHERE change_id=p_change_id) THEN
  RAISE EXCEPTION 'CHANGE_NOT_FOUND';
 END IF;
 SELECT e.canonical_text INTO txt FROM change_ledger.approval_envelopes e WHERE e.change_id=p_change_id
  ORDER BY e.seq DESC LIMIT 1;
 RETURN CASE WHEN txt IS NULL THEN NULL ELSE change_ledger.text_digest(txt) END;
END $fn$;

-- the single trusted service (the requester session) stores the canonical text once per (change, nonce)
CREATE OR REPLACE FUNCTION change_ledger.store_approval_text(t text, c text, p_change_id uuid, p_nonce text, p_text text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; nrow change_ledger.approval_nonces%ROWTYPE; ex change_ledger.approval_envelopes%ROWTYPE;
 env jsonb; dg text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_text IS NULL OR p_text='' OR octet_length(p_text)>262144 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 SELECT * INTO ex FROM change_ledger.approval_envelopes e WHERE e.change_id=p_change_id AND e.approval_nonce=p_nonce;
 IF FOUND THEN
  IF ex.canonical_text = p_text THEN RETURN change_ledger.text_digest(ex.canonical_text); END IF;   -- replay
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';                                    -- the stored text is immutable
 END IF;
 IF rec.lifecycle NOT IN ('PROPOSED','VALIDATED') OR rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED')
  OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 SELECT * INTO nrow FROM change_ledger.approval_nonces n WHERE n.nonce=p_nonce AND n.change_id=p_change_id;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 BEGIN
  env := p_text::jsonb;
 EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END;
 IF jsonb_typeof(env)<>'object' OR change_ledger.canon_json(env) IS DISTINCT FROM p_text THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';           -- only the canonical bytes are stored and hashed
 END IF;
 PERFORM change_ledger.envelope_check(rec,env,p_nonce);
 INSERT INTO change_ledger.approval_envelopes(change_id,tenant_id,company_id,approval_nonce,digest_version,
  canonical_text,stored_by) VALUES(p_change_id,t,c,p_nonce,'S12-APPROVAL-2',p_text,change_ledger.caller_role());
 dg := change_ledger.text_digest(p_text);
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVAL_TEXT_STORED',
  jsonb_build_object('digest',dg,'digest_version','S12-APPROVAL-2'));     -- digests only, never payload text
 RETURN dg;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.read_approval_text(t text, c text, p_change_id uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; txt text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF NOT (pg_has_role(who::name,'approver_role','USAGE') OR who IS NOT DISTINCT FROM rec.requester) THEN
  RAISE EXCEPTION 'CHANGE_NOT_FOUND';      -- the payload text is commercially sensitive: not for auditors
 END IF;
 SELECT e.canonical_text INTO txt FROM change_ledger.approval_envelopes e WHERE e.change_id=p_change_id
  ORDER BY e.seq DESC LIMIT 1;
 RETURN txt;
END $fn$;

-- the writer checks the exact payload it is about to send against the stored (approved) envelope
CREATE OR REPLACE FUNCTION change_ledger.verify_dispatch_payload(
 t text, c text, p_change_id uuid, p_generation bigint, p_payload text
) RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; pl jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
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
 RETURN true;
END $fn$;

-- ================================================================== read_status (007 body + version-2 fields)
CREATE OR REPLACE FUNCTION change_ledger.read_status(t text, c text, p_change_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; ap record; bk change_ledger.business_keys%ROWTYPE; dg text;
 en record;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF NOT (pg_has_role(who::name,'auditor_role','USAGE') OR pg_has_role(who::name,'approver_role','USAGE')
         OR who IS NOT DISTINCT FROM rec.requester) THEN
  RAISE EXCEPTION 'CHANGE_NOT_FOUND';
 END IF;
 SELECT a.approval_id, a.approver, a.digest, a.digest_version INTO ap FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.decision='APPROVE' ORDER BY a.approved_at DESC LIMIT 1;
 SELECT * INTO bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 SELECT e.approval_nonce, e.digest_version INTO en FROM change_ledger.approval_envelopes e
  WHERE e.change_id=p_change_id ORDER BY e.seq DESC LIMIT 1;
 dg := change_ledger.approval_digest(p_change_id);
 RETURN jsonb_build_object('change_id',rec.change_id,'kind',rec.kind,'requester',rec.requester,
  'tenant_id',rec.tenant_id,'company_id',rec.company_id,
  'base_fingerprint',rec.base_fingerprint,'organization_ref',rec.organization_ref,
  'target_ref',rec.target_ref,'target_version',rec.target_version,'parent_change_id',rec.parent_change_id,
  'repair_for',rec.repair_for,'payload_digest',rec.payload_digest,
  'lifecycle',rec.lifecycle,'authorization',rec.authorization_state,'execution',rec.execution_state,
  'verification',rec.verification_state,'call_ownership',rec.call_ownership,'attribution',rec.attribution,
  'effect_known',rec.effect_known,'reservation',rec.reservation_state,'dispatch',rec.dispatch_state,
  'claim_generation',rec.claim_generation,'expires_at',rec.expires_at,
  'epoch_dependencies',rec.epoch_dependencies,
  'epoch_current',change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies),
  'declared_target_class',rec.declared_target_class,
  'rule_table_version','S11-RULES-2026-10-12',
  'allowed_effects',change_ledger.allowed_effects(rec.kind),
  'business_key_hash',bk.key_hash,
  'approval_digest',dg,'approval_digest_version',en.digest_version,'approval_nonce',en.approval_nonce,
  'approved_digest',ap.digest,'approved_digest_version',ap.digest_version,
  'approval_id',ap.approval_id,'approver',ap.approver,
  'open_holds',(SELECT count(*) FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=rec.base_fingerprint AND h.released_at IS NULL),
  'evidence_count',(SELECT count(*) FROM change_ledger.evidence_records e WHERE e.change_id=p_change_id));
END $fn$;

-- ================================================================== approve (008 body; digest = stored version-2 text)
CREATE OR REPLACE FUNCTION change_ledger.approve(
 t text, c text, p_change_id uuid, p_nonce text, p_digest text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; v_approver text; nrow change_ledger.approval_nonces%ROWTYPE;
 aid uuid; bk change_ledger.business_keys%ROWTYPE; parent_req text; atype text; amfa boolean;
 env change_ledger.approval_envelopes%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_digest IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 v_approver := change_ledger.caller_role();
 PERFORM change_ledger.assert_switch_off(t,c);
 SELECT * INTO rec FROM change_ledger.records WHERE tenant_id=t AND company_id=c
  AND change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 -- B6e: a replay of the same approval (same nonce, digest, approver) returns the existing approval
 SELECT a.approval_id INTO aid FROM change_ledger.approvals a WHERE a.change_id=p_change_id AND a.nonce=p_nonce
  AND a.approver=v_approver AND a.decision='APPROVE' AND a.digest=p_digest AND a.digest_version='S12-APPROVAL-2'
  AND rec.authorization_state IN ('APPROVED','CLAIMED');
 IF FOUND THEN RETURN aid; END IF;
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
 -- S12-APPROVAL-2: only the digest of the stored text bound to THIS nonce can be approved
 SELECT * INTO env FROM change_ledger.approval_envelopes e WHERE e.change_id=p_change_id AND e.approval_nonce=p_nonce;
 IF NOT FOUND THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.approval_nonces n WHERE n.nonce=p_nonce AND n.change_id=p_change_id
    AND n.state='ISSUED' AND n.approver=v_approver) THEN
   RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
  END IF;
  RAISE EXCEPTION 'DIGEST_MISMATCH';          -- no canonical text was stored for this nonce
 END IF;
 IF p_digest IS DISTINCT FROM change_ledger.text_digest(env.canonical_text) THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 PERFORM change_ledger.envelope_check(rec,env.canonical_text::jsonb,p_nonce);   -- stale preview: DIGEST_MISMATCH
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 SELECT * INTO nrow FROM change_ledger.approval_nonces n
  WHERE n.nonce=p_nonce AND n.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.approver IS DISTINCT FROM v_approver THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 IF nrow.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'APPROVAL_EXPIRED';     -- B6d: the EXPIRED state is persisted by issue_approval_nonce and the sweep
 END IF;
 SELECT * INTO bk FROM change_ledger.business_keys WHERE change_id=p_change_id;
 IF FOUND AND bk.override_required AND NOT EXISTS(SELECT 1 FROM change_ledger.override_bindings ob
   WHERE ob.change_id=p_change_id AND ob.approver=v_approver AND ob.override_digest=bk.override_digest) THEN
  RAISE EXCEPTION 'DUPLICATE_SUSPECTED';
 END IF;
 UPDATE change_ledger.approval_nonces n SET state='CONSUMED' WHERE n.nonce=p_nonce;
 -- B6l: the approval type and the MFA flag are derived here, never supplied by the caller
 atype := change_ledger.approval_lane(t,c,rec.base_fingerprint);
 amfa := coalesce((SELECT pr.mfa FROM change_ledger.principals pr WHERE pr.tenant_id=t AND pr.company_id=c
   AND pr.principal=v_approver),false);
 INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision,approval_type,mfa_verified,
  digest_version,envelope_id)
 VALUES(p_change_id,v_approver,p_nonce,p_digest,'APPROVE',atype,amfa,'S12-APPROVAL-2',env.envelope_id)
 RETURNING approval_id INTO aid;
 UPDATE change_ledger.records SET authorization_state='APPROVED',
  epoch_dependencies=epoch_dependencies || jsonb_build_object('principal:'||v_approver,
   change_ledger.epoch_value(t,c,'principal:'||v_approver)),
  updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVED',
  jsonb_build_object('approval_id',aid,'digest',p_digest,'digest_version','S12-APPROVAL-2',
   'approval_type',atype,'mfa_verified',amfa));
 RETURN aid;
END $fn$;

-- ================================================================== claim (008 body + version gate)
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
 -- B6e: a replayed claim of a live claim returns the existing token (arguments are still cross-checked)
 IF rec.authorization_state='CLAIMED' AND rec.execution_state='NOT_STARTED' THEN
  SELECT * INTO tok FROM change_ledger.claim_tokens ct
   WHERE ct.change_id=p_change_id AND ct.generation=rec.claim_generation AND ct.state='ISSUED';
  IF FOUND THEN
   SELECT * INTO cb FROM change_ledger.change_budget b WHERE b.change_id=p_change_id;
   IF NOT FOUND OR p_grant_id IS DISTINCT FROM cb.grant_id THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
   IF p_amount IS DISTINCT FROM cb.amount
    OR coalesce(p_counts_create_update,false) IS DISTINCT FROM cb.counts_create_update
    OR coalesce(p_counts_post,false) IS DISTINCT FROM cb.counts_post THEN
    RAISE EXCEPTION 'DIGEST_MISMATCH';
   END IF;
   RETURN tok;
  END IF;
 END IF;
 IF rec.execution_state<>'NOT_STARTED' OR rec.verification_state<>'NOT_VERIFIED' OR rec.dispatch_state='DISPATCHED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF rec.authorization_state IN ('VOIDED','REVOKED') THEN RAISE EXCEPTION 'APPROVAL_VOIDED'; END IF;
 IF rec.authorization_state <> 'APPROVED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_approval_current(t,c,rec);       -- S12-APPROVAL-2: version gate + envelope binding
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
    WHERE tenant_id=t AND company_id=c AND change_id=rec.parent_change_id AND verification_state='VERIFIED') THEN
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

-- ================================================================== issue_permit (008 body + envelope gate)
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
 PERFORM change_ledger.assert_repair_authorized(t,c,rec);            -- B6f: hold + repair authorization again
 PERFORM change_ledger.assert_approval_current(t,c,rec);             -- S12-APPROVAL-2: payload digest recomputed
 -- B6e: a replayed issue_permit of a live PERMITTED permit returns it
 SELECT * INTO dp FROM change_ledger.dispatch_permits x WHERE x.change_id=p_change_id AND x.generation=p_generation;
 IF FOUND AND dp.state='PERMITTED' THEN
  RETURN jsonb_build_object('change_id',dp.change_id,'generation',dp.generation,
   'permit_digest',dp.permit_digest,'checkpoint_seq',dp.checkpoint_seq,
   'expires_at',to_char(dp.expires_at,'YYYY-MM-DD"T"HH24:MI:SS.US'));
 END IF;
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

-- ================================================================== begin_apply (008 body + envelope gate)
CREATE OR REPLACE FUNCTION change_ledger.begin_apply(
 t text, c text, p_token_id uuid, p_call_id uuid, p_writer_host text, p_onec_session text
) RETURNS change_ledger.claim_tokens LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
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
 IF caller IS DISTINCT FROM rec.requester AND NOT pg_has_role(caller::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF tok.generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF tok.state='CONSUMED' THEN
  IF rec.execution_state='APPLYING' AND rec.authorization_state='CLAIMED' AND rec.dispatch_state<>'DISPATCHED' THEN
   RETURN tok;
  END IF;
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 IF tok.state<>'ISSUED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.authorization_state<>'CLAIMED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_switch_off(t,c);
 IF change_ledger.blocking_hold(t,c,rec.base_fingerprint,rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 IF change_ledger.registry_enforced(t,c) AND NOT EXISTS(SELECT 1 FROM change_ledger.target_observations o
   WHERE o.change_id=rec.change_id AND o.generation=tok.generation
    AND o.observed_fingerprint=rec.base_fingerprint) THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 PERFORM change_ledger.assert_approval_current(t,c,rec);       -- S12-APPROVAL-2: version gate + payload recompute
 UPDATE change_ledger.claim_tokens SET state='CONSUMED' WHERE token_id=p_token_id;
 UPDATE change_ledger.records SET execution_state='APPLYING', updated_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
 INSERT INTO change_ledger.dispatch_permits(change_id,generation,state,call_id,writer_host,onec_session)
 VALUES(rec.change_id,tok.generation,'NOT_PERMITTED',p_call_id,p_writer_host,p_onec_session)
 ON CONFLICT(change_id,generation) DO NOTHING;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'APPLYING',
  jsonb_build_object('call_id',p_call_id,'writer_host',p_writer_host,'onec_session',p_onec_session));
 RETURN tok;
END $fn$;

-- ================================================================== invalidate S12-APPROVAL-SQL-1 approvals
-- Unclaimed approved changes whose approval is not a version-2 approval are voided (claimed ones are stopped by the
-- gates above). The approvals rows themselves are immutable and keep the S12-APPROVAL-SQL-1 label.
DO $retire$
DECLARE r record;
BEGIN
 FOR r IN SELECT x.tenant_id, x.company_id, x.change_id FROM change_ledger.records x
   WHERE x.authorization_state='APPROVED' AND x.execution_state='NOT_STARTED'
    AND NOT EXISTS(SELECT 1 FROM change_ledger.approvals a WHERE a.change_id=x.change_id
      AND a.decision='APPROVE' AND a.digest_version='S12-APPROVAL-2')
   ORDER BY x.created_at, x.change_id
 LOOP
  UPDATE change_ledger.records SET authorization_state='VOIDED', updated_at=clock_timestamp()
   WHERE change_id=r.change_id;
  PERFORM change_ledger.append_event(r.tenant_id,r.company_id,r.change_id,'APPROVAL_VERSION_RETIRED',
   jsonb_build_object('from','S12-APPROVAL-SQL-1','to','S12-APPROVAL-2'));
 END LOOP;
END $retire$;

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

GRANT EXECUTE ON FUNCTION change_ledger.store_approval_text(text,text,uuid,text,text) TO requester_role;
GRANT EXECUTE ON FUNCTION change_ledger.read_approval_text(text,text,uuid) TO requester_role, approver_role;
GRANT EXECUTE ON FUNCTION change_ledger.verify_dispatch_payload(text,text,uuid,bigint,text) TO writer_role, requester_role;

$body$;
END IF;
END $mig$;
COMMIT;
