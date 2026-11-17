-- Cumulative MC-01 S13 semantic consolidation of the published 027 function delta.
-- This forward migration preserves canonical migration 027 and carries no table/type/index/trigger DDL.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('030', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','028','029']) THEN
 EXECUTE $forward$
CREATE FUNCTION change_ledger.private_writer_assert_base_scope_limit_v1(
 p_base text,p_tenant text,p_company text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE n bigint;
BEGIN
 IF p_base IS NULL OR p_base='' OR p_base<>btrim(p_base)
   OR p_tenant IS NULL OR p_tenant='' OR p_company IS NULL OR p_company='' THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID' USING ERRCODE='P0001';
 END IF;
 SELECT count(*) INTO n FROM (
  SELECT x.tenant_id,x.company_id FROM change_ledger.targets x
   WHERE x.base_fingerprint=p_base
  UNION
  SELECT r.tenant_id,r.company_id FROM change_ledger.records r
   WHERE r.base_fingerprint=p_base
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
      OR r.call_ownership='POSSIBLY_EXECUTING'
      OR (r.dispatch_state='DISPATCHED'
        AND NOT (r.execution_state IN ('APPLIED','FAILED_APPLY')
          AND r.call_ownership='PROVEN_FINISHED')))
  UNION
  SELECT a.tenant_id,a.company_id FROM change_ledger.dispatch_attempts a
   WHERE a.base_fingerprint=p_base AND a.state<>'TERMINAL_WITH_EVIDENCE'
  UNION
  SELECT b.tenant_id,b.company_id FROM change_ledger.writer_barriers b
   WHERE b.base_fingerprint=p_base AND b.progress='CLOSED_WITH_HOLD'
  UNION
  SELECT p_tenant,p_company
 ) scopes;
 IF n>64 THEN RAISE EXCEPTION 'BASE_SCOPE_LIMIT' USING ERRCODE='P0001'; END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_register_barrier_ack_v1(
 p_ack change_ledger.private_writer_barrier_ack_v1,p_ref text,p_signed_bytes bytea,
 p_trust_revision bigint
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.writer_barriers%ROWTYPE; b change_ledger.writer_barriers%ROWTYPE;
        service_binding change_ledger.private_writer_service_bindings%ROWTYPE;
        service_binding_hint change_ledger.private_writer_service_bindings%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE; p change_ledger.private_writer_process_attestations%ROWTYPE;
        k change_ledger.private_writer_signer_key_versions%ROWTYPE;
        sk change_ledger.private_writer_signer_key_versions%ROWTYPE;
        prior change_ledger.writer_barrier_acknowledgements%ROWTYPE; expected_calls uuid[];
        exact_tuple boolean; ref_lock text; initial_public_key bytea;
         key_material_lock_ids bigint[]; key_material_lock_id bigint;
        expected_ref text; ref_material bytea; key_id_bytes bytea; key_version_bytes bytea;
        supervisor_public_key bytea; supervisor_key_id text; supervisor_key_version text;
        current_trust_revision bigint;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF SESSION_USER<>'private_writer_evidence_ingest' OR p_ack IS NULL OR p_ack.barrier_id IS NULL
   OR p_trust_revision IS NULL OR p_trust_revision<=0
   OR p_ref IS NULL OR p_ref='' OR p_ref<>btrim(p_ref) OR p_signed_bytes IS NULL
   OR octet_length(p_signed_bytes)=0 OR p_ack.base_fingerprint IS NULL
   OR p_ack.scope IS NULL OR (p_ack.scope).tenant_id IS NULL OR (p_ack.scope).company_id IS NULL
   OR p_ack.lifecycle_epoch IS NULL OR p_ack.lifecycle_epoch<=0
   OR p_ack.barrier_origin_instance_id IS NULL OR p_ack.barrier_origin_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_ack.barrier_origin_service_epoch IS NULL OR p_ack.barrier_origin_service_epoch<=0
   OR p_ack.call_ids IS NULL OR p_ack.key_id IS NULL OR p_ack.key_version IS NULL
   OR p_ack.writer_service_id IS NULL OR p_ack.writer_host_id IS NULL OR p_ack.host_boot_id IS NULL
   OR p_ack.writer_process_instance_id IS NULL OR p_ack.writer_process_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_ack.process_attestation_ref IS NULL
   OR p_ack.writer_queue_epoch IS NULL OR p_ack.writer_queue_epoch<=0
   OR p_ack.local_queue_closed IS DISTINCT FROM true OR p_ack.signed_at IS NULL
   OR p_ack.signed_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$'
   OR p_ack.signature IS NULL OR octet_length(p_ack.signature)<>64
   OR octet_length(p_signed_bytes)>2097152
   OR p_ack.process_attestation_ref<>p_ack.writer_process_instance_id THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 -- Acknowledgements belong to one enabled physical writer binding. Hold the binding row through
 -- registration so revocation cannot race a newly stored acknowledgement for that base/service.
  SELECT * INTO service_binding_hint FROM change_ledger.private_writer_service_bindings x
  WHERE x.base_fingerprint=p_ack.base_fingerprint
    AND x.writer_service_id=p_ack.writer_service_id
    AND x.writer_host_id=p_ack.writer_host_id
    AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 key_id_bytes:=pg_catalog.convert_to(p_ack.key_id,'UTF8');
 key_version_bytes:=pg_catalog.convert_to(p_ack.key_version,'UTF8');
 ref_material:=pg_catalog.convert_to('ERP_MCP_R2:S13:PHYSICAL-WRITER-BARRIER-REF:v1'||E'\n','UTF8')
   ||pg_catalog.int4send(octet_length(p_signed_bytes))||p_signed_bytes
   ||pg_catalog.int4send(octet_length(p_ack.signature))||p_ack.signature
   ||pg_catalog.int4send(octet_length(key_id_bytes))||key_id_bytes
   ||pg_catalog.int4send(octet_length(key_version_bytes))||key_version_bytes;
 expected_ref:='barrier-ack:v1:'||pg_catalog.encode(pg_catalog.sha256(ref_material),'hex');
 IF p_ref IS DISTINCT FROM expected_ref THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO hint FROM change_ledger.writer_barriers x WHERE x.barrier_id=p_ack.barrier_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO p FROM change_ledger.private_writer_process_attestations x
  WHERE x.process_instance_id=p_ack.writer_process_instance_id::uuid;
 IF NOT FOUND OR ROW(p.host_boot_id,p.service_id,p.host_id)
   IS DISTINCT FROM ROW(p_ack.host_boot_id::uuid,p_ack.writer_service_id,p_ack.writer_host_id) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT public_key INTO supervisor_public_key FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=p.supervisor_key_id AND x.key_version=p.supervisor_key_version;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
  -- Snapshot both immutable key materials as hints before locking either key-material identity.
  SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
   WHERE x.key_id=p_ack.key_id AND x.key_version=p_ack.key_version;
  IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
  initial_public_key:=k.public_key;
  -- Plan both actual signed bigint key identities before acquiring ranked advisory fences.
  key_material_lock_ids:=ARRAY[
   pg_catalog.hashtextextended(encode(supervisor_public_key,'hex'),17017),
   pg_catalog.hashtextextended(encode(initial_public_key,'hex'),17017)
  ];
 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
  END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
  IF NOT FOUND OR lf.state<>'RECOVERING' OR lf.epoch<>hint.epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
  -- Match the documented rank and sort/deduplicate both planned signed bigint key identities.
  FOR key_material_lock_id IN
   SELECT DISTINCT lock_id FROM pg_catalog.unnest(key_material_lock_ids) AS planned(lock_id)
   ORDER BY lock_id
  LOOP
   PERFORM pg_catalog.pg_advisory_xact_lock(key_material_lock_id);
  END LOOP;
 ref_lock:='barrier-ack-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_ref,'UTF8')),'hex');
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'barrier-id:v1:'||lower(p_ack.barrier_id::text),ref_lock]);
  -- The trust revision row follows key-material and namespace-6 fences, matching trust writers.
  -- Holding it through commit prevents stale-key admission while preserving the common lock rank.
  SELECT revision INTO current_trust_revision
   FROM change_ledger.private_writer_trust_registry_revision
   WHERE revision_id=1 FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
  SELECT * INTO service_binding FROM change_ledger.private_writer_service_bindings x
   WHERE x.base_fingerprint=p_ack.base_fingerprint
     AND x.writer_service_id=p_ack.writer_service_id
     AND x.writer_host_id=p_ack.writer_host_id
     AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
  IF NOT FOUND OR service_binding IS DISTINCT FROM service_binding_hint THEN
   RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
  END IF;
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=p_ack.key_id AND x.key_version=p_ack.key_version FOR SHARE;
 IF NOT FOUND OR k.public_key IS DISTINCT FROM initial_public_key
   OR ROW(k.signer_role,k.service_id,k.host_id)
   IS DISTINCT FROM ROW('writer_receipt',p_ack.writer_service_id,p_ack.writer_host_id) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO p FROM change_ledger.private_writer_process_attestations x
  WHERE x.process_instance_id=p_ack.writer_process_instance_id::uuid FOR SHARE;
 SELECT * INTO sk FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=p.supervisor_key_id AND x.key_version=p.supervisor_key_version FOR SHARE;
 IF NOT FOUND OR sk.public_key IS DISTINCT FROM supervisor_public_key THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 supervisor_key_id:=sk.key_id;
 supervisor_key_version:=sk.key_version;
 SELECT * INTO b FROM change_ledger.writer_barriers x WHERE x.barrier_id=p_ack.barrier_id FOR UPDATE;
 IF NOT FOUND OR ROW(p_ack.base_fingerprint,(p_ack.scope).tenant_id,(p_ack.scope).company_id,
     p_ack.lifecycle_epoch,p_ack.barrier_origin_instance_id,p_ack.barrier_origin_service_epoch)
   IS DISTINCT FROM ROW(b.base_fingerprint,b.tenant_id,b.company_id,b.epoch,
     b.barrier_origin_instance_id,b.barrier_origin_service_epoch) THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(array_agg(c.call_id ORDER BY c.call_id),ARRAY[]::uuid[])
  INTO expected_calls FROM change_ledger.writer_barrier_calls c WHERE c.barrier_id=b.barrier_id;
 IF p_ack.call_ids IS DISTINCT FROM expected_calls THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO prior FROM change_ledger.writer_barrier_acknowledgements x
  WHERE x.barrier_id=b.barrier_id OR x.acknowledgement_ref=p_ref FOR SHARE;
 IF FOUND THEN
  exact_tuple:=prior.barrier_id=b.barrier_id AND prior.acknowledgement_ref=p_ref
   AND prior.signed_bytes=p_signed_bytes AND prior.signer_key_id=p_ack.key_id
   AND prior.signer_key_version=p_ack.key_version
   AND ROW(prior.base_fingerprint,prior.tenant_id,prior.company_id,prior.lifecycle_epoch,
      prior.barrier_origin_instance_id,prior.barrier_origin_service_epoch,prior.call_ids,
      prior.writer_service_id,prior.writer_host_id,prior.host_boot_id,
      prior.writer_process_instance_id,prior.process_attestation_ref,prior.writer_queue_epoch,
      prior.local_queue_closed,prior.signed_at,prior.signature_bytes,
      prior.signed_bytes_sha256)
    IS NOT DISTINCT FROM ROW(p_ack.base_fingerprint,(p_ack.scope).tenant_id,(p_ack.scope).company_id,
      p_ack.lifecycle_epoch,p_ack.barrier_origin_instance_id,p_ack.barrier_origin_service_epoch,
      p_ack.call_ids,p_ack.writer_service_id,p_ack.writer_host_id,p_ack.host_boot_id,
      p_ack.writer_process_instance_id,p_ack.process_attestation_ref,p_ack.writer_queue_epoch,
      p_ack.local_queue_closed,p_ack.signed_at::timestamptz,p_ack.signature,
      pg_catalog.sha256(p_signed_bytes));
  IF exact_tuple THEN RETURN prior.acknowledgement_ref; END IF;
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
  IF current_trust_revision IS DISTINCT FROM p_trust_revision THEN
  RAISE EXCEPTION 'EVIDENCE_TRUST_REVISION_STALE' USING ERRCODE='P0001';
 END IF;
 IF p_ack.signed_at::timestamptz<k.valid_from
   OR p_ack.signed_at::timestamptz>=k.valid_until
   OR p_ack.signed_at::timestamptz>pg_catalog.clock_timestamp()
   OR pg_catalog.clock_timestamp()<k.valid_from
   OR pg_catalog.clock_timestamp()>=k.valid_until
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=k.key_id AND r.key_version=k.key_version) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 IF sk.signer_role<>'completion_supervisor' OR sk.host_id<>p_ack.writer_host_id
   OR sk.service_id=p_ack.writer_service_id
   OR p.process_created_at<sk.valid_from OR p.process_created_at>=sk.valid_until
   OR pg_catalog.clock_timestamp()<sk.valid_from
   OR pg_catalog.clock_timestamp()>=sk.valid_until
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=supervisor_key_id AND r.key_version=supervisor_key_version) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 IF b.progress<>'CLOSED_WITH_HOLD' THEN RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001'; END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_process_attestations candidate_process
      WHERE candidate_process.process_instance_id=p_ack.writer_process_instance_id::uuid
       AND candidate_process.host_boot_id=p_ack.host_boot_id::uuid
       AND candidate_process.service_id=p_ack.writer_service_id
       AND candidate_process.host_id=p_ack.writer_host_id
       AND candidate_process.process_created_at<=p_ack.signed_at::timestamptz) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.writer_barrier_acknowledgements(
  acknowledgement_ref,barrier_id,base_fingerprint,tenant_id,company_id,lifecycle_epoch,
  barrier_origin_instance_id,barrier_origin_service_epoch,call_ids,writer_service_id,writer_host_id,
  host_boot_id,writer_process_instance_id,process_attestation_ref,writer_queue_epoch,
  local_queue_closed,signed_at,signed_bytes,signature_bytes,signed_bytes_sha256,
  signer_key_id,signer_key_version,verified_at)
 VALUES(p_ref,b.barrier_id,b.base_fingerprint,b.tenant_id,b.company_id,b.epoch,
  b.barrier_origin_instance_id,b.barrier_origin_service_epoch,expected_calls,
  p_ack.writer_service_id,p_ack.writer_host_id,p_ack.host_boot_id,p_ack.writer_process_instance_id,
  p_ack.process_attestation_ref,p_ack.writer_queue_epoch,true,p_ack.signed_at::timestamptz,
  p_signed_bytes,p_ack.signature,pg_catalog.sha256(p_signed_bytes),
  p_ack.key_id,p_ack.key_version,clock_timestamp());
 RETURN p_ref;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_admit_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_instance_id text,
 p_service_epoch bigint
) RETURNS change_ledger.private_writer_admission_decision_v1
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 DECLARE b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE;
        i change_ledger.private_writer_dispatch_intents%ROWTYPE;
        pb change_ledger.private_writer_permit_bindings%ROWTYPE;
        existing change_ledger.dispatch_attempts%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        cas_id uuid:=pg_catalog.gen_random_uuid();
        permit_id uuid; repair_id uuid; outcome change_ledger.private_writer_call_snapshot_v1;
        changed integer;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_identity.tenant_id IS NULL OR p_identity.tenant_id=''
   OR p_identity.company_id IS NULL OR p_identity.company_id=''
   OR p_identity.organization_ref IS NULL OR p_identity.organization_ref=''
   OR p_identity.change_id IS NULL
   OR p_identity.change_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_identity.generation IS NULL OR p_identity.generation<=0
   OR p_identity.call_id IS NULL
   OR p_identity.call_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_identity.epoch IS NULL OR p_identity.epoch<=0
   OR p_identity.operation IS NULL OR p_identity.operation NOT IN ('CREATE_DRAFT','POST','UNPOST')
   OR p_identity.payload_digest IS NULL OR p_identity.payload_digest !~ '^[a-f0-9]{64}$'
   OR p_identity.permit_digest IS NULL OR p_identity.permit_digest !~ '^[a-f0-9]{64}$'
   OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR lower(p_identity.permit_id)='00000000-0000-0000-0000-000000000000'
   OR p_identity.base_fingerprint IS NULL OR p_identity.base_fingerprint=''
   OR p_identity.host_id IS NULL OR p_identity.host_id=''
   OR p_instance_id IS NULL OR p_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_service_epoch IS NULL OR p_service_epoch<=0
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       (p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        OR lower(p_identity.repair_authorization_id)='00000000-0000-0000-0000-000000000000')) THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT');
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;

 -- This unlocked binding read selects the authenticated physical-base fence. Re-read and lock it
 -- after the advisory plan; the login identity itself is never accepted from the caller.
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_identity.base_fingerprint
   AND x.writer_host_id=p_identity.host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(p_identity.tenant_id,p_identity.company_id);
 PERFORM change_ledger.private_writer_take_base_fence_v1(b.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(p_identity.tenant_id,p_identity.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id FOR UPDATE;
 IF NOT FOUND THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'STALE_EPOCH');
 END IF;
 -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 IF NOT FOUND OR lf.state<>'READY' OR lf.epoch<>p_identity.epoch THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'STALE_EPOCH');
 END IF;

 -- Allocate the CAS identity before the first row lock, then serialize its global unique key
 -- together with call/change identities using the canonical signed hash order.
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'call-id:v1:'||lower(p_identity.call_id::text),
  'record-change-id:v1:'||lower(p_identity.change_id::text),
  'dispatch-cas-id:v1:'||lower(cas_id::text)
 ]);
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_identity.base_fingerprint
   AND x.writer_host_id=p_identity.host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR SHARE;
 IF NOT FOUND OR serving.service_instance_id<>p_instance_id
   OR serving.service_epoch<>p_service_epoch OR serving.readiness_ref IS NULL THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'STALE_EPOCH');
 END IF;
 -- A global call ID is lookup-only on exact replay and conflicts across scopes or identities.
 SELECT * INTO existing FROM change_ledger.dispatch_attempts x WHERE x.call_id=p_identity.call_id;
 IF FOUND THEN
  outcome:=change_ledger.private_writer_lookup_v1(p_identity);
  RETURN ROW(p_identity,outcome.state,false,outcome.dispatch_cas_id,
    existing.writer_process_instance_id,outcome.evidence_ref,NULL)
   ::change_ledger.private_writer_admission_decision_v1;
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=b.base_fingerprint;
 IF NOT FOUND OR slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'WRITER_ADMISSION_CLOSED');
 END IF;
 IF slot.active_dispatch_cas_id IS NOT NULL THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'BASE_CALL_IN_PROGRESS');
 END IF;
 PERFORM change_ledger.assert_switch_off(p_identity.tenant_id,p_identity.company_id);
 IF EXISTS(SELECT 1 FROM change_ledger.private_writer_dispatch_intents x
    WHERE x.call_id=p_identity.call_id AND x.base_fingerprint<>p_identity.base_fingerprint)
   OR EXISTS(SELECT 1 FROM change_ledger.dispatch_permits x
    WHERE x.call_id=p_identity.call_id AND x.change_id<>p_identity.change_id) THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT');
 END IF;

 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id
   AND x.change_id=p_identity.change_id FOR UPDATE;
 IF NOT FOUND THEN RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT'); END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_identity.change_id AND x.generation=p_identity.generation FOR UPDATE;
 IF NOT FOUND THEN RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT'); END IF;
 SELECT * INTO i FROM change_ledger.private_writer_dispatch_intents x
  WHERE x.call_id=p_identity.call_id AND x.change_id=p_identity.change_id
   AND x.claim_generation=p_identity.generation FOR UPDATE;
 IF NOT FOUND THEN RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT'); END IF;
 SELECT * INTO pb FROM change_ledger.private_writer_permit_bindings x
  WHERE x.dispatch_intent_id=i.dispatch_intent_id FOR UPDATE;
 IF NOT FOUND THEN RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT'); END IF;

 IF ROW(rec.tenant_id,rec.company_id,rec.organization_ref,rec.base_fingerprint,rec.claim_generation,
        rec.payload_digest,rec.target_ref,rec.target_version,rec.auth_epoch_at_proposal,
        rec.repair_for,rec.execution_state,rec.authorization_state,rec.dispatch_state)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
        p_identity.base_fingerprint,p_identity.generation,p_identity.payload_digest,
        p_identity.target_ref,p_identity.target_version,p_identity.epoch,repair_id,
        'APPLYING','CLAIMED','PERMITTED')
   OR ROW(i.tenant_id,i.company_id,i.organization_ref,i.base_fingerprint,i.change_id,
        i.claim_generation,i.call_id,i.operation_kind,i.payload_digest,i.target_ref,
        i.expected_pre_version,i.auth_epoch,i.repair_authorization_id)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
        p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
        p_identity.operation,p_identity.payload_digest,p_identity.target_ref,p_identity.target_version,
        p_identity.epoch,repair_id)
   OR i.approval_digest IS DISTINCT FROM change_ledger.approval_digest(rec.change_id)
   OR dp.state<>'PERMITTED' OR dp.call_id IS DISTINCT FROM p_identity.call_id
   OR dp.writer_host IS DISTINCT FROM p_identity.host_id OR dp.lifecycle_epoch<>p_identity.epoch
   OR dp.permit_digest IS DISTINCT FROM p_identity.permit_digest
   OR dp.expires_at IS NULL OR dp.expires_at<=clock_timestamp()
   OR pb.permit_id<>permit_id OR pb.permit_digest<>p_identity.permit_digest
   OR pb.checkpoint_seq<>dp.checkpoint_seq OR pb.signer_key_id IS DISTINCT FROM dp.signer_key_id
   OR i.dispatch_intent_id IS DISTINCT FROM pb.dispatch_intent_id THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'CALL_IDENTITY_CONFLICT');
 END IF;
 IF change_ledger.blocking_hold(p_identity.tenant_id,p_identity.company_id,
      rec.base_fingerprint,rec.repair_for) THEN
  RETURN change_ledger.private_writer_refusal_v1(p_identity,'WRITER_ADMISSION_CLOSED');
 END IF;
 PERFORM change_ledger.assert_target_effect(p_identity.tenant_id,p_identity.company_id,
   rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 PERFORM change_ledger.assert_repair_authorized(p_identity.tenant_id,p_identity.company_id,rec);
 PERFORM change_ledger.assert_approval_current(p_identity.tenant_id,p_identity.company_id,rec);
 PERFORM change_ledger.assert_dispatch_verified(p_identity.change_id,p_identity.generation);

 BEGIN
  IF NOT change_ledger.dispatch_cas(p_identity.change_id,p_identity.generation,'PERMITTED','DISPATCHED') THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  INSERT INTO change_ledger.dispatch_attempts(
   dispatch_cas_id,dispatch_intent_id,tenant_id,company_id,organization_ref,base_fingerprint,
   change_id,claim_generation,dispatch_generation,call_id,operation_kind,approval_digest,payload_digest,
   permit_id,permit_digest,expected_target_ref,expected_pre_version,auth_epoch,repair_authorization_id,
   "session_user",writer_service_id,writer_host_id,writer_process_instance_id,service_epoch,
   onec_session_instance_id,state,invocation_started_at,terminalized_at)
  VALUES(cas_id,i.dispatch_intent_id,i.tenant_id,i.company_id,i.organization_ref,i.base_fingerprint,
   i.change_id,i.claim_generation,i.dispatch_generation,i.call_id,i.operation_kind,i.approval_digest,
   i.payload_digest,pb.permit_id,pb.permit_digest,i.target_ref,i.expected_pre_version,i.auth_epoch,
   i.repair_authorization_id,SESSION_USER,b.writer_service_id,b.writer_host_id,p_instance_id,
   p_service_epoch,dp.onec_session,'ACCEPTED_NOT_INVOKED',NULL,NULL);
  UPDATE change_ledger.records SET dispatch_state='DISPATCHED',updated_at=clock_timestamp()
   WHERE tenant_id=p_identity.tenant_id AND company_id=p_identity.company_id
    AND change_id=p_identity.change_id;
  UPDATE change_ledger.physical_base_slots SET active_dispatch_cas_id=cas_id
   WHERE base_fingerprint=b.base_fingerprint AND active_dispatch_cas_id IS NULL
    AND open_barrier_id IS NULL AND NOT admission_closed;
  GET DIAGNOSTICS changed=ROW_COUNT;
  IF changed<>1 THEN RAISE EXCEPTION 'BASE_CALL_IN_PROGRESS' USING ERRCODE='P0001'; END IF;
  PERFORM change_ledger.append_event(p_identity.tenant_id,p_identity.company_id,
   p_identity.change_id,'DISPATCHED',jsonb_build_object(
    'generation',p_identity.generation,'call_id',p_identity.call_id,'dispatch_cas_id',cas_id));
 EXCEPTION
  WHEN unique_violation THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  WHEN SQLSTATE 'P0001' THEN
   RAISE;
 END;
 RETURN ROW(p_identity,'ACCEPTED_NOT_INVOKED',true,cas_id,p_instance_id,NULL,NULL)
  ::change_ledger.private_writer_admission_decision_v1;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_mark_invoking_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_dispatch_cas_id uuid,
 p_instance_id text,
 p_service_epoch bigint
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE;
        i change_ledger.private_writer_dispatch_intents%ROWTYPE;
        pb change_ledger.private_writer_permit_bindings%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        permit_id uuid; repair_id uuid; changed integer;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid OR p_identity.call_id IS NULL
   OR p_identity.change_id IS NULL OR p_identity.tenant_id IS NULL OR p_identity.tenant_id=''
   OR p_identity.company_id IS NULL OR p_identity.company_id=''
   OR p_identity.base_fingerprint IS NULL OR p_identity.base_fingerprint=''
   OR p_identity.host_id IS NULL OR p_identity.host_id=''
   OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR p_identity.repair_authorization_id IS NOT NULL AND
      p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR p_instance_id IS NULL OR p_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_service_epoch IS NULL OR p_service_epoch<=0 THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_identity.base_fingerprint
   AND x.writer_host_id=p_identity.host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(p_identity.tenant_id,p_identity.company_id);
 PERFORM change_ledger.private_writer_take_base_fence_v1(b.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(p_identity.tenant_id,p_identity.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 IF NOT FOUND OR lf.state<>'READY' OR lf.epoch<>p_identity.epoch THEN RETURN false; END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'call-id:v1:'||lower(p_identity.call_id::text),
  'record-change-id:v1:'||lower(p_identity.change_id::text),
  'dispatch-cas-id:v1:'||lower(p_dispatch_cas_id::text)
 ]);
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_identity.base_fingerprint
   AND x.writer_host_id=p_identity.host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR SHARE;
 IF NOT FOUND OR serving.service_instance_id<>p_instance_id
   OR serving.service_epoch<>p_service_epoch OR serving.readiness_ref IS NULL THEN RETURN false; END IF;
 PERFORM change_ledger.assert_switch_off(p_identity.tenant_id,p_identity.company_id);

 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id
   AND x.change_id=p_identity.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_identity.change_id AND x.generation=p_identity.generation FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO i FROM change_ledger.private_writer_dispatch_intents x
  WHERE x.dispatch_intent_id=(SELECT y.dispatch_intent_id FROM change_ledger.dispatch_attempts y
    WHERE y.dispatch_cas_id=p_dispatch_cas_id) FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO pb FROM change_ledger.private_writer_permit_bindings x
  WHERE x.dispatch_intent_id=i.dispatch_intent_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=b.base_fingerprint FOR UPDATE;
 IF NOT FOUND OR slot.active_dispatch_cas_id IS DISTINCT FROM p_dispatch_cas_id
   OR slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN RETURN false; END IF;

 IF ROW(rec.tenant_id,rec.company_id,rec.organization_ref,rec.base_fingerprint,rec.claim_generation,
        rec.payload_digest,rec.target_ref,rec.target_version,rec.auth_epoch_at_proposal,rec.repair_for)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
        p_identity.base_fingerprint,p_identity.generation,p_identity.payload_digest,
        p_identity.target_ref,p_identity.target_version,p_identity.epoch,repair_id)
   OR ROW(i.tenant_id,i.company_id,i.organization_ref,i.base_fingerprint,i.change_id,
        i.claim_generation,i.call_id,i.operation_kind,i.payload_digest,i.target_ref,i.expected_pre_version,
        i.auth_epoch,i.repair_authorization_id,i.approval_digest)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
        p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
        p_identity.operation,p_identity.payload_digest,p_identity.target_ref,p_identity.target_version,
        p_identity.epoch,repair_id,change_ledger.approval_digest(rec.change_id))
   OR a.dispatch_intent_id IS DISTINCT FROM i.dispatch_intent_id
   OR ROW(a."session_user",a.writer_service_id,a.writer_host_id,a.writer_process_instance_id,a.service_epoch,
        a.call_id,a.permit_id,a.permit_digest)
   IS DISTINCT FROM ROW(SESSION_USER,b.writer_service_id,b.writer_host_id,p_instance_id,p_service_epoch,
        p_identity.call_id,permit_id,p_identity.permit_digest)
   OR dp.state<>'DISPATCHED' OR dp.call_id IS DISTINCT FROM p_identity.call_id
   OR dp.writer_host IS DISTINCT FROM p_identity.host_id OR dp.lifecycle_epoch<>p_identity.epoch
   OR dp.permit_digest IS DISTINCT FROM p_identity.permit_digest
   OR pb.permit_id<>permit_id OR pb.permit_digest<>p_identity.permit_digest
   OR pb.checkpoint_seq<>dp.checkpoint_seq OR pb.signer_key_id IS DISTINCT FROM dp.signer_key_id THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF a.state<>'ACCEPTED_NOT_INVOKED' THEN RETURN false; END IF;
 IF a.writer_process_instance_id<>p_instance_id THEN RETURN false; END IF;
 IF change_ledger.blocking_hold(p_identity.tenant_id,p_identity.company_id,
      rec.base_fingerprint,rec.repair_for) THEN RETURN false; END IF;
 PERFORM change_ledger.assert_target_effect(p_identity.tenant_id,p_identity.company_id,
   rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 PERFORM change_ledger.assert_repair_authorized(p_identity.tenant_id,p_identity.company_id,rec);
 PERFORM change_ledger.assert_approval_current(p_identity.tenant_id,p_identity.company_id,rec);
 PERFORM change_ledger.assert_dispatch_verified(p_identity.change_id,p_identity.generation);

 UPDATE change_ledger.dispatch_attempts SET state='POSSIBLY_EXECUTING',
  invocation_started_at=clock_timestamp()
  WHERE dispatch_cas_id=p_dispatch_cas_id AND state='ACCEPTED_NOT_INVOKED';
 GET DIAGNOSTICS changed=ROW_COUNT;
 RETURN changed=1;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_begin_com_entry_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_dispatch_cas_id uuid,
 p_instance_id text,
 p_service_epoch bigint
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.dispatch_attempts%ROWTYPE;
        b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        repair_id uuid;
        permit_id uuid;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid OR p_identity.call_id IS NULL
   OR p_identity.change_id IS NULL OR p_identity.tenant_id IS NULL OR p_identity.tenant_id=''
   OR p_identity.company_id IS NULL OR p_identity.company_id=''
   OR p_identity.base_fingerprint IS NULL OR p_identity.base_fingerprint=''
   OR p_identity.host_id IS NULL OR p_identity.host_id=''
   OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
   OR p_instance_id IS NULL OR p_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_service_epoch IS NULL OR p_service_epoch<=0 THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 SELECT * INTO hint FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id
   AND x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 -- The same switch/base/scope and global identity plan as admit/mark_invoking makes this
 -- one-way entry CAS race atomically with takeover, barriers, and non-entry recovery.
 PERFORM change_ledger.private_writer_take_switch_fence_v1(p_identity.tenant_id,p_identity.company_id);
 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(p_identity.tenant_id,p_identity.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 IF NOT FOUND OR lf.state<>'READY' OR lf.epoch<>p_identity.epoch THEN RETURN false; END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(p_identity.change_id::text),
  'call-id:v1:'||lower(p_identity.call_id::text),
  'dispatch-cas-id:v1:'||lower(p_dispatch_cas_id::text)
 ]);
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_identity.base_fingerprint
   AND x.writer_host_id=p_identity.host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR SHARE;
 IF NOT FOUND OR serving.service_instance_id IS DISTINCT FROM p_instance_id
   OR serving.service_epoch IS DISTINCT FROM p_service_epoch OR serving.readiness_ref IS NULL THEN
  RETURN false;
 END IF;
 PERFORM change_ledger.assert_switch_off(p_identity.tenant_id,p_identity.company_id);
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id
   AND x.change_id=p_identity.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_identity.change_id AND x.generation=p_identity.generation FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR ROW(a.tenant_id,a.company_id,a.organization_ref,a.base_fingerprint,a.change_id,
      a.claim_generation,a.call_id,a.operation_kind,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.payload_digest,a.permit_id::text,a.permit_digest,a.writer_host_id,a.repair_authorization_id,
      a.writer_process_instance_id,a.service_epoch)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
      p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
      p_identity.operation,p_identity.target_ref,p_identity.target_version,p_identity.epoch,
      p_identity.payload_digest,p_identity.permit_id,p_identity.permit_digest,p_identity.host_id,repair_id,
      p_instance_id,p_service_epoch)
   OR rec.claim_generation<>a.claim_generation OR rec.base_fingerprint<>a.base_fingerprint
   OR rec.execution_state<>'APPLYING' OR rec.authorization_state<>'CLAIMED'
   OR rec.dispatch_state<>'DISPATCHED' OR dp.state<>'DISPATCHED'
   OR dp.call_id IS DISTINCT FROM a.call_id OR dp.writer_host IS DISTINCT FROM a.writer_host_id
   OR dp.lifecycle_epoch<>p_identity.epoch OR dp.permit_digest IS DISTINCT FROM a.permit_digest THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=a.base_fingerprint FOR UPDATE;
 IF NOT FOUND OR slot.active_dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id
   OR slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN
  RETURN false;
 END IF;
 IF a.state<>'POSSIBLY_EXECUTING' OR a.writer_process_instance_id<>p_instance_id THEN
  RETURN false;
 END IF;
 IF a.com_entry_authorized_at IS NOT NULL THEN
  -- A replay must never invoke a second time. The existing durable guard may belong to a
  -- call whose response was lost; only recovery may inspect its evidence.
  RETURN false;
 END IF;
 PERFORM change_ledger.assert_target_effect(p_identity.tenant_id,p_identity.company_id,
   rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 PERFORM change_ledger.assert_repair_authorized(p_identity.tenant_id,p_identity.company_id,rec);
 PERFORM change_ledger.assert_approval_current(p_identity.tenant_id,p_identity.company_id,rec);
 PERFORM change_ledger.assert_dispatch_verified(p_identity.change_id,p_identity.generation);
 UPDATE change_ledger.dispatch_attempts SET com_entry_authorized_at=clock_timestamp()
  WHERE dispatch_cas_id=a.dispatch_cas_id AND state='POSSIBLY_EXECUTING'
   AND com_entry_authorized_at IS NULL;
 RETURN FOUND;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_issue_permit_v1(
 p_tenant text,p_company text,p_change_id uuid,p_generation bigint,
 p_dispatch_intent_id uuid,p_permit_id uuid,p_signer_key_id text,p_signer_key_version text,
 p_signature text
) RETURNS change_ledger.private_writer_permit_binding_v1
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE caller text; intent change_ledger.private_writer_dispatch_intents%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE; rec change_ledger.records%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE; old_binding change_ledger.private_writer_permit_bindings%ROWTYPE;
        signer change_ledger.private_writer_signer_key_versions%ROWTYPE;
        vk change_ledger.verifier_keys%ROWTYPE; key_hex text; issued jsonb;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.assert_scope(p_tenant,p_company);
 caller:=change_ledger.caller_role();
 IF NOT pg_has_role(caller::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_generation IS NULL OR p_generation<=0
   OR p_dispatch_intent_id IS NULL
   OR p_dispatch_intent_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_permit_id IS NULL OR p_permit_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_signer_key_id IS NULL OR p_signer_key_id='' OR p_signer_key_version IS NULL
   OR p_signer_key_version='' OR p_signature IS NULL OR p_signature !~ '^[a-f0-9]{128}$' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO intent FROM change_ledger.private_writer_dispatch_intents x
  WHERE x.dispatch_intent_id=p_dispatch_intent_id;
 IF NOT FOUND OR ROW(intent.tenant_id,intent.company_id,intent.change_id,intent.claim_generation)
   IS DISTINCT FROM ROW(p_tenant,p_company,p_change_id,p_generation) THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 SELECT * INTO signer FROM change_ledger.private_writer_signer_key_versions k
  WHERE k.key_id=p_signer_key_id AND k.key_version=p_signer_key_version;
 IF NOT FOUND OR signer.signer_role<>'checkpoint_signer' THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 key_hex:=encode(signer.public_key,'hex');
 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=p_tenant AND k.company_id=p_company AND k.key_id=p_signer_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
   OR vk.key_algorithm<>'ED25519' OR vk.key_material IS DISTINCT FROM key_hex THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(p_tenant,p_company);
 -- Permit issuance is part of the private-writer path: serialize it with base-slot/barrier
 -- transitions before taking the scope fence, using the base fingerprint frozen in the intent.
 PERFORM change_ledger.private_writer_take_base_fence_v1(intent.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(p_tenant,p_company);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_tenant AND x.company_id=p_company FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
  END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=p_tenant AND x.company_id=p_company;
  IF NOT FOUND OR lf.state<>'READY' OR lf.epoch<>intent.auth_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 -- Match the legacy verifier-key material advisory identity before namespace 6.
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(vk.key_material,17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'call-id:v1:'||lower(intent.call_id::text),
  'record-change-id:v1:'||lower(p_change_id::text),
  'dispatch-intent-id:v1:'||lower(p_dispatch_intent_id::text),
  'permit-id:v1:'||lower(p_permit_id::text),
  'signer-key-version:v1:'||p_signer_key_id||':'||p_signer_key_version
 ]);
 SELECT * INTO signer FROM change_ledger.private_writer_signer_key_versions k
  WHERE k.key_id=p_signer_key_id AND k.key_version=p_signer_key_version FOR SHARE;
 IF NOT FOUND OR signer.signer_role<>'checkpoint_signer' THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=p_tenant AND k.company_id=p_company AND k.key_id=p_signer_key_id FOR SHARE;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
   OR vk.key_algorithm<>'ED25519' OR vk.key_material IS DISTINCT FROM encode(signer.public_key,'hex') THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
   WHERE s.key_id=signer.key_id AND s.key_version=signer.key_version
    AND s.tenant_id=p_tenant AND s.company_id=p_company
    AND s.organization_ref=intent.organization_ref AND s.base_fingerprint=intent.base_fingerprint) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=p_tenant AND r.company_id=p_company AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(p_tenant,p_company);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 -- The exact-binding replay must retain the legacy issue_permit authorization and current-state
 -- guards. A previous binding does not authorize replay after switch, target, registry, repair,
 -- generation, or execution state has changed.
 PERFORM change_ledger.assert_switch_off(p_tenant,p_company);
 PERFORM change_ledger.assert_target_effect(
  p_tenant,p_company,rec.base_fingerprint,rec.organization_ref,rec.declared_target_class);
 PERFORM change_ledger.assert_registry_for_effect(
  p_tenant,p_company,rec.base_fingerprint);
 PERFORM change_ledger.assert_repair_authorized(p_tenant,p_company,rec);
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation FOR UPDATE;
 IF NOT FOUND OR dp.call_id IS DISTINCT FROM intent.call_id THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 SELECT * INTO intent FROM change_ledger.private_writer_dispatch_intents x
  WHERE x.dispatch_intent_id=p_dispatch_intent_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 SELECT * INTO old_binding FROM change_ledger.private_writer_permit_bindings x
  WHERE x.dispatch_intent_id=p_dispatch_intent_id;
 IF FOUND THEN
  -- The legacy route replays only a currently PERMITTED row. Preserve its expiry-independent
  -- replay rule, but never return a binding after dispatch or revocation changed the row state.
  IF dp.state<>'PERMITTED' THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
  IF old_binding.permit_id IS DISTINCT FROM p_permit_id
    OR old_binding.signer_key_id IS DISTINCT FROM p_signer_key_id
    OR old_binding.signer_key_version IS DISTINCT FROM p_signer_key_version
    OR dp.signer_key_id IS DISTINCT FROM p_signer_key_id
    OR dp.signature IS DISTINCT FROM p_signature
    OR dp.permit_digest IS DISTINCT FROM old_binding.permit_digest
    OR dp.checkpoint_seq IS DISTINCT FROM old_binding.checkpoint_seq THEN
   RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN ROW(old_binding.dispatch_intent_id,old_binding.permit_id,old_binding.permit_digest,
   old_binding.checkpoint_seq,old_binding.signer_key_id,old_binding.signer_key_version,
   old_binding.issued_at,old_binding.expires_at)::change_ledger.private_writer_permit_binding_v1;
 END IF;

 issued:=change_ledger.issue_permit(p_tenant,p_company,p_change_id,p_generation);
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation FOR UPDATE;
 IF NOT FOUND OR dp.state<>'PERMITTED' OR dp.checkpoint_seq IS NULL OR dp.checkpoint_seq<=0
   OR dp.permit_digest IS NULL OR dp.expires_at IS NULL OR dp.issued_at IS NULL
   OR dp.expires_at<=clock_timestamp() OR dp.call_id IS DISTINCT FROM intent.call_id THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 IF signer.valid_from>dp.issued_at OR signer.valid_until<=dp.issued_at
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations x
     WHERE x.key_id=signer.key_id AND x.key_version=signer.key_version
       AND x.revoked_at<=dp.issued_at)
   OR NOT change_ledger.signature_ok('ED25519',encode(signer.public_key,'hex'),
        'change-ledger-permit|v1|'||dp.permit_digest,p_signature) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 IF dp.signer_key_id IS NOT NULL AND
   (dp.signer_key_id IS DISTINCT FROM p_signer_key_id OR dp.signature IS DISTINCT FROM p_signature) THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 UPDATE change_ledger.dispatch_permits SET signer_key_id=p_signer_key_id,signature=p_signature
  WHERE change_id=p_change_id AND generation=p_generation AND state='PERMITTED'
   AND (signer_key_id IS NULL OR (signer_key_id=p_signer_key_id AND signature=p_signature));
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 INSERT INTO change_ledger.private_writer_permit_bindings(
  dispatch_intent_id,permit_id,permit_digest,checkpoint_seq,signer_key_id,signer_key_version,issued_at,expires_at)
 VALUES(p_dispatch_intent_id,p_permit_id,dp.permit_digest,dp.checkpoint_seq,p_signer_key_id,
  p_signer_key_version,dp.issued_at,dp.expires_at);
 RETURN ROW(p_dispatch_intent_id,p_permit_id,dp.permit_digest,dp.checkpoint_seq,
  p_signer_key_id,p_signer_key_version,dp.issued_at,dp.expires_at)
  ::change_ledger.private_writer_permit_binding_v1;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.change_ledger_begin_apply_v1(
 p_tenant text,p_company text,p_token_id uuid,p_call_id uuid,p_writer_host text,p_onec_session text
) RETURNS change_ledger.claim_tokens
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE caller text; token_hint change_ledger.claim_tokens%ROWTYPE;
        tok change_ledger.claim_tokens%ROWTYPE; rec change_ledger.records%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE; intent change_ledger.private_writer_dispatch_intents%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE; intent_id uuid:=pg_catalog.gen_random_uuid();
        next_dispatch_generation bigint; approved_digest text; operation_kind text;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.assert_scope(p_tenant,p_company);
 caller:=change_ledger.caller_role();
 IF caller IS NULL OR caller='' THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_token_id IS NULL OR p_token_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_call_id IS NULL OR p_call_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_writer_host IS NULL OR p_writer_host=''
   OR p_writer_host<>btrim(p_writer_host) OR p_onec_session IS NULL OR p_onec_session=''
   OR p_onec_session<>btrim(p_onec_session) THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO token_hint FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(p_tenant,p_company);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(p_tenant,p_company);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_tenant AND x.company_id=p_company FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=p_tenant AND x.company_id=p_company;
  IF NOT FOUND OR lf.state<>'READY' THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 PERFORM change_ledger.assert_switch_off(p_tenant,p_company);

  PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
   'call-id:v1:'||lower(p_call_id::text),
   'claim-token-id:v1:'||lower(p_token_id::text),
   'record-change-id:v1:'||lower(token_hint.change_id::text),
   'dispatch-intent-id:v1:'||lower(intent_id::text)
  ]);
 -- The record is the claim-token FK parent and is locked first; the token is re-read
 -- afterward so the unlocked discovery read cannot authorize a stale parent/generation pair.
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=p_tenant AND r.company_id=p_company
   AND r.change_id=token_hint.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT * INTO tok FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id FOR UPDATE;
 IF NOT FOUND OR tok.change_id IS DISTINCT FROM rec.change_id THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(p_tenant,p_company);
 IF tok.generation<>rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF caller IS DISTINCT FROM rec.requester AND NOT pg_has_role(caller::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;

 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=rec.change_id AND x.generation=tok.generation FOR UPDATE;
 IF tok.state='CONSUMED' THEN
  SELECT * INTO intent FROM change_ledger.private_writer_dispatch_intents x
   WHERE x.change_id=rec.change_id AND x.claim_generation=tok.generation;
  IF rec.execution_state='APPLYING' AND rec.authorization_state='CLAIMED'
    AND rec.dispatch_state<>'DISPATCHED' AND FOUND
    AND dp.call_id=p_call_id AND dp.writer_host=p_writer_host AND dp.onec_session=p_onec_session
    AND dp.lifecycle_epoch=lf.epoch AND intent.auth_epoch=lf.epoch
    AND intent.call_id=p_call_id AND intent.base_fingerprint=rec.base_fingerprint THEN
   RETURN tok;
  END IF;
  IF FOUND AND (dp.call_id IS DISTINCT FROM p_call_id OR dp.writer_host IS DISTINCT FROM p_writer_host
      OR dp.onec_session IS DISTINCT FROM p_onec_session) THEN
   RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 IF tok.state<>'ISSUED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.private_writer_dispatch_intents x
    WHERE x.call_id=p_call_id AND (x.change_id<>rec.change_id OR x.claim_generation<>tok.generation))
   OR EXISTS(SELECT 1 FROM change_ledger.dispatch_permits x
    WHERE x.call_id=p_call_id AND (x.change_id<>rec.change_id OR x.generation<>tok.generation)) THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF rec.execution_state<>'NOT_STARTED' OR rec.dispatch_state<>'NOT_PERMITTED' THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;
 IF rec.authorization_state<>'CLAIMED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 IF lf.epoch<>rec.auth_epoch_at_proposal OR NOT change_ledger.epoch_deps_current(
    p_tenant,p_company,rec.epoch_dependencies) THEN RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001'; END IF;
 IF change_ledger.blocking_hold(p_tenant,p_company,rec.base_fingerprint,rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
 PERFORM change_ledger.assert_target_effect(p_tenant,p_company,rec.base_fingerprint,
   rec.organization_ref,rec.declared_target_class);
 IF change_ledger.registry_enforced(p_tenant,p_company) AND NOT EXISTS(
   SELECT 1 FROM change_ledger.target_observations o
    WHERE o.change_id=rec.change_id AND o.generation=tok.generation
     AND o.observed_fingerprint=rec.base_fingerprint) THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.assert_repair_authorized(p_tenant,p_company,rec);
 PERFORM change_ledger.assert_approval_current(p_tenant,p_company,rec);
 approved_digest:=change_ledger.approval_digest(rec.change_id);
 IF approved_digest IS NULL THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.kind NOT IN ('CREATE_DRAFT','POST','UNPOST') THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 operation_kind:=rec.kind;
 SELECT coalesce(max(x.dispatch_generation),0)+1 INTO next_dispatch_generation
  FROM change_ledger.private_writer_dispatch_intents x WHERE x.change_id=rec.change_id;

 UPDATE change_ledger.claim_tokens SET state='CONSUMED' WHERE token_id=p_token_id AND state='ISSUED';
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 UPDATE change_ledger.records SET execution_state='APPLYING',updated_at=clock_timestamp()
  WHERE tenant_id=p_tenant AND company_id=p_company AND change_id=rec.change_id;
 -- Migration 027 removes the legacy row trigger, so this candidate entry point must bind
 -- the locked lifecycle epoch itself when creating the permit.
 INSERT INTO change_ledger.dispatch_permits(
  change_id,generation,state,call_id,writer_host,onec_session,lifecycle_epoch)
 VALUES(rec.change_id,tok.generation,'NOT_PERMITTED',p_call_id,p_writer_host,p_onec_session,lf.epoch)
 ON CONFLICT(change_id,generation) DO NOTHING;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=rec.change_id AND x.generation=tok.generation FOR UPDATE;
 IF NOT FOUND OR dp.call_id IS DISTINCT FROM p_call_id OR dp.writer_host IS DISTINCT FROM p_writer_host
   OR dp.onec_session IS DISTINCT FROM p_onec_session OR dp.lifecycle_epoch IS DISTINCT FROM lf.epoch
   OR dp.state<>'NOT_PERMITTED' THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.private_writer_dispatch_intents(
  dispatch_intent_id,tenant_id,company_id,organization_ref,base_fingerprint,change_id,
  claim_generation,dispatch_generation,call_id,operation_kind,approval_digest,payload_digest,
  target_ref,expected_pre_version,auth_epoch,repair_authorization_id)
 VALUES(intent_id,p_tenant,p_company,rec.organization_ref,rec.base_fingerprint,rec.change_id,
  tok.generation,next_dispatch_generation,p_call_id,operation_kind,approved_digest,rec.payload_digest,
  rec.target_ref,rec.target_version,lf.epoch,rec.repair_for);
 PERFORM change_ledger.append_event(p_tenant,p_company,rec.change_id,'APPLYING',jsonb_build_object(
   'call_id',p_call_id,'writer_host',p_writer_host,'onec_session',p_onec_session));
 RETURN tok;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_record_verified_success_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_dispatch_cas_id uuid,
 p_active_instance_id text,
 p_active_service_epoch bigint,
 p_receipt_ref text,
 p_outcome_ref text,
 p_completion_ref text
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.dispatch_attempts%ROWTYPE;
        b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        receipt change_ledger.private_writer_evidence%ROWTYPE;
        outcome change_ledger.private_writer_evidence%ROWTYPE;
        completion change_ledger.private_writer_evidence%ROWTYPE;
        keyrow record;
        permit_id uuid;
        repair_id uuid;
        prior text;
        completed text;
        verified text;
        completion_evidence jsonb;
        verification_evidence jsonb;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid OR p_active_instance_id IS NULL
   OR p_active_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_active_service_epoch IS NULL OR p_active_service_epoch<=0
   OR p_identity.call_id IS NULL OR p_identity.change_id IS NULL OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
   OR p_receipt_ref IS NULL OR p_receipt_ref='' OR p_receipt_ref<>btrim(p_receipt_ref)
   OR p_outcome_ref IS NULL OR p_outcome_ref='' OR p_outcome_ref<>btrim(p_outcome_ref)
   OR p_completion_ref IS NULL OR p_completion_ref='' OR p_completion_ref<>btrim(p_completion_ref) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 -- Discovery reads identify the lock plan only. Every authorization-bearing row is re-read
 -- under its fence below before any S12 or S13 state is changed.
 SELECT * INTO hint FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id
   AND x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 SELECT * INTO receipt FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 SELECT * INTO outcome FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_outcome_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 SELECT * INTO completion FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_completion_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 IF hint.dispatch_cas_id IS NULL OR receipt.evidence_ref IS NULL
   OR outcome.evidence_ref IS NULL OR completion.evidence_ref IS NULL THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;

 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
  END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
  IF NOT FOUND OR lf.state NOT IN ('READY','RECOVERING') THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 FOR keyrow IN
  SELECT DISTINCT k.key_id,k.key_version,k.public_key
   FROM change_ledger.private_writer_evidence e
   JOIN change_ledger.private_writer_signer_key_versions k
    ON k.key_id=e.signer_key_id AND k.key_version=e.signer_key_version
   WHERE e.evidence_ref IN (p_receipt_ref,p_outcome_ref,p_completion_ref)
    AND e.tenant_id=hint.tenant_id AND e.company_id=hint.company_id
   ORDER BY k.key_id,k.key_version
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(encode(keyrow.public_key,'hex'),17017));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(hint.change_id::text),
  'call-id:v1:'||lower(hint.call_id::text),
  'dispatch-cas-id:v1:'||lower(hint.dispatch_cas_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_receipt_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_outcome_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_completion_ref,'UTF8')),'hex')
 ]);
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 -- This row lock is the terminal authorization point. It remains held through both S12
 -- transitions and S13 slot release, so a takeover cannot race after epoch validation.
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR UPDATE;
 IF NOT FOUND OR serving.service_instance_id IS DISTINCT FROM p_active_instance_id
   OR serving.service_epoch IS DISTINCT FROM p_active_service_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 -- This routine only reconciles an already-entered, exact CAS-bound attempt. Startup readiness
 -- intentionally stays NULL while such attempts are inventoried; requiring readiness here would
 -- prevent the inventory from draining. New admission and COM entry remain readiness-gated.
 FOR keyrow IN
  SELECT DISTINCT k.key_id,k.key_version
   FROM change_ledger.private_writer_evidence e
   JOIN change_ledger.private_writer_signer_key_versions k
    ON k.key_id=e.signer_key_id AND k.key_version=e.signer_key_version
   WHERE e.evidence_ref IN (p_receipt_ref,p_outcome_ref,p_completion_ref)
    AND e.tenant_id=hint.tenant_id AND e.company_id=hint.company_id
   ORDER BY k.key_id,k.key_version
 LOOP
  IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions k
      WHERE k.key_id=keyrow.key_id AND k.key_version=keyrow.key_version
       AND k.valid_from<=clock_timestamp() AND k.valid_until>clock_timestamp())
    OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=keyrow.key_id AND r.key_version=keyrow.key_version) THEN
   RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
  END IF;
 END LOOP;
 SELECT * INTO receipt FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id
   AND x.company_id=hint.company_id FOR SHARE;
 SELECT * INTO outcome FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_outcome_ref AND x.tenant_id=hint.tenant_id
   AND x.company_id=hint.company_id FOR SHARE;
 SELECT * INTO completion FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_completion_ref AND x.tenant_id=hint.tenant_id
   AND x.company_id=hint.company_id FOR SHARE;
 -- Match begin_com_entry's S12 row order: record, permit, attempt, physical slot.
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id AND x.change_id=hint.change_id FOR UPDATE;
 IF NOT FOUND OR rec.claim_generation<>hint.claim_generation OR rec.base_fingerprint<>hint.base_fingerprint
   OR rec.execution_state NOT IN ('APPLYING','APPLIED') OR rec.dispatch_state<>'DISPATCHED' THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=hint.change_id AND x.generation=hint.claim_generation FOR UPDATE;
 IF NOT FOUND OR dp.state<>'DISPATCHED' OR dp.call_id IS DISTINCT FROM hint.call_id
   OR dp.writer_host IS DISTINCT FROM hint.writer_host_id
   OR dp.lifecycle_epoch IS DISTINCT FROM hint.auth_epoch
   OR dp.permit_digest IS DISTINCT FROM hint.permit_digest THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR ROW(a.tenant_id,a.company_id,a.organization_ref,a.base_fingerprint,a.change_id,
      a.claim_generation,a.call_id,a.operation_kind,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.payload_digest,a.permit_id::text,a.permit_digest,a.writer_host_id,a.repair_authorization_id)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
      p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
      p_identity.operation,p_identity.target_ref,p_identity.target_version,p_identity.epoch,
      p_identity.payload_digest,p_identity.permit_id,p_identity.permit_digest,p_identity.host_id,repair_id)
   OR ROW(receipt.dispatch_cas_id,receipt.dispatch_intent_id,receipt.change_id,receipt.call_id,
      receipt.tenant_id,receipt.company_id,receipt.organization_ref,receipt.base_fingerprint,
      receipt.operation_kind,receipt.approval_digest,receipt.payload_digest,receipt.permit_id,
      receipt.permit_digest,receipt.target_ref,receipt.pre_version,receipt.auth_epoch,
      receipt.repair_authorization_id)
    IS DISTINCT FROM ROW(a.dispatch_cas_id,a.dispatch_intent_id,a.change_id,a.call_id,a.tenant_id,
      a.company_id,a.organization_ref,a.base_fingerprint,a.operation_kind,a.approval_digest,
      a.payload_digest,a.permit_id,a.permit_digest,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.repair_authorization_id)
   OR ROW(outcome.dispatch_cas_id,outcome.dispatch_intent_id,outcome.change_id,outcome.call_id,
      outcome.tenant_id,outcome.company_id,outcome.organization_ref,outcome.base_fingerprint,
      outcome.operation_kind,outcome.approval_digest,outcome.payload_digest,outcome.permit_id,
      outcome.permit_digest,outcome.target_ref,outcome.pre_version,outcome.auth_epoch,
      outcome.repair_authorization_id)
    IS DISTINCT FROM ROW(a.dispatch_cas_id,a.dispatch_intent_id,a.change_id,a.call_id,a.tenant_id,
      a.company_id,a.organization_ref,a.base_fingerprint,a.operation_kind,a.approval_digest,
      a.payload_digest,a.permit_id,a.permit_digest,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.repair_authorization_id)
   OR ROW(completion.dispatch_cas_id,completion.dispatch_intent_id,completion.change_id,
      completion.call_id,completion.tenant_id,completion.company_id,completion.organization_ref,
      completion.base_fingerprint,completion.operation_kind,completion.approval_digest,
      completion.payload_digest,completion.permit_id,completion.permit_digest,
      completion.target_ref,completion.pre_version,completion.auth_epoch,
      completion.repair_authorization_id)
    IS DISTINCT FROM ROW(a.dispatch_cas_id,a.dispatch_intent_id,a.change_id,a.call_id,a.tenant_id,
      a.company_id,a.organization_ref,a.base_fingerprint,a.operation_kind,a.approval_digest,
      a.payload_digest,a.permit_id,a.permit_digest,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.repair_authorization_id)
   OR receipt.record_type<>'DISPATCH_RECEIPT_V1' OR receipt.signer_role<>'writer_receipt'
   OR receipt.writer_result_class<>'CALL_RETURNED_SUCCESS'
   OR receipt.writer_invocation_stage NOT IN ('ENTERED','INVOKED') OR receipt.writer_call_returned IS NOT TRUE
   OR receipt.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
   OR receipt.session_instance_id IS DISTINCT FROM a.onec_session_instance_id
   OR outcome.record_type NOT IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3')
   OR outcome.signer_role<>'verification_worker'
   OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
   OR outcome.outcome_observed_version IS DISTINCT FROM receipt.writer_returned_version
   OR outcome.outcome_observation_complete IS NOT TRUE OR outcome.outcome_fields_match IS NOT TRUE
   OR outcome.outcome_movements_match IS NOT TRUE OR outcome.outcome_reader_health<>'HEALTHY'
   OR outcome.outcome_effect_presence<>'PRESENT' OR outcome.outcome_effect_identity<>'MATCH'
   OR outcome.outcome_attribution_result<>'PROVEN'
   OR outcome.outcome_expected_effect_digest IS DISTINCT FROM outcome.outcome_observed_effect_digest
   OR outcome.outcome_uncertainty_count<>0
   OR outcome.outcome_completion_proof_class IS DISTINCT FROM completion.completion_proof_class
   OR (outcome.record_type='OUTCOME_EVIDENCE_V3'
       AND outcome.outcome_completion_proof_digest IS DISTINCT FROM completion.record_digest)
   OR completion.record_type<>'COMPLETION_PROOF_V1'
   OR completion.completion_proof_class<>'WRITER_CALL_RETURNED'
   OR completion.signer_role<>'writer_receipt'
   OR completion.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
   OR (a.operation_kind='CREATE_DRAFT' AND
       (receipt.target_ref IS NOT NULL OR receipt.pre_version IS NOT NULL
        OR outcome.outcome_pre_version IS NOT NULL))
   OR (a.operation_kind IN ('POST','UNPOST') AND
       (receipt.target_ref IS DISTINCT FROM a.expected_target_ref
        OR receipt.pre_version IS DISTINCT FROM a.expected_pre_version
        OR outcome.outcome_pre_version IS DISTINCT FROM a.expected_pre_version
        OR outcome.outcome_target_ref IS DISTINCT FROM a.expected_target_ref
        OR outcome.outcome_observed_version IS NOT DISTINCT FROM a.expected_pre_version
        OR outcome.outcome_version_relation<>'ADVANCED')) THEN
  RAISE EXCEPTION 'TERMINAL_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=a.base_fingerprint FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='OUTCOME';
 IF FOUND AND prior<>p_outcome_ref THEN RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='COMPLETION';
 IF FOUND AND prior<>p_completion_ref THEN RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 IF a.state='TERMINAL_WITH_EVIDENCE' THEN
  IF rec.execution_state<>'APPLIED' OR rec.verification_state<>'VERIFIED'
    OR slot.active_dispatch_cas_id IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
       WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_ref=p_receipt_ref
        AND x.evidence_purpose='WRITER_RECEIPT')
    OR NOT EXISTS(SELECT 1 FROM change_ledger.events x
       WHERE x.tenant_id=a.tenant_id AND x.company_id=a.company_id AND x.change_id=a.change_id
        AND x.event_type='COMPLETE_SUCCESS'
        AND x.payload->'private_writer'->>'receipt_ref'=p_receipt_ref
        AND x.payload->'private_writer'->>'outcome_ref'=p_outcome_ref
        AND x.payload->'private_writer'->>'completion_ref'=p_completion_ref)
    OR NOT EXISTS(SELECT 1 FROM change_ledger.events x
       WHERE x.tenant_id=a.tenant_id AND x.company_id=a.company_id AND x.change_id=a.change_id
        AND x.event_type='VERIFY_VERIFIED'
        AND x.payload->'private_writer'->>'outcome_ref'=p_outcome_ref
        AND x.payload->'private_writer'->>'completion_ref'=p_completion_ref) THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN p_outcome_ref;
 END IF;
 IF a.state<>'POSSIBLY_EXECUTING' OR a.com_entry_authorized_at IS NULL
   OR slot.active_dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF rec.execution_state<>'APPLYING' OR rec.verification_state<>'NOT_VERIFIED' THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001';
 END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='WRITER_RECEIPT';
 IF FOUND AND prior<>p_receipt_ref THEN RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_receipt_ref,'WRITER_RECEIPT')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_outcome_ref,'OUTCOME')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_completion_ref,'COMPLETION')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_ref=p_receipt_ref
       AND x.evidence_purpose='WRITER_RECEIPT')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_ref=p_outcome_ref
       AND x.evidence_purpose='OUTCOME')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_ref=p_completion_ref
       AND x.evidence_purpose='COMPLETION') THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN
  -- A barrier may close admission while an already admitted call finishes, but it may not
  -- be crossed if this call was not included in the immutable quiescence snapshot.
  IF NOT EXISTS(SELECT 1 FROM change_ledger.writer_barrier_calls x
      JOIN change_ledger.writer_barriers w USING(barrier_id)
      WHERE w.barrier_id=slot.open_barrier_id AND x.dispatch_cas_id=a.dispatch_cas_id) THEN
   RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001';
  END IF;
 END IF;
 completion_evidence:=jsonb_build_object('private_writer',jsonb_build_object(
  'receipt_ref',p_receipt_ref,'receipt_digest',receipt.record_digest,
  'outcome_ref',p_outcome_ref,'outcome_digest',outcome.record_digest,
  'completion_ref',p_completion_ref,'completion_digest',completion.record_digest));
 completed:=change_ledger.complete(a.tenant_id,a.company_id,a.change_id,a.claim_generation,
  'SUCCESS',completion_evidence,NULL);
 IF completed<>'APPLIED' THEN RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001'; END IF;
 verification_evidence:=jsonb_build_object('private_writer',jsonb_build_object(
  'outcome_ref',p_outcome_ref,'outcome_digest',outcome.record_digest,
  'completion_ref',p_completion_ref,'completion_digest',completion.record_digest,
  'observed_version',outcome.outcome_observed_version,
  'observed_target_ref',outcome.outcome_target_ref));
 verified:=change_ledger.verify(a.tenant_id,a.company_id,a.change_id,verification_evidence,true);
 IF verified<>'VERIFIED' THEN RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.dispatch_attempts SET state='TERMINAL_WITH_EVIDENCE'
  WHERE dispatch_cas_id=a.dispatch_cas_id AND state='POSSIBLY_EXECUTING';
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.physical_base_slots SET active_dispatch_cas_id=NULL
  WHERE base_fingerprint=a.base_fingerprint AND active_dispatch_cas_id=a.dispatch_cas_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 RETURN p_outcome_ref;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_record_recovered_not_invoked_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_dispatch_cas_id uuid,
 p_active_instance_id text,
 p_active_service_epoch bigint,
 p_receipt_ref text
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.dispatch_attempts%ROWTYPE;
        b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        rec_hint change_ledger.records%ROWTYPE;
        parent_hint change_ledger.records%ROWTYPE;
        repair_parent change_ledger.records%ROWTYPE;
        rowrec change_ledger.records%ROWTYPE;
        target_lock_hint change_ledger.target_locks%ROWTYPE;
        target_lock change_ledger.target_locks%ROWTYPE;
        record_ids uuid[]; v_target_ref text; target_lock_found boolean;
        slot change_ledger.physical_base_slots%ROWTYPE;
        receipt change_ledger.private_writer_evidence%ROWTYPE;
        keyrow change_ledger.private_writer_signer_key_versions%ROWTYPE;
        permit_id uuid;
        repair_id uuid;
        prior text;
        terminal_state text;
        no_effect_proof jsonb;
        completion_evidence jsonb;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid OR p_active_instance_id IS NULL
   OR p_active_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_active_service_epoch IS NULL OR p_active_service_epoch<=0
   OR p_receipt_ref IS NULL OR p_receipt_ref='' OR p_receipt_ref<>btrim(p_receipt_ref)
   OR p_identity.call_id IS NULL OR p_identity.change_id IS NULL OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 SELECT * INTO hint FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id
   AND x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 SELECT * INTO receipt FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 IF hint.dispatch_cas_id IS NULL OR receipt.evidence_ref IS NULL THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 -- Freeze the record/repair-parent and exact target-lock identity before acquiring row locks.
 SELECT * INTO rec_hint FROM change_ledger.records x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id AND x.change_id=hint.change_id;
 IF NOT FOUND OR rec_hint.base_fingerprint IS DISTINCT FROM hint.base_fingerprint THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 record_ids:=ARRAY[rec_hint.change_id];
 IF rec_hint.repair_for IS NOT NULL THEN
  SELECT * INTO parent_hint FROM change_ledger.records x
   WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id
    AND x.change_id=rec_hint.repair_for;
  IF NOT FOUND OR parent_hint.base_fingerprint IS DISTINCT FROM rec_hint.base_fingerprint THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  record_ids:=pg_catalog.array_append(record_ids,rec_hint.repair_for);
 END IF;
 v_target_ref:=coalesce(rec_hint.target_ref,rec_hint.change_id::text);
 SELECT * INTO target_lock_hint FROM change_ledger.target_locks x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id
   AND x.base_fingerprint=rec_hint.base_fingerprint AND x.target_ref=v_target_ref;
 target_lock_found:=FOUND;
 SELECT * INTO keyrow FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=receipt.signer_key_id AND x.key_version=receipt.signer_key_version;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(keyrow.public_key,'hex'),17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(hint.change_id::text),
  'record-change-id:v1:'||lower(coalesce(rec_hint.repair_for,hint.change_id)::text),
  'call-id:v1:'||lower(hint.call_id::text),
  'dispatch-cas-id:v1:'||lower(hint.dispatch_cas_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_receipt_ref,'UTF8')),'hex')
 ]);
 -- Namespace 4 serializes the exact target resource before any row lock. The later locked
 -- snapshot is compared with the pre-fence plan and must still be owned by this change.
 PERFORM pg_catalog.pg_advisory_xact_lock(4,pg_catalog.hashtext(
  'target-lock:v1:'||hint.tenant_id||':'||hint.company_id||':'||rec_hint.base_fingerprint||':'||v_target_ref));
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
 IF NOT FOUND OR lf.state NOT IN ('READY','RECOVERING') THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 -- Preserve the root's distinct READ COMMITTED lifecycle reread after lock acquisition.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 IF NOT FOUND OR lf.state NOT IN ('READY','RECOVERING') THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR UPDATE;
 IF NOT FOUND OR serving.service_instance_id IS DISTINCT FROM p_active_instance_id
    OR serving.service_epoch IS DISTINCT FROM p_active_service_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO keyrow FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=receipt.signer_key_id AND x.key_version=receipt.signer_key_version FOR SHARE;
 IF NOT FOUND OR keyrow.valid_from>clock_timestamp() OR keyrow.valid_until<=clock_timestamp()
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=keyrow.key_id AND r.key_version=keyrow.key_version) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO receipt FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id
   AND x.company_id=hint.company_id FOR SHARE;
 -- Match begin_com_entry's S12 row order: record, permit, attempt, physical slot.
 -- Lock the current record and repair parent in canonical change_id order before the
 -- referencing target_locks row; then verify that both still match the frozen plan.
 FOR rowrec IN SELECT x.* FROM change_ledger.records x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id AND x.change_id=ANY(record_ids)
  ORDER BY x.change_id FOR UPDATE
 LOOP
  IF rowrec.change_id=rec_hint.change_id THEN rec:=rowrec;
  ELSIF rowrec.change_id=rec_hint.repair_for THEN repair_parent:=rowrec;
  END IF;
 END LOOP;
 IF rec.change_id IS NULL OR pg_catalog.to_jsonb(rec) IS DISTINCT FROM pg_catalog.to_jsonb(rec_hint)
   OR (rec.repair_for IS NOT NULL AND
       pg_catalog.to_jsonb(repair_parent) IS DISTINCT FROM pg_catalog.to_jsonb(parent_hint)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF rec.claim_generation<>hint.claim_generation OR rec.base_fingerprint<>hint.base_fingerprint
   OR rec.execution_state NOT IN ('APPLYING','FAILED_APPLY')
   OR rec.dispatch_state<>'DISPATCHED' THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=hint.change_id AND x.generation=hint.claim_generation FOR UPDATE;
 IF NOT FOUND OR dp.state<>'DISPATCHED' OR dp.call_id IS DISTINCT FROM hint.call_id
   OR dp.writer_host IS DISTINCT FROM hint.writer_host_id
   OR dp.lifecycle_epoch IS DISTINCT FROM hint.auth_epoch
   OR dp.permit_digest IS DISTINCT FROM hint.permit_digest THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR ROW(a.tenant_id,a.company_id,a.organization_ref,a.base_fingerprint,a.change_id,
      a.claim_generation,a.call_id,a.operation_kind,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.payload_digest,a.permit_id::text,a.permit_digest,a.writer_host_id,a.repair_authorization_id)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
      p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
      p_identity.operation,p_identity.target_ref,p_identity.target_version,p_identity.epoch,
      p_identity.payload_digest,p_identity.permit_id,p_identity.permit_digest,p_identity.host_id,repair_id)
   OR ROW(receipt.dispatch_cas_id,receipt.dispatch_intent_id,receipt.change_id,receipt.call_id,
      receipt.tenant_id,receipt.company_id,receipt.organization_ref,receipt.base_fingerprint,
      receipt.operation_kind,receipt.approval_digest,receipt.payload_digest,receipt.permit_id,
      receipt.permit_digest,receipt.target_ref,receipt.pre_version,receipt.auth_epoch,
      receipt.repair_authorization_id)
    IS DISTINCT FROM ROW(a.dispatch_cas_id,a.dispatch_intent_id,a.change_id,a.call_id,a.tenant_id,
      a.company_id,a.organization_ref,a.base_fingerprint,a.operation_kind,a.approval_digest,
      a.payload_digest,a.permit_id,a.permit_digest,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.repair_authorization_id)
   OR receipt.record_type<>'DISPATCH_NO_ENTRY_RECEIPT_V1' OR receipt.signer_role<>'writer_receipt'
   OR receipt.writer_invocation_stage<>'NOT_INVOKED'
   OR receipt.writer_result_class<>'PRE_WRITE_NO_EFFECT' OR receipt.writer_call_returned IS NOT FALSE
   OR receipt.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
   OR receipt.session_instance_id IS DISTINCT FROM a.onec_session_instance_id
   OR receipt.no_effect_evidence_digest IS NULL
   OR receipt.no_effect_evidence_digest !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=a.base_fingerprint FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='NO_ENTRY_PROOF';
 IF a.state='TERMINAL_WITH_EVIDENCE' THEN
  IF prior IS DISTINCT FROM p_receipt_ref OR rec.execution_state<>'FAILED_APPLY'
    OR slot.active_dispatch_cas_id IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM change_ledger.events x
       WHERE x.tenant_id=a.tenant_id AND x.company_id=a.company_id AND x.change_id=a.change_id
        AND x.event_type='COMPLETE_PRE_WRITE_REFUSAL'
        AND x.payload->'private_writer'->>'no_entry_receipt_ref'=p_receipt_ref) THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN p_receipt_ref;
 END IF;
 IF a.state NOT IN ('ACCEPTED_NOT_INVOKED','POSSIBLY_EXECUTING')
   OR a.com_entry_authorized_at IS NOT NULL
   OR slot.active_dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id
   OR rec.execution_state<>'APPLYING' OR prior IS NOT NULL
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=a.dispatch_cas_id
       AND x.evidence_purpose IN ('WRITER_RECEIPT','OUTCOME','COMPLETION')) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 -- A first terminalization needs the live target lock to remain owned by this change.
 -- Exact terminal replay returned above: completion may have released or handed this lock back.
 SELECT * INTO target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=rec.tenant_id AND x.company_id=rec.company_id
   AND x.base_fingerprint=rec.base_fingerprint AND x.target_ref=v_target_ref FOR UPDATE;
 IF NOT target_lock_found OR NOT FOUND
   OR pg_catalog.to_jsonb(target_lock) IS DISTINCT FROM pg_catalog.to_jsonb(target_lock_hint)
   OR target_lock.owner_change_id IS DISTINCT FROM rec.change_id
   OR (SELECT count(*) FROM change_ledger.target_locks x WHERE x.owner_change_id=rec.change_id)<>1 THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 -- The locked target row and both record snapshots are frozen before terminal DML.
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_receipt_ref,'NO_ENTRY_PROOF');
 no_effect_proof:=jsonb_build_object('receipt_ref',p_receipt_ref,
  'receipt_digest',receipt.record_digest,
  'no_effect_evidence_digest',receipt.no_effect_evidence_digest);
 completion_evidence:=jsonb_build_object('private_writer',jsonb_build_object(
  'no_entry_receipt_ref',p_receipt_ref,'no_entry_receipt_digest',receipt.record_digest,
  'no_effect_proof',no_effect_proof));
 terminal_state:=change_ledger.complete(a.tenant_id,a.company_id,a.change_id,a.claim_generation,
  'PRE_WRITE_REFUSAL',completion_evidence,no_effect_proof);
 IF terminal_state<>'FAILED_APPLY' THEN RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.dispatch_attempts SET state='TERMINAL_WITH_EVIDENCE'
  WHERE dispatch_cas_id=a.dispatch_cas_id AND state IN ('ACCEPTED_NOT_INVOKED','POSSIBLY_EXECUTING')
    AND com_entry_authorized_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.physical_base_slots SET active_dispatch_cas_id=NULL
  WHERE base_fingerprint=a.base_fingerprint AND active_dispatch_cas_id=a.dispatch_cas_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 RETURN p_receipt_ref;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_record_recovered_terminal_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_dispatch_cas_id uuid,
 p_active_instance_id text,
 p_active_service_epoch bigint,
 p_outcome_ref text,
 p_completion_ref text,
 p_challenge_ref text,
 p_read_attestation_ref text,
 p_resolution_event_id uuid
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.dispatch_attempts%ROWTYPE;
        b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        dp change_ledger.dispatch_permits%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        receipt change_ledger.private_writer_evidence%ROWTYPE;
        outcome change_ledger.private_writer_evidence%ROWTYPE;
        completion change_ledger.private_writer_evidence%ROWTYPE;
        challenge change_ledger.private_writer_evidence%ROWTYPE;
        attestation change_ledger.private_writer_evidence%ROWTYPE;
        cs change_ledger.witness_cosigns%ROWTYPE;
        resolution change_ledger.events%ROWTYPE;
        keyrow record;
        permit_id uuid;
        repair_id uuid;
        prior text;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid OR p_active_instance_id IS NULL
   OR p_active_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_active_service_epoch IS NULL OR p_active_service_epoch<=0
   OR p_resolution_event_id IS NULL
   OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
   OR p_outcome_ref IS NULL OR p_outcome_ref='' OR p_outcome_ref<>btrim(p_outcome_ref)
   OR p_completion_ref IS NULL OR p_completion_ref='' OR p_completion_ref<>btrim(p_completion_ref)
   OR p_challenge_ref IS NULL OR p_challenge_ref='' OR p_challenge_ref<>btrim(p_challenge_ref)
   OR p_read_attestation_ref IS NULL OR p_read_attestation_ref=''
   OR p_read_attestation_ref<>btrim(p_read_attestation_ref) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 SELECT * INTO hint FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id
   AND x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT v.* INTO receipt FROM change_ledger.private_writer_attempt_evidence ae
  JOIN change_ledger.private_writer_evidence v USING(evidence_ref)
  WHERE ae.dispatch_cas_id=p_dispatch_cas_id AND ae.evidence_purpose='WRITER_RECEIPT'
   AND v.tenant_id=hint.tenant_id AND v.company_id=hint.company_id;
 SELECT * INTO outcome FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_outcome_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 SELECT * INTO completion FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_completion_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 SELECT * INTO challenge FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_challenge_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 SELECT * INTO attestation FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_read_attestation_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 IF receipt.evidence_ref IS NULL OR outcome.evidence_ref IS NULL OR completion.evidence_ref IS NULL
   OR challenge.evidence_ref IS NULL OR attestation.evidence_ref IS NULL THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;

 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
  END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
  IF NOT FOUND OR lf.state NOT IN ('READY','RECOVERING') THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 -- Serialize every evidence-key revocation by the same public-key material fence used by
 -- the registration path, then re-read validity and revocation after all fences are held.
 FOR keyrow IN
  SELECT DISTINCT k.key_id,k.key_version,k.public_key
   FROM change_ledger.private_writer_evidence e
   JOIN change_ledger.private_writer_signer_key_versions k
    ON k.key_id=e.signer_key_id AND k.key_version=e.signer_key_version
   WHERE e.evidence_ref IN (receipt.evidence_ref,outcome.evidence_ref,completion.evidence_ref,
       challenge.evidence_ref,attestation.evidence_ref)
    AND e.tenant_id=hint.tenant_id AND e.company_id=hint.company_id
   ORDER BY k.key_id,k.key_version
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(encode(keyrow.public_key,'hex'),17017));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(hint.change_id::text),
  'call-id:v1:'||lower(hint.call_id::text),
  'dispatch-cas-id:v1:'||lower(hint.dispatch_cas_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_outcome_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_completion_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_challenge_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_read_attestation_ref,'UTF8')),'hex')
 ]);
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR UPDATE;
 IF NOT FOUND OR serving.service_instance_id<>p_active_instance_id
   OR serving.service_epoch<>p_active_service_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 FOR keyrow IN
  SELECT DISTINCT k.key_id,k.key_version
   FROM change_ledger.private_writer_evidence e
   JOIN change_ledger.private_writer_signer_key_versions k
    ON k.key_id=e.signer_key_id AND k.key_version=e.signer_key_version
   WHERE e.evidence_ref IN (receipt.evidence_ref,outcome.evidence_ref,completion.evidence_ref,
       challenge.evidence_ref,attestation.evidence_ref)
    AND e.tenant_id=hint.tenant_id AND e.company_id=hint.company_id
   ORDER BY k.key_id,k.key_version
 LOOP
  IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions k
      WHERE k.key_id=keyrow.key_id AND k.key_version=keyrow.key_version
       AND k.valid_from<=clock_timestamp() AND k.valid_until>clock_timestamp())
    OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=keyrow.key_id AND r.key_version=keyrow.key_version) THEN
   RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
  END IF;
 END LOOP;
 -- Use the same S12 record/permit-before-attempt order as admission and COM-entry fencing.
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id AND x.change_id=hint.change_id FOR UPDATE;
 IF NOT FOUND OR rec.claim_generation<>hint.claim_generation OR rec.base_fingerprint<>hint.base_fingerprint
   OR rec.execution_state<>'FAILED_APPLY' OR rec.call_ownership<>'PROVEN_FINISHED'
   OR rec.reservation_state<>'RELEASED' THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=hint.change_id AND x.generation=hint.claim_generation FOR UPDATE;
 IF NOT FOUND OR dp.state<>'DISPATCHED' OR dp.call_id IS DISTINCT FROM hint.call_id
   OR dp.writer_host IS DISTINCT FROM hint.writer_host_id
   OR dp.lifecycle_epoch IS DISTINCT FROM hint.auth_epoch
   OR dp.permit_digest IS DISTINCT FROM hint.permit_digest THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR ROW(a.tenant_id,a.company_id,a.organization_ref,a.base_fingerprint,a.change_id,
      a.claim_generation,a.call_id,a.operation_kind,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.payload_digest,a.permit_id::text,a.permit_digest,a.writer_host_id,a.repair_authorization_id)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
      p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
      p_identity.operation,p_identity.target_ref,p_identity.target_version,p_identity.epoch,
      p_identity.payload_digest,p_identity.permit_id,p_identity.permit_digest,p_identity.host_id,repair_id)
   OR a.state NOT IN ('POSSIBLY_EXECUTING','TERMINAL_WITH_EVIDENCE') THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO resolution FROM change_ledger.events x
  WHERE x.tenant_id=a.tenant_id AND x.company_id=a.company_id AND x.event_id=p_resolution_event_id
   AND x.change_id=a.change_id AND x.event_type='OPERATOR_RESOLVE' FOR SHARE;
 IF NOT FOUND
   OR resolution.payload->>'execution' IS DISTINCT FROM 'FAILED_APPLY'
   OR resolution.payload->>'checkpoint_required' IS DISTINCT FROM 'true'
   OR resolution.payload->>'dispatch_cas_id' IS DISTINCT FROM a.dispatch_cas_id::text
   OR resolution.payload->>'receipt_ref' IS DISTINCT FROM receipt.evidence_ref
   OR resolution.payload->>'completion_ref' IS DISTINCT FROM completion.evidence_ref
   OR resolution.payload->>'outcome_ref' IS DISTINCT FROM outcome.evidence_ref
   OR resolution.payload->>'challenge_ref' IS DISTINCT FROM challenge.evidence_ref
   OR resolution.payload->>'read_attestation_ref' IS DISTINCT FROM attestation.evidence_ref
   OR resolution.payload->>'present' IS DISTINCT FROM 'false'
   OR resolution.payload->>'observation_evidence' IS DISTINCT FROM outcome.outcome_attribution_evidence_ref
   OR (resolution.payload->>'cosign_id') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR NOT EXISTS(SELECT 1 FROM change_ledger.checkpoints k
      WHERE k.tenant_id=a.tenant_id AND k.company_id=a.company_id
       AND k.ledger_seq=resolution.seq AND k.head_hash=resolution.hash
       AND k.sink_kind='REAL' AND k.read_back_confirmed AND k.verified) THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=(resolution.payload->>'cosign_id')::uuid AND w.change_id=a.change_id
   AND w.consumed_at IS NOT NULL FOR SHARE;
 IF NOT FOUND OR cs.completion_proof->>'evidence_id' IS DISTINCT FROM completion.completion_proof_id::text THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=a.base_fingerprint FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF receipt.record_type<>'DISPATCH_RECEIPT_V1'
   OR receipt.writer_result_class<>'CONDITIONAL_VERSION_CONFLICT'
   OR receipt.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
   OR outcome.record_type<>'OUTCOME_EVIDENCE_V3' OR outcome.dispatch_cas_id<>a.dispatch_cas_id
   OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
   OR outcome.outcome_pre_version IS DISTINCT FROM a.expected_pre_version
   OR outcome.outcome_observation_complete IS NOT TRUE
   OR outcome.outcome_effect_presence<>'ABSENT'
   OR outcome.outcome_effect_identity<>'NO_GOVERNED_EFFECT'
   OR outcome.outcome_attribution_result<>'COMPETING_WRITER'
   OR outcome.outcome_version_relation<>'DIFFERENT_COMPETING_WRITER'
   OR outcome.outcome_observed_version=a.expected_pre_version
   OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
   OR outcome.outcome_uncertainty_count<>0
   OR outcome.outcome_completion_proof_digest IS DISTINCT FROM completion.record_digest
   OR completion.record_type<>'COMPLETION_PROOF_V1'
   OR challenge.record_type<>'POST_COMPLETION_CHALLENGE_V1'
   OR attestation.record_type<>'POST_COMPLETION_READ_ATTESTATION_V1'
   OR outcome.outcome_challenge_id IS DISTINCT FROM challenge.challenge_id
   OR outcome.outcome_verification_sequence IS DISTINCT FROM attestation.read_attestation_sequence
   OR outcome.outcome_verification_sequence<=challenge.challenge_sequence_floor
   OR outcome.outcome_observation_digest IS DISTINCT FROM attestation.read_attestation_outcome_digest
   OR outcome.outcome_read_attestation_digest IS DISTINCT FROM attestation.record_digest
   OR resolution.payload->>'attributed' IS DISTINCT FROM 'false' THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 IF a.state='TERMINAL_WITH_EVIDENCE' THEN
  IF slot.active_dispatch_cas_id IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM change_ledger.events ev
       WHERE ev.tenant_id=a.tenant_id AND ev.company_id=a.company_id
        AND ev.change_id=a.change_id AND ev.event_type='PRIVATE_WRITER_RECOVERY_FINALIZED'
        AND ev.payload->>'dispatch_cas_id'=a.dispatch_cas_id::text
        AND ev.payload->>'resolution_event_id'=resolution.event_id::text
        AND ev.payload->>'cosign_id'=cs.cosign_id::text
        AND ev.payload->>'receipt_ref'=receipt.evidence_ref
        AND ev.payload->>'outcome_ref'=outcome.evidence_ref
        AND ev.payload->>'completion_ref'=completion.evidence_ref
        AND ev.payload->>'challenge_ref'=challenge.evidence_ref
        AND ev.payload->>'read_attestation_ref'=attestation.evidence_ref)
    OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=outcome.evidence_ref
        AND ae.evidence_purpose='OUTCOME')
    OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=completion.evidence_ref
        AND ae.evidence_purpose='COMPLETION')
    OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=challenge.evidence_ref
        AND ae.evidence_purpose='POST_COMPLETION_CHALLENGE')
    OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=attestation.evidence_ref
        AND ae.evidence_purpose='READ_ATTESTATION') THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN outcome.evidence_ref;
 END IF;
 IF slot.active_dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='OUTCOME';
 IF FOUND AND prior<>p_outcome_ref THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='COMPLETION';
 IF FOUND AND prior<>p_completion_ref THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='POST_COMPLETION_CHALLENGE';
 IF FOUND AND prior<>p_challenge_ref THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='READ_ATTESTATION';
 IF FOUND AND prior<>p_read_attestation_ref THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_outcome_ref,'OUTCOME')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_completion_ref,'COMPLETION')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_challenge_ref,'POST_COMPLETION_CHALLENGE')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_read_attestation_ref,'READ_ATTESTATION')
 ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=outcome.evidence_ref
       AND ae.evidence_purpose='OUTCOME')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=completion.evidence_ref
       AND ae.evidence_purpose='COMPLETION')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=challenge.evidence_ref
       AND ae.evidence_purpose='POST_COMPLETION_CHALLENGE')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=a.dispatch_cas_id AND ae.evidence_ref=attestation.evidence_ref
       AND ae.evidence_purpose='READ_ATTESTATION') THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 UPDATE change_ledger.dispatch_attempts SET state='TERMINAL_WITH_EVIDENCE'
  WHERE dispatch_cas_id=a.dispatch_cas_id AND state='POSSIBLY_EXECUTING';
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.physical_base_slots SET active_dispatch_cas_id=NULL
  WHERE base_fingerprint=a.base_fingerprint AND active_dispatch_cas_id=a.dispatch_cas_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM change_ledger.append_event(a.tenant_id,a.company_id,a.change_id,
  'PRIVATE_WRITER_RECOVERY_FINALIZED',jsonb_build_object(
   'dispatch_cas_id',a.dispatch_cas_id,'resolution_event_id',resolution.event_id,
   'cosign_id',cs.cosign_id,'receipt_ref',receipt.evidence_ref,
   'outcome_ref',outcome.evidence_ref,'completion_ref',completion.evidence_ref,
   'challenge_ref',challenge.evidence_ref,'read_attestation_ref',attestation.evidence_ref));
 RETURN outcome.evidence_ref;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_close_and_advance_v1(
 p_base text,p_scope change_ledger.private_writer_scope_v1,p_expected_epoch bigint,
 p_barrier_id uuid,p_instance_id text,p_service_epoch bigint
) RETURNS change_ledger.private_writer_barrier_snapshot_v1
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        prior change_ledger.writer_barriers%ROWTYPE;
        planned_calls uuid[]; frozen_calls uuid[]; n bigint;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_base IS NULL OR p_base='' OR p_base<>btrim(p_base)
   OR p_scope IS NULL OR p_scope.tenant_id IS NULL OR p_scope.tenant_id=''
   OR p_scope.company_id IS NULL OR p_scope.company_id=''
   OR p_expected_epoch IS NULL OR p_expected_epoch<0 OR p_barrier_id IS NULL
   OR p_barrier_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_instance_id IS NULL OR p_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_service_epoch IS NULL OR p_service_epoch<=0 THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_base
   AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 PERFORM change_ledger.private_writer_take_base_fence_v1(p_base);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(p_scope.tenant_id,p_scope.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=p_scope.tenant_id AND x.company_id=p_scope.company_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001'; END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=p_scope.tenant_id AND x.company_id=p_scope.company_id;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=p_base
   AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;

 SELECT * INTO prior FROM change_ledger.writer_barriers x WHERE x.barrier_id=p_barrier_id;
 IF FOUND THEN
  IF ROW(prior.base_fingerprint,prior.tenant_id,prior.company_id)
    IS DISTINCT FROM ROW(p_base,p_scope.tenant_id,p_scope.company_id) THEN
   RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
  END IF;
 -- Namespace 8 freezes same-base admission and terminal transitions while this complete global-ID
 -- plan is observed. Freeze the barrier and all extant call IDs together in namespace 6 so the
 -- helper acquires the single deduplicated set in its canonical signed-tuple order.
 SELECT count(*) INTO n FROM change_ledger.dispatch_attempts x
  WHERE x.base_fingerprint=p_base AND x.state<>'TERMINAL_WITH_EVIDENCE';
 IF n>200 THEN
  RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(array_agg(x.call_id ORDER BY x.call_id),ARRAY[]::uuid[])
  INTO planned_calls FROM change_ledger.dispatch_attempts x
  WHERE x.base_fingerprint=p_base AND x.state<>'TERMINAL_WITH_EVIDENCE';
 PERFORM change_ledger.private_writer_take_global_fences_v1(
  ARRAY['barrier-id:v1:'||lower(p_barrier_id::text)] || ARRAY(
  SELECT 'call-id:v1:'||lower(u.call_id::text)
  FROM unnest(planned_calls) AS u(call_id)
 ));
  SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
   WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
    AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR UPDATE;
  IF NOT FOUND OR serving.service_instance_id<>p_instance_id
    OR serving.service_epoch<>p_service_epoch THEN
   RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
  END IF;
  RETURN change_ledger.private_writer_lookup_barrier_v1(p_barrier_id);
 END IF;

 IF lf.state<>'READY' OR lf.epoch<>p_expected_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR UPDATE;
 IF NOT FOUND OR serving.service_instance_id<>p_instance_id
   OR serving.service_epoch<>p_service_epoch OR serving.readiness_ref IS NULL THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=p_base;
 IF NOT FOUND OR slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN
  RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(array_agg(x.call_id ORDER BY x.call_id),ARRAY[]::uuid[])
  INTO frozen_calls FROM change_ledger.dispatch_attempts x
  WHERE x.base_fingerprint=p_base AND x.state<>'TERMINAL_WITH_EVIDENCE';
 IF frozen_calls IS DISTINCT FROM planned_calls THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM 1 FROM change_ledger.dispatch_attempts x
  WHERE x.base_fingerprint=p_base AND x.state<>'TERMINAL_WITH_EVIDENCE'
  ORDER BY x.call_id FOR SHARE;
 INSERT INTO change_ledger.writer_barriers(
  barrier_id,base_fingerprint,tenant_id,company_id,expected_current_epoch,epoch,
  barrier_origin_instance_id,barrier_origin_service_epoch,progress)
 VALUES(p_barrier_id,p_base,p_scope.tenant_id,p_scope.company_id,p_expected_epoch,
  p_expected_epoch+1,p_instance_id,p_service_epoch,'CLOSED_WITH_HOLD');
 INSERT INTO change_ledger.writer_barrier_calls(
  barrier_id,base_fingerprint,snapshot_ordinal,call_id,dispatch_cas_id)
 SELECT p_barrier_id,p_base,(row_number() OVER(ORDER BY x.call_id)-1)::bigint,
        x.call_id,x.dispatch_cas_id
  FROM change_ledger.dispatch_attempts x
  WHERE x.base_fingerprint=p_base AND x.state<>'TERMINAL_WITH_EVIDENCE'
  ORDER BY x.call_id;
 GET DIAGNOSTICS n=ROW_COUNT;
 IF n<>cardinality(planned_calls) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 UPDATE change_ledger.lifecycle_fences SET state='RECOVERING',epoch=p_expected_epoch+1,
  reason='QUIESCENCE_BARRIER_OPEN',updated_at=clock_timestamp()
  WHERE tenant_id=p_scope.tenant_id AND company_id=p_scope.company_id
   AND state='READY' AND epoch=p_expected_epoch;
 IF NOT FOUND THEN RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.physical_base_slots SET admission_closed=true,open_barrier_id=p_barrier_id
  WHERE base_fingerprint=p_base AND NOT admission_closed AND open_barrier_id IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001'; END IF;
 RETURN change_ledger.private_writer_lookup_barrier_v1(p_barrier_id);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.private_writer_finish_barrier_v1(
 p_snapshot change_ledger.private_writer_barrier_snapshot_v1,p_acknowledgement_ref text,
 p_instance_id text,p_service_epoch bigint
) RETURNS change_ledger.private_writer_barrier_snapshot_v1
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.writer_barriers%ROWTYPE; b change_ledger.writer_barriers%ROWTYPE;
        binding change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE; slot change_ledger.physical_base_slots%ROWTYPE;
        ack change_ledger.writer_barrier_acknowledgements%ROWTYPE;
        frozen_calls uuid[]; unresolved uuid[]; ref_lock text;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_snapshot IS NULL OR p_snapshot.barrier_id IS NULL
   OR p_snapshot.barrier_id='00000000-0000-0000-0000-000000000000'::uuid OR p_snapshot.scope IS NULL
   OR p_snapshot.scope.tenant_id IS NULL OR p_snapshot.scope.company_id IS NULL
   OR p_snapshot.barrier_origin_instance_id IS NULL OR p_snapshot.barrier_origin_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_snapshot.call_ids IS NULL OR p_snapshot.progress<>'CLOSED_WITH_HOLD'
   OR p_snapshot.acknowledgement_ref IS NOT NULL OR p_snapshot.acknowledgement_digest IS NOT NULL
   OR p_snapshot.quiesced_at IS NOT NULL OR p_acknowledgement_ref IS NULL
   OR p_acknowledgement_ref='' OR p_acknowledgement_ref<>btrim(p_acknowledgement_ref)
   OR p_instance_id IS NULL OR p_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_service_epoch IS NULL OR p_service_epoch<=0 THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO hint FROM change_ledger.writer_barriers x
  WHERE x.barrier_id=p_snapshot.barrier_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001'; END IF;
 SELECT * INTO binding FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
  END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
  IF NOT FOUND OR lf.state<>'RECOVERING' OR lf.epoch<>hint.epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 ref_lock:='barrier-ack-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_acknowledgement_ref,'UTF8')),'hex');
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'barrier-id:v1:'||lower(p_snapshot.barrier_id::text),ref_lock]);
 SELECT * INTO binding FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=binding.writer_service_id AND x.base_fingerprint=binding.base_fingerprint
   AND x."session_user"=binding."session_user" AND x.writer_host_id=binding.writer_host_id FOR UPDATE;
 IF NOT FOUND OR serving.service_instance_id<>p_instance_id
   OR serving.service_epoch<>p_service_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO b FROM change_ledger.writer_barriers x
  WHERE x.barrier_id=p_snapshot.barrier_id FOR UPDATE;
 IF NOT FOUND OR ROW(p_snapshot.base_fingerprint,p_snapshot.scope.tenant_id,
     p_snapshot.scope.company_id,p_snapshot.expected_current_epoch,p_snapshot.epoch,
     p_snapshot.barrier_origin_instance_id,p_snapshot.barrier_origin_service_epoch)
   IS DISTINCT FROM ROW(b.base_fingerprint,b.tenant_id,b.company_id,b.expected_current_epoch,
     b.epoch,b.barrier_origin_instance_id,b.barrier_origin_service_epoch) THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(array_agg(c.call_id ORDER BY c.call_id),ARRAY[]::uuid[]),
        coalesce(array_agg(c.call_id ORDER BY c.call_id)
          FILTER(WHERE a.state<>'TERMINAL_WITH_EVIDENCE'),ARRAY[]::uuid[])
  INTO frozen_calls,unresolved
  FROM change_ledger.writer_barrier_calls c
  JOIN change_ledger.dispatch_attempts a ON a.dispatch_cas_id=c.dispatch_cas_id
  WHERE c.barrier_id=b.barrier_id;
 IF frozen_calls IS DISTINCT FROM p_snapshot.call_ids OR cardinality(unresolved)>0 THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 PERFORM 1 FROM change_ledger.dispatch_attempts a
  JOIN change_ledger.writer_barrier_calls c ON c.dispatch_cas_id=a.dispatch_cas_id
  WHERE c.barrier_id=b.barrier_id ORDER BY a.call_id FOR SHARE OF a;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=b.base_fingerprint FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO ack FROM change_ledger.writer_barrier_acknowledgements x
  WHERE x.barrier_id=b.barrier_id AND x.acknowledgement_ref=p_acknowledgement_ref FOR SHARE;
 IF NOT FOUND OR ROW(ack.base_fingerprint,ack.tenant_id,ack.company_id,ack.lifecycle_epoch,
     ack.barrier_origin_instance_id,ack.barrier_origin_service_epoch,ack.call_ids,
     ack.writer_service_id,ack.writer_host_id,ack.signed_bytes_sha256)
   IS DISTINCT FROM ROW(b.base_fingerprint,b.tenant_id,b.company_id,b.epoch,
     b.barrier_origin_instance_id,b.barrier_origin_service_epoch,frozen_calls,
     binding.writer_service_id,binding.writer_host_id,pg_catalog.sha256(ack.signed_bytes)) THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF b.progress='QUIESCED' THEN
  IF b.acknowledgement_ref IS DISTINCT FROM ack.acknowledgement_ref
    OR b.acknowledgement_digest IS DISTINCT FROM ack.signed_bytes_sha256
    OR slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN
   RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN change_ledger.private_writer_lookup_barrier_v1(b.barrier_id);
 END IF;
 IF b.progress<>'CLOSED_WITH_HOLD' OR lf.state<>'RECOVERING' OR lf.epoch<>b.epoch
   OR NOT slot.admission_closed OR slot.open_barrier_id IS DISTINCT FROM b.barrier_id THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 UPDATE change_ledger.writer_barriers SET progress='QUIESCED',
  acknowledgement_ref=ack.acknowledgement_ref,acknowledgement_digest=ack.signed_bytes_sha256
  WHERE barrier_id=b.barrier_id AND progress='CLOSED_WITH_HOLD';
 IF NOT FOUND THEN RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.physical_base_slots SET admission_closed=false,open_barrier_id=NULL
  WHERE base_fingerprint=b.base_fingerprint AND admission_closed AND open_barrier_id=b.barrier_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001'; END IF;
 RETURN change_ledger.private_writer_lookup_barrier_v1(b.barrier_id);
