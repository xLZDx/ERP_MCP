-- Restrict the lifecycle timeout to acquiring its fence row, not the rest of the caller transaction.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('024', ARRAY['001','002','003','004','005','006','007','008','009',
   '010','011','012','013','014','015','016','017','018','019','020','021','022','023']) THEN
 EXECUTE $body$

-- Hold the lifecycle row as before, but restore the caller's lock_timeout immediately after
-- the acquisition. If the lock attempt raises, the exception subtransaction restores it too.
CREATE OR REPLACE FUNCTION change_ledger.lock_lifecycle_fence(t text,c text)
RETURNS change_ledger.lifecycle_fences
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE
 prior_timeout text;
 f change_ledger.lifecycle_fences%ROWTYPE;
 found_fence boolean;
BEGIN
 prior_timeout := current_setting('lock_timeout');
 PERFORM change_ledger.bound_lifecycle_lock_wait();
 BEGIN
  SELECT * INTO f FROM change_ledger.lifecycle_fences
   WHERE tenant_id=t AND company_id=c FOR SHARE;
  found_fence := FOUND;
 EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('lock_timeout',prior_timeout,true);
  RAISE;
 END;
 PERFORM set_config('lock_timeout',prior_timeout,true);
 IF found_fence THEN RETURN f; END IF;
 RETURN NULL;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.dispatch_permit_lifecycle_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE r change_ledger.records%ROWTYPE; f change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 SELECT * INTO r FROM change_ledger.records WHERE change_id=NEW.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 f := change_ledger.lock_lifecycle_fence(r.tenant_id,r.company_id);
 IF f.tenant_id IS NULL OR f.state IN ('NOT_READY','RECOVERING') THEN
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
 f := change_ledger.lock_lifecycle_fence(NEW.tenant_id,NEW.company_id);
 IF f.tenant_id IS NULL OR f.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 RETURN NEW;
END $fn$;

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
 f := change_ledger.lock_lifecycle_fence(t,c);
 IF f.tenant_id IS NULL OR f.state<>'READY' OR f.epoch<>p_epoch THEN RETURN false; END IF;
 SELECT dp.lifecycle_epoch INTO permit_epoch
  FROM change_ledger.dispatch_permits dp
  JOIN change_ledger.records r ON r.change_id=dp.change_id
  WHERE r.tenant_id=t AND r.company_id=c
    AND dp.change_id=p_change_id AND dp.generation=p_generation;
 RETURN FOUND AND permit_epoch=p_epoch;
END $fn$;

REVOKE ALL ON FUNCTION change_ledger.lock_lifecycle_fence(text,text) FROM PUBLIC,
 requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role;
REVOKE ALL ON FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint)
 FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.dispatch_permit_lifecycle_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION change_ledger.events_lifecycle_fence_guard() FROM PUBLIC;

ALTER FUNCTION change_ledger.lock_lifecycle_fence(text,text) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint) OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.dispatch_permit_lifecycle_guard() OWNER TO ledger_owner;
ALTER FUNCTION change_ledger.events_lifecycle_fence_guard() OWNER TO ledger_owner;

    $body$;
 END IF;
END $mig$;
COMMIT;
