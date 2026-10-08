-- R2/G1 transactional APIs; disposable PostgreSQL validation required before use.
-- Fixed lock order in every function: source -> job -> cursor -> outbox.
-- Error codes: INVALID_ARGUMENT, INVALID_LEASE, SOURCE_NOT_FOUND, SCOPE_REVOKED,
-- JOB_UNAVAILABLE, STALE_JOB_FENCE, CURSOR_NOT_FOUND, STALE_CURSOR_OR_SCOPE,
-- CURSOR_ALREADY_APPLIED (NOTICE; call is an idempotent no-op), CONFLICTING_EVENT_DIGEST.
-- The source row is locked FOR UPDATE in every API (one mode, so no SHARE->UPDATE upgrade deadlocks).
-- Whole-file guard: re-running this file after it is recorded is a no-op (keeps 003 hardening).
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('002', ARRAY['001']) THEN
EXECUTE $body$

-- Expired RUNNING jobs of a source go back to PENDING (backoff) or FAILED when attempts are spent.
CREATE OR REPLACE FUNCTION living.reap_expired_jobs(t text,s text) RETURNS integer
LANGUAGE plpgsql AS $fn$
DECLARE n integer;
BEGIN
 PERFORM living.assert_scope(t,s);
 PERFORM 1 FROM living.sources WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 UPDATE living.jobs SET
  state=CASE WHEN attempt>=max_attempts THEN 'FAILED' ELSE 'PENDING' END,
  lease_owner=NULL,lease_until=NULL,
  last_error='LEASE_EXPIRED',
  next_run_at=clock_timestamp()+make_interval(secs=>least(300,power(2,least(attempt,8))::integer))
 WHERE tenant_id=t AND source_id=s AND state='RUNNING' AND lease_until<=clock_timestamp();
 GET DIAGNOSTICS n = ROW_COUNT;
 RETURN n;
END $fn$;

CREATE OR REPLACE FUNCTION living.acquire_job(t text,s text,j uuid,worker text,lease_seconds integer)
RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE token bigint; src_status text; src_epoch bigint;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF j IS NULL OR worker IS NULL OR length(worker)=0
  OR lease_seconds IS NULL OR lease_seconds<1 OR lease_seconds>300 THEN
   RAISE EXCEPTION 'INVALID_LEASE';
 END IF;
 SELECT status,scope_epoch INTO src_status,src_epoch FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 PERFORM living.reap_expired_jobs(t,s);
 -- Source lock is held: a live RUNNING job of this source means unavailable (not a raw 23505).
 IF EXISTS(SELECT 1 FROM living.jobs WHERE tenant_id=t AND source_id=s AND state='RUNNING') THEN
  RAISE EXCEPTION 'JOB_UNAVAILABLE';
 END IF;
 UPDATE living.jobs SET state='RUNNING',lease_owner=worker,
  lease_until=clock_timestamp()+make_interval(secs=>lease_seconds),
  fence=fence+1,attempt=attempt+1
 WHERE tenant_id=t AND source_id=s AND job_id=j
   AND state='PENDING' AND scope_epoch=src_epoch
   AND attempt<max_attempts AND next_run_at<=clock_timestamp()
 RETURNING fence INTO token;
 IF token IS NULL THEN
  IF EXISTS(SELECT 1 FROM living.jobs WHERE tenant_id=t AND source_id=s AND job_id=j
            AND scope_epoch IS DISTINCT FROM src_epoch) THEN
   RAISE EXCEPTION 'SCOPE_REVOKED';
  END IF;
  RAISE EXCEPTION 'JOB_UNAVAILABLE';
 END IF;
 RETURN token;
END $fn$;

CREATE OR REPLACE FUNCTION living.renew_lease(
 t text,s text,j uuid,worker text,token bigint,lease_seconds integer)
RETURNS timestamptz LANGUAGE plpgsql AS $fn$
DECLARE src_status text; src_epoch bigint; new_until timestamptz;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF j IS NULL OR worker IS NULL OR length(worker)=0 OR token IS NULL
  OR lease_seconds IS NULL OR lease_seconds<1 OR lease_seconds>300 THEN
  RAISE EXCEPTION 'INVALID_LEASE';
 END IF;
 SELECT status,scope_epoch INTO src_status,src_epoch FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 UPDATE living.jobs SET lease_until=clock_timestamp()+make_interval(secs=>lease_seconds)
 WHERE tenant_id=t AND source_id=s AND job_id=j
   AND state='RUNNING' AND lease_owner=worker AND fence=token
   AND lease_until>clock_timestamp() AND scope_epoch=src_epoch
 RETURNING lease_until INTO new_until;
 IF new_until IS NULL THEN RAISE EXCEPTION 'STALE_JOB_FENCE'; END IF;
 RETURN new_until;
END $fn$;