END $fn$;

CREATE FUNCTION change_ledger.approve_registry_change_v1(
 t text,c text,p_change_id uuid,p_digest text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; plan change_ledger.registry_changes%ROWTYPE; rc change_ledger.registry_changes%ROWTYPE;
        ap change_ledger.registry_change_approvals%ROWTYPE; lf change_ledger.lifecycle_fences%ROWTYPE;
        n jsonb; v bigint; caps text[];
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_change_id IS NULL OR p_digest IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO plan FROM change_ledger.registry_changes x
  WHERE x.change_id=p_change_id AND x.tenant_id=t AND x.company_id=c;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 IF plan.kind='TARGET' THEN
  IF pg_catalog.jsonb_typeof(plan.params->'base') IS DISTINCT FROM 'string' THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  PERFORM change_ledger.private_writer_take_base_fence_v1(plan.params->>'base');
 END IF;
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 IF plan.kind='TARGET' THEN
  PERFORM change_ledger.private_writer_assert_base_scope_limit_v1(plan.params->>'base',t,c);
 END IF;
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF plan.kind='VERIFIER_KEY' THEN
  IF pg_catalog.jsonb_typeof(plan.params->'key_material') IS DISTINCT FROM 'string' THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(plan.params->>'key_material',17017));
 END IF;
 IF plan.kind='VERIFIER_KEY' THEN
  PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
   'registry-change-id:v1:'||pg_catalog.lower(p_change_id::text),
   'verifier-key-id:v1:'||(plan.params->>'key_id')
  ]);
 ELSE
  PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
   'registry-change-id:v1:'||pg_catalog.lower(p_change_id::text)
  ]);
 END IF;

 SELECT * INTO rc FROM change_ledger.registry_changes x
  WHERE x.change_id=p_change_id AND x.tenant_id=t AND x.company_id=c FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF ROW(plan.kind,plan.params,plan.params_digest,plan.proposer,plan.proposer_person,
        plan.proposer_session,plan.expires_at)
    IS DISTINCT FROM
    ROW(rc.kind,rc.params,rc.params_digest,rc.proposer,rc.proposer_person,
        rc.proposer_session,rc.expires_at) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF p_digest IS DISTINCT FROM rc.params_digest THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
 SELECT * INTO ap FROM change_ledger.registry_change_approvals a
  WHERE a.change_id=p_change_id FOR UPDATE;
 IF FOUND THEN
  IF change_ledger.same_person(t,c,ap.approver,who) THEN
   RETURN pg_catalog.jsonb_build_object('registry_change_id',p_change_id,'kind',rc.kind,
    'digest',rc.params_digest,'epoch',NULL::bigint,'replay',true);
  END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF rc.expires_at<=pg_catalog.clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'operator');
 PERFORM change_ledger.assert_capability(t,c,rc.proposer,'operator');
 PERFORM change_ledger.assert_independent(t,c,who,rc.proposer);
 PERFORM change_ledger.assert_session_independent(t,c,rc.proposer_session);
 n:=rc.params;
 INSERT INTO change_ledger.registry_change_approvals(change_id,tenant_id,company_id,approver,approver_person,
  approver_session,proposer,proposer_person,proposer_session,params_digest)
 VALUES(p_change_id,t,c,who,change_ledger.person_of(t,c,who),session_user::text,rc.proposer,rc.proposer_person,
  rc.proposer_session,rc.params_digest);
 IF rc.kind='PRINCIPAL' THEN
  caps:=ARRAY(SELECT jsonb_array_elements_text(n->'capabilities'));
  v:=change_ledger.register_principal_core(t,c,n->>'principal',n->>'person_id',caps,(n->>'active')::boolean,who);
 ELSIF rc.kind='TARGET' THEN
  v:=change_ledger.register_target_core(t,c,n->>'base',n->>'organization',n->>'class',n->>'status',
   (n->>'permission_expires_at')::timestamptz,who);
 ELSE
  PERFORM change_ledger.register_verifier_key_core(t,c,n->>'key_id',n->>'role_name',n->>'key_material',who);
  v:=NULL;
 END IF;
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_CHANGE_APPLIED',
  pg_catalog.jsonb_build_object('registry_change_id',p_change_id,'kind',rc.kind,'digest',rc.params_digest,
   'proposer',rc.proposer,'proposer_person',rc.proposer_person,'proposer_session',rc.proposer_session,
   'approver',who,'approver_person',change_ledger.person_of(t,c,who),
   'approver_session',session_user::text,'summary',change_ledger.registry_summary(rc.kind,n)));
 RETURN pg_catalog.jsonb_build_object('registry_change_id',p_change_id,'kind',rc.kind,
  'digest',rc.params_digest,'epoch',v,'replay',false);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.register_verifier_key_v1(
 t text,c text,p_key_id text,p_role_name text,p_key_material text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; n jsonb; ex change_ledger.verifier_keys%ROWTYPE; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 n:=change_ledger.registry_normalize('VERIFIER_KEY',pg_catalog.jsonb_build_object(
  'key_id',p_key_id,'role_name',p_role_name,'key_material',p_key_material));
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 -- Match verifier_key_receipt_role_guard's exact key and rank it before verifier row/index work.
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(p_key_material,17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'verifier-key-id:v1:'||p_key_id
 ]);
 SELECT * INTO ex FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND AND (ex.key_material IS DISTINCT FROM p_key_material OR ex.role_name IS DISTINCT FROM p_role_name) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF NOT change_ledger.registry_single_ok(t,c,'VERIFIER_KEY',n) THEN
  RAISE EXCEPTION 'TWO_PERSON_REQUIRED';
 END IF;
 PERFORM change_ledger.register_verifier_key_core(t,c,p_key_id,p_role_name,p_key_material,who);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_verifier_key_v1(t text,c text,p_key_id text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; n integer; v_key_material text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 -- The legacy void API treats a NULL key ID as a successful no-op with no event.
 IF p_key_id IS NULL THEN RETURN; END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 -- Resolve the immutable material identity without a row lock, then take the same
 -- advisory fence as registration/approval before verifier-key row locks.
 SELECT k.key_material INTO v_key_material FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND THEN
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(v_key_material,17017));
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'verifier-key-id:v1:'||p_key_id
 ]);
 UPDATE change_ledger.verifier_keys k SET status='REVOKED'
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id AND k.status='ACTIVE'
   AND v_key_material IS NOT NULL AND k.key_material=v_key_material;
 GET DIAGNOSTICS n=ROW_COUNT;
 IF n=1 THEN
  PERFORM change_ledger.append_event(t,c,NULL,'VERIFIER_KEY_REVOKED',
   pg_catalog.jsonb_build_object('key_id',p_key_id,'by',who));
 END IF;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.attach_permit_signature_v1(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_signature text
) RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; rec_before change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        dp_before change_ledger.dispatch_permits%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        vk_before change_ledger.verifier_keys%ROWTYPE; vk change_ledger.verifier_keys%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'checkpoint_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'
   OR p_generation IS NULL OR p_generation<=0 OR p_key_id IS NULL OR p_key_id=''
   OR p_key_id<>pg_catalog.btrim(p_key_id) OR p_signature IS NULL OR p_signature='' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 -- S13 makes this commit the first relation-lock participant for the tenant/company scope.
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
  -- Keep the row lock, but evaluate admission from a distinct READ COMMITTED statement snapshot.
  SELECT * INTO lf FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c;
  IF NOT FOUND OR lf.state<>'READY' THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);

 -- The same key-material advisory identity serializes signature attachment with key
 -- registration, approval and revocation. Acquire it before namespace-6 and relation rows.
 SELECT * INTO vk_before FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND AND vk_before.key_material IS NOT NULL AND vk_before.key_material<>'' THEN
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(vk_before.key_material,17017));
 END IF;

 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text)]);

 SELECT * INTO rec_before FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT * INTO dp_before FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=p_generation AND p.state='PERMITTED';
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;

 -- The permit references its record parent; lock that parent first, then the permit child.
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR pg_catalog.to_jsonb(rec) IS DISTINCT FROM pg_catalog.to_jsonb(rec_before) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT * INTO dp FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=p_generation FOR UPDATE;
 IF NOT FOUND OR pg_catalog.to_jsonb(dp) IS DISTINCT FROM pg_catalog.to_jsonb(dp_before)
   OR dp.state<>'PERMITTED' THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 -- Signing is an operation on a live permit; recheck expiry after acquiring the
 -- frozen permit row so an expired PERMITTED state cannot receive a new signature.
 IF dp.expires_at IS NULL OR dp.expires_at<=pg_catalog.clock_timestamp() THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;

 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;
 IF vk_before.key_id IS NULL
   OR pg_catalog.to_jsonb(vk) IS DISTINCT FROM pg_catalog.to_jsonb(vk_before) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
   OR NOT pg_catalog.pg_has_role(who::name,vk.role_name::name,'USAGE')
   OR vk.key_algorithm IS DISTINCT FROM 'ED25519'
   OR vk.key_material IS NULL OR vk.key_material='' THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,
    'change-ledger-permit|v1|'||dp.permit_digest,p_signature) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 UPDATE change_ledger.dispatch_permits p SET signer_key_id=p_key_id,signature=p_signature
  WHERE p.change_id=p_change_id AND p.generation=p_generation AND p.state='PERMITTED'
   AND p.permit_digest=dp.permit_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
