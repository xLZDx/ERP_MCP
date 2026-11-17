-- S13: establish a durable, bounded base recovery epoch before external recovery reads.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('036', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','030','031','032','033','034','035']) THEN
 EXECUTE $body$

CREATE TABLE change_ledger.base_recovery_fences (
 base_fingerprint text PRIMARY KEY CHECK(base_fingerprint<>'' AND base_fingerprint=btrim(base_fingerprint)),
 state text NOT NULL CHECK(state='RECOVERING'),
 epoch bigint NOT NULL CHECK(epoch>0),
 scope_manifest jsonb NOT NULL CHECK(jsonb_typeof(scope_manifest)='array'),
 manifest_digest text NOT NULL CHECK(manifest_digest ~ '^[a-f0-9]{64}$'),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE change_ledger.base_recovery_fences OWNER TO ledger_owner;
ALTER TABLE change_ledger.base_recovery_fences ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_ledger.base_recovery_fences FORCE ROW LEVEL SECURITY;
CREATE POLICY ledger_owner_all ON change_ledger.base_recovery_fences
 FOR ALL TO ledger_owner USING (true) WITH CHECK (true);
REVOKE ALL ON change_ledger.base_recovery_fences FROM PUBLIC,
 requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

-- Existing target APIs take the base fence before target DML. This trigger makes the durable
-- RECOVERING row authoritative after begin commits, including a target added in a new scope.
CREATE FUNCTION change_ledger.private_writer_guard_base_recovery_target_v1()
RETURNS trigger LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE old_base text; new_base text;
BEGIN
 IF TG_OP<>'INSERT' THEN old_base:=OLD.base_fingerprint; END IF;
 IF TG_OP<>'DELETE' THEN new_base:=NEW.base_fingerprint; END IF;
 IF EXISTS (
  SELECT 1 FROM change_ledger.base_recovery_fences f
  WHERE f.state='RECOVERING'
    AND f.base_fingerprint IN (old_base,new_base)
 ) THEN
  RAISE EXCEPTION 'BASE_RECOVERY_IN_PROGRESS' USING ERRCODE='P0001';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_guard_base_recovery_target_v1() OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.private_writer_guard_base_recovery_target_v1() FROM PUBLIC,
 requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
CREATE TRIGGER private_writer_base_recovery_target_guard
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.targets
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_guard_base_recovery_target_v1();

-- Not idempotent: a retry after a lost response begins a fresh epoch, so earlier recovery
-- observations are stale and must not be reused.
-- The caller must set statement_timeout <= 15s before issuing SELECT; changing it here cannot
-- bound the already-running top-level command or the complete manifest scan.
CREATE FUNCTION change_ledger.begin_base_recovery(p_base_fingerprint text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE manifest_before jsonb; manifest_after jsonb; manifest_digest text;
        scope_row record; existing_epoch bigint; max_scope_epoch bigint:=0; scope_epoch bigint;
        next_epoch bigint; prior_timeout text; result jsonb;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_base_fingerprint IS NULL OR p_base_fingerprint='' OR
    p_base_fingerprint<>btrim(p_base_fingerprint) THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID' USING ERRCODE='P0001';
 END IF;
 prior_timeout:=current_setting('lock_timeout');
 PERFORM change_ledger.bound_lifecycle_lock_wait();
 BEGIN

 -- Snapshot the complete scope union before taking any locks or mutating rows.
 IF NOT EXISTS (SELECT 1 FROM change_ledger.targets t
                WHERE t.base_fingerprint=p_base_fingerprint) THEN
  RAISE EXCEPTION 'BASE_SCOPE_MAPPING_MISSING' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('tenant_id',s.tenant_id,'company_id',s.company_id)
                  ORDER BY s.tenant_id COLLATE "C",s.company_id COLLATE "C"),'[]'::jsonb)
 INTO manifest_before
 FROM (
  SELECT s.tenant_id,s.company_id FROM (
   SELECT t.tenant_id,t.company_id FROM change_ledger.targets t
    WHERE t.base_fingerprint=p_base_fingerprint
   UNION
   SELECT r.tenant_id,r.company_id FROM change_ledger.records r
    WHERE r.base_fingerprint=p_base_fingerprint
     AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
       OR r.call_ownership='POSSIBLY_EXECUTING'
       OR (r.dispatch_state='DISPATCHED'
         AND NOT (r.execution_state IN ('APPLIED','FAILED_APPLY')
           AND r.call_ownership='PROVEN_FINISHED')))
   UNION
   SELECT a.tenant_id,a.company_id FROM change_ledger.dispatch_attempts a
    WHERE a.base_fingerprint=p_base_fingerprint AND a.state<>'TERMINAL_WITH_EVIDENCE'
   UNION
   SELECT b.tenant_id,b.company_id FROM change_ledger.writer_barriers b
    WHERE b.base_fingerprint=p_base_fingerprint AND b.progress='CLOSED_WITH_HOLD'
  ) s
  ORDER BY s.tenant_id COLLATE "C",s.company_id COLLATE "C"
  LIMIT 65
 ) s;
 IF jsonb_array_length(manifest_before)>64 THEN
  RAISE EXCEPTION 'BASE_SCOPE_LIMIT' USING ERRCODE='P0001';
 END IF;

 -- Match every scope writer's rank: namespace 2, namespace 8, then namespace 7.
 FOR scope_row IN
  SELECT x.tenant_id,x.company_id FROM jsonb_to_recordset(manifest_before) AS x(tenant_id text,company_id text)
   ORDER BY x.tenant_id COLLATE "C",x.company_id COLLATE "C"
 LOOP
  PERFORM change_ledger.private_writer_take_switch_fence_v1(scope_row.tenant_id,scope_row.company_id);
 END LOOP;
 PERFORM change_ledger.private_writer_take_base_fence_v1(p_base_fingerprint);

 -- A changed target/call inventory aborts before namespace 7 locks or any writes.
 IF NOT EXISTS (SELECT 1 FROM change_ledger.targets t
                WHERE t.base_fingerprint=p_base_fingerprint) THEN
  RAISE EXCEPTION 'BASE_SCOPE_MANIFEST_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('tenant_id',s.tenant_id,'company_id',s.company_id)
                  ORDER BY s.tenant_id COLLATE "C",s.company_id COLLATE "C"),'[]'::jsonb)
 INTO manifest_after
 FROM (
  SELECT s.tenant_id,s.company_id FROM (
   SELECT t.tenant_id,t.company_id FROM change_ledger.targets t
    WHERE t.base_fingerprint=p_base_fingerprint
   UNION
   SELECT r.tenant_id,r.company_id FROM change_ledger.records r
    WHERE r.base_fingerprint=p_base_fingerprint
     AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
       OR r.call_ownership='POSSIBLY_EXECUTING'
       OR (r.dispatch_state='DISPATCHED'
         AND NOT (r.execution_state IN ('APPLIED','FAILED_APPLY')
           AND r.call_ownership='PROVEN_FINISHED')))
   UNION
   SELECT a.tenant_id,a.company_id FROM change_ledger.dispatch_attempts a
    WHERE a.base_fingerprint=p_base_fingerprint AND a.state<>'TERMINAL_WITH_EVIDENCE'
   UNION
   SELECT b.tenant_id,b.company_id FROM change_ledger.writer_barriers b
    WHERE b.base_fingerprint=p_base_fingerprint AND b.progress='CLOSED_WITH_HOLD'
  ) s
  ORDER BY s.tenant_id COLLATE "C",s.company_id COLLATE "C"
  LIMIT 65
 ) s;
 IF manifest_after IS DISTINCT FROM manifest_before THEN
  RAISE EXCEPTION 'BASE_SCOPE_MANIFEST_STALE' USING ERRCODE='P0001';
 END IF;
 IF jsonb_array_length(manifest_after)>64 THEN
  RAISE EXCEPTION 'BASE_SCOPE_LIMIT' USING ERRCODE='P0001';
 END IF;

 FOR scope_row IN
  SELECT x.tenant_id,x.company_id FROM jsonb_to_recordset(manifest_after) AS x(tenant_id text,company_id text)
   ORDER BY x.tenant_id COLLATE "C",x.company_id COLLATE "C"
 LOOP
  PERFORM change_ledger.private_writer_take_scope_fence_v1(scope_row.tenant_id,scope_row.company_id);
 END LOOP;

 -- A separate base cannot concurrently own a shared lifecycle scope; fail closed after
 -- acquiring the same namespace-7 fences that serialize this check with other begin calls.
 IF EXISTS (
  SELECT 1 FROM change_ledger.base_recovery_fences active
  CROSS JOIN LATERAL jsonb_to_recordset(active.scope_manifest) AS a(tenant_id text,company_id text)
  JOIN LATERAL jsonb_to_recordset(manifest_after) AS n(tenant_id text,company_id text)
    ON n.tenant_id=a.tenant_id AND n.company_id=a.company_id
  WHERE active.base_fingerprint<>p_base_fingerprint AND active.state='RECOVERING'
 ) THEN
  RAISE EXCEPTION 'BASE_RECOVERY_SCOPE_BUSY' USING ERRCODE='P0001';
 END IF;

 FOR scope_row IN
  SELECT x.tenant_id,x.company_id FROM jsonb_to_recordset(manifest_after) AS x(tenant_id text,company_id text)
   ORDER BY x.tenant_id COLLATE "C",x.company_id COLLATE "C"
 LOOP
  SELECT f.epoch INTO scope_epoch FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=scope_row.tenant_id AND f.company_id=scope_row.company_id FOR UPDATE;
  IF FOUND THEN max_scope_epoch:=greatest(max_scope_epoch,scope_epoch); END IF;
 END LOOP;
 SELECT f.epoch INTO existing_epoch FROM change_ledger.base_recovery_fences f
  WHERE f.base_fingerprint=p_base_fingerprint FOR UPDATE;
 IF greatest(coalesce(existing_epoch,0),max_scope_epoch)=9223372036854775807 THEN
  RAISE EXCEPTION 'BASE_RECOVERY_EPOCH_EXHAUSTED' USING ERRCODE='P0001';
 END IF;
 next_epoch:=greatest(coalesce(existing_epoch,0),max_scope_epoch)+1;
 manifest_digest:=encode(pg_catalog.sha256(convert_to(manifest_after::text,'UTF8')),'hex');

 INSERT INTO change_ledger.base_recovery_fences
  (base_fingerprint,state,epoch,scope_manifest,manifest_digest,updated_at)
 VALUES(p_base_fingerprint,'RECOVERING',next_epoch,manifest_after,manifest_digest,clock_timestamp())
 ON CONFLICT(base_fingerprint) DO UPDATE SET state='RECOVERING',epoch=EXCLUDED.epoch,
  scope_manifest=EXCLUDED.scope_manifest,manifest_digest=EXCLUDED.manifest_digest,
  updated_at=EXCLUDED.updated_at;
 FOR scope_row IN
  SELECT x.tenant_id,x.company_id FROM jsonb_to_recordset(manifest_after) AS x(tenant_id text,company_id text)
   ORDER BY x.tenant_id COLLATE "C",x.company_id COLLATE "C"
 LOOP
  INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason,updated_at)
  VALUES(scope_row.tenant_id,scope_row.company_id,'RECOVERING',next_epoch,
         'BASE_RECOVERY_IN_PROGRESS',clock_timestamp())
  ON CONFLICT(tenant_id,company_id) DO UPDATE SET state='RECOVERING',epoch=EXCLUDED.epoch,
   reason=EXCLUDED.reason,updated_at=EXCLUDED.updated_at;
 END LOOP;
 result:=jsonb_build_object('base_fingerprint',p_base_fingerprint,'state','RECOVERING','epoch',next_epoch,
  'manifest_digest',manifest_digest,'scope_count',jsonb_array_length(manifest_after),
  'scope_manifest',manifest_after);
 PERFORM set_config('lock_timeout',prior_timeout,true);
 RETURN result;
 EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('lock_timeout',prior_timeout,true);
  RAISE;
 END;
END $fn$;
ALTER FUNCTION change_ledger.begin_base_recovery(text) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.begin_base_recovery(text) FROM PUBLIC,
 requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

 $body$;
 END IF;
END $mig$;
COMMIT;

