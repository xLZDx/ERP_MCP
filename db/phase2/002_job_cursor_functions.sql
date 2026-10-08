-- R2/G1 transactional APIs; disposable PostgreSQL validation required before use.
BEGIN;
CREATE OR REPLACE FUNCTION living.acquire_job(t text,s text,j uuid,worker text,lease_seconds integer)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE token bigint;
BEGIN
 IF worker IS NULL OR length(worker)=0 OR lease_seconds<1 OR lease_seconds>300 THEN
   RAISE EXCEPTION 'INVALID_LEASE';
 END IF;
 UPDATE living.jobs SET state='RUNNING',lease_owner=worker,
  lease_until=clock_timestamp()+make_interval(secs=>lease_seconds),
  fence=fence+1
 WHERE tenant_id=t AND source_id=s AND job_id=j
   AND (state='PENDING' OR (state='RUNNING' AND lease_until<clock_timestamp()))
 RETURNING fence INTO token;
 IF token IS NULL THEN RAISE EXCEPTION 'JOB_UNAVAILABLE'; END IF;
 RETURN token;
END $$;
CREATE OR REPLACE FUNCTION living.finish_job(
 t text,s text,j uuid,worker text,token bigint,completed_state text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF completed_state NOT IN ('SUCCEEDED','FAILED','CANCELLED') THEN
  RAISE EXCEPTION 'INVALID_TERMINAL_STATE';
 END IF;
 UPDATE living.jobs SET state=completed_state,lease_owner=NULL,lease_until=NULL
 WHERE tenant_id=t AND source_id=s AND job_id=j
 AND state='RUNNING' AND lease_owner=worker AND fence=token
 AND lease_until>clock_timestamp();
 IF NOT FOUND THEN RAISE EXCEPTION 'STALE_JOB_FENCE'; END IF;
END $$;
CREATE OR REPLACE FUNCTION living.commit_cursor_page(
 t text,s text,c text,prior_cursor text,prior_version bigint,
 expected_epoch bigint,new_cursor text,page_events jsonb
) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE next_version bigint; item jsonb; eid text; edigest text;
BEGIN
 IF new_cursor IS NULL OR new_cursor='' OR jsonb_typeof(page_events)<>'array'
  OR jsonb_array_length(page_events)>1000 THEN
  RAISE EXCEPTION 'INVALID_CURSOR_BATCH';
 END IF;
 UPDATE living.cursors SET cursor_value=new_cursor,version=version+1
 WHERE tenant_id=t AND source_id=s AND connection_id=c
 AND cursor_value=prior_cursor AND version=prior_version AND scope_epoch=expected_epoch
 RETURNING version INTO next_version;
 IF next_version IS NULL THEN RAISE EXCEPTION 'STALE_CURSOR_OR_SCOPE'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(page_events) LOOP
  eid:=item->>'event_id'; edigest:=item->>'digest';
  IF eid IS NULL OR eid='' OR edigest IS NULL OR edigest !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'INVALID_OUTBOX_EVENT';
  END IF;
  INSERT INTO living.outbox(tenant_id,source_id,connection_id,event_id,event_digest,content)
   VALUES(t,s,c,eid,edigest,item)
   ON CONFLICT(tenant_id,source_id,connection_id,event_id) DO NOTHING;
  IF NOT FOUND AND EXISTS(
    SELECT 1 FROM living.outbox WHERE tenant_id=t AND source_id=s
    AND connection_id=c AND event_id=eid AND event_digest<>edigest
  ) THEN RAISE EXCEPTION 'CONFLICTING_EVENT_DIGEST'; END IF;
 END LOOP;
 RETURN next_version;
END $$;
COMMIT;