END $fn$;

CREATE FUNCTION change_ledger.register_target_v1(
 t text,c text,p_base text,p_org text,p_class text,p_status text,p_permission_expires_at timestamptz
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; n jsonb; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 n:=change_ledger.registry_normalize('TARGET',pg_catalog.jsonb_build_object(
  'base',p_base,'organization',p_org,'class',p_class,'status',p_status,
  'permission_expires_at',pg_catalog.to_jsonb(change_ledger.registry_ts_text(p_permission_expires_at))));
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_base_fence_v1(p_base);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM change_ledger.private_writer_assert_base_scope_limit_v1(p_base,t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
  IF EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL) THEN
   RAISE EXCEPTION 'ANCHOR_GAP_ACTIVE' USING ERRCODE='P0001';
  END IF;
 IF NOT change_ledger.registry_single_ok(t,c,'TARGET',n) THEN RAISE EXCEPTION 'TWO_PERSON_REQUIRED'; END IF;
 RETURN change_ledger.register_target_core(t,c,p_base,p_org,n->>'class',p_status,p_permission_expires_at,who);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.require_dispatch_receipt_v1(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text)
 ]);
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF who IS DISTINCT FROM rec.requester AND NOT pg_catalog.pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' OR rec.dispatch_state='DISPATCHED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 INSERT INTO change_ledger.dispatch_receipt_requirements(
  tenant_id,company_id,change_id,generation,required_by
 ) VALUES(t,c,p_change_id,p_generation,who)
 ON CONFLICT(change_id,generation) DO NOTHING;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.record_dispatch_receipt_v1(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_received_sha text,
 p_new_version text,p_signature text,p_receipt_id uuid
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text;
        vk_before change_ledger.verifier_keys%ROWTYPE; vk change_ledger.verifier_keys%ROWTYPE;
        did uuid; ex change_ledger.dispatch_receipts%ROWTYPE; verified_wire_sha text;
        lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF p_change_id IS NULL OR p_generation IS NULL OR p_key_id IS NULL OR p_key_id=''
   OR p_signature IS NULL OR p_received_sha IS NULL OR p_received_sha !~ '^[a-f0-9]{64}$'
   OR p_new_version IS NULL OR p_new_version='' OR pg_catalog.strpos(p_new_version,'|')>0
    OR p_receipt_id IS NULL
    OR p_receipt_id='00000000-0000-0000-0000-000000000000'::uuid THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 -- Serialize receipt signature validation with verifier-key registration and revocation.
 -- Keep the non-locking key snapshot as a hint; preserve receipt error precedence below.
 SELECT * INTO vk_before FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND AND vk_before.key_material IS NOT NULL AND vk_before.key_material<>'' THEN
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(vk_before.key_material,17017));
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'dispatch-receipt-id:v1:'||pg_catalog.lower(p_receipt_id::text)
 ]);
 IF EXISTS(SELECT 1 FROM change_ledger.dispatch_receipts r WHERE r.receipt_id=p_receipt_id) THEN
  RAISE EXCEPTION 'RECEIPT_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF who IS DISTINCT FROM rec.requester AND NOT pg_catalog.pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;

 SELECT dp.call_id INTO did FROM change_ledger.dispatch_permits dp
  WHERE dp.change_id=p_change_id AND dp.generation=p_generation AND dp.state='DISPATCHED';
 IF NOT FOUND OR rec.dispatch_state<>'DISPATCHED' THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF vk_before.key_id IS NULL
   OR pg_catalog.to_jsonb(vk) IS DISTINCT FROM pg_catalog.to_jsonb(vk_before) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF vk.status<>'ACTIVE' OR vk.role_name<>'receipt_role' THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,
   change_ledger.dispatch_receipt_text(p_change_id,did,p_received_sha,p_new_version),p_signature) THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 SELECT v.wire_payload_sha256 INTO verified_wire_sha
  FROM change_ledger.change_dispatch_verifications v
  WHERE v.change_id=p_change_id AND v.generation=p_generation
   AND v.payload_digest=rec.payload_digest AND v.wire_payload_sha256 IS NOT NULL;
 IF NOT FOUND OR verified_wire_sha IS NULL OR verified_wire_sha IS DISTINCT FROM p_received_sha THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;

 SELECT * INTO ex FROM change_ledger.dispatch_receipts r
  WHERE r.change_id=p_change_id AND r.generation=p_generation;
 IF FOUND THEN
  IF ex.dispatch_id IS DISTINCT FROM did
    OR ex.received_payload_sha256 IS DISTINCT FROM p_received_sha
    OR ex.new_version IS DISTINCT FROM p_new_version
    OR ex.signer_key_id IS DISTINCT FROM p_key_id
    OR ex.signature IS DISTINCT FROM p_signature THEN
   RAISE EXCEPTION 'RECEIPT_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN ex.receipt_id;
 END IF;
 INSERT INTO change_ledger.dispatch_receipts(
  receipt_id,tenant_id,company_id,change_id,generation,dispatch_id,received_payload_sha256,
  new_version,signer_key_id,signature,recorded_by
 ) VALUES(p_receipt_id,t,c,p_change_id,p_generation,did,p_received_sha,p_new_version,p_key_id,p_signature,who);
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_RECEIPT_RECORDED',
  pg_catalog.jsonb_build_object('receipt_id',p_receipt_id,'generation',p_generation,'dispatch_id',did,
   'received_payload_sha256',p_received_sha,'new_version',p_new_version,'key_id',p_key_id));
 RETURN p_receipt_id;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.verify_dispatch_payload_v1(
 t text,c text,p_change_id uuid,p_generation bigint,p_payload text,p_verification_id uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; pl jsonb; canonical_payload text;
        wire_sha text; existing_sha text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
  IF p_change_id IS NULL OR p_generation IS NULL OR p_verification_id IS NULL
    OR p_verification_id='00000000-0000-0000-0000-000000000000'::uuid THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'dispatch-verification-id:v1:'||pg_catalog.lower(p_verification_id::text)
 ]);
 IF EXISTS(SELECT 1 FROM change_ledger.change_dispatch_verifications v
   WHERE v.verification_id=p_verification_id) THEN
  RAISE EXCEPTION 'DISPATCH_VERIFICATION_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF who IS DISTINCT FROM rec.requester AND NOT pg_catalog.pg_has_role(who::name,'writer_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF rec.authorization_state<>'CLAIMED' OR rec.execution_state<>'APPLYING' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_approval_current(t,c,rec);

 BEGIN
  pl:=coalesce(p_payload,'{}')::jsonb;
 EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END;
 IF pg_catalog.jsonb_typeof(pl)='null' THEN pl:='{}'::jsonb; END IF;
 IF pg_catalog.jsonb_typeof(pl)<>'object' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 canonical_payload:=change_ledger.canon_json(pl);
 IF p_payload IS NOT NULL AND p_payload IS DISTINCT FROM canonical_payload THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF change_ledger.payload_digest_of(pl,rec.target_version) IS DISTINCT FROM rec.payload_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 wire_sha:=change_ledger.text_digest(canonical_payload);
 SELECT v.wire_payload_sha256 INTO existing_sha FROM change_ledger.change_dispatch_verifications v
  WHERE v.change_id=p_change_id AND v.generation=p_generation
   AND v.payload_digest=rec.payload_digest AND v.wire_payload_sha256 IS NOT NULL;
 IF FOUND THEN
  IF existing_sha IS DISTINCT FROM wire_sha THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
  RETURN true;
 END IF;
 INSERT INTO change_ledger.change_dispatch_verifications(
  verification_id,tenant_id,company_id,change_id,generation,payload_digest,wire_payload_sha256,verified_by
 ) VALUES(p_verification_id,t,c,p_change_id,p_generation,rec.payload_digest,wire_sha,who);
 PERFORM change_ledger.append_event(t,c,p_change_id,'DISPATCH_PAYLOAD_VERIFIED',
  pg_catalog.jsonb_build_object('generation',p_generation,'payload_digest',rec.payload_digest,
   'wire_payload_sha256',wire_sha,'verification_id',p_verification_id));
 RETURN true;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.check_anchor_v1(t text,c text,p_ext_seq bigint,p_ext_head_hash text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE ok boolean; plan_targets jsonb; current_targets jsonb; plan_holds jsonb; current_holds jsonb;
        plan_new jsonb; plan_new_bases jsonb; current_new_bases jsonb;
        global_keys text[]:=ARRAY[]::text[]; item record; opened integer:=0;
        target_count bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_ext_seq IS NULL OR p_ext_seq<1 OR p_ext_head_hash IS NULL
   OR p_ext_head_hash!~'^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
  PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.seq=p_ext_seq AND e.hash=p_ext_head_hash) INTO ok;
 IF ok THEN RETURN pg_catalog.jsonb_build_object('ok',true,'holds_opened',0); END IF;
 SELECT count(*) INTO target_count FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c;
 IF target_count>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
   SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO plan_targets FROM (SELECT x.* FROM change_ledger.targets x
    WHERE x.tenant_id=t AND x.company_id=c ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.hold_id),'[]'::jsonb)
  INTO plan_holds FROM (SELECT h.* FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
   AND (h.ext_seq IS NULL OR h.ext_seq<p_ext_seq)
   ORDER BY h.base_fingerprint,h.hold_id LIMIT 201) x;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'base_fingerprint',x.base_fingerprint,'hold_id',pg_catalog.gen_random_uuid())
   ORDER BY x.base_fingerprint),'[]'::jsonb)
    INTO plan_new FROM (SELECT x.base_fingerprint FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND NOT EXISTS(SELECT 1 FROM change_ledger.holds h
    WHERE h.tenant_id=t AND h.company_id=c AND h.base_fingerprint=x.base_fingerprint
     AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL)
   ORDER BY x.base_fingerprint LIMIT 201) x;
  IF pg_catalog.jsonb_array_length(plan_targets)>200 OR pg_catalog.jsonb_array_length(plan_holds)>200
    OR pg_catalog.jsonb_array_length(plan_new)>200
    OR pg_catalog.jsonb_array_length(plan_targets)+pg_catalog.jsonb_array_length(plan_holds)
       +pg_catalog.jsonb_array_length(plan_new)>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('base_fingerprint',x.base_fingerprint)
   ORDER BY x.base_fingerprint),'[]'::jsonb)
  INTO plan_new_bases FROM pg_catalog.jsonb_to_recordset(plan_new) AS x(base_fingerprint text,hold_id uuid);
 FOR item IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(
   hold_id uuid,tenant_id text,company_id text,base_fingerprint text,cause text,change_id uuid,
   opened_at timestamptz,released_at timestamptz,release_evidence jsonb,ext_seq bigint,ext_head_hash text)
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(item.hold_id::text));
 END LOOP;
 FOR item IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_new) AS x(base_fingerprint text,hold_id uuid)
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(item.hold_id::text));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 IF EXISTS(SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_new) AS x(base_fingerprint text,hold_id uuid)
   GROUP BY x.hold_id HAVING count(*)>1)
   OR EXISTS(SELECT 1 FROM change_ledger.holds h JOIN pg_catalog.jsonb_to_recordset(plan_new) AS x(
    base_fingerprint text,hold_id uuid) USING(hold_id)) THEN
  RAISE EXCEPTION 'HOLD_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':ANCHOR_GAP'));
 SELECT count(*) INTO target_count FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c;
 IF target_count>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
  FOR item IN SELECT x.base_fingerprint
    FROM pg_catalog.jsonb_to_recordset(plan_targets) AS x(base_fingerprint text)
    ORDER BY x.base_fingerprint
 LOOP
  PERFORM 1 FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c
     AND x.base_fingerprint=item.base_fingerprint FOR SHARE;
 END LOOP;
 PERFORM 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
  AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
  AND (h.ext_seq IS NULL OR h.ext_seq<p_ext_seq)
  ORDER BY h.base_fingerprint,h.hold_id LIMIT 201 FOR UPDATE;
    SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint),'[]'::jsonb)
     INTO current_targets FROM (SELECT x.* FROM change_ledger.targets x
     WHERE x.tenant_id=t AND x.company_id=c ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.hold_id),'[]'::jsonb)
  INTO current_holds FROM (SELECT h.* FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
   AND (h.ext_seq IS NULL OR h.ext_seq<p_ext_seq)
   ORDER BY h.base_fingerprint,h.hold_id LIMIT 201) x;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('base_fingerprint',x.base_fingerprint)
   ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO current_new_bases FROM (SELECT x.base_fingerprint FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND NOT EXISTS(SELECT 1 FROM change_ledger.holds h
    WHERE h.tenant_id=t AND h.company_id=c AND h.base_fingerprint=x.base_fingerprint
     AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL)
   ORDER BY x.base_fingerprint LIMIT 201) x;
 IF plan_targets IS DISTINCT FROM current_targets OR plan_holds IS DISTINCT FROM current_holds
   OR plan_new_bases IS DISTINCT FROM current_new_bases THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(1,pg_catalog.hashtext(t||':'||c));
 SELECT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.seq=p_ext_seq AND e.hash=p_ext_head_hash) INTO ok;
 IF ok THEN RETURN pg_catalog.jsonb_build_object('ok',true,'holds_opened',0); END IF;
 IF pg_catalog.jsonb_array_length(plan_holds)=0 AND pg_catalog.jsonb_array_length(plan_new)=0
   AND EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
     AND e.event_type='ANCHOR_GAP'
     AND e.payload=pg_catalog.jsonb_build_object('ext_seq',p_ext_seq,'ext_head_hash',p_ext_head_hash)) THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'holds_opened',0);
 END IF;
 FOR item IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(
   hold_id uuid,tenant_id text,company_id text,base_fingerprint text,cause text,change_id uuid,
   opened_at timestamptz,released_at timestamptz,release_evidence jsonb,ext_seq bigint,ext_head_hash text)
  WHERE x.ext_seq IS NULL OR x.ext_seq<p_ext_seq
 LOOP
  UPDATE change_ledger.holds SET ext_seq=p_ext_seq,ext_head_hash=p_ext_head_hash WHERE hold_id=item.hold_id;
 END LOOP;
 FOR item IN SELECT x.base_fingerprint,x.hold_id
   FROM pg_catalog.jsonb_to_recordset(plan_new) AS x(base_fingerprint text,hold_id uuid)
   ORDER BY x.base_fingerprint
 LOOP
  INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause,ext_seq,ext_head_hash)
   VALUES(item.hold_id,t,c,item.base_fingerprint,'ANCHOR_GAP',p_ext_seq,p_ext_head_hash);
  opened:=opened+1;
 END LOOP;
 PERFORM change_ledger.append_event(t,c,NULL,'ANCHOR_GAP',
  pg_catalog.jsonb_build_object('ext_seq',p_ext_seq,'ext_head_hash',p_ext_head_hash));
 RETURN pg_catalog.jsonb_build_object('ok',false,'holds_opened',opened);
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.revoke_stale_v1(t text,c text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; plan_records jsonb; current_records jsonb;
        plan_parent_records jsonb; current_parent_records jsonb;
        plan_tokens jsonb; current_tokens jsonb;
        plan_targets jsonb; current_targets jsonb; plan_tlocks jsonb; current_tlocks jsonb;
        plan_keys jsonb; current_keys jsonb; plan_res jsonb; current_res jsonb;
        plan_leases jsonb; current_leases jsonb; plan_failures jsonb; current_failures jsonb;
        ids uuid[]:='{}'::uuid[]; parent_ids uuid[]:='{}'::uuid[];
        record_lock_ids uuid[]:='{}'::uuid[]; bases text[]:='{}'::text[];
        global_keys text[]:=ARRAY[]::text[]; key_keys text[]:=ARRAY[]::text[];
        item record; cid uuid; lock_hash integer; lock_rows integer; effects integer;
        success_count integer:=0; result_state text; err_state text; err_msg text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'worker_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 -- Preserve the approved candidate rank: namespace 2 -> scope 7 -> lifecycle row -> sweep 5.
 PERFORM pg_catalog.pg_advisory_xact_lock(5,pg_catalog.hashtext('sweep:'||t||':'||c));

 -- Select the largest ordered prefix whose conservative lock and effect estimates fit one batch.
 -- A fixed top-20 set can exceed the 200-row cap from token/resource fan-out and then refuse
 -- unchanged before per-item failure state is written, starving every later eligible record.
 WITH eligible AS (
  SELECT r.change_id,r.created_at,r.authorization_state,r.base_fingerprint,r.parent_change_id,
   r.repair_for,sf.last_at AS failure_last_at
   FROM change_ledger.records r
   LEFT JOIN change_ledger.sweep_failures sf ON sf.tenant_id=r.tenant_id AND sf.company_id=r.company_id
    AND sf.subject_id=r.change_id AND sf.stage='REVOKE_STALE'
   WHERE r.tenant_id=t AND r.company_id=c AND r.authorization_state IN ('APPROVED','CLAIMED')
    AND r.execution_state='NOT_STARTED' AND r.dispatch_state NOT IN ('PERMITTED','DISPATCHED')
    AND NOT change_ledger.epoch_deps_current(t,c,r.epoch_dependencies)
   ORDER BY sf.last_at NULLS FIRST,r.created_at,r.change_id LIMIT 20
 ), costs AS (
  SELECT e.*,
   2+(SELECT count(DISTINCT p.parent_id) FROM pg_catalog.unnest(
      ARRAY[e.parent_change_id,e.repair_for]
     ) p(parent_id) WHERE p.parent_id IS NOT NULL AND p.parent_id<>e.change_id)
    +(SELECT count(*) FROM change_ledger.claim_tokens x WHERE x.change_id=e.change_id)
    +(SELECT count(*) FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c
      AND x.base_fingerprint=e.base_fingerprint)
    +(SELECT count(*) FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
      AND x.owner_change_id=e.change_id)
    +(SELECT count(*) FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
      AND x.owner_change_id=e.change_id)
    +(SELECT count(*) FROM change_ledger.reservations x WHERE x.change_id=e.change_id)
    +(SELECT count(*) FROM change_ledger.writer_leases x WHERE x.tenant_id=t AND x.company_id=c
      AND x.owner_change_id=e.change_id) AS lock_cost,
   3+(SELECT count(*) FROM change_ledger.claim_tokens x WHERE x.change_id=e.change_id)
    +(SELECT count(*) FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
      AND x.owner_change_id=e.change_id)
    +CASE WHEN e.authorization_state='CLAIMED' THEN 4 ELSE 0 END AS effect_cost
  FROM eligible e
 ), ranked AS (
  SELECT x.*,row_number() OVER (ORDER BY x.failure_last_at NULLS FIRST,x.created_at,x.change_id) AS batch_rank,
   sum(x.lock_cost) OVER (ORDER BY x.failure_last_at NULLS FIRST,x.created_at,x.change_id) AS batch_lock_rows,
   sum(x.effect_cost) OVER (ORDER BY x.failure_last_at NULLS FIRST,x.created_at,x.change_id) AS batch_effect_rows
  FROM costs x
 ), selected AS (
  SELECT x.change_id,x.batch_rank FROM ranked x WHERE x.batch_rank<=20
   AND x.batch_lock_rows<=200 AND x.batch_effect_rows<=200
 )
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY s.batch_rank),'[]'::jsonb)
  INTO plan_records FROM selected s JOIN change_ledger.records r USING(change_id);
 IF pg_catalog.jsonb_array_length(plan_records)=0 AND EXISTS(
   SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.sweep_failures sf
    ON sf.tenant_id=r.tenant_id AND sf.company_id=r.company_id AND sf.subject_id=r.change_id
     AND sf.stage='REVOKE_STALE'
   WHERE r.tenant_id=t AND r.company_id=c AND r.authorization_state IN ('APPROVED','CLAIMED')
    AND r.execution_state='NOT_STARTED' AND r.dispatch_state NOT IN ('PERMITTED','DISPATCHED')
    AND NOT change_ledger.epoch_deps_current(t,c,r.epoch_dependencies)) THEN
  RAISE EXCEPTION 'NOT_ACCEPTED';
 END IF;
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks k
    JOIN pg_catalog.jsonb_to_recordset(plan_records) AS r(
      change_id uuid,tenant_id text,company_id text,base_fingerprint text)
      ON r.change_id=k.owner_change_id
    WHERE k.tenant_id IS DISTINCT FROM r.tenant_id
      OR k.company_id IS DISTINCT FROM r.company_id
      OR k.base_fingerprint IS DISTINCT FROM r.base_fingerprint) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  FOR item IN SELECT x.change_id,x.base_fingerprint FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(
    change_id uuid,base_fingerprint text)
  LOOP
   PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
    t,c,item.change_id,item.base_fingerprint);
  END LOOP;
 SELECT coalesce(pg_catalog.array_agg(x.change_id ORDER BY x.change_id),'{}'::uuid[])
  INTO ids FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(change_id uuid);
 SELECT coalesce(pg_catalog.array_agg(DISTINCT x.base_fingerprint ORDER BY x.base_fingerprint),'{}'::text[])
  INTO bases FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(base_fingerprint text);
 SELECT coalesce(pg_catalog.array_agg(DISTINCT p.parent_id ORDER BY p.parent_id),'{}'::uuid[])
  INTO parent_ids FROM (
   SELECT x.parent_change_id AS parent_id
    FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(parent_change_id uuid)
   UNION
   SELECT x.repair_for AS parent_id
    FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(repair_for uuid)
  ) p WHERE p.parent_id IS NOT NULL AND NOT (p.parent_id=ANY(ids));
 SELECT coalesce(pg_catalog.array_agg(DISTINCT u.record_id ORDER BY u.record_id),'{}'::uuid[])
  INTO record_lock_ids FROM pg_catalog.unnest(ids||parent_ids) AS u(record_id);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO plan_parent_records FROM change_ledger.records x WHERE x.change_id=ANY(parent_ids);
 IF pg_catalog.jsonb_array_length(plan_parent_records)<>pg_catalog.cardinality(parent_ids)
    OR EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_parent_records) AS x(
       tenant_id text,company_id text)
      WHERE x.tenant_id<>t OR x.company_id<>c) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO plan_tokens FROM (SELECT x.* FROM change_ledger.claim_tokens x WHERE x.change_id=ANY(ids)
   ORDER BY x.token_id LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
   ORDER BY x.base_fingerprint),'[]'::jsonb)
  INTO plan_targets FROM (SELECT x.* FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=ANY(bases) ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.target_ref),'[]'::jsonb)
  INTO plan_tlocks FROM (SELECT x.* FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint,x.target_ref LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO plan_keys FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO plan_res FROM (SELECT x.* FROM change_ledger.reservations x WHERE x.change_id=ANY(ids)
   ORDER BY x.change_id LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint),'[]'::jsonb)
  INTO plan_leases FROM (SELECT x.* FROM change_ledger.writer_leases x WHERE x.tenant_id=t AND x.company_id=c
   AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.subject_id,x.stage),'[]'::jsonb)
  INTO plan_failures FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=ANY(ids) AND x.stage='REVOKE_STALE'
   ORDER BY x.subject_id,x.stage LIMIT 201) x;

 -- Include one possible failure row per item, including rows that do not exist yet.
 lock_rows:=pg_catalog.cardinality(ids)*2+pg_catalog.cardinality(parent_ids)
  +pg_catalog.jsonb_array_length(plan_tokens)
  +pg_catalog.jsonb_array_length(plan_targets)+pg_catalog.jsonb_array_length(plan_tlocks)
  +pg_catalog.jsonb_array_length(plan_keys)+pg_catalog.jsonb_array_length(plan_res)
  +pg_catalog.jsonb_array_length(plan_leases);
 SELECT pg_catalog.cardinality(ids)*2 + pg_catalog.jsonb_array_length(plan_tokens)
   +pg_catalog.jsonb_array_length(plan_keys)
   +4*(SELECT count(*) FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(authorization_state text)
       WHERE x.authorization_state='CLAIMED')
   +pg_catalog.cardinality(ids)
  INTO effects;
  IF lock_rows>200 OR effects>200
    OR pg_catalog.jsonb_array_length(plan_tokens)>200
    OR pg_catalog.jsonb_array_length(plan_targets)>200
    OR pg_catalog.jsonb_array_length(plan_tlocks)>200
    OR pg_catalog.jsonb_array_length(plan_keys)>200
    OR pg_catalog.jsonb_array_length(plan_res)>200
    OR pg_catalog.jsonb_array_length(plan_leases)>200
    OR pg_catalog.jsonb_array_length(plan_failures)>200 THEN
   RAISE EXCEPTION 'NOT_ACCEPTED';
  END IF;

 FOREACH cid IN ARRAY record_lock_ids
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(cid::text));
 END LOOP;
 FOR item IN SELECT x.change_id FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(change_id uuid)
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'sweep-failure:v1:'||pg_catalog.lower(item.change_id::text)||':REVOKE_STALE');
 END LOOP;
 FOR item IN SELECT x.token_id FROM pg_catalog.jsonb_to_recordset(plan_tokens) AS x(token_id uuid)
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(item.token_id::text));
 END LOOP;
  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  FOR item IN SELECT x.change_id,x.base_fingerprint FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(
    change_id uuid,base_fingerprint text)
  LOOP
   PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
    t,c,item.change_id,item.base_fingerprint);
  END LOOP;
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks k
    JOIN pg_catalog.jsonb_to_recordset(plan_records) AS r(
      change_id uuid,tenant_id text,company_id text,base_fingerprint text)
      ON r.change_id=k.owner_change_id
    WHERE k.tenant_id IS DISTINCT FROM r.tenant_id
      OR k.company_id IS DISTINCT FROM r.company_id
      OR k.base_fingerprint IS DISTINCT FROM r.base_fingerprint)
    OR (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
        FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
         AND x.owner_change_id=ANY(ids)) IS DISTINCT FROM plan_keys THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  FOR item IN SELECT x.key_hash,x.base_fingerprint FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
   key_hash text,base_fingerprint text) ORDER BY x.base_fingerprint,x.key_hash
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||item.base_fingerprint||':'||item.key_hash);
 END LOOP;
 FOR item IN SELECT x.base_fingerprint,x.target_ref FROM pg_catalog.jsonb_to_recordset(plan_tlocks) AS x(
   base_fingerprint text,target_ref text) ORDER BY x.base_fingerprint,x.target_ref
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||item.base_fingerprint||':'||item.target_ref);
 END LOOP;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS u(k) ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;

  PERFORM 1 FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=ANY(bases) ORDER BY x.base_fingerprint LIMIT 201 FOR SHARE;
 PERFORM 1 FROM change_ledger.records x WHERE x.change_id=ANY(record_lock_ids)
  ORDER BY x.change_id FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO current_parent_records FROM change_ledger.records x WHERE x.change_id=ANY(parent_ids);
 PERFORM 1 FROM change_ledger.claim_tokens x WHERE x.change_id=ANY(ids)
  ORDER BY x.token_id LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint,x.key_hash LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.reservations x WHERE x.change_id=ANY(ids)
  ORDER BY x.change_id LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
  AND x.subject_id=ANY(ids) AND x.stage='REVOKE_STALE' ORDER BY x.subject_id,x.stage LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint,x.target_ref LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.writer_leases x WHERE x.tenant_id=t AND x.company_id=c
  AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint LIMIT 201 FOR UPDATE;

 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
          ORDER BY sf.last_at NULLS FIRST,x.created_at,x.change_id),'[]'::jsonb)
  INTO current_records FROM change_ledger.records x
  LEFT JOIN change_ledger.sweep_failures sf ON sf.tenant_id=x.tenant_id AND sf.company_id=x.company_id
   AND sf.subject_id=x.change_id AND sf.stage='REVOKE_STALE'
  WHERE x.change_id=ANY(ids) AND x.tenant_id=t AND x.company_id=c
   AND x.authorization_state IN ('APPROVED','CLAIMED')
   AND x.execution_state='NOT_STARTED' AND x.dispatch_state NOT IN ('PERMITTED','DISPATCHED')
   AND NOT change_ledger.epoch_deps_current(t,c,x.epoch_dependencies);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO current_tokens FROM (SELECT x.* FROM change_ledger.claim_tokens x WHERE x.change_id=ANY(ids)
   ORDER BY x.token_id LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
   ORDER BY x.base_fingerprint),'[]'::jsonb)
  INTO current_targets FROM (SELECT x.* FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=ANY(bases) ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.target_ref),'[]'::jsonb)
  INTO current_tlocks FROM (SELECT x.* FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint,x.target_ref LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO current_keys FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO current_res FROM (SELECT x.* FROM change_ledger.reservations x WHERE x.change_id=ANY(ids)
   ORDER BY x.change_id LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint),'[]'::jsonb)
  INTO current_leases FROM (SELECT x.* FROM change_ledger.writer_leases x WHERE x.tenant_id=t AND x.company_id=c
   AND x.owner_change_id=ANY(ids) ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.subject_id,x.stage),'[]'::jsonb)
  INTO current_failures FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=ANY(ids) AND x.stage='REVOKE_STALE'
   ORDER BY x.subject_id,x.stage LIMIT 201) x;
 IF plan_records IS DISTINCT FROM current_records
   OR plan_parent_records IS DISTINCT FROM current_parent_records
   OR plan_tokens IS DISTINCT FROM current_tokens
   OR plan_targets IS DISTINCT FROM current_targets OR plan_tlocks IS DISTINCT FROM current_tlocks
   OR plan_keys IS DISTINCT FROM current_keys OR plan_res IS DISTINCT FROM current_res
   OR plan_leases IS DISTINCT FROM current_leases OR plan_failures IS DISTINCT FROM current_failures THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);

 FOR item IN SELECT x.change_id
  FROM ROWS FROM (pg_catalog.jsonb_to_recordset(plan_records) AS (change_id uuid))
   WITH ORDINALITY AS x(change_id,ord)
  ORDER BY x.ord
 LOOP
  cid:=item.change_id;
  BEGIN
   result_state:=change_ledger.revoke_core(t,c,cid,'EPOCH_DEPENDENCY');
   IF result_state IN ('REVOKED','VOIDED') THEN
    DELETE FROM change_ledger.sweep_failures WHERE tenant_id=t AND company_id=c
     AND subject_id=cid AND stage='REVOKE_STALE';
    success_count:=success_count+1;
   END IF;
  EXCEPTION WHEN OTHERS THEN
   GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
   PERFORM change_ledger.sweep_item_failed(t,c,cid,'REVOKE_STALE',err_state,err_msg);
  END;
 END LOOP;
 RETURN success_count;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.propose_v1(
 t text,c text,p_change_id uuid,p_kind text,p_base_fingerprint text,p_organization_ref text,
 p_requester text,p_request_id text,p_payload_digest text,p_target_ref text,p_target_version text,
 p_parent_change_id uuid,p_expires_at timestamptz,p_repair_for uuid DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE existing change_ledger.records%ROWTYPE; tgt_epoch bigint; tgt_status text;
        tgt_org text; tgt_exp timestamptz; pre_tgt_epoch bigint; pre_tgt_status text;
        pre_tgt_org text; pre_tgt_exp timestamptz;
        parent_ids uuid[]; parent_count bigint; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
  IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_kind IS NULL OR p_base_fingerprint IS NULL
  OR p_organization_ref IS NULL OR p_requester IS NULL OR p_request_id IS NULL
  OR p_payload_digest IS NULL OR p_expires_at IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_repair_for IS NOT NULL AND (p_kind<>'UNPOST' OR p_parent_change_id IS DISTINCT FROM p_repair_for) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 parent_ids:=ARRAY(SELECT DISTINCT x FROM unnest(ARRAY[p_parent_change_id,p_repair_for]) AS u(x)
  WHERE x IS NOT NULL ORDER BY x);
 PERFORM change_ledger.private_writer_take_global_fences_v1(
  ARRAY['record-change-id:v1:'||pg_catalog.lower(p_change_id::text)]||
  ARRAY(SELECT 'record-change-id:v1:'||pg_catalog.lower(x::text) FROM unnest(parent_ids) AS u(x))
 );
 -- Preserve the source target/entitlement error precedence using non-locking reads, so a
 -- cross-scope global-ID refusal does not reveal anything to an ineligible requester.
 SELECT x.status,x.epoch,x.organization_ref,x.permission_expires_at
  INTO pre_tgt_status,pre_tgt_epoch,pre_tgt_org,pre_tgt_exp FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base_fingerprint;
 IF NOT FOUND THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF pre_tgt_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF pre_tgt_org IS DISTINCT FROM p_organization_ref THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF pre_tgt_exp IS NOT NULL AND pre_tgt_exp<=pg_catalog.clock_timestamp() THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,p_requester,'requester');
 -- Caller-selected change IDs are global. Reject an ID owned by another scope before
 -- locking the requested target row; the advisory fence makes this check race-safe.
 IF EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=p_change_id
    AND (r.tenant_id IS DISTINCT FROM t OR r.company_id IS DISTINCT FROM c)) THEN
  RAISE EXCEPTION 'CHANGE_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 -- Re-read under the target row lock after the global-ID check and reject a stale preflight.
 SELECT x.status,x.epoch,x.organization_ref,x.permission_expires_at
  INTO tgt_status,tgt_epoch,tgt_org,tgt_exp FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base_fingerprint FOR SHARE;
 IF NOT FOUND OR tgt_status IS DISTINCT FROM pre_tgt_status OR tgt_epoch IS DISTINCT FROM pre_tgt_epoch
   OR tgt_org IS DISTINCT FROM pre_tgt_org OR tgt_exp IS DISTINCT FROM pre_tgt_exp THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tgt_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_org IS DISTINCT FROM p_organization_ref THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_exp IS NOT NULL AND tgt_exp<=pg_catalog.clock_timestamp() THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 SELECT * INTO existing FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.requester=p_requester AND r.kind=p_kind
   AND r.base_fingerprint=p_base_fingerprint AND r.organization_ref=p_organization_ref
   AND r.request_id=p_request_id;
 IF FOUND THEN
  IF existing.payload_digest IS DISTINCT FROM p_payload_digest THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT'; END IF;
  RETURN existing.change_id;
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=p_change_id) THEN
  RAISE EXCEPTION 'CHANGE_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF pg_catalog.cardinality(parent_ids)>0 THEN
  SELECT pg_catalog.count(*) INTO parent_count FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(parent_ids);
  IF parent_count<>pg_catalog.cardinality(parent_ids) THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
  PERFORM 1 FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(parent_ids)
   ORDER BY r.change_id FOR KEY SHARE;
 END IF;
 BEGIN
  INSERT INTO change_ledger.records(
   change_id,tenant_id,company_id,base_fingerprint,organization_ref,kind,requester,request_id,
   payload_digest,target_ref,target_version,parent_change_id,repair_for,auth_epoch_at_proposal,expires_at,
   epoch_dependencies,requester_session
  ) VALUES(p_change_id,t,c,p_base_fingerprint,p_organization_ref,p_kind,p_requester,p_request_id,
   p_payload_digest,p_target_ref,p_target_version,p_parent_change_id,p_repair_for,tgt_epoch,p_expires_at,
   pg_catalog.jsonb_build_object(
    'target:'||p_base_fingerprint,change_ledger.epoch_value(t,c,'target:'||p_base_fingerprint),
    'principal:'||p_requester,change_ledger.epoch_value(t,c,'principal:'||p_requester)),
   session_user::text);
 EXCEPTION WHEN unique_violation THEN
  SELECT * INTO existing FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.requester=p_requester AND r.kind=p_kind
    AND r.base_fingerprint=p_base_fingerprint AND r.organization_ref=p_organization_ref
    AND r.request_id=p_request_id;
  IF FOUND AND existing.payload_digest IS NOT DISTINCT FROM p_payload_digest THEN
   RETURN existing.change_id;
  END IF;
  RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
 END;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PROPOSED',
  pg_catalog.jsonb_build_object('kind',p_kind,'payload_digest',p_payload_digest));
 RETURN p_change_id;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.add_role_scope(p_role text,t text,c text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF NOT pg_catalog.pg_has_role(change_ledger.caller_role()::name,'ledger_owner','USAGE') THEN
  RAISE EXCEPTION 'NOT_OWNER';
 END IF;
 IF p_role IS NULL OR p_role='' OR t IS NULL OR t='' OR c IS NULL OR c='' THEN
  RAISE EXCEPTION 'INVALID_ARGUMENT';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=p_role) THEN
  RAISE EXCEPTION 'ROLE_NOT_FOUND';
 END IF;

 -- Preserve the source API's owner/argument/role error precedence, then serialize the
 -- unique role_scope key with the common scope order before PostgreSQL arbitration.
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id)
  VALUES(p_role,t,c) ON CONFLICT(role_name,tenant_id,company_id) DO NOTHING;
