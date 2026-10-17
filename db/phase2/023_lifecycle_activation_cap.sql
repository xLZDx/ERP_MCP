-- Keep the preparatory S13 fence fail-closed until its coordinator and physical writer boundary exist.
-- This migration does not clear existing RECOVERING rows and never creates READY.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('023', ARRAY['001','002','003','004','005','006','007','008','009',
   '010','011','012','013','014','015','016','017','018','019','020','021','022']) THEN
 EXECUTE $body$

-- A lifecycle row lock must never wait longer than five seconds. Preserve a shorter timeout
-- already selected by the caller; PostgreSQL's value "0" means unlimited, so cap that too.
CREATE OR REPLACE FUNCTION change_ledger.bound_lifecycle_lock_wait() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE current_timeout interval;
BEGIN
 current_timeout := current_setting('lock_timeout')::interval;
 IF current_timeout=interval '0' OR current_timeout>interval '5 seconds' THEN
  PERFORM set_config('lock_timeout','5s',true);
 END IF;
END $fn$;

-- There is no reviewed READY-producing coordinator. Do not let application roles create a
-- durable RECOVERING state that they cannot safely finish. Even a privileged direct call fails
-- closed until a later migration replaces this function with the fully reviewed coordinator.
CREATE OR REPLACE FUNCTION change_ledger.lifecycle_begin_recovery(t text,c text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 RAISE EXCEPTION 'LIFECYCLE_COORDINATOR_UNAVAILABLE';
END $fn$;

-- Every trigger read that participates in the lifecycle fence uses a bounded lock wait.
CREATE OR REPLACE FUNCTION change_ledger.dispatch_permit_lifecycle_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE r change_ledger.records%ROWTYPE; f change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.bound_lifecycle_lock_wait();
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

CREATE OR REPLACE FUNCTION change_ledger.events_lifecycle_fence_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE f change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.bound_lifecycle_lock_wait();
 SELECT * INTO f FROM change_ledger.lifecycle_fences
  WHERE tenant_id=NEW.tenant_id AND company_id=NEW.company_id FOR SHARE;
 IF NOT FOUND OR f.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 RETURN NEW;
END $fn$;

-- The writer pre-call epoch check also locks the lifecycle row; bound that path identically.
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
 PERFORM change_ledger.bound_lifecycle_lock_wait();
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

REVOKE ALL ON FUNCTION change_ledger.bound_lifecycle_lock_wait() FROM PUBLIC,requester_role,
 approver_role,operator_role,writer_role,worker_role,auditor_role;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_begin_recovery(text,text) FROM PUBLIC,
 requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint)
 FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.dispatch_permit_lifecycle_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.events_lifecycle_fence_guard() FROM PUBLIC;

ALTER FUNCTION change_ledger.bound_lifecycle_lock_wait() OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.lifecycle_begin_recovery(text,text) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.dispatch_permit_lifecycle_guard() OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.events_lifecycle_fence_guard() OWNER TO ledger_owner;

    $body$;
 END IF;
END $mig$;
COMMIT;