CREATE OR REPLACE FUNCTION living.finish_job(
 t text,s text,j uuid,worker text,token bigint,completed_state text,err text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE src_status text; src_epoch bigint;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF j IS NULL OR worker IS NULL OR token IS NULL OR completed_state IS NULL
  OR completed_state NOT IN ('SUCCEEDED','FAILED','CANCELLED') THEN
  RAISE EXCEPTION 'INVALID_TERMINAL_STATE';
 END IF;
 SELECT status,scope_epoch INTO src_status,src_epoch FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 UPDATE living.jobs SET state=completed_state,lease_owner=NULL,lease_until=NULL,
  last_error=CASE WHEN completed_state='SUCCEEDED' THEN NULL ELSE err END
 WHERE tenant_id=t AND source_id=s AND job_id=j
 AND state='RUNNING' AND lease_owner=worker AND fence=token
 AND lease_until>clock_timestamp() AND scope_epoch=src_epoch;
 IF NOT FOUND THEN RAISE EXCEPTION 'STALE_JOB_FENCE'; END IF;
END $fn$;

-- Atomic page commit: validates source scope, job fence/lease and cursor CAS, then writes the outbox.
-- Any RAISE aborts the whole call, so a rejected page leaves the cursor untouched.
CREATE OR REPLACE FUNCTION living.commit_cursor_page(
 t text,s text,c text,p_job_id uuid,p_worker text,p_fence bigint,
 prior_cursor text,prior_version bigint,expected_epoch bigint,new_cursor text,page_events jsonb
) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE
 next_version bigint; item jsonb; eid text; edigest text;
 src_status text; src_epoch bigint;
 j_state text; j_owner text; j_fence bigint; j_until timestamptz; j_epoch bigint;
 cur_value text; cur_version bigint; cur_epoch bigint;
BEGIN
 PERFORM living.assert_scope(t,s);
 IF c IS NULL OR c='' OR p_job_id IS NULL OR p_worker IS NULL OR p_fence IS NULL
  OR prior_cursor IS NULL OR prior_version IS NULL OR expected_epoch IS NULL THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 IF new_cursor IS NULL OR new_cursor='' OR page_events IS NULL
  OR jsonb_typeof(page_events) IS DISTINCT FROM 'array'
  OR jsonb_array_length(page_events)>1000
  OR octet_length(page_events::text)>4194304 THEN
  RAISE EXCEPTION 'INVALID_CURSOR_BATCH';
 END IF;
 -- The event digest is computed here from the content (event minus its own "digest" key);
 -- a caller-supplied digest is only a claim and must match.
 FOR item IN SELECT value FROM jsonb_array_elements(page_events) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'object'
   OR coalesce(item->>'event_id','')=''
   OR octet_length(item::text)>262144
   OR coalesce(item->>'digest','') !~ '^[a-f0-9]{64}$'
   OR item->>'digest' IS DISTINCT FROM
      encode(sha256(convert_to((item - 'digest')::text,'UTF8')),'hex') THEN
   RAISE EXCEPTION 'INVALID_OUTBOX_EVENT';
  END IF;
 END LOOP;
 -- 1. source
 SELECT status,scope_epoch INTO src_status,src_epoch FROM living.sources
  WHERE tenant_id=t AND source_id=s FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_NOT_FOUND'; END IF;
 IF src_status IS DISTINCT FROM 'ACTIVE' OR src_epoch IS DISTINCT FROM expected_epoch THEN
  RAISE EXCEPTION 'SCOPE_REVOKED';
 END IF;
 -- 2. job
 SELECT state,lease_owner,fence,lease_until,scope_epoch
  INTO j_state,j_owner,j_fence,j_until,j_epoch FROM living.jobs
  WHERE tenant_id=t AND source_id=s AND job_id=p_job_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'STALE_JOB_FENCE'; END IF;
 IF j_epoch IS DISTINCT FROM src_epoch THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 IF j_state IS DISTINCT FROM 'RUNNING' OR j_owner IS DISTINCT FROM p_worker
  OR j_fence IS DISTINCT FROM p_fence OR j_until IS NULL OR j_until<=clock_timestamp() THEN
  RAISE EXCEPTION 'STALE_JOB_FENCE';
 END IF;
 -- 3. cursor
 SELECT cursor_value,version,scope_epoch INTO cur_value,cur_version,cur_epoch
  FROM living.cursors WHERE tenant_id=t AND source_id=s AND connection_id=c FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CURSOR_NOT_FOUND'; END IF;
 IF cur_epoch IS DISTINCT FROM expected_epoch THEN RAISE EXCEPTION 'SCOPE_REVOKED'; END IF;
 IF cur_value IS NOT DISTINCT FROM new_cursor AND cur_version IS NOT DISTINCT FROM prior_version+1 THEN
  RAISE NOTICE 'CURSOR_ALREADY_APPLIED';
  RETURN cur_version;
 END IF;
 IF cur_value IS DISTINCT FROM prior_cursor OR cur_version IS DISTINCT FROM prior_version THEN
  RAISE EXCEPTION 'STALE_CURSOR_OR_SCOPE';
 END IF;
 UPDATE living.cursors SET cursor_value=new_cursor,version=version+1
  WHERE tenant_id=t AND source_id=s AND connection_id=c
  RETURNING version INTO next_version;
 -- 4. outbox
 FOR item IN SELECT value FROM jsonb_array_elements(page_events) LOOP
  eid:=item->>'event_id';
  edigest:=encode(sha256(convert_to((item - 'digest')::text,'UTF8')),'hex');
  INSERT INTO living.outbox(tenant_id,source_id,connection_id,event_id,event_digest,content)
   VALUES(t,s,c,eid,edigest,item)
   ON CONFLICT(tenant_id,source_id,connection_id,event_id) DO NOTHING;
  IF NOT FOUND AND EXISTS(
    SELECT 1 FROM living.outbox WHERE tenant_id=t AND source_id=s
    AND connection_id=c AND event_id=eid
    AND (event_digest IS DISTINCT FROM edigest OR content IS DISTINCT FROM item)
  ) THEN RAISE EXCEPTION 'CONFLICTING_EVENT_DIGEST'; END IF;
 END LOOP;
 RETURN next_version;
END $fn$;
$body$;
END IF;
END $mig$;
COMMIT;
