-- S13 local fail-closed lifecycle fence primitives.
-- This migration deliberately does not expose a RECOVERING -> READY transition. The complete
-- suffix classifier, external anti-rollback proof, and all-mutator coverage are not yet present.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('022', ARRAY['001','002','003','004','005','006','007','008','009',
   '010','011','012','013','014','015','016','017','018','019','020','021']) THEN
 EXECUTE $body$

CREATE TABLE IF NOT EXISTS change_ledger.lifecycle_fences(
 tenant_id text NOT NULL,
 company_id text NOT NULL,
 state text NOT NULL CHECK(state IN ('LEGACY','NOT_READY','RECOVERING','READY')),
 epoch bigint NOT NULL CHECK(epoch>=0),
 reason text NOT NULL CHECK(length(reason)>0),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id)
);

-- Existing scopes stay in LEGACY mode for compatibility with the accepted 001-021 surface.
-- No migration-time inference can establish checkpoint freshness, and lifecycle_status reports
-- this state as NOT_READY. Explicitly starting recovery advances the epoch and fences the scope.
 INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason)
 SELECT DISTINCT tenant_id,company_id,'LEGACY',0,'LIFECYCLE_NOT_ACTIVATED'
 FROM change_ledger.role_scope
 ON CONFLICT(tenant_id,company_id) DO NOTHING;

ALTER TABLE change_ledger.dispatch_permits
 ADD COLUMN IF NOT EXISTS lifecycle_epoch bigint NOT NULL DEFAULT 0 CHECK(lifecycle_epoch>=0);