END $fn$;

CREATE OR REPLACE FUNCTION change_ledger.check_anchor(t text,c text,p_ext_seq bigint,p_ext_head_hash text)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.check_anchor_v1($1,$2,$3,$4)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.require_dispatch_receipt(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.require_dispatch_receipt_v1($1,$2,$3,$4)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.attach_permit_signature(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_signature text
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.attach_permit_signature_v1($1,$2,$3,$4,$5,$6)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.record_dispatch_receipt(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_received_sha text,
 p_new_version text,p_signature text
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.record_dispatch_receipt_v1(
  $1,$2,$3,$4,$5,$6,$7,$8,pg_catalog.gen_random_uuid())
$fn$;

CREATE FUNCTION change_ledger.record_dispatch_receipt(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_received_sha text,
 p_new_version text,p_signature text,p_receipt_id uuid
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.record_dispatch_receipt_v1(
  $1,$2,$3,$4,$5,$6,$7,$8,$9)
$fn$;

CREATE OR REPLACE FUNCTION change_ledger.verify_dispatch_payload(
 t text,c text,p_change_id uuid,p_generation bigint,p_payload text
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.verify_dispatch_payload_v1(
  $1,$2,$3,$4,$5,pg_catalog.gen_random_uuid())
$fn$;

CREATE FUNCTION change_ledger.verify_dispatch_payload(
 t text,c text,p_change_id uuid,p_generation bigint,p_payload text,p_verification_id uuid
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.verify_dispatch_payload_v1($1,$2,$3,$4,$5,$6)
$fn$;

ALTER FUNCTION change_ledger.private_writer_assert_base_scope_limit_v1(text,text,text) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.private_writer_assert_base_scope_limit_v1(text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
ALTER FUNCTION change_ledger.record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text,uuid)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text,uuid)
 FROM PUBLIC;
GRANT EXECUTE ON FUNCTION change_ledger.record_dispatch_receipt(
 text,text,uuid,bigint,text,text,text,text,uuid) TO writer_role,requester_role;
ALTER FUNCTION change_ledger.verify_dispatch_payload(text,text,uuid,bigint,text,uuid)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.verify_dispatch_payload(text,text,uuid,bigint,text,uuid)
 FROM PUBLIC;
GRANT EXECUTE ON FUNCTION change_ledger.verify_dispatch_payload(
 text,text,uuid,bigint,text,uuid) TO writer_role,requester_role;

 $forward$;
 END IF;
END $mig$;
COMMIT;