CREATE OR REPLACE FUNCTION change_ledger.lifecycle_status(t text,c text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE f change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT * INTO f FROM change_ledger.lifecycle_fences
  WHERE tenant_id=t AND company_id=c;
 IF NOT FOUND OR f.state='LEGACY' THEN
  RETURN jsonb_build_object('state','NOT_READY','epoch',0,'reason','LIFECYCLE_NOT_ACTIVATED');
 END IF;
 RETURN jsonb_build_object('state',f.state,'epoch',f.epoch,'reason',f.reason,
                           'updated_at',f.updated_at);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.lifecycle_begin_recovery(t text,c text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE f change_ledger.lifecycle_fences%ROWTYPE; n bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF NOT pg_has_role(change_ledger.caller_role()::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason)
  VALUES(t,c,'RECOVERING',1,'RECOVERY_IN_PROGRESS')
  ON CONFLICT(tenant_id,company_id) DO UPDATE
   SET state='RECOVERING',epoch=change_ledger.lifecycle_fences.epoch+1,
       reason='RECOVERY_IN_PROGRESS',updated_at=clock_timestamp()
  RETURNING * INTO f;
 SELECT count(*) INTO n FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c
   AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
        OR r.call_ownership='POSSIBLY_EXECUTING'
        OR (r.dispatch_state='DISPATCHED'
            AND NOT (r.execution_state IN ('APPLIED','FAILED_APPLY')
                     AND r.call_ownership='PROVEN_FINISHED')));
 RETURN jsonb_build_object('state',f.state,'epoch',f.epoch,'reason',f.reason,
                           'unresolved_calls',n,'updated_at',f.updated_at);
END $fn$;

-- This read is intended for the writer's immediate pre-call gate. A missing row, RECOVERING
-- state, or stale permit epoch is always a refusal.
CREATE OR REPLACE FUNCTION change_ledger.lifecycle_writer_epoch(
 t text,c text,p_change_id uuid,p_generation bigint,p_epoch bigint
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE f change_ledger.lifecycle_fences%ROWTYPE; permit_epoch bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF NOT pg_has_role(change_ledger.caller_role()::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 SELECT * INTO f FROM change_ledger.lifecycle_fences
  WHERE tenant_id=t AND company_id=c FOR SHARE;
 IF NOT FOUND OR f.state<>'READY' OR f.epoch<>p_epoch THEN RETURN false; END IF;
 SELECT dp.lifecycle_epoch INTO permit_epoch
  FROM change_ledger.dispatch_permits dp
  JOIN change_ledger.records r ON r.change_id=dp.change_id
  WHERE r.tenant_id=t AND r.company_id=c
    AND dp.change_id=p_change_id AND dp.generation=p_generation;
 RETURN FOUND AND permit_epoch=p_epoch;
END $fn$;

-- Read the epoch actually bound to this permit row. This avoids a second-round-trip race where
-- a caller might accidentally stamp a newer current epoch onto a stale permit.
CREATE OR REPLACE FUNCTION change_ledger.lifecycle_permit_epoch(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE e bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 SELECT dp.lifecycle_epoch INTO e FROM change_ledger.dispatch_permits dp
 JOIN change_ledger.records r ON r.change_id=dp.change_id
  WHERE r.tenant_id=t AND r.company_id=c
   AND dp.change_id=p_change_id AND dp.generation=p_generation;
 RETURN e;
END $fn$;

-- Capture the current durable epoch in each permit. LEGACY preserves existing 001-021 behavior;
-- NOT_READY/RECOVERING reject issuance. A reviewed future implementation may add READY admission.
CREATE OR REPLACE FUNCTION change_ledger.dispatch_permit_lifecycle_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE r change_ledger.records%ROWTYPE; f change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 SELECT * INTO r FROM change_ledger.records WHERE change_id=NEW.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT * INTO f FROM change_ledger.lifecycle_fences
  WHERE tenant_id=r.tenant_id AND company_id=r.company_id FOR SHARE;
 IF NOT FOUND OR f.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 IF TG_OP='INSERT' THEN
  NEW.lifecycle_epoch := f.epoch;
 ELSIF NEW.lifecycle_epoch IS DISTINCT FROM f.epoch THEN
  RAISE EXCEPTION 'LIFECYCLE_EPOCH_STALE';
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS dispatch_permit_lifecycle_guard ON change_ledger.dispatch_permits;
CREATE TRIGGER dispatch_permit_lifecycle_guard
 BEFORE INSERT OR UPDATE ON change_ledger.dispatch_permits
 FOR EACH ROW EXECUTE FUNCTION change_ledger.dispatch_permit_lifecycle_guard();

-- Serialize all event-backed ledger mutations against recovery. The legacy state keeps the
-- pre-022 behavior until recovery is explicitly started; once RECOVERING begins, the complete
-- transaction rolls back for every event-producing API. Recovery orchestration is not yet
-- authorized to mutate through this fence, so this intentionally remains fail-closed.
CREATE OR REPLACE FUNCTION change_ledger.events_lifecycle_fence_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE f change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 SELECT * INTO f FROM change_ledger.lifecycle_fences
  WHERE tenant_id=NEW.tenant_id AND company_id=NEW.company_id FOR SHARE;
 IF NOT FOUND OR f.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS events_lifecycle_fence_guard ON change_ledger.events;
CREATE TRIGGER events_lifecycle_fence_guard
 BEFORE INSERT ON change_ledger.events
 FOR EACH ROW EXECUTE FUNCTION change_ledger.events_lifecycle_fence_guard();

-- Narrow source boundary: record_call's existing CAS remains the last SQL transaction before
-- the physical call. The trigger above serializes it against recovery's epoch update and checks
-- the permit epoch as the DISPATCHED CAS commits. This does not make the absent real writer or
-- all non-dispatch mutations lifecycle-aware.

REVOKE ALL ON change_ledger.lifecycle_fences FROM PUBLIC,requester_role,approver_role,operator_role,
 writer_role,worker_role,auditor_role;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_status(text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_begin_recovery(text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_permit_epoch(text,text,uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.events_lifecycle_fence_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.dispatch_permit_lifecycle_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION change_ledger.lifecycle_status(text,text) TO worker_role,auditor_role;
GRANT EXECUTE ON FUNCTION change_ledger.lifecycle_begin_recovery(text,text) TO worker_role;
GRANT EXECUTE ON FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint) TO writer_role;
GRANT EXECUTE ON FUNCTION change_ledger.lifecycle_permit_epoch(text,text,uuid,bigint) TO worker_role;

-- Keep these roles scoped to the existing tenant/company grants; the public surface is only the
-- three reviewed functions above.
ALTER FUNCTION change_ledger.lifecycle_status(text,text) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.lifecycle_begin_recovery(text,text) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.lifecycle_permit_epoch(text,text,uuid,bigint) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.dispatch_permit_lifecycle_guard() OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.events_lifecycle_fence_guard() OWNER TO ledger_owner;
-- SECURITY DEFINER bodies and trigger callbacks execute as ledger_owner. Own the new state table
-- explicitly (004/006 perform the same ownership transfer for tables created in those migrations).
ALTER TABLE change_ledger.lifecycle_fences OWNER TO ledger_owner;

    $body$;
 END IF;
END $mig$;
COMMIT;
