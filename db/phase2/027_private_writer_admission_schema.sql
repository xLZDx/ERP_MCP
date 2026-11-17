-- S13 private-writer durable admission schema.
-- Candidate only: do not apply until coding, tests and source/security review are complete.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('027', ARRAY['001','002','003','004','005','006','007','008','009',
   '010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026']) THEN
 EXECUTE $body$

-- The S13 admission path verifies an external checkpoint row before it can close a
-- stop-effects hold. Existing historical rows are retained but are not retroactively trusted.
ALTER TABLE change_ledger.checkpoints
 ADD COLUMN IF NOT EXISTS verified boolean NOT NULL DEFAULT false;

DO $roles$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='ledger_owner')
    OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='ledger_owner'
       AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole)) THEN
  RAISE EXCEPTION 'LEDGER_ROLE_UNSAFE';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
    WHERE m.roleid=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname='ledger_owner')
       OR m.member=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname='ledger_owner')) THEN
  RAISE EXCEPTION 'LEDGER_ROLE_MEMBERSHIP_UNSAFE';
 END IF;
 -- Migration 004 creates this non-login owner without an explicit NOINHERIT clause, so fresh
 -- PostgreSQL clusters retain the server default INHERIT. Tighten the known-safe role only after
 -- rejecting unexpected privileges and all role memberships.
 ALTER ROLE ledger_owner NOINHERIT;
 IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='ledger_owner' AND rolinherit) THEN
  RAISE EXCEPTION 'LEDGER_ROLE_UNSAFE';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='business_ai_private_writer') THEN
  CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
 ELSIF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='business_ai_private_writer'
       AND (NOT rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole
            OR rolreplication OR rolinherit)) THEN
  RAISE EXCEPTION 'PRIVATE_WRITER_ROLE_UNSAFE';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='private_writer_evidence_ingest') THEN
  CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
 ELSIF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='private_writer_evidence_ingest'
       AND (NOT rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole
            OR rolreplication OR rolinherit)) THEN
  RAISE EXCEPTION 'EVIDENCE_INGEST_ROLE_UNSAFE';
 END IF;
 IF pg_catalog.pg_has_role('business_ai_private_writer','ledger_owner','MEMBER')
    OR pg_catalog.pg_has_role('private_writer_evidence_ingest','ledger_owner','MEMBER') THEN
  RAISE EXCEPTION 'PRIVATE_WRITER_ROLE_MEMBERSHIP_UNSAFE';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
    WHERE m.member IN (SELECT oid FROM pg_catalog.pg_roles
                       WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))) THEN
  RAISE EXCEPTION 'PRIVATE_WRITER_ROLE_HAS_MEMBERSHIP';
 END IF;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
     WHERE m.roleid IN (SELECT oid FROM pg_catalog.pg_roles
                        WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))) THEN
   RAISE EXCEPTION 'PRIVATE_WRITER_ROLE_HAS_UNEXPECTED_MEMBER';
  END IF;
 -- ACL revokes cannot remove the implicit rights of an object owner. These login roles are
 -- service principals, never object owners; reject pre-provisioned ownership instead of silently
 -- changing ownership or allowing a private writer to retain DDL authority.
 IF EXISTS (
   SELECT 1 FROM pg_catalog.pg_database d
    WHERE d.datname=pg_catalog.current_database()
      AND d.datdba IN (SELECT oid FROM pg_catalog.pg_roles
                       WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_namespace n
    WHERE n.nspowner IN (SELECT oid FROM pg_catalog.pg_roles
                         WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_class c
    WHERE c.relowner IN (SELECT oid FROM pg_catalog.pg_roles
                         WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_proc p
    WHERE p.proowner IN (SELECT oid FROM pg_catalog.pg_roles
                         WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_type t
    WHERE t.typowner IN (SELECT oid FROM pg_catalog.pg_roles
                         WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_extension e
    WHERE e.extowner IN (SELECT oid FROM pg_catalog.pg_roles
                         WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_largeobject_metadata l
    WHERE l.lomowner IN (SELECT oid FROM pg_catalog.pg_roles
                         WHERE rolname IN ('business_ai_private_writer','private_writer_evidence_ingest'))
 ) THEN
  RAISE EXCEPTION 'PRIVATE_WRITER_ROLE_OWNS_OBJECT';
 END IF;
 -- NOCREATEDB controls database creation, not schema creation inside this database. Remove
 -- any direct database CREATE grant from the two login roles and fail closed if PUBLIC or
 -- another grant path still gives either role effective CREATE.
 EXECUTE format('REVOKE CREATE ON DATABASE %I FROM business_ai_private_writer,private_writer_evidence_ingest',
                pg_catalog.current_database());
 IF pg_catalog.has_database_privilege('business_ai_private_writer',pg_catalog.current_database(),'CREATE')
    OR pg_catalog.has_database_privilege('private_writer_evidence_ingest',pg_catalog.current_database(),'CREATE') THEN
  RAISE EXCEPTION 'PRIVATE_WRITER_DATABASE_CREATE_UNSAFE';
 END IF;
END $roles$;

-- Default ACL REVOKE must be global: PostgreSQL adds schema-specific defaults to global
-- defaults, so an IN SCHEMA REVOKE cannot cancel a grant already supplied globally. ledger_owner
-- is the non-login owner dedicated to the private change_ledger schema; future objects it creates
-- must not become PUBLIC or private-role entry points by default.
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner REVOKE ALL ON TABLES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner REVOKE ALL ON SEQUENCES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner REVOKE EXECUTE ON ROUTINES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner REVOKE USAGE ON TYPES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
-- Schema-local default ACLs are additive to the global defaults above. Normalize both
-- layers so an older change_ledger-specific grant cannot reintroduce PUBLIC/private access.
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner IN SCHEMA change_ledger REVOKE ALL ON TABLES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner IN SCHEMA change_ledger REVOKE ALL ON SEQUENCES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner IN SCHEMA change_ledger REVOKE EXECUTE ON ROUTINES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner IN SCHEMA change_ledger REVOKE USAGE ON TYPES
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;

CREATE TABLE change_ledger.private_writer_service_bindings (
 "session_user" name PRIMARY KEY,
 base_fingerprint text NOT NULL UNIQUE CHECK (base_fingerprint<>'' AND base_fingerprint=btrim(base_fingerprint)),
 writer_service_id text NOT NULL CHECK (writer_service_id<>'' AND writer_service_id=btrim(writer_service_id)),
 writer_host_id text NOT NULL CHECK (writer_host_id<>'' AND writer_host_id=btrim(writer_host_id)),
 binding_enabled boolean NOT NULL DEFAULT true CHECK (binding_enabled=true),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 revoked_at timestamptz NULL,
 UNIQUE("session_user",base_fingerprint,writer_service_id,writer_host_id,binding_enabled),
 UNIQUE(writer_service_id,base_fingerprint),
 CHECK(revoked_at IS NULL OR revoked_at>=created_at)
);

CREATE TABLE change_ledger.private_writer_serving_fences (
 writer_service_id text NOT NULL,
 base_fingerprint text NOT NULL CHECK(base_fingerprint<>'' AND base_fingerprint=btrim(base_fingerprint)),
 "session_user" name NOT NULL,
 writer_host_id text NOT NULL,
 binding_enabled boolean NOT NULL DEFAULT true CHECK(binding_enabled=true),
 service_instance_id text NOT NULL CHECK(service_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 service_epoch bigint NOT NULL CHECK(service_epoch>0),
 started_at timestamptz NOT NULL,
 readiness_ref uuid NULL
  CHECK(readiness_ref IS NULL OR readiness_ref<>'00000000-0000-0000-0000-000000000000'::uuid),
 PRIMARY KEY(writer_service_id,base_fingerprint),
 UNIQUE("session_user",base_fingerprint,service_instance_id,service_epoch),
 FOREIGN KEY("session_user",base_fingerprint,writer_service_id,writer_host_id,binding_enabled)
  REFERENCES change_ledger.private_writer_service_bindings
   ("session_user",base_fingerprint,writer_service_id,writer_host_id,binding_enabled)
);

CREATE TABLE change_ledger.private_writer_service_instance_history (
 writer_service_id text NOT NULL,
 base_fingerprint text NOT NULL,
 service_instance_id text NOT NULL CHECK(service_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 service_epoch bigint NOT NULL CHECK(service_epoch>0),
 first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(writer_service_id,base_fingerprint,service_instance_id),
 UNIQUE(writer_service_id,base_fingerprint,service_epoch),
 FOREIGN KEY(writer_service_id,base_fingerprint)
  REFERENCES change_ledger.private_writer_service_bindings(writer_service_id,base_fingerprint)
);

CREATE FUNCTION change_ledger.private_writer_service_binding_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF ROW(NEW."session_user",NEW.base_fingerprint,NEW.writer_service_id,NEW.writer_host_id,
   NEW.binding_enabled,NEW.created_at)
  IS DISTINCT FROM ROW(OLD."session_user",OLD.base_fingerprint,OLD.writer_service_id,OLD.writer_host_id,
   OLD.binding_enabled,OLD.created_at) OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL THEN
  RAISE EXCEPTION 'IMMUTABLE_RECORD';
 END IF;
 NEW.revoked_at:=clock_timestamp();
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_service_binding_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_service_binding_guard
 BEFORE UPDATE OR DELETE ON change_ledger.private_writer_service_bindings
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_service_binding_guard_v1();

CREATE FUNCTION change_ledger.private_writer_serving_fence_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF ROW(NEW.writer_service_id,NEW.base_fingerprint,NEW."session_user",NEW.writer_host_id,NEW.binding_enabled)
  IS DISTINCT FROM ROW(OLD.writer_service_id,OLD.base_fingerprint,OLD."session_user",OLD.writer_host_id,
   OLD.binding_enabled) THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF NEW.service_epoch=OLD.service_epoch THEN
  IF NEW.service_instance_id IS DISTINCT FROM OLD.service_instance_id
    OR NEW.started_at IS DISTINCT FROM OLD.started_at
    OR (OLD.readiness_ref IS NOT NULL AND NEW.readiness_ref IS NOT NULL
        AND NEW.readiness_ref IS DISTINCT FROM OLD.readiness_ref) THEN
   RAISE EXCEPTION 'STALE_EPOCH';
  END IF;
 ELSE
  IF NEW.service_epoch<>OLD.service_epoch+1 OR NEW.service_instance_id=OLD.service_instance_id
    OR NEW.started_at<OLD.started_at OR NEW.readiness_ref IS NOT NULL THEN
   RAISE EXCEPTION 'STALE_EPOCH';
  END IF;
 END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_serving_fence_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_serving_fence_guard
 BEFORE UPDATE OR DELETE ON change_ledger.private_writer_serving_fences
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_serving_fence_guard_v1();

CREATE TABLE change_ledger.private_writer_signer_key_versions (
 key_id text NOT NULL CHECK(key_id<>'' AND key_id=btrim(key_id) AND length(key_id)<=128),
 key_version text NOT NULL CHECK(key_version<>'' AND key_version=btrim(key_version) AND length(key_version)<=64),
 public_key bytea NOT NULL CHECK(octet_length(public_key)=32),
 signer_role text NOT NULL CHECK(signer_role IN
  ('writer_receipt','verification_worker','completion_supervisor','read_attestor','checkpoint_signer')),
 service_id text NOT NULL CHECK(service_id<>'' AND service_id=btrim(service_id) AND length(service_id)<=128),
 host_id text NOT NULL CHECK(host_id<>'' AND host_id=btrim(host_id) AND length(host_id)<=128),
 valid_from timestamptz NOT NULL,
 valid_until timestamptz NOT NULL CHECK(valid_until>valid_from),
 registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(key_id,key_version),
 UNIQUE(public_key),
 UNIQUE(key_id,key_version,signer_role,service_id,host_id)
);

CREATE TABLE change_ledger.private_writer_signer_key_scopes (
 key_id text NOT NULL,
 key_version text NOT NULL,
 tenant_id text NOT NULL CHECK(tenant_id<>'' AND tenant_id=btrim(tenant_id) AND length(tenant_id)<=128),
 company_id text NOT NULL CHECK(company_id<>'' AND company_id=btrim(company_id) AND length(company_id)<=128),
 organization_ref text NOT NULL CHECK(organization_ref<>'' AND organization_ref=btrim(organization_ref) AND length(organization_ref)<=128),
 base_fingerprint text NOT NULL CHECK(base_fingerprint ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(key_id,key_version,tenant_id,company_id,organization_ref,base_fingerprint),
 FOREIGN KEY(key_id,key_version) REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version)
);

CREATE TABLE change_ledger.private_writer_signer_key_revocations (
 key_id text NOT NULL,
 key_version text NOT NULL,
 revoked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 reason_code text NOT NULL CHECK(reason_code IN ('ROTATION','COMPROMISE','ADMINISTRATIVE')),
 recorded_by name NOT NULL DEFAULT session_user,
 PRIMARY KEY(key_id,key_version),
 FOREIGN KEY(key_id,key_version) REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version)
);

CREATE TABLE change_ledger.private_writer_signer_key_rotations (
 predecessor_key_id text NOT NULL,
 predecessor_key_version text NOT NULL,
 successor_key_id text NOT NULL,
 successor_key_version text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(predecessor_key_id,predecessor_key_version),
 UNIQUE(successor_key_id,successor_key_version),
 CHECK((predecessor_key_id,predecessor_key_version)<>(successor_key_id,successor_key_version)),
 FOREIGN KEY(predecessor_key_id,predecessor_key_version)
  REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version),
 FOREIGN KEY(successor_key_id,successor_key_version)
  REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version)
);

CREATE TABLE change_ledger.private_writer_trust_registry_revision (
 revision_id smallint PRIMARY KEY CHECK(revision_id=1),
 revision bigint NOT NULL CHECK(revision>0),
 changed_at timestamptz NOT NULL
);
INSERT INTO change_ledger.private_writer_trust_registry_revision(revision_id,revision,changed_at)
 VALUES(1,1,pg_catalog.clock_timestamp());

CREATE TABLE change_ledger.private_writer_process_attestations (
 process_instance_id uuid PRIMARY KEY CHECK(process_instance_id::text ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 host_boot_id uuid NOT NULL CHECK(host_boot_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 service_id text NOT NULL CHECK(service_id<>'' AND service_id=btrim(service_id) AND length(service_id)<=128),
 host_id text NOT NULL CHECK(host_id<>'' AND host_id=btrim(host_id) AND length(host_id)<=128),
 os_pid integer NOT NULL CHECK(os_pid>0),
 process_created_at timestamptz NOT NULL,
 supervisor_key_id text NOT NULL CHECK(supervisor_key_id<>'' AND supervisor_key_id=btrim(supervisor_key_id) AND length(supervisor_key_id)<=128),
 supervisor_key_version text NOT NULL CHECK(supervisor_key_version<>'' AND supervisor_key_version=btrim(supervisor_key_version) AND length(supervisor_key_version)<=64),
 signature bytea NOT NULL CHECK(octet_length(signature)=64),
 recorded_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
 FOREIGN KEY(supervisor_key_id,supervisor_key_version)
  REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version)
);

CREATE TABLE change_ledger.private_writer_oracle_artifacts (
 tenant_id text NOT NULL CHECK(tenant_id<>'' AND tenant_id=btrim(tenant_id) AND length(tenant_id)<=128),
 company_id text NOT NULL CHECK(company_id<>'' AND company_id=btrim(company_id) AND length(company_id)<=128),
 organization_ref text NOT NULL CHECK(organization_ref<>'' AND organization_ref=btrim(organization_ref) AND length(organization_ref)<=128),
 base_fingerprint text NOT NULL CHECK(base_fingerprint ~ '^[0-9a-f]{64}$'),
 operation_kind text NOT NULL CHECK(operation_kind IN ('CREATE_DRAFT','POST','UNPOST')),
 oracle_id text NOT NULL CHECK(oracle_id<>'' AND oracle_id=btrim(oracle_id) AND length(oracle_id)<=128),
 oracle_version text NOT NULL CHECK(oracle_version<>'' AND oracle_version=btrim(oracle_version) AND length(oracle_version)<=64),
 document_shape_revision text NOT NULL CHECK(document_shape_revision<>'' AND document_shape_revision=btrim(document_shape_revision) AND length(document_shape_revision)<=128),
 configuration_fingerprint text NOT NULL CHECK(configuration_fingerprint ~ '^[0-9a-f]{64}$'),
 oracle_digest text NOT NULL CHECK(oracle_digest ~ '^[0-9a-f]{64}$'),
 query_plan_digest text NOT NULL CHECK(query_plan_digest ~ '^[0-9a-f]{64}$'),
 expected_effect_schema_version text NOT NULL CHECK(expected_effect_schema_version<>'' AND expected_effect_schema_version=btrim(expected_effect_schema_version) AND length(expected_effect_schema_version)<=64),
 recorded_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,organization_ref,base_fingerprint,operation_kind,oracle_id,oracle_version)
);

CREATE TABLE change_ledger.private_writer_outcome_version_floors (
 tenant_id text NOT NULL CHECK(tenant_id<>'' AND tenant_id=btrim(tenant_id) AND length(tenant_id)<=128),
 company_id text NOT NULL CHECK(company_id<>'' AND company_id=btrim(company_id) AND length(company_id)<=128),
 organization_ref text NOT NULL CHECK(organization_ref<>'' AND organization_ref=btrim(organization_ref) AND length(organization_ref)<=128),
 base_fingerprint text NOT NULL CHECK(base_fingerprint ~ '^[0-9a-f]{64}$'),
 operation_kind text NOT NULL CHECK(operation_kind IN ('CREATE_DRAFT','POST','UNPOST')),
 minimum_version smallint NOT NULL CHECK(minimum_version IN (1,2,3)),
 policy_revision bigint NOT NULL CHECK(policy_revision>0),
 changed_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
 PRIMARY KEY(tenant_id,company_id,organization_ref,base_fingerprint,operation_kind)
);

CREATE FUNCTION change_ledger.private_writer_bump_trust_revision_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 UPDATE change_ledger.private_writer_trust_registry_revision
  SET revision=revision+1,changed_at=pg_catalog.clock_timestamp() WHERE revision_id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'TRUST_REGISTRY_REVISION_UNAVAILABLE'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_bump_trust_revision_v1() OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_trust_revision_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF TG_OP IN ('INSERT','DELETE') THEN
  RAISE EXCEPTION 'IMMUTABLE_TRUST_REVISION';
 END IF;
 IF NEW.revision IS DISTINCT FROM OLD.revision+1 THEN
  RAISE EXCEPTION 'TRUST_REVISION_STEP_INVALID';
 END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_trust_revision_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_trust_revision_guard
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_trust_registry_revision
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_trust_revision_guard_v1();

-- Serialize every trust-registry mutation before it can lock or change a registry row.
CREATE FUNCTION change_ledger.private_writer_lock_trust_revision_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE current_revision bigint;
BEGIN
 SELECT revision INTO current_revision
  FROM change_ledger.private_writer_trust_registry_revision
  WHERE revision_id=1 FOR UPDATE;
 IF NOT FOUND OR current_revision<=0 THEN
  RAISE EXCEPTION 'TRUST_REGISTRY_REVISION_UNAVAILABLE';
 END IF;
 RETURN NULL;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_lock_trust_revision_v1() OWNER TO ledger_owner;

CREATE TRIGGER private_writer_trust_lock_key
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_versions
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();
CREATE TRIGGER private_writer_trust_lock_scope
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_scopes
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();
CREATE TRIGGER private_writer_trust_lock_revocation
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_revocations
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();
CREATE TRIGGER private_writer_trust_lock_rotation
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_rotations
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();
CREATE TRIGGER private_writer_trust_lock_process
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_process_attestations
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();
CREATE TRIGGER private_writer_trust_lock_oracle
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_oracle_artifacts
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();
CREATE TRIGGER private_writer_trust_lock_outcome_policy
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_outcome_version_floors
 FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.private_writer_lock_trust_revision_v1();

CREATE TRIGGER private_writer_trust_revision_key
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_versions
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();
CREATE TRIGGER private_writer_trust_revision_scope
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_scopes
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();
CREATE TRIGGER private_writer_trust_revision_revocation
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_revocations
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();
CREATE TRIGGER private_writer_trust_revision_rotation
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_signer_key_rotations
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();
CREATE TRIGGER private_writer_trust_revision_process
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_process_attestations
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();
CREATE TRIGGER private_writer_trust_revision_oracle
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_oracle_artifacts
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();
CREATE TRIGGER private_writer_trust_revision_outcome_policy
 AFTER INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_outcome_version_floors
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_bump_trust_revision_v1();

CREATE FUNCTION change_ledger.private_writer_resolve_signer_key_v1(
 p_key_id text,p_key_version text,p_signer_role text,p_service_id text,p_host_id text,
 p_tenant_id text,p_company_id text,p_organization_ref text,p_base_fingerprint text,
 p_signed_at timestamptz
) RETURNS bytea
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE k change_ledger.private_writer_signer_key_versions%ROWTYPE; key_material bytea;
        resolved_at timestamptz;
BEGIN
 IF SESSION_USER<>'private_writer_evidence_ingest' OR p_key_id IS NULL OR p_key_id=''
   OR p_key_version IS NULL OR p_key_version='' OR p_signer_role IS NULL OR p_service_id IS NULL
   OR p_service_id='' OR p_host_id IS NULL OR p_host_id='' OR p_tenant_id IS NULL OR p_tenant_id=''
   OR p_company_id IS NULL OR p_company_id='' OR p_organization_ref IS NULL OR p_organization_ref=''
   OR p_base_fingerprint IS NULL OR p_base_fingerprint !~ '^[0-9a-f]{64}$' OR p_signed_at IS NULL THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'EVIDENCE_KEY_TRANSACTION_INVALID' USING ERRCODE='P0001';
 END IF;
  -- First read only the material needed to choose the shared trust-key fence. Re-read all
  -- authorization and revocation predicates after acquiring it, so resolution serializes with
  -- key revocation without returning a stale pre-fence snapshot.
  SELECT v.public_key INTO key_material FROM change_ledger.private_writer_signer_key_versions v
   WHERE v.key_id=p_key_id AND v.key_version=p_key_version;
  IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_KEY_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(encode(key_material,'hex'),17017));
  -- Validation time is sampled after any wait for a concurrent revocation to finish.
  resolved_at:=pg_catalog.clock_timestamp();
 SELECT v.* INTO k
  FROM change_ledger.private_writer_signer_key_versions v
  JOIN change_ledger.private_writer_signer_key_scopes s
    ON s.key_id=v.key_id AND s.key_version=v.key_version
  WHERE v.key_id=p_key_id AND v.key_version=p_key_version AND v.signer_role=p_signer_role
    AND v.service_id=p_service_id AND v.host_id=p_host_id
    AND s.tenant_id=p_tenant_id AND s.company_id=p_company_id
    AND s.organization_ref=p_organization_ref AND s.base_fingerprint=p_base_fingerprint
    AND v.valid_from<=p_signed_at AND p_signed_at<v.valid_until
    AND v.valid_from<=resolved_at AND resolved_at<v.valid_until
    AND p_signed_at<=resolved_at
    AND NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=v.key_id AND r.key_version=v.key_version AND r.revoked_at<=resolved_at);
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_KEY_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 RETURN k.public_key;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_resolve_signer_key_v1(
 text,text,text,text,text,text,text,text,text,timestamptz) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_load_trust_snapshot_v1(
 p_tenant_id text,p_company_id text,p_organization_ref text,p_base_fingerprint text,
 p_operation_kind text,p_signer_key_ids text[],p_signer_key_versions text[],
 p_process_instance_ids uuid[],p_oracle_id text,p_oracle_version text,
 p_include_operation_oracle_policy boolean
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE registry_revision bigint; loaded timestamptz:=pg_catalog.clock_timestamp();
        signer_docs jsonb; process_docs jsonb; oracle_docs jsonb; floor_docs jsonb;
BEGIN
 IF SESSION_USER<>'private_writer_evidence_ingest' THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
  IF current_setting('transaction_isolation')<>'repeatable read'
    OR current_setting('transaction_read_only')<>'on' THEN
   RAISE EXCEPTION 'TRUST_SNAPSHOT_TRANSACTION_INVALID' USING ERRCODE='P0001';
  END IF;
 IF p_process_instance_ids IS NOT NULL
   AND (array_position(p_process_instance_ids,'00000000-0000-0000-0000-000000000000'::uuid) IS NOT NULL
     OR EXISTS(SELECT 1 FROM unnest(p_process_instance_ids) AS x(process_id)
       WHERE process_id::text !~
        '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')) THEN
  RAISE EXCEPTION 'TRUST_SNAPSHOT_REQUEST_INVALID' USING ERRCODE='P0001';
 END IF;
 IF p_tenant_id IS NULL OR p_tenant_id='' OR p_tenant_id<>btrim(p_tenant_id)
   OR p_company_id IS NULL OR p_company_id='' OR p_company_id<>btrim(p_company_id)
   OR p_organization_ref IS NULL OR p_organization_ref='' OR p_organization_ref<>btrim(p_organization_ref)
   OR p_base_fingerprint IS NULL OR p_base_fingerprint !~ '^[0-9a-f]{64}$'
   OR p_operation_kind IS NULL OR p_operation_kind NOT IN ('CREATE_DRAFT','POST','UNPOST')
   OR p_signer_key_ids IS NULL OR p_signer_key_versions IS NULL
   OR cardinality(p_signer_key_ids)<1 OR cardinality(p_signer_key_ids)>16
   OR cardinality(p_signer_key_ids)<>cardinality(p_signer_key_versions)
   OR array_position(p_signer_key_ids,NULL) IS NOT NULL
   OR array_position(p_signer_key_versions,NULL) IS NOT NULL
   OR EXISTS(SELECT 1 FROM unnest(p_signer_key_ids,p_signer_key_versions) AS x(key_id,key_version)
     WHERE key_id='' OR key_id<>btrim(key_id) OR length(key_id)>128
        OR key_version='' OR key_version<>btrim(key_version) OR length(key_version)>64)
   OR p_process_instance_ids IS NULL OR cardinality(p_process_instance_ids)>16
   OR array_position(p_process_instance_ids,NULL) IS NOT NULL
   OR p_include_operation_oracle_policy IS NULL
   OR (p_include_operation_oracle_policy AND p_oracle_id IS NOT NULL)
   OR ((p_oracle_id IS NULL)<>(p_oracle_version IS NULL))
   OR (p_oracle_id IS NOT NULL AND (p_oracle_id='' OR p_oracle_id<>btrim(p_oracle_id)
       OR p_oracle_version='' OR p_oracle_version<>btrim(p_oracle_version))) THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF (SELECT count(*) FROM (SELECT DISTINCT key_id,key_version
       FROM unnest(p_signer_key_ids,p_signer_key_versions) AS x(key_id,key_version)) q)
       <>cardinality(p_signer_key_ids)
   OR (SELECT count(DISTINCT process_id) FROM unnest(p_process_instance_ids) AS x(process_id))
       <>cardinality(p_process_instance_ids) THEN
  RAISE EXCEPTION 'TRUST_SNAPSHOT_REQUEST_INVALID' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions
   WHERE signer_role IN ('writer_receipt','verification_worker','completion_supervisor',
                         'read_attestor','checkpoint_signer')
   GROUP BY service_id HAVING count(DISTINCT signer_role)>1) THEN
  RAISE EXCEPTION 'TRUST_REGISTRY_SERVICE_COLLISION' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(SELECT 1 FROM unnest(p_signer_key_ids,p_signer_key_versions) AS req(key_id,key_version)
   LEFT JOIN change_ledger.private_writer_signer_key_versions v
    ON v.key_id=req.key_id AND v.key_version=req.key_version
   LEFT JOIN change_ledger.private_writer_signer_key_scopes s
    ON s.key_id=req.key_id AND s.key_version=req.key_version
     AND s.tenant_id=p_tenant_id AND s.company_id=p_company_id
     AND s.organization_ref=p_organization_ref AND s.base_fingerprint=p_base_fingerprint
   WHERE v.key_id IS NULL OR s.key_id IS NULL) THEN
  RAISE EXCEPTION 'TRUST_SIGNER_SCOPE_UNAVAILABLE' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(SELECT 1 FROM unnest(p_process_instance_ids) AS req(process_id)
   LEFT JOIN change_ledger.private_writer_process_attestations a
    ON a.process_instance_id=req.process_id WHERE a.process_instance_id IS NULL) THEN
  RAISE EXCEPTION 'TRUST_PROCESS_BINDING_UNAVAILABLE' USING ERRCODE='P0001';
 END IF;
 SELECT revision INTO registry_revision FROM change_ledger.private_writer_trust_registry_revision
  WHERE revision_id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'TRUST_REGISTRY_REVISION_UNAVAILABLE' USING ERRCODE='P0001'; END IF;

 WITH RECURSIVE
 roots(key_id,key_version) AS (
  SELECT x.key_id,x.key_version FROM unnest(p_signer_key_ids,p_signer_key_versions) AS x(key_id,key_version)
  UNION
  SELECT a.supervisor_key_id,a.supervisor_key_version
   FROM change_ledger.private_writer_process_attestations a
   WHERE a.process_instance_id=ANY(p_process_instance_ids)
 ),
 walk(root_key_id,root_key_version,key_id,key_version,depth) AS (
  SELECT r.key_id,r.key_version,r.key_id,r.key_version,0 FROM roots r
  UNION ALL
  SELECT w.root_key_id,w.root_key_version,r.predecessor_key_id,r.predecessor_key_version,w.depth+1
   FROM walk w JOIN change_ledger.private_writer_signer_key_rotations r
    ON r.successor_key_id=w.key_id AND r.successor_key_version=w.key_version
   WHERE w.depth<128
 ),
 all_keys(key_id,key_version) AS (
  SELECT DISTINCT key_id,key_version FROM walk
 ),
 histories(start_key_id,start_key_version,key_id,key_version,depth) AS (
  SELECT k.key_id,k.key_version,k.key_id,k.key_version,0 FROM all_keys k
  UNION ALL
  SELECT h.start_key_id,h.start_key_version,r.predecessor_key_id,r.predecessor_key_version,h.depth+1
   FROM histories h JOIN change_ledger.private_writer_signer_key_rotations r
    ON r.successor_key_id=h.key_id AND r.successor_key_version=h.key_version
   WHERE h.depth<128
 )
 SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'key_id',v.key_id,'key_version',v.key_version,'public_key_hex',pg_catalog.encode(v.public_key,'hex'),
   'signer_role',v.signer_role,'service_id',v.service_id,'host_id',v.host_id,
   'valid_from',v.valid_from,'valid_until',v.valid_until,'revoked_at',rev.revoked_at,
   'allowed_scopes',COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'tenant_id',s.tenant_id,'company_id',s.company_id,'organization_ref',s.organization_ref,
     'base_fingerprint',s.base_fingerprint) ORDER BY s.tenant_id,s.company_id,
       s.organization_ref,s.base_fingerprint)
     FROM change_ledger.private_writer_signer_key_scopes s
     WHERE s.key_id=v.key_id AND s.key_version=v.key_version
       AND s.tenant_id=p_tenant_id AND s.company_id=p_company_id
       AND s.organization_ref=p_organization_ref AND s.base_fingerprint=p_base_fingerprint),'[]'::jsonb),
   'rotation_history',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'key_id',h.key_id,'key_version',h.key_version) ORDER BY h.depth DESC)
      FROM histories h WHERE h.start_key_id=v.key_id AND h.start_key_version=v.key_version)
  ) ORDER BY v.key_id,v.key_version)
  INTO signer_docs
  FROM all_keys k
  JOIN change_ledger.private_writer_signer_key_versions v
   ON v.key_id=k.key_id AND v.key_version=k.key_version
  LEFT JOIN change_ledger.private_writer_signer_key_revocations rev
   ON rev.key_id=v.key_id AND rev.key_version=v.key_version;
 IF signer_docs IS NULL OR (SELECT count(*) FROM pg_catalog.jsonb_array_elements(signer_docs))=0 THEN
  RAISE EXCEPTION 'TRUST_SIGNER_SCOPE_UNAVAILABLE' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(
  WITH RECURSIVE roots(key_id,key_version) AS (
   SELECT x.key_id,x.key_version FROM unnest(p_signer_key_ids,p_signer_key_versions) AS x(key_id,key_version)
   UNION SELECT a.supervisor_key_id,a.supervisor_key_version FROM change_ledger.private_writer_process_attestations a
    WHERE a.process_instance_id=ANY(p_process_instance_ids)
  ), walk(root_key_id,root_key_version,key_id,key_version,depth) AS (
   SELECT key_id,key_version,key_id,key_version,0 FROM roots
   UNION ALL SELECT w.root_key_id,w.root_key_version,r.predecessor_key_id,r.predecessor_key_version,w.depth+1
    FROM walk w JOIN change_ledger.private_writer_signer_key_rotations r
     ON r.successor_key_id=w.key_id AND r.successor_key_version=w.key_version WHERE w.depth<128
  ) SELECT 1 FROM walk WHERE depth=128
 ) THEN RAISE EXCEPTION 'TRUST_ROTATION_CHAIN_TOO_DEEP' USING ERRCODE='P0001'; END IF;

 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'process_instance_id',a.process_instance_id,'host_boot_id',a.host_boot_id,
   'service_id',a.service_id,'host_id',a.host_id,'os_pid',a.os_pid,
   'process_created_at',a.process_created_at,'supervisor_key_id',a.supervisor_key_id,
   'supervisor_key_version',a.supervisor_key_version,'signature_hex',pg_catalog.encode(a.signature,'hex')
  ) ORDER BY a.process_instance_id),'[]'::jsonb)
  INTO process_docs FROM change_ledger.private_writer_process_attestations a
  WHERE a.process_instance_id=ANY(p_process_instance_ids);

 -- A legacy v1 outcome has no oracle reference, so return the complete bounded set for
 -- this operation. Never truncate it: overflow must fail closed instead of hiding a v2 pin.
 IF p_include_operation_oracle_policy AND (
   SELECT count(*) FROM change_ledger.private_writer_oracle_artifacts o
    WHERE o.tenant_id=p_tenant_id AND o.company_id=p_company_id
      AND o.organization_ref=p_organization_ref AND o.base_fingerprint=p_base_fingerprint
      AND o.operation_kind=p_operation_kind
 )>16 THEN
  RAISE EXCEPTION 'TRUST_ORACLE_SET_TOO_LARGE' USING ERRCODE='P0001';
 END IF;

 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'tenant_id',o.tenant_id,'company_id',o.company_id,'organization_ref',o.organization_ref,
   'base_fingerprint',o.base_fingerprint,'operation_kind',o.operation_kind,'oracle_id',o.oracle_id,
   'oracle_version',o.oracle_version,'document_shape_revision',o.document_shape_revision,
   'configuration_fingerprint',o.configuration_fingerprint,'oracle_digest',o.oracle_digest,
   'expected_effect_schema_version',o.expected_effect_schema_version
  ) ORDER BY o.oracle_id,o.oracle_version),'[]'::jsonb)
  INTO oracle_docs FROM change_ledger.private_writer_oracle_artifacts o
  WHERE o.tenant_id=p_tenant_id AND o.company_id=p_company_id
   AND o.organization_ref=p_organization_ref AND o.base_fingerprint=p_base_fingerprint
   AND o.operation_kind=p_operation_kind
   AND ((p_include_operation_oracle_policy AND p_oracle_id IS NULL)
        OR (p_oracle_id IS NOT NULL AND o.oracle_id=p_oracle_id
            AND o.oracle_version=p_oracle_version));

 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'tenant_id',f.tenant_id,'company_id',f.company_id,'organization_ref',f.organization_ref,
   'base_fingerprint',f.base_fingerprint,'operation_kind',f.operation_kind,
   'minimum_version',f.minimum_version
  ) ORDER BY f.operation_kind),'[]'::jsonb)
  INTO floor_docs FROM change_ledger.private_writer_outcome_version_floors f
  WHERE f.tenant_id=p_tenant_id AND f.company_id=p_company_id
   AND f.organization_ref=p_organization_ref AND f.base_fingerprint=p_base_fingerprint
   AND f.operation_kind=p_operation_kind;

 RETURN pg_catalog.jsonb_build_object(
  'revision',registry_revision::text,'loaded_at',loaded,'signers',signer_docs,
  'process_bindings',process_docs,'oracle_artifacts',oracle_docs,
  'outcome_version_floors',floor_docs);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_load_trust_snapshot_v1(
 text,text,text,text,text,text[],text[],uuid[],text,text,boolean) OWNER TO ledger_owner;

CREATE TABLE change_ledger.private_writer_dispatch_intents (
 dispatch_intent_id uuid PRIMARY KEY CHECK(dispatch_intent_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 tenant_id text NOT NULL,
 company_id text NOT NULL,
 organization_ref text NOT NULL,
 base_fingerprint text NOT NULL,
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id)
  CHECK(change_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 claim_generation bigint NOT NULL CHECK(claim_generation>0),
 dispatch_generation bigint NOT NULL CHECK(dispatch_generation>0),
 call_id uuid NOT NULL UNIQUE CHECK(call_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 operation_kind text NOT NULL CHECK(operation_kind IN ('CREATE_DRAFT','POST','UNPOST')),
 approval_digest text NOT NULL CHECK(approval_digest ~ '^[a-f0-9]{64}$'),
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 target_ref text NULL,
 expected_pre_version text NULL,
 auth_epoch bigint NOT NULL CHECK(auth_epoch>0),
 repair_authorization_id uuid NULL
  CHECK(repair_authorization_id IS NULL OR
        repair_authorization_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(change_id,claim_generation),
 UNIQUE(change_id,dispatch_generation),
 UNIQUE(dispatch_intent_id,change_id,claim_generation,dispatch_generation,call_id,payload_digest),
 UNIQUE(dispatch_intent_id,change_id,claim_generation,dispatch_generation,call_id,tenant_id,company_id,
        organization_ref,base_fingerprint,operation_kind,approval_digest,payload_digest,auth_epoch),
 UNIQUE(dispatch_intent_id,change_id,claim_generation,dispatch_generation,call_id,tenant_id,company_id,
        organization_ref,base_fingerprint,operation_kind,approval_digest,payload_digest,auth_epoch,
        repair_authorization_id),
 FOREIGN KEY(change_id,claim_generation) REFERENCES change_ledger.dispatch_permits(change_id,generation)
);

CREATE TABLE change_ledger.private_writer_permit_bindings (
 dispatch_intent_id uuid PRIMARY KEY REFERENCES change_ledger.private_writer_dispatch_intents(dispatch_intent_id)
  CHECK(dispatch_intent_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 permit_id uuid NOT NULL UNIQUE CHECK(permit_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 permit_digest text NOT NULL CHECK(permit_digest ~ '^[a-f0-9]{64}$'),
 checkpoint_seq bigint NOT NULL CHECK(checkpoint_seq>0),
 signer_key_id text NOT NULL,
 signer_key_version text NOT NULL,
 issued_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL CHECK(expires_at>issued_at),
 UNIQUE(dispatch_intent_id,permit_id,permit_digest),
 FOREIGN KEY(signer_key_id,signer_key_version)
  REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version)
);

CREATE TABLE change_ledger.dispatch_attempts (
 dispatch_cas_id uuid PRIMARY KEY CHECK(dispatch_cas_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 dispatch_intent_id uuid NOT NULL UNIQUE
  CHECK(dispatch_intent_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 tenant_id text NOT NULL,
 company_id text NOT NULL,
 organization_ref text NOT NULL,
 base_fingerprint text NOT NULL,
 change_id uuid NOT NULL REFERENCES change_ledger.records(change_id)
  CHECK(change_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 claim_generation bigint NOT NULL CHECK(claim_generation>0),
 dispatch_generation bigint NOT NULL CHECK(dispatch_generation>0),
 call_id uuid NOT NULL UNIQUE CHECK(call_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 operation_kind text NOT NULL CHECK(operation_kind IN ('CREATE_DRAFT','POST','UNPOST')),
 approval_digest text NOT NULL CHECK(approval_digest ~ '^[a-f0-9]{64}$'),
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 permit_id uuid NOT NULL CHECK(permit_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 permit_digest text NOT NULL CHECK(permit_digest ~ '^[a-f0-9]{64}$'),
 expected_target_ref text NULL,
 expected_pre_version text NULL,
 auth_epoch bigint NOT NULL CHECK(auth_epoch>0),
 repair_authorization_id uuid NULL
  CHECK(repair_authorization_id IS NULL OR
        repair_authorization_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 "session_user" name NOT NULL,
 writer_service_id text NOT NULL,
 writer_host_id text NOT NULL,
 writer_process_instance_id text NOT NULL CHECK(writer_process_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 service_epoch bigint NOT NULL CHECK(service_epoch>0),
 onec_session_instance_id text NULL,
 binding_enabled boolean NOT NULL DEFAULT true CHECK(binding_enabled=true),
 state text NOT NULL CHECK(state IN ('ACCEPTED_NOT_INVOKED','POSSIBLY_EXECUTING','TERMINAL_WITH_EVIDENCE')),
 invocation_started_at timestamptz NULL,
 com_entry_authorized_at timestamptz NULL,
 terminalized_at timestamptz NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(dispatch_cas_id,dispatch_intent_id,change_id,claim_generation,dispatch_generation,call_id,
        tenant_id,company_id,organization_ref,base_fingerprint,operation_kind,auth_epoch,approval_digest,
        payload_digest,permit_id,permit_digest),
 UNIQUE(base_fingerprint,dispatch_cas_id),
 UNIQUE(base_fingerprint,call_id,dispatch_cas_id),
 UNIQUE(dispatch_cas_id,dispatch_intent_id),
 FOREIGN KEY(dispatch_intent_id,change_id,claim_generation,dispatch_generation,call_id,tenant_id,company_id,
              organization_ref,base_fingerprint,operation_kind,approval_digest,payload_digest,auth_epoch)
  REFERENCES change_ledger.private_writer_dispatch_intents
   (dispatch_intent_id,change_id,claim_generation,dispatch_generation,call_id,tenant_id,company_id,
    organization_ref,base_fingerprint,operation_kind,approval_digest,payload_digest,auth_epoch),
 FOREIGN KEY(dispatch_intent_id,permit_id,permit_digest)
  REFERENCES change_ledger.private_writer_permit_bindings(dispatch_intent_id,permit_id,permit_digest),
 FOREIGN KEY(change_id,claim_generation) REFERENCES change_ledger.dispatch_permits(change_id,generation),
 FOREIGN KEY("session_user",base_fingerprint,writer_service_id,writer_host_id,binding_enabled)
  REFERENCES change_ledger.private_writer_service_bindings
   ("session_user",base_fingerprint,writer_service_id,writer_host_id,binding_enabled),
 CHECK((state='ACCEPTED_NOT_INVOKED' AND invocation_started_at IS NULL AND terminalized_at IS NULL)
    OR (state='POSSIBLY_EXECUTING' AND invocation_started_at IS NOT NULL AND terminalized_at IS NULL)
    OR (state='TERMINAL_WITH_EVIDENCE' AND terminalized_at IS NOT NULL)),
 CHECK(state<>'ACCEPTED_NOT_INVOKED' OR com_entry_authorized_at IS NULL),
 CHECK(com_entry_authorized_at IS NULL OR
       (invocation_started_at IS NOT NULL AND com_entry_authorized_at>=invocation_started_at))
);

CREATE TABLE change_ledger.private_writer_evidence (
 evidence_ref text PRIMARY KEY CHECK(evidence_ref<>'' AND evidence_ref=btrim(evidence_ref)),
 record_type text NOT NULL CHECK(record_type IN
  ('DISPATCH_RECEIPT_V1','DISPATCH_NO_ENTRY_RECEIPT_V1',
   'OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3',
   'COMPLETION_PROOF_V1','POST_COMPLETION_CHALLENGE_V1','POST_COMPLETION_READ_ATTESTATION_V1')),
 -- These typed values are a projection emitted only by the authenticated evidence validator.
 -- They let terminal SQL recheck the S12 predicates without parsing/reconstructing signed JSON.
 -- The raw bytes remain the immutable signed source; this projection is never writer input.
 writer_receipt_id uuid NULL,
 writer_invocation_stage text NULL,
 writer_result_class text NULL,
 writer_call_returned boolean NULL,
 writer_returned_at timestamptz NULL,
 writer_returned_target_ref text NULL,
 writer_returned_version text NULL,
 no_effect_evidence_digest text NULL,
 outcome_evidence_version smallint NULL,
 outcome_dispatch_receipt_id uuid NULL,
 outcome_target_ref text NULL,
 outcome_pre_version text NULL,
 outcome_observed_version text NULL,
 outcome_expected_effect_digest text NULL,
 outcome_observed_effect_digest text NULL,
 outcome_fields_match boolean NULL,
 outcome_movements_match boolean NULL,
 outcome_observation_complete boolean NULL,
 outcome_reader_health text NULL,
 outcome_effect_presence text NULL,
 outcome_effect_identity text NULL,
 outcome_version_relation text NULL,
 outcome_attribution_result text NULL,
 outcome_attribution_evidence_ref text NULL,
 outcome_uncertainty_count integer NULL,
 outcome_completion_proof_class text NULL,
 outcome_completion_proof_digest text NULL,
 outcome_challenge_id uuid NULL,
 outcome_verification_sequence bigint NULL,
 outcome_observation_digest text NULL,
 outcome_read_attestation_digest text NULL,
 completion_proof_id uuid NULL,
 completion_proof_class text NULL,
 challenge_id uuid NULL,
 challenge_sequence_floor bigint NULL,
 read_attestation_sequence bigint NULL,
 read_attestation_outcome_digest text NULL,
 signed_bytes bytea NOT NULL CHECK(octet_length(signed_bytes)>0),
 signed_bytes_sha256 bytea NOT NULL CHECK(octet_length(signed_bytes_sha256)=32
   AND signed_bytes_sha256=pg_catalog.sha256(signed_bytes)),
 record_digest text NOT NULL CHECK(record_digest ~ '^[a-f0-9]{64}$'),
 tenant_id text NOT NULL,
 company_id text NOT NULL,
 organization_ref text NOT NULL,
 base_fingerprint text NOT NULL,
 change_id uuid NOT NULL,
 claim_generation bigint NOT NULL CHECK(claim_generation>0),
 dispatch_generation bigint NOT NULL CHECK(dispatch_generation>0),
 call_id uuid NOT NULL,
 dispatch_cas_id uuid NOT NULL,
 dispatch_intent_id uuid NOT NULL,
 operation_kind text NOT NULL CHECK(operation_kind IN ('CREATE_DRAFT','POST','UNPOST')),
 approval_digest text NOT NULL CHECK(approval_digest ~ '^[a-f0-9]{64}$'),
 payload_digest text NOT NULL CHECK(payload_digest ~ '^[a-f0-9]{64}$'),
 permit_id uuid NOT NULL,
 permit_digest text NOT NULL CHECK(permit_digest ~ '^[a-f0-9]{64}$'),
 target_ref text NULL,
 pre_version text NULL,
 auth_epoch bigint NOT NULL CHECK(auth_epoch>0),
 repair_authorization_id uuid NULL,
 signer_key_id text NOT NULL,
 signer_key_version text NOT NULL,
 signer_role text NOT NULL,
 signer_service_id text NOT NULL,
 signer_host_id text NOT NULL,
 signed_at timestamptz NOT NULL,
 trust_registry_revision bigint NOT NULL CHECK(trust_registry_revision>0),
 verified_at timestamptz NOT NULL,
 CHECK(verified_at>=signed_at),
 validator_build_id text NOT NULL,
 process_instance_id text NULL CHECK(process_instance_id IS NULL OR process_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 session_instance_id text NULL,
 CHECK(writer_receipt_id IS NULL
   OR writer_receipt_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 CHECK(outcome_dispatch_receipt_id IS NULL
   OR outcome_dispatch_receipt_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 CHECK(outcome_challenge_id IS NULL
   OR outcome_challenge_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 CHECK(completion_proof_id IS NULL
   OR completion_proof_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 CHECK(challenge_id IS NULL
   OR challenge_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 UNIQUE(record_type,record_digest),
 UNIQUE(evidence_ref,dispatch_cas_id,dispatch_intent_id),
 UNIQUE(evidence_ref,dispatch_cas_id,dispatch_intent_id,record_type,record_digest),
 FOREIGN KEY(dispatch_cas_id,dispatch_intent_id,change_id,claim_generation,dispatch_generation,
              call_id,tenant_id,company_id,organization_ref,base_fingerprint,operation_kind,auth_epoch,
              approval_digest,payload_digest,permit_id,permit_digest)
  REFERENCES change_ledger.dispatch_attempts(dispatch_cas_id,dispatch_intent_id,change_id,
   claim_generation,dispatch_generation,call_id,tenant_id,company_id,organization_ref,base_fingerprint,
   operation_kind,auth_epoch,approval_digest,payload_digest,permit_id,permit_digest),
 FOREIGN KEY(signer_key_id,signer_key_version)
  REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version),
 CHECK((record_type IN ('DISPATCH_RECEIPT_V1','DISPATCH_NO_ENTRY_RECEIPT_V1')
        AND writer_invocation_stage IS NOT NULL
        AND writer_invocation_stage IN ('NOT_INVOKED','ENTERED','INVOKED')
        AND writer_result_class IS NOT NULL
        AND writer_result_class IN ('PRE_WRITE_NO_EFFECT','CALL_RETURNED_SUCCESS','CALL_RETURNED_ERROR',
             'POST_START_UNKNOWN','RECEIPT_PERSISTENCE_UNKNOWN','CONDITIONAL_VERSION_CONFLICT')
        AND writer_call_returned IS NOT NULL
        AND writer_receipt_id IS NOT NULL
        AND (writer_call_returned=(writer_returned_at IS NOT NULL))
        AND (writer_result_class='PRE_WRITE_NO_EFFECT'
             AND writer_invocation_stage='NOT_INVOKED' AND NOT writer_call_returned
             AND writer_returned_target_ref IS NULL AND writer_returned_version IS NULL
             AND no_effect_evidence_digest IS NOT NULL
             AND no_effect_evidence_digest ~ '^[a-f0-9]{64}$'
          OR writer_result_class<>'PRE_WRITE_NO_EFFECT' AND no_effect_evidence_digest IS NULL)
        AND (record_type<>'DISPATCH_NO_ENTRY_RECEIPT_V1'
          OR (writer_result_class='PRE_WRITE_NO_EFFECT'
              AND writer_invocation_stage='NOT_INVOKED' AND NOT writer_call_returned))
        AND (writer_result_class<>'CALL_RETURNED_SUCCESS'
          OR (writer_invocation_stage IN ('ENTERED','INVOKED') AND writer_call_returned
              AND writer_returned_target_ref IS NOT NULL AND writer_returned_version IS NOT NULL
              AND (operation_kind='CREATE_DRAFT'
                   OR writer_returned_target_ref=target_ref)))
        AND (writer_result_class<>'CONDITIONAL_VERSION_CONFLICT'
          OR (operation_kind IN ('POST','UNPOST') AND writer_invocation_stage='ENTERED'
              AND writer_call_returned AND writer_returned_target_ref IS NULL
              AND writer_returned_version IS NULL)))
    OR (record_type IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3')
        AND outcome_evidence_version IS NOT NULL
        AND outcome_evidence_version=CASE record_type WHEN 'OUTCOME_EVIDENCE_V1' THEN 1
              WHEN 'OUTCOME_EVIDENCE_V2' THEN 2 ELSE 3 END
        AND outcome_target_ref IS NOT NULL
        AND ((operation_kind='CREATE_DRAFT' AND outcome_pre_version IS NULL)
          OR (operation_kind IN ('POST','UNPOST') AND outcome_pre_version IS NOT NULL))
        AND outcome_observed_version IS NOT NULL
        AND outcome_expected_effect_digest IS NOT NULL
        AND outcome_expected_effect_digest ~ '^[a-f0-9]{64}$'
        AND outcome_observed_effect_digest IS NOT NULL
        AND outcome_observed_effect_digest ~ '^[a-f0-9]{64}$'
        AND outcome_fields_match IS NOT NULL AND outcome_movements_match IS NOT NULL
        AND outcome_observation_complete IS NOT NULL
        AND outcome_reader_health IS NOT NULL
        AND outcome_effect_presence IS NOT NULL
        AND outcome_effect_presence IN ('PRESENT','ABSENT','UNKNOWN')
        AND outcome_effect_identity IS NOT NULL
        AND outcome_effect_identity IN ('MATCH','NO_GOVERNED_EFFECT','UNKNOWN')
        AND outcome_version_relation IS NOT NULL
        AND outcome_version_relation IN ('ADVANCED','UNCHANGED','DIFFERENT_COMPETING_WRITER','UNKNOWN')
        AND outcome_attribution_result IS NOT NULL
        AND outcome_attribution_result IN ('PROVEN','COMPETING_WRITER','UNATTRIBUTED','UNKNOWN')
        AND outcome_uncertainty_count IS NOT NULL
        AND outcome_uncertainty_count>=0
        AND outcome_dispatch_receipt_id IS NOT NULL
        AND outcome_completion_proof_class IS NOT NULL
        AND outcome_completion_proof_class IN
          ('WRITER_CALL_RETURNED','INDEPENDENT_SESSION_AND_PROCESS_CLOSED'))
    OR record_type='COMPLETION_PROOF_V1' AND completion_proof_id IS NOT NULL
       AND completion_proof_class IS NOT NULL AND completion_proof_class IN
       ('WRITER_CALL_RETURNED','INDEPENDENT_SESSION_AND_PROCESS_CLOSED')
    OR record_type IN ('POST_COMPLETION_CHALLENGE_V1','POST_COMPLETION_READ_ATTESTATION_V1')),
 CHECK((record_type='OUTCOME_EVIDENCE_V3'
        AND outcome_completion_proof_class IS NOT NULL
        AND outcome_completion_proof_digest IS NOT NULL
        AND outcome_completion_proof_digest ~ '^[a-f0-9]{64}$'
        AND outcome_challenge_id IS NOT NULL
        AND outcome_verification_sequence IS NOT NULL AND outcome_verification_sequence>0
        AND outcome_observation_digest IS NOT NULL
        AND outcome_observation_digest ~ '^[a-f0-9]{64}$'
        AND outcome_read_attestation_digest IS NOT NULL
        AND outcome_read_attestation_digest ~ '^[a-f0-9]{64}$')
    OR record_type<>'OUTCOME_EVIDENCE_V3'),
 CHECK(record_type='OUTCOME_EVIDENCE_V3' OR
       (outcome_completion_proof_digest IS NULL
        AND outcome_challenge_id IS NULL
        AND outcome_verification_sequence IS NULL
        AND outcome_observation_digest IS NULL AND outcome_read_attestation_digest IS NULL)),
 CHECK((record_type='POST_COMPLETION_CHALLENGE_V1'
        AND challenge_id IS NOT NULL AND challenge_sequence_floor IS NOT NULL
        AND challenge_sequence_floor>=0)
    OR (record_type='POST_COMPLETION_READ_ATTESTATION_V1'
        AND read_attestation_sequence IS NOT NULL AND read_attestation_sequence>0
        AND read_attestation_outcome_digest IS NOT NULL
        AND read_attestation_outcome_digest ~ '^[a-f0-9]{64}$')
    OR record_type NOT IN ('POST_COMPLETION_CHALLENGE_V1','POST_COMPLETION_READ_ATTESTATION_V1')),
 CHECK(record_type IN ('DISPATCH_RECEIPT_V1','DISPATCH_NO_ENTRY_RECEIPT_V1')
    OR (writer_invocation_stage IS NULL AND writer_result_class IS NULL
        AND writer_receipt_id IS NULL
        AND writer_call_returned IS NULL AND writer_returned_at IS NULL
        AND writer_returned_target_ref IS NULL AND writer_returned_version IS NULL
        AND no_effect_evidence_digest IS NULL)),
 CHECK(record_type='COMPLETION_PROOF_V1'
    OR (completion_proof_id IS NULL AND completion_proof_class IS NULL)),
 CHECK(record_type IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3')
       OR (outcome_evidence_version IS NULL AND outcome_dispatch_receipt_id IS NULL
        AND outcome_target_ref IS NULL AND outcome_pre_version IS NULL
        AND outcome_observed_version IS NULL AND outcome_expected_effect_digest IS NULL
        AND outcome_observed_effect_digest IS NULL AND outcome_fields_match IS NULL
        AND outcome_movements_match IS NULL AND outcome_observation_complete IS NULL
        AND outcome_reader_health IS NULL
        AND outcome_effect_presence IS NULL AND outcome_effect_identity IS NULL
        AND outcome_version_relation IS NULL AND outcome_attribution_result IS NULL
        AND outcome_attribution_evidence_ref IS NULL AND outcome_uncertainty_count IS NULL
        AND outcome_completion_proof_class IS NULL AND outcome_completion_proof_digest IS NULL
        AND outcome_challenge_id IS NULL AND outcome_verification_sequence IS NULL
        AND outcome_observation_digest IS NULL AND outcome_read_attestation_digest IS NULL)),
 CHECK(record_type='POST_COMPLETION_CHALLENGE_V1'
    OR (challenge_id IS NULL AND challenge_sequence_floor IS NULL)),
 CHECK(record_type='POST_COMPLETION_READ_ATTESTATION_V1'
    OR (read_attestation_sequence IS NULL AND read_attestation_outcome_digest IS NULL))
);

-- Database-side binding is a second guard after the trusted canonical/signature validator.
CREATE FUNCTION change_ledger.private_writer_evidence_binding_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a change_ledger.dispatch_attempts%ROWTYPE; k change_ledger.private_writer_signer_key_versions%ROWTYPE;
BEGIN
 NEW.verified_at:=clock_timestamp();
 SELECT * INTO a FROM change_ledger.dispatch_attempts WHERE dispatch_cas_id=NEW.dispatch_cas_id;
 IF NOT FOUND OR ROW(NEW.dispatch_intent_id,NEW.tenant_id,NEW.company_id,NEW.organization_ref,
    NEW.base_fingerprint,NEW.change_id,NEW.claim_generation,NEW.dispatch_generation,NEW.call_id,
    NEW.operation_kind,NEW.approval_digest,NEW.payload_digest,NEW.permit_id,NEW.permit_digest,
    NEW.auth_epoch,NEW.repair_authorization_id)
   IS DISTINCT FROM ROW(a.dispatch_intent_id,a.tenant_id,a.company_id,a.organization_ref,
    a.base_fingerprint,a.change_id,a.claim_generation,a.dispatch_generation,a.call_id,
    a.operation_kind,a.approval_digest,a.payload_digest,a.permit_id,a.permit_digest,
    a.auth_epoch,a.repair_authorization_id)
   OR NEW.target_ref IS DISTINCT FROM a.expected_target_ref
   OR NEW.pre_version IS DISTINCT FROM a.expected_pre_version THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT';
 END IF;
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions
  WHERE key_id=NEW.signer_key_id AND key_version=NEW.signer_key_version;
 IF NOT FOUND OR ROW(NEW.signer_role,NEW.signer_service_id,NEW.signer_host_id)
   IS DISTINCT FROM ROW(k.signer_role,k.service_id,k.host_id)
   OR NEW.signed_at<k.valid_from OR NEW.signed_at>=k.valid_until
   OR NEW.verified_at<k.valid_from OR NEW.verified_at>=k.valid_until
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
      WHERE s.key_id=k.key_id AND s.key_version=k.key_version
       AND s.tenant_id=NEW.tenant_id AND s.company_id=NEW.company_id
       AND s.organization_ref=NEW.organization_ref AND s.base_fingerprint=NEW.base_fingerprint)
   OR (NEW.record_type IN ('DISPATCH_RECEIPT_V1','DISPATCH_NO_ENTRY_RECEIPT_V1') AND
       (NEW.signer_role<>'writer_receipt' OR NEW.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
        OR NEW.session_instance_id IS DISTINCT FROM a.onec_session_instance_id))
   OR (NEW.record_type LIKE 'OUTCOME_EVIDENCE_%' AND NEW.signer_role<>'verification_worker')
   OR (NEW.record_type='COMPLETION_PROOF_V1' AND
       ((NEW.completion_proof_class='WRITER_CALL_RETURNED' AND
         (NEW.signer_role<>'writer_receipt' OR NEW.signer_service_id IS DISTINCT FROM a.writer_service_id
          OR NEW.signer_host_id IS DISTINCT FROM a.writer_host_id
          OR NEW.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
          OR NEW.session_instance_id IS DISTINCT FROM a.onec_session_instance_id))
        OR (NEW.completion_proof_class='INDEPENDENT_SESSION_AND_PROCESS_CLOSED' AND
         (NEW.signer_role<>'completion_supervisor' OR NEW.signer_service_id IS NOT DISTINCT FROM a.writer_service_id
          OR NEW.signer_host_id IS DISTINCT FROM a.writer_host_id
          OR NEW.process_instance_id IS NOT DISTINCT FROM a.writer_process_instance_id
          OR NEW.session_instance_id IS DISTINCT FROM a.onec_session_instance_id))))
   OR (NEW.record_type='POST_COMPLETION_CHALLENGE_V1' AND NEW.signer_role<>'completion_supervisor')
   OR (NEW.record_type='POST_COMPLETION_READ_ATTESTATION_V1' AND NEW.signer_role<>'read_attestor')
   OR NEW.validator_build_id='' OR NEW.validator_build_id<>btrim(NEW.validator_build_id)
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=k.key_id AND r.key_version=k.key_version
       AND (r.revoked_at<=NEW.signed_at OR r.revoked_at<=NEW.verified_at)) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED';
 END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_evidence_binding_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_evidence_binding_guard
 BEFORE INSERT ON change_ledger.private_writer_evidence
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_evidence_binding_guard_v1();

CREATE FUNCTION change_ledger.private_writer_register_evidence_v1(
 p_record change_ledger.private_writer_evidence
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE attempt change_ledger.dispatch_attempts%ROWTYPE;
        key_row change_ledger.private_writer_signer_key_versions%ROWTYPE;
        prior change_ledger.private_writer_evidence%ROWTYPE;
        stored change_ledger.private_writer_evidence%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        current_trust_revision bigint;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF SESSION_USER<>'private_writer_evidence_ingest' OR p_record IS NULL
   OR p_record.evidence_ref IS NULL OR p_record.record_type IS NULL
   OR p_record.signed_bytes IS NULL OR p_record.record_digest IS NULL
   OR p_record.dispatch_cas_id IS NULL OR p_record.signer_key_id IS NULL
   OR p_record.signer_key_version IS NULL OR p_record.validator_build_id IS NULL
   OR p_record.trust_registry_revision IS NULL OR p_record.trust_registry_revision<=0
   OR (p_record.process_instance_id IS NOT NULL AND p_record.process_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
   OR p_record.validator_build_id='' OR p_record.validator_build_id<>btrim(p_record.validator_build_id) THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 -- Match trust-writer trigger order: revision precedes key and scope row locks.
 SELECT revision INTO current_trust_revision
  FROM change_ledger.private_writer_trust_registry_revision
  WHERE revision_id=1 FOR SHARE;
 IF NOT FOUND OR current_trust_revision IS DISTINCT FROM p_record.trust_registry_revision THEN
  RAISE EXCEPTION 'EVIDENCE_TRUST_REVISION_STALE' USING ERRCODE='P0001';
 END IF;
 -- Use only caller-supplied immutable scope selectors for the non-locking plan reads. A foreign
 -- CAS or signer key must not select another tenant's base/key material for later advisory locks.
 SELECT * INTO attempt FROM change_ledger.dispatch_attempts a
  WHERE a.dispatch_cas_id=p_record.dispatch_cas_id
    AND a.tenant_id=p_record.tenant_id AND a.company_id=p_record.company_id
    AND a.organization_ref=p_record.organization_ref
    AND a.base_fingerprint=p_record.base_fingerprint;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO key_row FROM change_ledger.private_writer_signer_key_versions k
  WHERE k.key_id=p_record.signer_key_id AND k.key_version=p_record.signer_key_version
    AND k.signer_role=p_record.signer_role AND k.service_id=p_record.signer_service_id
    AND k.host_id=p_record.signer_host_id
    AND EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
      WHERE s.key_id=k.key_id AND s.key_version=k.key_version
       AND s.tenant_id=attempt.tenant_id AND s.company_id=attempt.company_id
       AND s.organization_ref=attempt.organization_ref
       AND s.base_fingerprint=attempt.base_fingerprint);
 IF NOT FOUND THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.private_writer_take_base_fence_v1(attempt.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(attempt.tenant_id,attempt.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=attempt.tenant_id AND x.company_id=attempt.company_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 SELECT * INTO key_row FROM change_ledger.private_writer_signer_key_versions k
  WHERE k.key_id=p_record.signer_key_id AND k.key_version=p_record.signer_key_version FOR SHARE;
 SELECT * INTO attempt FROM change_ledger.dispatch_attempts a
  WHERE a.dispatch_cas_id=p_record.dispatch_cas_id FOR SHARE;
 IF NOT FOUND OR ROW(p_record.dispatch_intent_id,p_record.change_id,p_record.claim_generation,
     p_record.dispatch_generation,p_record.call_id,p_record.tenant_id,p_record.company_id,
     p_record.organization_ref,p_record.base_fingerprint,p_record.operation_kind,p_record.auth_epoch,
     p_record.approval_digest,p_record.payload_digest,p_record.permit_id,p_record.permit_digest,
     p_record.target_ref,p_record.pre_version,p_record.repair_authorization_id)
   IS DISTINCT FROM ROW(attempt.dispatch_intent_id,attempt.change_id,attempt.claim_generation,
     attempt.dispatch_generation,attempt.call_id,attempt.tenant_id,attempt.company_id,
     attempt.organization_ref,attempt.base_fingerprint,attempt.operation_kind,attempt.auth_epoch,
     attempt.approval_digest,attempt.payload_digest,attempt.permit_id,attempt.permit_digest,
     attempt.expected_target_ref,attempt.expected_pre_version,attempt.repair_authorization_id) THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 -- This exact material lock is also used by the established verifier-key mutation triggers.
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(key_row.public_key,'hex'),17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_record.evidence_ref,'UTF8')),'hex'),
  'evidence-record:v1:'||p_record.record_type||':'||p_record.record_digest
 ]);
 IF ROW(p_record.signer_role,p_record.signer_service_id,p_record.signer_host_id)
   IS DISTINCT FROM ROW(key_row.signer_role,key_row.service_id,key_row.host_id)
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
     WHERE s.key_id=key_row.key_id AND s.key_version=key_row.key_version
      AND s.tenant_id=attempt.tenant_id AND s.company_id=attempt.company_id
      AND s.organization_ref=attempt.organization_ref AND s.base_fingerprint=attempt.base_fingerprint) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO prior FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_record.evidence_ref OR
   (e.record_type=p_record.record_type AND e.record_digest=p_record.record_digest)
  ORDER BY (e.evidence_ref=p_record.evidence_ref) DESC LIMIT 1 FOR SHARE;
 IF FOUND THEN
  IF ROW(prior.record_type,prior.signed_bytes,prior.record_digest,prior.tenant_id,prior.company_id,
       prior.organization_ref,prior.base_fingerprint,prior.change_id,prior.claim_generation,
       prior.dispatch_generation,prior.call_id,prior.dispatch_cas_id,prior.dispatch_intent_id,
       prior.operation_kind,prior.approval_digest,prior.payload_digest,prior.permit_id,prior.permit_digest,
       prior.target_ref,prior.pre_version,prior.auth_epoch,prior.repair_authorization_id,
       prior.signer_key_id,prior.signer_key_version,prior.signer_role,prior.signer_service_id,
       prior.signer_host_id,prior.signed_at,prior.process_instance_id,
       prior.session_instance_id)
    IS DISTINCT FROM ROW(p_record.record_type,p_record.signed_bytes,p_record.record_digest,
       p_record.tenant_id,p_record.company_id,p_record.organization_ref,p_record.base_fingerprint,
       p_record.change_id,p_record.claim_generation,p_record.dispatch_generation,p_record.call_id,
       p_record.dispatch_cas_id,p_record.dispatch_intent_id,p_record.operation_kind,p_record.approval_digest,
       p_record.payload_digest,p_record.permit_id,p_record.permit_digest,p_record.target_ref,p_record.pre_version,
       p_record.auth_epoch,p_record.repair_authorization_id,p_record.signer_key_id,p_record.signer_key_version,
       p_record.signer_role,p_record.signer_service_id,p_record.signer_host_id,p_record.signed_at,
       p_record.process_instance_id,p_record.session_instance_id) THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN prior.evidence_ref;
 END IF;
 stored:=p_record;
 stored.signed_bytes_sha256:=pg_catalog.sha256(p_record.signed_bytes);
 INSERT INTO change_ledger.private_writer_evidence SELECT stored.*;
 RETURN stored.evidence_ref;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_register_evidence_v1(
 change_ledger.private_writer_evidence) OWNER TO ledger_owner;

CREATE TABLE change_ledger.private_writer_attempt_evidence (
 dispatch_cas_id uuid NOT NULL,
 dispatch_intent_id uuid NOT NULL,
 evidence_ref text NOT NULL,
 evidence_purpose text NOT NULL CHECK(evidence_purpose IN
  ('WRITER_RECEIPT','NO_ENTRY_PROOF','OUTCOME','COMPLETION','POST_COMPLETION_CHALLENGE','READ_ATTESTATION')),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(dispatch_cas_id,evidence_ref),
 UNIQUE(dispatch_cas_id,evidence_ref,evidence_purpose),
 FOREIGN KEY(dispatch_cas_id,dispatch_intent_id)
  REFERENCES change_ledger.dispatch_attempts(dispatch_cas_id,dispatch_intent_id),
 FOREIGN KEY(evidence_ref,dispatch_cas_id,dispatch_intent_id)
  REFERENCES change_ledger.private_writer_evidence(evidence_ref,dispatch_cas_id,dispatch_intent_id)
);
CREATE UNIQUE INDEX private_writer_attempt_one_receipt_uq
 ON change_ledger.private_writer_attempt_evidence(dispatch_cas_id) WHERE evidence_purpose='WRITER_RECEIPT';
CREATE UNIQUE INDEX private_writer_attempt_one_no_entry_uq
 ON change_ledger.private_writer_attempt_evidence(dispatch_cas_id) WHERE evidence_purpose='NO_ENTRY_PROOF';
CREATE UNIQUE INDEX private_writer_attempt_one_completion_uq
 ON change_ledger.private_writer_attempt_evidence(dispatch_cas_id) WHERE evidence_purpose='COMPLETION';
CREATE UNIQUE INDEX private_writer_attempt_one_challenge_uq
 ON change_ledger.private_writer_attempt_evidence(dispatch_cas_id) WHERE evidence_purpose='POST_COMPLETION_CHALLENGE';
CREATE UNIQUE INDEX private_writer_attempt_one_read_attestation_uq
 ON change_ledger.private_writer_attempt_evidence(dispatch_cas_id) WHERE evidence_purpose='READ_ATTESTATION';

CREATE FUNCTION change_ledger.private_writer_attempt_evidence_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE typ text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 SELECT record_type INTO typ FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=NEW.evidence_ref AND e.dispatch_cas_id=NEW.dispatch_cas_id
   AND e.dispatch_intent_id=NEW.dispatch_intent_id;
 IF NOT FOUND OR NOT (
   (NEW.evidence_purpose='WRITER_RECEIPT' AND typ='DISPATCH_RECEIPT_V1') OR
   (NEW.evidence_purpose='NO_ENTRY_PROOF' AND typ='DISPATCH_NO_ENTRY_RECEIPT_V1') OR
   (NEW.evidence_purpose='OUTCOME' AND typ IN
      ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3')) OR
   (NEW.evidence_purpose='COMPLETION' AND typ='COMPLETION_PROOF_V1') OR
   (NEW.evidence_purpose='POST_COMPLETION_CHALLENGE' AND typ='POST_COMPLETION_CHALLENGE_V1') OR
   (NEW.evidence_purpose='READ_ATTESTATION' AND typ='POST_COMPLETION_READ_ATTESTATION_V1')) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_attempt_evidence_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_attempt_evidence_guard
 BEFORE INSERT OR UPDATE OR DELETE ON change_ledger.private_writer_attempt_evidence
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_attempt_evidence_guard_v1();

CREATE TABLE change_ledger.writer_barriers (
 barrier_id uuid PRIMARY KEY CHECK(barrier_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 base_fingerprint text NOT NULL,
 tenant_id text NOT NULL,
 company_id text NOT NULL,
 expected_current_epoch bigint NOT NULL CHECK(expected_current_epoch>=0),
 epoch bigint NOT NULL CHECK(epoch=expected_current_epoch+1),
 barrier_origin_instance_id text NOT NULL CHECK(barrier_origin_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 barrier_origin_service_epoch bigint NOT NULL CHECK(barrier_origin_service_epoch>0),
 progress text NOT NULL CHECK(progress IN ('CLOSED_WITH_HOLD','QUIESCED')),
 acknowledgement_ref text NULL,
 acknowledgement_digest bytea NULL,
 quiesced_at timestamptz NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(base_fingerprint,barrier_id),
 CHECK((progress='CLOSED_WITH_HOLD' AND acknowledgement_ref IS NULL AND acknowledgement_digest IS NULL AND quiesced_at IS NULL)
    OR (progress='QUIESCED' AND acknowledgement_ref IS NOT NULL AND acknowledgement_digest IS NOT NULL
        AND octet_length(acknowledgement_digest)=32 AND quiesced_at IS NOT NULL))
);

CREATE TABLE change_ledger.writer_barrier_calls (
 barrier_id uuid NOT NULL CHECK(barrier_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 base_fingerprint text NOT NULL,
 snapshot_ordinal bigint NOT NULL CHECK(snapshot_ordinal>=0),
 call_id uuid NOT NULL CHECK(call_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 dispatch_cas_id uuid NOT NULL CHECK(dispatch_cas_id<>'00000000-0000-0000-0000-000000000000'::uuid),
 PRIMARY KEY(barrier_id,call_id),
 UNIQUE(barrier_id,snapshot_ordinal),
 UNIQUE(barrier_id,dispatch_cas_id),
 FOREIGN KEY(base_fingerprint,barrier_id) REFERENCES change_ledger.writer_barriers(base_fingerprint,barrier_id),
 FOREIGN KEY(base_fingerprint,call_id,dispatch_cas_id)
  REFERENCES change_ledger.dispatch_attempts(base_fingerprint,call_id,dispatch_cas_id)
);

CREATE TYPE change_ledger.private_writer_scope_v1 AS (tenant_id text, company_id text);
CREATE TYPE change_ledger.private_writer_barrier_ack_v1 AS (
 base_fingerprint text, scope change_ledger.private_writer_scope_v1, lifecycle_epoch bigint,
 barrier_id uuid, barrier_origin_instance_id text, barrier_origin_service_epoch bigint,
 call_ids uuid[], key_id text, key_version text, writer_service_id text, writer_host_id text,
 host_boot_id text, writer_process_instance_id text, process_attestation_ref text,
 writer_queue_epoch bigint, local_queue_closed boolean, signed_at text, signature bytea
);

CREATE TABLE change_ledger.writer_barrier_acknowledgements (
 acknowledgement_ref text PRIMARY KEY CHECK(acknowledgement_ref<>'' AND acknowledgement_ref=btrim(acknowledgement_ref)),
 barrier_id uuid NOT NULL UNIQUE REFERENCES change_ledger.writer_barriers(barrier_id),
 base_fingerprint text NOT NULL CHECK(base_fingerprint<>'' AND base_fingerprint=btrim(base_fingerprint)),
 tenant_id text NOT NULL,
 company_id text NOT NULL,
 lifecycle_epoch bigint NOT NULL CHECK(lifecycle_epoch>0),
 barrier_origin_instance_id text NOT NULL CHECK(barrier_origin_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 barrier_origin_service_epoch bigint NOT NULL CHECK(barrier_origin_service_epoch>0),
 call_ids uuid[] NOT NULL,
 writer_service_id text NOT NULL CHECK(writer_service_id<>'' AND writer_service_id=btrim(writer_service_id)),
 writer_host_id text NOT NULL CHECK(writer_host_id<>'' AND writer_host_id=btrim(writer_host_id)),
 host_boot_id text NOT NULL CHECK(host_boot_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 writer_process_instance_id text NOT NULL CHECK(writer_process_instance_id ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
 process_attestation_ref text NOT NULL CHECK(process_attestation_ref<>''
   AND process_attestation_ref=btrim(process_attestation_ref)),
 writer_queue_epoch bigint NOT NULL CHECK(writer_queue_epoch>0),
 local_queue_closed boolean NOT NULL CHECK(local_queue_closed),
 signed_at timestamptz NOT NULL,
 signed_bytes bytea NOT NULL CHECK(octet_length(signed_bytes)>0),
 signature_bytes bytea NOT NULL CHECK(octet_length(signature_bytes)=64),
 signed_bytes_sha256 bytea NOT NULL CHECK(octet_length(signed_bytes_sha256)=32
   AND signed_bytes_sha256=pg_catalog.sha256(signed_bytes)),
 signer_key_id text NOT NULL,
 signer_key_version text NOT NULL,
 verified_at timestamptz NOT NULL,
 UNIQUE(barrier_id,acknowledgement_ref,signed_bytes_sha256),
 FOREIGN KEY(base_fingerprint,barrier_id) REFERENCES change_ledger.writer_barriers(base_fingerprint,barrier_id),
 FOREIGN KEY(signer_key_id,signer_key_version)
  REFERENCES change_ledger.private_writer_signer_key_versions(key_id,key_version)
);

ALTER TABLE change_ledger.writer_barriers ADD CONSTRAINT writer_barrier_ack_binding_fk
 FOREIGN KEY(barrier_id,acknowledgement_ref,acknowledgement_digest)
 REFERENCES change_ledger.writer_barrier_acknowledgements(barrier_id,acknowledgement_ref,signed_bytes_sha256)
 MATCH SIMPLE;

CREATE FUNCTION change_ledger.private_writer_barrier_ack_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b change_ledger.writer_barriers%ROWTYPE; k change_ledger.private_writer_signer_key_versions%ROWTYPE;
        expected_calls uuid[]; prior_revoked boolean;
BEGIN
 NEW.verified_at:=clock_timestamp();
 SELECT * INTO b FROM change_ledger.writer_barriers x WHERE x.barrier_id=NEW.barrier_id;
 IF NOT FOUND OR ROW(NEW.base_fingerprint,NEW.tenant_id,NEW.company_id,NEW.lifecycle_epoch,
     NEW.barrier_origin_instance_id,NEW.barrier_origin_service_epoch)
   IS DISTINCT FROM ROW(b.base_fingerprint,b.tenant_id,b.company_id,b.epoch,
     b.barrier_origin_instance_id,b.barrier_origin_service_epoch) THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(array_agg(c.call_id ORDER BY c.call_id),ARRAY[]::uuid[])
  INTO expected_calls FROM change_ledger.writer_barrier_calls c WHERE c.barrier_id=b.barrier_id;
 IF NEW.call_ids IS DISTINCT FROM expected_calls THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=NEW.signer_key_id AND x.key_version=NEW.signer_key_version;
 IF NOT FOUND OR ROW(k.signer_role,k.service_id,k.host_id)
   IS DISTINCT FROM ROW('writer_receipt',NEW.writer_service_id,NEW.writer_host_id)
   OR NEW.signed_at<k.valid_from OR NEW.signed_at>=k.valid_until
   OR NEW.verified_at<k.valid_from OR NEW.verified_at>=k.valid_until
   OR NOT NEW.local_queue_closed OR NEW.writer_queue_epoch<=0
   OR NEW.process_attestation_ref='' OR NEW.process_attestation_ref<>btrim(NEW.process_attestation_ref)
   OR NEW.process_attestation_ref<>NEW.writer_process_instance_id
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_process_attestations p
      JOIN change_ledger.private_writer_signer_key_versions sk
       ON sk.key_id=p.supervisor_key_id AND sk.key_version=p.supervisor_key_version
      WHERE p.process_instance_id=NEW.writer_process_instance_id::uuid
       AND p.host_boot_id=NEW.host_boot_id::uuid AND p.service_id=NEW.writer_service_id
       AND p.host_id=NEW.writer_host_id AND p.process_created_at<=NEW.signed_at
       AND sk.signer_role='completion_supervisor' AND sk.host_id=NEW.writer_host_id
       AND sk.service_id<>NEW.writer_service_id
       AND sk.valid_from<=p.process_created_at AND p.process_created_at<sk.valid_until
       AND sk.valid_from<=NEW.verified_at AND NEW.verified_at<sk.valid_until
       AND NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
         WHERE r.key_id=sk.key_id AND r.key_version=sk.key_version
           AND r.revoked_at<=NEW.verified_at)
       AND EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
         WHERE s.key_id=sk.key_id AND s.key_version=sk.key_version
          AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
          AND s.base_fingerprint=b.base_fingerprint)
       AND NOT EXISTS(SELECT 1 FROM change_ledger.writer_barrier_calls c
          JOIN change_ledger.dispatch_attempts a ON a.dispatch_cas_id=c.dispatch_cas_id
          WHERE c.barrier_id=b.barrier_id AND NOT EXISTS(
            SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
            WHERE s.key_id=sk.key_id AND s.key_version=sk.key_version
             AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
             AND s.organization_ref=a.organization_ref AND s.base_fingerprint=b.base_fingerprint)))
   OR NEW.signed_bytes_sha256<>pg_catalog.sha256(NEW.signed_bytes)
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
      WHERE s.key_id=k.key_id AND s.key_version=k.key_version AND s.tenant_id=b.tenant_id
       AND s.company_id=b.company_id AND s.base_fingerprint=b.base_fingerprint)
   OR EXISTS(SELECT 1 FROM change_ledger.writer_barrier_calls c
       JOIN change_ledger.dispatch_attempts a ON a.dispatch_cas_id=c.dispatch_cas_id
       WHERE c.barrier_id=b.barrier_id AND NOT EXISTS(
         SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
         WHERE s.key_id=k.key_id AND s.key_version=k.key_version
          AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
          AND s.organization_ref=a.organization_ref AND s.base_fingerprint=b.base_fingerprint)) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
   WHERE r.key_id=k.key_id AND r.key_version=k.key_version) INTO prior_revoked;
 IF prior_revoked THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_barrier_ack_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_barrier_ack_guard
 BEFORE INSERT ON change_ledger.writer_barrier_acknowledgements
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_barrier_ack_guard_v1();

CREATE FUNCTION change_ledger.private_writer_register_barrier_ack_v1(
 p_ack change_ledger.private_writer_barrier_ack_v1,p_ref text,p_signed_bytes bytea,
 p_trust_revision bigint
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.writer_barriers%ROWTYPE; b change_ledger.writer_barriers%ROWTYPE;
        service_binding change_ledger.private_writer_service_bindings%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE; p change_ledger.private_writer_process_attestations%ROWTYPE;
        k change_ledger.private_writer_signer_key_versions%ROWTYPE;
        sk change_ledger.private_writer_signer_key_versions%ROWTYPE;
        prior change_ledger.writer_barrier_acknowledgements%ROWTYPE; expected_calls uuid[];
        exact_tuple boolean; ref_lock text; initial_public_key bytea;
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
 SELECT * INTO service_binding FROM change_ledger.private_writer_service_bindings x
  WHERE x.base_fingerprint=p_ack.base_fingerprint
    AND x.writer_service_id=p_ack.writer_service_id
    AND x.writer_host_id=p_ack.writer_host_id
    AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 -- Match trust-registry writers: revision row precedes key/advisory locks. Holding this share
 -- lock through commit prevents a new acknowledgement from being admitted against a stale key
 -- snapshot while still allowing exact replay below after revocation.
 SELECT revision INTO current_trust_revision
  FROM change_ledger.private_writer_trust_registry_revision
  WHERE revision_id=1 FOR SHARE;
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
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(supervisor_public_key,'hex'),17017));
 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
  IF NOT FOUND OR lf.state<>'RECOVERING' OR lf.epoch<>hint.epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=p_ack.key_id AND x.key_version=p_ack.key_version;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 initial_public_key:=k.public_key;
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(initial_public_key,'hex'),17017));
 ref_lock:='barrier-ack-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_ref,'UTF8')),'hex');
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'barrier-id:v1:'||lower(p_ack.barrier_id::text),ref_lock]);
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
ALTER FUNCTION change_ledger.private_writer_register_barrier_ack_v1(
 change_ledger.private_writer_barrier_ack_v1,text,bytea,bigint) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_lookup_barrier_ack_v1(p_barrier_id uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE result jsonb; ack_base text;
BEGIN
 IF SESSION_USER<>'private_writer_evidence_ingest'
   OR current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')<>'on'
   OR p_barrier_id IS NULL THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 SELECT pg_catalog.jsonb_build_object(
   'acknowledgement_ref',a.acknowledgement_ref,
   'barrier_id',a.barrier_id::text,
   'base_fingerprint',a.base_fingerprint,
   'tenant_id',a.tenant_id,
   'company_id',a.company_id,
   'lifecycle_epoch',a.lifecycle_epoch,
   'barrier_origin_instance_id',a.barrier_origin_instance_id,
   'barrier_origin_service_epoch',a.barrier_origin_service_epoch,
   'call_ids',to_jsonb(a.call_ids),
   'writer_service_id',a.writer_service_id,
   'writer_host_id',a.writer_host_id,
   'host_boot_id',a.host_boot_id,
   'writer_process_instance_id',a.writer_process_instance_id,
   'process_attestation_ref',a.process_attestation_ref,
   'writer_queue_epoch',a.writer_queue_epoch,
   'local_queue_closed',a.local_queue_closed,
   'signed_at',pg_catalog.to_char(a.signed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'signed_bytes_hex',pg_catalog.encode(a.signed_bytes,'hex'),
   'signature_hex',pg_catalog.encode(a.signature_bytes,'hex'),
   'signed_bytes_sha256',pg_catalog.encode(a.signed_bytes_sha256,'hex'),
   'signer_key_id',a.signer_key_id,
   'signer_key_version',a.signer_key_version,
   'verified_at',pg_catalog.to_char(a.verified_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ),a.base_fingerprint INTO result,ack_base
  FROM change_ledger.writer_barrier_acknowledgements a
  WHERE a.barrier_id=p_barrier_id;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_service_bindings b
      WHERE b."session_user"=session_user AND b.base_fingerprint=ack_base
       AND b.binding_enabled AND b.revoked_at IS NULL) THEN
  RETURN NULL;
 END IF;
 RETURN result;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_lookup_barrier_ack_v1(uuid) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_load_barrier_ack_trust_v1(
 p_ack change_ledger.private_writer_barrier_ack_v1)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b change_ledger.writer_barriers%ROWTYPE;
        process_row change_ledger.private_writer_process_attestations%ROWTYPE;
        registry_revision bigint; loaded_at timestamptz:=pg_catalog.clock_timestamp();
        represented_scopes jsonb; signer_docs jsonb; process_docs jsonb;
BEGIN
 IF SESSION_USER<>'private_writer_evidence_ingest'
   OR current_setting('transaction_isolation')<>'repeatable read'
   OR current_setting('transaction_read_only')<>'on' OR p_ack IS NULL
   OR p_ack.barrier_id IS NULL OR p_ack.key_id IS NULL OR p_ack.key_version IS NULL
   OR p_ack.writer_process_instance_id IS NULL
   OR p_ack.process_attestation_ref IS DISTINCT FROM p_ack.writer_process_instance_id
   OR p_ack.local_queue_closed IS DISTINCT FROM true OR p_ack.signature IS NULL
   OR pg_catalog.octet_length(p_ack.signature)<>64
   OR p_ack.signed_at IS NULL OR p_ack.signed_at !~
      '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$' THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 SELECT * INTO b FROM change_ledger.writer_barriers x
  WHERE x.barrier_id=p_ack.barrier_id;
 IF NOT FOUND OR b.progress<>'CLOSED_WITH_HOLD'
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_service_bindings binding
      WHERE binding."session_user"=session_user AND binding.base_fingerprint=b.base_fingerprint
       AND binding.binding_enabled AND binding.revoked_at IS NULL)
   OR ROW(p_ack.base_fingerprint,(p_ack.scope).tenant_id,(p_ack.scope).company_id,
      p_ack.lifecycle_epoch,p_ack.barrier_origin_instance_id,p_ack.barrier_origin_service_epoch)
    IS DISTINCT FROM ROW(b.base_fingerprint,b.tenant_id,b.company_id,b.epoch,
      b.barrier_origin_instance_id,b.barrier_origin_service_epoch)
   OR p_ack.call_ids IS DISTINCT FROM COALESCE((
      SELECT array_agg(c.call_id ORDER BY c.call_id)
       FROM change_ledger.writer_barrier_calls c WHERE c.barrier_id=b.barrier_id),ARRAY[]::uuid[])
   OR p_ack.writer_service_id IS NULL OR p_ack.writer_host_id IS NULL
   OR p_ack.host_boot_id IS NULL OR p_ack.writer_process_instance_id IS NULL THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO process_row FROM change_ledger.private_writer_process_attestations p
  WHERE p.process_instance_id=p_ack.writer_process_instance_id::uuid;
 IF NOT FOUND OR ROW(process_row.host_boot_id,process_row.service_id,process_row.host_id)
   IS DISTINCT FROM ROW(p_ack.host_boot_id::uuid,p_ack.writer_service_id,p_ack.writer_host_id) THEN
  RAISE EXCEPTION 'TRUST_PROCESS_BINDING_UNAVAILABLE' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions
   WHERE signer_role IN ('writer_receipt','verification_worker','completion_supervisor',
                         'read_attestor','checkpoint_signer')
   GROUP BY service_id HAVING count(DISTINCT signer_role)>1) THEN
  RAISE EXCEPTION 'TRUST_REGISTRY_SERVICE_COLLISION' USING ERRCODE='P0001';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions k
   WHERE k.key_id=p_ack.key_id AND k.key_version=p_ack.key_version
    AND k.signer_role='writer_receipt' AND k.service_id=p_ack.writer_service_id
    AND k.host_id=p_ack.writer_host_id)
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions k
   WHERE k.key_id=process_row.supervisor_key_id
    AND k.key_version=process_row.supervisor_key_version
    AND k.signer_role='completion_supervisor' AND k.host_id=p_ack.writer_host_id
    AND k.service_id<>p_ack.writer_service_id) THEN
  RAISE EXCEPTION 'TRUST_SIGNER_SCOPE_UNAVAILABLE' USING ERRCODE='P0001';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
   WHERE s.key_id=p_ack.key_id AND s.key_version=p_ack.key_version
    AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
    AND s.base_fingerprint=b.base_fingerprint)
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
   WHERE s.key_id=process_row.supervisor_key_id
    AND s.key_version=process_row.supervisor_key_version
    AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
    AND s.base_fingerprint=b.base_fingerprint)
   OR EXISTS(SELECT 1 FROM change_ledger.writer_barrier_calls c
      JOIN change_ledger.dispatch_attempts a ON a.dispatch_cas_id=c.dispatch_cas_id
      WHERE c.barrier_id=b.barrier_id AND (
       NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
         WHERE s.key_id=p_ack.key_id AND s.key_version=p_ack.key_version
          AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
          AND s.organization_ref=a.organization_ref AND s.base_fingerprint=b.base_fingerprint)
       OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes s
         WHERE s.key_id=process_row.supervisor_key_id
          AND s.key_version=process_row.supervisor_key_version
          AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
          AND s.organization_ref=a.organization_ref AND s.base_fingerprint=b.base_fingerprint))) THEN
  RAISE EXCEPTION 'TRUST_SIGNER_SCOPE_UNAVAILABLE' USING ERRCODE='P0001';
 END IF;
 SELECT revision INTO registry_revision FROM change_ledger.private_writer_trust_registry_revision
  WHERE revision_id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'TRUST_REGISTRY_REVISION_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'tenant_id',s.tenant_id,'company_id',s.company_id,'organization_ref',s.organization_ref,
   'base_fingerprint',s.base_fingerprint) ORDER BY s.organization_ref),'[]'::jsonb)
  INTO represented_scopes
  FROM (SELECT DISTINCT a.organization_ref
        FROM change_ledger.writer_barrier_calls c
        JOIN change_ledger.dispatch_attempts a ON a.dispatch_cas_id=c.dispatch_cas_id
        WHERE c.barrier_id=b.barrier_id) organizations
  JOIN LATERAL (SELECT b.tenant_id,b.company_id,organizations.organization_ref,
                       b.base_fingerprint) s ON true;
 IF pg_catalog.jsonb_array_length(represented_scopes)>4096 THEN
  RAISE EXCEPTION 'TRUST_SNAPSHOT_REQUEST_INVALID' USING ERRCODE='P0001';
 END IF;

 WITH RECURSIVE roots(key_id,key_version) AS (
   VALUES (p_ack.key_id,p_ack.key_version),
          (process_row.supervisor_key_id,process_row.supervisor_key_version)
 ), walk(root_key_id,root_key_version,key_id,key_version,depth) AS (
   SELECT r.key_id,r.key_version,r.key_id,r.key_version,0 FROM roots r
   UNION ALL
   SELECT w.root_key_id,w.root_key_version,r.predecessor_key_id,r.predecessor_key_version,w.depth+1
    FROM walk w JOIN change_ledger.private_writer_signer_key_rotations r
     ON r.successor_key_id=w.key_id AND r.successor_key_version=w.key_version
    WHERE w.depth<128
 ), all_keys(key_id,key_version) AS (
   SELECT DISTINCT key_id,key_version FROM walk
 ), histories(start_key_id,start_key_version,key_id,key_version,depth) AS (
   SELECT k.key_id,k.key_version,k.key_id,k.key_version,0 FROM all_keys k
   UNION ALL
   SELECT h.start_key_id,h.start_key_version,r.predecessor_key_id,r.predecessor_key_version,h.depth+1
    FROM histories h JOIN change_ledger.private_writer_signer_key_rotations r
     ON r.successor_key_id=h.key_id AND r.successor_key_version=h.key_version
    WHERE h.depth<128
 )
 SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'key_id',v.key_id,'key_version',v.key_version,'public_key_hex',pg_catalog.encode(v.public_key,'hex'),
   'signer_role',v.signer_role,'service_id',v.service_id,'host_id',v.host_id,
   'valid_from',v.valid_from,'valid_until',v.valid_until,'revoked_at',rev.revoked_at,
   'allowed_scopes',COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'tenant_id',s.tenant_id,'company_id',s.company_id,'organization_ref',s.organization_ref,
      'base_fingerprint',s.base_fingerprint) ORDER BY s.tenant_id,s.company_id,
        s.organization_ref,s.base_fingerprint)
     FROM change_ledger.private_writer_signer_key_scopes s
     WHERE s.key_id=v.key_id AND s.key_version=v.key_version
      AND s.tenant_id=b.tenant_id AND s.company_id=b.company_id
      AND s.base_fingerprint=b.base_fingerprint
      AND EXISTS(SELECT 1 FROM roots requested
        WHERE requested.key_id=v.key_id AND requested.key_version=v.key_version)
      AND (s.organization_ref IN (SELECT x.organization_ref FROM jsonb_to_recordset(represented_scopes)
            AS x(tenant_id text,company_id text,organization_ref text,base_fingerprint text))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(represented_scopes)))),'[]'::jsonb),
   'rotation_history',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'key_id',h.key_id,'key_version',h.key_version) ORDER BY h.depth DESC)
      FROM histories h WHERE h.start_key_id=v.key_id AND h.start_key_version=v.key_version)
  ) ORDER BY v.key_id,v.key_version)
  INTO signer_docs
  FROM all_keys k JOIN change_ledger.private_writer_signer_key_versions v
    ON v.key_id=k.key_id AND v.key_version=k.key_version
  LEFT JOIN change_ledger.private_writer_signer_key_revocations rev
    ON rev.key_id=v.key_id AND rev.key_version=v.key_version;
 IF signer_docs IS NULL OR (SELECT count(*) FROM pg_catalog.jsonb_array_elements(signer_docs))=0
   OR EXISTS(WITH RECURSIVE roots(key_id,key_version) AS (
      VALUES (p_ack.key_id,p_ack.key_version),
             (process_row.supervisor_key_id,process_row.supervisor_key_version)
      ),walk(root_key_id,root_key_version,key_id,key_version,depth) AS (
       SELECT key_id,key_version,key_id,key_version,0 FROM roots
       UNION ALL SELECT w.root_key_id,w.root_key_version,r.predecessor_key_id,
         r.predecessor_key_version,w.depth+1 FROM walk w
         JOIN change_ledger.private_writer_signer_key_rotations r
          ON r.successor_key_id=w.key_id AND r.successor_key_version=w.key_version
         WHERE w.depth<128)
      SELECT 1 FROM walk WHERE depth=128) THEN
  RAISE EXCEPTION 'TRUST_ROTATION_CHAIN_TOO_DEEP' USING ERRCODE='P0001';
 END IF;
 SELECT pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
   'process_instance_id',p.process_instance_id,'host_boot_id',p.host_boot_id,
   'service_id',p.service_id,'host_id',p.host_id,'os_pid',p.os_pid,
   'process_created_at',p.process_created_at,'supervisor_key_id',p.supervisor_key_id,
   'supervisor_key_version',p.supervisor_key_version,'signature_hex',pg_catalog.encode(p.signature,'hex')))
  INTO process_docs FROM change_ledger.private_writer_process_attestations p
  WHERE p.process_instance_id=process_row.process_instance_id;
 RETURN pg_catalog.jsonb_build_object(
   'snapshot',pg_catalog.jsonb_build_object('revision',registry_revision::text,
     'loaded_at',loaded_at,'signers',signer_docs,'process_bindings',process_docs,
     'oracle_artifacts','[]'::jsonb,'outcome_version_floors','[]'::jsonb),
   'represented_scopes',represented_scopes);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_load_barrier_ack_trust_v1(
 change_ledger.private_writer_barrier_ack_v1) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_key_revocation_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE key_material bytea;
BEGIN
  -- Serialize key resolution/registration/terminalization before locking the key-version row.
  SELECT public_key INTO key_material FROM change_ledger.private_writer_signer_key_versions
   WHERE key_id=NEW.key_id AND key_version=NEW.key_version;
  IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED'; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(encode(key_material,'hex'),17017));
 PERFORM 1 FROM change_ledger.private_writer_signer_key_versions
  WHERE key_id=NEW.key_id AND key_version=NEW.key_version FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED'; END IF;
 NEW.revoked_at := clock_timestamp();
 NEW.recorded_by := session_user;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_key_revocation_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_key_revocation_guard
 BEFORE INSERT ON change_ledger.private_writer_signer_key_revocations
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_key_revocation_guard_v1();

CREATE FUNCTION change_ledger.private_writer_key_rotation_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE cur_id text:=NEW.successor_key_id; cur_version text:=NEW.successor_key_version;
        next_id text; next_version text; remaining integer;
BEGIN
 -- Serialize the immutable graph edge before any relation/index conflict can race a reverse edge.
 PERFORM pg_catalog.pg_advisory_xact_lock(6, pg_catalog.hashtext('private-writer-key-rotation-graph:v1'));
 SELECT count(*)+1 INTO remaining FROM change_ledger.private_writer_signer_key_rotations;
 WHILE remaining>0 LOOP
  IF cur_id=NEW.predecessor_key_id AND cur_version=NEW.predecessor_key_version THEN
   RAISE EXCEPTION 'SIGNER_KEY_ROTATION_CYCLE';
  END IF;
  SELECT successor_key_id,successor_key_version INTO next_id,next_version
   FROM change_ledger.private_writer_signer_key_rotations
   WHERE predecessor_key_id=cur_id AND predecessor_key_version=cur_version;
  IF NOT FOUND THEN RETURN NEW; END IF;
  cur_id:=next_id; cur_version:=next_version; remaining:=remaining-1;
 END LOOP;
 RAISE EXCEPTION 'SIGNER_KEY_ROTATION_GRAPH_CORRUPT';
END $fn$;
ALTER FUNCTION change_ledger.private_writer_key_rotation_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_key_rotation_guard
 BEFORE INSERT ON change_ledger.private_writer_signer_key_rotations
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_key_rotation_guard_v1();

CREATE TABLE change_ledger.physical_base_slots (
 base_fingerprint text PRIMARY KEY,
 active_dispatch_cas_id uuid NULL UNIQUE,
 open_barrier_id uuid NULL,
 admission_closed boolean NOT NULL DEFAULT false,
 UNIQUE(base_fingerprint,active_dispatch_cas_id),
 FOREIGN KEY(base_fingerprint,active_dispatch_cas_id)
  REFERENCES change_ledger.dispatch_attempts(base_fingerprint,dispatch_cas_id),
 FOREIGN KEY(base_fingerprint,open_barrier_id)
  REFERENCES change_ledger.writer_barriers(base_fingerprint,barrier_id),
 CHECK(admission_closed=(open_barrier_id IS NOT NULL))
);

CREATE FUNCTION change_ledger.private_writer_permit_signature_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF ROW(NEW.signer_key_id,NEW.signature) IS DISTINCT FROM ROW(OLD.signer_key_id,OLD.signature)
   AND EXISTS(SELECT 1 FROM change_ledger.private_writer_permit_bindings b
     JOIN change_ledger.private_writer_dispatch_intents i
       ON i.dispatch_intent_id=b.dispatch_intent_id
     WHERE i.change_id=OLD.change_id AND i.claim_generation=OLD.generation) THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_permit_signature_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_permit_signature_guard
 BEFORE UPDATE OF signer_key_id,signature ON change_ledger.dispatch_permits
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_permit_signature_guard_v1();

CREATE TYPE change_ledger.private_writer_identity_v1 AS (
 tenant_id text, company_id text, organization_ref text, change_id uuid, generation bigint,
 call_id uuid, operation text, target_ref text, target_version text, epoch bigint, payload_digest text,
 permit_id text, permit_digest text, base_fingerprint text, host_id text, repair_authorization_id text
);
CREATE TYPE change_ledger.private_writer_admission_decision_v1 AS (
 identity change_ledger.private_writer_identity_v1, state text, newly_admitted boolean,
 dispatch_cas_id uuid, owner_instance_id text, evidence_ref text, refusal_code text
);
CREATE TYPE change_ledger.private_writer_permit_binding_v1 AS (
 dispatch_intent_id uuid, permit_id uuid, permit_digest text, checkpoint_seq bigint,
 signer_key_id text, signer_key_version text, issued_at timestamptz, expires_at timestamptz
);
-- Exact immutable S12 dispatch context returned only through the evidence-ingest lookup.
CREATE TYPE change_ledger.private_writer_evidence_attempt_v1 AS (
 dispatch_cas_id uuid, dispatch_intent_id uuid, tenant_id text, company_id text,
 organization_ref text, base_fingerprint text, change_id uuid, claim_generation bigint,
 dispatch_generation bigint, call_id uuid, operation_kind text, approval_digest text,
 payload_digest text, permit_id uuid, permit_digest text, expected_target_ref text,
 expected_pre_version text, auth_epoch bigint, repair_authorization_id uuid,
 writer_service_id text, writer_host_id text, writer_process_instance_id text,
 onec_session_instance_id text
);
CREATE TYPE change_ledger.private_writer_dispatch_intent_v1 AS (
 dispatch_intent_id uuid, tenant_id text, company_id text, organization_ref text,
 base_fingerprint text, change_id uuid, claim_generation bigint, dispatch_generation bigint,
 call_id uuid, operation_kind text, approval_digest text, payload_digest text,
 target_ref text, expected_pre_version text, auth_epoch bigint, repair_authorization_id uuid,
 created_at timestamptz
);
CREATE TYPE change_ledger.private_writer_call_snapshot_v1 AS (
 identity change_ledger.private_writer_identity_v1, state text, dispatch_cas_id uuid,
 evidence_ref text, owner_instance_id text
);
CREATE TYPE change_ledger.private_writer_barrier_snapshot_v1 AS (
 scope change_ledger.private_writer_scope_v1, base_fingerprint text, barrier_id uuid,
 expected_current_epoch bigint, epoch bigint, barrier_origin_instance_id text,
 barrier_origin_service_epoch bigint, call_ids uuid[], progress text, acknowledgement_ref text,
 acknowledgement_digest bytea, quiesced_at timestamptz, unresolved_call_ids uuid[]
);
CREATE TYPE change_ledger.private_writer_startup_state_v1 AS (
 service_instance_id text, service_epoch bigint,
 pending_calls change_ledger.private_writer_call_snapshot_v1[],
 open_barriers change_ledger.private_writer_barrier_snapshot_v1[], readiness_ref text
);

CREATE FUNCTION change_ledger.private_writer_assert_transaction_v1() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')='on'
   OR pg_catalog.txid_current_if_assigned() IS NOT NULL THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 -- A granted entry must be the transaction's first ranked-lock participant. In particular,
 -- reject session- or transaction-level advisory locks so callers cannot enter namespace 7
 -- while already holding namespace 6 (or compose multiple top-level scopes in one transaction).
 -- AccessShare is the only allowed relation mode: adapter/type resolution and ordinary reads
 -- may hold it, while every explicit stronger relation lock could block or invert this entry.
 IF EXISTS (
   SELECT 1 FROM pg_catalog.pg_locks l
   WHERE l.pid=pg_catalog.pg_backend_pid() AND l.granted
     AND (
       l.locktype='advisory'
       OR (l.locktype='relation' AND l.mode<>'AccessShareLock'
         AND l.database=(SELECT d.oid FROM pg_catalog.pg_database d
           WHERE d.datname=pg_catalog.current_database()))
     )
 ) THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_assert_transaction_v1() OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_take_switch_fence_v1(p_tenant text,p_company text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF p_tenant IS NULL OR p_tenant='' OR p_company IS NULL OR p_company='' THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 -- Namespace 2 is the legacy kill-switch identity; retain its delimiter encoding exactly.
 PERFORM pg_catalog.pg_advisory_xact_lock_shared(2,pg_catalog.hashtext(p_tenant||':'||p_company));
END $fn$;
ALTER FUNCTION change_ledger.private_writer_take_switch_fence_v1(text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_take_base_fence_v1(p_base text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF p_base IS NULL OR p_base='' OR p_base<>btrim(p_base) THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(8,
  pg_catalog.hashtext('s13-base-writer:v1:'||p_base));
END $fn$;
ALTER FUNCTION change_ledger.private_writer_take_base_fence_v1(text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_take_scope_fence_v1(p_tenant text,p_company text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE scope_key text;
BEGIN
 IF p_tenant IS NULL OR p_tenant='' OR p_company IS NULL OR p_company='' THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 scope_key:='s13-scope:v1:'||octet_length(p_tenant)::text||':'||p_tenant||':'||
  octet_length(p_company)::text||':'||p_company;
 PERFORM pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext(scope_key));
END $fn$;
ALTER FUNCTION change_ledger.private_writer_take_scope_fence_v1(text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_take_global_fences_v1(p_keys text[])
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE k integer;
BEGIN
 -- Barrier snapshot is capped at 200 unresolved calls and includes its own immutable ID.
 -- Keep the whole collision domain in one sorted acquisition plan before any row lock.
 IF p_keys IS NULL OR cardinality(p_keys)>201 OR EXISTS(
   SELECT 1 FROM unnest(p_keys) AS x(lock_key) WHERE lock_key IS NULL OR lock_key='') THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 FOR k IN SELECT DISTINCT pg_catalog.hashtext(lock_key) FROM unnest(p_keys) AS x(lock_key)
   ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(6,k);
 END LOOP;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_take_global_fences_v1(text[]) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_attempt_transition_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE receipt change_ledger.private_writer_evidence%ROWTYPE;
        outcome change_ledger.private_writer_evidence%ROWTYPE;
        completion change_ledger.private_writer_evidence%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF ROW(NEW.dispatch_cas_id,NEW.dispatch_intent_id,NEW.tenant_id,NEW.company_id,
   NEW.organization_ref,NEW.base_fingerprint,NEW.change_id,NEW.claim_generation,
   NEW.dispatch_generation,NEW.call_id,NEW.operation_kind,NEW.approval_digest,NEW.payload_digest,
   NEW.permit_id,NEW.permit_digest,NEW.expected_target_ref,NEW.expected_pre_version,NEW.auth_epoch,
   NEW.repair_authorization_id,NEW."session_user",NEW.writer_service_id,NEW.writer_host_id,
   NEW.writer_process_instance_id,NEW.service_epoch,NEW.onec_session_instance_id,NEW.binding_enabled,
   NEW.created_at)
  IS DISTINCT FROM ROW(OLD.dispatch_cas_id,OLD.dispatch_intent_id,OLD.tenant_id,OLD.company_id,
   OLD.organization_ref,OLD.base_fingerprint,OLD.change_id,OLD.claim_generation,
   OLD.dispatch_generation,OLD.call_id,OLD.operation_kind,OLD.approval_digest,OLD.payload_digest,
   OLD.permit_id,OLD.permit_digest,OLD.expected_target_ref,OLD.expected_pre_version,OLD.auth_epoch,
   OLD.repair_authorization_id,OLD."session_user",OLD.writer_service_id,OLD.writer_host_id,
   OLD.writer_process_instance_id,OLD.service_epoch,OLD.onec_session_instance_id,OLD.binding_enabled,
   OLD.created_at) THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF OLD.com_entry_authorized_at IS NOT NULL
   AND NEW.com_entry_authorized_at IS DISTINCT FROM OLD.com_entry_authorized_at THEN
  RAISE EXCEPTION 'IMMUTABLE_RECORD';
 END IF;
 IF OLD.com_entry_authorized_at IS NULL AND NEW.com_entry_authorized_at IS NOT NULL
   AND (OLD.state<>'POSSIBLY_EXECUTING' OR NEW.state<>'POSSIBLY_EXECUTING'
        OR NEW.invocation_started_at IS DISTINCT FROM OLD.invocation_started_at) THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION';
 END IF;
 IF OLD.state='TERMINAL_WITH_EVIDENCE' OR NEW.state NOT IN ('POSSIBLY_EXECUTING','TERMINAL_WITH_EVIDENCE') THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION';
 END IF;
 IF OLD.state='POSSIBLY_EXECUTING' AND NEW.state='POSSIBLY_EXECUTING'
   AND NOT (OLD.com_entry_authorized_at IS NULL AND NEW.com_entry_authorized_at IS NOT NULL) THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION';
 END IF;
 IF NEW.state='POSSIBLY_EXECUTING' THEN
   IF OLD.state='ACCEPTED_NOT_INVOKED' THEN
    IF NEW.com_entry_authorized_at IS NOT NULL THEN RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION'; END IF;
    NEW.invocation_started_at:=clock_timestamp();
    NEW.terminalized_at:=NULL;
   ELSIF OLD.state='POSSIBLY_EXECUTING' THEN
    -- The earlier one-way COM-entry CAS checks the NULL-to-timestamp change and immutable
    -- invocation start. Do not treat this same-state transition as a second initial invocation.
    IF OLD.com_entry_authorized_at IS NOT NULL OR NEW.com_entry_authorized_at IS NULL THEN
     RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION';
    END IF;
    NEW.terminalized_at:=NULL;
   ELSE
    RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION';
   END IF;
 ELSE
  IF OLD.state NOT IN ('ACCEPTED_NOT_INVOKED','POSSIBLY_EXECUTING') THEN
   RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION';
  END IF;
  IF OLD.state='ACCEPTED_NOT_INVOKED' THEN
   IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
       WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='NO_ENTRY_PROOF'
        AND v.record_type='DISPATCH_NO_ENTRY_RECEIPT_V1'
        AND v.writer_invocation_stage='NOT_INVOKED'
        AND v.writer_result_class='PRE_WRITE_NO_EFFECT'
        AND NOT v.writer_call_returned)
     OR EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id
         AND ae.evidence_purpose IN ('WRITER_RECEIPT','OUTCOME','COMPLETION')) THEN
    RAISE EXCEPTION 'TERMINAL_EVIDENCE_REQUIRED';
   END IF;
  ELSE
   IF OLD.state='POSSIBLY_EXECUTING' AND OLD.com_entry_authorized_at IS NULL
     AND EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='NO_ENTRY_PROOF'
         AND v.record_type='DISPATCH_NO_ENTRY_RECEIPT_V1'
         AND v.writer_invocation_stage='NOT_INVOKED'
         AND v.writer_result_class='PRE_WRITE_NO_EFFECT'
         AND NOT v.writer_call_returned)
     AND NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id
         AND ae.evidence_purpose IN ('WRITER_RECEIPT','OUTCOME','COMPLETION')) THEN
    NULL;
   ELSE
   IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='WRITER_RECEIPT'
         AND v.record_type='DISPATCH_RECEIPT_V1'
         AND v.writer_result_class IN ('CALL_RETURNED_SUCCESS','CONDITIONAL_VERSION_CONFLICT'))
      OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='OUTCOME'
         AND v.record_type IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3'))
      OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='COMPLETION'
         AND v.record_type='COMPLETION_PROOF_V1') THEN
    RAISE EXCEPTION 'TERMINAL_EVIDENCE_REQUIRED';
   END IF;
   SELECT v.* INTO receipt FROM change_ledger.private_writer_attempt_evidence ae
    JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
    WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='WRITER_RECEIPT';
   SELECT v.* INTO outcome FROM change_ledger.private_writer_attempt_evidence ae
    JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
    WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='OUTCOME';
   SELECT v.* INTO completion FROM change_ledger.private_writer_attempt_evidence ae
    JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
    WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='COMPLETION';
   IF receipt.writer_result_class='CALL_RETURNED_SUCCESS' THEN
    -- This guard closes the physical writer attempt, not the business attribution decision.
    -- T16 may still need its independent witness before an UNATTRIBUTED effect is finalized.
    IF OLD.com_entry_authorized_at IS NULL
      OR receipt.writer_invocation_stage NOT IN ('ENTERED','INVOKED')
      OR receipt.writer_call_returned IS NOT TRUE
      OR receipt.writer_returned_at IS NULL
      OR outcome.record_type NOT IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3')
      OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
      OR outcome.outcome_observation_complete IS NOT TRUE
      OR outcome.outcome_reader_health IS DISTINCT FROM 'HEALTHY'
      OR outcome.outcome_effect_presence IS NULL
      OR outcome.outcome_effect_presence NOT IN ('PRESENT','ABSENT')
      OR (outcome.outcome_effect_presence='PRESENT' AND
          (outcome.outcome_effect_identity IS DISTINCT FROM 'MATCH'
           OR outcome.outcome_fields_match IS NOT TRUE
           OR outcome.outcome_movements_match IS NOT TRUE
           OR outcome.outcome_observed_version IS DISTINCT FROM receipt.writer_returned_version
           OR outcome.outcome_target_ref IS DISTINCT FROM receipt.writer_returned_target_ref
           OR outcome.outcome_expected_effect_digest IS DISTINCT FROM outcome.outcome_observed_effect_digest
           OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
           OR outcome.outcome_attribution_result IS NULL
           OR outcome.outcome_attribution_result NOT IN ('PROVEN','UNATTRIBUTED')))
      OR (outcome.outcome_effect_presence='ABSENT' AND
          (outcome.outcome_effect_identity IS DISTINCT FROM 'NO_GOVERNED_EFFECT'
           OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
           OR outcome.outcome_attribution_result IS DISTINCT FROM 'COMPETING_WRITER'))
      OR outcome.outcome_uncertainty_count IS DISTINCT FROM 0
      OR outcome.outcome_completion_proof_class IS DISTINCT FROM completion.completion_proof_class
      OR completion.record_type<>'COMPLETION_PROOF_V1'
      OR completion.completion_proof_class<>'WRITER_CALL_RETURNED'
      OR completion.process_instance_id IS DISTINCT FROM OLD.writer_process_instance_id
      OR (OLD.operation_kind='CREATE_DRAFT' AND
          (receipt.target_ref IS NOT NULL OR receipt.pre_version IS NOT NULL
           OR outcome.outcome_pre_version IS NOT NULL))
      OR (OLD.operation_kind IN ('POST','UNPOST') AND
          (receipt.target_ref IS DISTINCT FROM OLD.expected_target_ref
           OR receipt.pre_version IS DISTINCT FROM OLD.expected_pre_version
           OR outcome.outcome_pre_version IS DISTINCT FROM OLD.expected_pre_version
           OR (outcome.outcome_effect_presence='PRESENT' AND
              (outcome.outcome_target_ref IS DISTINCT FROM OLD.expected_target_ref
               OR outcome.outcome_observed_version=OLD.expected_pre_version
               OR outcome.outcome_version_relation IS DISTINCT FROM 'ADVANCED')))) THEN
     RAISE EXCEPTION 'TERMINAL_EVIDENCE_REJECTED';
    END IF;
   ELSIF receipt.writer_result_class='CONDITIONAL_VERSION_CONFLICT' THEN
    IF receipt.writer_invocation_stage<>'ENTERED' OR NOT receipt.writer_call_returned
      OR OLD.operation_kind NOT IN ('POST','UNPOST')
      OR receipt.writer_returned_target_ref IS NOT NULL OR receipt.writer_returned_version IS NOT NULL
      OR outcome.record_type<>'OUTCOME_EVIDENCE_V3'
      OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
      OR outcome.outcome_pre_version IS DISTINCT FROM OLD.expected_pre_version
      OR outcome.outcome_observation_complete IS NOT TRUE
      OR outcome.outcome_effect_presence<>'ABSENT'
      OR outcome.outcome_effect_identity<>'NO_GOVERNED_EFFECT'
      OR outcome.outcome_attribution_result<>'COMPETING_WRITER'
      OR outcome.outcome_version_relation<>'DIFFERENT_COMPETING_WRITER'
      OR outcome.outcome_observed_version=OLD.expected_pre_version
      OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
      OR outcome.outcome_uncertainty_count<>0
      OR outcome.outcome_completion_proof_class IS DISTINCT FROM completion.completion_proof_class
      OR outcome.outcome_completion_proof_digest IS DISTINCT FROM completion.record_digest
      OR completion.record_type<>'COMPLETION_PROOF_V1' THEN
     RAISE EXCEPTION 'TERMINAL_EVIDENCE_REJECTED';
    END IF;
   END IF;
   IF EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='WRITER_RECEIPT'
         AND v.writer_result_class='CONDITIONAL_VERSION_CONFLICT')
      AND (NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='POST_COMPLETION_CHALLENGE'
         AND v.record_type='POST_COMPLETION_CHALLENGE_V1')
       OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
        JOIN change_ledger.private_writer_evidence v ON v.evidence_ref=ae.evidence_ref
        WHERE ae.dispatch_cas_id=OLD.dispatch_cas_id AND ae.evidence_purpose='READ_ATTESTATION'
         AND v.record_type='POST_COMPLETION_READ_ATTESTATION_V1')) THEN
    RAISE EXCEPTION 'TERMINAL_EVIDENCE_REQUIRED';
   END IF;
   END IF;
  END IF;
  NEW.invocation_started_at:=OLD.invocation_started_at;
  NEW.terminalized_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_attempt_transition_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_attempt_transition_guard
 BEFORE UPDATE OR DELETE ON change_ledger.dispatch_attempts
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_attempt_transition_guard_v1();

CREATE FUNCTION change_ledger.private_writer_barrier_transition_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF ROW(NEW.barrier_id,NEW.base_fingerprint,NEW.tenant_id,NEW.company_id,
   NEW.expected_current_epoch,NEW.epoch,NEW.barrier_origin_instance_id,NEW.barrier_origin_service_epoch,
   NEW.created_at)
  IS DISTINCT FROM ROW(OLD.barrier_id,OLD.base_fingerprint,OLD.tenant_id,OLD.company_id,
   OLD.expected_current_epoch,OLD.epoch,OLD.barrier_origin_instance_id,OLD.barrier_origin_service_epoch,
   OLD.created_at) THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF OLD.progress<>'CLOSED_WITH_HOLD' OR NEW.progress<>'QUIESCED'
   OR OLD.acknowledgement_ref IS NOT NULL OR OLD.acknowledgement_digest IS NOT NULL
   OR NEW.acknowledgement_ref IS NULL OR NEW.acknowledgement_digest IS NULL
   OR NOT EXISTS(SELECT 1 FROM change_ledger.writer_barrier_acknowledgements a
      WHERE a.barrier_id=OLD.barrier_id AND a.acknowledgement_ref=NEW.acknowledgement_ref
       AND a.signed_bytes_sha256=NEW.acknowledgement_digest)
   OR EXISTS(SELECT 1 FROM change_ledger.writer_barrier_calls c
      JOIN change_ledger.dispatch_attempts d ON d.dispatch_cas_id=c.dispatch_cas_id
      WHERE c.barrier_id=OLD.barrier_id AND d.state<>'TERMINAL_WITH_EVIDENCE') THEN
  RAISE EXCEPTION 'BARRIER_CONFLICT';
 END IF;
 NEW.quiesced_at:=clock_timestamp();
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_barrier_transition_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_barrier_transition_guard
 BEFORE UPDATE OR DELETE ON change_ledger.writer_barriers
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_barrier_transition_guard_v1();

CREATE FUNCTION change_ledger.private_writer_base_slot_transition_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE d change_ledger.dispatch_attempts%ROWTYPE; b change_ledger.writer_barriers%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF NEW.base_fingerprint IS DISTINCT FROM OLD.base_fingerprint THEN RAISE EXCEPTION 'IMMUTABLE_RECORD'; END IF;
 IF OLD.active_dispatch_cas_id IS NOT NULL AND NEW.active_dispatch_cas_id IS NULL THEN
  SELECT * INTO d FROM change_ledger.dispatch_attempts
   WHERE dispatch_cas_id=OLD.active_dispatch_cas_id AND base_fingerprint=OLD.base_fingerprint;
  IF NOT FOUND OR d.state<>'TERMINAL_WITH_EVIDENCE' THEN RAISE EXCEPTION 'PHYSICAL_CALL_STILL_HELD'; END IF;
 ELSIF OLD.active_dispatch_cas_id IS NOT NULL
   AND NEW.active_dispatch_cas_id IS DISTINCT FROM OLD.active_dispatch_cas_id THEN
  RAISE EXCEPTION 'PHYSICAL_CALL_STILL_HELD';
 END IF;
 IF OLD.open_barrier_id IS NOT NULL AND NEW.open_barrier_id IS NULL THEN
  SELECT * INTO b FROM change_ledger.writer_barriers
   WHERE barrier_id=OLD.open_barrier_id AND base_fingerprint=OLD.base_fingerprint;
  IF NOT FOUND OR b.progress<>'QUIESCED' THEN RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED'; END IF;
 ELSIF OLD.open_barrier_id IS NOT NULL AND NEW.open_barrier_id IS DISTINCT FROM OLD.open_barrier_id THEN
  RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED';
 END IF;
 IF OLD.admission_closed AND NOT NEW.admission_closed AND OLD.open_barrier_id IS NOT NULL
   AND NEW.open_barrier_id IS NOT NULL THEN RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED'; END IF;
 RETURN NEW;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_base_slot_transition_guard_v1() OWNER TO ledger_owner;
CREATE TRIGGER private_writer_base_slot_transition_guard
 BEFORE UPDATE OR DELETE ON change_ledger.physical_base_slots
 FOR EACH ROW EXECUTE FUNCTION change_ledger.private_writer_base_slot_transition_guard_v1();

CREATE FUNCTION change_ledger.private_writer_lookup_v1(
 p_identity change_ledger.private_writer_identity_v1
) RETURNS change_ledger.private_writer_call_snapshot_v1
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a change_ledger.dispatch_attempts%ROWTYPE; receipt text;
BEGIN
 IF p_identity.call_id IS NULL OR p_identity.change_id IS NULL OR p_identity.generation IS NULL
    OR p_identity.base_fingerprint IS NULL OR p_identity.host_id IS NULL THEN
  RAISE EXCEPTION 'NOT_ACCEPTED';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_service_bindings b
   WHERE b."session_user"=session_user AND b.base_fingerprint=p_identity.base_fingerprint
    AND b.writer_host_id=p_identity.host_id AND b.binding_enabled AND b.revoked_at IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.call_id=p_identity.call_id AND x.base_fingerprint=p_identity.base_fingerprint;
 IF NOT FOUND THEN
   -- The lookup boundary is scoped to the authenticated base. Do not turn a foreign-base
   -- call_id into an existence oracle; admission still fails closed on the global unique key.
  RAISE EXCEPTION 'NOT_ACCEPTED';
 END IF;
 IF ROW(a.tenant_id,a.company_id,a.organization_ref,a.change_id,a.claim_generation,a.call_id,
       a.operation_kind,a.expected_target_ref,a.expected_pre_version,a.auth_epoch,a.payload_digest,
       a.permit_id::text,a.permit_digest,a.base_fingerprint,a.writer_host_id,a.repair_authorization_id)
    IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
       p_identity.change_id,p_identity.generation,p_identity.call_id,p_identity.operation,
       p_identity.target_ref,p_identity.target_version,p_identity.epoch,p_identity.payload_digest,
       p_identity.permit_id,p_identity.permit_digest,p_identity.base_fingerprint,p_identity.host_id,
       CASE WHEN p_identity.repair_authorization_id IS NULL THEN NULL::uuid
            ELSE p_identity.repair_authorization_id::uuid END) THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT';
 END IF;
 SELECT e.evidence_ref INTO receipt FROM change_ledger.private_writer_attempt_evidence e
  WHERE e.dispatch_cas_id=a.dispatch_cas_id
  ORDER BY CASE e.evidence_purpose WHEN 'WRITER_RECEIPT' THEN 0 WHEN 'OUTCOME' THEN 1 ELSE 2 END,
   e.recorded_at, e.evidence_ref LIMIT 1;
 RETURN ROW(p_identity,a.state,a.dispatch_cas_id,receipt,
   CASE WHEN a.state='POSSIBLY_EXECUTING' THEN a.writer_process_instance_id ELSE NULL END)
   ::change_ledger.private_writer_call_snapshot_v1;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_lookup_v1(change_ledger.private_writer_identity_v1)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_lookup_barrier_v1(p_barrier_id uuid)
RETURNS change_ledger.private_writer_barrier_snapshot_v1
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE b change_ledger.writer_barriers%ROWTYPE; calls uuid[]; unresolved uuid[];
BEGIN
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_service_bindings x
   WHERE x."session_user"=session_user AND x.binding_enabled AND x.revoked_at IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 SELECT * INTO b FROM change_ledger.writer_barriers WHERE barrier_id=p_barrier_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_service_bindings x
   WHERE x."session_user"=session_user AND x.base_fingerprint=b.base_fingerprint
    AND x.binding_enabled AND x.revoked_at IS NULL) THEN
   -- A foreign-base barrier ID must be indistinguishable from an absent ID to this binding.
   RETURN NULL;
 END IF;
 SELECT coalesce(array_agg(c.call_id ORDER BY c.call_id),ARRAY[]::uuid[]),
        coalesce(array_agg(c.call_id ORDER BY c.call_id) FILTER(WHERE a.state<>'TERMINAL_WITH_EVIDENCE'),
                 ARRAY[]::uuid[])
  INTO calls,unresolved
  FROM change_ledger.writer_barrier_calls c
  JOIN change_ledger.dispatch_attempts a ON a.dispatch_cas_id=c.dispatch_cas_id
  WHERE c.barrier_id=b.barrier_id;
 RETURN ROW(ROW(b.tenant_id,b.company_id)::change_ledger.private_writer_scope_v1,
  b.base_fingerprint,b.barrier_id,b.expected_current_epoch,b.epoch,b.barrier_origin_instance_id,
  b.barrier_origin_service_epoch,calls,b.progress,b.acknowledgement_ref,b.acknowledgement_digest,
  b.quiesced_at,unresolved)::change_ledger.private_writer_barrier_snapshot_v1;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_lookup_barrier_v1(uuid) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_startup_recovery_state_v1(p_instance_id text)
RETURNS change_ledger.private_writer_startup_state_v1
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE binding change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        prior change_ledger.private_writer_service_instance_history%ROWTYPE;
        binding_count integer; next_epoch bigint; pending change_ledger.private_writer_call_snapshot_v1[];
        barriers change_ledger.private_writer_barrier_snapshot_v1[]; ready_ref uuid;
        pending_count bigint; barrier_count bigint; barrier_call_count bigint;
        same_instance boolean:=false;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_instance_id IS NULL OR p_instance_id !~
   '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 SELECT count(*) INTO binding_count FROM change_ledger.private_writer_service_bindings b
  WHERE b."session_user"=session_user AND b.binding_enabled AND b.revoked_at IS NULL;
 IF binding_count<>1 THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO binding FROM change_ledger.private_writer_service_bindings b
  WHERE b."session_user"=session_user AND b.binding_enabled AND b.revoked_at IS NULL;
 PERFORM pg_catalog.pg_advisory_xact_lock(8,
  pg_catalog.hashtext('s13-base-writer:v1:'||binding.base_fingerprint));
 SELECT count(*) INTO pending_count FROM (
  SELECT 1 FROM change_ledger.dispatch_attempts a
   WHERE a.base_fingerprint=binding.base_fingerprint AND a.state<>'TERMINAL_WITH_EVIDENCE'
   LIMIT 201
 ) bounded_pending;
 SELECT count(*) INTO barrier_count FROM (
  SELECT 1 FROM change_ledger.writer_barriers b
   WHERE b.base_fingerprint=binding.base_fingerprint AND b.progress='CLOSED_WITH_HOLD'
   LIMIT 201
 ) bounded_barriers;
 SELECT count(*) INTO barrier_call_count FROM (
  SELECT 1 FROM change_ledger.writer_barrier_calls c
   JOIN change_ledger.writer_barriers b ON b.barrier_id=c.barrier_id
   WHERE b.base_fingerprint=binding.base_fingerprint AND b.progress='CLOSED_WITH_HOLD'
   LIMIT 201
 ) bounded_barrier_calls;
 IF pending_count+barrier_count+barrier_call_count>200 THEN
  RAISE EXCEPTION 'STARTUP_RECOVERY_INVENTORY_LIMIT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences s
  WHERE s.writer_service_id=binding.writer_service_id AND s.base_fingerprint=binding.base_fingerprint
  FOR UPDATE;
 SELECT * INTO prior FROM change_ledger.private_writer_service_instance_history h
  WHERE h.writer_service_id=binding.writer_service_id AND h.base_fingerprint=binding.base_fingerprint
   AND h.service_instance_id=p_instance_id;
 IF FOUND THEN
  IF NOT FOUND OR serving.service_instance_id IS DISTINCT FROM p_instance_id
    OR serving.service_epoch IS DISTINCT FROM prior.service_epoch THEN
   RAISE EXCEPTION 'STALE_EPOCH';
  END IF;
  next_epoch:=prior.service_epoch;
  same_instance:=true;
 ELSE
  next_epoch:=CASE WHEN serving.service_epoch IS NULL THEN 1 ELSE serving.service_epoch+1 END;
  INSERT INTO change_ledger.private_writer_service_instance_history
   (writer_service_id,base_fingerprint,service_instance_id,service_epoch)
  VALUES(binding.writer_service_id,binding.base_fingerprint,p_instance_id,next_epoch);
  INSERT INTO change_ledger.private_writer_serving_fences
   (writer_service_id,base_fingerprint,"session_user",writer_host_id,binding_enabled,
    service_instance_id,service_epoch,started_at,readiness_ref)
  VALUES(binding.writer_service_id,binding.base_fingerprint,binding."session_user",binding.writer_host_id,
    binding.binding_enabled,p_instance_id,next_epoch,clock_timestamp(),NULL)
  ON CONFLICT(writer_service_id,base_fingerprint) DO UPDATE SET
   "session_user"=EXCLUDED."session_user",writer_host_id=EXCLUDED.writer_host_id,
   binding_enabled=EXCLUDED.binding_enabled,service_instance_id=EXCLUDED.service_instance_id,
   service_epoch=EXCLUDED.service_epoch,started_at=EXCLUDED.started_at,readiness_ref=NULL;
 END IF;
 SELECT coalesce(array_agg(ROW(
   ROW(a.tenant_id,a.company_id,a.organization_ref,a.change_id,a.claim_generation,a.call_id,
    a.operation_kind,a.expected_target_ref,a.expected_pre_version,a.auth_epoch,a.payload_digest,
    a.permit_id::text,a.permit_digest,a.base_fingerprint,a.writer_host_id,
    a.repair_authorization_id::text)::change_ledger.private_writer_identity_v1,
   a.state,a.dispatch_cas_id,
   (SELECT e.evidence_ref FROM change_ledger.private_writer_attempt_evidence e
     WHERE e.dispatch_cas_id=a.dispatch_cas_id
     ORDER BY CASE e.evidence_purpose WHEN 'WRITER_RECEIPT' THEN 0 WHEN 'OUTCOME' THEN 1 ELSE 2 END,
      e.recorded_at,e.evidence_ref LIMIT 1),
   CASE WHEN a.state='POSSIBLY_EXECUTING' THEN a.writer_process_instance_id ELSE NULL END
  )::change_ledger.private_writer_call_snapshot_v1 ORDER BY a.call_id),
  ARRAY[]::change_ledger.private_writer_call_snapshot_v1[])
 INTO pending FROM change_ledger.dispatch_attempts a
 WHERE a.base_fingerprint=binding.base_fingerprint AND a.state<>'TERMINAL_WITH_EVIDENCE';
 SELECT coalesce(array_agg(ROW(
   ROW(b.tenant_id,b.company_id)::change_ledger.private_writer_scope_v1,
   b.base_fingerprint,b.barrier_id,b.expected_current_epoch,b.epoch,b.barrier_origin_instance_id,
   b.barrier_origin_service_epoch,
   coalesce((SELECT array_agg(c.call_id ORDER BY c.call_id)
    FROM change_ledger.writer_barrier_calls c WHERE c.barrier_id=b.barrier_id),ARRAY[]::uuid[]),
   b.progress,b.acknowledgement_ref,b.acknowledgement_digest,b.quiesced_at,
   coalesce((SELECT array_agg(c.call_id ORDER BY c.call_id)
    FROM change_ledger.writer_barrier_calls c JOIN change_ledger.dispatch_attempts a
     ON a.dispatch_cas_id=c.dispatch_cas_id
    WHERE c.barrier_id=b.barrier_id AND a.state<>'TERMINAL_WITH_EVIDENCE'),ARRAY[]::uuid[])
  )::change_ledger.private_writer_barrier_snapshot_v1 ORDER BY b.barrier_id),
  ARRAY[]::change_ledger.private_writer_barrier_snapshot_v1[])
 INTO barriers FROM change_ledger.writer_barriers b
 WHERE b.base_fingerprint=binding.base_fingerprint AND b.progress='CLOSED_WITH_HOLD';
 ready_ref:=CASE WHEN cardinality(pending)=0 AND cardinality(barriers)=0
  THEN CASE WHEN same_instance THEN coalesce(serving.readiness_ref,pg_catalog.gen_random_uuid())
       ELSE pg_catalog.gen_random_uuid() END ELSE NULL END;
 UPDATE change_ledger.private_writer_serving_fences
  SET readiness_ref=ready_ref WHERE writer_service_id=binding.writer_service_id
   AND base_fingerprint=binding.base_fingerprint;
 RETURN ROW(p_instance_id,next_epoch,pending,barriers,ready_ref)
  ::change_ledger.private_writer_startup_state_v1;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_startup_recovery_state_v1(text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_refusal_v1(
 p_identity change_ledger.private_writer_identity_v1,p_code text
) RETURNS change_ledger.private_writer_admission_decision_v1
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT ROW(p_identity,'NOT_ACCEPTED',false,NULL::uuid,NULL::text,NULL::text,p_code)
  ::change_ledger.private_writer_admission_decision_v1
$fn$;
ALTER FUNCTION change_ledger.private_writer_refusal_v1(change_ledger.private_writer_identity_v1,text)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_admit_v1(
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
ALTER FUNCTION change_ledger.private_writer_admit_v1(
 change_ledger.private_writer_identity_v1,text,bigint) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_mark_invoking_v1(
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
ALTER FUNCTION change_ledger.private_writer_mark_invoking_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_begin_com_entry_v1(
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
ALTER FUNCTION change_ledger.private_writer_begin_com_entry_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_issue_permit_v1(
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
ALTER FUNCTION change_ledger.private_writer_issue_permit_v1(
 text,text,uuid,bigint,uuid,uuid,text,text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.change_ledger_begin_apply_v1(
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
 INSERT INTO change_ledger.dispatch_permits(change_id,generation,state,call_id,writer_host,onec_session)
 VALUES(rec.change_id,tok.generation,'NOT_PERMITTED',p_call_id,p_writer_host,p_onec_session)
 ON CONFLICT(change_id,generation) DO NOTHING;
 SELECT * INTO dp FROM change_ledger.dispatch_permits x
  WHERE x.change_id=rec.change_id AND x.generation=tok.generation FOR UPDATE;
 IF NOT FOUND OR dp.call_id IS DISTINCT FROM p_call_id OR dp.writer_host IS DISTINCT FROM p_writer_host
   OR dp.onec_session IS DISTINCT FROM p_onec_session OR dp.state<>'NOT_PERMITTED' THEN
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
ALTER FUNCTION change_ledger.change_ledger_begin_apply_v1(text,text,uuid,uuid,text,text)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_dispatch_intent_for_call_v1(
 p_tenant text,p_company text,p_call_id uuid
)
RETURNS change_ledger.private_writer_dispatch_intent_v1
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE i change_ledger.private_writer_dispatch_intents%ROWTYPE; requester text; caller text;
BEGIN
 IF p_call_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.assert_scope(p_tenant,p_company);
 caller:=change_ledger.caller_role();
 SELECT x.* INTO i FROM change_ledger.private_writer_dispatch_intents x
  WHERE x.tenant_id=p_tenant AND x.company_id=p_company AND x.call_id=p_call_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT r.requester INTO requester FROM change_ledger.records r
  WHERE r.tenant_id=p_tenant AND r.company_id=p_company AND r.change_id=i.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 IF caller IS DISTINCT FROM requester AND NOT pg_has_role(caller::name,'writer_role','USAGE')
   AND NOT pg_has_role(caller::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 RETURN ROW(i.dispatch_intent_id,i.tenant_id,i.company_id,i.organization_ref,i.base_fingerprint,
  i.change_id,i.claim_generation,i.dispatch_generation,i.call_id,i.operation_kind,i.approval_digest,
  i.payload_digest,i.target_ref,i.expected_pre_version,i.auth_epoch,i.repair_authorization_id,i.created_at)
  ::change_ledger.private_writer_dispatch_intent_v1;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_dispatch_intent_for_call_v1(text,text,uuid)
 OWNER TO ledger_owner;

-- Candidate exact-attempt lookup for evidence ingestion. Its ACL stays withheld until independent
-- database/security review accepts its enumeration and cross-scope disclosure boundary.
CREATE FUNCTION change_ledger.private_writer_evidence_attempt_v1(
 p_dispatch_cas_id uuid,p_call_id uuid,p_tenant_id text,p_company_id text,
 p_organization_ref text,p_base_fingerprint text
) RETURNS change_ledger.private_writer_evidence_attempt_v1
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE a change_ledger.dispatch_attempts%ROWTYPE;
BEGIN
 IF SESSION_USER<>'private_writer_evidence_ingest' THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_call_id IS NULL OR p_tenant_id IS NULL OR p_tenant_id=''
   OR p_tenant_id<>btrim(p_tenant_id) OR pg_catalog.octet_length(p_tenant_id)>2048
   OR p_tenant_id ~ '[[:cntrl:]]' OR p_company_id IS NULL OR p_company_id=''
   OR p_company_id<>btrim(p_company_id) OR pg_catalog.octet_length(p_company_id)>2048
   OR p_company_id ~ '[[:cntrl:]]' OR p_organization_ref IS NULL OR p_organization_ref=''
   OR p_organization_ref<>btrim(p_organization_ref)
   OR pg_catalog.octet_length(p_organization_ref)>2048
   OR p_organization_ref ~ '[[:cntrl:]]' OR p_base_fingerprint IS NULL
   OR p_base_fingerprint !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT x.* INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id AND x.call_id=p_call_id
   AND x.tenant_id=p_tenant_id AND x.company_id=p_company_id
   AND x.organization_ref=p_organization_ref AND x.base_fingerprint=p_base_fingerprint
  LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF pg_catalog.octet_length(a.tenant_id)>2048 OR pg_catalog.octet_length(a.company_id)>2048
   OR pg_catalog.octet_length(a.organization_ref)>2048
   OR pg_catalog.octet_length(a.expected_target_ref)>2048
   OR pg_catalog.octet_length(a.expected_pre_version)>2048
   OR pg_catalog.octet_length(a.writer_service_id)>2048
   OR pg_catalog.octet_length(a.writer_host_id)>2048
   OR pg_catalog.octet_length(a.writer_process_instance_id)>2048
   OR coalesce(pg_catalog.octet_length(a.onec_session_instance_id),0)>2048 THEN
  RAISE EXCEPTION 'EVIDENCE_ATTEMPT_CONTEXT_INVALID' USING ERRCODE='P0001';
 END IF;
 RETURN ROW(a.dispatch_cas_id,a.dispatch_intent_id,a.tenant_id,a.company_id,
  a.organization_ref,a.base_fingerprint,a.change_id,a.claim_generation,a.dispatch_generation,
  a.call_id,a.operation_kind,a.approval_digest,a.payload_digest,a.permit_id,a.permit_digest,
  a.expected_target_ref,a.expected_pre_version,a.auth_epoch,a.repair_authorization_id,
  a.writer_service_id,a.writer_host_id,a.writer_process_instance_id,a.onec_session_instance_id)
  ::change_ledger.private_writer_evidence_attempt_v1;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_evidence_attempt_v1(uuid,uuid,text,text,text,text)
 OWNER TO ledger_owner;

-- Candidate bounded lookup for previously registered immutable evidence. The function returns
-- only exact requested envelopes for one complete attempt selector; it never grants table access.
-- EXECUTE remains withheld until independent database/security review accepts enumeration scope.
CREATE FUNCTION change_ledger.private_writer_load_evidence_records_v1(
 p_dispatch_cas_id uuid,p_call_id uuid,p_tenant_id text,p_company_id text,
 p_organization_ref text,p_base_fingerprint text,p_change_id uuid,
 p_claim_generation bigint,p_operation_kind text,p_evidence_refs text[]
) RETURNS TABLE(evidence_ref text,record_type text,signed_bytes bytea)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE returned_count integer;
BEGIN
 IF SESSION_USER<>'private_writer_evidence_ingest' THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_dispatch_cas_id IS NULL OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_call_id IS NULL OR p_call_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_claim_generation IS NULL OR p_claim_generation<=0
   OR p_tenant_id IS NULL OR p_tenant_id='' OR p_tenant_id<>btrim(p_tenant_id)
   OR pg_catalog.octet_length(p_tenant_id)>2048 OR p_tenant_id ~ '[[:cntrl:]]'
   OR p_company_id IS NULL OR p_company_id='' OR p_company_id<>btrim(p_company_id)
   OR pg_catalog.octet_length(p_company_id)>2048 OR p_company_id ~ '[[:cntrl:]]'
   OR p_organization_ref IS NULL OR p_organization_ref=''
   OR p_organization_ref<>btrim(p_organization_ref)
   OR pg_catalog.octet_length(p_organization_ref)>2048 OR p_organization_ref ~ '[[:cntrl:]]'
   OR p_base_fingerprint IS NULL OR p_base_fingerprint !~ '^[a-f0-9]{64}$'
   OR p_operation_kind IS NULL OR p_operation_kind NOT IN ('CREATE_DRAFT','POST','UNPOST')
   OR p_evidence_refs IS NULL OR pg_catalog.cardinality(p_evidence_refs) NOT BETWEEN 1 AND 5
   OR pg_catalog.array_ndims(p_evidence_refs)<>1
   OR pg_catalog.array_lower(p_evidence_refs,1)<>1
   OR EXISTS (SELECT 1 FROM pg_catalog.unnest(p_evidence_refs) AS u(ref)
              WHERE u.ref IS NULL OR u.ref='' OR u.ref<>pg_catalog.btrim(u.ref)
                OR pg_catalog.octet_length(u.ref)>256 OR u.ref ~ '[[:cntrl:]]')
   OR (SELECT pg_catalog.count(DISTINCT u.ref)
         FROM pg_catalog.unnest(p_evidence_refs) AS u(ref))
      <> pg_catalog.cardinality(p_evidence_refs) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT EXISTS (
   SELECT 1 FROM change_ledger.dispatch_attempts a
    WHERE a.dispatch_cas_id=p_dispatch_cas_id AND a.call_id=p_call_id
      AND a.tenant_id=p_tenant_id AND a.company_id=p_company_id
      AND a.organization_ref=p_organization_ref AND a.base_fingerprint=p_base_fingerprint
      AND a.change_id=p_change_id AND a.claim_generation=p_claim_generation
      AND a.operation_kind=p_operation_kind
 ) THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 RETURN QUERY
  SELECT e.evidence_ref,e.record_type,e.signed_bytes
   FROM change_ledger.private_writer_evidence e
   JOIN change_ledger.dispatch_attempts a
     ON a.dispatch_cas_id=e.dispatch_cas_id AND a.dispatch_intent_id=e.dispatch_intent_id
    AND a.call_id=e.call_id AND a.dispatch_generation=e.dispatch_generation
    AND a.tenant_id=e.tenant_id AND a.company_id=e.company_id
    AND a.organization_ref=e.organization_ref AND a.base_fingerprint=e.base_fingerprint
    AND a.change_id=e.change_id AND a.claim_generation=e.claim_generation
    AND a.operation_kind=e.operation_kind AND a.approval_digest=e.approval_digest
    AND a.payload_digest=e.payload_digest AND a.permit_id=e.permit_id
    AND a.permit_digest=e.permit_digest AND a.auth_epoch=e.auth_epoch
    AND a.repair_authorization_id IS NOT DISTINCT FROM e.repair_authorization_id
    AND a.expected_target_ref IS NOT DISTINCT FROM e.target_ref
    AND a.expected_pre_version IS NOT DISTINCT FROM e.pre_version
   WHERE e.evidence_ref=ANY(p_evidence_refs)
     AND a.dispatch_cas_id=p_dispatch_cas_id AND a.call_id=p_call_id
     AND a.tenant_id=p_tenant_id AND a.company_id=p_company_id
     AND a.organization_ref=p_organization_ref AND a.base_fingerprint=p_base_fingerprint
     AND a.change_id=p_change_id AND a.claim_generation=p_claim_generation
     AND a.operation_kind=p_operation_kind
     AND e.dispatch_cas_id=p_dispatch_cas_id AND e.call_id=p_call_id
     AND e.tenant_id=p_tenant_id AND e.company_id=p_company_id
     AND e.organization_ref=p_organization_ref AND e.base_fingerprint=p_base_fingerprint
     AND e.change_id=p_change_id AND e.claim_generation=p_claim_generation
     AND e.operation_kind=p_operation_kind
     AND pg_catalog.octet_length(e.signed_bytes)<=2097152
   ORDER BY pg_catalog.array_position(p_evidence_refs,e.evidence_ref);
 GET DIAGNOSTICS returned_count=ROW_COUNT;
 IF returned_count<>pg_catalog.cardinality(p_evidence_refs) THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_load_evidence_records_v1(
 uuid,uuid,text,text,text,text,uuid,bigint,text,text[]) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_permit_binding_for_intent_v1(
 p_tenant text,p_company text,p_dispatch_intent_id uuid
)
RETURNS change_ledger.private_writer_permit_binding_v1
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE intent change_ledger.private_writer_dispatch_intents%ROWTYPE;
        binding change_ledger.private_writer_permit_bindings%ROWTYPE;
        caller text;
BEGIN
 IF p_dispatch_intent_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.assert_scope(p_tenant,p_company);
 SELECT * INTO intent FROM change_ledger.private_writer_dispatch_intents x
  WHERE x.tenant_id=p_tenant AND x.company_id=p_company
   AND x.dispatch_intent_id=p_dispatch_intent_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 caller:=change_ledger.caller_role();
 IF caller IS NULL OR NOT pg_has_role(caller::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 SELECT * INTO binding FROM change_ledger.private_writer_permit_bindings x
  WHERE x.dispatch_intent_id=p_dispatch_intent_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN ROW(binding.dispatch_intent_id,binding.permit_id,binding.permit_digest,
  binding.checkpoint_seq,binding.signer_key_id,binding.signer_key_version,
  binding.issued_at,binding.expires_at)::change_ledger.private_writer_permit_binding_v1;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_permit_binding_for_intent_v1(text,text,uuid)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_record_terminal_v1(
 p_identity change_ledger.private_writer_identity_v1,
 p_dispatch_cas_id uuid,
 p_instance_id text,
 p_receipt_ref text
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.dispatch_attempts%ROWTYPE;
        b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        e change_ledger.private_writer_evidence%ROWTYPE;
        k change_ledger.private_writer_signer_key_versions%ROWTYPE;
        permit_id uuid; repair_id uuid; prior text;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_instance_id IS NULL OR p_instance_id !~
   '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_receipt_ref IS NULL OR p_receipt_ref=''
   OR p_receipt_ref<>btrim(p_receipt_ref) OR p_identity.call_id IS NULL OR p_identity.change_id IS NULL
   OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 SELECT * INTO hint FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id
   AND x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 SELECT * INTO e FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 IF hint.dispatch_cas_id IS NULL OR e.evidence_ref IS NULL THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=e.signer_key_id AND x.key_version=e.signer_key_version;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;

 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR SHARE;
 IF NOT FOUND OR serving.service_instance_id<>p_instance_id
   OR serving.service_epoch<>hint.service_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(k.public_key,'hex'),17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(hint.change_id::text),
  'call-id:v1:'||lower(hint.call_id::text),
  'dispatch-cas-id:v1:'||lower(hint.dispatch_cas_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_receipt_ref,'UTF8')),'hex')
 ]);
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=e.signer_key_id AND x.key_version=e.signer_key_version FOR SHARE;
 IF NOT FOUND OR k.valid_from>clock_timestamp() OR k.valid_until<=clock_timestamp() THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
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
   OR ROW(e.dispatch_cas_id,e.dispatch_intent_id,e.change_id,e.call_id,e.tenant_id,e.company_id,
      e.organization_ref,e.base_fingerprint,e.operation_kind,e.approval_digest,e.payload_digest,
      e.permit_id,e.permit_digest,e.target_ref,e.pre_version,e.auth_epoch,e.repair_authorization_id)
   IS DISTINCT FROM ROW(a.dispatch_cas_id,a.dispatch_intent_id,a.change_id,a.call_id,a.tenant_id,
      a.company_id,a.organization_ref,a.base_fingerprint,a.operation_kind,a.approval_digest,
      a.payload_digest,a.permit_id,a.permit_digest,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.repair_authorization_id)
   OR e.record_type<>'DISPATCH_RECEIPT_V1' OR e.signer_role<>'writer_receipt'
   OR e.process_instance_id IS DISTINCT FROM a.writer_process_instance_id
   OR e.session_instance_id IS DISTINCT FROM a.onec_session_instance_id
   OR e.signer_key_id IS DISTINCT FROM k.key_id OR e.signer_key_version IS DISTINCT FROM k.key_version THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT x.evidence_ref INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='WRITER_RECEIPT';
 IF FOUND THEN
  IF prior=p_receipt_ref THEN RETURN prior; END IF;
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=a.base_fingerprint FOR UPDATE;
 IF NOT FOUND OR slot.active_dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO e FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id
   AND x.company_id=hint.company_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
   WHERE r.key_id=k.key_id AND r.key_version=k.key_version) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 IF a.state<>'POSSIBLY_EXECUTING' OR a.writer_process_instance_id<>p_instance_id THEN
  RAISE EXCEPTION 'INVALID_ATTEMPT_TRANSITION' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_receipt_ref,'WRITER_RECEIPT');
 -- A receipt proves that the writer returned a signed response, not that the business
 -- operation succeeded or that recovery may release the physical-base slot.
 RETURN p_receipt_ref;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_record_terminal_v1(
 change_ledger.private_writer_identity_v1,uuid,text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_attach_recovered_receipt_v1(
 p_identity change_ledger.private_writer_identity_v1,p_dispatch_cas_id uuid,
 p_active_instance_id text,p_active_service_epoch bigint,p_original_owner_instance_id text,
 p_receipt_ref text
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE hint change_ledger.dispatch_attempts%ROWTYPE;
        b change_ledger.private_writer_service_bindings%ROWTYPE;
        serving change_ledger.private_writer_serving_fences%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        a change_ledger.dispatch_attempts%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        e change_ledger.private_writer_evidence%ROWTYPE;
        k change_ledger.private_writer_signer_key_versions%ROWTYPE;
        prior text; permit_id uuid; repair_id uuid;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_identity IS NULL OR p_dispatch_cas_id IS NULL
   OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid OR p_active_instance_id IS NULL
   OR p_active_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_active_service_epoch IS NULL OR p_active_service_epoch<=0
   OR p_original_owner_instance_id IS NULL OR p_original_owner_instance_id !~
      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
   OR p_receipt_ref IS NULL OR p_receipt_ref='' OR p_receipt_ref<>btrim(p_receipt_ref)
   OR p_identity.permit_id IS NULL
   OR p_identity.permit_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR (p_identity.repair_authorization_id IS NOT NULL AND
       p_identity.repair_authorization_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') THEN
  RAISE EXCEPTION 'CALL_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 permit_id:=p_identity.permit_id::uuid;
 repair_id:=p_identity.repair_authorization_id::uuid;
 SELECT * INTO hint FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id
   AND x.tenant_id=p_identity.tenant_id AND x.company_id=p_identity.company_id;
 SELECT * INTO e FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id;
 IF hint.dispatch_cas_id IS NULL OR e.evidence_ref IS NULL THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=e.signer_key_id AND x.key_version=e.signer_key_version;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 PERFORM change_ledger.private_writer_take_base_fence_v1(hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(hint.tenant_id,hint.company_id);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 SELECT * INTO b FROM change_ledger.private_writer_service_bindings x
  WHERE x."session_user"=SESSION_USER AND x.base_fingerprint=hint.base_fingerprint
   AND x.writer_host_id=hint.writer_host_id AND x.binding_enabled AND x.revoked_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501'; END IF;
 SELECT * INTO serving FROM change_ledger.private_writer_serving_fences x
  WHERE x.writer_service_id=b.writer_service_id AND x.base_fingerprint=b.base_fingerprint
   AND x."session_user"=b."session_user" AND x.writer_host_id=b.writer_host_id FOR SHARE;
 IF NOT FOUND OR serving.service_instance_id<>p_active_instance_id
   OR serving.service_epoch<>p_active_service_epoch THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(k.public_key,'hex'),17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(hint.change_id::text),
  'call-id:v1:'||lower(hint.call_id::text),
  'dispatch-cas-id:v1:'||lower(hint.dispatch_cas_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_receipt_ref,'UTF8')),'hex')
 ]);
 SELECT * INTO k FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=e.signer_key_id AND x.key_version=e.signer_key_version FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO a FROM change_ledger.dispatch_attempts x
  WHERE x.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR ROW(a.tenant_id,a.company_id,a.organization_ref,a.base_fingerprint,a.change_id,
      a.claim_generation,a.call_id,a.operation_kind,a.expected_target_ref,a.expected_pre_version,
      a.auth_epoch,a.payload_digest,a.permit_id::text,a.permit_digest,a.writer_host_id,a.repair_authorization_id)
   IS DISTINCT FROM ROW(p_identity.tenant_id,p_identity.company_id,p_identity.organization_ref,
      p_identity.base_fingerprint,p_identity.change_id,p_identity.generation,p_identity.call_id,
      p_identity.operation,p_identity.target_ref,p_identity.target_version,p_identity.epoch,
      p_identity.payload_digest,p_identity.permit_id,p_identity.permit_digest,p_identity.host_id,repair_id)
   OR a.writer_process_instance_id IS DISTINCT FROM p_original_owner_instance_id
   OR e.dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id
   OR e.dispatch_intent_id IS DISTINCT FROM a.dispatch_intent_id
   OR e.record_type<>'DISPATCH_RECEIPT_V1' OR e.signer_role<>'writer_receipt'
   OR e.process_instance_id IS DISTINCT FROM p_original_owner_instance_id
   OR e.session_instance_id IS DISTINCT FROM a.onec_session_instance_id THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=a.base_fingerprint FOR UPDATE;
 IF NOT FOUND OR slot.active_dispatch_cas_id IS DISTINCT FROM a.dispatch_cas_id
   OR a.state<>'POSSIBLY_EXECUTING' THEN
  RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO prior FROM change_ledger.private_writer_attempt_evidence x
  WHERE x.dispatch_cas_id=a.dispatch_cas_id AND x.evidence_purpose='WRITER_RECEIPT';
 IF FOUND THEN
  IF prior=p_receipt_ref THEN RETURN prior; END IF;
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO e FROM change_ledger.private_writer_evidence x
  WHERE x.evidence_ref=p_receipt_ref AND x.tenant_id=hint.tenant_id
   AND x.company_id=hint.company_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 IF k.valid_from>clock_timestamp() OR k.valid_until<=clock_timestamp()
   OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations x
      WHERE x.key_id=k.key_id AND x.key_version=k.key_version) THEN
  RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.private_writer_attempt_evidence(
  dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose)
 VALUES(a.dispatch_cas_id,a.dispatch_intent_id,p_receipt_ref,'WRITER_RECEIPT');
 RETURN p_receipt_ref;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_attach_recovered_receipt_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_record_verified_success_v1(
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
ALTER FUNCTION change_ledger.private_writer_record_verified_success_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_record_recovered_not_invoked_v1(
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
 SELECT * INTO lf FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id FOR UPDATE;
 IF NOT FOUND OR lf.state NOT IN ('READY','RECOVERING') THEN
  RAISE EXCEPTION 'STALE_EPOCH' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO keyrow FROM change_ledger.private_writer_signer_key_versions x
  WHERE x.key_id=receipt.signer_key_id AND x.key_version=receipt.signer_key_version;
 IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001'; END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(encode(keyrow.public_key,'hex'),17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||lower(hint.change_id::text),
  'call-id:v1:'||lower(hint.call_id::text),
  'dispatch-cas-id:v1:'||lower(hint.dispatch_cas_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(p_receipt_ref,'UTF8')),'hex')
 ]);
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
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=hint.tenant_id AND x.company_id=hint.company_id AND x.change_id=hint.change_id FOR UPDATE;
 IF NOT FOUND OR rec.claim_generation<>hint.claim_generation OR rec.base_fingerprint<>hint.base_fingerprint
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
ALTER FUNCTION change_ledger.private_writer_record_recovered_not_invoked_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_record_recovered_terminal_v1(
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
ALTER FUNCTION change_ledger.private_writer_record_recovered_terminal_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text,text,text,uuid) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_close_and_advance_v1(
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
ALTER FUNCTION change_ledger.private_writer_close_and_advance_v1(
 text,change_ledger.private_writer_scope_v1,bigint,uuid,text,bigint) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_finish_barrier_v1(
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
ALTER FUNCTION change_ledger.private_writer_finish_barrier_v1(
 change_ledger.private_writer_barrier_snapshot_v1,text,text,bigint) OWNER TO ledger_owner;

DO $immut$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'private_writer_service_instance_history','private_writer_signer_key_versions',
  'private_writer_signer_key_scopes','private_writer_signer_key_revocations',
  'private_writer_signer_key_rotations','private_writer_process_attestations',
  'private_writer_oracle_artifacts','private_writer_dispatch_intents','private_writer_permit_bindings',
  'private_writer_evidence','private_writer_attempt_evidence','writer_barrier_calls',
  'writer_barrier_acknowledgements'
 ] LOOP
  EXECUTE format('CREATE TRIGGER s13_immutable BEFORE UPDATE OR DELETE ON change_ledger.%I '
   'FOR EACH ROW EXECUTE FUNCTION change_ledger.reject_immutable_mutation()',tbl);
  EXECUTE format('CREATE TRIGGER s13_no_truncate BEFORE TRUNCATE ON change_ledger.%I '
   'FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation()',tbl);
 END LOOP;
END $immut$;

DO $no_truncate$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'private_writer_service_bindings','private_writer_serving_fences','dispatch_attempts',
  'writer_barriers','physical_base_slots','private_writer_outcome_version_floors',
  'private_writer_trust_registry_revision'
 ] LOOP
  EXECUTE format('CREATE TRIGGER s13_no_truncate BEFORE TRUNCATE ON change_ledger.%I '
   'FOR EACH STATEMENT EXECUTE FUNCTION change_ledger.reject_immutable_mutation()',tbl);
 END LOOP;
END $no_truncate$;

-- Requester-owned S13 epoch-dependency entry.  Its namespace-7 snapshot is not safe while any
-- legacy path can still change an epoch key without that fence (bump_epoch, direct principal or
-- target registration, and registry approval applying those cores).  Keep it ungranted until all
-- of those writers join the same candidate fence and the coordinated cutover is accepted.
CREATE FUNCTION change_ledger.add_epoch_dependency_v1(
 t text,c text,p_change_id uuid,p_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE;
        deps jsonb;
BEGIN
  PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 200 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;

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
 IF rec.requester IS DISTINCT FROM change_ledger.caller_role() THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF rec.epoch_dependencies ? p_key THEN RETURN rec.epoch_dependencies; END IF;

 -- epoch_value executes as a separate READ COMMITTED statement after the ranked fences.
 deps:=rec.epoch_dependencies||pg_catalog.jsonb_build_object(
  p_key,change_ledger.epoch_value(t,c,p_key));
 UPDATE change_ledger.records SET epoch_dependencies=deps,updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'EPOCH_DEPENDENCY_ADDED',
  pg_catalog.jsonb_build_object('key',p_key));
 RETURN deps;
END $fn$;
ALTER FUNCTION change_ledger.add_epoch_dependency_v1(text,text,uuid,text) OWNER TO ledger_owner;

-- Candidate fenced counterpart for the legacy operator epoch bump. The v1 signature remains
-- ungranted; the final migration block routes the preserved legacy signature through this body
-- atomically with the same-scope registry writer bridges.
CREATE FUNCTION change_ledger.bump_epoch_v1(t text,c text,p_key text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_key IS NULL OR pg_catalog.length(p_key) NOT BETWEEN 1 AND 200 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 RETURN change_ledger.bump_epoch_internal(t,c,p_key);
END $fn$;
ALTER FUNCTION change_ledger.bump_epoch_v1(text,text,text) OWNER TO ledger_owner;

-- Candidate same-scope registry entries. They remain ungranted until the complete registry writer
-- graph, including approval and verifier-key paths, passes lock and privilege review.
CREATE FUNCTION change_ledger.register_principal_v1(
 t text,c text,p_principal text,p_person_id text,p_capabilities text[],p_active boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; n jsonb; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 n:=change_ledger.registry_normalize('PRINCIPAL',pg_catalog.jsonb_build_object(
  'principal',p_principal,'person_id',p_person_id,'capabilities',pg_catalog.to_jsonb(p_capabilities),
  'active',p_active));
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF NOT change_ledger.registry_single_ok(t,c,'PRINCIPAL',n) THEN
  RAISE EXCEPTION 'TWO_PERSON_REQUIRED';
 END IF;
 RETURN change_ledger.register_principal_core(t,c,p_principal,p_person_id,p_capabilities,p_active,who);
END $fn$;
ALTER FUNCTION change_ledger.register_principal_v1(text,text,text,text,text[],boolean) OWNER TO ledger_owner;

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
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
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
ALTER FUNCTION change_ledger.register_target_v1(text,text,text,text,text,text,timestamptz) OWNER TO ledger_owner;

-- Candidate registry approval entry. It freezes the proposal plan before taking the ranked
-- verifier-material/namespace-6 locks, then revalidates the immutable row before approval DML.
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
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
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
ALTER FUNCTION change_ledger.approve_registry_change_v1(text,text,uuid,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.register_verifier_key_v1(
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
ALTER FUNCTION change_ledger.register_verifier_key_v1(text,text,text,text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.revoke_verifier_key_v1(t text,c text,p_key_id text) RETURNS void
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
ALTER FUNCTION change_ledger.revoke_verifier_key_v1(text,text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.enforce_registry_v1(t text,c text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; had boolean; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT p.enforced INTO had FROM change_ledger.registry_policy p
  WHERE p.tenant_id=t AND p.company_id=c;
 IF had IS TRUE THEN RETURN true; END IF;
 INSERT INTO change_ledger.registry_policy(tenant_id,company_id,enforced,updated_by)
 VALUES(t,c,true,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET enforced=true,updated_by=who,
  updated_at=pg_catalog.clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_ENFORCED',
  pg_catalog.jsonb_build_object('by',who));
 RETURN true;
END $fn$;
ALTER FUNCTION change_ledger.enforce_registry_v1(text,text) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.propose_registry_change_v1(
 t text,c text,p_change_id uuid,p_kind text,p_params jsonb
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; n jsonb; dg text; ex change_ledger.registry_changes%ROWTYPE;
        lf change_ledger.lifecycle_fences%ROWTYPE; person text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
  IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
    OR p_kind IS NULL OR p_kind NOT IN ('PRINCIPAL','TARGET','VERIFIER_KEY') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'operator');
 n:=change_ledger.registry_normalize(p_kind,p_params);
 dg:=change_ledger.registry_change_digest(t,c,p_kind,n);

 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'registry-change-id:v1:'||pg_catalog.lower(p_change_id::text)
 ]);
 PERFORM change_ledger.assert_capability(t,c,who,'operator');
 person:=change_ledger.person_of(t,c,who);
 SELECT * INTO ex FROM change_ledger.registry_changes x
  WHERE x.tenant_id=t AND x.company_id=c AND x.params_digest=dg
   AND x.expires_at>pg_catalog.clock_timestamp()
   AND change_ledger.same_person(t,c,x.proposer,who)
   AND NOT EXISTS(SELECT 1 FROM change_ledger.registry_change_approvals a WHERE a.change_id=x.change_id)
  ORDER BY x.proposed_at DESC LIMIT 1;
 IF FOUND THEN RETURN ex.change_id; END IF;

 IF EXISTS(SELECT 1 FROM change_ledger.registry_changes x WHERE x.change_id=p_change_id) THEN
  RAISE EXCEPTION 'CHANGE_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.registry_changes(change_id,tenant_id,company_id,kind,params,summary,params_digest,
  proposer,proposer_person,proposer_session,expires_at)
 VALUES(p_change_id,t,c,p_kind,n,change_ledger.registry_summary(p_kind,n),dg,who,person,session_user::text,
  pg_catalog.clock_timestamp()+interval '24 hours');
 PERFORM change_ledger.append_event(t,c,NULL,'REGISTRY_CHANGE_PROPOSED',
  pg_catalog.jsonb_build_object('registry_change_id',p_change_id,'kind',p_kind,'digest',dg,'proposer',who,
   'proposer_person',person,'proposer_session',session_user::text,
   'summary',change_ledger.registry_summary(p_kind,n)));
 RETURN p_change_id;
END $fn$;
ALTER FUNCTION change_ledger.propose_registry_change_v1(text,text,uuid,text,jsonb) OWNER TO ledger_owner;

-- Candidate counterpart for the generation receipt requirement. It is intentionally ungranted
-- until the claim-generation writer and receipt writers are qualified under the same scope fence.
CREATE FUNCTION change_ledger.require_dispatch_receipt_v1(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF p_change_id IS NULL OR p_generation IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;

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
ALTER FUNCTION change_ledger.require_dispatch_receipt_v1(text,text,uuid,bigint) OWNER TO ledger_owner;

-- Candidate counterpart for the clone-produced dispatch receipt. The allocated receipt ID is
-- accepted explicitly so its global identity can join the ranked lock plan before row work.
CREATE FUNCTION change_ledger.record_dispatch_receipt_v1(
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
ALTER FUNCTION change_ledger.record_dispatch_receipt_v1(text,text,uuid,bigint,text,text,text,text,uuid)
 OWNER TO ledger_owner;

-- Candidate wire-payload verifier with an adapter-allocated global verification identity.
CREATE FUNCTION change_ledger.verify_dispatch_payload_v1(
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
ALTER FUNCTION change_ledger.verify_dispatch_payload_v1(text,text,uuid,bigint,text,uuid) OWNER TO ledger_owner;

-- Evidence replay is idempotent only for the complete immutable signed tuple and original actor.
CREATE FUNCTION change_ledger.record_evidence_v1(
 t text,c text,p_change_id uuid,p_kind text,p_content_hash text,p_observed_at timestamptz,
 p_content jsonb,p_key_id text,p_binding_hash text,p_signature text,p_generation bigint,p_call_id uuid,
 p_evidence_id uuid
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text;
        rec change_ledger.records%ROWTYPE;
        vk_before change_ledger.verifier_keys%ROWTYPE;
        vk change_ledger.verifier_keys%ROWTYPE;
        prior change_ledger.evidence_records%ROWTYPE;
        id_owner change_ledger.evidence_records%ROWTYPE;
        eid uuid;
        want text;
        cls text;
        is_worker boolean;
        is_writer boolean;
        dp_call uuid;
BEGIN
  -- Reject malformed identities before any scope fence or table access.
  IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
    OR p_evidence_id IS NULL OR p_evidence_id='00000000-0000-0000-0000-000000000000'::uuid
  THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  IF p_kind IS DISTINCT FROM 'AUTH_RECEIPT'
    AND (p_generation IS NULL OR p_generation<=0 OR p_call_id IS NULL
    OR p_call_id='00000000-0000-0000-0000-000000000000'::uuid) THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
  IF p_kind IS NULL OR p_kind NOT IN ('FIELD','MOVEMENT','VERSION','AUTH_RECEIPT','COMPLETION_PROOF','OBSERVATION')
    OR p_content_hash IS NULL OR p_content_hash !~ '^[a-f0-9]{64}$' OR p_observed_at IS NULL
   OR p_content IS NULL OR pg_catalog.jsonb_typeof(p_content)<>'object'
   OR pg_catalog.octet_length(p_content::text)>65536 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 is_worker:=pg_catalog.pg_has_role(who::name,'worker_role','USAGE');
 is_writer:=pg_catalog.pg_has_role(who::name,'writer_role','USAGE');
 IF NOT (is_worker OR (is_writer AND p_kind='COMPLETION_PROOF')) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c AND f.state IN ('NOT_READY','RECOVERING')) THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 -- Snapshot signer material without a row lock, then join the common key-mutation fence
 -- before namespace-6 identities and relation locks.
 SELECT * INTO vk_before FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id;
 IF FOUND AND vk_before.key_material IS NOT NULL AND vk_before.key_material<>'' THEN
  PERFORM pg_catalog.pg_advisory_xact_lock(
   pg_catalog.hashtextextended(vk_before.key_material,17017));
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'evidence-record-id:v1:'||pg_catalog.lower(p_evidence_id::text)
 ]);

  -- Preserve the legacy missing-parent error precedence after ranked fences, without
  -- taking a row lock before signer-key ordering. Recheck and lock the parent below.
  PERFORM 1 FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;

  IF p_key_id IS NULL OR p_key_id='' OR p_signature IS NULL OR p_signature=''
    OR p_binding_hash IS NULL THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
  IF p_content_hash IS DISTINCT FROM change_ledger.canonical_content_hash(p_content) THEN
   RAISE EXCEPTION 'DIGEST_MISMATCH';
  END IF;
  want:=change_ledger.evidence_binding(p_change_id,p_kind,p_content_hash,p_observed_at,p_generation,p_call_id);
  IF p_binding_hash IS DISTINCT FROM want THEN RAISE EXCEPTION 'DIGEST_MISMATCH'; END IF;
  IF p_observed_at>pg_catalog.clock_timestamp()+interval '5 minutes' THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;

 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_key_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF vk_before.key_id IS NULL
   OR pg_catalog.to_jsonb(vk) IS DISTINCT FROM pg_catalog.to_jsonb(vk_before) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF vk.status<>'ACTIVE' THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF NOT pg_catalog.pg_has_role(who::name,vk.role_name::name,'USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF vk.key_algorithm IS DISTINCT FROM 'ED25519' OR vk.key_material IS NULL OR vk.key_material=''
   OR NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,want,p_signature) THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;

  IF p_kind IN ('COMPLETION_PROOF','OBSERVATION')
    AND ((p_content->>'generation') IS DISTINCT FROM p_generation::text
      OR (p_content->>'call_id') IS DISTINCT FROM p_call_id::text) THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  IF p_kind='COMPLETION_PROOF' THEN
   cls:=p_content->>'class';
   IF cls IS NULL OR cls NOT IN ('a','b') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
   IF (cls='a' AND NOT is_writer) OR (cls='b' AND NOT is_worker) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
   IF pg_catalog.jsonb_typeof(p_content->'result_returned') IS DISTINCT FROM 'boolean' THEN
    RAISE EXCEPTION 'SCHEMA_INVALID';
   END IF;
  ELSIF p_kind='OBSERVATION' THEN
   IF p_content ? 'effect_present' AND pg_catalog.jsonb_typeof(p_content->'effect_present')<>'boolean' THEN
    RAISE EXCEPTION 'SCHEMA_INVALID';
   END IF;
  ELSIF p_kind IN ('FIELD','MOVEMENT','VERSION') THEN
   IF pg_catalog.jsonb_typeof(p_content->'matches') IS DISTINCT FROM 'boolean' THEN
    RAISE EXCEPTION 'SCHEMA_INVALID';
   END IF;
  END IF;

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_kind<>'AUTH_RECEIPT' THEN
  IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
  SELECT dp.call_id INTO dp_call FROM change_ledger.dispatch_permits dp
   WHERE dp.change_id=p_change_id AND dp.generation=p_generation;
  IF NOT FOUND OR dp_call IS DISTINCT FROM p_call_id THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 END IF;
 IF p_kind='AUTH_RECEIPT' AND NOT EXISTS(
   SELECT 1 FROM change_ledger.approvals a WHERE a.change_id=p_change_id
    AND a.approval_id::text=p_content->>'approval_id') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 SELECT * INTO prior FROM change_ledger.evidence_records e
  WHERE e.change_id=p_change_id AND e.kind=p_kind AND e.content_hash=p_content_hash;
 IF FOUND THEN
  IF ROW(prior.tenant_id,prior.company_id,prior.change_id,prior.kind,prior.content_hash,
      prior.observed_at,prior.content,prior.signer_key_id,prior.signature,prior.binding_hash,
      prior.generation,prior.call_id,prior.recorded_by)
    IS DISTINCT FROM ROW(t,c,p_change_id,p_kind,p_content_hash,p_observed_at,p_content,p_key_id,
      p_signature,want,p_generation,p_call_id,who) THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  -- Evidence rows are children of records: resolve the natural replay only after locking
  -- the parent. Reusing that row's own ID is exact replay; an ID owned by another row is not.
  SELECT * INTO id_owner FROM change_ledger.evidence_records e WHERE e.evidence_id=p_evidence_id;
  IF FOUND AND id_owner.evidence_id IS DISTINCT FROM prior.evidence_id THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN prior.evidence_id;
 END IF;

 -- No natural-key replay exists. Refuse an already-reserved global ID before insert; the
 -- primary key remains the arbiter if an out-of-contract legacy writer races this pre-read.
 SELECT * INTO id_owner FROM change_ledger.evidence_records e WHERE e.evidence_id=p_evidence_id;
 IF FOUND THEN RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
 BEGIN
  INSERT INTO change_ledger.evidence_records(evidence_id,tenant_id,company_id,change_id,kind,
   content_hash,observed_at,content,signer_key_id,signature,binding_hash,recorded_by,generation,call_id)
  VALUES(p_evidence_id,t,c,p_change_id,p_kind,p_content_hash,p_observed_at,p_content,p_key_id,
   p_signature,want,who,p_generation,p_call_id)
  ON CONFLICT(change_id,kind,content_hash) DO NOTHING
  RETURNING evidence_id INTO eid;
 EXCEPTION WHEN unique_violation THEN
  RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
 END;
 IF eid IS NULL THEN
  -- A concurrent legacy exact-key insert may win during additive qualification. Re-read
  -- under READ COMMITTED and accept only the same complete signed tuple and actor.
  SELECT * INTO prior FROM change_ledger.evidence_records e
   WHERE e.change_id=p_change_id AND e.kind=p_kind AND e.content_hash=p_content_hash;
  IF NOT FOUND OR ROW(prior.tenant_id,prior.company_id,prior.change_id,prior.kind,prior.content_hash,
      prior.observed_at,prior.content,prior.signer_key_id,prior.signature,prior.binding_hash,
      prior.generation,prior.call_id,prior.recorded_by)
    IS DISTINCT FROM ROW(t,c,p_change_id,p_kind,p_content_hash,p_observed_at,p_content,p_key_id,
      p_signature,want,p_generation,p_call_id,who) THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  SELECT * INTO id_owner FROM change_ledger.evidence_records e WHERE e.evidence_id=p_evidence_id;
  IF FOUND AND id_owner.evidence_id IS DISTINCT FROM prior.evidence_id THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN prior.evidence_id;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'EVIDENCE_RECORDED',
  pg_catalog.jsonb_build_object('evidence_id',p_evidence_id,'kind',p_kind,'content_hash',p_content_hash,
   'key_id',p_key_id,'generation',p_generation,'call_id',p_call_id));
 RETURN p_evidence_id;
END $fn$;
ALTER FUNCTION change_ledger.record_evidence_v1(
 text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid,uuid) OWNER TO ledger_owner;

-- Signed T16 witness submission under the S13 scope fence. Exact retries are lookup-only by
-- current authenticated signer/session and completion-evidence identity; a new proof is checked
-- against the locked current generation before the preallocated child row is inserted.
DO $cosign_preflight$
BEGIN
 IF EXISTS(
   SELECT 1 FROM change_ledger.witness_cosigns w
   WHERE w.signer_session IS NOT NULL AND w.completion_proof->>'evidence_id' IS NOT NULL
   GROUP BY w.change_id,w.signer,w.signer_session,(w.completion_proof->>'evidence_id')
   HAVING count(*)>1
 ) THEN
  RAISE EXCEPTION 'S13_WITNESS_COSIGN_DUPLICATE_PREFLIGHT';
 END IF;
END $cosign_preflight$;
CREATE UNIQUE INDEX IF NOT EXISTS witness_cosigns_s13_identity_uidx
 ON change_ledger.witness_cosigns
 (change_id,signer,signer_session,(completion_proof->>'evidence_id'))
 WHERE signer_session IS NOT NULL AND completion_proof->>'evidence_id' IS NOT NULL;

CREATE FUNCTION change_ledger.witness_cosign_signed_v1(
 t text,c text,p_change_id uuid,p_completion uuid
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; cid uuid:=pg_catalog.gen_random_uuid(); prior change_ledger.witness_cosigns%ROWTYPE;
        rec change_ledger.records%ROWTYPE; rec_before change_ledger.records%ROWTYPE;
        cp change_ledger.evidence_records%ROWTYPE; dp_call uuid;
        dp_before change_ledger.dispatch_permits%ROWTYPE; dp change_ledger.dispatch_permits%ROWTYPE;
        attempt_before change_ledger.dispatch_attempts%ROWTYPE; attempt change_ledger.dispatch_attempts%ROWTYPE;
        receipt_before change_ledger.private_writer_evidence%ROWTYPE;
        receipt change_ledger.private_writer_evidence%ROWTYPE;
        completion_before change_ledger.private_writer_evidence%ROWTYPE;
        completion change_ledger.private_writer_evidence%ROWTYPE;
        hold_hint change_ledger.holds%ROWTYPE; call_hold change_ledger.holds%ROWTYPE;
        proof jsonb; global_keys text[];
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'operator_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'
   OR p_completion IS NULL OR p_completion='00000000-0000-0000-0000-000000000000' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c AND f.state IN ('NOT_READY','RECOVERING')) THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 SELECT * INTO rec_before FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT * INTO hold_hint FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id
    AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL;
 -- APPLY_UNKNOWN cosigns are allowed only after the exact entered-conflict receipt and matching
 -- completion projection are attached to this private-writer attempt. These are plan reads; later
 -- ranked fences and full-row comparisons establish the mutation decision.
 IF rec_before.execution_state='APPLY_UNKNOWN' THEN
  SELECT * INTO dp_before FROM change_ledger.dispatch_permits p
   WHERE p.change_id=p_change_id AND p.generation=rec_before.claim_generation;
  IF NOT FOUND OR dp_before.state<>'DISPATCHED' OR dp_before.call_id IS NULL THEN
   RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
  END IF;
  SELECT * INTO attempt_before FROM change_ledger.dispatch_attempts a
   WHERE a.tenant_id=t AND a.company_id=c AND a.change_id=p_change_id
    AND a.claim_generation=rec_before.claim_generation AND a.call_id=dp_before.call_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001'; END IF;
  SELECT e.* INTO receipt_before FROM change_ledger.private_writer_attempt_evidence ae
   JOIN change_ledger.private_writer_evidence e USING(evidence_ref)
   WHERE ae.dispatch_cas_id=attempt_before.dispatch_cas_id
    AND ae.evidence_purpose='WRITER_RECEIPT';
  SELECT e.* INTO completion_before FROM change_ledger.private_writer_attempt_evidence ae
   JOIN change_ledger.private_writer_evidence e USING(evidence_ref)
   WHERE ae.dispatch_cas_id=attempt_before.dispatch_cas_id AND ae.evidence_purpose='COMPLETION'
    AND e.completion_proof_id=p_completion;
  IF receipt_before.evidence_ref IS NULL OR completion_before.evidence_ref IS NULL
    OR receipt_before.record_type<>'DISPATCH_RECEIPT_V1'
    OR receipt_before.writer_receipt_id IS NULL
    OR receipt_before.writer_invocation_stage<>'ENTERED'
    OR receipt_before.writer_result_class<>'CONDITIONAL_VERSION_CONFLICT'
    OR receipt_before.writer_call_returned IS NOT TRUE
    OR receipt_before.writer_returned_at IS NULL
    OR receipt_before.no_effect_evidence_digest IS NOT NULL
    OR receipt_before.writer_returned_target_ref IS NOT NULL
    OR receipt_before.writer_returned_version IS NOT NULL
    OR receipt_before.dispatch_cas_id IS DISTINCT FROM attempt_before.dispatch_cas_id
    OR receipt_before.call_id IS DISTINCT FROM dp_before.call_id
    OR receipt_before.process_instance_id IS DISTINCT FROM attempt_before.writer_process_instance_id
    OR completion_before.record_type<>'COMPLETION_PROOF_V1'
    OR completion_before.dispatch_cas_id IS DISTINCT FROM attempt_before.dispatch_cas_id THEN
   RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
  END IF;
 END IF;
 global_keys:=ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'evidence-record-id:v1:'||pg_catalog.lower(p_completion::text),
  'witness-cosign-id:v1:'||pg_catalog.lower(cid::text)
 ];
 IF rec_before.execution_state='APPLY_UNKNOWN' THEN
  global_keys:=global_keys||ARRAY[
   'call-id:v1:'||pg_catalog.lower(dp_before.call_id::text),
   'dispatch-cas-id:v1:'||pg_catalog.lower(attempt_before.dispatch_cas_id::text),
   'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(receipt_before.evidence_ref,'UTF8')),'hex'),
   'evidence-ref:v1:'||encode(pg_catalog.sha256(convert_to(completion_before.evidence_ref,'UTF8')),'hex')
  ];
 END IF;
 IF hold_hint.hold_id IS NOT NULL THEN
  global_keys:=global_keys||('hold-id:v1:'||pg_catalog.lower(hold_hint.hold_id::text));
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':CALL_OWNERSHIP'));
 SELECT * INTO cp FROM change_ledger.evidence_ref(t,c,p_change_id,p_completion,'COMPLETION_PROOF');
 IF pg_catalog.jsonb_typeof(cp.content->'attribution_proof') IS NOT NULL
   AND pg_catalog.jsonb_typeof(cp.content->'attribution_proof') IS DISTINCT FROM 'boolean' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF cp.content->>'class' IS NULL OR cp.content->>'class' NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 proof:=pg_catalog.jsonb_build_object('class',cp.content->>'class','evidence_id',cp.evidence_id,
  'attribution_proof',coalesce((cp.content->>'attribution_proof')::boolean,false));

 -- The session trigger owns signer_session. A matching immutable row is safe to replay even
 -- after the completion evidence is no longer current or the cosign has been consumed.
 SELECT w.* INTO prior FROM change_ledger.witness_cosigns w
  JOIN change_ledger.records owner_rec ON owner_rec.change_id=w.change_id
  WHERE w.change_id=p_change_id AND w.signer=who AND w.signer_session=session_user::text
    AND owner_rec.tenant_id=t AND owner_rec.company_id=c
    AND w.completion_proof->>'evidence_id'=p_completion::text;
 IF FOUND THEN
  IF pg_catalog.jsonb_typeof(prior.completion_proof) IS DISTINCT FROM 'object'
    OR prior.completion_proof->>'class' IS NULL
    OR prior.completion_proof->>'class' NOT IN ('a','b')
    OR prior.completion_proof->>'evidence_id' IS DISTINCT FROM p_completion::text
    OR prior.completion_proof IS DISTINCT FROM proof THEN
   RAISE EXCEPTION 'COSIGN_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN prior.cosign_id;
 END IF;

 PERFORM change_ledger.assert_capability(t,c,who,'recovery_witness');
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec IS DISTINCT FROM rec_before THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF rec.execution_state NOT IN ('TRIAGE_REQUIRED','APPLY_UNKNOWN') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.witness_cosigns w WHERE w.cosign_id=cid) THEN
  RAISE EXCEPTION 'COSIGN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF cp.generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO dp FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=rec.claim_generation FOR SHARE;
 IF NOT FOUND OR cp.call_id IS DISTINCT FROM dp.call_id THEN RAISE EXCEPTION 'PERMIT_MISSING'; END IF;
 dp_call:=dp.call_id;
 IF rec.execution_state='APPLY_UNKNOWN' THEN
  IF pg_catalog.to_jsonb(dp) IS DISTINCT FROM pg_catalog.to_jsonb(dp_before)
    OR dp.state<>'DISPATCHED' THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  SELECT * INTO attempt FROM change_ledger.dispatch_attempts a
   WHERE a.dispatch_cas_id=attempt_before.dispatch_cas_id FOR UPDATE;
  IF NOT FOUND OR pg_catalog.to_jsonb(attempt) IS DISTINCT FROM pg_catalog.to_jsonb(attempt_before)
    OR attempt.state<>'POSSIBLY_EXECUTING' OR attempt.invocation_started_at IS NULL
    OR attempt.com_entry_authorized_at IS NULL THEN
   RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
  END IF;
  SELECT e.* INTO receipt FROM change_ledger.private_writer_attempt_evidence ae
   JOIN change_ledger.private_writer_evidence e USING(evidence_ref)
   WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_purpose='WRITER_RECEIPT';
  SELECT e.* INTO completion FROM change_ledger.private_writer_attempt_evidence ae
   JOIN change_ledger.private_writer_evidence e USING(evidence_ref)
   WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_purpose='COMPLETION'
    AND e.completion_proof_id=p_completion;
  IF pg_catalog.to_jsonb(receipt) IS DISTINCT FROM pg_catalog.to_jsonb(receipt_before)
    OR pg_catalog.to_jsonb(completion) IS DISTINCT FROM pg_catalog.to_jsonb(completion_before) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 END IF;
 IF hold_hint.hold_id IS NULL THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT * INTO call_hold FROM change_ledger.holds h
  WHERE h.hold_id=hold_hint.hold_id AND h.tenant_id=t AND h.company_id=c FOR UPDATE;
 IF NOT FOUND OR call_hold IS DISTINCT FROM hold_hint OR call_hold.released_at IS NOT NULL THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.witness_cosigns(cosign_id,change_id,signer,completion_proof)
 VALUES(cid,p_change_id,who,proof);
 RETURN cid;
END $fn$;
ALTER FUNCTION change_ledger.witness_cosign_signed_v1(text,text,uuid,uuid) OWNER TO ledger_owner;

-- Internal T17 gate: direct execution could consume a cosign outside the terminal transition.
-- The recovery witness is never the requester or current approver; the operator may be approver
-- only when the independently distinct witness is not.
CREATE OR REPLACE FUNCTION change_ledger.consume_two_person_cosign(
 p_rec change_ledger.records,p_operator text,p_cosign_id uuid
) RETURNS change_ledger.witness_cosigns LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE cs change_ledger.witness_cosigns%ROWTYPE; approver_subject text;
        t text:=p_rec.tenant_id; c text:=p_rec.company_id;
BEGIN
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_rec.change_id AND w.consumed_at IS NULL FOR UPDATE;
 IF NOT FOUND OR coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 PERFORM change_ledger.assert_ed25519_cosign_evidence(t,c,p_rec.change_id,cs.completion_proof);
 SELECT a.approver INTO approver_subject FROM change_ledger.approvals a
  WHERE a.change_id=p_rec.change_id AND a.decision='APPROVE'
  ORDER BY a.approved_at DESC,a.approval_id DESC LIMIT 1;
 IF approver_subject IS NULL OR change_ledger.same_person(t,c,p_operator,cs.signer)
  OR change_ledger.same_person(t,c,p_operator,p_rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,p_rec.requester)
  OR change_ledger.same_person(t,c,approver_subject,p_rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,approver_subject) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,p_operator,'operator');
 PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
 IF change_ledger.registry_enforced(t,c) AND (change_ledger.person_of(t,c,p_operator) IS NULL
  OR change_ledger.person_of(t,c,cs.signer) IS NULL
  OR change_ledger.person_of(t,c,p_rec.requester) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 UPDATE change_ledger.witness_cosigns w SET consumed_at=clock_timestamp()
  WHERE w.cosign_id=p_cosign_id;
 RETURN cs;
END $fn$;
ALTER FUNCTION change_ledger.consume_two_person_cosign(change_ledger.records,text,uuid)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.consume_two_person_cosign(change_ledger.records,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

CREATE FUNCTION change_ledger.private_writer_assert_target_lease_owner_scope_v1(
 t text,c text,p_change_id uuid,p_base_fingerprint text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF p_change_id IS NULL OR p_base_fingerprint IS NULL
   OR EXISTS(SELECT 1 FROM change_ledger.target_locks x WHERE x.owner_change_id=p_change_id
      AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
        OR x.base_fingerprint IS DISTINCT FROM p_base_fingerprint))
   OR EXISTS(SELECT 1 FROM change_ledger.writer_leases x WHERE x.owner_change_id=p_change_id
      AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
        OR x.base_fingerprint IS DISTINCT FROM p_base_fingerprint)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_assert_target_lease_owner_scope_v1(text,text,uuid,text)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.private_writer_assert_target_lease_owner_scope_v1(text,text,uuid,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
  business_ai_private_writer,private_writer_evidence_ingest;

CREATE FUNCTION change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
 t text,c text,p_record_ids uuid[],p_base_fingerprint text,p_target_ref text,p_key_hash text,
 p_check_lease boolean
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 IF p_record_ids IS NULL OR p_base_fingerprint IS NULL OR p_check_lease IS NULL
   OR EXISTS(SELECT 1 FROM pg_catalog.unnest(p_record_ids) AS x(change_id) WHERE x.change_id IS NULL)
   OR (SELECT count(DISTINCT x.change_id) FROM pg_catalog.unnest(p_record_ids) AS x(change_id))
      <> (SELECT count(*) FROM change_ledger.records r WHERE r.change_id=ANY(p_record_ids))
   OR EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.change_id=ANY(p_record_ids)
      AND (r.tenant_id IS DISTINCT FROM t OR r.company_id IS DISTINCT FROM c))
   OR (p_target_ref IS NOT NULL AND EXISTS(SELECT 1 FROM change_ledger.target_locks x
      LEFT JOIN change_ledger.records r ON r.change_id=x.owner_change_id
     WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base_fingerprint
      AND x.target_ref=p_target_ref
      AND (x.owner_change_id<>ALL(p_record_ids) OR r.change_id IS NULL
        OR r.tenant_id IS DISTINCT FROM x.tenant_id OR r.company_id IS DISTINCT FROM x.company_id
        OR r.base_fingerprint IS DISTINCT FROM x.base_fingerprint)))
   OR (p_key_hash IS NOT NULL AND EXISTS(SELECT 1 FROM change_ledger.key_locks x
      LEFT JOIN change_ledger.records r ON r.change_id=x.owner_change_id
     WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base_fingerprint
      AND x.key_hash=p_key_hash
      AND (x.owner_change_id<>ALL(p_record_ids) OR r.change_id IS NULL
        OR r.tenant_id IS DISTINCT FROM x.tenant_id OR r.company_id IS DISTINCT FROM x.company_id
        OR r.base_fingerprint IS DISTINCT FROM x.base_fingerprint)))
   OR (p_check_lease AND EXISTS(SELECT 1 FROM change_ledger.writer_leases x
      LEFT JOIN change_ledger.records r ON r.change_id=x.owner_change_id
     WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base_fingerprint
      AND (x.owner_change_id<>ALL(p_record_ids) OR r.change_id IS NULL
        OR r.tenant_id IS DISTINCT FROM x.tenant_id OR r.company_id IS DISTINCT FROM x.company_id
        OR r.base_fingerprint IS DISTINCT FROM x.base_fingerprint))) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
 text,text,uuid[],text,text,text,boolean) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
 text,text,uuid[],text,text,text,boolean)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
  business_ai_private_writer,private_writer_evidence_ingest;

-- S13 unknown-outcome triage path. The validator-approved OUTCOME projection is the immutable
-- observation; caller booleans are deliberately absent. Only a returned writer call with a
-- determinate observation can terminalize the physical attempt and enter T16 Path A. An
-- ambiguous result remains APPLY_UNKNOWN, and an entered conditional conflict uses Path B.
CREATE FUNCTION change_ledger.resolve_unknown_v2(
 t text,c text,p_change_id uuid,p_dispatch_cas_id uuid,
 p_receipt_ref text,p_completion_ref text,p_outcome_ref text
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; rec_hint change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        permit_hint change_ledger.dispatch_permits%ROWTYPE; permit change_ledger.dispatch_permits%ROWTYPE;
        attempt_hint change_ledger.dispatch_attempts%ROWTYPE; attempt change_ledger.dispatch_attempts%ROWTYPE;
        receipt_hint change_ledger.private_writer_evidence%ROWTYPE;
        completion_hint change_ledger.private_writer_evidence%ROWTYPE;
        outcome_hint change_ledger.private_writer_evidence%ROWTYPE;
        receipt change_ledger.private_writer_evidence%ROWTYPE;
        completion change_ledger.private_writer_evidence%ROWTYPE;
        outcome change_ledger.private_writer_evidence%ROWTYPE;
        slot change_ledger.physical_base_slots%ROWTYPE;
        hold_row change_ledger.holds%ROWTYPE; resolution change_ledger.events%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_dispatch_cas_id IS NULL OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_receipt_ref IS NULL OR p_receipt_ref='' OR p_receipt_ref<>pg_catalog.btrim(p_receipt_ref)
   OR p_completion_ref IS NULL OR p_completion_ref='' OR p_completion_ref<>pg_catalog.btrim(p_completion_ref)
   OR p_outcome_ref IS NULL OR p_outcome_ref='' OR p_outcome_ref<>pg_catalog.btrim(p_outcome_ref)
   OR p_receipt_ref=p_completion_ref OR p_receipt_ref=p_outcome_ref OR p_completion_ref=p_outcome_ref THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 -- These unlocked reads build only a bounded identity plan. The authoritative values are all
 -- re-read after the common fences and compared before any state change.
 SELECT * INTO rec_hint FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,rec_hint.base_fingerprint);
 SELECT * INTO permit_hint FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=rec_hint.claim_generation;
 IF NOT FOUND OR permit_hint.call_id IS NULL THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO attempt_hint FROM change_ledger.dispatch_attempts a
  WHERE a.dispatch_cas_id=p_dispatch_cas_id AND a.tenant_id=t AND a.company_id=c
   AND a.change_id=p_change_id AND a.claim_generation=rec_hint.claim_generation
   AND a.call_id=permit_hint.call_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO receipt_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_receipt_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO completion_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_completion_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO outcome_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_outcome_ref AND e.tenant_id=t AND e.company_id=c;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_base_fence_v1(attempt_hint.base_fingerprint);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'call-id:v1:'||pg_catalog.lower(attempt_hint.call_id::text),
  'dispatch-cas-id:v1:'||pg_catalog.lower(p_dispatch_cas_id::text),
  'evidence-ref:v1:'||pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_receipt_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_completion_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_outcome_ref,'UTF8')),'hex')
 ]);
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,rec_hint.base_fingerprint);
 -- Acquire namespace-6 identity fences before the first relation-row lock. Hold the lifecycle
 -- row afterward to serialize readiness changes, but do not require READY: inventoried calls
 -- must drain before startup recovery can finish.
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF rec IS DISTINCT FROM rec_hint THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT * INTO permit FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=rec.claim_generation FOR UPDATE;
 IF NOT FOUND OR permit IS DISTINCT FROM permit_hint
   OR permit.call_id IS DISTINCT FROM attempt_hint.call_id THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO attempt FROM change_ledger.dispatch_attempts a
  WHERE a.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR attempt IS DISTINCT FROM attempt_hint
   OR attempt.tenant_id IS DISTINCT FROM t OR attempt.company_id IS DISTINCT FROM c
   OR attempt.change_id IS DISTINCT FROM p_change_id
   OR attempt.claim_generation IS DISTINCT FROM rec.claim_generation
   OR attempt.call_id IS DISTINCT FROM permit.call_id THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001';
 END IF;

 -- Terminal/current-state replay is lookup-only after the record/permit/attempt identity check.
 -- TRIAGE_REQUIRED is tied to the original immutable reference tuple; other terminal outcomes
 -- are returned without demanding another evidence read.
 IF rec.execution_state IN ('APPLIED','FAILED_APPLY','TRIAGE_REQUIRED') THEN
  IF rec.execution_state='TRIAGE_REQUIRED' THEN
   SELECT * INTO resolution FROM change_ledger.events e
    WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
     AND e.event_type='RESOLVE_UNKNOWN'
     AND e.payload->'observation'->>'outcome_evidence_ref'=p_outcome_ref
     AND e.payload->'observation'->>'receipt_ref'=p_receipt_ref
     AND e.payload->'observation'->>'completion_ref'=p_completion_ref
    ORDER BY e.seq DESC LIMIT 1;
   IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001'; END IF;
  END IF;
  RETURN rec.execution_state;
 END IF;
 IF rec.execution_state<>'APPLY_UNKNOWN' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;

 -- Lock the immutable evidence rows in stable reference order, then verify their attempt links.
 PERFORM 1 FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref IN (p_receipt_ref,p_completion_ref,p_outcome_ref)
  ORDER BY e.evidence_ref FOR SHARE;
 SELECT * INTO receipt FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_receipt_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO completion FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_completion_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO outcome FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_outcome_ref AND e.tenant_id=t AND e.company_id=c;
 IF receipt IS DISTINCT FROM receipt_hint OR completion IS DISTINCT FROM completion_hint
   OR outcome IS DISTINCT FROM outcome_hint
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=p_dispatch_cas_id AND x.dispatch_intent_id=attempt.dispatch_intent_id
       AND x.evidence_ref=p_receipt_ref AND x.evidence_purpose='WRITER_RECEIPT')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=p_dispatch_cas_id AND x.dispatch_intent_id=attempt.dispatch_intent_id
       AND x.evidence_ref=p_completion_ref AND x.evidence_purpose='COMPLETION')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence x
      WHERE x.dispatch_cas_id=p_dispatch_cas_id AND x.dispatch_intent_id=attempt.dispatch_intent_id
       AND x.evidence_ref=p_outcome_ref AND x.evidence_purpose='OUTCOME') THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001';
 END IF;
 IF ROW(receipt.record_type,receipt.dispatch_cas_id,receipt.dispatch_intent_id,receipt.change_id,
      receipt.claim_generation,receipt.call_id,receipt.writer_receipt_id,receipt.signer_role)
    IS DISTINCT FROM ROW('DISPATCH_RECEIPT_V1',attempt.dispatch_cas_id,attempt.dispatch_intent_id,
      p_change_id,rec.claim_generation,permit.call_id,receipt.writer_receipt_id,'writer_receipt')
   OR receipt.writer_receipt_id IS NULL
   OR receipt.writer_invocation_stage NOT IN ('ENTERED','INVOKED')
   OR completion.record_type<>'COMPLETION_PROOF_V1'
   OR completion.dispatch_cas_id IS DISTINCT FROM attempt.dispatch_cas_id
   OR completion.dispatch_intent_id IS DISTINCT FROM attempt.dispatch_intent_id
   OR completion.change_id IS DISTINCT FROM p_change_id
   OR completion.claim_generation IS DISTINCT FROM rec.claim_generation
   OR completion.call_id IS DISTINCT FROM permit.call_id
   OR outcome.record_type NOT IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2','OUTCOME_EVIDENCE_V3')
   OR outcome.signer_role<>'verification_worker'
   OR outcome.dispatch_cas_id IS DISTINCT FROM attempt.dispatch_cas_id
   OR outcome.dispatch_intent_id IS DISTINCT FROM attempt.dispatch_intent_id
   OR outcome.change_id IS DISTINCT FROM p_change_id
   OR outcome.claim_generation IS DISTINCT FROM rec.claim_generation
   OR outcome.call_id IS DISTINCT FROM permit.call_id
   OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
   OR completion.completion_proof_class NOT IN
      ('WRITER_CALL_RETURNED','INDEPENDENT_SESSION_AND_PROCESS_CLOSED')
   OR outcome.outcome_completion_proof_class IS DISTINCT FROM completion.completion_proof_class
   OR completion.session_instance_id IS DISTINCT FROM attempt.onec_session_instance_id
   OR (completion.completion_proof_class='WRITER_CALL_RETURNED' AND
       (completion.signer_role<>'writer_receipt'
        OR completion.signer_service_id IS DISTINCT FROM attempt.writer_service_id
        OR completion.signer_host_id IS DISTINCT FROM attempt.writer_host_id
        OR completion.process_instance_id IS DISTINCT FROM attempt.writer_process_instance_id
        OR receipt.writer_call_returned IS NOT TRUE OR receipt.writer_returned_at IS NULL))
   OR (completion.completion_proof_class='INDEPENDENT_SESSION_AND_PROCESS_CLOSED' AND
       (completion.signer_role<>'completion_supervisor'
        OR completion.signer_service_id IS NOT DISTINCT FROM attempt.writer_service_id
        OR completion.signer_host_id IS DISTINCT FROM attempt.writer_host_id
        OR completion.process_instance_id IS NOT DISTINCT FROM attempt.writer_process_instance_id))
   OR receipt.process_instance_id IS DISTINCT FROM attempt.writer_process_instance_id
   OR receipt.session_instance_id IS DISTINCT FROM attempt.onec_session_instance_id
   OR (outcome.record_type='OUTCOME_EVIDENCE_V3'
       AND outcome.outcome_completion_proof_digest IS DISTINCT FROM completion.record_digest) THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001';
 END IF;

 IF permit.state<>'DISPATCHED' THEN RAISE EXCEPTION 'TICKET_SUPERSEDED' USING ERRCODE='P0001'; END IF;
 IF attempt.state<>'POSSIBLY_EXECUTING' OR attempt.invocation_started_at IS NULL
   OR attempt.com_entry_authorized_at IS NULL THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 -- TRIAGE_REQUIRED is the T16 Path A entry and requires physical call terminality. Only a
 -- returned-success receipt plus a complete, healthy, determinate observation can close this
 -- writer attempt here; UNKNOWN stays APPLY_UNKNOWN and conditional conflicts use Path B.
 IF receipt.writer_result_class IS DISTINCT FROM 'CALL_RETURNED_SUCCESS'
   OR receipt.writer_call_returned IS NOT TRUE OR receipt.writer_returned_at IS NULL
   OR completion.completion_proof_class IS DISTINCT FROM 'WRITER_CALL_RETURNED'
   OR outcome.record_type NOT IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2')
   OR outcome.outcome_observation_complete IS NOT TRUE
   OR outcome.outcome_reader_health IS DISTINCT FROM 'HEALTHY'
   OR outcome.outcome_uncertainty_count IS DISTINCT FROM 0
   OR outcome.outcome_effect_presence IS NULL
   OR outcome.outcome_effect_presence NOT IN ('PRESENT','ABSENT')
   OR (outcome.outcome_effect_presence='PRESENT' AND
       (outcome.outcome_effect_identity IS DISTINCT FROM 'MATCH'
        OR outcome.outcome_fields_match IS NOT TRUE
        OR outcome.outcome_movements_match IS NOT TRUE
        OR outcome.outcome_target_ref IS DISTINCT FROM receipt.writer_returned_target_ref
        OR outcome.outcome_observed_version IS DISTINCT FROM receipt.writer_returned_version
        OR outcome.outcome_expected_effect_digest IS DISTINCT FROM outcome.outcome_observed_effect_digest
        OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
        OR outcome.outcome_attribution_result IS NULL
        OR outcome.outcome_attribution_result NOT IN ('PROVEN','UNATTRIBUTED')))
   OR (outcome.outcome_effect_presence='ABSENT' AND
       (outcome.outcome_effect_identity IS DISTINCT FROM 'NO_GOVERNED_EFFECT'
        OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
        OR outcome.outcome_attribution_result IS DISTINCT FROM 'COMPETING_WRITER'))
   OR (attempt.operation_kind IN ('POST','UNPOST') AND
       (outcome.outcome_pre_version IS DISTINCT FROM attempt.expected_pre_version
        OR (outcome.outcome_effect_presence='PRESENT'
            AND outcome.outcome_version_relation IS DISTINCT FROM 'ADVANCED'))) THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO slot FROM change_ledger.physical_base_slots x
  WHERE x.base_fingerprint=attempt.base_fingerprint FOR UPDATE;
 IF NOT FOUND OR slot.active_dispatch_cas_id IS DISTINCT FROM attempt.dispatch_cas_id THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF slot.admission_closed OR slot.open_barrier_id IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.writer_barrier_calls x
      JOIN change_ledger.writer_barriers w USING(barrier_id)
      WHERE w.barrier_id=slot.open_barrier_id AND x.dispatch_cas_id=attempt.dispatch_cas_id) THEN
   RAISE EXCEPTION 'WRITER_ADMISSION_CLOSED' USING ERRCODE='P0001';
  END IF;
 END IF;
 SELECT * INTO hold_row FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id
   AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED',
  call_ownership='PROVEN_FINISHED',updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 UPDATE change_ledger.dispatch_attempts SET state='TERMINAL_WITH_EVIDENCE'
  WHERE dispatch_cas_id=p_dispatch_cas_id AND state='POSSIBLY_EXECUTING';
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 UPDATE change_ledger.physical_base_slots SET active_dispatch_cas_id=NULL
  WHERE base_fingerprint=attempt.base_fingerprint
   AND active_dispatch_cas_id=attempt.dispatch_cas_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'RESOLVE_UNKNOWN',pg_catalog.jsonb_build_object(
  'found',CASE outcome.outcome_effect_presence WHEN 'PRESENT' THEN true ELSE NULL END,
  'attributed_claim',outcome.outcome_attribution_result,
  'observation',pg_catalog.jsonb_build_object('outcome_evidence_ref',p_outcome_ref,
   'receipt_ref',p_receipt_ref,'completion_ref',p_completion_ref,
   'effect_presence',outcome.outcome_effect_presence,'effect_identity',outcome.outcome_effect_identity,
   'attribution',outcome.outcome_attribution_result)));
 RETURN 'TRIAGE_REQUIRED';
END $fn$;
ALTER FUNCTION change_ledger.resolve_unknown_v2(text,text,uuid,uuid,text,text,text) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.resolve_unknown_v2(text,text,uuid,uuid,text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

CREATE FUNCTION change_ledger.operator_resolve_v1(
 t text,c text,p_change_id uuid,p_dispatch_cas_id uuid,p_cosign_id uuid,
 p_receipt_ref text,p_completion_ref text,p_outcome_ref text,
 p_challenge_ref text DEFAULT NULL,p_read_attestation_ref text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; rec_hint change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        repair_hint change_ledger.records%ROWTYPE; repair_rec change_ledger.records%ROWTYPE;
        permit_hint change_ledger.dispatch_permits%ROWTYPE; permit change_ledger.dispatch_permits%ROWTYPE;
        attempt_hint change_ledger.dispatch_attempts%ROWTYPE; attempt change_ledger.dispatch_attempts%ROWTYPE;
        receipt_hint change_ledger.private_writer_evidence%ROWTYPE;
        completion_hint change_ledger.private_writer_evidence%ROWTYPE;
        outcome_hint change_ledger.private_writer_evidence%ROWTYPE;
        challenge_hint change_ledger.private_writer_evidence%ROWTYPE;
        attestation_hint change_ledger.private_writer_evidence%ROWTYPE;
        receipt change_ledger.private_writer_evidence%ROWTYPE;
        completion change_ledger.private_writer_evidence%ROWTYPE;
        outcome change_ledger.private_writer_evidence%ROWTYPE;
        challenge change_ledger.private_writer_evidence%ROWTYPE;
        attestation change_ledger.private_writer_evidence%ROWTYPE;
        cosign_hint change_ledger.witness_cosigns%ROWTYPE; cs change_ledger.witness_cosigns%ROWTYPE;
        hold_hint change_ledger.holds%ROWTYPE; call_hold change_ledger.holds%ROWTYPE;
        approval_hint change_ledger.approvals%ROWTYPE; approval change_ledger.approvals%ROWTYPE;
        reservation_hint change_ledger.reservations%ROWTYPE; reservation change_ledger.reservations%ROWTYPE;
        lifecycle change_ledger.lifecycle_fences%ROWTYPE; target_plan jsonb; key_plan jsonb;
        lease_plan jsonb; anchor_plan jsonb; active_targets_plan jsonb;
        global_keys text[]; parent_ids uuid[];
        rowrec record; keyrow record; resolution change_ledger.events%ROWTYPE;
        disposition text; attributed boolean; resolved_event_id uuid; event_seq bigint; event_hash text;
        checkpoint_signed_at timestamptz;
        row_count integer; open_hold_count integer; open_anchor_count integer;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'operator_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_change_id IS NULL OR p_change_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_dispatch_cas_id IS NULL OR p_dispatch_cas_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_cosign_id IS NULL OR p_cosign_id='00000000-0000-0000-0000-000000000000'::uuid
   OR p_receipt_ref IS NULL OR p_receipt_ref='' OR p_receipt_ref<>pg_catalog.btrim(p_receipt_ref)
   OR p_completion_ref IS NULL OR p_completion_ref='' OR p_completion_ref<>pg_catalog.btrim(p_completion_ref)
   OR p_outcome_ref IS NULL OR p_outcome_ref='' OR p_outcome_ref<>pg_catalog.btrim(p_outcome_ref)
   OR ((p_challenge_ref IS NULL)<>(p_read_attestation_ref IS NULL))
   OR (p_challenge_ref IS NOT NULL AND
      (p_challenge_ref='' OR p_challenge_ref<>pg_catalog.btrim(p_challenge_ref)))
   OR (p_read_attestation_ref IS NOT NULL AND
      (p_read_attestation_ref='' OR p_read_attestation_ref<>pg_catalog.btrim(p_read_attestation_ref))) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 -- A fully committed T16 may be retried after every linked hold was released and the scope's
 -- target registry later grew beyond the bounded mutation plan. This immutable-event replay is
 -- read-only; it performs no release or other state change and lets the caller resume the exact
 -- checkpoint/release sequence without rebuilding an obsolete mutation plan.
 SELECT * INTO resolution FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
  AND e.change_id=p_change_id AND e.event_type='OPERATOR_RESOLVE'
  AND e.payload->>'cosign_id'=p_cosign_id::text;
 IF FOUND THEN
  IF resolution.payload->>'dispatch_cas_id' IS DISTINCT FROM p_dispatch_cas_id::text
    OR resolution.payload->>'receipt_ref' IS DISTINCT FROM p_receipt_ref
    OR resolution.payload->>'completion_ref' IS DISTINCT FROM p_completion_ref
    OR resolution.payload->>'outcome_ref' IS DISTINCT FROM p_outcome_ref
    OR resolution.payload->>'challenge_ref' IS DISTINCT FROM p_challenge_ref
    OR resolution.payload->>'read_attestation_ref' IS DISTINCT FROM p_read_attestation_ref
    OR resolution.payload->>'checkpoint_required' IS DISTINCT FROM 'true'
    OR pg_catalog.jsonb_typeof(resolution.payload->'checkpoint_hold_ids') IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN pg_catalog.jsonb_build_object('execution_state',resolution.payload->>'execution',
   'event_id',resolution.event_id,'event_seq',resolution.seq,'event_hash',resolution.hash,
   'checkpoint_signed_at',resolution.recorded_at,
   'attributed',resolution.payload->>'attributed'='true',
   'hold_id',(resolution.payload->>'hold_id')::uuid,
   'checkpoint_hold_ids',resolution.payload->'checkpoint_hold_ids','checkpoint_required',true);
 END IF;

 -- Unlocked reads construct a bounded plan only; every decision is repeated after the ranked fences.
 SELECT * INTO rec_hint FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,rec_hint.base_fingerprint);
 SELECT * INTO permit_hint FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=rec_hint.claim_generation;
 IF NOT FOUND OR permit_hint.call_id IS NULL THEN RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO attempt_hint FROM change_ledger.dispatch_attempts a
  WHERE a.dispatch_cas_id=p_dispatch_cas_id AND a.tenant_id=t AND a.company_id=c
   AND a.change_id=p_change_id AND a.call_id=permit_hint.call_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001'; END IF;
 SELECT * INTO receipt_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_receipt_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO completion_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_completion_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO outcome_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_outcome_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO challenge_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_challenge_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO attestation_hint FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_read_attestation_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO cosign_hint FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_change_id;
 IF receipt_hint.evidence_ref IS NULL OR completion_hint.evidence_ref IS NULL
   OR outcome_hint.evidence_ref IS NULL OR cosign_hint.cosign_id IS NULL THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;
 IF rec_hint.repair_for IS NOT NULL THEN
  SELECT * INTO repair_hint FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=rec_hint.repair_for;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END IF;
 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.target_ref),'[]'::jsonb) INTO target_plan
   FROM (SELECT x.* FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
    AND x.base_fingerprint=rec_hint.base_fingerprint AND x.owner_change_id=p_change_id
    ORDER BY x.base_fingerprint,x.target_ref LIMIT 201) x;
 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb) INTO key_plan
   FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
    AND x.base_fingerprint=rec_hint.base_fingerprint AND x.owner_change_id=p_change_id
    ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 IF EXISTS(SELECT 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
   AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
     OR x.base_fingerprint IS DISTINCT FROM rec_hint.base_fingerprint)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint),'[]'::jsonb) INTO lease_plan
   FROM (SELECT x.* FROM change_ledger.writer_leases x WHERE x.tenant_id=t AND x.company_id=c
    AND x.base_fingerprint=rec_hint.base_fingerprint AND x.owner_change_id=p_change_id
    ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT * INTO reservation_hint FROM change_ledger.reservations x WHERE x.change_id=p_change_id;
 SELECT * INTO approval_hint FROM change_ledger.approvals x
 WHERE x.change_id=p_change_id AND x.decision='APPROVE'
  ORDER BY x.approved_at DESC,x.approval_id DESC LIMIT 1;
   SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
            'base_fingerprint',x.base_fingerprint)
            ORDER BY x.base_fingerprint),'[]'::jsonb) INTO active_targets_plan
    FROM (SELECT x.base_fingerprint FROM change_ledger.targets x
          WHERE x.tenant_id=t AND x.company_id=c
          ORDER BY x.base_fingerprint LIMIT 201) x;
  SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
           'base_fingerprint',x.base_fingerprint,'hold_id',pg_catalog.gen_random_uuid())
           ORDER BY x.base_fingerprint),'[]'::jsonb) INTO anchor_plan
   FROM (SELECT DISTINCT base_fingerprint FROM change_ledger.targets
         WHERE tenant_id=t AND company_id=c ORDER BY base_fingerprint LIMIT 201) x;
  IF NOT EXISTS(
     SELECT 1 FROM pg_catalog.jsonb_to_recordset(anchor_plan) AS x(base_fingerprint text,hold_id uuid)
     WHERE x.base_fingerprint=rec_hint.base_fingerprint) THEN
   RAISE EXCEPTION 'ANCHOR_GAP_ACTIVE' USING ERRCODE='P0001';
  END IF;
  row_count:=7+CASE WHEN rec_hint.repair_for IS NULL THEN 0 ELSE 1 END
    +jsonb_array_length(active_targets_plan)+jsonb_array_length(anchor_plan)
    +jsonb_array_length(target_plan)+jsonb_array_length(key_plan)
   +jsonb_array_length(lease_plan)+1
    +CASE WHEN reservation_hint.change_id IS NULL THEN 0 ELSE 1 END;
  IF row_count>200 OR pg_catalog.jsonb_array_length(target_plan)>200
    OR pg_catalog.jsonb_array_length(key_plan)>200 OR pg_catalog.jsonb_array_length(lease_plan)>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);

 -- The cosign is the stable replay identity. After an uncertain client response, return the
 -- immutable prior terminal result before requiring the now-consumed cosign or released call hold.
 SELECT * INTO resolution FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
  AND e.change_id=p_change_id AND e.event_type='OPERATOR_RESOLVE'
  AND e.payload->>'cosign_id'=p_cosign_id::text;
 IF FOUND THEN
  IF resolution.payload->>'dispatch_cas_id' IS DISTINCT FROM p_dispatch_cas_id::text
    OR resolution.payload->>'receipt_ref' IS DISTINCT FROM p_receipt_ref
    OR resolution.payload->>'completion_ref' IS DISTINCT FROM p_completion_ref
    OR resolution.payload->>'outcome_ref' IS DISTINCT FROM p_outcome_ref
    OR resolution.payload->>'challenge_ref' IS DISTINCT FROM p_challenge_ref
    OR resolution.payload->>'read_attestation_ref' IS DISTINCT FROM p_read_attestation_ref
    OR resolution.payload->>'checkpoint_required' IS DISTINCT FROM 'true'
    OR pg_catalog.jsonb_typeof(resolution.payload->'checkpoint_hold_ids') IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'EVIDENCE_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN pg_catalog.jsonb_build_object('execution_state',resolution.payload->>'execution',
   'event_id',resolution.event_id,'event_seq',resolution.seq,'event_hash',resolution.hash,
   'checkpoint_signed_at',resolution.recorded_at,
   'attributed',resolution.payload->>'attributed'='true',
   'hold_id',(resolution.payload->>'hold_id')::uuid,
   'checkpoint_hold_ids',resolution.payload->'checkpoint_hold_ids','checkpoint_required',true);
 END IF;

 -- New resolution still requires the original unique call hold and no open scope anchor gap.
 -- These checks follow immutable-event replay so a caller can recover a lost response after
 -- checkpointing has already released one or more linked holds.
 SELECT count(*) INTO open_hold_count FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id
   AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL;
 SELECT * INTO hold_hint FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id
   AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL
  ORDER BY h.opened_at,h.hold_id LIMIT 1;
 SELECT count(*) INTO open_anchor_count FROM change_ledger.holds h
  WHERE h.tenant_id=t AND h.company_id=c AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL;
 IF open_hold_count<>1 OR hold_hint.hold_id IS NULL OR open_anchor_count<>0 THEN
  RAISE EXCEPTION 'ANCHOR_GAP_ACTIVE' USING ERRCODE='P0001';
 END IF;

 -- Serialize signer-key revocation before namespace 6. Sort/deduplicate by the actual signed
 -- bigint advisory key, not by the evidence reference or key ID.
 FOR keyrow IN
  SELECT DISTINCT lock_id FROM (
   SELECT pg_catalog.hashtextextended(encode(k.public_key,'hex'),17017) AS lock_id
    FROM change_ledger.private_writer_evidence e
    JOIN change_ledger.private_writer_signer_key_versions k
     ON k.key_id=e.signer_key_id AND k.key_version=e.signer_key_version
    WHERE e.evidence_ref=ANY(ARRAY[p_receipt_ref,p_completion_ref,p_outcome_ref,
      p_challenge_ref,p_read_attestation_ref]) AND e.tenant_id=t AND e.company_id=c
   UNION
   SELECT pg_catalog.hashtextextended(k.key_material,17017) AS lock_id
    FROM change_ledger.evidence_records e
    JOIN change_ledger.verifier_keys k ON k.tenant_id=e.tenant_id AND k.company_id=e.company_id
     AND k.key_id=e.signer_key_id
    WHERE e.tenant_id=t AND e.company_id=c AND e.evidence_id=
      CASE WHEN coalesce(cosign_hint.completion_proof->>'evidence_id','') ~*
       '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       THEN (cosign_hint.completion_proof->>'evidence_id')::uuid ELSE NULL END
  ) lock_ids ORDER BY lock_id
 LOOP PERFORM pg_catalog.pg_advisory_xact_lock(keyrow.lock_id); END LOOP;
 FOR keyrow IN
  SELECT DISTINCT k.key_id,k.key_version
   FROM change_ledger.private_writer_evidence e
   JOIN change_ledger.private_writer_signer_key_versions k
    ON k.key_id=e.signer_key_id AND k.key_version=e.signer_key_version
   WHERE e.evidence_ref=ANY(ARRAY[p_receipt_ref,p_completion_ref,p_outcome_ref,
       p_challenge_ref,p_read_attestation_ref]) AND e.tenant_id=t AND e.company_id=c
   ORDER BY k.key_id,k.key_version
 LOOP
  IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_versions k
      WHERE k.key_id=keyrow.key_id AND k.key_version=keyrow.key_version
       AND k.valid_from<=clock_timestamp() AND k.valid_until>clock_timestamp())
    OR EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations r
      WHERE r.key_id=keyrow.key_id AND r.key_version=keyrow.key_version) THEN
   RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
  END IF;
 END LOOP;

 global_keys:=ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'call-id:v1:'||pg_catalog.lower(attempt_hint.call_id::text),
  'dispatch-cas-id:v1:'||pg_catalog.lower(p_dispatch_cas_id::text),
  'witness-cosign-id:v1:'||pg_catalog.lower(p_cosign_id::text),
  'hold-id:v1:'||pg_catalog.lower(hold_hint.hold_id::text),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(pg_catalog.convert_to(p_receipt_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(pg_catalog.convert_to(p_completion_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(pg_catalog.convert_to(p_outcome_ref,'UTF8')),'hex')
 ];
 IF p_challenge_ref IS NOT NULL THEN global_keys:=global_keys||ARRAY[
  'evidence-ref:v1:'||encode(pg_catalog.sha256(pg_catalog.convert_to(p_challenge_ref,'UTF8')),'hex'),
  'evidence-ref:v1:'||encode(pg_catalog.sha256(pg_catalog.convert_to(p_read_attestation_ref,'UTF8')),'hex')
 ]; END IF;
 IF rec_hint.repair_for IS NOT NULL THEN
  global_keys:=global_keys||('record-change-id:v1:'||pg_catalog.lower(rec_hint.repair_for::text));
 END IF;
 FOR rowrec IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(anchor_plan) AS x(
   base_fingerprint text,hold_id uuid) ORDER BY x.hold_id
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(rowrec.hold_id::text));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,rec_hint.base_fingerprint);
  -- Resolution can release or hand back the selected target and remove the matching key/lease
  -- rows. Bind those resource owners to the already planned record before namespace-3/4 locks.
  PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
   t,c,ARRAY[p_change_id],rec_hint.base_fingerprint,
   coalesce(rec_hint.target_ref,p_change_id::text),NULL,true);
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
      AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
        OR x.base_fingerprint IS DISTINCT FROM rec_hint.base_fingerprint))
    OR (SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
        FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
         AND x.base_fingerprint=rec_hint.base_fingerprint AND x.owner_change_id=p_change_id)
      IS DISTINCT FROM key_plan THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 FOR keyrow IN
  SELECT DISTINCT pg_catalog.hashtext(t||':'||c||':'||cause) AS lock_id
   FROM unnest(ARRAY['CALL_OWNERSHIP','ANCHOR_GAP']) AS causes(cause)
   ORDER BY lock_id
 LOOP PERFORM pg_catalog.pg_advisory_xact_lock(3,keyrow.lock_id); END LOOP;
   FOR keyrow IN
    SELECT DISTINCT pg_catalog.hashtext(x.lock_key) AS lock_id
     FROM (
      SELECT 'target-lock:v1:'||t||':'||c||':'||x.base_fingerprint||':'||x.target_ref AS lock_key
       FROM pg_catalog.jsonb_to_recordset(target_plan) AS x(
         base_fingerprint text,target_ref text)
      UNION
      SELECT x.tenant_id||':'||x.company_id||':'||x.base_fingerprint||':'||x.key_hash AS lock_key
       FROM pg_catalog.jsonb_to_recordset(key_plan) AS x(
        tenant_id text,company_id text,base_fingerprint text,key_hash text)
     ) x ORDER BY lock_id
   LOOP PERFORM pg_catalog.pg_advisory_xact_lock(4,keyrow.lock_id); END LOOP;

  -- Acquire every advisory rank before the first relation-row lock. Then gate on lifecycle and
  -- lock this bounded target-parent set before its referencing record rows.
  SELECT * INTO lifecycle FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
  IF NOT FOUND OR lifecycle.state IN ('NOT_READY','RECOVERING') THEN
   RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
  END IF;
  FOR rowrec IN SELECT x.base_fingerprint
   FROM pg_catalog.jsonb_to_recordset(active_targets_plan) AS x(base_fingerprint text)
   ORDER BY x.base_fingerprint
 LOOP
  PERFORM 1 FROM change_ledger.targets x WHERE x.tenant_id=t AND x.company_id=c
    AND x.base_fingerprint=rowrec.base_fingerprint FOR SHARE;
 END LOOP;
 IF EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL) THEN
  RAISE EXCEPTION 'ANCHOR_GAP_ACTIVE' USING ERRCODE='P0001';
 END IF;
  IF (SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
       'base_fingerprint',x.base_fingerprint)
       ORDER BY x.base_fingerprint), '[]'::jsonb)
      FROM (SELECT x.base_fingerprint FROM change_ledger.targets x
      WHERE x.tenant_id=t AND x.company_id=c
       ORDER BY x.base_fingerprint LIMIT 201) x)
    IS DISTINCT FROM active_targets_plan THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;

 -- Lock current and repair-parent records before any referencing child row.
 parent_ids:=ARRAY[p_change_id];
 IF rec_hint.repair_for IS NOT NULL THEN parent_ids:=ARRAY[p_change_id,rec_hint.repair_for]; END IF;
 FOR rowrec IN SELECT r.* FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(parent_ids)
   ORDER BY r.change_id FOR UPDATE
 LOOP
  IF rowrec.change_id=p_change_id THEN rec:=rowrec;
  ELSIF rowrec.change_id=rec_hint.repair_for THEN repair_rec:=rowrec;
  END IF;
 END LOOP;
 IF rec.change_id IS NULL OR pg_catalog.to_jsonb(rec) IS DISTINCT FROM pg_catalog.to_jsonb(rec_hint)
   OR (rec_hint.repair_for IS NOT NULL AND
       pg_catalog.to_jsonb(repair_rec) IS DISTINCT FROM pg_catalog.to_jsonb(repair_hint)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT * INTO permit FROM change_ledger.dispatch_permits p
  WHERE p.change_id=p_change_id AND p.generation=rec.claim_generation FOR UPDATE;
 IF NOT FOUND OR pg_catalog.to_jsonb(permit) IS DISTINCT FROM pg_catalog.to_jsonb(permit_hint) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO attempt FROM change_ledger.dispatch_attempts a
  WHERE a.dispatch_cas_id=p_dispatch_cas_id FOR UPDATE;
 IF NOT FOUND OR pg_catalog.to_jsonb(attempt) IS DISTINCT FROM pg_catalog.to_jsonb(attempt_hint) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.cosign_id=p_cosign_id AND w.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR pg_catalog.to_jsonb(cs) IS DISTINCT FROM pg_catalog.to_jsonb(cosign_hint)
   OR cs.consumed_at IS NOT NULL THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO call_hold FROM change_ledger.holds h WHERE h.hold_id=hold_hint.hold_id FOR UPDATE;
 IF NOT FOUND OR call_hold IS DISTINCT FROM hold_hint OR call_hold.released_at IS NOT NULL THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id FOR UPDATE;
 IF reservation IS DISTINCT FROM reservation_hint THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.base_fingerprint=rec.base_fingerprint AND x.owner_change_id=p_change_id
   ORDER BY x.target_ref LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.base_fingerprint=rec.base_fingerprint AND x.owner_change_id=p_change_id
   ORDER BY x.key_hash LIMIT 201 FOR UPDATE;
 PERFORM 1 FROM change_ledger.writer_leases x WHERE x.tenant_id=t AND x.company_id=c
  AND x.base_fingerprint=rec.base_fingerprint AND x.owner_change_id=p_change_id FOR UPDATE;
  IF (SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.target_ref),'[]'::jsonb)
        FROM (SELECT x.* FROM change_ledger.target_locks x
         WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=rec.base_fingerprint
          AND x.owner_change_id=p_change_id ORDER BY x.base_fingerprint,x.target_ref LIMIT 201) x)
       IS DISTINCT FROM target_plan
    OR (SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
        FROM (SELECT x.* FROM change_ledger.key_locks x
         WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=rec.base_fingerprint
          AND x.owner_change_id=p_change_id ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x)
       IS DISTINCT FROM key_plan
    OR (SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint),'[]'::jsonb)
        FROM (SELECT x.* FROM change_ledger.writer_leases x
         WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=rec.base_fingerprint
          AND x.owner_change_id=p_change_id ORDER BY x.base_fingerprint LIMIT 201) x)
       IS DISTINCT FROM lease_plan THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;

 SELECT * INTO receipt FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_receipt_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO completion FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_completion_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO outcome FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_outcome_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO challenge FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_challenge_ref AND e.tenant_id=t AND e.company_id=c;
 SELECT * INTO attestation FROM change_ledger.private_writer_evidence e
  WHERE e.evidence_ref=p_read_attestation_ref AND e.tenant_id=t AND e.company_id=c;
 IF receipt IS DISTINCT FROM receipt_hint OR completion IS DISTINCT FROM completion_hint
   OR outcome IS DISTINCT FROM outcome_hint OR challenge IS DISTINCT FROM challenge_hint
   OR attestation IS DISTINCT FROM attestation_hint THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
  IF ROW(receipt.tenant_id,receipt.company_id,receipt.organization_ref,receipt.base_fingerprint,
      receipt.change_id,receipt.claim_generation,receipt.dispatch_generation,receipt.call_id,
      receipt.dispatch_cas_id,receipt.dispatch_intent_id,receipt.operation_kind,receipt.approval_digest,
      receipt.payload_digest,receipt.permit_id,receipt.permit_digest,receipt.target_ref,receipt.pre_version,
      receipt.auth_epoch)
       IS DISTINCT FROM ROW(attempt.tenant_id,attempt.company_id,attempt.organization_ref,
      attempt.base_fingerprint,attempt.change_id,attempt.claim_generation,attempt.dispatch_generation,
      attempt.call_id,attempt.dispatch_cas_id,attempt.dispatch_intent_id,attempt.operation_kind,
      attempt.approval_digest,attempt.payload_digest,attempt.permit_id,attempt.permit_digest,
      attempt.expected_target_ref,attempt.expected_pre_version,attempt.auth_epoch)
    OR ROW(completion.tenant_id,completion.company_id,completion.organization_ref,completion.base_fingerprint,
      completion.change_id,completion.claim_generation,completion.dispatch_generation,completion.call_id,
      completion.dispatch_cas_id,completion.dispatch_intent_id,completion.operation_kind,
      completion.approval_digest,completion.payload_digest,completion.permit_id,completion.permit_digest,
      completion.target_ref,completion.pre_version,completion.auth_epoch)
       IS DISTINCT FROM ROW(attempt.tenant_id,attempt.company_id,attempt.organization_ref,
      attempt.base_fingerprint,attempt.change_id,attempt.claim_generation,attempt.dispatch_generation,
      attempt.call_id,attempt.dispatch_cas_id,attempt.dispatch_intent_id,attempt.operation_kind,
      attempt.approval_digest,attempt.payload_digest,attempt.permit_id,attempt.permit_digest,
      attempt.expected_target_ref,attempt.expected_pre_version,attempt.auth_epoch)
    OR ROW(outcome.tenant_id,outcome.company_id,outcome.organization_ref,outcome.base_fingerprint,
      outcome.change_id,outcome.claim_generation,outcome.dispatch_generation,outcome.call_id,
      outcome.dispatch_cas_id,outcome.dispatch_intent_id,outcome.operation_kind,outcome.approval_digest,
      outcome.payload_digest,outcome.permit_id,outcome.permit_digest,outcome.target_ref,outcome.pre_version,
      outcome.auth_epoch)
       IS DISTINCT FROM ROW(attempt.tenant_id,attempt.company_id,attempt.organization_ref,
      attempt.base_fingerprint,attempt.change_id,attempt.claim_generation,attempt.dispatch_generation,
      attempt.call_id,attempt.dispatch_cas_id,attempt.dispatch_intent_id,attempt.operation_kind,
      attempt.approval_digest,attempt.payload_digest,attempt.permit_id,attempt.permit_digest,
      attempt.expected_target_ref,attempt.expected_pre_version,attempt.auth_epoch)
    OR completion.completion_proof_class NOT IN
      ('WRITER_CALL_RETURNED','INDEPENDENT_SESSION_AND_PROCESS_CLOSED')
    OR outcome.outcome_completion_proof_class IS DISTINCT FROM completion.completion_proof_class
    OR completion.session_instance_id IS DISTINCT FROM attempt.onec_session_instance_id
    OR (completion.completion_proof_class='WRITER_CALL_RETURNED' AND
       (completion.signer_role<>'writer_receipt'
        OR completion.signer_service_id IS DISTINCT FROM attempt.writer_service_id
        OR completion.signer_host_id IS DISTINCT FROM attempt.writer_host_id
        OR completion.process_instance_id IS DISTINCT FROM attempt.writer_process_instance_id
        OR receipt.writer_call_returned IS NOT TRUE OR receipt.writer_returned_at IS NULL))
    OR (completion.completion_proof_class='INDEPENDENT_SESSION_AND_PROCESS_CLOSED' AND
       (completion.signer_role<>'completion_supervisor'
        OR completion.signer_service_id IS NOT DISTINCT FROM attempt.writer_service_id
        OR completion.signer_host_id IS DISTINCT FROM attempt.writer_host_id
        OR completion.process_instance_id IS NOT DISTINCT FROM attempt.writer_process_instance_id))
    OR (outcome.record_type='OUTCOME_EVIDENCE_V3'
       AND outcome.outcome_completion_proof_digest IS DISTINCT FROM completion.record_digest)
    OR (p_challenge_ref IS NOT NULL AND (
      ROW(challenge.tenant_id,challenge.company_id,challenge.organization_ref,challenge.base_fingerprint,
        challenge.change_id,challenge.claim_generation,challenge.dispatch_generation,challenge.call_id,
        challenge.dispatch_cas_id,challenge.dispatch_intent_id,challenge.operation_kind,
        challenge.approval_digest,challenge.payload_digest,challenge.permit_id,challenge.permit_digest,
        challenge.target_ref,challenge.pre_version,challenge.auth_epoch)
         IS DISTINCT FROM ROW(attempt.tenant_id,attempt.company_id,attempt.organization_ref,
        attempt.base_fingerprint,attempt.change_id,attempt.claim_generation,attempt.dispatch_generation,
        attempt.call_id,attempt.dispatch_cas_id,attempt.dispatch_intent_id,attempt.operation_kind,
        attempt.approval_digest,attempt.payload_digest,attempt.permit_id,attempt.permit_digest,
        attempt.expected_target_ref,attempt.expected_pre_version,attempt.auth_epoch)
      OR ROW(attestation.tenant_id,attestation.company_id,attestation.organization_ref,
        attestation.base_fingerprint,attestation.change_id,attestation.claim_generation,
        attestation.dispatch_generation,attestation.call_id,attestation.dispatch_cas_id,
        attestation.dispatch_intent_id,attestation.operation_kind,attestation.approval_digest,
        attestation.payload_digest,attestation.permit_id,attestation.permit_digest,
        attestation.target_ref,attestation.pre_version,attestation.auth_epoch)
         IS DISTINCT FROM ROW(attempt.tenant_id,attempt.company_id,attempt.organization_ref,
        attempt.base_fingerprint,attempt.change_id,attempt.claim_generation,attempt.dispatch_generation,
        attempt.call_id,attempt.dispatch_cas_id,attempt.dispatch_intent_id,attempt.operation_kind,
        attempt.approval_digest,attempt.payload_digest,attempt.permit_id,attempt.permit_digest,
        attempt.expected_target_ref,attempt.expected_pre_version,attempt.auth_epoch))) THEN
   RAISE EXCEPTION 'RECOVERY_EVIDENCE_REJECTED' USING ERRCODE='P0001';
  END IF;
 IF NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_ref=receipt.evidence_ref
       AND ae.evidence_purpose='WRITER_RECEIPT')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_ref=completion.evidence_ref
       AND ae.evidence_purpose='COMPLETION')
   OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
      WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_ref=outcome.evidence_ref
       AND ae.evidence_purpose='OUTCOME') THEN
  RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
 END IF;

 IF rec.execution_state='TRIAGE_REQUIRED' THEN
  IF permit.state<>'DISPATCHED' OR permit.call_id IS DISTINCT FROM attempt.call_id
    OR attempt.state<>'TERMINAL_WITH_EVIDENCE' OR rec.call_ownership<>'PROVEN_FINISHED'
    OR receipt.record_type<>'DISPATCH_RECEIPT_V1'
    OR receipt.writer_result_class<>'CALL_RETURNED_SUCCESS'
    OR receipt.writer_call_returned IS NOT TRUE
    OR completion.record_type<>'COMPLETION_PROOF_V1'
    OR completion.dispatch_cas_id IS DISTINCT FROM attempt.dispatch_cas_id
    OR receipt.writer_receipt_id IS NULL
    OR outcome.record_type NOT IN ('OUTCOME_EVIDENCE_V1','OUTCOME_EVIDENCE_V2')
    OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
    OR outcome.outcome_observation_complete IS NOT TRUE
    OR outcome.outcome_reader_health<>'HEALTHY'
    OR outcome.outcome_uncertainty_count<>0
    OR (outcome.outcome_effect_presence='PRESENT' AND
        (outcome.outcome_effect_identity<>'MATCH' OR outcome.outcome_fields_match IS NOT TRUE
         OR outcome.outcome_movements_match IS NOT TRUE
         OR outcome.outcome_target_ref IS DISTINCT FROM receipt.writer_returned_target_ref
         OR outcome.outcome_observed_version IS DISTINCT FROM receipt.writer_returned_version
          OR outcome.outcome_expected_effect_digest IS DISTINCT FROM outcome.outcome_observed_effect_digest
          OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
          OR outcome.outcome_attribution_result NOT IN ('PROVEN','UNATTRIBUTED')))
    OR (outcome.outcome_effect_presence='ABSENT' AND
        (outcome.outcome_effect_identity<>'NO_GOVERNED_EFFECT'
          OR coalesce(outcome.outcome_attribution_evidence_ref,'')=''
          OR outcome.outcome_attribution_result<>'COMPETING_WRITER'))
    OR outcome.outcome_effect_presence NOT IN ('PRESENT','ABSENT')
    OR (attempt.operation_kind IN ('POST','UNPOST') AND
        (outcome.outcome_pre_version IS DISTINCT FROM attempt.expected_pre_version
         OR (outcome.outcome_effect_presence='PRESENT' AND outcome.outcome_version_relation<>'ADVANCED')))
    OR p_challenge_ref IS NOT NULL THEN
   RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
  END IF;
  attributed:=outcome.outcome_effect_presence='PRESENT'
    AND outcome.outcome_attribution_result='PROVEN';
  IF attributed AND coalesce((cs.completion_proof->>'attribution_proof')::boolean,false) IS NOT TRUE THEN
   RAISE EXCEPTION 'ATTRIBUTION_UNPROVEN';
  END IF;
  disposition:=CASE WHEN outcome.outcome_effect_presence='PRESENT' THEN 'APPLIED' ELSE 'FAILED_APPLY' END;
 ELSIF rec.execution_state='APPLY_UNKNOWN' THEN
  IF p_challenge_ref IS NULL OR p_read_attestation_ref IS NULL
    OR permit.state<>'DISPATCHED' OR permit.call_id IS DISTINCT FROM attempt.call_id
    OR attempt.state<>'POSSIBLY_EXECUTING' OR attempt.invocation_started_at IS NULL
    OR attempt.com_entry_authorized_at IS NULL OR rec.call_ownership<>'POSSIBLY_EXECUTING'
    OR receipt.record_type<>'DISPATCH_RECEIPT_V1'
    OR receipt.writer_invocation_stage<>'ENTERED'
    OR receipt.writer_result_class<>'CONDITIONAL_VERSION_CONFLICT'
    OR receipt.writer_call_returned IS NOT TRUE OR receipt.writer_returned_at IS NULL
    OR receipt.no_effect_evidence_digest IS NOT NULL
    OR receipt.writer_returned_target_ref IS NOT NULL OR receipt.writer_returned_version IS NOT NULL
    OR receipt.process_instance_id IS DISTINCT FROM attempt.writer_process_instance_id
    OR completion.record_type<>'COMPLETION_PROOF_V1'
    OR completion.dispatch_cas_id IS DISTINCT FROM attempt.dispatch_cas_id
    OR outcome.record_type<>'OUTCOME_EVIDENCE_V3'
    OR outcome.outcome_dispatch_receipt_id IS DISTINCT FROM receipt.writer_receipt_id
    OR outcome.outcome_pre_version IS DISTINCT FROM attempt.expected_pre_version
    OR outcome.outcome_observation_complete IS NOT TRUE
    OR outcome.outcome_reader_health<>'HEALTHY'
    OR outcome.outcome_effect_presence<>'ABSENT'
    OR outcome.outcome_effect_identity<>'NO_GOVERNED_EFFECT'
    OR outcome.outcome_attribution_result<>'COMPETING_WRITER'
    OR outcome.outcome_version_relation<>'DIFFERENT_COMPETING_WRITER'
    OR outcome.outcome_observed_version IS NOT DISTINCT FROM attempt.expected_pre_version
    OR outcome.outcome_uncertainty_count<>0
    OR outcome.outcome_completion_proof_digest IS DISTINCT FROM completion.record_digest
     OR outcome.outcome_completion_proof_class IS DISTINCT FROM completion.completion_proof_class
    OR challenge.record_type<>'POST_COMPLETION_CHALLENGE_V1'
    OR attestation.record_type<>'POST_COMPLETION_READ_ATTESTATION_V1'
     OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_ref=challenge.evidence_ref
        AND ae.evidence_purpose='POST_COMPLETION_CHALLENGE')
     OR NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_attempt_evidence ae
       WHERE ae.dispatch_cas_id=attempt.dispatch_cas_id AND ae.evidence_ref=attestation.evidence_ref
        AND ae.evidence_purpose='READ_ATTESTATION')
    OR outcome.outcome_challenge_id IS DISTINCT FROM challenge.challenge_id
    OR outcome.outcome_verification_sequence IS DISTINCT FROM attestation.read_attestation_sequence
    OR outcome.outcome_verification_sequence<=challenge.challenge_sequence_floor
    OR outcome.outcome_observation_digest IS DISTINCT FROM attestation.read_attestation_outcome_digest
    OR outcome.outcome_read_attestation_digest IS DISTINCT FROM attestation.record_digest THEN
   RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED' USING ERRCODE='P0001';
  END IF;
  attributed:=false; disposition:='FAILED_APPLY';
 ELSE
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;

 -- Every absent-effect terminal resolution must still own the exact target lock it will release
 -- or hand back. Validate that frozen-plan resource precondition before consuming the witness
 -- cosign or applying any terminal/resource DML.
 IF disposition='FAILED_APPLY' AND NOT EXISTS(
    SELECT 1 FROM change_ledger.target_locks x
     WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=rec.base_fingerprint
      AND x.target_ref=coalesce(rec.target_ref,rec.change_id::text)
      AND x.owner_change_id=p_change_id) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;

 IF cs.completion_proof->>'evidence_id' IS DISTINCT FROM completion.completion_proof_id::text
   OR coalesce(cs.completion_proof->>'class','') NOT IN ('a','b') THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 PERFORM change_ledger.assert_ed25519_cosign_evidence(t,c,p_change_id,cs.completion_proof);
 SELECT a.* INTO approval FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.decision='APPROVE'
  ORDER BY a.approved_at DESC,a.approval_id DESC LIMIT 1 FOR SHARE;
  IF approval IS DISTINCT FROM approval_hint THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 IF approval.approval_id IS NULL OR change_ledger.same_person(t,c,who,cs.signer)
   OR change_ledger.same_person(t,c,who,rec.requester)
   OR change_ledger.same_person(t,c,cs.signer,rec.requester)
  OR change_ledger.same_person(t,c,approval.approver,rec.requester)
  OR change_ledger.same_person(t,c,cs.signer,approval.approver) THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'operator');
 PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
 IF change_ledger.registry_enforced(t,c) AND (change_ledger.person_of(t,c,who) IS NULL
   OR change_ledger.person_of(t,c,cs.signer) IS NULL OR change_ledger.person_of(t,c,rec.requester) IS NULL) THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF reservation.change_id IS NULL OR reservation.state<>'RESERVED'
   OR rec.reservation_state<>'RESERVED' THEN RAISE EXCEPTION 'T16_RESOLUTION_REQUIRED'; END IF;

 UPDATE change_ledger.witness_cosigns SET consumed_at=pg_catalog.clock_timestamp()
  WHERE cosign_id=p_cosign_id AND consumed_at IS NULL;
 IF disposition='FAILED_APPLY' THEN
  UPDATE change_ledger.records SET execution_state='FAILED_APPLY',effect_known='NO',
   reservation_state='RELEASED',call_ownership='PROVEN_FINISHED',attribution='NOT_APPLICABLE',
   updated_at=pg_catalog.clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state='RESERVED';
  PERFORM change_ledger.release_or_handback_target(t,c,rec);
 ELSE
  UPDATE change_ledger.records SET execution_state='APPLIED',effect_known='YES',
   reservation_state='CONSUMED',call_ownership='PROVEN_FINISHED',
   attribution=CASE WHEN attributed THEN 'PROVEN' ELSE 'UNPROVEN_OPERATOR_ATTESTED' END,
   updated_at=pg_catalog.clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.reservations SET state='CONSUMED' WHERE change_id=p_change_id AND state='RESERVED';
 END IF;
 DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 DELETE FROM change_ledger.writer_leases WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 -- Keep the call hold open and freeze every active base with an ANCHOR_GAP hold until the
 -- exact OPERATOR_RESOLVE event has a signed external checkpoint and successful read-back.
 FOR rowrec IN SELECT x.base_fingerprint,x.hold_id
  FROM pg_catalog.jsonb_to_recordset(anchor_plan) AS x(base_fingerprint text,hold_id uuid)
  ORDER BY x.base_fingerprint
 LOOP
  INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause,change_id)
   VALUES(rowrec.hold_id,t,c,rowrec.base_fingerprint,'ANCHOR_GAP',p_change_id);
 END LOOP;
 resolved_event_id:=change_ledger.append_event(t,c,p_change_id,'OPERATOR_RESOLVE',pg_catalog.jsonb_build_object(
  'execution',disposition,'present',outcome.outcome_effect_presence='PRESENT',
  'attributed',attributed,'observation_evidence',outcome.outcome_attribution_evidence_ref,
  'cosign_id',p_cosign_id,
  'dispatch_cas_id',p_dispatch_cas_id,'receipt_ref',p_receipt_ref,
  'completion_ref',p_completion_ref,'outcome_ref',p_outcome_ref,
  'challenge_ref',p_challenge_ref,'read_attestation_ref',p_read_attestation_ref,
  'checkpoint_required',true,'hold_id',call_hold.hold_id,
  'operator',who,'witness',cs.signer,'approval_id',approval.approval_id,
  'checkpoint_hold_ids',(SELECT COALESCE(pg_catalog.jsonb_agg(x.hold_id ORDER BY x.base_fingerprint),'[]'::jsonb)
    FROM pg_catalog.jsonb_to_recordset(anchor_plan) AS x(base_fingerprint text,hold_id uuid))));
 SELECT e.seq,e.hash,e.recorded_at INTO event_seq,event_hash,checkpoint_signed_at
  FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.event_id=resolved_event_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
 RETURN pg_catalog.jsonb_build_object('execution_state',disposition,'event_id',resolved_event_id,
  'event_seq',event_seq,'event_hash',event_hash,'attributed',attributed,
  'checkpoint_signed_at',checkpoint_signed_at,
  'hold_id',call_hold.hold_id,
  'checkpoint_hold_ids',(SELECT COALESCE(pg_catalog.jsonb_agg(x.hold_id ORDER BY x.base_fingerprint),'[]'::jsonb)
    FROM pg_catalog.jsonb_to_recordset(anchor_plan) AS x(base_fingerprint text,hold_id uuid)),
  'checkpoint_required',true);
END $fn$;
ALTER FUNCTION change_ledger.operator_resolve_v1(text,text,uuid,uuid,uuid,text,text,text,text,text)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.operator_resolve_v1(text,text,uuid,uuid,uuid,text,text,text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

DO $hold_cosign_preflight$
BEGIN
 IF EXISTS(
   SELECT 1 FROM change_ledger.hold_cosigns h
   WHERE h.signer_session IS NOT NULL
   GROUP BY h.hold_id,h.signer,h.signer_session,change_ledger.canonical_content_hash(h.evidence)
   HAVING count(*)>1
 ) THEN
  RAISE EXCEPTION 'S13_HOLD_COSIGN_DUPLICATE_PREFLIGHT';
 END IF;
END $hold_cosign_preflight$;
CREATE UNIQUE INDEX IF NOT EXISTS hold_cosigns_s13_identity_uidx
 ON change_ledger.hold_cosigns
 (hold_id,signer,signer_session,change_ledger.canonical_content_hash(evidence))
 WHERE signer_session IS NOT NULL;

CREATE FUNCTION change_ledger.anchor_gap_cosign_v1(
 t text,c text,p_hold_id uuid,p_evidence jsonb
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; cid uuid:=pg_catalog.gen_random_uuid(); hint change_ledger.holds%ROWTYPE;
        h change_ledger.holds%ROWTYPE; prior change_ledger.hold_cosigns%ROWTYPE; digest text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'operator_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_hold_id IS NULL OR p_hold_id='00000000-0000-0000-0000-000000000000'
   OR p_evidence IS NULL OR pg_catalog.jsonb_typeof(p_evidence)<>'object' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c AND f.state IN ('NOT_READY','RECOVERING')) THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'hold-id:v1:'||pg_catalog.lower(p_hold_id::text),
  'hold-cosign-id:v1:'||pg_catalog.lower(cid::text)
 ]);
 SELECT * INTO hint FROM change_ledger.holds x
  WHERE x.hold_id=p_hold_id AND x.tenant_id=t AND x.company_id=c;
 IF NOT FOUND THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 SELECT * INTO h FROM change_ledger.holds x
  WHERE x.hold_id=p_hold_id AND x.tenant_id=t AND x.company_id=c FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF h IS DISTINCT FROM hint THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF h.cause<>'ANCHOR_GAP' OR h.ext_seq IS NULL OR h.ext_head_hash IS NULL THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF coalesce(p_evidence->>'class','') NOT IN ('a','b')
  OR pg_catalog.jsonb_typeof(p_evidence->'reconciliation') IS DISTINCT FROM 'string'
  OR length(coalesce(p_evidence->>'reconciliation',''))=0
  OR p_evidence->'ext_seq' IS DISTINCT FROM pg_catalog.to_jsonb(h.ext_seq)
  OR p_evidence->>'ext_head_hash' IS DISTINCT FROM h.ext_head_hash THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'recovery_witness');
 digest:=change_ledger.canonical_content_hash(p_evidence);
 SELECT * INTO prior FROM change_ledger.hold_cosigns w
  WHERE w.hold_id=p_hold_id AND w.signer=who AND w.signer_session=session_user::text
   AND change_ledger.canonical_content_hash(w.evidence)=digest;
 IF FOUND THEN
  IF prior.evidence IS DISTINCT FROM p_evidence THEN
   RAISE EXCEPTION 'COSIGN_IDENTITY_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN prior.cosign_id;
 END IF;
 IF h.released_at IS NOT NULL THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.hold_cosigns w WHERE w.cosign_id=cid) THEN
  RAISE EXCEPTION 'COSIGN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 INSERT INTO change_ledger.hold_cosigns(cosign_id,tenant_id,company_id,hold_id,signer,evidence)
 VALUES(cid,t,c,p_hold_id,who,p_evidence);
 RETURN cid;
END $fn$;
ALTER FUNCTION change_ledger.anchor_gap_cosign_v1(text,text,uuid,jsonb) OWNER TO ledger_owner;

-- Operator policy update joined to the candidate scope/lifecycle fence.
CREATE FUNCTION change_ledger.set_sweep_policy_v1(t text,c text,p_params jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; pk text; pv jsonb; num numeric; prev jsonb; lo_v numeric; hi_v numeric;
        merged jsonb; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_params IS NULL OR pg_catalog.jsonb_typeof(p_params)<>'object' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 FOR pk,pv IN SELECT * FROM pg_catalog.jsonb_each(p_params) LOOP
  IF NOT (change_ledger.sweep_constants() ? pk) OR pg_catalog.jsonb_typeof(pv)<>'number' THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  num:=(pv#>>'{}')::numeric;
  SELECT r.lo,r.hi INTO lo_v,hi_v FROM (VALUES
   ('claim_ttl_seconds',10,3600),('permit_ttl_seconds',10,600),('t12_window_seconds',60,86400),
   ('t12_max_attempts',1,50),('anchor_gap_window_seconds',60,86400),
   ('verify_max_attempts',1,20),('verify_min_tick_seconds',1,3600)
  ) AS r(kk,lo,hi) WHERE r.kk=pk;
  IF num<lo_v OR num>hi_v OR ((pk LIKE '%\_attempts') AND num<>pg_catalog.trunc(num)) THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 END LOOP;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT sp.params INTO prev FROM change_ledger.sweep_policy sp
  WHERE sp.tenant_id=t AND sp.company_id=c FOR UPDATE;
 merged:=coalesce(prev,'{}'::jsonb)||p_params;
 INSERT INTO change_ledger.sweep_policy(tenant_id,company_id,params,updated_by)
 VALUES(t,c,merged,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET params=EXCLUDED.params,updated_by=who,
  updated_at=pg_catalog.clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'SWEEP_POLICY_SET',
  pg_catalog.jsonb_build_object('previous',coalesce(prev,'{}'::jsonb),'params',merged,'by',who));
 RETURN merged;
END $fn$;
ALTER FUNCTION change_ledger.set_sweep_policy_v1(text,text,jsonb) OWNER TO ledger_owner;

 -- NOT VALID checks preserve legacy invalid rows for diagnosis while rejecting new or modified
 -- PostgreSQL numeric NaN values. budget_precheck below refuses legacy budget and reservation rows.
 ALTER TABLE change_ledger.grants ADD CONSTRAINT grants_amount_limit_not_nan
  CHECK (amount_limit<>'NaN'::numeric) NOT VALID;
 ALTER TABLE change_ledger.change_budget ADD CONSTRAINT change_budget_amount_not_nan
  CHECK (amount<>'NaN'::numeric) NOT VALID;
 ALTER TABLE change_ledger.reservations ADD CONSTRAINT reservations_amount_not_nan
  CHECK (amount<>'NaN'::numeric) NOT VALID;

 -- Fail closed on legacy non-finite monetary values as well as rejecting new inputs below.
-- The historical budget_precheck compares sums and limits numerically; PostgreSQL sorts NaN
-- above ordinary values, so a stored NaN grant limit could otherwise bypass the amount ceiling.
CREATE OR REPLACE FUNCTION change_ledger.budget_precheck(
 t text,c text,p_rec change_ledger.records,p_lock boolean,p_window boolean
) RETURNS numeric LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE cb change_ledger.change_budget%ROWTYPE; g change_ledger.grants%ROWTYPE; eff numeric;
        used_amount numeric; consumed_amount numeric; used_cu integer; used_post integer; tref text;
BEGIN
 SELECT * INTO cb FROM change_ledger.change_budget b WHERE b.change_id=p_rec.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF p_lock THEN
  SELECT * INTO g FROM change_ledger.grants x
   WHERE x.grant_id=cb.grant_id AND x.tenant_id=t AND x.company_id=c FOR UPDATE;
 ELSE
  SELECT * INTO g FROM change_ledger.grants x
   WHERE x.grant_id=cb.grant_id AND x.tenant_id=t AND x.company_id=c;
 END IF;
 IF NOT FOUND OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF pg_catalog.lower(cb.amount::text) IN ('nan','infinity','-infinity')
   OR pg_catalog.lower(g.amount_limit::text) IN ('nan','infinity','-infinity') THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 IF g.currency IS DISTINCT FROM cb.currency THEN RAISE EXCEPTION 'CURRENCY_NOT_BUDGETED'; END IF;
 IF p_window AND (pg_catalog.clock_timestamp()<g.window_start
   OR pg_catalog.clock_timestamp()>=g.window_end) THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 tref:=coalesce(p_rec.target_ref,p_rec.change_id::text);
 eff:=cb.amount;
 IF p_rec.kind='POST' THEN
  consumed_amount:=change_ledger.amount_consumed(t,c,tref,cb.grant_id);
  IF pg_catalog.lower(consumed_amount::text) IN ('nan','infinity','-infinity') THEN
   RAISE EXCEPTION 'BUDGET_EXCEEDED';
  END IF;
  eff:=greatest(eff-consumed_amount,0);
 END IF;
 SELECT coalesce(sum(r.amount),0),
        count(*) FILTER (WHERE r.counts_create_update),count(*) FILTER (WHERE r.counts_post)
  INTO used_amount,used_cu,used_post
  FROM change_ledger.reservations r
  WHERE r.grant_id=cb.grant_id AND r.state IN ('RESERVED','CONSUMED')
    AND r.change_id<>p_rec.change_id;
 IF pg_catalog.lower(used_amount::text) IN ('nan','infinity','-infinity') THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 IF used_amount+eff>g.amount_limit
  OR used_cu+(CASE WHEN cb.counts_create_update THEN 1 ELSE 0 END)>g.count_limit
  OR used_post+(CASE WHEN cb.counts_post THEN 1 ELSE 0 END)>g.post_count_limit THEN
  RAISE EXCEPTION 'BUDGET_EXCEEDED';
 END IF;
 RETURN eff;
END $fn$;
ALTER FUNCTION change_ledger.budget_precheck(text,text,change_ledger.records,boolean,boolean)
 OWNER TO ledger_owner;

-- Operator budget administration serialized on the global grant identity before row arbitration.
CREATE FUNCTION change_ledger.budget_admin_v1(
 t text,c text,p_grant_id uuid,p_currency text,p_amount_limit numeric,p_count_limit integer,
 p_post_count_limit integer,p_window_start timestamptz,p_window_end timestamptz
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; ex change_ledger.grants%ROWTYPE; gid uuid;
        lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'operator_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_currency IS NULL OR pg_catalog.length(p_currency)<>3 OR p_amount_limit IS NULL
  OR p_amount_limit<0 OR pg_catalog.lower(p_amount_limit::text) IN ('nan','infinity','-infinity')
  OR p_count_limit IS NULL OR p_count_limit<0 OR p_post_count_limit IS NULL OR p_post_count_limit<0
  OR (p_grant_id IS NOT NULL AND p_grant_id='00000000-0000-0000-0000-000000000000'::uuid)
  OR p_window_start IS NULL OR p_window_end IS NULL OR p_window_end<=p_window_start THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 gid:=coalesce(p_grant_id,pg_catalog.gen_random_uuid());

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'grant-id:v1:'||pg_catalog.lower(gid::text)
 ]);
 SELECT * INTO ex FROM change_ledger.grants g WHERE g.grant_id=gid FOR UPDATE;
 IF FOUND THEN
  IF ex.tenant_id IS DISTINCT FROM t OR ex.company_id IS DISTINCT FROM c THEN
   RAISE EXCEPTION 'SCOPE_NOT_GRANTED';
  END IF;
  IF ex.status<>'ACTIVE' OR ex.currency<>p_currency THEN
   RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
  END IF;
  UPDATE change_ledger.grants g SET amount_limit=p_amount_limit,count_limit=p_count_limit,
   post_count_limit=p_post_count_limit,window_start=p_window_start,window_end=p_window_end
   WHERE g.grant_id=gid AND g.tenant_id=t AND g.company_id=c;
 ELSE
  INSERT INTO change_ledger.grants(grant_id,tenant_id,company_id,currency,amount_limit,count_limit,
   post_count_limit,window_start,window_end)
  VALUES(gid,t,c,p_currency,p_amount_limit,p_count_limit,p_post_count_limit,p_window_start,p_window_end);
 END IF;
 PERFORM change_ledger.append_event(t,c,NULL,'BUDGET_GRANT_SET',
  pg_catalog.jsonb_build_object('grant_id',gid,'currency',p_currency,'amount_limit',p_amount_limit::text,
   'count_limit',p_count_limit,'post_count_limit',p_post_count_limit,'window_start',p_window_start,
   'window_end',p_window_end,'update',ex.grant_id IS NOT NULL,
   'previous',CASE WHEN ex.grant_id IS NULL THEN NULL ELSE pg_catalog.jsonb_build_object(
     'amount_limit',ex.amount_limit::text,'count_limit',ex.count_limit,
     'post_count_limit',ex.post_count_limit,'window_start',ex.window_start,'window_end',ex.window_end) END,
   'by',who));
 RETURN gid;
END $fn$;
ALTER FUNCTION change_ledger.budget_admin_v1(
 text,text,uuid,text,numeric,integer,integer,timestamptz,timestamptz) OWNER TO ledger_owner;

-- Operator grant revocation shares the global grant-ID fence with budget administration.
CREATE FUNCTION change_ledger.budget_revoke_v1(t text,c text,p_grant_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; ex change_ledger.grants%ROWTYPE; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'operator_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_grant_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'grant-id:v1:'||pg_catalog.lower(p_grant_id::text)
 ]);
 SELECT * INTO ex FROM change_ledger.grants g WHERE g.grant_id=p_grant_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF ex.tenant_id IS DISTINCT FROM t OR ex.company_id IS DISTINCT FROM c THEN
  RAISE EXCEPTION 'SCOPE_NOT_GRANTED';
 END IF;
 IF ex.status='REVOKED' THEN RETURN 'REVOKED'; END IF;
 UPDATE change_ledger.grants g SET status='REVOKED'
  WHERE g.grant_id=p_grant_id AND g.tenant_id=t AND g.company_id=c;
 PERFORM change_ledger.append_event(t,c,NULL,'BUDGET_GRANT_REVOKED',
  pg_catalog.jsonb_build_object('grant_id',p_grant_id,'by',who));
 RETURN 'REVOKED';
END $fn$;
ALTER FUNCTION change_ledger.budget_revoke_v1(text,text,uuid) OWNER TO ledger_owner;

-- Requester budget declaration freezes and revalidates both FK parents before child arbitration.
CREATE FUNCTION change_ledger.declare_budget_v1(
 t text,c text,p_change_id uuid,p_grant_id uuid,p_currency text,p_amount numeric,
 p_counts_create_update boolean,p_counts_post boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_grant change_ledger.grants%ROWTYPE; g change_ledger.grants%ROWTYPE;
        lc text; who text; grant_found boolean; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 IF p_change_id IS NULL OR p_grant_id IS NULL OR p_currency IS NULL OR pg_catalog.length(p_currency)<>3
  OR p_amount IS NULL OR p_amount<0
  OR pg_catalog.lower(p_amount::text) IN ('nan','infinity','-infinity')
  OR p_counts_create_update IS NULL OR p_counts_post IS NULL THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 SELECT * INTO plan_rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT * INTO plan_grant FROM change_ledger.grants x WHERE x.grant_id=p_grant_id;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'grant-id:v1:'||pg_catalog.lower(p_grant_id::text),
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text)
 ]);

 -- Parent order follows the candidate FK graph: grant before record, then budget child DML.
 SELECT * INTO g FROM change_ledger.grants x WHERE x.grant_id=p_grant_id FOR UPDATE;
 grant_found:=FOUND;
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 -- The plan freezes both complete FK parents, including mutable grant limits/windows and every
 -- record field. Never silently rebase an unlocked snapshot after the global-ID fences.
 IF plan_rec IS DISTINCT FROM rec OR plan_grant IS DISTINCT FROM g THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM who THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF NOT grant_found OR g.tenant_id IS DISTINCT FROM t OR g.company_id IS DISTINCT FROM c
   OR g.status<>'ACTIVE' THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF g.currency<>p_currency THEN RAISE EXCEPTION 'CURRENCY_NOT_BUDGETED'; END IF;
 INSERT INTO change_ledger.change_budget(change_id,tenant_id,company_id,grant_id,currency,amount,
  counts_create_update,counts_post,declared_by)
 VALUES(p_change_id,t,c,p_grant_id,p_currency,p_amount,p_counts_create_update,p_counts_post,who)
 ON CONFLICT(change_id) DO UPDATE SET grant_id=EXCLUDED.grant_id,currency=EXCLUDED.currency,
  amount=EXCLUDED.amount,counts_create_update=EXCLUDED.counts_create_update,
  counts_post=EXCLUDED.counts_post,declared_by=EXCLUDED.declared_by,
  declared_at=pg_catalog.clock_timestamp();
 lc:=rec.lifecycle;
 IF rec.lifecycle='VALIDATED' THEN
  UPDATE change_ledger.records SET lifecycle='PROPOSED',updated_at=pg_catalog.clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  lc:='PROPOSED';
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'BUDGET_DECLARED',
  pg_catalog.jsonb_build_object('grant_id',p_grant_id,'currency',p_currency,'amount',p_amount::text,
   'counts_create_update',p_counts_create_update,'counts_post',p_counts_post));
 RETURN lc;
END $fn$;
ALTER FUNCTION change_ledger.declare_budget_v1(text,text,uuid,uuid,text,numeric,boolean,boolean)
 OWNER TO ledger_owner;

-- Open-hold candidates preallocate a global ID and freeze the full target row/existing-hold predicate for one base.
CREATE FUNCTION change_ledger.private_writer_open_hold_v1(
 t text,c text,p_base text,p_cause text,p_event text,p_detail jsonb
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_targets jsonb; current_targets jsonb; plan_rows jsonb; plan_bases jsonb; current_bases jsonb;
        current_rows jsonb;
        global_keys text[]:=ARRAY[]::text[]; item record; opened integer:=0;
        target_count bigint;
BEGIN
 IF p_base IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
   PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT count(*) INTO target_count FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base;
 IF target_count>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;

   SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO plan_targets FROM (SELECT x.* FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base
     ORDER BY x.base_fingerprint LIMIT 201) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'base_fingerprint',x.base_fingerprint,'hold_id',pg_catalog.gen_random_uuid())
    ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO plan_rows FROM (SELECT x.base_fingerprint FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base
    AND NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=x.base_fingerprint AND h.cause=p_cause AND h.released_at IS NULL)
   ORDER BY x.base_fingerprint LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(plan_targets)>200 OR pg_catalog.jsonb_array_length(plan_rows)>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('base_fingerprint',x.base_fingerprint)
   ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO plan_bases FROM (SELECT x.base_fingerprint
    FROM pg_catalog.jsonb_to_recordset(plan_rows) AS x(base_fingerprint text,hold_id uuid)) x;
 FOR item IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_rows) AS x(base_fingerprint text,hold_id uuid)
  ORDER BY x.hold_id
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(item.hold_id::text));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 IF EXISTS(SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_rows) AS x(base_fingerprint text,hold_id uuid)
   GROUP BY x.hold_id HAVING count(*)>1)
   OR EXISTS(SELECT 1 FROM change_ledger.holds h JOIN pg_catalog.jsonb_to_recordset(plan_rows) AS x(
    base_fingerprint text,hold_id uuid) USING(hold_id)) THEN
  RAISE EXCEPTION 'HOLD_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':'||p_cause));
 SELECT count(*) INTO target_count FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base;
 IF plan_targets='[]'::jsonb THEN
  IF target_count>0 THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
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
    SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO current_targets FROM (SELECT x.* FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base
     ORDER BY x.base_fingerprint LIMIT 201) x;
 IF plan_targets IS DISTINCT FROM current_targets THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('base_fingerprint',x.base_fingerprint)
   ORDER BY x.base_fingerprint),'[]'::jsonb)
   INTO current_bases FROM (SELECT x.base_fingerprint FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base
    AND NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=x.base_fingerprint AND h.cause=p_cause AND h.released_at IS NULL)
   ORDER BY x.base_fingerprint LIMIT 201) x;
  IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(current_bases) AS current_base(base_fingerprint text)
    WHERE NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_bases) AS planned_base(base_fingerprint text)
      WHERE planned_base.base_fingerprint=current_base.base_fingerprint)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
  -- Namespace 3 serializes this one-base insert with peers. A peer may have opened the same hold
  -- after our plan; skip that base like the source routine, but refuse if a new target became
  -- eligible without a preallocated/fenced hold ID.
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'base_fingerprint',planned.base_fingerprint,'hold_id',planned.hold_id)
    ORDER BY planned.base_fingerprint),'[]'::jsonb)
   INTO current_rows FROM pg_catalog.jsonb_to_recordset(plan_rows) AS planned(
    base_fingerprint text,hold_id uuid)
   WHERE EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(current_bases) AS eligible(base_fingerprint text)
     WHERE eligible.base_fingerprint=planned.base_fingerprint);

  FOR item IN SELECT x.base_fingerprint,x.hold_id
    FROM pg_catalog.jsonb_to_recordset(current_rows) AS x(base_fingerprint text,hold_id uuid)
   ORDER BY x.base_fingerprint
 LOOP
  INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause)
   VALUES(item.hold_id,t,c,item.base_fingerprint,p_cause);
  opened:=opened+1;
 END LOOP;
 IF opened>0 THEN
  PERFORM change_ledger.append_event(t,c,NULL,p_event,
   coalesce(p_detail,'{}'::jsonb)||pg_catalog.jsonb_build_object('cause',p_cause,'bases_held',opened));
 END IF;
 RETURN opened;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_open_hold_v1(text,text,text,text,text,jsonb) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.declare_anchor_gap_v1(t text,c text,p_base text,p_detail jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.private_writer_open_hold_v1(t,c,p_base,'ANCHOR_GAP','ANCHOR_GAP',
  coalesce(p_detail,'{}'::jsonb)||pg_catalog.jsonb_build_object('source','DECLARED'));
END $fn$;
ALTER FUNCTION change_ledger.declare_anchor_gap_v1(text,text,text,jsonb) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.declare_unclean_restart_v1(t text,c text,p_base text,p_detail jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.private_writer_open_hold_v1(t,c,p_base,'RLC_UNCLEAN','UNCLEAN_RESTART',p_detail);
END $fn$;
ALTER FUNCTION change_ledger.declare_unclean_restart_v1(text,text,text,jsonb) OWNER TO ledger_owner;

-- Anchor reconciliation freezes all affected hold rows and generated IDs before any write.
CREATE FUNCTION change_ledger.check_anchor_v1(t text,c text,p_ext_seq bigint,p_ext_head_hash text)
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
ALTER FUNCTION change_ledger.check_anchor_v1(text,text,bigint,text) OWNER TO ledger_owner;

-- Claim candidate freezes every parent/resource identity before locking the FK graph.
CREATE FUNCTION change_ledger.claim_v1(
 t text,c text,p_change_id uuid,p_key_hash text,p_grant_id uuid,p_amount numeric,
 p_counts_create_update boolean,p_counts_post boolean,p_token_id uuid
) RETURNS change_ledger.claim_tokens
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; lf change_ledger.lifecycle_fences%ROWTYPE; lf_found boolean;
        plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE; parent change_ledger.records%ROWTYPE;
        plan_grant change_ledger.grants%ROWTYPE; g change_ledger.grants%ROWTYPE;
        plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
        plan_budget change_ledger.change_budget%ROWTYPE; cb change_ledger.change_budget%ROWTYPE;
         current_business_key change_ledger.business_keys%ROWTYPE;
         plan_owned_key change_ledger.key_locks%ROWTYPE; current_owned_key change_ledger.key_locks%ROWTYPE;
        current_owned_key_snapshot jsonb;
        tok change_ledger.claim_tokens%ROWTYPE;
        plan_reservation change_ledger.reservations%ROWTYPE; reservation change_ledger.reservations%ROWTYPE;
        plan_target_lock change_ledger.target_locks%ROWTYPE; target_lock change_ledger.target_locks%ROWTYPE;
        plan_key_lock change_ledger.key_locks%ROWTYPE; key_lock change_ledger.key_locks%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_business_key change_ledger.business_keys%ROWTYPE;
        rec_found boolean; grant_found boolean; target_found boolean; budget_found boolean;
         token_found boolean; reservation_found boolean; target_lock_found boolean;
         current_business_key_found boolean;
         plan_owned_key_found boolean; current_owned_key_found boolean;
         plan_owned_key_count integer; current_owned_key_count integer;
        key_lock_found boolean; lease_found boolean; business_key_found boolean;
        plan_grant_found boolean; plan_target_found boolean; plan_budget_found boolean;
        plan_reservation_found boolean; plan_target_lock_found boolean;
        plan_key_lock_found boolean; plan_lease_found boolean;
        record_ids uuid[]; global_keys text[]:=ARRAY[]::text[]; key_keys text[]:=ARRAY[]::text[];
        record_id uuid; lock_hash integer; v_target_ref text; v_key_hash text;
        eff_amount numeric; gen bigint;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
  IF p_token_id IS NULL OR p_token_id='00000000-0000-0000-0000-000000000000'::uuid THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 lf_found:=FOUND;

 -- Build the non-locking plan after entry fences. No relation lock is taken here.
 SELECT * INTO plan_rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);
 SELECT * INTO plan_budget FROM change_ledger.change_budget b WHERE b.change_id=p_change_id;
 plan_budget_found:=FOUND;
 IF plan_budget_found THEN
  SELECT * INTO plan_grant FROM change_ledger.grants x WHERE x.grant_id=plan_budget.grant_id;
  plan_grant_found:=FOUND;
 ELSE
  plan_grant_found:=false;
 END IF;
 SELECT * INTO plan_business_key FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 business_key_found:=FOUND;
  SELECT count(*)::integer INTO plan_owned_key_count FROM (
   SELECT 1 FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id LIMIT 2
  ) owned_keys;
  IF plan_owned_key_count>1 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
  IF plan_owned_key_count=1 THEN
   SELECT * INTO plan_owned_key FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id;
   plan_owned_key_found:=FOUND;
  ELSE plan_owned_key_found:=false; END IF;
  IF plan_owned_key_found AND (plan_owned_key.tenant_id IS DISTINCT FROM t
    OR plan_owned_key.company_id IS DISTINCT FROM c
    OR plan_owned_key.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 IF business_key_found THEN v_key_hash:=plan_business_key.key_hash;
 ELSIF plan_rec.kind<>'CREATE_DRAFT' THEN v_key_hash:=p_key_hash;
 ELSE v_key_hash:=NULL;
 END IF;
 v_target_ref:=coalesce(plan_rec.target_ref,p_change_id::text);
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_target_found:=FOUND;
 SELECT * INTO plan_target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=v_target_ref;
 plan_target_lock_found:=FOUND;
 IF v_key_hash IS NOT NULL THEN
  SELECT * INTO plan_key_lock FROM change_ledger.key_locks x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
    AND x.key_hash=v_key_hash;
  plan_key_lock_found:=FOUND;
 ELSE plan_key_lock_found:=false; END IF;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_lease_found:=FOUND;
 SELECT * INTO plan_reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id;
 plan_reservation_found:=FOUND;

 record_ids:=ARRAY[p_change_id];
 IF plan_rec.repair_for IS NOT NULL THEN record_ids:=pg_catalog.array_append(record_ids,plan_rec.repair_for);
 ELSIF plan_rec.parent_change_id IS NOT NULL THEN
  record_ids:=pg_catalog.array_append(record_ids,plan_rec.parent_change_id);
 END IF;
 IF plan_target_lock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_target_lock.owner_change_id); END IF;
 IF plan_key_lock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_key_lock.owner_change_id); END IF;
 IF plan_lease_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_lease.owner_change_id); END IF;
 FOR record_id IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
   WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,
   'record-change-id:v1:'||pg_catalog.lower(record_id::text));
 END LOOP;
 IF plan_budget_found THEN global_keys:=pg_catalog.array_append(global_keys,
  'grant-id:v1:'||pg_catalog.lower(plan_budget.grant_id::text)); END IF;
 global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(p_token_id::text));

  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);
  -- Every planned FK owner must be a record in this claim's scope. The FK on these
  -- resource tables binds only change_id, so a malformed cross-scope owner would not
  -- be locked by the scoped records loop below. Reject it before namespace-4/resource
  -- locks; also require each selected resource owner's base to match its lock identity.
  PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
   t,c,record_ids,plan_rec.base_fingerprint,v_target_ref,v_key_hash,true);
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
       ORDER BY x.tenant_id,x.company_id,x.base_fingerprint,x.key_hash),'[]'::jsonb)
    INTO current_owned_key_snapshot
    FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id;
  IF plan_owned_key_found THEN
   IF current_owned_key_snapshot IS DISTINCT FROM
      pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(plan_owned_key)) THEN
    RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
   END IF;
  ELSIF current_owned_key_snapshot IS DISTINCT FROM '[]'::jsonb THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  key_keys:=pg_catalog.array_append(key_keys,
  'target-lock:v1:'||t||':'||c||':'||plan_rec.base_fingerprint||':'||v_target_ref);
 IF v_key_hash IS NOT NULL THEN key_keys:=pg_catalog.array_append(key_keys,
  t||':'||c||':'||plan_rec.base_fingerprint||':'||v_key_hash); END IF;
  IF plan_owned_key_found THEN key_keys:=pg_catalog.array_append(key_keys,
   plan_owned_key.tenant_id||':'||plan_owned_key.company_id||':'||
   plan_owned_key.base_fingerprint||':'||plan_owned_key.key_hash); END IF;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS x(k)
   ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;
 IF EXISTS(SELECT 1 FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id) THEN
  RAISE EXCEPTION 'CLAIM_TOKEN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;

 -- Lock FK parents in deterministic relation order, then the records SCC, then child rows.
 IF plan_budget_found THEN
  SELECT * INTO g FROM change_ledger.grants x WHERE x.grant_id=plan_budget.grant_id FOR UPDATE;
  grant_found:=FOUND;
 ELSE grant_found:=false; END IF;
 SELECT * INTO target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
 target_found:=FOUND;
 FOR record_id IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
   WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  PERFORM 1 FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=record_id FOR UPDATE;
 END LOOP;
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 rec_found:=FOUND;
  SELECT * INTO current_business_key FROM change_ledger.business_keys b
   WHERE b.change_id=p_change_id FOR UPDATE;
  current_business_key_found:=FOUND;
 IF plan_budget_found THEN
  SELECT * INTO cb FROM change_ledger.change_budget x WHERE x.change_id=p_change_id FOR UPDATE;
  budget_found:=FOUND;
 ELSE budget_found:=false; END IF;
 IF rec_found AND rec.claim_generation<9223372036854775807 THEN
  SELECT * INTO tok FROM change_ledger.claim_tokens x
   WHERE x.change_id=p_change_id AND x.generation=rec.claim_generation AND x.state='ISSUED' FOR UPDATE;
  token_found:=FOUND;
 ELSE token_found:=false; END IF;
  PERFORM 1 FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id
   ORDER BY k.tenant_id,k.company_id,k.base_fingerprint,k.key_hash LIMIT 2 FOR UPDATE;
  SELECT count(*)::integer INTO current_owned_key_count FROM (
   SELECT 1 FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id LIMIT 2
  ) owned_keys;
  IF current_owned_key_count>1 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
  IF current_owned_key_count=1 THEN
   SELECT * INTO current_owned_key FROM change_ledger.key_locks k
    WHERE k.owner_change_id=p_change_id;
   current_owned_key_found:=FOUND;
  ELSE current_owned_key_found:=false; END IF;
 IF NOT rec_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 IF plan_rec IS DISTINCT FROM rec
   OR plan_budget_found IS DISTINCT FROM budget_found
    OR (plan_budget_found AND plan_budget IS DISTINCT FROM cb)
    OR business_key_found IS DISTINCT FROM current_business_key_found
    OR (business_key_found AND plan_business_key IS DISTINCT FROM current_business_key)
    OR plan_owned_key_found IS DISTINCT FROM current_owned_key_found
    OR (plan_owned_key_found AND plan_owned_key IS DISTINCT FROM current_owned_key)
   OR plan_grant_found IS DISTINCT FROM grant_found
   OR (plan_grant_found AND plan_grant IS DISTINCT FROM g)
   OR plan_target_found IS DISTINCT FROM target_found
   OR (plan_target_found AND plan_target IS DISTINCT FROM target) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
  IF who IS DISTINCT FROM rec.requester THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;

  -- Preserve the live-token replay before lifecycle-readiness, switch-state, and budget checks.
 IF rec.authorization_state='CLAIMED' AND rec.execution_state='NOT_STARTED' AND token_found THEN
  IF NOT budget_found OR p_grant_id IS DISTINCT FROM cb.grant_id THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
  IF p_amount IS DISTINCT FROM cb.amount
   OR coalesce(p_counts_create_update,false) IS DISTINCT FROM cb.counts_create_update
   OR coalesce(p_counts_post,false) IS DISTINCT FROM cb.counts_post THEN
   RAISE EXCEPTION 'DIGEST_MISMATCH';
  END IF;
   -- Exact replay binds every supplied immutable claim argument before returning its token.
   -- Fresh-claim validation remains below this fast path to preserve its error precedence.
   IF business_key_found AND p_key_hash IS NOT NULL
     AND p_key_hash IS DISTINCT FROM plan_business_key.key_hash THEN
    RAISE EXCEPTION 'DIGEST_MISMATCH';
   END IF;
   IF (v_key_hash IS NULL AND plan_owned_key_found)
     OR (v_key_hash IS NOT NULL AND (NOT plan_owned_key_found
       OR plan_owned_key.owner_change_id IS DISTINCT FROM p_change_id
       OR plan_owned_key.tenant_id IS DISTINCT FROM t
       OR plan_owned_key.company_id IS DISTINCT FROM c
       OR plan_owned_key.base_fingerprint IS DISTINCT FROM rec.base_fingerprint
       OR plan_owned_key.key_hash IS DISTINCT FROM v_key_hash)) THEN
    RAISE EXCEPTION 'DIGEST_MISMATCH';
   END IF;
  RETURN tok;
 END IF;
 IF v_key_hash IS NOT NULL THEN
  SELECT * INTO key_lock FROM change_ledger.key_locks x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
    AND x.key_hash=v_key_hash FOR UPDATE;
  key_lock_found:=FOUND;
 ELSE key_lock_found:=false; END IF;
 SELECT * INTO reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id FOR UPDATE;
 reservation_found:=FOUND;
 SELECT * INTO target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=v_target_ref FOR UPDATE;
 target_lock_found:=FOUND;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 lease_found:=FOUND;
 IF plan_reservation_found IS DISTINCT FROM reservation_found
   OR (plan_reservation_found AND plan_reservation IS DISTINCT FROM reservation)
   OR plan_target_lock_found IS DISTINCT FROM target_lock_found
   OR (plan_target_lock_found AND plan_target_lock IS DISTINCT FROM target_lock)
   OR plan_key_lock_found IS DISTINCT FROM key_lock_found
   OR (plan_key_lock_found AND plan_key_lock IS DISTINCT FROM key_lock)
   OR plan_lease_found IS DISTINCT FROM lease_found
   OR (plan_lease_found AND plan_lease IS DISTINCT FROM lease) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 
 IF rec.execution_state<>'NOT_STARTED' OR rec.verification_state<>'NOT_VERIFIED'
   OR rec.dispatch_state='DISPATCHED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF rec.authorization_state IN ('VOIDED','REVOKED') THEN RAISE EXCEPTION 'APPROVAL_VOIDED'; END IF;
 IF rec.authorization_state<>'APPROVED' THEN RAISE EXCEPTION 'APPROVAL_MISSING'; END IF;
 IF rec.expires_at<=pg_catalog.clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 PERFORM change_ledger.assert_approval_current(t,c,rec);
 PERFORM change_ledger.assert_switch_off(t,c);
 IF NOT lf_found OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 IF change_ledger.blocking_hold(t,c,rec.base_fingerprint,rec.repair_for) THEN
  RAISE EXCEPTION 'BASE_HOLD';
 END IF;
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN RAISE EXCEPTION 'EPOCH_CHANGED'; END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,
  rec.declared_target_class);
 PERFORM change_ledger.assert_registry_for_effect(t,c,rec.base_fingerprint);

 IF business_key_found THEN
  IF p_key_hash IS NOT NULL AND p_key_hash IS DISTINCT FROM plan_business_key.key_hash THEN
   RAISE EXCEPTION 'DIGEST_MISMATCH';
  END IF;
  v_key_hash:=plan_business_key.key_hash;
 ELSIF rec.kind='CREATE_DRAFT' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 ELSE
  v_key_hash:=p_key_hash;
 END IF;
 IF NOT budget_found OR p_grant_id IS DISTINCT FROM cb.grant_id THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
 IF p_amount IS DISTINCT FROM cb.amount
   OR coalesce(p_counts_create_update,false) IS DISTINCT FROM cb.counts_create_update
   OR coalesce(p_counts_post,false) IS DISTINCT FROM cb.counts_post THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 IF cb.grant_id IS DISTINCT FROM plan_budget.grant_id THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 v_target_ref:=coalesce(rec.target_ref,p_change_id::text);
 IF rec.repair_for IS NOT NULL THEN
  SELECT * INTO parent FROM change_ledger.records p
   WHERE p.tenant_id=t AND p.company_id=c AND p.change_id=rec.repair_for;
  IF NOT FOUND OR parent.verification_state<>'FAILED_VERIFY' OR parent.effect_known IS DISTINCT FROM 'YES'
    OR parent.target_ref IS DISTINCT FROM rec.target_ref
    OR parent.base_fingerprint IS DISTINCT FROM rec.base_fingerprint
    OR NOT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
      AND h.base_fingerprint=rec.base_fingerprint AND h.cause='FAILED_VERIFY_HALT'
      AND h.change_id=rec.repair_for AND h.released_at IS NULL) THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 ELSIF rec.parent_change_id IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.records p WHERE p.tenant_id=t AND p.company_id=c
    AND p.change_id=rec.parent_change_id AND p.verification_state='VERIFIED') THEN
   RAISE EXCEPTION 'PARENT_NOT_VERIFIED';
  END IF;
 END IF;

 BEGIN
  eff_amount:=change_ledger.budget_precheck(t,c,rec,true,true);
  INSERT INTO change_ledger.reservations(change_id,grant_id,amount,counts_create_update,counts_post)
  VALUES(p_change_id,cb.grant_id,eff_amount,cb.counts_create_update,cb.counts_post)
  ON CONFLICT(change_id) DO UPDATE SET grant_id=EXCLUDED.grant_id,amount=EXCLUDED.amount,
   counts_create_update=EXCLUDED.counts_create_update,counts_post=EXCLUDED.counts_post,
   state='RESERVED',reserved_at=pg_catalog.clock_timestamp()
   WHERE change_ledger.reservations.state='RELEASED';
  IF NOT EXISTS(SELECT 1 FROM change_ledger.reservations r
    WHERE r.change_id=p_change_id AND r.state='RESERVED') THEN RAISE EXCEPTION 'BUDGET_EXCEEDED'; END IF;
  IF rec.repair_for IS NOT NULL THEN
   IF NOT change_ledger.handoff_target_lock(t,c,rec.base_fingerprint,v_target_ref,
       rec.repair_for,rec.change_id) THEN RAISE EXCEPTION 'LOCK_BUSY'; END IF;
  ELSE
   INSERT INTO change_ledger.target_locks(tenant_id,company_id,base_fingerprint,target_ref,owner_change_id)
   VALUES(t,c,rec.base_fingerprint,v_target_ref,p_change_id);
  END IF;
  IF v_key_hash IS NOT NULL THEN
   INSERT INTO change_ledger.key_locks(tenant_id,company_id,base_fingerprint,key_hash,owner_change_id)
   VALUES(t,c,rec.base_fingerprint,v_key_hash,p_change_id);
  END IF;
  INSERT INTO change_ledger.writer_leases(tenant_id,company_id,base_fingerprint,owner_change_id)
  VALUES(t,c,rec.base_fingerprint,p_change_id);
 EXCEPTION WHEN unique_violation THEN
  RAISE EXCEPTION 'LOCK_BUSY';
 END;

 gen:=rec.claim_generation+1;
 -- Updating claim_generation may carry an immutable dispatch-receipt marker in migration 017's AFTER trigger.
 UPDATE change_ledger.records SET authorization_state='CLAIMED',execution_state='NOT_STARTED',
  claim_generation=gen,reservation_state='RESERVED',updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 INSERT INTO change_ledger.claim_tokens(token_id,change_id,generation)
  VALUES(p_token_id,p_change_id,gen) RETURNING * INTO tok;
 PERFORM change_ledger.append_event(t,c,p_change_id,'CLAIMED',
  pg_catalog.jsonb_build_object('generation',gen,'token_id',tok.token_id));
 RETURN tok;
END $fn$;
ALTER FUNCTION change_ledger.claim_v1(text,text,uuid,text,uuid,numeric,boolean,boolean,uuid)
 OWNER TO ledger_owner;

-- Preserve the granted legacy signature as the caller boundary while imposing claim_v1's
-- namespace-7 and parent-first lock plan. The token ID is allocated before the candidate body
-- acquires any ranked lock; direct execution of claim_v1 remains revoked.
CREATE OR REPLACE FUNCTION change_ledger.claim(
 t text,c text,p_change_id uuid,p_key_hash text,p_grant_id uuid,p_amount numeric,
 p_counts_create_update boolean,p_counts_post boolean
) RETURNS change_ledger.claim_tokens
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.claim_v1(t,c,p_change_id,p_key_hash,p_grant_id,p_amount,
  p_counts_create_update,p_counts_post,pg_catalog.gen_random_uuid());
END $fn$;
ALTER FUNCTION change_ledger.claim(text,text,uuid,text,uuid,numeric,boolean,boolean) OWNER TO ledger_owner;

-- Candidate adapter bridge preserves its preallocated token identity without granting direct
-- execution of the versioned body. The caller still enters through this narrow SECURITY DEFINER
-- function, which delegates scope, entitlement, epoch, and ranked-lock checks to claim_v1.
CREATE FUNCTION change_ledger.claim_with_id_v1(
 t text,c text,p_change_id uuid,p_key_hash text,p_grant_id uuid,p_amount numeric,
 p_counts_create_update boolean,p_counts_post boolean,p_token_id uuid
) RETURNS change_ledger.claim_tokens
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.claim_v1(t,c,p_change_id,p_key_hash,p_grant_id,p_amount,
  p_counts_create_update,p_counts_post,p_token_id);
END $fn$;
ALTER FUNCTION change_ledger.claim_with_id_v1(
 text,text,uuid,text,uuid,numeric,boolean,boolean,uuid) OWNER TO ledger_owner;

-- Claim release takes record parents before the token/resource children and freezes the helper effects.
CREATE FUNCTION change_ledger.release_claim_v1(t text,c text,p_token_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE caller text;
        plan_tok change_ledger.claim_tokens%ROWTYPE; tok change_ledger.claim_tokens%ROWTYPE;
        plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
        plan_target_lock change_ledger.target_locks%ROWTYPE; target_lock change_ledger.target_locks%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_reservation change_ledger.reservations%ROWTYPE; reservation change_ledger.reservations%ROWTYPE;
        plan_keys jsonb; current_keys jsonb; plan_target_found boolean; target_found boolean;
        plan_target_lock_found boolean; target_lock_found boolean; plan_lease_found boolean;
        lease_found boolean; plan_reservation_found boolean; reservation_found boolean;
         tok_found boolean; rec_found boolean; parent_ids uuid[]:='{}'::uuid[];
         plan_parents jsonb; current_parents jsonb; record_ids uuid[];
         global_keys text[]:=ARRAY[]::text[];
        key_keys text[]:=ARRAY[]::text[]; rid uuid; key_row record; lock_hash integer; tref text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 caller:=change_ledger.caller_role();
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 -- Take the ranked lifecycle lock; this legacy path has no lifecycle-readiness rejection.
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;

 -- Freeze the token, record and every resource row the legacy release helper can touch.
 SELECT * INTO plan_tok FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=plan_tok.change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,plan_rec.change_id,plan_rec.base_fingerprint);
 tref:=coalesce(plan_rec.target_ref,plan_rec.change_id::text);
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_target_found:=FOUND;
 SELECT * INTO plan_target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref;
 plan_target_lock_found:=FOUND;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_lease_found:=FOUND;
 SELECT * INTO plan_reservation FROM change_ledger.reservations x
  WHERE x.change_id=plan_rec.change_id;
 plan_reservation_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash), '[]'::jsonb)
  INTO plan_keys FROM change_ledger.key_locks x WHERE x.owner_change_id=plan_rec.change_id;
  IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
     tenant_id text,company_id text,base_fingerprint text)
    WHERE x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
     OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;

  record_ids:=ARRAY[plan_rec.change_id];
  IF plan_rec.repair_for IS NOT NULL THEN
   parent_ids:=ARRAY[plan_rec.repair_for];
  ELSIF plan_rec.parent_change_id IS NOT NULL THEN
   parent_ids:=ARRAY[plan_rec.parent_change_id];
  END IF;
  IF pg_catalog.cardinality(parent_ids)>0 THEN
   SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
    INTO plan_parents FROM change_ledger.records x WHERE x.change_id=ANY(parent_ids);
   IF pg_catalog.jsonb_array_length(plan_parents)<>pg_catalog.cardinality(parent_ids)
     OR EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_parents) AS x(
       tenant_id text,company_id text) WHERE x.tenant_id IS DISTINCT FROM t
        OR x.company_id IS DISTINCT FROM c) THEN
    RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
   END IF;
   record_ids:=record_ids||parent_ids;
  ELSE
   plan_parents:='[]'::jsonb;
  END IF;
 IF plan_target_lock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_target_lock.owner_change_id); END IF;
 IF plan_lease_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_lease.owner_change_id); END IF;
 FOR rid IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
   WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
 END LOOP;
 global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(p_token_id::text));
  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,plan_rec.change_id,plan_rec.base_fingerprint);
 PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
  t,c,record_ids,plan_rec.base_fingerprint,tref,NULL,true);
  IF (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
       ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
      FROM change_ledger.key_locks x WHERE x.owner_change_id=plan_rec.change_id)
    IS DISTINCT FROM plan_keys THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;

  key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||
  plan_rec.base_fingerprint||':'||tref);
 FOR key_row IN SELECT x.key_hash FROM change_ledger.key_locks x
   WHERE x.owner_change_id=plan_rec.change_id ORDER BY x.key_hash
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||plan_rec.base_fingerprint||':'||key_row.key_hash);
 END LOOP;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS x(k) ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;

 -- Parent rows precede the record SCC; child rows are acquired in qualified-name order.
 IF plan_target_found THEN
  SELECT * INTO target FROM change_ledger.targets x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
  target_found:=FOUND;
 ELSE target_found:=false; END IF;
 FOR rid IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
   WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  PERFORM 1 FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=rid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
   INTO current_parents FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=ANY(parent_ids);
  IF current_parents IS DISTINCT FROM plan_parents THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=plan_rec.change_id;
 rec_found:=FOUND;
 IF rec_found THEN
  SELECT * INTO tok FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id FOR UPDATE;
  tok_found:=FOUND;
 ELSE tok_found:=false; END IF;
 IF NOT rec_found OR NOT tok_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 IF plan_tok IS DISTINCT FROM tok OR plan_rec IS DISTINCT FROM rec
   OR plan_target_found IS DISTINCT FROM target_found
   OR (plan_target_found AND plan_target IS DISTINCT FROM target) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=plan_rec.change_id
  ORDER BY x.base_fingerprint,x.key_hash FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash), '[]'::jsonb)
  INTO current_keys FROM change_ledger.key_locks x WHERE x.owner_change_id=plan_rec.change_id;
 SELECT * INTO reservation FROM change_ledger.reservations x WHERE x.change_id=plan_rec.change_id FOR UPDATE;
 reservation_found:=FOUND;
 SELECT * INTO target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref FOR UPDATE;
 target_lock_found:=FOUND;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 lease_found:=FOUND;
 IF plan_keys IS DISTINCT FROM current_keys
   OR plan_reservation_found IS DISTINCT FROM reservation_found
   OR (plan_reservation_found AND plan_reservation IS DISTINCT FROM reservation)
   OR plan_target_lock_found IS DISTINCT FROM target_lock_found
   OR (plan_target_lock_found AND plan_target_lock IS DISTINCT FROM target_lock)
   OR plan_lease_found IS DISTINCT FROM lease_found
   OR (plan_lease_found AND plan_lease IS DISTINCT FROM lease) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF caller IS DISTINCT FROM rec.requester AND NOT pg_catalog.pg_has_role(caller::name,'worker_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF tok.state<>'ISSUED' THEN RETURN tok.state; END IF;
  -- The legacy ordinary release path treats a zero-row scoped delete as success. Require the
  -- exact frozen owner before changing this issued token, after preserving lookup-only replay.
  IF NOT target_lock_found OR target_lock.owner_change_id IS DISTINCT FROM plan_rec.change_id THEN
   RAISE EXCEPTION 'LOCK_BUSY';
  END IF;
 UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE token_id=p_token_id;
 PERFORM change_ledger.release_zero_effect(t,c,rec.change_id);
 UPDATE change_ledger.records SET
  authorization_state=CASE WHEN rec.expires_at<=pg_catalog.clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
  execution_state='NOT_STARTED',updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
 PERFORM change_ledger.append_event(t,c,rec.change_id,'CLAIM_RELEASED','{}'::jsonb);
 RETURN 'SUPERSEDED';
END $fn$;
ALTER FUNCTION change_ledger.release_claim_v1(text,text,uuid) OWNER TO ledger_owner;

-- Preserve the historical EXECUTE grants while routing every legacy caller through the same
-- parent-first lock order as claim_v1; otherwise token→record release can deadlock against a
-- record→token claim replay. Caller identity remains based on SESSION_USER/current role inside
-- caller_role(), and the versioned body retains the legacy no-lifecycle-readiness behavior.
CREATE OR REPLACE FUNCTION change_ledger.release_claim(t text,c text,p_token_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.release_claim_v1(t,c,p_token_id);
END $fn$;
ALTER FUNCTION change_ledger.release_claim(text,text,uuid) OWNER TO ledger_owner;

-- Hold release freezes optional cosign identity before global-fence and parent-first row work.
CREATE FUNCTION change_ledger.revoke_change_v1(t text,c text,p_change_id uuid,p_cause text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
        plan_tlock change_ledger.target_locks%ROWTYPE; tlock change_ledger.target_locks%ROWTYPE;
        plan_res change_ledger.reservations%ROWTYPE; res change_ledger.reservations%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_tokens jsonb; tokens jsonb; plan_keys jsonb; keys_now jsonb;
        target_found boolean; tlock_found boolean; res_found boolean; lease_found boolean;
        global_keys text[]:=ARRAY[]::text[]; key_keys text[]:=ARRAY[]::text[];
        record_ids uuid[]; rid uuid; item record; lock_hash integer; tref text; lock_count integer;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF p_cause IS NULL OR p_cause NOT IN ('SESSION_REVOKED','ROLE_REVOKED','APPROVER_REVOKED','EPOCH_DEPENDENCY') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);
 tref:=coalesce(plan_rec.target_ref,p_change_id::text);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO plan_tokens FROM (SELECT x.* FROM change_ledger.claim_tokens x
   WHERE x.change_id=p_change_id ORDER BY x.token_id LIMIT 197) x;
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 target_found:=FOUND;
 SELECT * INTO plan_tlock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref;
 tlock_found:=FOUND;
 SELECT * INTO plan_res FROM change_ledger.reservations x WHERE x.change_id=p_change_id;
 res_found:=FOUND;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 lease_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO plan_keys FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
   ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(plan_tokens)>196 OR pg_catalog.jsonb_array_length(plan_keys)>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
    tenant_id text,company_id text,base_fingerprint text)
   WHERE x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
    OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 record_ids:=ARRAY[p_change_id];
 IF plan_rec.repair_for IS NOT NULL THEN record_ids:=pg_catalog.array_append(record_ids,plan_rec.repair_for);
 ELSIF plan_rec.parent_change_id IS NOT NULL THEN
  record_ids:=pg_catalog.array_append(record_ids,plan_rec.parent_change_id);
 END IF;
 IF tlock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_tlock.owner_change_id); END IF;
 IF lease_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_lease.owner_change_id); END IF;
 SELECT coalesce(pg_catalog.array_agg(DISTINCT u.lock_id ORDER BY u.lock_id),'{}'::uuid[])
  INTO record_ids FROM pg_catalog.unnest(record_ids) AS u(lock_id) WHERE u.lock_id IS NOT NULL;
 lock_count:=pg_catalog.cardinality(record_ids)+pg_catalog.jsonb_array_length(plan_tokens)
  +pg_catalog.jsonb_array_length(plan_keys)+CASE WHEN target_found THEN 1 ELSE 0 END
  +CASE WHEN tlock_found THEN 1 ELSE 0 END+CASE WHEN res_found THEN 1 ELSE 0 END
  +CASE WHEN lease_found THEN 1 ELSE 0 END;
 IF lock_count>200 OR pg_catalog.jsonb_array_length(plan_tokens)>196
    OR pg_catalog.jsonb_array_length(plan_keys)>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 FOR rid IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
  WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
 END LOOP;
 FOR item IN SELECT x.token_id FROM pg_catalog.jsonb_to_recordset(plan_tokens) AS x(
   token_id uuid,change_id uuid,generation bigint,state text,issued_at timestamptz)
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(item.token_id::text));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,plan_rec.base_fingerprint);
 PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
  t,c,record_ids,plan_rec.base_fingerprint,tref,NULL,true);
 IF (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
      ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
     FROM (SELECT k.* FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id
      ORDER BY k.base_fingerprint,k.key_hash LIMIT 201) x)
   IS DISTINCT FROM plan_keys THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;

 key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||plan_rec.base_fingerprint||':'||tref);
 FOR item IN SELECT x.base_fingerprint,x.key_hash FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
   tenant_id text,company_id text,base_fingerprint text,key_hash text,owner_change_id uuid)
  ORDER BY x.base_fingerprint,x.key_hash
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||item.base_fingerprint||':'||item.key_hash);
 END LOOP;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS x(k) ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;
 SELECT * INTO target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
 IF target_found IS DISTINCT FROM FOUND OR (target_found AND plan_target IS DISTINCT FROM target) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 FOR rid IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
  WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  PERFORM 1 FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=rid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR plan_rec IS DISTINCT FROM rec THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM 1 FROM change_ledger.claim_tokens x WHERE x.change_id=p_change_id
  ORDER BY x.token_id LIMIT 197 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO tokens FROM (SELECT x.* FROM change_ledger.claim_tokens x WHERE x.change_id=p_change_id
   ORDER BY x.token_id LIMIT 197) x;
 IF pg_catalog.jsonb_array_length(tokens)>196 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
  ORDER BY x.base_fingerprint,x.key_hash LIMIT 201 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO keys_now FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
   ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(keys_now)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT * INTO res FROM change_ledger.reservations x WHERE x.change_id=p_change_id FOR UPDATE;
 IF res_found IS DISTINCT FROM FOUND OR (res_found AND plan_res IS DISTINCT FROM res) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO tlock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref FOR UPDATE;
 IF tlock_found IS DISTINCT FROM FOUND OR (tlock_found AND plan_tlock IS DISTINCT FROM tlock) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 IF lease_found IS DISTINCT FROM FOUND OR (lease_found AND plan_lease IS DISTINCT FROM lease)
    OR plan_tokens IS DISTINCT FROM tokens OR plan_keys IS DISTINCT FROM keys_now THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 RETURN change_ledger.revoke_core(t,c,p_change_id,p_cause);
END $fn$;
ALTER FUNCTION change_ledger.revoke_change_v1(text,text,uuid,text) OWNER TO ledger_owner;

-- Stale-epoch recovery freezes a fair, small bounded batch before the first item can append an event.
CREATE FUNCTION change_ledger.revoke_stale_v1(t text,c text) RETURNS integer
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

 FOR item IN SELECT x.change_id FROM pg_catalog.jsonb_to_recordset(plan_records) WITH ORDINALITY AS x(
   change_id uuid,ord bigint) ORDER BY x.ord
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
ALTER FUNCTION change_ledger.revoke_stale_v1(text,text) OWNER TO ledger_owner;

-- Keep the emergency-stop direction available; reopening remains fail-closed until recovery is qualified.
CREATE FUNCTION change_ledger.kill_switch_v1(t text,c text,p_mode text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; current_mode text; effective_mode text; lifecycle_found boolean;
        recovery_run_id uuid; recovery_report jsonb; blocked boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT change_ledger.is_operator(who) THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_mode IS NULL OR p_mode NOT IN ('OFF','STOP_ADMIT','STOP_EFFECTS','REVOKE') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 -- Preallocate the sweep-run identity before taking the exclusive switch fence. The deferred
 -- recovery helper later fences this exact global ID before locking recovery rows.
 IF p_mode='OFF' THEN recovery_run_id:=pg_catalog.gen_random_uuid(); END IF;
 -- Preserve the exact legacy namespace-2 key, exclusively, before joining namespace 7.
 PERFORM pg_catalog.pg_advisory_xact_lock(2,pg_catalog.hashtext(t||':'||c));
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences lf
  WHERE lf.tenant_id=t AND lf.company_id=c FOR SHARE;
 lifecycle_found:=FOUND;
  IF NOT lifecycle_found THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
  PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT ks.mode INTO current_mode FROM change_ledger.kill_switch_state ks
  WHERE ks.tenant_id=t AND ks.company_id=c;
 IF p_mode='OFF' AND coalesce(current_mode,'OFF')='OFF' THEN
  -- Preserve the established idempotent OFF contract: no write, timestamp churn or event.
  RETURN 'OFF';
 END IF;
 IF p_mode='OFF' AND coalesce(current_mode,'OFF')<>'OFF' THEN
  -- Recovery effects are committed in this transaction, but their event-chain writes are
  -- deferred until the outer OFF decision has updated (or preserved) kill_switch_state.
  recovery_report:=change_ledger.private_writer_recover_sweep_deferred_v1(
   t,c,'{}'::jsonb,recovery_run_id);
  blocked:=coalesce((recovery_report->>'failed_count')::integer,0)>0
    OR coalesce((recovery_report->>'sweep_failure_count')::bigint,0)>0
    OR coalesce((recovery_report->>'has_more_eligible')::boolean,false)
    OR coalesce((recovery_report->>'has_unresolved')::boolean,false);
  IF blocked THEN
   -- Unlike a direct recover_sweep_v1 call, OFF must be a no-effect refusal until recovery is
   -- complete. Raising here rolls back the deferred sweep run and its queued events as well.
   RAISE EXCEPTION 'RECOVERY_NOT_READY';
  END IF;
  effective_mode:='OFF';
  INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode,updated_by)
   VALUES(t,c,effective_mode,who)
   ON CONFLICT(tenant_id,company_id) DO UPDATE SET mode=EXCLUDED.mode,updated_by=who,
    updated_at=clock_timestamp();
  PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,recovery_report->'events');
  PERFORM change_ledger.append_event(t,c,NULL,'KILL_SWITCH',pg_catalog.jsonb_build_object(
   'mode',effective_mode,'requested_mode','OFF','effective_mode',effective_mode,
   'outcome',CASE WHEN blocked THEN 'BLOCKED' ELSE 'APPLIED' END,'by',who,
   'run_id',recovery_run_id,'failed_count',recovery_report->'failed_count',
   'sweep_failure_count',recovery_report->'sweep_failure_count',
   'has_more_eligible',recovery_report->'has_more_eligible',
   'has_unresolved',recovery_report->'has_unresolved',
   'selected_counts',recovery_report->'selected_counts'));
  RETURN effective_mode;
 END IF;
 INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode,updated_by)
 VALUES(t,c,p_mode,who)
 ON CONFLICT(tenant_id,company_id) DO UPDATE SET mode=EXCLUDED.mode,updated_by=who,
  updated_at=clock_timestamp();
 PERFORM change_ledger.append_event(t,c,NULL,'KILL_SWITCH',
  pg_catalog.jsonb_build_object('mode',p_mode,'by',who));
 RETURN p_mode;
END $fn$;
ALTER FUNCTION change_ledger.kill_switch_v1(text,text,text) OWNER TO ledger_owner;

-- Retry verification freezes evidence, hold, counter and zero-effect lock identities before mutation.
CREATE FUNCTION change_ledger.retry_verify_v1(t text,c text,p_change_id uuid,
 p_field uuid,p_movement uuid,p_version uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
         plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
         plan_tlock change_ledger.target_locks%ROWTYPE; tlock change_ledger.target_locks%ROWTYPE;
        plan_counter change_ledger.sweep_counters%ROWTYPE; counter change_ledger.sweep_counters%ROWTYPE;
         rec_found boolean; target_found boolean; tlock_found boolean; current_tlock_found boolean;
         counter_found boolean; current_counter_found boolean;
         plan_holds jsonb; current_holds jsonb; plan_keys jsonb; current_keys jsonb;
         plan_tlocks jsonb; current_tlocks jsonb;
        hold_ids uuid[]:='{}'::uuid[]; record_ids uuid[]:='{}'::uuid[];
        global_keys text[]:=ARRAY[]::text[];
        key_keys text[]:=ARRAY[]::text[]; evidence_ids uuid[]; item record; lock_hash integer;
        row_count integer; owner_id uuid; verdict jsonb; passed boolean; evidence jsonb;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'worker_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;

 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 rec_found:=FOUND;
 IF NOT rec_found THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,plan_rec.base_fingerprint);
 IF plan_rec.verification_state<>'FAILED_VERIFY' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 target_found:=FOUND;
 SELECT * INTO plan_tlock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=coalesce(plan_rec.target_ref,plan_rec.change_id::text);
 tlock_found:=FOUND;
  -- The pass path deletes every lock owned by this change for the base, not only the
  -- expected target_ref. Freeze that complete delete set plus the exact owner-check row.
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.target_ref),'[]'::jsonb)
   INTO plan_tlocks FROM (SELECT x.* FROM change_ledger.target_locks x
    WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
     AND (x.owner_change_id=p_change_id
       OR x.target_ref=coalesce(plan_rec.target_ref,plan_rec.change_id::text))
    ORDER BY x.target_ref LIMIT 201) x;
 SELECT coalesce(pg_catalog.array_agg(DISTINCT x.change_id ORDER BY x.change_id),'{}'::uuid[])
  INTO record_ids FROM (
   SELECT p_change_id AS change_id
   UNION SELECT x.owner_change_id
    FROM pg_catalog.jsonb_to_recordset(plan_tlocks) AS x(owner_change_id uuid)
  ) x WHERE x.change_id IS NOT NULL;
 SELECT * INTO plan_counter FROM change_ledger.sweep_counters x
  WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_change_id AND x.kind='VERIFY_RETRY';
 counter_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.hold_id),'[]'::jsonb)
  INTO plan_holds FROM (SELECT h.* FROM change_ledger.holds h
   WHERE h.tenant_id=t AND h.company_id=c AND h.change_id=p_change_id
    AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL
   ORDER BY h.base_fingerprint,h.hold_id LIMIT 196) x;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO plan_keys FROM (SELECT k.* FROM change_ledger.key_locks k
    WHERE k.tenant_id=t AND k.company_id=c AND k.base_fingerprint=plan_rec.base_fingerprint
     AND k.owner_change_id=p_change_id
   ORDER BY k.base_fingerprint,k.key_hash LIMIT 201) x;
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
    AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
      OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint)) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 SELECT coalesce(pg_catalog.array_agg(x.hold_id ORDER BY x.hold_id),'{}'::uuid[])
  INTO hold_ids FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid);
 evidence_ids:=pg_catalog.array_remove(ARRAY[p_field,p_movement,p_version]::uuid[],NULL::uuid);
 -- Count the counter row even when absent: this call creates it after plan validation.
  row_count:=pg_catalog.cardinality(record_ids)+1+CASE WHEN target_found THEN 1 ELSE 0 END
   +pg_catalog.jsonb_array_length(plan_tlocks)
  +pg_catalog.jsonb_array_length(plan_holds)
  +pg_catalog.jsonb_array_length(plan_keys);
  IF pg_catalog.jsonb_array_length(plan_tlocks)>200
     OR pg_catalog.jsonb_array_length(plan_holds)>195 OR pg_catalog.jsonb_array_length(plan_keys)>200
     OR row_count>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;

 FOREACH owner_id IN ARRAY record_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(owner_id::text));
 END LOOP;
 global_keys:=pg_catalog.array_append(global_keys,'sweep-counter:v1:'||pg_catalog.lower(p_change_id::text)||':VERIFY_RETRY');
 FOREACH owner_id IN ARRAY evidence_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'evidence-record-id:v1:'||pg_catalog.lower(owner_id::text));
 END LOOP;
 FOREACH owner_id IN ARRAY hold_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(owner_id::text));
 END LOOP;
 IF pg_catalog.cardinality(global_keys)>201 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);
  PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
   t,c,record_ids,plan_rec.base_fingerprint,
   coalesce(plan_rec.target_ref,plan_rec.change_id::text),NULL,false);
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
      AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
        OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint))
    OR (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
         ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
        FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
         AND x.base_fingerprint=plan_rec.base_fingerprint AND x.owner_change_id=p_change_id)
      IS DISTINCT FROM plan_keys THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(3,
  pg_catalog.hashtext(t||':'||c||':FAILED_VERIFY_HALT'));
  key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||
   plan_rec.base_fingerprint||':'||coalesce(plan_rec.target_ref,plan_rec.change_id::text));
  FOR item IN SELECT x.target_ref FROM pg_catalog.jsonb_to_recordset(plan_tlocks) AS x(
   tenant_id text,company_id text,base_fingerprint text,target_ref text,owner_change_id uuid,acquired_at timestamptz)
   ORDER BY x.target_ref
  LOOP
   key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||
    plan_rec.base_fingerprint||':'||item.target_ref);
  END LOOP;
 FOR item IN SELECT x.key_hash,x.base_fingerprint
  FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(key_hash text,base_fingerprint text)
  ORDER BY x.base_fingerprint,x.key_hash
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||item.base_fingerprint||':'||item.key_hash);
 END LOOP;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS u(k) ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;

 SELECT * INTO target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
 IF target_found IS DISTINCT FROM FOUND OR (target_found AND plan_target IS DISTINCT FROM target) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 FOR owner_id IN SELECT x.change_id FROM pg_catalog.unnest(record_ids) AS x(change_id)
   ORDER BY x.change_id
 LOOP
  PERFORM 1 FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 IF NOT FOUND OR plan_rec IS DISTINCT FROM rec THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM 1 FROM change_ledger.holds x WHERE x.tenant_id=t AND x.company_id=c
  AND x.change_id=p_change_id AND x.cause='FAILED_VERIFY_HALT' AND x.released_at IS NULL
  ORDER BY x.hold_id LIMIT 196 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.hold_id),'[]'::jsonb)
  INTO current_holds FROM (SELECT x.* FROM change_ledger.holds x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id
    AND x.cause='FAILED_VERIFY_HALT' AND x.released_at IS NULL
   ORDER BY x.base_fingerprint,x.hold_id LIMIT 196) x;
 IF pg_catalog.jsonb_array_length(current_holds)>195 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=plan_rec.base_fingerprint AND x.owner_change_id=p_change_id
   ORDER BY x.base_fingerprint,x.key_hash LIMIT 201 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO current_keys FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
    AND x.base_fingerprint=plan_rec.base_fingerprint AND x.owner_change_id=p_change_id
    ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(current_keys)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT * INTO counter FROM change_ledger.sweep_counters x
  WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_change_id AND x.kind='VERIFY_RETRY' FOR UPDATE;
 current_counter_found:=FOUND;
 PERFORM 1 FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.base_fingerprint=plan_rec.base_fingerprint
  AND (x.owner_change_id=p_change_id OR x.target_ref=coalesce(plan_rec.target_ref,plan_rec.change_id::text))
  ORDER BY x.target_ref LIMIT 201 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.target_ref),'[]'::jsonb)
  INTO current_tlocks FROM (SELECT x.* FROM change_ledger.target_locks x
   WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
    AND (x.owner_change_id=p_change_id
      OR x.target_ref=coalesce(plan_rec.target_ref,plan_rec.change_id::text))
   ORDER BY x.target_ref LIMIT 201) x;
 SELECT * INTO tlock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=coalesce(plan_rec.target_ref,plan_rec.change_id::text);
 current_tlock_found:=FOUND;
 IF tlock_found IS DISTINCT FROM current_tlock_found
    OR (tlock_found AND plan_tlock IS DISTINCT FROM tlock) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF counter_found IS DISTINCT FROM current_counter_found OR (counter_found AND plan_counter IS DISTINCT FROM counter)
     OR plan_holds IS DISTINCT FROM current_holds OR plan_keys IS DISTINCT FROM current_keys
     OR plan_tlocks IS DISTINCT FROM current_tlocks THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.verification_state<>'FAILED_VERIFY' OR pg_catalog.jsonb_array_length(current_holds)=0 THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 verdict:=change_ledger.derive_verdict(t,c,rec,p_field,p_movement,p_version);
 passed:=(verdict->>'passed')::boolean;
 evidence:=verdict->'refs';
 owner_id:=tlock.owner_change_id;
 IF owner_id IS NOT NULL AND owner_id<>p_change_id THEN RAISE EXCEPTION 'LOCK_BUSY'; END IF;
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
  VALUES(t,c,p_change_id,'VERIFY_RETRY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO counter FROM change_ledger.sweep_counters x
  WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_change_id AND x.kind='VERIFY_RETRY' FOR UPDATE;
 IF counter.attempts>=3 THEN RAISE EXCEPTION 'VERIFY_FAILED'; END IF;
 UPDATE change_ledger.sweep_counters SET attempts=attempts+1,last_attempt_at=clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='VERIFY_RETRY'
  RETURNING * INTO counter;
 IF passed THEN
  UPDATE change_ledger.records SET verification_state='VERIFIED',updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  UPDATE change_ledger.holds SET released_at=clock_timestamp(),
   release_evidence=pg_catalog.jsonb_build_object('retry_verify',counter.attempts,'evidence',evidence)
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
    AND cause='FAILED_VERIFY_HALT' AND released_at IS NULL;
  DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
   AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
  UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(),close_reason='VERIFIED'
   WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='VERIFY_RETRY';
  PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_PASSED',
   pg_catalog.jsonb_build_object('attempt',counter.attempts)||pg_catalog.jsonb_build_object('evidence',evidence));
  RETURN 'VERIFIED';
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_FAILED',
  pg_catalog.jsonb_build_object('attempt',counter.attempts)||pg_catalog.jsonb_build_object('evidence',evidence));
 RETURN 'FAILED_VERIFY';
END $fn$;
ALTER FUNCTION change_ledger.retry_verify_v1(text,text,uuid,uuid,uuid,uuid) OWNER TO ledger_owner;

-- Keep due work separate from in-flight uncertainty: callers report the latter via has_unresolved.
-- Stale epoch dependencies remain reportable here, while revoke_stale_v1 owns their mutation;
-- a recovery sweep must still be able to return a zero-work run report for that separate queue.
CREATE FUNCTION change_ledger.private_writer_recovery_has_eligible_v1(
 t text,c text,p jsonb,p_mode text,p_now timestamptz) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT EXISTS(SELECT 1 FROM change_ledger.claim_tokens ct JOIN change_ledger.records r ON r.change_id=ct.change_id
    WHERE r.tenant_id=t AND r.company_id=c AND ct.state='ISSUED'
     AND ct.generation=r.claim_generation AND r.authorization_state='CLAIMED'
     AND r.execution_state='NOT_STARTED'
     AND (p_mode<>'OFF' OR ct.issued_at<=p_now-make_interval(secs=>(p->>'claim_ttl_seconds')::double precision))
   UNION ALL SELECT 1 FROM change_ledger.records r
    WHERE r.tenant_id=t AND r.company_id=c AND r.authorization_state IN ('APPROVED','CLAIMED')
     AND r.execution_state='NOT_STARTED' AND r.dispatch_state NOT IN ('PERMITTED','DISPATCHED')
     AND NOT change_ledger.epoch_deps_current(t,c,r.epoch_dependencies)
   UNION ALL SELECT 1 FROM change_ledger.dispatch_permits dp JOIN change_ledger.records r
    ON r.change_id=dp.change_id AND r.claim_generation=dp.generation
    WHERE r.tenant_id=t AND r.company_id=c AND dp.state='PERMITTED'
     AND (dp.expires_at<=p_now OR p_mode<>'OFF')
    UNION ALL SELECT 1 FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
     ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
     WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='NOT_PERMITTED'
      AND coalesce((SELECT max(e.recorded_at) FROM change_ledger.events e
       WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=r.change_id AND e.event_type='APPLYING'),
       'infinity'::timestamptz)+make_interval(secs=>(p->>'permit_ttl_seconds')::double precision)<=p_now
   UNION ALL SELECT 1 FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
    ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
    WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='DISPATCHED'
     AND coalesce((SELECT cd.hard_deadline_at FROM change_ledger.call_deadlines cd
       WHERE cd.change_id=r.change_id AND cd.generation=r.claim_generation),
      coalesce((SELECT max(e.recorded_at) FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
        AND e.change_id=r.change_id AND e.event_type='DISPATCHED'),r.updated_at)
       +make_interval(secs=>CASE WHEN r.kind='POST' THEN (p->>'post_deadline_seconds')::double precision
                                 ELSE (p->>'deadline_seconds')::double precision END))<=p_now
   UNION ALL SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND r.expires_at<=p_now AND r.execution_state='NOT_STARTED'
    AND r.lifecycle IN ('PROPOSED','VALIDATED') AND r.authorization_state IN ('NONE','APPROVED','EXPIRED')
   UNION ALL SELECT 1 FROM change_ledger.records r WHERE p_mode='REVOKE' AND r.tenant_id=t AND r.company_id=c
    AND r.authorization_state='APPROVED' AND r.execution_state='NOT_STARTED'
   UNION ALL SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.sweep_counters k
    ON k.subject_id=r.change_id AND k.kind='RESOLVE'
    WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLY_UNKNOWN'
     AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND (k.next_attempt_at<=p_now
       OR k.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=p_now)))
   UNION ALL SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND r.execution_state='APPLY_UNKNOWN' AND EXISTS(SELECT 1 FROM change_ledger.holds h
     WHERE h.tenant_id=t AND h.company_id=c AND h.base_fingerprint=r.base_fingerprint
      AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
      AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=p_now)
    UNION ALL SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
     AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=p_now
     AND (EXISTS(SELECT 1 FROM change_ledger.sweep_failures f WHERE f.tenant_id=t AND f.company_id=c
       AND f.subject_id=h.hold_id AND f.stage='GAP_BOUND')
      OR NOT EXISTS(SELECT 1 FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
       AND sc.subject_id=h.hold_id AND sc.kind='ANCHOR_GAP' AND sc.closed_at IS NOT NULL
       AND sc.close_reason='BOUND_EXCEEDED')
      OR NOT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
       AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=h.hold_id::text))
   UNION ALL SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.sweep_counters k
    ON k.subject_id=r.change_id AND k.kind='VERIFY'
    WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLIED'
     AND r.verification_state='NOT_VERIFIED'
     AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND k.next_attempt_at<=p_now))
   UNION ALL SELECT 1 FROM change_ledger.approval_nonces n JOIN change_ledger.records r ON r.change_id=n.change_id
    WHERE r.tenant_id=t AND r.company_id=c AND n.state='ISSUED' AND n.expires_at<=p_now)
$fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_has_eligible_v1(text,text,jsonb,text,timestamptz)
 OWNER TO ledger_owner;

-- Announce one expired anchor-gap bound without releasing its fail-closed hold.
CREATE FUNCTION change_ledger.private_writer_recovery_gap_bound_v1(
 t text,c text,p_hold_id uuid,p jsonb,p_mode text,p_now timestamptz,p_run_id uuid,p_effect_reserve integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_hold change_ledger.holds%ROWTYPE; hold_row change_ledger.holds%ROWTYPE;
        plan_counter change_ledger.sweep_counters%ROWTYPE; counter change_ledger.sweep_counters%ROWTYPE;
        plan_counter_found boolean; counter_found boolean;
        plan_failure jsonb; current_failure jsonb; plan_event_exists boolean; current_event_exists boolean;
        global_keys text[]; lock_rows integer; changed integer:=0; failure_count bigint;
        has_more boolean; has_unresolved boolean; announce boolean; queued_events jsonb:='[]'::jsonb;
        a_fail jsonb:='[]'::jsonb; err_state text; err_msg text; item record;
BEGIN
 IF p_effect_reserve IS NULL OR p_effect_reserve<0 OR p_effect_reserve>2 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO plan_hold FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
  AND h.hold_id=p_hold_id;
 IF NOT FOUND OR plan_hold.cause<>'ANCHOR_GAP' OR plan_hold.released_at IS NOT NULL
   OR plan_hold.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)>p_now THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO plan_counter FROM change_ledger.sweep_counters sc
  WHERE sc.tenant_id=t AND sc.company_id=c AND sc.subject_id=p_hold_id AND sc.kind='ANCHOR_GAP';
 plan_counter_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO plan_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_hold_id AND x.stage='GAP_BOUND') sf;
 SELECT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=p_hold_id::text)
  INTO plan_event_exists;
 IF plan_counter_found AND plan_counter.closed_at IS NOT NULL AND plan_counter.close_reason='BOUND_EXCEEDED'
    AND plan_event_exists AND pg_catalog.jsonb_array_length(plan_failure)=0 THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 -- Bound the hold, present-or-new counter, present-or-new failure, run row and one event row.
 lock_rows:=5;
 IF lock_rows+p_effect_reserve>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 global_keys:=ARRAY['sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text),
  'hold-id:v1:'||pg_catalog.lower(p_hold_id::text),
  'sweep-counter:v1:'||pg_catalog.lower(p_hold_id::text)||':ANCHOR_GAP',
  'sweep-failure:v1:'||pg_catalog.lower(p_hold_id::text)||':GAP_BOUND'];
  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs sr WHERE sr.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO hold_row FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
  AND h.hold_id=p_hold_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO counter FROM change_ledger.sweep_counters sc
  WHERE sc.tenant_id=t AND sc.company_id=c AND sc.subject_id=p_hold_id AND sc.kind='ANCHOR_GAP' FOR UPDATE;
 counter_found:=FOUND;
 PERFORM 1 FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
  AND sf.subject_id=p_hold_id AND sf.stage='GAP_BOUND' FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO current_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_hold_id AND x.stage='GAP_BOUND') sf;
 SELECT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
   AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=p_hold_id::text)
  INTO current_event_exists;
 IF plan_hold IS DISTINCT FROM hold_row OR plan_counter_found IS DISTINCT FROM counter_found
   OR (plan_counter_found AND plan_counter IS DISTINCT FROM counter)
   OR plan_failure IS DISTINCT FROM current_failure OR plan_event_exists IS DISTINCT FROM current_event_exists
   OR hold_row.cause<>'ANCHOR_GAP' OR hold_row.released_at IS NOT NULL
   OR hold_row.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)>p_now THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 BEGIN
  INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,closed_at,close_reason)
   VALUES(t,c,p_hold_id,'ANCHOR_GAP',hold_row.opened_at,pg_catalog.clock_timestamp(),'BOUND_EXCEEDED')
   ON CONFLICT(subject_id,kind) DO NOTHING;
  GET DIAGNOSTICS lock_rows=ROW_COUNT;
  IF lock_rows=1 THEN changed:=changed+1; END IF;
  SELECT * INTO counter FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
   AND sc.subject_id=p_hold_id AND sc.kind='ANCHOR_GAP' FOR UPDATE;
  IF NOT FOUND OR counter.closed_at IS NULL OR counter.close_reason IS DISTINCT FROM 'BOUND_EXCEEDED' THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  SELECT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
    AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=p_hold_id::text)
   INTO announce;
  IF NOT announce THEN
   queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
    'change_id',NULL,'event_type','ANCHOR_GAP_BOUND_EXCEEDED','payload',pg_catalog.jsonb_build_object(
     'hold_id',p_hold_id,'base_fingerprint',hold_row.base_fingerprint,'alert',true)));
  END IF;
  IF counter.closed_at IS NOT NULL AND counter.close_reason='BOUND_EXCEEDED' THEN
   DELETE FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
    AND sf.subject_id=p_hold_id AND sf.stage='GAP_BOUND';
  END IF;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
   changed:=0;
  INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
   VALUES(t,c,p_hold_id,'GAP_BOUND',err_state,pg_catalog.left(coalesce(err_msg,''),300))
   ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
    last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
  a_fail:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','GAP_BOUND','subject',p_hold_id));
  queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('change_id',NULL,
   'event_type','SWEEP_ITEM_FAILED','payload',pg_catalog.jsonb_build_object('stage','GAP_BOUND',
    'subject',p_hold_id,'sqlstate',err_state,'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
 END;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c;
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
      OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
  INTO has_unresolved;
 IF pg_catalog.jsonb_array_length(queued_events)>1 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
  VALUES(t,c,p_run_id,p_now,pg_catalog.clock_timestamp(),changed);
 -- Direct sweep reports eligibility after its queued announcement is durable in this transaction.
 -- Deferred kill-switch callers retain the queue until the outer state/event decision is complete.
 IF p_effect_reserve=0 AND pg_catalog.jsonb_array_length(queued_events)>0 THEN
  PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,queued_events);
  queued_events:='[]'::jsonb;
 END IF;
 has_more:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,p_mode,p_now);
RETURN pg_catalog.jsonb_build_object('changed',changed,'T5x','[]'::jsonb,'T6c','[]'::jsonb,'T6r','[]'::jsonb,
  'T9','[]'::jsonb,'T3','[]'::jsonb,'VOIDED','[]'::jsonb,'T12_ATTEMPT','[]'::jsonb,'T12','[]'::jsonb,
  'ANCHOR_GAP_TRIAGE','[]'::jsonb,'VERIFY_DUE','[]'::jsonb,'VERIFY_EXHAUSTED','[]'::jsonb,'FAILED',a_fail,
  'NONCES_EXPIRED',0,'run_id',p_run_id,'selected_counts',pg_catalog.jsonb_build_object('T5x',0,'T6c',0,
   'T6r',0,'T9',0,'T3',0,'VOID',0,'T12',0,'GAP',0,'GAP_BOUND',1,'VERIFY',0,'NONCES_EXPIRED',0),
  'has_more_eligible',has_more,'has_unresolved',has_unresolved,'failed_count',pg_catalog.jsonb_array_length(a_fail),
  'sweep_failure_count',failure_count,'events',queued_events);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_gap_bound_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 OWNER TO ledger_owner;

-- Triage one APPLY_UNKNOWN record only while an expired ANCHOR_GAP hold still protects its base.
CREATE FUNCTION change_ledger.private_writer_recovery_gap_v1(
 t text,c text,p_change_id uuid,p jsonb,p_mode text,p_now timestamptz,p_run_id uuid,p_effect_reserve integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_counter change_ledger.sweep_counters%ROWTYPE; counter change_ledger.sweep_counters%ROWTYPE;
        plan_counter_found boolean; counter_found boolean; plan_holds jsonb; current_holds jsonb;
        plan_records jsonb; current_records jsonb; record_ids uuid[]:='{}'::uuid[]; rid uuid;
        plan_failure jsonb; current_failure jsonb; hold_ids uuid[]; v_hold_id uuid; lock_rows integer;
        global_keys text[]; changed integer:=0; failure_count bigint; has_more boolean; has_unresolved boolean;
        a_gap uuid[]:='{}'::uuid[]; a_fail jsonb:='[]'::jsonb; queued_events jsonb:='[]'::jsonb;
        err_state text; err_msg text; item record;
BEGIN
 IF p_effect_reserve IS NULL OR p_effect_reserve<0 OR p_effect_reserve>2 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO plan_rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
  AND r.change_id=p_change_id;
 IF NOT FOUND OR plan_rec.execution_state<>'APPLY_UNKNOWN' THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
  INTO plan_holds FROM (SELECT h.* FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.base_fingerprint=plan_rec.base_fingerprint AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
   AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=p_now
   ORDER BY h.hold_id LIMIT 201) h;
 IF pg_catalog.jsonb_array_length(plan_holds)=0 THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 IF pg_catalog.jsonb_array_length(plan_holds)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT coalesce(pg_catalog.array_agg(DISTINCT p.parent_id ORDER BY p.parent_id),'{}'::uuid[])
  INTO record_ids FROM (
   SELECT p_change_id AS parent_id
   UNION SELECT x.change_id FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(change_id uuid)
  ) p WHERE p.parent_id IS NOT NULL;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
  INTO plan_records FROM change_ledger.records r WHERE r.change_id=ANY(record_ids);
 IF pg_catalog.jsonb_array_length(plan_records)<>pg_catalog.cardinality(record_ids)
   OR EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_records) AS x(tenant_id text,company_id text)
      WHERE x.tenant_id<>t OR x.company_id<>c)
   OR EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_holds) AS h(change_id uuid,base_fingerprint text)
      JOIN pg_catalog.jsonb_to_recordset(plan_records) AS r(change_id uuid,base_fingerprint text)
       ON r.change_id=h.change_id
      WHERE h.change_id IS NOT NULL AND h.base_fingerprint IS DISTINCT FROM r.base_fingerprint) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(pg_catalog.array_agg(x.hold_id ORDER BY x.hold_id),'{}'::uuid[]) INTO hold_ids
  FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid);
 SELECT * INTO plan_counter FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
  AND sc.subject_id=p_change_id AND sc.kind='RESOLVE';
 plan_counter_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO plan_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
   AND x.subject_id=p_change_id AND x.stage='GAP') sf;
 -- Include every hold's record parent, all holds, optional RESOLVE counter, possible failure row, run and event.
 lock_rows:=pg_catalog.cardinality(record_ids)+pg_catalog.jsonb_array_length(plan_holds)+1+1+1+1;
 IF lock_rows+p_effect_reserve>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 global_keys:=ARRAY['sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text),
  'sweep-failure:v1:'||pg_catalog.lower(p_change_id::text)||':GAP'];
 FOREACH rid IN ARRAY record_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
 END LOOP;
 FOREACH v_hold_id IN ARRAY hold_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(v_hold_id::text));
 END LOOP;
 IF plan_counter_found THEN
  global_keys:=pg_catalog.array_append(global_keys,'sweep-counter:v1:'||pg_catalog.lower(p_change_id::text)||':RESOLVE');
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs sr WHERE sr.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 PERFORM 1 FROM change_ledger.records r WHERE r.change_id=ANY(record_ids) ORDER BY r.change_id FOR UPDATE;
 SELECT * INTO rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
  AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 FOR v_hold_id IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid)
  ORDER BY x.hold_id LOOP
  PERFORM 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c AND h.hold_id=v_hold_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO counter FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
  AND sc.subject_id=p_change_id AND sc.kind='RESOLVE' FOR UPDATE;
 counter_found:=FOUND;
 PERFORM 1 FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
  AND sf.subject_id=p_change_id AND sf.stage='GAP' FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
  INTO current_holds FROM (SELECT h.* FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.base_fingerprint=plan_rec.base_fingerprint AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
   AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=p_now
   ORDER BY h.hold_id LIMIT 201) h;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
  INTO current_records FROM change_ledger.records r WHERE r.change_id=ANY(record_ids);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO current_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
   AND x.subject_id=p_change_id AND x.stage='GAP') sf;
 IF plan_rec IS DISTINCT FROM rec OR plan_records IS DISTINCT FROM current_records
   OR plan_holds IS DISTINCT FROM current_holds
   OR plan_counter_found IS DISTINCT FROM counter_found OR (plan_counter_found AND plan_counter IS DISTINCT FROM counter)
   OR plan_failure IS DISTINCT FROM current_failure THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 BEGIN
  IF rec.execution_state='APPLY_UNKNOWN' THEN
   UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED',updated_at=pg_catalog.clock_timestamp()
    WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND execution_state='APPLY_UNKNOWN';
   IF FOUND THEN
    UPDATE change_ledger.sweep_counters SET closed_at=pg_catalog.clock_timestamp(),close_reason='ANCHOR_GAP_WINDOW'
     WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='RESOLVE' AND closed_at IS NULL;
    DELETE FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
     AND sf.subject_id=p_change_id AND sf.stage='GAP';
    changed:=1; a_gap:=ARRAY[p_change_id];
    queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
     'change_id',p_change_id,'event_type','TRIAGE_REQUIRED','payload',pg_catalog.jsonb_build_object(
      'reason','ANCHOR_GAP_WINDOW','alert',true)));
   END IF;
  ELSE
   DELETE FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
    AND sf.subject_id=p_change_id AND sf.stage='GAP';
  END IF;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
  changed:=0; a_gap:='{}'::uuid[];
  INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
   VALUES(t,c,p_change_id,'GAP',err_state,pg_catalog.left(coalesce(err_msg,''),300))
   ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
    last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
  a_fail:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','GAP','subject',p_change_id));
  queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('change_id',p_change_id,
   'event_type','SWEEP_ITEM_FAILED','payload',pg_catalog.jsonb_build_object('stage','GAP','subject',p_change_id,
    'sqlstate',err_state,'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
 END;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c;
 has_more:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,p_mode,p_now);
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN') OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
  INTO has_unresolved;
 IF pg_catalog.jsonb_array_length(queued_events)>1 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
  VALUES(t,c,p_run_id,p_now,pg_catalog.clock_timestamp(),changed);
RETURN pg_catalog.jsonb_build_object('changed',changed,'T5x','[]'::jsonb,'T6c','[]'::jsonb,'T6r','[]'::jsonb,
  'T9','[]'::jsonb,'T3','[]'::jsonb,'VOIDED','[]'::jsonb,'T12_ATTEMPT','[]'::jsonb,'T12','[]'::jsonb,
  'ANCHOR_GAP_TRIAGE',pg_catalog.to_jsonb(a_gap),'VERIFY_DUE','[]'::jsonb,'VERIFY_EXHAUSTED','[]'::jsonb,
  'FAILED',a_fail,'NONCES_EXPIRED',0,'run_id',p_run_id,'selected_counts',pg_catalog.jsonb_build_object('T5x',0,
   'T6c',0,'T6r',0,'T9',0,'T3',0,'VOID',0,'T12',0,'GAP',1,'GAP_BOUND',0,'VERIFY',0,'NONCES_EXPIRED',0),
  'has_more_eligible',has_more,'has_unresolved',has_unresolved,'failed_count',pg_catalog.jsonb_array_length(a_fail),
  'sweep_failure_count',failure_count,'events',queued_events);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_gap_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 OWNER TO ledger_owner;

-- Record one due stuck-verification attempt; exhaustion keeps the applied effect and opens a halt hold.
CREATE FUNCTION change_ledger.private_writer_recovery_verify_v1(
 t text,c text,p_change_id uuid,p jsonb,p_mode text,p_now timestamptz,p_run_id uuid,p_effect_reserve integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_counter change_ledger.sweep_counters%ROWTYPE; counter change_ledger.sweep_counters%ROWTYPE;
        plan_counter_found boolean; counter_found boolean; plan_holds jsonb; current_holds jsonb;
        plan_failure jsonb; current_failure jsonb; plan_started_event timestamptz; current_started_event timestamptz;
        candidate_hold_id uuid:=pg_catalog.gen_random_uuid(); hold_ids uuid[]; v_hold_id uuid;
        global_keys text[]; lock_rows integer; changed integer:=0; failure_count bigint;
        has_more boolean; has_unresolved boolean; exhausted boolean:=false; attempt_durable boolean:=false;
        a_due uuid[]:='{}'::uuid[]; a_exhausted uuid[]:='{}'::uuid[];
        a_fail jsonb:='[]'::jsonb; queued_events jsonb:='[]'::jsonb;
        err_state text; err_msg text; item record;
BEGIN
 IF p_effect_reserve IS NULL OR p_effect_reserve<0 OR p_effect_reserve>2 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO plan_rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
  AND r.change_id=p_change_id;
 IF NOT FOUND OR plan_rec.execution_state<>'APPLIED' OR plan_rec.verification_state<>'NOT_VERIFIED' THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT max(e.recorded_at) INTO plan_started_event FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.event_type IN ('COMPLETE_SUCCESS','RESOLVE_UNKNOWN','OPERATOR_RESOLVE');
 SELECT * INTO plan_counter FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
  AND sc.subject_id=p_change_id AND sc.kind='VERIFY';
 plan_counter_found:=FOUND;
 IF plan_counter_found AND (plan_counter.closed_at IS NOT NULL OR
   plan_counter.next_attempt_at>p_now) THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
  INTO plan_holds FROM (SELECT h.* FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL
   ORDER BY h.hold_id LIMIT 201) h;
 IF pg_catalog.jsonb_array_length(plan_holds)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT coalesce(pg_catalog.array_agg(x.hold_id ORDER BY x.hold_id),'{}'::uuid[]) INTO hold_ids
  FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO plan_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
   AND x.subject_id=p_change_id AND x.stage='VERIFY') sf;
 -- Include record, present-or-new counter, existing-or-new halt hold, possible failure, run and event.
 lock_rows:=1+1+greatest(pg_catalog.jsonb_array_length(plan_holds),1)+1+1+1;
 IF lock_rows+p_effect_reserve>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 global_keys:=ARRAY['sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text),
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'sweep-counter:v1:'||pg_catalog.lower(p_change_id::text)||':VERIFY',
  'sweep-failure:v1:'||pg_catalog.lower(p_change_id::text)||':VERIFY',
  'hold-id:v1:'||pg_catalog.lower(candidate_hold_id::text)];
 FOREACH v_hold_id IN ARRAY hold_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(v_hold_id::text));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs sr WHERE sr.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':FAILED_VERIFY_HALT'));
 SELECT * INTO rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
  AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 FOR v_hold_id IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid)
  ORDER BY x.hold_id LOOP
  PERFORM 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c AND h.hold_id=v_hold_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO counter FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
  AND sc.subject_id=p_change_id AND sc.kind='VERIFY' FOR UPDATE;
 counter_found:=FOUND;
 PERFORM 1 FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
  AND sf.subject_id=p_change_id AND sf.stage='VERIFY' FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
  INTO current_holds FROM (SELECT h.* FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL
   ORDER BY h.hold_id LIMIT 201) h;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO current_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
   AND x.subject_id=p_change_id AND x.stage='VERIFY') sf;
 SELECT max(e.recorded_at) INTO current_started_event FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.event_type IN ('COMPLETE_SUCCESS','RESOLVE_UNKNOWN','OPERATOR_RESOLVE');
 IF plan_rec IS DISTINCT FROM rec OR plan_started_event IS DISTINCT FROM current_started_event
   OR plan_counter_found IS DISTINCT FROM counter_found OR (plan_counter_found AND plan_counter IS DISTINCT FROM counter)
   OR plan_holds IS DISTINCT FROM current_holds OR plan_failure IS DISTINCT FROM current_failure THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 BEGIN
  INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,next_attempt_at)
   VALUES(t,c,p_change_id,'VERIFY',coalesce(current_started_event,rec.updated_at),
    coalesce(current_started_event,rec.updated_at)+make_interval(secs=>(p->>'verify_interval_seconds')::double precision))
   ON CONFLICT(subject_id,kind) DO NOTHING;
  SELECT * INTO counter FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
   AND sc.subject_id=p_change_id AND sc.kind='VERIFY' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
  IF counter.closed_at IS NULL AND counter.next_attempt_at<=p_now THEN
   UPDATE change_ledger.sweep_counters SET attempts=attempts+1,last_attempt_at=p_now,
    next_attempt_at=p_now+make_interval(secs=>(p->>'verify_interval_seconds')::double precision)
    WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='VERIFY' RETURNING * INTO counter;
   IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
   changed:=changed+1; attempt_durable:=true;
   IF counter.attempts>=(p->>'verify_max_attempts')::integer THEN
    UPDATE change_ledger.records SET verification_state='FAILED_VERIFY',effect_known='UNKNOWN',
     updated_at=pg_catalog.clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
      AND execution_state='APPLIED' AND verification_state='NOT_VERIFIED';
    IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
    IF pg_catalog.jsonb_array_length(current_holds)=0 THEN
     INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause,change_id)
      VALUES(candidate_hold_id,t,c,rec.base_fingerprint,'FAILED_VERIFY_HALT',p_change_id);
    END IF;
    UPDATE change_ledger.sweep_counters SET closed_at=pg_catalog.clock_timestamp(),close_reason='EXHAUSTED'
     WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='VERIFY';
    exhausted:=true; a_exhausted:=ARRAY[p_change_id];
    queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
     'change_id',p_change_id,'event_type','VERIFY_RETRY_EXHAUSTED','payload',pg_catalog.jsonb_build_object(
      'reason','SWEEP_STUCK','attempts',counter.attempts,'alert',true)));
   ELSE
    a_due:=ARRAY[p_change_id];
    queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
     'change_id',p_change_id,'event_type','VERIFY_ATTEMPT','payload',pg_catalog.jsonb_build_object(
      'reason','SWEEP_STUCK','attempt',counter.attempts)));
   END IF;
  END IF;
  IF attempt_durable OR rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED' THEN
   DELETE FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
    AND sf.subject_id=p_change_id AND sf.stage='VERIFY';
  END IF;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
  changed:=0; attempt_durable:=false; exhausted:=false;
  INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
   VALUES(t,c,p_change_id,'VERIFY',err_state,pg_catalog.left(coalesce(err_msg,''),300))
   ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
    last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
  a_fail:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','VERIFY','subject',p_change_id));
  a_due:='{}'::uuid[]; a_exhausted:='{}'::uuid[];
  queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('change_id',p_change_id,
   'event_type','SWEEP_ITEM_FAILED','payload',pg_catalog.jsonb_build_object('stage','VERIFY','subject',p_change_id,
    'sqlstate',err_state,'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
 END;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c;
 has_more:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,p_mode,p_now);
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN') OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
  INTO has_unresolved;
 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
  VALUES(t,c,p_run_id,p_now,pg_catalog.clock_timestamp(),changed);
RETURN pg_catalog.jsonb_build_object('changed',changed,'T5x','[]'::jsonb,'T6c','[]'::jsonb,'T6r','[]'::jsonb,
  'T9','[]'::jsonb,'T3','[]'::jsonb,'VOIDED','[]'::jsonb,'T12_ATTEMPT','[]'::jsonb,'T12','[]'::jsonb,
  'ANCHOR_GAP_TRIAGE','[]'::jsonb,'VERIFY_DUE',pg_catalog.to_jsonb(a_due),'VERIFY_EXHAUSTED',pg_catalog.to_jsonb(a_exhausted),
  'FAILED',a_fail,'NONCES_EXPIRED',0,'run_id',p_run_id,'selected_counts',pg_catalog.jsonb_build_object('T5x',0,
   'T6c',0,'T6r',0,'T9',0,'T3',0,'VOID',0,'T12',0,'GAP',0,'GAP_BOUND',0,'VERIFY',1,'NONCES_EXPIRED',0),
  'has_more_eligible',has_more,'has_unresolved',has_unresolved,'failed_count',pg_catalog.jsonb_array_length(a_fail),
  'sweep_failure_count',failure_count,'events',queued_events);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_verify_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 OWNER TO ledger_owner;

-- These private one-item helpers run only after the outer sweep has acquired namespaces 2/7/5 and
-- the lifecycle row; they receive no selected business-row locks and remain ungranted.
-- T6c/T6r apply cancellation effects after recovery has taken the transaction fences.
CREATE FUNCTION change_ledger.private_writer_recovery_permit_v1(
 t text,c text,p_change_id uuid,p_generation bigint,p jsonb,p_mode text,p_now timestamptz,p_run_id uuid,p_stage text,p_effect_reserve integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
        plan_target_lock change_ledger.target_locks%ROWTYPE; target_lock change_ledger.target_locks%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_reservation change_ledger.reservations%ROWTYPE; reservation change_ledger.reservations%ROWTYPE;
        plan_permit change_ledger.dispatch_permits%ROWTYPE; permit change_ledger.dispatch_permits%ROWTYPE;
        plan_tokens jsonb; current_tokens jsonb; plan_keys jsonb; current_keys jsonb;
        plan_records jsonb; current_records jsonb; plan_failure jsonb; current_failure jsonb;
        plan_target_found boolean; target_found boolean; plan_target_lock_found boolean; target_lock_found boolean;
        plan_lease_found boolean; lease_found boolean; plan_reservation_found boolean; reservation_found boolean;
        plan_permit_found boolean; permit_found boolean; rec_found boolean; record_ids uuid[]; rid uuid;
        global_keys text[]:='{}'::text[]; key_keys text[]:='{}'::text[];
        item record; lock_hash integer; tref text; lock_rows integer; effect_rows integer;
        changed integer:=0; failure_count bigint; has_more boolean; has_unresolved boolean;
        plan_applying_at timestamptz; current_applying_at timestamptz; permit_from text;
        a_t6c uuid[]:='{}'::uuid[]; a_t6r uuid[]:='{}'::uuid[];
        a_fail jsonb:='[]'::jsonb; queued_events jsonb:='[]'::jsonb;
        err_state text; err_msg text;
BEGIN
 IF p_effect_reserve IS NULL OR p_effect_reserve<0 OR p_effect_reserve>2 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_stage IS NULL OR p_stage NOT IN ('T6c','T6r') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 permit_from:=CASE WHEN p_stage='T6c' THEN 'PERMITTED' ELSE 'NOT_PERMITTED' END;
 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,plan_rec.base_fingerprint);
 SELECT max(e.recorded_at) INTO plan_applying_at FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.event_type='APPLYING';
 tref:=coalesce(plan_rec.target_ref,p_change_id::text);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO plan_tokens FROM (SELECT ct.* FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id
   ORDER BY ct.token_id LIMIT 197) x;
 SELECT * INTO plan_permit FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation;
 plan_permit_found:=FOUND;
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_target_found:=FOUND;
 SELECT * INTO plan_target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref;
 plan_target_lock_found:=FOUND;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_lease_found:=FOUND;
 SELECT * INTO plan_reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id;
 plan_reservation_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO plan_keys FROM (SELECT kl.* FROM change_ledger.key_locks kl WHERE kl.owner_change_id=p_change_id
   ORDER BY kl.base_fingerprint,kl.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(plan_tokens)>196 OR pg_catalog.jsonb_array_length(plan_keys)>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
    tenant_id text,company_id text,base_fingerprint text)
   WHERE x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
    OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.subject_id,x.stage),'[]'::jsonb)
  INTO plan_failure FROM (SELECT sf.* FROM change_ledger.sweep_failures sf
   WHERE sf.tenant_id=t AND sf.company_id=c AND sf.subject_id=p_change_id AND sf.stage=p_stage) x;
 record_ids:=ARRAY[p_change_id];
 IF plan_rec.repair_for IS NOT NULL THEN record_ids:=pg_catalog.array_append(record_ids,plan_rec.repair_for);
 ELSIF plan_rec.parent_change_id IS NOT NULL THEN
  record_ids:=pg_catalog.array_append(record_ids,plan_rec.parent_change_id);
 END IF;
 IF plan_target_lock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_target_lock.owner_change_id); END IF;
 IF plan_lease_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_lease.owner_change_id); END IF;
 SELECT coalesce(pg_catalog.array_agg(DISTINCT u.x ORDER BY u.x),'{}'::uuid[]) INTO record_ids
  FROM pg_catalog.unnest(record_ids) AS u(x) WHERE u.x IS NOT NULL;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO plan_records FROM (SELECT r.* FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(record_ids)
   ORDER BY r.change_id LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(plan_records)<>pg_catalog.cardinality(record_ids)
   OR NOT plan_permit_found OR plan_permit.state IS DISTINCT FROM permit_from
   OR plan_rec.claim_generation IS DISTINCT FROM p_generation
   OR (p_stage='T6c' AND p_mode='OFF'
    AND (plan_permit.expires_at IS NULL OR plan_permit.expires_at>p_now))
   OR (p_stage='T6r' AND (plan_rec.execution_state<>'APPLYING' OR plan_applying_at IS NULL
    OR plan_applying_at+make_interval(secs=>(p->>'permit_ttl_seconds')::double precision)>p_now)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 lock_rows:=pg_catalog.cardinality(record_ids)+pg_catalog.jsonb_array_length(plan_tokens)
  +pg_catalog.jsonb_array_length(plan_keys)
  +CASE WHEN plan_target_found THEN 1 ELSE 0 END
  +CASE WHEN plan_permit_found THEN 1 ELSE 0 END
  +CASE WHEN plan_reservation_found THEN 1 ELSE 0 END
  +CASE WHEN plan_target_lock_found THEN 1 ELSE 0 END
  +CASE WHEN plan_lease_found THEN 1 ELSE 0 END
  +pg_catalog.jsonb_array_length(plan_failure)+1;
 effect_rows:=pg_catalog.jsonb_array_length(plan_tokens)+pg_catalog.jsonb_array_length(plan_keys)+10;
 IF lock_rows+p_effect_reserve>200 OR effect_rows+p_effect_reserve>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 global_keys:=ARRAY['sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text),
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'sweep-failure:v1:'||pg_catalog.lower(p_change_id::text)||':'||p_stage];
 FOREACH rid IN ARRAY record_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
 END LOOP;
 FOR item IN SELECT x.token_id FROM pg_catalog.jsonb_to_recordset(plan_tokens) AS x(token_id uuid)
 LOOP global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(item.token_id::text)); END LOOP;
 key_keys:=ARRAY['target-lock:v1:'||t||':'||c||':'||plan_rec.base_fingerprint||':'||tref];
 FOR item IN SELECT x.base_fingerprint,x.key_hash
  FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(base_fingerprint text,key_hash text)
  ORDER BY x.base_fingerprint,x.key_hash
  LOOP key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||item.base_fingerprint||':'||item.key_hash); END LOOP;
  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);
  PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
   t,c,record_ids,plan_rec.base_fingerprint,tref,NULL,true);
  IF (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
       ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
      FROM (SELECT k.* FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id
       ORDER BY k.base_fingerprint,k.key_hash LIMIT 201) x)
    IS DISTINCT FROM plan_keys THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs sr WHERE sr.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS z(k) ORDER BY 1
 LOOP PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash); END LOOP;
 SELECT * INTO target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
 target_found:=FOUND;
 FOR rid IN SELECT u.x FROM pg_catalog.unnest(record_ids) AS u(x) ORDER BY u.x LOOP
  PERFORM 1 FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=rid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 rec_found:=FOUND;
 IF NOT rec_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.claim_tokens x WHERE x.change_id=p_change_id
  ORDER BY x.token_id LIMIT 197 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO current_tokens FROM (SELECT ct.* FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id
   ORDER BY ct.token_id LIMIT 197) x;
 IF pg_catalog.jsonb_array_length(current_tokens)>196 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT * INTO permit FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation FOR UPDATE;
 permit_found:=FOUND;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
  ORDER BY x.base_fingerprint,x.key_hash LIMIT 201 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO current_keys FROM (SELECT kl.* FROM change_ledger.key_locks kl WHERE kl.owner_change_id=p_change_id
   ORDER BY kl.base_fingerprint,kl.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(current_keys)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT * INTO reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id FOR UPDATE;
 reservation_found:=FOUND;
 PERFORM 1 FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
  AND x.subject_id=p_change_id AND x.stage=p_stage FOR UPDATE;
 SELECT * INTO target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref FOR UPDATE;
 target_lock_found:=FOUND;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 lease_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.subject_id,x.stage),'[]'::jsonb)
  INTO current_failure FROM (SELECT sf.* FROM change_ledger.sweep_failures sf
   WHERE sf.tenant_id=t AND sf.company_id=c AND sf.subject_id=p_change_id AND sf.stage=p_stage) x;
 SELECT max(e.recorded_at) INTO current_applying_at FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id AND e.event_type='APPLYING';
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO current_records FROM (SELECT r.* FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(record_ids)
   ORDER BY r.change_id LIMIT 201) x;
 IF plan_rec IS DISTINCT FROM rec OR plan_records IS DISTINCT FROM current_records
  OR plan_tokens IS DISTINCT FROM current_tokens OR plan_permit_found IS DISTINCT FROM permit_found
  OR (plan_permit_found AND plan_permit IS DISTINCT FROM permit)
  OR plan_target_found IS DISTINCT FROM target_found OR (plan_target_found AND plan_target IS DISTINCT FROM target)
  OR plan_keys IS DISTINCT FROM current_keys OR plan_reservation_found IS DISTINCT FROM reservation_found
  OR (plan_reservation_found AND plan_reservation IS DISTINCT FROM reservation)
  OR plan_target_lock_found IS DISTINCT FROM target_lock_found
  OR (plan_target_lock_found AND plan_target_lock IS DISTINCT FROM target_lock)
  OR plan_lease_found IS DISTINCT FROM lease_found OR (plan_lease_found AND plan_lease IS DISTINCT FROM lease)
  OR plan_failure IS DISTINCT FROM current_failure THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF permit.state IS DISTINCT FROM permit_from
  OR rec.claim_generation IS DISTINCT FROM p_generation
  OR (p_stage='T6c' AND p_mode='OFF'
   AND (permit.expires_at IS NULL OR permit.expires_at>p_now))
  OR (p_stage='T6r' AND (rec.execution_state<>'APPLYING' OR current_applying_at IS NULL
   OR current_applying_at+make_interval(secs=>(p->>'permit_ttl_seconds')::double precision)>p_now
   OR plan_applying_at IS DISTINCT FROM current_applying_at)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 BEGIN
  PERFORM change_ledger.recheck_scope_locked(t,c);
   IF change_ledger.dispatch_cas(p_change_id,p_generation,permit_from,'CANCELLED_UNDISPATCHED') THEN
   UPDATE change_ledger.claim_tokens SET state='SUPERSEDED'
    WHERE change_id=p_change_id AND generation=p_generation;
   PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
   UPDATE change_ledger.records SET
    authorization_state=CASE WHEN rec.expires_at<=p_now THEN 'EXPIRED' ELSE 'APPROVED' END,
    execution_state='NOT_STARTED',dispatch_state='CANCELLED_UNDISPATCHED',updated_at=pg_catalog.clock_timestamp()
    WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
   IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
    DELETE FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
     AND x.subject_id=p_change_id AND x.stage=p_stage;
    changed:=1;
    IF p_stage='T6c' THEN a_t6c:=ARRAY[p_change_id]; ELSE a_t6r:=ARRAY[p_change_id]; END IF;
   queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
     'change_id',p_change_id,'event_type',CASE WHEN p_stage='T6c' THEN 'PERMIT_CANCELLED' ELSE 'PERMIT_NOT_ISSUED' END,
    'payload',pg_catalog.jsonb_build_object('generation',p_generation)));
  END IF;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
  changed:=0; a_t6c:='{}'::uuid[]; a_t6r:='{}'::uuid[];
  INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
   VALUES(t,c,p_change_id,p_stage,err_state,pg_catalog.left(coalesce(err_msg,''),300))
   ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
    last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
  a_fail:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage',p_stage,'subject',p_change_id));
  queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
   'change_id',p_change_id,'event_type','SWEEP_ITEM_FAILED',
   'payload',pg_catalog.jsonb_build_object('stage',p_stage,'subject',p_change_id,'sqlstate',err_state,
    'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
 END;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures x
  WHERE x.tenant_id=t AND x.company_id=c;
 has_more:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,p_mode,p_now);
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
      OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
  INTO has_unresolved;
 IF pg_catalog.jsonb_array_length(queued_events)>1 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
  VALUES(t,c,p_run_id,p_now,pg_catalog.clock_timestamp(),changed);
RETURN pg_catalog.jsonb_build_object('changed',changed,'T5x','[]'::jsonb,'T6c',pg_catalog.to_jsonb(a_t6c),
  'T6r',pg_catalog.to_jsonb(a_t6r),'T9','[]'::jsonb,'T3','[]'::jsonb,'VOIDED','[]'::jsonb,'T12_ATTEMPT','[]'::jsonb,
  'T12','[]'::jsonb,'ANCHOR_GAP_TRIAGE','[]'::jsonb,'VERIFY_DUE','[]'::jsonb,'VERIFY_EXHAUSTED','[]'::jsonb,
  'FAILED',a_fail,'NONCES_EXPIRED',0,'run_id',p_run_id,
  'selected_counts',pg_catalog.jsonb_build_object('T5x',0,'T6c',CASE WHEN p_stage='T6c' THEN 1 ELSE 0 END,
   'T6r',CASE WHEN p_stage='T6r' THEN 1 ELSE 0 END,'T9',0,'T3',0,'VOID',0,
   'T12',0,'GAP',0,'GAP_BOUND',0,'VERIFY',0,'NONCES_EXPIRED',0),
  'has_more_eligible',has_more,'has_unresolved',has_unresolved,
  'failed_count',pg_catalog.jsonb_array_length(a_fail),'sweep_failure_count',failure_count,'events',queued_events);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_permit_v1(text,text,uuid,bigint,jsonb,text,timestamptz,uuid,text,integer)
 OWNER TO ledger_owner;

-- Resolve one APPLY_UNKNOWN retry/triage item after all outer recovery fences are held.
CREATE FUNCTION change_ledger.private_writer_recovery_t12_v1(
 t text,c text,p_change_id uuid,p jsonb,p_mode text,p_now timestamptz,p_run_id uuid,p_effect_reserve integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_counter change_ledger.sweep_counters%ROWTYPE; counter change_ledger.sweep_counters%ROWTYPE;
        plan_counter_found boolean; counter_found boolean;
        plan_failure jsonb; current_failure jsonb; plan_started_event timestamptz; current_started_event timestamptz;
        global_keys text[]; rid uuid; lock_rows integer; effect_rows integer; counter_inserted integer:=0;
        due_in double precision; started timestamptz; t12_clear boolean:=false;
        changed integer:=0; failure_count bigint; has_more boolean; has_unresolved boolean; triage_rows integer;
        a_t12 uuid[]:='{}'::uuid[]; a_t12_attempt uuid[]:='{}'::uuid[];
        a_fail jsonb:='[]'::jsonb; queued_events jsonb:='[]'::jsonb;
        err_state text; err_msg text; item record;
BEGIN
 IF p_effect_reserve IS NULL OR p_effect_reserve<0 OR p_effect_reserve>2 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO plan_rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND OR plan_rec.execution_state<>'APPLY_UNKNOWN' THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT max(e.recorded_at) INTO plan_started_event FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.event_type IN ('COMPLETE_UNKNOWN','HARD_DEADLINE_UNKNOWN');
 started:=coalesce(plan_started_event,plan_rec.updated_at);
 SELECT * INTO plan_counter FROM change_ledger.sweep_counters sc
  WHERE sc.tenant_id=t AND sc.company_id=c AND sc.subject_id=p_change_id AND sc.kind='RESOLVE';
 plan_counter_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO plan_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_change_id AND x.stage='T12') sf;
 IF plan_counter_found AND (plan_counter.closed_at IS NOT NULL OR
    NOT (plan_counter.next_attempt_at<=p_now OR plan_counter.started_at+
     make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=p_now)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 lock_rows:=1+CASE WHEN plan_counter_found THEN 1 ELSE 0 END
  +pg_catalog.jsonb_array_length(plan_failure)+1;
 effect_rows:=7;
 IF lock_rows+p_effect_reserve>200 OR effect_rows+p_effect_reserve>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 global_keys:=ARRAY['sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text),
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'sweep-counter:v1:'||pg_catalog.lower(p_change_id::text)||':RESOLVE',
  'sweep-failure:v1:'||pg_catalog.lower(p_change_id::text)||':T12'];
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs sr WHERE sr.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO counter FROM change_ledger.sweep_counters sc
  WHERE sc.tenant_id=t AND sc.company_id=c AND sc.subject_id=p_change_id AND sc.kind='RESOLVE' FOR UPDATE;
 counter_found:=FOUND;
 PERFORM 1 FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
  AND sf.subject_id=p_change_id AND sf.stage='T12' FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(sf) ORDER BY sf.subject_id,sf.stage),'[]'::jsonb)
  INTO current_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=p_change_id AND x.stage='T12') sf;
 SELECT max(e.recorded_at) INTO current_started_event FROM change_ledger.events e
  WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=p_change_id
   AND e.event_type IN ('COMPLETE_UNKNOWN','HARD_DEADLINE_UNKNOWN');
 IF plan_rec IS DISTINCT FROM rec OR plan_started_event IS DISTINCT FROM current_started_event
  OR plan_counter_found IS DISTINCT FROM counter_found
  OR (plan_counter_found AND plan_counter IS DISTINCT FROM counter)
  OR plan_failure IS DISTINCT FROM current_failure THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF rec.execution_state<>'APPLY_UNKNOWN'
   OR (counter_found AND (counter.closed_at IS NOT NULL OR
      NOT (counter.next_attempt_at<=p_now OR counter.started_at+
       make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=p_now))) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 BEGIN
  t12_clear:=false;
  started:=coalesce(current_started_event,rec.updated_at);
  due_in:=(p->>'t12_interval_seconds')::double precision
    +random()*(p->>'t12_jitter_seconds')::double precision;
  INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,next_attempt_at)
   VALUES(t,c,p_change_id,'RESOLVE',started,started+make_interval(secs=>due_in))
   ON CONFLICT(subject_id,kind) DO NOTHING;
  GET DIAGNOSTICS counter_inserted=ROW_COUNT;
  -- The first eligible pass establishes the durable schedule only, even when its
  -- event-derived deadline is already due. The next sweep owns the first attempt.
  changed:=changed+counter_inserted;
  SELECT * INTO counter FROM change_ledger.sweep_counters sc
   WHERE sc.tenant_id=t AND sc.company_id=c AND sc.subject_id=p_change_id AND sc.kind='RESOLVE' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
  IF counter_inserted=0 AND counter.closed_at IS NULL THEN
   IF counter.next_attempt_at<=p_now THEN
    UPDATE change_ledger.sweep_counters SET attempts=attempts+1,last_attempt_at=p_now,
     next_attempt_at=p_now+make_interval(secs=>due_in)
     WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='RESOLVE'
     RETURNING * INTO counter;
    changed:=changed+1;
    IF counter.attempts>=(p->>'t12_max_attempts')::integer THEN
     UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED',updated_at=pg_catalog.clock_timestamp()
      WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND execution_state='APPLY_UNKNOWN';
     GET DIAGNOSTICS triage_rows=ROW_COUNT;
     IF triage_rows=1 THEN
      UPDATE change_ledger.sweep_counters SET closed_at=pg_catalog.clock_timestamp(),close_reason='ATTEMPTS'
       WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='RESOLVE';
      queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
       'change_id',p_change_id,'event_type','TRIAGE_REQUIRED','payload',pg_catalog.jsonb_build_object(
        'reason','ATTEMPTS','alert',true)));
      t12_clear:=true;
     END IF;
     a_t12:=pg_catalog.array_append(a_t12,p_change_id);
    ELSIF counter.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=p_now THEN
     UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED',updated_at=pg_catalog.clock_timestamp()
      WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND execution_state='APPLY_UNKNOWN';
     GET DIAGNOSTICS triage_rows=ROW_COUNT;
     IF triage_rows=1 THEN
      UPDATE change_ledger.sweep_counters SET closed_at=pg_catalog.clock_timestamp(),close_reason='WINDOW'
       WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='RESOLVE';
      queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
       'change_id',p_change_id,'event_type','TRIAGE_REQUIRED','payload',pg_catalog.jsonb_build_object(
        'reason','WINDOW','alert',true)));
      t12_clear:=true;
     END IF;
     a_t12:=pg_catalog.array_append(a_t12,p_change_id);
    ELSE
     queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'change_id',p_change_id,'event_type','RESOLVE_ATTEMPT',
      'payload',pg_catalog.jsonb_build_object('attempt',counter.attempts,'next_attempt_at',counter.next_attempt_at)));
     t12_clear:=true; a_t12_attempt:=pg_catalog.array_append(a_t12_attempt,p_change_id);
    END IF;
   ELSIF counter_inserted=0 AND
      counter.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=p_now THEN
    UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED',updated_at=pg_catalog.clock_timestamp()
     WHERE tenant_id=t AND company_id=c AND change_id=p_change_id AND execution_state='APPLY_UNKNOWN';
    GET DIAGNOSTICS triage_rows=ROW_COUNT;
    IF triage_rows=1 THEN
     UPDATE change_ledger.sweep_counters SET closed_at=pg_catalog.clock_timestamp(),close_reason='WINDOW'
      WHERE tenant_id=t AND company_id=c AND subject_id=p_change_id AND kind='RESOLVE';
     queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'change_id',p_change_id,'event_type','TRIAGE_REQUIRED','payload',pg_catalog.jsonb_build_object(
       'reason','WINDOW','alert',true)));
     t12_clear:=true; changed:=changed+1; a_t12:=pg_catalog.array_append(a_t12,p_change_id);
    END IF;
   END IF;
  END IF;
  -- Any successfully processed eligible T12 item also clears its prior retry failure.
  -- Counter initialization can be successful without being a RESOLVE attempt or triage.
  DELETE FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c
   AND sf.subject_id=p_change_id AND sf.stage='T12';
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
   changed:=0; t12_clear:=false; a_t12:='{}'::uuid[]; a_t12_attempt:='{}'::uuid[];
  INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
    VALUES(t,c,p_change_id,'T12',err_state,pg_catalog.left(coalesce(err_msg,''),300))
   ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
    last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
  a_fail:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','T12','subject',p_change_id));
  queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
   'change_id',p_change_id,'event_type','SWEEP_ITEM_FAILED',
   'payload',pg_catalog.jsonb_build_object('stage','T12','subject',p_change_id,'sqlstate',err_state,
    'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
 END;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures sf WHERE sf.tenant_id=t AND sf.company_id=c;
 has_more:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,p_mode,p_now);
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
      OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
  INTO has_unresolved;
 IF pg_catalog.jsonb_array_length(queued_events)>1 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
  VALUES(t,c,p_run_id,p_now,pg_catalog.clock_timestamp(),changed);
RETURN pg_catalog.jsonb_build_object('changed',changed,'T5x','[]'::jsonb,'T6c','[]'::jsonb,
  'T6r','[]'::jsonb,'T9','[]'::jsonb,'T3','[]'::jsonb,'VOIDED','[]'::jsonb,'T12_ATTEMPT',pg_catalog.to_jsonb(a_t12_attempt),
  'T12',pg_catalog.to_jsonb(a_t12),'ANCHOR_GAP_TRIAGE','[]'::jsonb,'VERIFY_DUE','[]'::jsonb,
  'VERIFY_EXHAUSTED','[]'::jsonb,'FAILED',a_fail,'NONCES_EXPIRED',0,'run_id',p_run_id,
  'selected_counts',pg_catalog.jsonb_build_object('T5x',0,'T6c',0,'T6r',0,'T9',0,'T3',0,'VOID',0,
   'T12',1,'GAP',0,'GAP_BOUND',0,'VERIFY',0,'NONCES_EXPIRED',0),
  'has_more_eligible',has_more,'has_unresolved',has_unresolved,
  'failed_count',pg_catalog.jsonb_array_length(a_fail),'sweep_failure_count',failure_count,'events',queued_events);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_t12_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 OWNER TO ledger_owner;

-- Release one expired/current-mode issued claim while preserving the legacy repair handoff.
CREATE FUNCTION change_ledger.private_writer_recovery_t5x_v1(
 t text,c text,p_token_id uuid,p jsonb,p_mode text,p_now timestamptz,p_run_id uuid,p_effect_reserve integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_tok change_ledger.claim_tokens%ROWTYPE; tok change_ledger.claim_tokens%ROWTYPE;
        plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
        plan_tlock change_ledger.target_locks%ROWTYPE; tlock change_ledger.target_locks%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_reservation change_ledger.reservations%ROWTYPE; reservation change_ledger.reservations%ROWTYPE;
        plan_keys jsonb; current_keys jsonb; plan_records jsonb; current_records jsonb;
        plan_failure jsonb; current_failure jsonb;
        plan_target_found boolean; target_found boolean; plan_target_lock_found boolean; target_lock_found boolean;
        plan_lease_found boolean; lease_found boolean; plan_reservation_found boolean; reservation_found boolean;
        record_found boolean; token_found boolean; record_ids uuid[]; rid uuid;
        global_keys text[]:=ARRAY[]::text[]; key_keys text[]:=ARRAY[]::text[];
        key_row record; lock_hash integer; tref text; row_count integer;
        changed integer:=0; failure_count bigint; has_more boolean; has_unresolved boolean;
        a_t5x uuid[]:='{}'::uuid[]; a_fail jsonb:='[]'::jsonb; queued_events jsonb:='[]'::jsonb;
        err_state text; err_msg text; item record;
BEGIN
 IF p_effect_reserve IS NULL OR p_effect_reserve<0 OR p_effect_reserve>2 THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO plan_tok FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=plan_tok.change_id;
 IF NOT FOUND OR plan_tok.state<>'ISSUED' OR plan_tok.generation<>plan_rec.claim_generation
   OR plan_rec.authorization_state<>'CLAIMED' OR plan_rec.execution_state<>'NOT_STARTED'
   OR (p_mode='OFF' AND plan_tok.issued_at>p_now-
      make_interval(secs=>(p->>'claim_ttl_seconds')::double precision)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,plan_rec.change_id,plan_rec.base_fingerprint);
 tref:=coalesce(plan_rec.target_ref,plan_rec.change_id::text);
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_target_found:=FOUND;
 IF NOT plan_target_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO plan_tlock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref;
 plan_target_lock_found:=FOUND;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_lease_found:=FOUND;
 SELECT * INTO plan_reservation FROM change_ledger.reservations x
  WHERE x.change_id=plan_rec.change_id;
 plan_reservation_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO plan_keys FROM (SELECT x.* FROM change_ledger.key_locks x
   WHERE x.owner_change_id=plan_rec.change_id ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(plan_keys)>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
  IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
     tenant_id text,company_id text,base_fingerprint text)
    WHERE x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
     OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.subject_id,x.stage),'[]'::jsonb)
  INTO plan_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=plan_rec.change_id AND x.stage='T5x') x;
 record_ids:=ARRAY[plan_rec.change_id];
 IF plan_rec.repair_for IS NOT NULL THEN record_ids:=pg_catalog.array_append(record_ids,plan_rec.repair_for);
 ELSIF plan_rec.parent_change_id IS NOT NULL THEN
  record_ids:=pg_catalog.array_append(record_ids,plan_rec.parent_change_id);
 END IF;
 IF plan_target_lock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_tlock.owner_change_id); END IF;
 IF plan_lease_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_lease.owner_change_id); END IF;
 SELECT coalesce(pg_catalog.array_agg(DISTINCT x ORDER BY x),'{}'::uuid[]) INTO record_ids
  FROM pg_catalog.unnest(record_ids) AS u(x) WHERE x IS NOT NULL;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO plan_records FROM (SELECT x.* FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=ANY(record_ids)
   ORDER BY x.change_id LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(plan_records)<>pg_catalog.cardinality(record_ids) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 row_count:=pg_catalog.cardinality(record_ids)+1+pg_catalog.jsonb_array_length(plan_keys)
  +CASE WHEN plan_target_found THEN 1 ELSE 0 END+CASE WHEN plan_target_lock_found THEN 1 ELSE 0 END
  +CASE WHEN plan_lease_found THEN 1 ELSE 0 END+CASE WHEN plan_reservation_found THEN 1 ELSE 0 END
  +2; -- one bounded failure-row slot, one sweep-run row; the event effect is counted below
 IF row_count+1+p_effect_reserve>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 global_keys:=pg_catalog.array_append(global_keys,'sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text));
 global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(p_token_id::text));
 global_keys:=pg_catalog.array_append(global_keys,'sweep-failure:v1:'||pg_catalog.lower(plan_rec.change_id::text)||':T5x');
 FOREACH rid IN ARRAY record_ids LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
 END LOOP;
 key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||
  plan_rec.base_fingerprint||':'||tref);
 FOR key_row IN SELECT x.key_hash FROM change_ledger.key_locks x
   WHERE x.owner_change_id=plan_rec.change_id ORDER BY x.key_hash
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||plan_rec.base_fingerprint||':'||key_row.key_hash);
 END LOOP;
  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,plan_rec.change_id,plan_rec.base_fingerprint);
  PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
   t,c,record_ids,plan_rec.base_fingerprint,tref,NULL,true);
  IF (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
       ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
      FROM (SELECT k.* FROM change_ledger.key_locks k WHERE k.owner_change_id=plan_rec.change_id
       ORDER BY k.base_fingerprint,k.key_hash LIMIT 201) x)
    IS DISTINCT FROM plan_keys
    OR EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
       tenant_id text,company_id text,base_fingerprint text)
      WHERE x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
       OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs x WHERE x.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS x(k) ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;
 SELECT * INTO target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
 target_found:=FOUND;
 IF target_found IS DISTINCT FROM plan_target_found OR (target_found AND target IS DISTINCT FROM plan_target) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 FOREACH rid IN ARRAY record_ids LOOP
  PERFORM 1 FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=rid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.change_id),'[]'::jsonb)
  INTO current_records FROM (SELECT x.* FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=ANY(record_ids)
   ORDER BY x.change_id LIMIT 201) x;
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=plan_rec.change_id;
 record_found:=FOUND;
 IF record_found THEN
  SELECT * INTO tok FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id FOR UPDATE;
  token_found:=FOUND;
 ELSE token_found:=false; END IF;
 IF NOT record_found OR NOT token_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=plan_rec.change_id
  ORDER BY x.base_fingerprint,x.key_hash FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO current_keys FROM (SELECT x.* FROM change_ledger.key_locks x
   WHERE x.owner_change_id=plan_rec.change_id ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 SELECT * INTO reservation FROM change_ledger.reservations x WHERE x.change_id=plan_rec.change_id FOR UPDATE;
 reservation_found:=FOUND;
 PERFORM 1 FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
  AND x.subject_id=plan_rec.change_id AND x.stage='T5x' FOR UPDATE;
 SELECT * INTO tlock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref FOR UPDATE;
 target_lock_found:=FOUND;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 lease_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.subject_id,x.stage),'[]'::jsonb)
  INTO current_failure FROM (SELECT x.* FROM change_ledger.sweep_failures x
   WHERE x.tenant_id=t AND x.company_id=c AND x.subject_id=plan_rec.change_id AND x.stage='T5x') x;
 IF plan_records IS DISTINCT FROM current_records OR plan_tok IS DISTINCT FROM tok OR plan_rec IS DISTINCT FROM rec
   OR plan_keys IS DISTINCT FROM current_keys
   OR target_lock_found IS DISTINCT FROM plan_target_lock_found
   OR (target_lock_found AND plan_tlock IS DISTINCT FROM tlock)
   OR lease_found IS DISTINCT FROM plan_lease_found
   OR (lease_found AND plan_lease IS DISTINCT FROM lease)
   OR reservation_found IS DISTINCT FROM plan_reservation_found
   OR (reservation_found AND plan_reservation IS DISTINCT FROM reservation)
   OR plan_failure IS DISTINCT FROM current_failure THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF tok.state<>'ISSUED' OR tok.generation<>rec.claim_generation
   OR rec.authorization_state<>'CLAIMED' OR rec.execution_state<>'NOT_STARTED'
   OR (p_mode='OFF' AND tok.issued_at>p_now-
      make_interval(secs=>(p->>'claim_ttl_seconds')::double precision)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 BEGIN
  UPDATE change_ledger.claim_tokens SET state='SUPERSEDED' WHERE token_id=p_token_id AND state='ISSUED';
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
  PERFORM change_ledger.release_zero_effect(t,c,rec.change_id);
  UPDATE change_ledger.records SET
   authorization_state=CASE WHEN p_mode='REVOKE' THEN 'VOIDED'
    WHEN rec.expires_at<=p_now THEN 'EXPIRED' ELSE 'APPROVED' END,
   execution_state='NOT_STARTED',updated_at=pg_catalog.clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=rec.change_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
  DELETE FROM change_ledger.sweep_failures x WHERE x.tenant_id=t AND x.company_id=c
   AND x.subject_id=rec.change_id AND x.stage='T5x';
  changed:=1; a_t5x:=ARRAY[rec.change_id];
  queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
   'change_id',rec.change_id,'event_type','CLAIM_RELEASED',
   'payload',pg_catalog.jsonb_build_object('cause',CASE WHEN p_mode='REVOKE' THEN 'REVOKE' ELSE 'SWEEP' END)));
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
   changed:=0; a_t5x:='{}'::uuid[];
  INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
   VALUES(t,c,plan_rec.change_id,'T5x',err_state,pg_catalog.left(coalesce(err_msg,''),300))
   ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
    last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
  a_fail:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','T5x','subject',plan_rec.change_id));
  -- The exception subtransaction rolls back SQL effects, not this PL/pgSQL queue.
  queued_events:=pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
   'change_id',plan_rec.change_id,'event_type','SWEEP_ITEM_FAILED',
   'payload',pg_catalog.jsonb_build_object('stage','T5x','subject',plan_rec.change_id,'sqlstate',err_state,
    'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
 END;
 SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures x
  WHERE x.tenant_id=t AND x.company_id=c;
 has_more:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,p_mode,p_now);
 SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
    AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
      OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
   OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
  INTO has_unresolved;
 IF pg_catalog.jsonb_array_length(queued_events)>1 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
  VALUES(t,c,p_run_id,p_now,pg_catalog.clock_timestamp(),changed);
RETURN pg_catalog.jsonb_build_object('changed',changed,'T5x',pg_catalog.to_jsonb(a_t5x),'T6c','[]'::jsonb,
  'T6r','[]'::jsonb,'T9','[]'::jsonb,'T3','[]'::jsonb,'VOIDED','[]'::jsonb,'T12_ATTEMPT','[]'::jsonb,
  'T12','[]'::jsonb,'ANCHOR_GAP_TRIAGE','[]'::jsonb,'VERIFY_DUE','[]'::jsonb,'VERIFY_EXHAUSTED','[]'::jsonb,
  'FAILED',a_fail,'NONCES_EXPIRED',0,'run_id',p_run_id,
  'selected_counts',pg_catalog.jsonb_build_object('T5x',1,'T6c',0,'T6r',0,'T9',0,'T3',0,'VOID',0,
   'T12',0,'GAP',0,'GAP_BOUND',0,'VERIFY',0,'NONCES_EXPIRED',0),
  'has_more_eligible',has_more,'has_unresolved',has_unresolved,
  'failed_count',pg_catalog.jsonb_array_length(a_fail),'sweep_failure_count',failure_count,'events',queued_events);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recovery_t5x_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 OWNER TO ledger_owner;

-- The bounded versioned recovery candidate routes T5x, T6c/T6r, T12, GAP_BOUND, GAP and VERIFY
-- as isolated one-item stages, then handles bounded T3, REVOKE-only VOID, expired nonces and T9.
-- Stage events are queued with their row effects and appended only after the sweep-run row is written.
CREATE FUNCTION change_ledger.private_writer_append_queued_events_v1(t text,c text,p_events jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE item record;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 -- This internal sink runs after the recovery core has already changed durable rows. Reusing
 -- the top-level entry assertion here would reject the assigned transaction ID and roll back
 -- every recovery call. Keep the transaction mode guard, but do not reassert first participation.
 IF current_setting('transaction_isolation')<>'read committed'
   OR current_setting('transaction_read_only')='on' THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 IF p_events IS NULL OR pg_catalog.jsonb_typeof(p_events)<>'array'
    OR pg_catalog.jsonb_array_length(p_events)>201 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 FOR item IN SELECT x.change_id,x.event_type,x.payload
  FROM pg_catalog.jsonb_array_elements(p_events) WITH ORDINALITY AS q(value,ordinal)
   CROSS JOIN LATERAL pg_catalog.jsonb_to_record(q.value) AS x(
    change_id uuid,event_type text,payload jsonb)
  ORDER BY q.ordinal
 LOOP
  IF item.event_type IS NULL OR item.event_type='' OR item.payload IS NULL
     OR pg_catalog.jsonb_typeof(item.payload)<>'object' THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
  PERFORM change_ledger.append_event(t,c,item.change_id,item.event_type,item.payload);
 END LOOP;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_append_queued_events_v1(text,text,jsonb)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_recover_sweep_core_v1(
 t text,c text,p_params jsonb,p_run_id uuid,p_defer_events boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; p jsonb; v_mode text; v_now timestamptz; has_more_eligible boolean;
        has_unresolved boolean; failure_count bigint; batch_size integer;
        t5x_token_id uuid; t6c_change_id uuid; t6c_generation bigint; t12_change_id uuid;
        t6r_change_id uuid; t6r_generation bigint; gap_bound_hold_id uuid; gap_change_id uuid; verify_change_id uuid;
         c_t3 uuid[]:='{}'::uuid[]; c_void uuid[]:='{}'::uuid[]; c_t9 uuid[]:='{}'::uuid[];
         c_nonce text[]:='{}'::text[]; nonce_record_ids uuid[]:='{}'::uuid[];
         ids uuid[]:='{}'::uuid[]; cid uuid; nonce_key text; n integer:=0;
         queued_count_before integer; changed_count_before integer;
         selected_effects integer; selected_nonces integer:=0; nonce_changed integer:=0;
         selected_t9 integer:=0; remaining_items integer; remaining_effect_rows integer;
         hold_id_pool uuid[]; hold_id_ix integer:=0; planned_hold_id uuid;
         hold_found boolean; hold_row change_ledger.holds%ROWTYPE; deadline_at timestamptz;
        rec change_ledger.records%ROWTYPE; err_state text; err_msg text; item record;
         plan_records jsonb; current_records jsonb; plan_failures jsonb; current_failures jsonb;
         plan_nonces jsonb; current_nonces jsonb; plan_permits jsonb; current_permits jsonb;
         plan_holds jsonb; current_holds jsonb; plan_deadlines jsonb; current_deadlines jsonb;
         t9_hold_plan jsonb:='[]'::jsonb; current_t9_hold_plan jsonb;
         global_keys text[]:=ARRAY[]::text[]; hold_ids uuid[]:='{}'::uuid[]; row_count integer;
         a_t3 uuid[]:='{}'::uuid[]; a_void uuid[]:='{}'::uuid[]; a_t9 uuid[]:='{}'::uuid[];
         a_fail jsonb:='[]'::jsonb; queued_events jsonb:='[]'::jsonb; report jsonb;
BEGIN
 IF p_defer_events IS TRUE THEN
  -- The only caller is the revoked deferred wrapper reached from kill_switch_v1. That parent
  -- already owns namespace 2, namespace 7 and the lifecycle row before entering this core.
  -- Preserve its transaction mode checks without incorrectly requiring first lock participation.
  IF current_setting('transaction_isolation')<>'read committed'
    OR current_setting('transaction_read_only')='on' THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
 ELSE
  PERFORM change_ledger.private_writer_assert_transaction_v1();
 END IF;
 PERFORM change_ledger.assert_scope(t,c);
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'worker_role','USAGE') AND NOT p_defer_events THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 IF p_run_id IS NULL OR p_run_id='00000000-0000-0000-0000-000000000000'::uuid
    OR p_defer_events IS NULL
    OR (p_params IS NOT NULL AND pg_catalog.jsonb_typeof(p_params)<>'object') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF p_params IS NOT NULL AND p_params ?| ARRAY['claim_ttl_seconds','permit_ttl_seconds','t12_window_seconds',
   't12_max_attempts','anchor_gap_window_seconds','verify_max_attempts'] THEN
  RAISE EXCEPTION 'NOT_ENTITLED';
 END IF;
 SELECT pg_catalog.array_agg(pg_catalog.gen_random_uuid() ORDER BY s.i) INTO hold_id_pool
  FROM pg_catalog.generate_series(1,66) s(i);
  PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
  PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
  PERFORM 1 FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
  PERFORM change_ledger.recheck_scope_locked(t,c);
  PERFORM pg_catalog.pg_advisory_xact_lock(5,pg_catalog.hashtext('sweep:'||t||':'||c));
 v_now:=clock_timestamp();
 p:=change_ledger.sweep_params(p_params,change_ledger.sweep_tunables()||change_ledger.sweep_constants());
 p:=p||change_ledger.sweep_effective(t,c);
  SELECT coalesce(max(ks.mode),'OFF') INTO v_mode FROM change_ledger.kill_switch_state ks
   WHERE ks.tenant_id=t AND ks.company_id=c;
   batch_size:=least((p->>'batch_size')::integer,66);
  SELECT ct.token_id INTO t5x_token_id FROM change_ledger.claim_tokens ct
   JOIN change_ledger.records r ON r.change_id=ct.change_id
   WHERE r.tenant_id=t AND r.company_id=c AND ct.state='ISSUED'
    AND ct.generation=r.claim_generation AND r.authorization_state='CLAIMED'
    AND r.execution_state='NOT_STARTED'
    AND (v_mode<>'OFF' OR ct.issued_at<=v_now-
      make_interval(secs=>(p->>'claim_ttl_seconds')::double precision))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
     WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='T5x'),0),
    ct.issued_at,r.change_id,ct.token_id LIMIT 1;
  IF FOUND THEN
   report:=change_ledger.private_writer_recovery_t5x_v1(t,c,t5x_token_id,p,v_mode,v_now,p_run_id,CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
  END IF;
   SELECT dp.change_id,dp.generation INTO t6c_change_id,t6c_generation
    FROM change_ledger.dispatch_permits dp JOIN change_ledger.records r
     ON r.change_id=dp.change_id AND r.claim_generation=dp.generation
    WHERE r.tenant_id=t AND r.company_id=c AND dp.state='PERMITTED'
     AND (dp.expires_at<=v_now OR v_mode<>'OFF')
    ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
      WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=dp.change_id AND f.stage='T6c'),0),
     dp.expires_at,dp.change_id,dp.generation LIMIT 1;
   IF FOUND THEN
     report:=change_ledger.private_writer_recovery_permit_v1(
      t,c,t6c_change_id,t6c_generation,p,v_mode,v_now,p_run_id,'T6c',CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
   END IF;
   SELECT r.change_id,dp.generation INTO t6r_change_id,t6r_generation
    FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
     ON dp.change_id=r.change_id AND dp.generation=r.claim_generation
    WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING' AND dp.state='NOT_PERMITTED'
     AND coalesce((SELECT max(e.recorded_at) FROM change_ledger.events e
       WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=r.change_id AND e.event_type='APPLYING'),
       'infinity'::timestamptz)+make_interval(secs=>(p->>'permit_ttl_seconds')::double precision)<=v_now
    ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
      WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='T6r'),0),
     r.updated_at,r.change_id,dp.generation LIMIT 1;
   IF FOUND THEN
    report:=change_ledger.private_writer_recovery_permit_v1(
     t,c,t6r_change_id,t6r_generation,p,v_mode,v_now,p_run_id,'T6r',CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
   END IF;
  -- Preserve the documented one-item priority before selecting batched T3/VOID/nonce/T9 work.
  SELECT r.change_id INTO t12_change_id FROM change_ledger.records r
   LEFT JOIN change_ledger.sweep_counters k ON k.subject_id=r.change_id AND k.kind='RESOLVE'
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLY_UNKNOWN'
    AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND (k.next_attempt_at<=v_now
      OR k.started_at+make_interval(secs=>(p->>'t12_window_seconds')::double precision)<=v_now)))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
     WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='T12'),0),
    r.updated_at,r.change_id LIMIT 1;
  IF FOUND THEN
   report:=change_ledger.private_writer_recovery_t12_v1(t,c,t12_change_id,p,v_mode,v_now,p_run_id,CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
  END IF;
  SELECT h.hold_id INTO gap_bound_hold_id FROM change_ledger.holds h
   WHERE h.tenant_id=t AND h.company_id=c AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
    AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=v_now
    AND (EXISTS(SELECT 1 FROM change_ledger.sweep_failures f WHERE f.tenant_id=t AND f.company_id=c
      AND f.subject_id=h.hold_id AND f.stage='GAP_BOUND')
     OR NOT EXISTS(SELECT 1 FROM change_ledger.sweep_counters sc WHERE sc.tenant_id=t AND sc.company_id=c
      AND sc.subject_id=h.hold_id AND sc.kind='ANCHOR_GAP' AND sc.closed_at IS NOT NULL
      AND sc.close_reason='BOUND_EXCEEDED')
     OR NOT EXISTS(SELECT 1 FROM change_ledger.events e WHERE e.tenant_id=t AND e.company_id=c
      AND e.event_type='ANCHOR_GAP_BOUND_EXCEEDED' AND e.payload->>'hold_id'=h.hold_id::text))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
     WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=h.hold_id AND f.stage='GAP_BOUND'),0),
    h.opened_at,h.hold_id LIMIT 1;
  IF FOUND THEN
   report:=change_ledger.private_writer_recovery_gap_bound_v1(
    t,c,gap_bound_hold_id,p,v_mode,v_now,p_run_id,CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
  END IF;
  SELECT r.change_id INTO gap_change_id FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLY_UNKNOWN'
    AND EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.base_fingerprint=r.base_fingerprint AND h.cause='ANCHOR_GAP' AND h.released_at IS NULL
     AND h.opened_at+make_interval(secs=>(p->>'anchor_gap_window_seconds')::double precision)<=v_now)
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
     WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='GAP'),0),
    r.updated_at,r.change_id LIMIT 1;
  IF FOUND THEN
   report:=change_ledger.private_writer_recovery_gap_v1(t,c,gap_change_id,p,v_mode,v_now,p_run_id,CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
  END IF;
  SELECT r.change_id INTO verify_change_id FROM change_ledger.records r
   LEFT JOIN change_ledger.sweep_counters k ON k.subject_id=r.change_id AND k.kind='VERIFY'
   WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLIED'
    AND r.verification_state='NOT_VERIFIED'
    AND (k.subject_id IS NULL OR (k.closed_at IS NULL AND k.next_attempt_at<=v_now))
   ORDER BY coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
     WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='VERIFY'),0),
    r.updated_at,r.change_id LIMIT 1;
  IF FOUND THEN
   report:=change_ledger.private_writer_recovery_verify_v1(t,c,verify_change_id,p,v_mode,v_now,p_run_id,CASE WHEN p_defer_events THEN 2 ELSE 0 END);
   IF NOT p_defer_events THEN
    PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,report->'events');
    RETURN report-'events';
   END IF;
   RETURN report;
  END IF;
  -- Select one aggregate bounded batch. Per-stage LIMITs alone can repeatedly select a combined
  -- set above the transaction's item/effect caps, causing a no-progress refusal on every sweep.
  remaining_items:=66;
  remaining_effect_rows:=200-1-CASE WHEN p_defer_events THEN 2 ELSE 0 END;
  SELECT coalesce(pg_catalog.array_agg(s.change_id ORDER BY s.failure_count,s.created_at,s.change_id),'{}'::uuid[]) INTO c_t3 FROM (
   SELECT r.change_id,coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
      WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='T3'),0) AS failure_count,
     r.created_at FROM change_ledger.records r
    WHERE r.tenant_id=t AND r.company_id=c AND r.expires_at<=v_now
     AND r.execution_state='NOT_STARTED' AND r.lifecycle IN ('PROPOSED','VALIDATED')
     AND r.authorization_state IN ('NONE','APPROVED','EXPIRED')
    ORDER BY failure_count,r.created_at,r.change_id LIMIT least(batch_size,remaining_items,remaining_effect_rows/3)) s;
  remaining_items:=remaining_items-pg_catalog.cardinality(c_t3);
  remaining_effect_rows:=remaining_effect_rows-pg_catalog.cardinality(c_t3)*3;
  SELECT coalesce(pg_catalog.array_agg(s.change_id ORDER BY s.failure_count,s.updated_at,s.change_id),'{}'::uuid[]) INTO c_t9 FROM (
   SELECT r.change_id,coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
      WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='T9'),0) AS failure_count,
     r.updated_at FROM change_ledger.records r
    JOIN change_ledger.dispatch_permits dp ON dp.change_id=r.change_id
     AND dp.generation=r.claim_generation AND dp.state='DISPATCHED'
    WHERE r.tenant_id=t AND r.company_id=c AND r.execution_state='APPLYING'
     AND coalesce((SELECT cd.hard_deadline_at FROM change_ledger.call_deadlines cd
       WHERE cd.change_id=r.change_id AND cd.generation=r.claim_generation),
      coalesce((SELECT max(e.recorded_at) FROM change_ledger.events e
        WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=r.change_id AND e.event_type='DISPATCHED'),
       r.updated_at)+make_interval(secs=>CASE WHEN r.kind='POST'
        THEN (p->>'post_deadline_seconds')::double precision
        ELSE (p->>'deadline_seconds')::double precision END))<=v_now
    ORDER BY failure_count,r.updated_at,r.change_id LIMIT least(batch_size,remaining_items,remaining_effect_rows/4)) s;
  remaining_items:=remaining_items-pg_catalog.cardinality(c_t9);
  remaining_effect_rows:=remaining_effect_rows-pg_catalog.cardinality(c_t9)*4;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'change_id',r.change_id,'generation',r.claim_generation,'execution_state',r.execution_state,
    'deadline_at',coalesce(cd.hard_deadline_at,
     coalesce(d.dispatched_at,r.updated_at)+make_interval(secs=>CASE WHEN r.kind='POST'
      THEN (p->>'post_deadline_seconds')::double precision
      ELSE (p->>'deadline_seconds')::double precision END)),
    'deadline_row',pg_catalog.to_jsonb(cd),'last_dispatched_at',d.dispatched_at
   ) ORDER BY r.change_id),'[]'::jsonb) INTO plan_deadlines
   FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
    ON dp.change_id=r.change_id AND dp.generation=r.claim_generation AND dp.state='DISPATCHED'
   LEFT JOIN change_ledger.call_deadlines cd ON cd.change_id=r.change_id AND cd.generation=r.claim_generation
   LEFT JOIN LATERAL (SELECT max(e.recorded_at) AS dispatched_at FROM change_ledger.events e
     WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=r.change_id AND e.event_type='DISPATCHED') d ON true
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(c_t9);
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(dp) ORDER BY dp.change_id,dp.generation),'[]'::jsonb)
   INTO plan_permits FROM change_ledger.dispatch_permits dp
    WHERE dp.change_id=ANY(c_t9) AND dp.state='DISPATCHED';
  -- Duplicate, cross-record same-base, or wrong-base live ownership holds are ambiguous legacy state.
  IF EXISTS(SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.holds h
      ON h.tenant_id=t AND h.company_id=c AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL
       AND (h.change_id=r.change_id OR h.base_fingerprint=r.base_fingerprint)
     WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(c_t9)
     GROUP BY r.change_id,r.base_fingerprint
     HAVING count(h.hold_id)>1 OR coalesce(pg_catalog.bool_or(h.hold_id IS NOT NULL AND
       (h.change_id IS DISTINCT FROM r.change_id OR h.base_fingerprint IS DISTINCT FROM r.base_fingerprint)),false)) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  FOREACH cid IN ARRAY c_t9 LOOP
   SELECT * INTO rec FROM change_ledger.records r
    WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=cid;
   SELECT * INTO hold_row FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.base_fingerprint=rec.base_fingerprint AND h.cause='CALL_OWNERSHIP'
    AND h.change_id=cid AND h.released_at IS NULL;
   hold_found:=FOUND;
   IF hold_found THEN planned_hold_id:=hold_row.hold_id;
   ELSE
    hold_id_ix:=hold_id_ix+1;
    planned_hold_id:=hold_id_pool[hold_id_ix];
   END IF;
   t9_hold_plan:=t9_hold_plan||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
    'change_id',cid,'base_fingerprint',rec.base_fingerprint,'hold_id',planned_hold_id,
    'existing',hold_found,'hold_row',CASE WHEN hold_found THEN pg_catalog.to_jsonb(hold_row) ELSE NULL END));
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(t9_hold_plan) AS x(
      change_id uuid,base_fingerprint text,hold_id uuid,existing boolean,hold_row jsonb)
      GROUP BY x.base_fingerprint HAVING count(*)>1) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
   INTO plan_holds FROM (SELECT DISTINCT h.* FROM change_ledger.holds h
    WHERE h.tenant_id=t AND h.company_id=c AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL
     AND (h.change_id=ANY(c_t9) OR EXISTS(SELECT 1 FROM change_ledger.records r
      WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(c_t9)
       AND r.base_fingerprint=h.base_fingerprint)) ORDER BY h.hold_id LIMIT 201) h;
  SELECT coalesce(pg_catalog.array_agg(x.hold_id ORDER BY x.hold_id),'{}'::uuid[]) INTO hold_ids
   FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid);
  IF v_mode='REVOKE' THEN
   SELECT coalesce(pg_catalog.array_agg(s.change_id ORDER BY s.failure_count,s.created_at,s.change_id),'{}'::uuid[]) INTO c_void FROM (
    SELECT r.change_id,coalesce((SELECT f.failures FROM change_ledger.sweep_failures f
       WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=r.change_id AND f.stage='VOID'),0) AS failure_count,
      r.created_at FROM change_ledger.records r
     WHERE r.tenant_id=t AND r.company_id=c AND r.authorization_state='APPROVED'
      AND r.execution_state='NOT_STARTED'
     ORDER BY failure_count,r.created_at,r.change_id LIMIT least(batch_size,remaining_items,remaining_effect_rows/3)) s;
   remaining_items:=remaining_items-pg_catalog.cardinality(c_void);
   remaining_effect_rows:=remaining_effect_rows-pg_catalog.cardinality(c_void)*3;
  END IF;
 has_more_eligible:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,v_mode,v_now);
   selected_effects:=pg_catalog.cardinality(c_t3)+pg_catalog.cardinality(c_void);
  selected_t9:=pg_catalog.cardinality(c_t9);
  SELECT coalesce(pg_catalog.array_agg(s.nonce ORDER BY s.expires_at,s.nonce),'{}'::text[]) INTO c_nonce FROM (
   SELECT an.nonce,an.expires_at FROM change_ledger.approval_nonces an
    JOIN change_ledger.records r ON r.change_id=an.change_id
    WHERE r.tenant_id=t AND r.company_id=c AND an.state='ISSUED' AND an.expires_at<=v_now
    ORDER BY an.expires_at,an.nonce LIMIT least(batch_size,remaining_items,remaining_effect_rows)) s;
  remaining_items:=remaining_items-pg_catalog.cardinality(c_nonce);
  remaining_effect_rows:=remaining_effect_rows-pg_catalog.cardinality(c_nonce);
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(an) ORDER BY an.nonce),'[]'::jsonb)
   INTO plan_nonces FROM (SELECT an.* FROM change_ledger.approval_nonces an
    WHERE an.nonce=ANY(c_nonce) ORDER BY an.nonce LIMIT 100) an;
  SELECT coalesce(pg_catalog.array_agg(DISTINCT an.change_id ORDER BY an.change_id),'{}'::uuid[])
   INTO nonce_record_ids FROM change_ledger.approval_nonces an WHERE an.nonce=ANY(c_nonce);
  selected_nonces:=pg_catalog.cardinality(c_nonce);
  -- A stale epoch dependency is reported by has_more_eligible but is deliberately handled by
  -- revoke_stale_v1, which has no sweep run ID. Let this recovery call persist a zero-work run
  -- and report has_more=true when no sweep stage is selected; otherwise the caller cannot
  -- observe the separate stale-revocation queue through its documented eligibility result.
  IF selected_effects+selected_nonces+selected_t9>66
     OR selected_effects*3+selected_nonces+selected_t9*4+1+
        (CASE WHEN p_defer_events THEN 2 ELSE 0 END)>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
   SELECT coalesce(pg_catalog.array_agg(DISTINCT x ORDER BY x),'{}'::uuid[]) INTO ids
     FROM pg_catalog.unnest(c_t3||c_void||c_t9||nonce_record_ids) AS u(x);
  global_keys:=pg_catalog.array_append(global_keys,'sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text));
  FOREACH cid IN ARRAY ids LOOP
   global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(cid::text));
  END LOOP;
   FOREACH cid IN ARRAY c_t3 LOOP
    global_keys:=pg_catalog.array_append(global_keys,'sweep-failure:v1:'||pg_catalog.lower(cid::text)||':T3');
   END LOOP;
   FOREACH cid IN ARRAY c_void LOOP
    global_keys:=pg_catalog.array_append(global_keys,'sweep-failure:v1:'||pg_catalog.lower(cid::text)||':VOID');
   END LOOP;
  FOREACH cid IN ARRAY c_t9 LOOP
   global_keys:=pg_catalog.array_append(global_keys,'sweep-failure:v1:'||pg_catalog.lower(cid::text)||':T9');
  END LOOP;
  FOREACH nonce_key IN ARRAY c_nonce LOOP
   global_keys:=pg_catalog.array_append(global_keys,'approval-nonce:v1:'||nonce_key);
  END LOOP;
  FOR item IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(plan_holds) AS x(hold_id uuid)
   ORDER BY x.hold_id
  LOOP
   global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(item.hold_id::text));
  END LOOP;
  FOR item IN SELECT x.hold_id FROM pg_catalog.jsonb_to_recordset(t9_hold_plan) AS x(
    change_id uuid,base_fingerprint text,hold_id uuid,existing boolean,hold_row jsonb)
   WHERE NOT x.existing ORDER BY x.hold_id
  LOOP
   global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(item.hold_id::text));
  END LOOP;
  PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  IF selected_t9>0 THEN
   -- Acquire the legacy hold identity before selected record/resource row locks, matching hold writers.
   PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':CALL_OWNERSHIP'));
   -- Close the pre-fence hold-plan race before taking any selected row lock.
   IF EXISTS(SELECT 1 FROM change_ledger.records r LEFT JOIN change_ledger.holds h
       ON h.tenant_id=t AND h.company_id=c AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL
        AND (h.change_id=r.change_id OR h.base_fingerprint=r.base_fingerprint)
      WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(c_t9)
      GROUP BY r.change_id,r.base_fingerprint
      HAVING count(h.hold_id)>1 OR coalesce(pg_catalog.bool_or(h.hold_id IS NOT NULL AND
        (h.change_id IS DISTINCT FROM r.change_id OR h.base_fingerprint IS DISTINCT FROM r.base_fingerprint)),false)) THEN
    RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
   END IF;
  END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.sweep_runs r WHERE r.run_id=p_run_id) THEN
  RAISE EXCEPTION 'SWEEP_RUN_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
   INTO plan_records FROM (SELECT r.* FROM change_ledger.records r
    WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(ids)
    ORDER BY r.change_id LIMIT 100) r;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(f) ORDER BY f.subject_id,f.stage),'[]'::jsonb)
   INTO plan_failures FROM (SELECT f.* FROM change_ledger.sweep_failures f
    WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=ANY(ids) AND f.stage IN ('T3','VOID','T9')
    ORDER BY f.subject_id,f.stage LIMIT 100) f;
  row_count:=pg_catalog.jsonb_array_length(plan_records)+pg_catalog.jsonb_array_length(plan_failures);
  IF pg_catalog.jsonb_array_length(plan_records)<>pg_catalog.cardinality(ids)
      OR pg_catalog.jsonb_array_length(plan_failures)>66 OR row_count+(CASE WHEN p_defer_events THEN 2 ELSE 0 END)>200
       OR selected_effects*3+selected_nonces+selected_t9*4+1+
          (CASE WHEN p_defer_events THEN 2 ELSE 0 END)>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
  IF pg_catalog.jsonb_array_length(plan_deadlines)<>selected_t9
     OR pg_catalog.jsonb_array_length(plan_permits)<>selected_t9
     OR pg_catalog.jsonb_array_length(t9_hold_plan)<>selected_t9 THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_deadlines) AS x(
    change_id uuid,generation bigint,execution_state text,deadline_at timestamptz,
    deadline_row jsonb,last_dispatched_at timestamptz)
    WHERE x.execution_state<>'APPLYING' OR x.deadline_at>v_now) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  row_count:=row_count+pg_catalog.jsonb_array_length(plan_permits)
   +pg_catalog.jsonb_array_length(plan_holds);
  IF row_count+(CASE WHEN p_defer_events THEN 2 ELSE 0 END)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
  row_count:=row_count+pg_catalog.jsonb_array_length(plan_nonces);
  IF pg_catalog.jsonb_array_length(plan_nonces)<>selected_nonces
     OR row_count+(CASE WHEN p_defer_events THEN 2 ELSE 0 END)>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
  PERFORM 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
   AND r.change_id=ANY(ids) ORDER BY r.change_id FOR UPDATE;
  PERFORM 1 FROM change_ledger.approval_nonces an WHERE an.nonce=ANY(c_nonce)
   ORDER BY an.nonce FOR UPDATE;
  PERFORM 1 FROM change_ledger.dispatch_permits dp WHERE dp.change_id=ANY(c_t9)
   AND (dp.change_id,dp.generation) IN (
    SELECT x.change_id,x.generation FROM pg_catalog.jsonb_to_recordset(plan_permits) AS x(
     change_id uuid,generation bigint))
   ORDER BY dp.change_id,dp.generation FOR UPDATE;
  IF selected_t9>0 THEN
   PERFORM 1 FROM change_ledger.holds h WHERE h.hold_id=ANY(hold_ids)
    ORDER BY h.hold_id FOR UPDATE;
  END IF;
  PERFORM 1 FROM change_ledger.sweep_failures f WHERE f.tenant_id=t AND f.company_id=c
    AND f.subject_id=ANY(ids) AND f.stage IN ('T3','VOID','T9') ORDER BY f.subject_id,f.stage FOR UPDATE;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
   INTO current_records FROM (SELECT r.* FROM change_ledger.records r
    WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(ids)
    ORDER BY r.change_id LIMIT 100) r;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(f) ORDER BY f.subject_id,f.stage),'[]'::jsonb)
   INTO current_failures FROM (SELECT f.* FROM change_ledger.sweep_failures f
      WHERE f.tenant_id=t AND f.company_id=c AND f.subject_id=ANY(ids) AND f.stage IN ('T3','VOID','T9')
    ORDER BY f.subject_id,f.stage LIMIT 100) f;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(an) ORDER BY an.nonce),'[]'::jsonb)
   INTO current_nonces FROM (SELECT an.* FROM change_ledger.approval_nonces an
    WHERE an.nonce=ANY(c_nonce) ORDER BY an.nonce LIMIT 100) an;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(dp) ORDER BY dp.change_id,dp.generation),'[]'::jsonb)
   INTO current_permits FROM change_ledger.dispatch_permits dp
    WHERE (dp.change_id,dp.generation) IN (
     SELECT x.change_id,x.generation FROM pg_catalog.jsonb_to_recordset(plan_permits) AS x(
      change_id uuid,generation bigint));
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
   INTO current_holds FROM (SELECT DISTINCT h.* FROM change_ledger.holds h
    WHERE h.tenant_id=t AND h.company_id=c AND h.cause='CALL_OWNERSHIP' AND h.released_at IS NULL
     AND (h.change_id=ANY(c_t9) OR EXISTS(SELECT 1 FROM change_ledger.records r
      WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(c_t9)
       AND r.base_fingerprint=h.base_fingerprint)) ORDER BY h.hold_id LIMIT 201) h;
  IF pg_catalog.jsonb_array_length(current_holds)>200 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'change_id',p.change_id,'base_fingerprint',p.base_fingerprint,
    'hold_id',coalesce(h.hold_id,p.hold_id),'existing',h.hold_id IS NOT NULL,'hold_row',pg_catalog.to_jsonb(h)
   ) ORDER BY p.change_id),'[]'::jsonb) INTO current_t9_hold_plan
   FROM pg_catalog.jsonb_to_recordset(t9_hold_plan) AS p(
    change_id uuid,base_fingerprint text,hold_id uuid,existing boolean,hold_row jsonb)
   LEFT JOIN change_ledger.holds h ON h.tenant_id=t AND h.company_id=c
    AND h.base_fingerprint=p.base_fingerprint AND h.cause='CALL_OWNERSHIP'
    AND h.change_id=p.change_id AND h.released_at IS NULL;
  SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
     'change_id',r.change_id,'generation',r.claim_generation,'execution_state',r.execution_state,
    'deadline_at',coalesce(cd.hard_deadline_at,
     coalesce(d.dispatched_at,r.updated_at)+make_interval(secs=>CASE WHEN r.kind='POST'
      THEN (p->>'post_deadline_seconds')::double precision
      ELSE (p->>'deadline_seconds')::double precision END)),
    'deadline_row',pg_catalog.to_jsonb(cd),'last_dispatched_at',d.dispatched_at
   ) ORDER BY r.change_id),'[]'::jsonb) INTO current_deadlines
   FROM change_ledger.records r JOIN change_ledger.dispatch_permits dp
    ON dp.change_id=r.change_id AND dp.generation=r.claim_generation AND dp.state='DISPATCHED'
   LEFT JOIN change_ledger.call_deadlines cd ON cd.change_id=r.change_id AND cd.generation=r.claim_generation
   LEFT JOIN LATERAL (SELECT max(e.recorded_at) AS dispatched_at FROM change_ledger.events e
     WHERE e.tenant_id=t AND e.company_id=c AND e.change_id=r.change_id AND e.event_type='DISPATCHED') d ON true
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(c_t9);
   IF plan_records IS DISTINCT FROM current_records OR plan_failures IS DISTINCT FROM current_failures
      OR plan_nonces IS DISTINCT FROM current_nonces OR plan_permits IS DISTINCT FROM current_permits
      OR plan_holds IS DISTINCT FROM current_holds OR t9_hold_plan IS DISTINCT FROM current_t9_hold_plan
      OR plan_deadlines IS DISTINCT FROM current_deadlines THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
  IF selected_nonces>0 THEN
   UPDATE change_ledger.approval_nonces an SET state='EXPIRED'
    WHERE an.nonce=ANY(c_nonce) AND an.state='ISSUED' AND an.expires_at<=v_now;
   GET DIAGNOSTICS nonce_changed=ROW_COUNT;
   IF nonce_changed<>selected_nonces THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
  END IF;
  FOREACH cid IN ARRAY c_t3 LOOP
   queued_count_before:=pg_catalog.jsonb_array_length(queued_events);
   changed_count_before:=n;
   BEGIN
    SELECT * INTO rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
     AND r.change_id=cid FOR UPDATE;
    IF FOUND AND rec.expires_at<=v_now AND rec.execution_state='NOT_STARTED'
       AND rec.lifecycle IN ('PROPOSED','VALIDATED')
       AND rec.authorization_state IN ('NONE','APPROVED','EXPIRED') THEN
     UPDATE change_ledger.records SET lifecycle='EXPIRED_QUEUED',authorization_state='EXPIRED',
      updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=cid;
     DELETE FROM change_ledger.sweep_failures f WHERE f.tenant_id=t AND f.company_id=c
      AND f.subject_id=cid AND f.stage='T3';
      a_t3:=a_t3||cid;
      queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
       'change_id',cid,'event_type','EXPIRED',
       'payload',pg_catalog.jsonb_build_object('lifecycle_from',rec.lifecycle,
        'authorization_from',rec.authorization_state)));
      n:=n+1;
    END IF;
   EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
    queued_events:=coalesce((SELECT pg_catalog.jsonb_agg(q.value ORDER BY q.ordinal)
      FROM pg_catalog.jsonb_array_elements(queued_events) WITH ORDINALITY AS q(value,ordinal)
      WHERE q.ordinal<=queued_count_before),'[]'::jsonb);
    n:=changed_count_before;
     a_t3:=pg_catalog.array_remove(a_t3,cid);
    INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
     VALUES(t,c,cid,'T3',err_state,pg_catalog.left(coalesce(err_msg,''),300))
     ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
      last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
    a_fail:=a_fail||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','T3','subject',cid));
     queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'change_id',cid,'event_type','SWEEP_ITEM_FAILED',
      'payload',pg_catalog.jsonb_build_object('stage','T3','subject',cid,'sqlstate',err_state,
       'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
   END;
  END LOOP;
   FOREACH cid IN ARRAY c_void LOOP
    queued_count_before:=pg_catalog.jsonb_array_length(queued_events);
    changed_count_before:=n;
    BEGIN
     SELECT * INTO rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
      AND r.change_id=cid FOR UPDATE;
     IF FOUND AND v_mode='REVOKE' AND rec.authorization_state='APPROVED'
        AND rec.execution_state='NOT_STARTED' THEN
      UPDATE change_ledger.records SET authorization_state='VOIDED',updated_at=clock_timestamp()
       WHERE tenant_id=t AND company_id=c AND change_id=cid;
      DELETE FROM change_ledger.sweep_failures f WHERE f.tenant_id=t AND f.company_id=c
       AND f.subject_id=cid AND f.stage='VOID';
       a_void:=a_void||cid;
        queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'change_id',cid,'event_type','APPROVAL_VOIDED','payload',pg_catalog.jsonb_build_object('cause','REVOKE')));
       n:=n+1;
     END IF;
    EXCEPTION WHEN OTHERS THEN
     GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
     queued_events:=coalesce((SELECT pg_catalog.jsonb_agg(q.value ORDER BY q.ordinal)
       FROM pg_catalog.jsonb_array_elements(queued_events) WITH ORDINALITY AS q(value,ordinal)
       WHERE q.ordinal<=queued_count_before),'[]'::jsonb);
     n:=changed_count_before;
      a_void:=pg_catalog.array_remove(a_void,cid);
     INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
      VALUES(t,c,cid,'VOID',err_state,pg_catalog.left(coalesce(err_msg,''),300))
      ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
       last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
     a_fail:=a_fail||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','VOID','subject',cid));
      queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
       'change_id',cid,'event_type','SWEEP_ITEM_FAILED',
       'payload',pg_catalog.jsonb_build_object('stage','VOID','subject',cid,'sqlstate',err_state,
        'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
    END;
   END LOOP;
  FOREACH cid IN ARRAY c_t9 LOOP
   queued_count_before:=pg_catalog.jsonb_array_length(queued_events);
   changed_count_before:=n;
   BEGIN
    SELECT * INTO rec FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
     AND r.change_id=cid FOR UPDATE;
    SELECT x.deadline_at INTO deadline_at FROM pg_catalog.jsonb_to_recordset(plan_deadlines) AS x(
     change_id uuid,generation bigint,execution_state text,deadline_at timestamptz,deadline_row jsonb,last_dispatched_at timestamptz)
     WHERE x.change_id=cid;
    SELECT x.hold_id,x.existing INTO planned_hold_id,hold_found
     FROM pg_catalog.jsonb_to_recordset(t9_hold_plan) AS x(
      change_id uuid,base_fingerprint text,hold_id uuid,existing boolean,hold_row jsonb)
     WHERE x.change_id=cid;
    IF FOUND AND rec.execution_state='APPLYING' AND deadline_at<=v_now
       AND EXISTS(SELECT 1 FROM change_ledger.dispatch_permits dp
        WHERE dp.change_id=cid AND dp.generation=rec.claim_generation AND dp.state='DISPATCHED') THEN
     UPDATE change_ledger.records SET execution_state='APPLY_UNKNOWN',
      call_ownership='POSSIBLY_EXECUTING',updated_at=pg_catalog.clock_timestamp()
      WHERE tenant_id=t AND company_id=c AND change_id=cid;
     IF NOT hold_found THEN
      INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause,change_id)
       VALUES(planned_hold_id,t,c,rec.base_fingerprint,'CALL_OWNERSHIP',cid);
     END IF;
     DELETE FROM change_ledger.sweep_failures f WHERE f.tenant_id=t AND f.company_id=c
      AND f.subject_id=cid AND f.stage='T9';
      a_t9:=a_t9||cid;
      queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
       'change_id',cid,'event_type','HARD_DEADLINE_UNKNOWN',
       'payload',pg_catalog.jsonb_build_object('generation',rec.claim_generation,'hard_deadline_at',deadline_at)));
      n:=n+1;
    END IF;
   EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS err_state=RETURNED_SQLSTATE,err_msg=MESSAGE_TEXT;
    queued_events:=coalesce((SELECT pg_catalog.jsonb_agg(q.value ORDER BY q.ordinal)
      FROM pg_catalog.jsonb_array_elements(queued_events) WITH ORDINALITY AS q(value,ordinal)
      WHERE q.ordinal<=queued_count_before),'[]'::jsonb);
    n:=changed_count_before;
     a_t9:=pg_catalog.array_remove(a_t9,cid);
    INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error)
     VALUES(t,c,cid,'T9',err_state,pg_catalog.left(coalesce(err_msg,''),300))
     ON CONFLICT(subject_id,stage) DO UPDATE SET failures=change_ledger.sweep_failures.failures+1,
      last_sqlstate=EXCLUDED.last_sqlstate,last_error=EXCLUDED.last_error,last_at=pg_catalog.clock_timestamp();
    a_fail:=a_fail||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('stage','T9','subject',cid));
    queued_events:=queued_events||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
     'change_id',cid,'event_type','SWEEP_ITEM_FAILED',
     'payload',pg_catalog.jsonb_build_object('stage','T9','subject',cid,'sqlstate',err_state,
      'error',pg_catalog.left(coalesce(err_msg,''),300),'alert',true)));
   END;
  END LOOP;
  IF pg_catalog.jsonb_array_length(queued_events)>selected_effects+selected_t9 THEN
   RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
  END IF;
  has_more_eligible:=change_ledger.private_writer_recovery_has_eligible_v1(t,c,p,v_mode,v_now);
  SELECT EXISTS(SELECT 1 FROM change_ledger.records r WHERE r.tenant_id=t AND r.company_id=c
     AND (r.execution_state IN ('APPLYING','APPLY_UNKNOWN')
       OR (r.execution_state='APPLIED' AND r.verification_state='NOT_VERIFIED')))
    OR EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
     AND h.released_at IS NULL AND h.cause IN ('CALL_OWNERSHIP','FAILED_VERIFY_HALT','ANCHOR_GAP','RLC_UNCLEAN'))
   INTO has_unresolved;
  SELECT count(*) INTO failure_count FROM change_ledger.sweep_failures f
   WHERE f.tenant_id=t AND f.company_id=c;
  INSERT INTO change_ledger.sweep_runs(tenant_id,company_id,run_id,started_at,finished_at,changed)
   VALUES(t,c,p_run_id,v_now,clock_timestamp(),n);
 IF NOT p_defer_events THEN
  PERFORM change_ledger.private_writer_append_queued_events_v1(t,c,queued_events);
 END IF;
 report:=pg_catalog.jsonb_build_object('changed',n,'T5x','[]'::jsonb,'T6c','[]'::jsonb,
    'T6r','[]'::jsonb,'T9',pg_catalog.to_jsonb(a_t9),'T3',pg_catalog.to_jsonb(a_t3),'VOIDED',pg_catalog.to_jsonb(a_void),
  'T12_ATTEMPT','[]'::jsonb,'T12','[]'::jsonb,'ANCHOR_GAP_TRIAGE','[]'::jsonb,
   'VERIFY_DUE','[]'::jsonb,'VERIFY_EXHAUSTED','[]'::jsonb,'FAILED',a_fail,
    'NONCES_EXPIRED',nonce_changed,'run_id',p_run_id,'selected_counts',
     pg_catalog.jsonb_build_object('T5x',0,'T6c',0,'T6r',0,'T9',selected_t9,
     'T3',pg_catalog.cardinality(c_t3),'VOID',pg_catalog.cardinality(c_void),
     'T12',0,'GAP',0,'GAP_BOUND',0,'VERIFY',0,'NONCES_EXPIRED',selected_nonces),
   'has_more_eligible',has_more_eligible,'has_unresolved',has_unresolved,
   'failed_count',pg_catalog.jsonb_array_length(a_fail),
  'sweep_failure_count',failure_count,'events',queued_events);
 RETURN report;
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recover_sweep_core_v1(text,text,jsonb,uuid,boolean)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.recover_sweep_v1(t text,c text,p_params jsonb,p_run_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE report jsonb;
BEGIN
 report:=change_ledger.private_writer_recover_sweep_core_v1(t,c,p_params,p_run_id,false);
 RETURN report-'events';
END $fn$;
ALTER FUNCTION change_ledger.recover_sweep_v1(text,text,jsonb,uuid) OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.private_writer_recover_sweep_deferred_v1(
 t text,c text,p_params jsonb,p_run_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.private_writer_recover_sweep_core_v1(t,c,p_params,p_run_id,true);
END $fn$;
ALTER FUNCTION change_ledger.private_writer_recover_sweep_deferred_v1(text,text,jsonb,uuid)
 OWNER TO ledger_owner;

-- Hold release freezes optional cosign identity before global-fence and parent-first row work.
CREATE FUNCTION change_ledger.release_hold_v1(t text,c text,p_hold_id uuid,p_release_evidence jsonb)
RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_h change_ledger.holds%ROWTYPE; h change_ledger.holds%ROWTYPE;
        plan_cs change_ledger.hold_cosigns%ROWTYPE; cs change_ledger.hold_cosigns%ROWTYPE;
        plan_cs_found boolean:=false; cs_found boolean:=false;
        parent change_ledger.records%ROWTYPE; parent_found boolean;
        resolution change_ledger.events%ROWTYPE; resolution_hold boolean:=false;
        cos_text text; cos_id uuid; cp bigint; ts timestamptz; two boolean:=false; who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;

 SELECT * INTO plan_h FROM change_ledger.holds x
  WHERE x.hold_id=p_hold_id AND x.tenant_id=t AND x.company_id=c;
 IF NOT FOUND THEN RAISE EXCEPTION 'BASE_HOLD'; END IF;
 IF plan_h.released_at IS NULL AND plan_h.cause='ANCHOR_GAP' AND plan_h.ext_seq IS NOT NULL
    AND p_release_evidence IS NOT NULL AND pg_catalog.jsonb_typeof(p_release_evidence)='object'
    AND p_release_evidence ? 'two_person_cosign' THEN
  cos_text:=p_release_evidence->>'two_person_cosign';
  IF cos_text IS NULL OR cos_text !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
   RAISE EXCEPTION 'SCHEMA_INVALID';
  END IF;
  cos_id:=cos_text::uuid;
  SELECT * INTO plan_cs FROM change_ledger.hold_cosigns x
   WHERE x.cosign_id=cos_id AND x.hold_id=p_hold_id;
  plan_cs_found:=FOUND;
 END IF;

 PERFORM change_ledger.private_writer_take_global_fences_v1(pg_catalog.array_remove(ARRAY[
  'hold-id:v1:'||pg_catalog.lower(p_hold_id::text),
  CASE WHEN cos_id IS NULL THEN NULL ELSE 'hold-cosign-id:v1:'||pg_catalog.lower(cos_id::text) END
 ],NULL));
 PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':'||plan_h.cause));
 IF plan_h.change_id IS NOT NULL THEN
  SELECT * INTO parent FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=plan_h.change_id FOR UPDATE;
  parent_found:=FOUND;
  IF NOT parent_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END IF;
 SELECT * INTO h FROM change_ledger.holds x
  WHERE x.hold_id=p_hold_id AND x.tenant_id=t AND x.company_id=c FOR UPDATE;
 IF NOT FOUND OR plan_h IS DISTINCT FROM h THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF cos_id IS NOT NULL THEN
  SELECT * INTO cs FROM change_ledger.hold_cosigns x
   WHERE x.cosign_id=cos_id AND x.hold_id=p_hold_id FOR UPDATE;
  cs_found:=FOUND;
 END IF;
 IF plan_cs_found IS DISTINCT FROM cs_found OR (plan_cs_found AND plan_cs IS DISTINCT FROM cs) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);

 IF h.released_at IS NOT NULL THEN RETURN h.released_at; END IF;
 IF h.cause='FAILED_VERIFY_HALT' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF p_release_evidence IS NULL OR pg_catalog.jsonb_typeof(p_release_evidence)<>'object' THEN
  RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
 END IF;
  SELECT * INTO resolution FROM change_ledger.events e
   WHERE e.tenant_id=t AND e.company_id=c AND e.event_type='OPERATOR_RESOLVE'
    AND (e.payload->>'hold_id'=p_hold_id::text
      OR e.payload->'checkpoint_hold_ids' @> pg_catalog.jsonb_build_array(p_hold_id))
   ORDER BY e.seq DESC LIMIT 1;
  resolution_hold:=FOUND;
  IF resolution_hold THEN
   IF h.cause NOT IN ('CALL_OWNERSHIP','ANCHOR_GAP')
     OR coalesce(p_release_evidence->>'resolution_event_id','') !~*
       '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     OR (p_release_evidence->>'resolution_event_id')::uuid IS DISTINCT FROM resolution.event_id
     OR p_release_evidence->'store_accepted' IS DISTINCT FROM 'true'::jsonb
     OR NOT EXISTS(SELECT 1 FROM change_ledger.checkpoints k
        WHERE k.tenant_id=t AND k.company_id=c AND k.ledger_seq=resolution.seq
         AND k.head_hash=resolution.hash AND k.sink_kind='REAL' AND k.read_back_confirmed
         AND k.verified AND k.written_at>=h.opened_at) THEN
    RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
   END IF;
   IF NOT change_ledger.chain_ok(t,c) THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
  ELSE
   IF h.cause='CALL_OWNERSHIP' THEN
    RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
   ELSIF h.cause='ANCHOR_GAP' THEN
    IF h.ext_seq IS NOT NULL AND p_release_evidence ? 'two_person_cosign' THEN
     IF cos_id IS NULL OR NOT cs_found OR cs.consumed_at IS NOT NULL THEN
      RAISE EXCEPTION 'COMPLETION_PROOF_MISSING';
     END IF;
     who:=change_ledger.caller_role();
     IF change_ledger.same_person(t,c,who,cs.signer) THEN
      RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
     END IF;
     PERFORM change_ledger.assert_capability(t,c,who,'operator');
     PERFORM change_ledger.assert_capability(t,c,cs.signer,'recovery_witness');
     IF change_ledger.registry_enforced(t,c)
        AND (change_ledger.person_of(t,c,who) IS NULL
          OR change_ledger.person_of(t,c,cs.signer) IS NULL) THEN
      RAISE EXCEPTION 'NOT_ENTITLED';
     END IF;
     IF NOT change_ledger.chain_ok(t,c) THEN RAISE EXCEPTION 'AUDIT_UNAVAILABLE'; END IF;
     UPDATE change_ledger.hold_cosigns SET consumed_at=pg_catalog.clock_timestamp()
      WHERE cosign_id=cs.cosign_id;
     two:=true;
    ELSE
     IF p_release_evidence->'store_accepted' IS DISTINCT FROM 'true'::jsonb THEN
      RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
     END IF;
     IF h.ext_seq IS NOT NULL AND NOT EXISTS(SELECT 1 FROM change_ledger.events e
       WHERE e.tenant_id=t AND e.company_id=c AND e.seq=h.ext_seq AND e.hash=h.ext_head_hash) THEN
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
  END IF;
 UPDATE change_ledger.holds SET released_at=pg_catalog.clock_timestamp(),release_evidence=p_release_evidence
  WHERE hold_id=p_hold_id RETURNING released_at INTO ts;
 PERFORM change_ledger.append_event(t,c,h.change_id,'HOLD_RELEASED',
   pg_catalog.jsonb_build_object('hold_id',p_hold_id,'cause',h.cause,'two_person',two)
    || CASE WHEN resolution_hold THEN pg_catalog.jsonb_build_object(
       'resolution_event_id',resolution.event_id,'checkpoint_event_seq',resolution.seq)
       ELSE '{}'::jsonb END);
 RETURN ts;
END $fn$;
ALTER FUNCTION change_ledger.release_hold_v1(text,text,uuid,jsonb) OWNER TO ledger_owner;

-- Permit cancellation locks record parents before token, permit and release-resource children.
CREATE FUNCTION change_ledger.cancel_permit_v1(t text,c text,p_change_id uuid,p_generation bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_target change_ledger.targets%ROWTYPE; target change_ledger.targets%ROWTYPE;
        plan_target_lock change_ledger.target_locks%ROWTYPE; target_lock change_ledger.target_locks%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_reservation change_ledger.reservations%ROWTYPE; reservation change_ledger.reservations%ROWTYPE;
        plan_permit change_ledger.dispatch_permits%ROWTYPE; permit change_ledger.dispatch_permits%ROWTYPE;
        plan_tokens jsonb; current_tokens jsonb; plan_keys jsonb; current_keys jsonb;
        plan_target_found boolean; target_found boolean; plan_target_lock_found boolean; target_lock_found boolean;
        plan_lease_found boolean; lease_found boolean; plan_reservation_found boolean; reservation_found boolean;
        plan_permit_found boolean; permit_found boolean; rec_found boolean; record_ids uuid[];
        global_keys text[]:=ARRAY[]::text[]; key_keys text[]:=ARRAY[]::text[];
        item record; rid uuid; lock_hash integer; tref text; lock_count integer;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences x
  WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LIFECYCLE_NOT_READY'; END IF;
 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,plan_rec.base_fingerprint);
 tref:=coalesce(plan_rec.target_ref,p_change_id::text);
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO plan_tokens FROM (SELECT ct.* FROM change_ledger.claim_tokens ct WHERE ct.change_id=p_change_id
   ORDER BY ct.token_id LIMIT 201) x;
 SELECT * INTO plan_permit FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation;
 plan_permit_found:=FOUND;
 SELECT * INTO plan_target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_target_found:=FOUND;
 SELECT * INTO plan_target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref;
 plan_target_lock_found:=FOUND;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_lease_found:=FOUND;
 SELECT * INTO plan_reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id;
 plan_reservation_found:=FOUND;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO plan_keys FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
   ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;

 IF pg_catalog.jsonb_array_length(plan_tokens)>196 OR pg_catalog.jsonb_array_length(plan_keys)>200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
    tenant_id text,company_id text,base_fingerprint text)
   WHERE x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
    OR x.base_fingerprint IS DISTINCT FROM plan_rec.base_fingerprint) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;

 record_ids:=ARRAY[p_change_id];
 IF plan_rec.repair_for IS NOT NULL THEN record_ids:=pg_catalog.array_append(record_ids,plan_rec.repair_for);
 ELSIF plan_rec.parent_change_id IS NOT NULL THEN
  record_ids:=pg_catalog.array_append(record_ids,plan_rec.parent_change_id);
 END IF;
 IF plan_target_lock_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_target_lock.owner_change_id); END IF;
 IF plan_lease_found THEN record_ids:=pg_catalog.array_append(record_ids,plan_lease.owner_change_id); END IF;
 SELECT coalesce(pg_catalog.array_agg(DISTINCT u.lock_id ORDER BY u.lock_id),'{}'::uuid[])
  INTO record_ids FROM pg_catalog.unnest(record_ids) AS u(lock_id) WHERE u.lock_id IS NOT NULL;
 lock_count:=pg_catalog.cardinality(record_ids)+pg_catalog.jsonb_array_length(plan_tokens)
  +pg_catalog.jsonb_array_length(plan_keys)
  +CASE WHEN plan_target_found THEN 1 ELSE 0 END
  +CASE WHEN plan_permit_found THEN 1 ELSE 0 END
  +CASE WHEN plan_reservation_found THEN 1 ELSE 0 END
  +CASE WHEN plan_target_lock_found THEN 1 ELSE 0 END
  +CASE WHEN plan_lease_found THEN 1 ELSE 0 END;
 IF lock_count>200 OR pg_catalog.jsonb_array_length(plan_tokens)>196 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 FOR rid IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
   WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
 END LOOP;
 FOR item IN SELECT x.token_id FROM pg_catalog.jsonb_to_recordset(plan_tokens) AS x(
   token_id uuid,change_id uuid,generation bigint,state text,issued_at timestamptz)
 LOOP
  global_keys:=pg_catalog.array_append(global_keys,'claim-token-id:v1:'||pg_catalog.lower(item.token_id::text));
 END LOOP;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,plan_rec.base_fingerprint);
 PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
  t,c,record_ids,plan_rec.base_fingerprint,tref,NULL,true);
 IF (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x)
      ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
     FROM (SELECT k.* FROM change_ledger.key_locks k WHERE k.owner_change_id=p_change_id
      ORDER BY k.base_fingerprint,k.key_hash LIMIT 201) x)
   IS DISTINCT FROM plan_keys THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;

 key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||plan_rec.base_fingerprint||':'||tref);
 FOR item IN SELECT x.base_fingerprint,x.key_hash FROM pg_catalog.jsonb_to_recordset(plan_keys) AS x(
   tenant_id text,company_id text,base_fingerprint text,key_hash text,owner_change_id uuid)
  ORDER BY x.base_fingerprint,x.key_hash
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,t||':'||c||':'||item.base_fingerprint||':'||item.key_hash);
 END LOOP;
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) AS x(k) ORDER BY 1
 LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash);
 END LOOP;

 SELECT * INTO target FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR SHARE;
 target_found:=FOUND;
 FOR rid IN SELECT DISTINCT u.lock_id FROM pg_catalog.unnest(record_ids) AS u(lock_id)
   WHERE u.lock_id IS NOT NULL ORDER BY u.lock_id
 LOOP
  PERFORM 1 FROM change_ledger.records x
   WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=rid FOR UPDATE;
 END LOOP;
 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 rec_found:=FOUND;
 IF NOT rec_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.claim_tokens x WHERE x.change_id=p_change_id
  ORDER BY x.token_id LIMIT 197 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.token_id),'[]'::jsonb)
  INTO current_tokens FROM (SELECT x.* FROM change_ledger.claim_tokens x WHERE x.change_id=p_change_id
   ORDER BY x.token_id LIMIT 197) x;
 IF pg_catalog.jsonb_array_length(current_tokens)>196 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT * INTO permit FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation FOR UPDATE;
 permit_found:=FOUND;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
  ORDER BY x.base_fingerprint,x.key_hash LIMIT 201 FOR UPDATE;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO current_keys FROM (SELECT x.* FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
   ORDER BY x.base_fingerprint,x.key_hash LIMIT 201) x;
 IF pg_catalog.jsonb_array_length(current_keys)>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;
 SELECT * INTO reservation FROM change_ledger.reservations x WHERE x.change_id=p_change_id FOR UPDATE;
 reservation_found:=FOUND;
 SELECT * INTO target_lock FROM change_ledger.target_locks x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint
   AND x.target_ref=tref FOR UPDATE;
 target_lock_found:=FOUND;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 lease_found:=FOUND;
 IF plan_rec IS DISTINCT FROM rec OR plan_tokens IS DISTINCT FROM current_tokens
   OR plan_permit_found IS DISTINCT FROM permit_found
   OR (plan_permit_found AND plan_permit IS DISTINCT FROM permit)
   OR plan_target_found IS DISTINCT FROM target_found
   OR (plan_target_found AND plan_target IS DISTINCT FROM target)
   OR plan_keys IS DISTINCT FROM current_keys
   OR plan_reservation_found IS DISTINCT FROM reservation_found
   OR (plan_reservation_found AND plan_reservation IS DISTINCT FROM reservation)
   OR plan_target_lock_found IS DISTINCT FROM target_lock_found
   OR (plan_target_lock_found AND plan_target_lock IS DISTINCT FROM target_lock)
   OR plan_lease_found IS DISTINCT FROM lease_found
   OR (plan_lease_found AND plan_lease IS DISTINCT FROM lease) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF NOT change_ledger.dispatch_cas(p_change_id,p_generation,'PERMITTED','CANCELLED_UNDISPATCHED') THEN
  RETURN false;
 END IF;
 UPDATE change_ledger.claim_tokens SET state='SUPERSEDED'
  WHERE change_id=p_change_id AND generation=p_generation;
 PERFORM change_ledger.release_zero_effect(t,c,p_change_id);
 UPDATE change_ledger.records SET
  authorization_state=CASE WHEN rec.expires_at<=pg_catalog.clock_timestamp() THEN 'EXPIRED' ELSE 'APPROVED' END,
  execution_state='NOT_STARTED',dispatch_state='CANCELLED_UNDISPATCHED',updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'PERMIT_CANCELLED',
  pg_catalog.jsonb_build_object('generation',p_generation));
 RETURN true;
END $fn$;
ALTER FUNCTION change_ledger.cancel_permit_v1(text,text,uuid,bigint) OWNER TO ledger_owner;

-- Lease renewal follows the record parent and freezes its permit/lease child plan before updating.
CREATE FUNCTION change_ledger.renew_writer_lease_v1(
 t text,c text,p_change_id uuid,p_generation bigint,p_ttl_seconds integer DEFAULT 300
) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE lf change_ledger.lifecycle_fences%ROWTYPE;
        plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_permit change_ledger.dispatch_permits%ROWTYPE; permit change_ledger.dispatch_permits%ROWTYPE;
        plan_lease change_ledger.writer_leases%ROWTYPE; lease change_ledger.writer_leases%ROWTYPE;
        plan_permit_found boolean; permit_found boolean; plan_lease_found boolean; lease_found boolean;
        rec_found boolean; n integer; exp_at timestamptz;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 IF p_ttl_seconds IS NULL OR p_ttl_seconds<1 OR p_ttl_seconds>3600 THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
  SELECT * INTO lf FROM change_ledger.lifecycle_fences x
   WHERE x.tenant_id=t AND x.company_id=c FOR SHARE;
  IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
   RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
  END IF;
 SELECT * INTO plan_rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);
 SELECT * INTO plan_permit FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation;
 plan_permit_found:=FOUND;
 SELECT * INTO plan_lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint;
 plan_lease_found:=FOUND;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text)
 ]);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,plan_rec.base_fingerprint);

 SELECT * INTO rec FROM change_ledger.records x
  WHERE x.tenant_id=t AND x.company_id=c AND x.change_id=p_change_id FOR UPDATE;
 rec_found:=FOUND;
 IF NOT rec_found THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF p_generation IS DISTINCT FROM rec.claim_generation THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 SELECT * INTO permit FROM change_ledger.dispatch_permits x
  WHERE x.change_id=p_change_id AND x.generation=p_generation FOR UPDATE;
 permit_found:=FOUND;
 SELECT * INTO lease FROM change_ledger.writer_leases x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=plan_rec.base_fingerprint FOR UPDATE;
 lease_found:=FOUND;
 IF plan_rec IS DISTINCT FROM rec
   OR plan_permit_found IS DISTINCT FROM permit_found
   OR (plan_permit_found AND plan_permit IS DISTINCT FROM permit)
   OR plan_lease_found IS DISTINCT FROM lease_found
   OR (plan_lease_found AND plan_lease IS DISTINCT FROM lease) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF rec.execution_state<>'APPLYING' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF NOT permit_found OR permit.state NOT IN ('PERMITTED','DISPATCHED') THEN
  RAISE EXCEPTION 'PERMIT_MISSING';
 END IF;
 exp_at:=pg_catalog.clock_timestamp()+pg_catalog.make_interval(secs=>p_ttl_seconds);
 UPDATE change_ledger.writer_leases SET lease_expires_at=exp_at,renewed_at=pg_catalog.clock_timestamp(),
  renew_count=renew_count+1
  WHERE tenant_id=t AND company_id=c AND base_fingerprint=rec.base_fingerprint
   AND owner_change_id=p_change_id AND (lease_expires_at IS NULL OR lease_expires_at>pg_catalog.clock_timestamp());
 GET DIAGNOSTICS n=ROW_COUNT;
 IF n=0 THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'LEASE_RENEWED',
  pg_catalog.jsonb_build_object('generation',p_generation,'lease_expires_at',exp_at));
 RETURN exp_at;
END $fn$;
ALTER FUNCTION change_ledger.renew_writer_lease_v1(text,text,uuid,bigint,integer) OWNER TO ledger_owner;

-- Approver binding candidate with lookup-only exact replay and no duplicate event.
CREATE FUNCTION change_ledger.bind_duplicate_override_v1(
 t text,c text,p_change_id uuid,p_override_digest text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; bk change_ledger.business_keys%ROWTYPE;
        who text; existing_count bigint; existing_digest text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF p_change_id IS NULL OR p_override_digest IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
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
 IF rec.lifecycle<>'VALIDATED' OR rec.authorization_state<>'NONE' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF pg_catalog.pg_has_role(who::name,rec.requester::name,'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'approver');
 PERFORM change_ledger.assert_independent(t,c,who,rec.requester);

 SELECT count(*),pg_catalog.min(ob.override_digest) INTO existing_count,existing_digest
  FROM change_ledger.override_bindings ob
  WHERE ob.change_id=p_change_id AND ob.approver=who;
 IF existing_count>1 THEN RAISE EXCEPTION 'OVERRIDE_BINDING_CONFLICT' USING ERRCODE='P0001'; END IF;
 IF existing_count=1 THEN
  IF existing_digest IS DISTINCT FROM p_override_digest THEN
   RAISE EXCEPTION 'OVERRIDE_BINDING_CONFLICT' USING ERRCODE='P0001';
  END IF;
  SELECT * INTO bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
  IF NOT FOUND OR NOT bk.override_required OR bk.override_digest IS DISTINCT FROM p_override_digest THEN
   RAISE EXCEPTION 'DIGEST_MISMATCH';
  END IF;
  RETURN true;
 END IF;

 SELECT * INTO bk FROM change_ledger.business_keys b
  WHERE b.change_id=p_change_id FOR SHARE;
 IF NOT FOUND OR NOT bk.override_required OR bk.override_digest IS DISTINCT FROM p_override_digest THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 INSERT INTO change_ledger.override_bindings(change_id,approver,override_digest)
 VALUES(p_change_id,who,bk.override_digest);
 PERFORM change_ledger.append_event(t,c,p_change_id,'OVERRIDE_BOUND',
  pg_catalog.jsonb_build_object('approver',who));
 RETURN true;
END $fn$;
ALTER FUNCTION change_ledger.bind_duplicate_override_v1(text,text,uuid,text) OWNER TO ledger_owner;

-- Requester business-key mutation on the common scope fence. The legacy validation key identity
-- remains exact; both global and business-key arbiters are acquired before the record row.
CREATE FUNCTION change_ledger.declare_business_key_v1(
 t text,c text,p_change_id uuid,p_key_hash text,p_override_of text DEFAULT NULL,
 p_justification text DEFAULT NULL
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_bk change_ledger.business_keys%ROWTYPE; ex change_ledger.business_keys%ROWTYPE;
        prior text; dg text; key_changed boolean; plan_bk_found boolean;
        had_ex boolean; who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 IF p_key_hash IS NULL OR p_key_hash !~ '^[a-f0-9]{64}$'
  OR (p_override_of IS NULL) <> (p_justification IS NULL)
  OR (p_override_of IS NOT NULL AND (p_override_of='' OR p_justification='')) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;

 -- The record is a non-locking plan input for the compatibility namespace-4 key.
 SELECT * INTO plan FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 -- Freeze the globally keyed child too; after the parent lock, a changed child means this
 -- operation's pre-fence mutation plan is stale and must not be silently rebased.
 SELECT * INTO plan_bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 plan_bk_found:=FOUND;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text)
 ]);
 PERFORM pg_catalog.pg_advisory_xact_lock(4,pg_catalog.hashtext(
  t||':'||c||':'||plan.base_fingerprint||':'||p_key_hash));

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF ROW(plan.requester,plan.kind,plan.authorization_state,plan.lifecycle,plan.base_fingerprint,
        plan.target_ref,plan.created_at)
    IS DISTINCT FROM
    ROW(rec.requester,rec.kind,rec.authorization_state,rec.lifecycle,rec.base_fingerprint,
        rec.target_ref,rec.created_at) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.requester IS DISTINCT FROM who THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.kind NOT IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 -- Parent before globally keyed business_keys child, matching the FK-SCC lock contract.
 SELECT * INTO ex FROM change_ledger.business_keys b
  WHERE b.change_id=p_change_id FOR UPDATE;
 had_ex:=FOUND;
 IF plan_bk_found IS DISTINCT FROM had_ex
    OR (plan_bk_found AND plan_bk IS DISTINCT FROM ex) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 dg:=pg_catalog.encode(pg_catalog.sha256(convert_to(
  p_change_id::text||':'||p_key_hash||':'||coalesce(p_override_of,'')||':'||
  coalesce(p_justification,''),'UTF8')),'hex');
 IF had_ex AND ex.override_digest=dg THEN RETURN rec.lifecycle; END IF;

 -- This lookup determines only the event's source-compatible key_changed bit.
 SELECT b.key_hash INTO prior FROM change_ledger.business_keys b
  JOIN change_ledger.records o ON o.change_id=b.change_id
  WHERE o.tenant_id=t AND o.company_id=c AND o.target_ref IS NOT DISTINCT FROM rec.target_ref
   AND rec.target_ref IS NOT NULL AND o.change_id<>p_change_id
  ORDER BY o.created_at DESC LIMIT 1;
 key_changed:=(had_ex AND ex.key_hash IS DISTINCT FROM p_key_hash)
  OR (prior IS NOT NULL AND prior IS DISTINCT FROM p_key_hash);
 INSERT INTO change_ledger.business_keys(change_id,tenant_id,company_id,key_hash,override_of,
  override_justification,override_digest,override_required,declared_by)
 VALUES(p_change_id,t,c,p_key_hash,p_override_of,p_justification,dg,false,who)
 ON CONFLICT(change_id) DO UPDATE SET key_hash=EXCLUDED.key_hash,override_of=EXCLUDED.override_of,
  override_justification=EXCLUDED.override_justification,override_digest=EXCLUDED.override_digest,
  override_required=false,declared_at=pg_catalog.clock_timestamp();
 IF rec.lifecycle='VALIDATED' THEN
  UPDATE change_ledger.records SET lifecycle='PROPOSED',updated_at=pg_catalog.clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 END IF;
 PERFORM change_ledger.append_event(t,c,p_change_id,'BUSINESS_KEY_DECLARED',
  pg_catalog.jsonb_build_object('key_changed',coalesce(key_changed,false),
   'override',p_override_of IS NOT NULL,'revalidate',rec.lifecycle='VALIDATED'));
 RETURN CASE WHEN rec.lifecycle='VALIDATED' THEN 'PROPOSED' ELSE rec.lifecycle END;
END $fn$;
ALTER FUNCTION change_ledger.declare_business_key_v1(text,text,uuid,text,text,text) OWNER TO ledger_owner;

-- Requester target-class mutation joined to the same scope/lifecycle writer fence.
CREATE FUNCTION change_ledger.declare_target_class_v1(t text,c text,p_change_id uuid,p_class text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; cls text; who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF p_change_id IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 cls:=change_ledger.norm_target_class(p_class);
 IF cls IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
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
 IF rec.requester IS DISTINCT FROM who THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.authorization_state<>'NONE' OR rec.lifecycle NOT IN ('PROPOSED','VALIDATED') THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,cls);
 UPDATE change_ledger.records SET declared_target_class=cls,updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'TARGET_CLASS_DECLARED',
  pg_catalog.jsonb_build_object('class',cls));
 RETURN cls;
END $fn$;
ALTER FUNCTION change_ledger.declare_target_class_v1(text,text,uuid,text) OWNER TO ledger_owner;

-- Writer-owned S13 target observation. Exact replay is lookup-only and a changed stored
-- observation (including a different authenticated observer) fails before event or row DML.
-- This remains an ungranted additive candidate until the full same-scope fence cutover qualifies.
CREATE FUNCTION change_ledger.observe_target_v1(
 t text,c text,p_token_id uuid,p_fingerprint text,p_class text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE planned change_ledger.claim_tokens%ROWTYPE;
        tok change_ledger.claim_tokens%ROWTYPE;
        rec change_ledger.records%ROWTYPE;
        tg change_ledger.targets%ROWTYPE;
        prior change_ledger.target_observations%ROWTYPE;
        cls text;
        who text;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();

 -- Registry/target authorization must serialize with every candidate same-scope writer.
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c AND f.state IN ('NOT_READY','RECOVERING')) THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;

 -- The immutable token-parent identity is a non-locking plan input. Lock both global IDs in
 -- the helper's signed-hash order before taking parent-first records/token row locks, then
 -- revalidate the plan under those locks.
 SELECT * INTO planned FROM change_ledger.claim_tokens x WHERE x.token_id=p_token_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'claim-token-id:v1:'||pg_catalog.lower(p_token_id::text),
  'record-change-id:v1:'||pg_catalog.lower(planned.change_id::text)
 ]);

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=planned.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 SELECT * INTO tok FROM change_ledger.claim_tokens x
  WHERE x.token_id=p_token_id AND x.change_id=rec.change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TICKET_SUPERSEDED'; END IF;
 IF tok.change_id IS DISTINCT FROM planned.change_id OR tok.generation IS DISTINCT FROM planned.generation THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tok.generation<>rec.claim_generation OR tok.state<>'ISSUED' THEN
  RAISE EXCEPTION 'TICKET_SUPERSEDED';
 END IF;

 cls:=change_ledger.norm_target_class(p_class);
 IF cls IS NULL OR p_fingerprint IS NULL THEN RAISE EXCEPTION 'SCHEMA_INVALID'; END IF;
 SELECT * INTO tg FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=rec.base_fingerprint;
 IF NOT FOUND OR p_fingerprint IS DISTINCT FROM tg.base_fingerprint
   OR cls IS DISTINCT FROM tg.target_class THEN
  RAISE EXCEPTION 'TARGET_REJECTED';
 END IF;
 PERFORM change_ledger.assert_target_effect(t,c,rec.base_fingerprint,rec.organization_ref,
  coalesce(rec.declared_target_class,cls));
 who:=change_ledger.caller_role();

 SELECT * INTO prior FROM change_ledger.target_observations o
  WHERE o.change_id=rec.change_id AND o.generation=tok.generation;
 IF FOUND THEN
  IF prior.observed_fingerprint IS DISTINCT FROM p_fingerprint
    OR prior.observed_class IS DISTINCT FROM cls OR prior.observed_by IS DISTINCT FROM who THEN
   RAISE EXCEPTION 'TARGET_OBSERVATION_CONFLICT' USING ERRCODE='P0001';
  END IF;
  RETURN true;
 END IF;

 INSERT INTO change_ledger.target_observations(
  change_id,generation,observed_fingerprint,observed_class,observed_by)
 VALUES(rec.change_id,tok.generation,p_fingerprint,cls,who);
 PERFORM change_ledger.append_event(t,c,rec.change_id,'TARGET_OBSERVED',
  pg_catalog.jsonb_build_object('generation',tok.generation,'class',cls));
 RETURN true;
END $fn$;
ALTER FUNCTION change_ledger.observe_target_v1(text,text,uuid,text,text) OWNER TO ledger_owner;

-- Worker-owned S13 observation entry. This is additive and remains unreachable from the adapter
-- until its S12/S13 qualification and the coordinated legacy-grant cutover are accepted.
CREATE FUNCTION change_ledger.verify_inconclusive_v1(
 t text,c text,p_change_id uuid,p_observation uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE;
        obs change_ledger.evidence_records%ROWTYPE;
        prior change_ledger.verify_attempt_log%ROWTYPE;
        k change_ledger.sweep_counters%ROWTYPE;
        candidate_hold_id uuid:=pg_catalog.gen_random_uuid();
        spacing double precision;
        has_open_halt boolean;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_change_id IS NULL OR (p_observation IS NOT NULL
   AND p_observation='00000000-0000-0000-0000-000000000000'::uuid) THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c AND f.state IN ('NOT_READY','RECOVERING')) THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;

 -- Namespace 6 covers the global counter subject, caller-supplied evidence ID, and any
 -- exhaustion hold ID. The helper sorts/deduplicates the actual signed hash keys before rows.
 PERFORM change_ledger.private_writer_take_global_fences_v1(
  CASE WHEN p_observation IS NULL THEN ARRAY[
   'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
   'sweep-counter:v1:'||pg_catalog.lower(p_change_id::text)||':VERIFY',
   'hold-id:v1:'||pg_catalog.lower(candidate_hold_id::text)
  ] ELSE ARRAY[
   'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
   'sweep-counter:v1:'||pg_catalog.lower(p_change_id::text)||':VERIFY',
   'verify-attempt-evidence-id:v1:'||pg_catalog.lower(p_observation::text),
   'hold-id:v1:'||pg_catalog.lower(candidate_hold_id::text)
  ] END);

 -- Check the global attempt-log owner before locking business rows. An exact retry returns
 -- only the authoritative current counter snapshot; no attempt/event is appended again.
 SELECT * INTO prior FROM change_ledger.verify_attempt_log l
  WHERE l.evidence_id=p_observation;
 IF FOUND THEN
  IF prior.tenant_id IS DISTINCT FROM t OR prior.company_id IS DISTINCT FROM c
    OR prior.change_id IS DISTINCT FROM p_change_id THEN
   RAISE EXCEPTION 'VERIFY_EVIDENCE_ID_CONFLICT' USING ERRCODE='P0001';
  END IF;
 END IF;

 -- Match the legacy record-first replay boundary after the global owner/conflict check.
 -- This keeps replay serialized with record/lifecycle changes and revalidates scope before
 -- exposing the current counter snapshot.
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);

 IF prior.evidence_id IS NOT NULL THEN
  IF prior.generation IS DISTINCT FROM rec.claim_generation THEN
   RAISE EXCEPTION 'VERIFY_EVIDENCE_ID_CONFLICT' USING ERRCODE='P0001';
  END IF;
  SELECT * INTO obs FROM change_ledger.evidence_records e WHERE e.evidence_id=p_observation;
  IF NOT FOUND OR obs.tenant_id IS DISTINCT FROM prior.tenant_id
    OR obs.company_id IS DISTINCT FROM prior.company_id OR obs.change_id IS DISTINCT FROM prior.change_id
    OR obs.kind IS DISTINCT FROM 'OBSERVATION' OR obs.generation IS DISTINCT FROM prior.generation
    OR obs.content->'inconclusive' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'VERIFY_EVIDENCE_ID_CONFLICT' USING ERRCODE='P0001';
  END IF;
  SELECT * INTO k FROM change_ledger.sweep_counters x
   WHERE x.subject_id=p_change_id AND x.kind='VERIFY';
  RETURN jsonb_build_object('attempts',coalesce(k.attempts,0),
    'exhausted',coalesce(k.closed_at IS NOT NULL,false),'replay',true);
 END IF;

 IF rec.execution_state<>'APPLIED' OR rec.verification_state<>'NOT_VERIFIED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;

 SELECT * INTO obs FROM change_ledger.evidence_records e
  WHERE e.evidence_id=p_observation AND e.tenant_id=t AND e.company_id=c
   AND e.change_id=p_change_id AND e.kind='OBSERVATION';
 IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_UNSIGNED'; END IF;
 IF obs.generation IS DISTINCT FROM rec.claim_generation
   OR obs.content->'inconclusive' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'EVIDENCE_UNSIGNED';
 END IF;
 INSERT INTO change_ledger.verify_attempt_log(evidence_id,tenant_id,company_id,change_id,generation)
 VALUES(p_observation,t,c,p_change_id,obs.generation);

 spacing:=change_ledger.verify_tick_min_spacing(t,c);
 INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind)
 VALUES(t,c,p_change_id,'VERIFY') ON CONFLICT(subject_id,kind) DO NOTHING;
 SELECT * INTO k FROM change_ledger.sweep_counters x
  WHERE x.subject_id=p_change_id AND x.kind='VERIFY' FOR UPDATE;
 IF k.closed_at IS NOT NULL THEN
  RETURN jsonb_build_object('attempts',k.attempts,'exhausted',true);
 END IF;

 UPDATE change_ledger.sweep_counters SET attempts=attempts+1,
  last_attempt_at=clock_timestamp(),
  next_attempt_at=clock_timestamp()+make_interval(secs=>greatest(180::double precision,spacing))
  WHERE subject_id=p_change_id AND kind='VERIFY' RETURNING * INTO k;
 IF k.attempts>=3 THEN
  UPDATE change_ledger.records SET verification_state='FAILED_VERIFY',effect_known='UNKNOWN',
   updated_at=clock_timestamp() WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
  SELECT EXISTS(SELECT 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
    AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL)
   INTO has_open_halt;
  IF NOT has_open_halt THEN
   INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause,change_id)
   VALUES(candidate_hold_id,t,c,rec.base_fingerprint,'FAILED_VERIFY_HALT',p_change_id);
  END IF;
  UPDATE change_ledger.sweep_counters SET closed_at=clock_timestamp(),close_reason='EXHAUSTED'
   WHERE subject_id=p_change_id AND kind='VERIFY';
  PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_RETRY_EXHAUSTED',
   jsonb_build_object('reason','WORKER_INCONCLUSIVE','attempts',k.attempts,'alert',true));
  RETURN jsonb_build_object('attempts',k.attempts,'exhausted',true);
 END IF;

 PERFORM change_ledger.append_event(t,c,p_change_id,'VERIFY_ATTEMPT',
  jsonb_build_object('reason','WORKER_INCONCLUSIVE','attempt',k.attempts));
 RETURN jsonb_build_object('attempts',k.attempts,'exhausted',false);
END $fn$;
ALTER FUNCTION change_ledger.verify_inconclusive_v1(text,text,uuid,uuid) OWNER TO ledger_owner;

-- Proposal preserves the legacy identity, target, entitlement, epoch and replay contract while
-- fencing caller-selected global IDs before parent/child row work. Keep the versioned signature
-- ungranted; the legacy caller-facing signature is replaced below by an ACL-preserving bridge in
-- this same transaction after every same-scope epoch writer has joined the namespace-7 fence.
CREATE FUNCTION change_ledger.propose_v1(
 t text,c text,p_change_id uuid,p_kind text,p_base_fingerprint text,p_organization_ref text,
 p_requester text,p_request_id text,p_payload_digest text,p_target_ref text,p_target_version text,
 p_parent_change_id uuid,p_expires_at timestamptz,p_repair_for uuid DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE existing change_ledger.records%ROWTYPE; tgt_epoch bigint; tgt_status text;
        tgt_org text; tgt_exp timestamptz;
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
 SELECT x.status,x.epoch,x.organization_ref,x.permission_expires_at
  INTO tgt_status,tgt_epoch,tgt_org,tgt_exp FROM change_ledger.targets x
  WHERE x.tenant_id=t AND x.company_id=c AND x.base_fingerprint=p_base_fingerprint FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF tgt_status IS DISTINCT FROM 'ACTIVE' THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_org IS DISTINCT FROM p_organization_ref THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 IF tgt_exp IS NOT NULL AND tgt_exp<=pg_catalog.clock_timestamp() THEN RAISE EXCEPTION 'TARGET_REJECTED'; END IF;
 PERFORM change_ledger.assert_capability(t,c,p_requester,'requester');
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
ALTER FUNCTION change_ledger.propose_v1(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)
 OWNER TO ledger_owner;

CREATE FUNCTION change_ledger.validate_v1(t text,c text,p_change_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE plan_rec change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        plan_bk change_ledger.business_keys%ROWTYPE; bk change_ledger.business_keys%ROWTYPE;
        colls text[]; dup boolean:=false; ovr boolean:=false;
        plan_has_bk boolean; have_bk boolean; who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.private_writer_take_switch_fence_v1(t,c);
 PERFORM change_ledger.assert_switch_off(t,c);
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 SELECT * INTO plan_rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text)
 ]);
 SELECT * INTO plan_bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 plan_has_bk:=FOUND;
 IF plan_rec.lifecycle='PROPOSED' AND NOT plan_has_bk AND plan_rec.kind='CREATE_DRAFT' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF plan_rec.lifecycle='PROPOSED' AND plan_has_bk
   AND plan_rec.kind IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN
  PERFORM pg_catalog.pg_advisory_xact_lock(4,pg_catalog.hashtext(
   t||':'||c||':'||plan_rec.base_fingerprint||':'||plan_bk.key_hash));
 END IF;

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 IF pg_catalog.to_jsonb(plan_rec) IS DISTINCT FROM pg_catalog.to_jsonb(rec) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 SELECT * INTO bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id FOR UPDATE;
 have_bk:=FOUND;
 IF have_bk IS DISTINCT FROM plan_has_bk
   OR (have_bk AND pg_catalog.to_jsonb(plan_bk) IS DISTINCT FROM pg_catalog.to_jsonb(bk)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 who:=change_ledger.caller_role();
 IF rec.requester IS DISTINCT FROM who THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF rec.lifecycle IN ('VALIDATED','DUPLICATE_PARKED') THEN RETURN rec.lifecycle; END IF;
 IF rec.lifecycle<>'PROPOSED' THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 PERFORM change_ledger.budget_precheck(t,c,rec,false,false);
 IF have_bk AND rec.kind IN ('CREATE_DRAFT','UPDATE_DRAFT') THEN
  SELECT coalesce(pg_catalog.array_agg(x.change_id::text ORDER BY x.created_at,x.change_id),
                  ARRAY[]::text[])
   INTO colls FROM (
    SELECT o.change_id,o.created_at FROM change_ledger.records o
    JOIN change_ledger.business_keys ob ON ob.change_id=o.change_id
    WHERE o.tenant_id=t AND o.company_id=c AND o.base_fingerprint=rec.base_fingerprint
     AND o.organization_ref=rec.organization_ref AND o.change_id<>rec.change_id
     AND ob.key_hash=bk.key_hash AND o.lifecycle='VALIDATED'
     AND o.authorization_state NOT IN ('VOIDED','REVOKED','EXPIRED')
     AND o.execution_state NOT IN ('FAILED_APPLY','ROLLBACK_REFUSED')
     AND NOT (rec.kind='UPDATE_DRAFT' AND rec.target_ref IS NOT NULL
              AND o.target_ref IS NOT DISTINCT FROM rec.target_ref)
    ORDER BY o.created_at,o.change_id LIMIT 2
   ) x;
  IF pg_catalog.cardinality(colls)>0 THEN
   IF bk.override_of IS NOT NULL AND pg_catalog.cardinality(colls)=1 AND bk.override_of=colls[1] THEN
    ovr:=true;
    UPDATE change_ledger.business_keys SET override_required=true WHERE change_id=p_change_id;
   ELSE
    dup:=true;
   END IF;
  END IF;
 END IF;
 UPDATE change_ledger.records SET
  lifecycle=CASE WHEN dup THEN 'DUPLICATE_PARKED' ELSE 'VALIDATED' END,
  updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
  RETURNING lifecycle INTO rec.lifecycle;
 PERFORM change_ledger.append_event(t,c,p_change_id,'VALIDATED',
  pg_catalog.jsonb_build_object('lifecycle',rec.lifecycle,'override_pending',ovr));
 RETURN rec.lifecycle;
END $fn$;
ALTER FUNCTION change_ledger.validate_v1(text,text,uuid) OWNER TO ledger_owner;

-- Bridge the still-granted historical signature to the same fenced implementation. This prevents
-- candidate and legacy adapter instances from holding record and namespace-4 locks in opposite order.
CREATE OR REPLACE FUNCTION change_ledger.validate(t text,c text,p_change_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
BEGIN
 RETURN change_ledger.validate_v1(t,c,p_change_id);
END $fn$;
ALTER FUNCTION change_ledger.validate(text,text,uuid) OWNER TO ledger_owner;

-- Approval nonce issuance shares its parent/child order with envelope, approval and recovery paths.
CREATE FUNCTION change_ledger.issue_approval_nonce_v1(
 t text,c text,p_change_id uuid,p_nonce text
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; who text; lf change_ledger.lifecycle_fences%ROWTYPE;
        v_now timestamptz; plan_expired text[]; current_expired text[]; locked_expired text[];
        global_keys text[];
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_nonce!~'^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 v_now:=pg_catalog.clock_timestamp();
 SELECT coalesce(pg_catalog.array_agg(n.nonce ORDER BY n.nonce),ARRAY[]::text[])
  INTO plan_expired FROM change_ledger.approval_nonces n
  JOIN change_ledger.records r ON r.change_id=n.change_id AND r.tenant_id=t AND r.company_id=c
  WHERE n.change_id=p_change_id AND n.state='ISSUED' AND n.expires_at<=v_now;
 IF pg_catalog.cardinality(plan_expired)>=200 THEN
  RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID';
 END IF;
 SELECT pg_catalog.array_agg(x.lock_key ORDER BY x.lock_key) INTO global_keys
  FROM (SELECT 'record-change-id:v1:'||pg_catalog.lower(p_change_id::text) AS lock_key
        UNION ALL SELECT 'approval-nonce:v1:'||n FROM pg_catalog.unnest(plan_expired||ARRAY[p_nonce]) AS u(n)) x;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);

 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 who:=change_ledger.caller_role();
 IF who IS NOT DISTINCT FROM rec.requester OR pg_catalog.pg_has_role(who::name,rec.requester::name,'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 IF rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED','APPROVED')
   OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,who,'approver');
 PERFORM change_ledger.assert_independent(t,c,who,rec.requester);
 PERFORM change_ledger.assert_session_independent(t,c,rec.requester_session);

 SELECT coalesce(pg_catalog.array_agg(q.nonce ORDER BY q.nonce),ARRAY[]::text[])
  INTO locked_expired FROM (
   SELECT n.nonce FROM change_ledger.approval_nonces n
    WHERE n.change_id=p_change_id AND n.nonce=ANY(plan_expired)
    ORDER BY n.nonce FOR UPDATE
  ) q;
 SELECT coalesce(pg_catalog.array_agg(n.nonce ORDER BY n.nonce),ARRAY[]::text[])
  INTO current_expired FROM change_ledger.approval_nonces n
  WHERE n.change_id=p_change_id AND n.state='ISSUED' AND n.expires_at<=v_now;
 IF locked_expired IS DISTINCT FROM plan_expired OR current_expired IS DISTINCT FROM plan_expired THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.approval_nonces n WHERE n.nonce=p_nonce) THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;

 IF pg_catalog.cardinality(plan_expired)>0 THEN
  UPDATE change_ledger.approval_nonces n SET state='EXPIRED'
   WHERE n.change_id=p_change_id AND n.nonce=ANY(plan_expired) AND n.state='ISSUED';
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END IF;
 INSERT INTO change_ledger.approval_nonces(nonce,change_id,approver,expires_at)
 VALUES(p_nonce,p_change_id,who,v_now+interval '10 minutes');
 RETURN p_nonce;
END $fn$;
ALTER FUNCTION change_ledger.issue_approval_nonce_v1(text,text,uuid,text) OWNER TO ledger_owner;

-- Canonical approval-envelope storage joins the common S13 mutation fence. The granted legacy
-- signature is routed through an ACL-preserving bridge below; direct v1 remains ungranted.
CREATE FUNCTION change_ledger.store_approval_text_v1(
 t text,c text,p_change_id uuid,p_nonce text,p_text text,p_envelope_id uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; nrow change_ledger.approval_nonces%ROWTYPE;
        ex change_ledger.approval_envelopes%ROWTYPE; env jsonb; dg text;
        who text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_nonce!~'^[a-f0-9]{64}$'
    OR p_text IS NULL OR p_text='' OR p_envelope_id IS NULL
    OR p_envelope_id='00000000-0000-0000-0000-000000000000'::uuid
   OR pg_catalog.octet_length(p_text)>262144 THEN
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
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'approval-nonce:v1:'||p_nonce,
  'approval-envelope-id:v1:'||pg_catalog.lower(p_envelope_id::text)
 ]);
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 who:=change_ledger.caller_role();
 IF rec.requester IS DISTINCT FROM who THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;

 SELECT * INTO ex FROM change_ledger.approval_envelopes e
  WHERE e.change_id=p_change_id AND e.approval_nonce=p_nonce;
 IF FOUND THEN
  IF ex.canonical_text=p_text THEN RETURN change_ledger.text_digest(ex.canonical_text); END IF;
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF rec.lifecycle NOT IN ('PROPOSED','VALIDATED')
   OR rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED')
   OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 SELECT * INTO nrow FROM change_ledger.approval_nonces n
  WHERE n.nonce=p_nonce AND n.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.expires_at<=pg_catalog.clock_timestamp() THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.approval_envelopes e WHERE e.envelope_id=p_envelope_id) THEN
  RAISE EXCEPTION 'APPROVAL_ENVELOPE_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 BEGIN
  env:=p_text::jsonb;
 EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END;
 IF pg_catalog.jsonb_typeof(env)<>'object'
   OR change_ledger.canon_json(env) IS DISTINCT FROM p_text THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.envelope_check(rec,env,p_nonce);
 INSERT INTO change_ledger.approval_envelopes(
  envelope_id,change_id,tenant_id,company_id,approval_nonce,digest_version,canonical_text,stored_by
 ) VALUES(p_envelope_id,p_change_id,t,c,p_nonce,'S12-APPROVAL-2',p_text,who);
 dg:=change_ledger.text_digest(p_text);
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVAL_TEXT_STORED',
  pg_catalog.jsonb_build_object('digest',dg,'digest_version','S12-APPROVAL-2'));
 RETURN dg;
END $fn$;
ALTER FUNCTION change_ledger.store_approval_text_v1(text,text,uuid,text,text,uuid) OWNER TO ledger_owner;

-- Approval consumes an immutable stored envelope and preallocates its global approval identity.
CREATE FUNCTION change_ledger.approve_v1(
 t text,c text,p_change_id uuid,p_nonce text,p_digest text,p_approval_id uuid
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; nrow change_ledger.approval_nonces%ROWTYPE;
        env change_ledger.approval_envelopes%ROWTYPE; bk change_ledger.business_keys%ROWTYPE;
        v_approver text; aid uuid; parent_req text; atype text; amfa boolean;
        lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_nonce!~'^[a-f0-9]{64}$'
    OR p_digest IS NULL OR p_approval_id IS NULL
    OR p_approval_id='00000000-0000-0000-0000-000000000000'::uuid THEN
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
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'approval-nonce:v1:'||p_nonce,
  'approval-id:v1:'||pg_catalog.lower(p_approval_id::text)
 ]);
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 v_approver:=change_ledger.caller_role();
 SELECT a.approval_id INTO aid FROM change_ledger.approvals a
  WHERE a.change_id=p_change_id AND a.nonce=p_nonce AND a.approver=v_approver
   AND a.decision='APPROVE' AND a.digest=p_digest AND a.digest_version='S12-APPROVAL-2'
   AND rec.authorization_state IN ('APPROVED','CLAIMED');
 IF FOUND THEN RETURN aid; END IF;
 IF rec.lifecycle<>'VALIDATED' OR rec.authorization_state NOT IN ('NONE','VOIDED','REVOKED')
   OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 IF v_approver IS NOT DISTINCT FROM rec.requester
   OR pg_catalog.pg_has_role(v_approver::name,rec.requester::name,'MEMBER') THEN
  RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
 END IF;
 PERFORM change_ledger.assert_capability(t,c,v_approver,'approver');
 PERFORM change_ledger.assert_independent(t,c,v_approver,rec.requester);
 PERFORM change_ledger.assert_session_independent(t,c,rec.requester_session);
 IF rec.repair_for IS NOT NULL THEN
  SELECT p.requester INTO parent_req FROM change_ledger.records p
   WHERE p.tenant_id=t AND p.company_id=c AND p.change_id=rec.repair_for;
  IF change_ledger.same_person(t,c,v_approver,parent_req) THEN
   RAISE EXCEPTION 'APPROVER_NOT_INDEPENDENT';
  END IF;
 END IF;
 SELECT * INTO env FROM change_ledger.approval_envelopes e
  WHERE e.change_id=p_change_id AND e.approval_nonce=p_nonce;
 IF NOT FOUND THEN
  IF NOT EXISTS(SELECT 1 FROM change_ledger.approval_nonces n
   WHERE n.nonce=p_nonce AND n.change_id=p_change_id AND n.state='ISSUED' AND n.approver=v_approver) THEN
   RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
  END IF;
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 IF p_digest IS DISTINCT FROM change_ledger.text_digest(env.canonical_text) THEN
  RAISE EXCEPTION 'DIGEST_MISMATCH';
 END IF;
 PERFORM change_ledger.envelope_check(rec,env.canonical_text::jsonb,p_nonce);
 IF NOT change_ledger.epoch_deps_current(t,c,rec.epoch_dependencies) THEN
  RAISE EXCEPTION 'EPOCH_CHANGED';
 END IF;
 SELECT * INTO nrow FROM change_ledger.approval_nonces n
  WHERE n.nonce=p_nonce AND n.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.approver IS DISTINCT FROM v_approver THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 IF nrow.expires_at<=pg_catalog.clock_timestamp() THEN RAISE EXCEPTION 'APPROVAL_EXPIRED'; END IF;
 SELECT * INTO bk FROM change_ledger.business_keys b WHERE b.change_id=p_change_id;
 IF FOUND AND bk.override_required AND NOT EXISTS(SELECT 1 FROM change_ledger.override_bindings ob
  WHERE ob.change_id=p_change_id AND ob.approver=v_approver AND ob.override_digest=bk.override_digest) THEN
  RAISE EXCEPTION 'DUPLICATE_SUSPECTED';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.approvals a WHERE a.approval_id=p_approval_id) THEN
  RAISE EXCEPTION 'APPROVAL_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 UPDATE change_ledger.approval_nonces n SET state='CONSUMED' WHERE n.nonce=p_nonce;
 atype:=change_ledger.approval_lane(t,c,rec.base_fingerprint);
 amfa:=coalesce((SELECT pr.mfa FROM change_ledger.principals pr
  WHERE pr.tenant_id=t AND pr.company_id=c AND pr.principal=v_approver),false);
 INSERT INTO change_ledger.approvals(
  approval_id,change_id,approver,nonce,digest,decision,approval_type,mfa_verified,digest_version,envelope_id
 ) VALUES(p_approval_id,p_change_id,v_approver,p_nonce,p_digest,'APPROVE',atype,amfa,'S12-APPROVAL-2',env.envelope_id);
 UPDATE change_ledger.records SET authorization_state='APPROVED',
  epoch_dependencies=epoch_dependencies||pg_catalog.jsonb_build_object('principal:'||v_approver,
   change_ledger.epoch_value(t,c,'principal:'||v_approver)),
  updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'APPROVED',
  pg_catalog.jsonb_build_object('approval_id',p_approval_id,'digest',p_digest,
   'digest_version','S12-APPROVAL-2','approval_type',atype,'mfa_verified',amfa));
 RETURN p_approval_id;
END $fn$;
ALTER FUNCTION change_ledger.approve_v1(text,text,uuid,text,text,uuid) OWNER TO ledger_owner;

-- Rejection is deliberately one-shot; a repeated post-REJECTED call must not append another approval/event.
CREATE FUNCTION change_ledger.reject_v1(
 t text,c text,p_change_id uuid,p_nonce text,p_approval_id uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE rec change_ledger.records%ROWTYPE; nrow change_ledger.approval_nonces%ROWTYPE;
        v_approver text; lf change_ledger.lifecycle_fences%ROWTYPE;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 IF p_change_id IS NULL OR p_nonce IS NULL OR p_nonce!~'^[a-f0-9]{64}$'
    OR p_approval_id IS NULL
    OR p_approval_id='00000000-0000-0000-0000-000000000000'::uuid THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT * INTO lf FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR lf.state IN ('NOT_READY','RECOVERING') THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
  'approval-nonce:v1:'||p_nonce,
  'approval-id:v1:'||pg_catalog.lower(p_approval_id::text)
 ]);
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.lifecycle NOT IN ('PROPOSED','VALIDATED')
   OR rec.authorization_state NOT IN ('NONE','APPROVED') OR rec.execution_state<>'NOT_STARTED' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 v_approver:=change_ledger.caller_role();
 SELECT * INTO nrow FROM change_ledger.approval_nonces n
  WHERE n.nonce=p_nonce AND n.change_id=p_change_id FOR UPDATE;
 IF NOT FOUND OR nrow.state<>'ISSUED' OR nrow.approver IS DISTINCT FROM v_approver
   OR nrow.expires_at<=pg_catalog.clock_timestamp() THEN
  RAISE EXCEPTION 'APPROVAL_NONCE_INVALID';
 END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.approvals a WHERE a.approval_id=p_approval_id) THEN
  RAISE EXCEPTION 'APPROVAL_ID_CONFLICT' USING ERRCODE='P0001';
 END IF;
 UPDATE change_ledger.approval_nonces n SET state='CONSUMED' WHERE n.nonce=p_nonce;
 INSERT INTO change_ledger.approvals(
  approval_id,change_id,approver,nonce,digest,decision,approval_type,mfa_verified
 ) VALUES(p_approval_id,p_change_id,v_approver,p_nonce,pg_catalog.repeat('0',64),'REJECT',
  change_ledger.approval_lane(t,c,rec.base_fingerprint),
  coalesce((SELECT pr.mfa FROM change_ledger.principals pr
   WHERE pr.tenant_id=t AND pr.company_id=c AND pr.principal=v_approver),false));
 UPDATE change_ledger.records SET lifecycle='REJECTED',
  authorization_state=CASE WHEN authorization_state='APPROVED' THEN 'VOIDED' ELSE authorization_state END,
  updated_at=pg_catalog.clock_timestamp()
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 PERFORM change_ledger.append_event(t,c,p_change_id,'REJECTED',
  pg_catalog.jsonb_build_object('authorization_from',rec.authorization_state));
 RETURN 'REJECTED';
END $fn$;
ALTER FUNCTION change_ledger.reject_v1(text,text,uuid,text,uuid) OWNER TO ledger_owner;

-- Keep checkpoint inserts inside the candidate's scope serialization order. The historical
-- implementation in 015 validates and inserts correctly, but does not acquire namespace 7;
-- S13 requires same-scope checkpoint writes to serialize while preserving the global identity
-- sequence and accepting rollback gaps. Provider I/O remains the caller's responsibility and
-- must finish before this database function is entered.
CREATE OR REPLACE FUNCTION change_ledger.record_checkpoint(
 t text, c text, p_ledger_seq bigint, p_head_hash text, p_sink_kind text, p_sink_id text,
 p_signer_key_id text, p_signature text, p_signed_at timestamptz, p_read_back boolean
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE s bigint; who text; vk change_ledger.verifier_keys%ROWTYPE;
BEGIN
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 PERFORM change_ledger.assert_scope(t,c);
 who := change_ledger.caller_role();
 IF NOT pg_has_role(who::name,'checkpoint_role','USAGE') THEN RAISE EXCEPTION 'NOT_ENTITLED'; END IF;
 IF p_ledger_seq IS NULL OR p_head_hash IS NULL OR p_head_hash !~ '^[a-f0-9]{64}$' OR p_sink_id IS NULL
  OR p_sink_id='' OR p_signer_key_id IS NULL OR p_signature IS NULL OR p_signed_at IS NULL
  OR p_read_back IS NULL OR p_sink_kind IS NULL OR p_sink_kind NOT IN ('REAL','TEST') THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 IF NOT p_read_back THEN RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE'; END IF;

 -- Serialize same-scope retries first. An already verified exact Ed25519 record remains usable
 -- for replay even if its key was later revoked for new checkpoint writes.
 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 SELECT k.seq INTO s FROM change_ledger.checkpoints k
  JOIN change_ledger.verifier_keys old_key
    ON old_key.tenant_id=k.tenant_id AND old_key.company_id=k.company_id
   AND old_key.key_id=k.signer_key_id
  WHERE k.tenant_id=t AND k.company_id=c AND k.ledger_seq=p_ledger_seq
   AND k.head_hash=p_head_hash AND k.sink_kind=p_sink_kind AND k.sink_id=p_sink_id
   AND k.signer_key_id=p_signer_key_id AND k.signature=p_signature AND k.signed_at=p_signed_at
   AND k.read_back_confirmed AND k.verified
   AND old_key.role_name='checkpoint_role' AND old_key.key_algorithm='ED25519'
  ORDER BY k.seq LIMIT 1;
 IF FOUND THEN RETURN s; END IF;

 -- Plan the verifier-material fence without locking a relation row. The scope fence is held
 -- before the key-material fence, verifier row lock and checkpoint INSERT.
 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_signer_key_id;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
   OR vk.key_algorithm IS DISTINCT FROM 'ED25519' OR vk.key_material IS NULL
   OR NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(vk.key_material,17017));
 PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[
  'verifier-key-id:v1:'||p_signer_key_id
 ]);
 SELECT * INTO vk FROM change_ledger.verifier_keys k
  WHERE k.tenant_id=t AND k.company_id=c AND k.key_id=p_signer_key_id FOR SHARE;
 IF NOT FOUND OR vk.status<>'ACTIVE' OR vk.role_name<>'checkpoint_role'
   OR vk.key_algorithm IS DISTINCT FROM 'ED25519' OR vk.key_material IS NULL
   OR NOT pg_has_role(who::name,vk.role_name::name,'USAGE') THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 IF NOT change_ledger.signature_ok(vk.key_algorithm,vk.key_material,
   change_ledger.checkpoint_payload(t,c,p_ledger_seq,p_head_hash,p_signed_at,
                                    p_signer_key_id,p_sink_kind,p_sink_id),
   p_signature) THEN
  RAISE EXCEPTION 'CHECKPOINT_UNAVAILABLE';
 END IF;
 INSERT INTO change_ledger.checkpoints(tenant_id,company_id,ledger_seq,head_hash,sink_kind,
  sink_id,signer_key_id,signature,signed_at,read_back_confirmed,written_by,verified)
 VALUES(t,c,p_ledger_seq,p_head_hash,p_sink_kind,p_sink_id,p_signer_key_id,p_signature,
  p_signed_at,true,who,true)
 RETURNING seq INTO s;
 RETURN s;
END $fn$;

DO $owner$
DECLARE tbl text;
BEGIN
 FOREACH tbl IN ARRAY ARRAY[
  'private_writer_service_bindings','private_writer_serving_fences','private_writer_signer_key_versions',
  'private_writer_service_instance_history',
  'private_writer_signer_key_scopes','private_writer_signer_key_revocations','private_writer_signer_key_rotations',
  'private_writer_process_attestations','private_writer_oracle_artifacts',
  'private_writer_outcome_version_floors','private_writer_trust_registry_revision',
  'private_writer_dispatch_intents','private_writer_permit_bindings','dispatch_attempts','private_writer_evidence',
  'private_writer_attempt_evidence','writer_barriers','writer_barrier_calls','writer_barrier_acknowledgements',
  'physical_base_slots'
 ] LOOP
  EXECUTE format('ALTER TABLE change_ledger.%I OWNER TO ledger_owner',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE change_ledger.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('CREATE POLICY ledger_owner_all ON change_ledger.%I FOR ALL TO ledger_owner USING (true) WITH CHECK (true)',tbl);
 END LOOP;
 FOREACH tbl IN ARRAY ARRAY[
  'private_writer_scope_v1','private_writer_identity_v1','private_writer_admission_decision_v1',
  'private_writer_permit_binding_v1','private_writer_dispatch_intent_v1',
  'private_writer_evidence_attempt_v1','private_writer_call_snapshot_v1',
  'private_writer_barrier_snapshot_v1','private_writer_startup_state_v1',
  'private_writer_barrier_ack_v1'
 ] LOOP
  EXECUTE format('ALTER TYPE change_ledger.%I OWNER TO ledger_owner',tbl);
 END LOOP;
END $owner$;

DO $acl$
DECLARE tbl text; schema_name name; loid oid; type_row record;
BEGIN
 -- The service principals are scoped to this database API. Remove direct grants on every
 -- application schema, not only change_ledger; standard system schemas remain untouched.
 FOR schema_name IN
  SELECT n.nspname FROM pg_catalog.pg_namespace n
   WHERE n.nspname<>'information_schema' AND n.nspname !~ '^pg_'
 LOOP
  EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM business_ai_private_writer,private_writer_evidence_ingest',
                 schema_name);
  EXECUTE format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %I FROM business_ai_private_writer,private_writer_evidence_ingest',
                 schema_name);
  EXECUTE format('REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA %I FROM business_ai_private_writer,private_writer_evidence_ingest',
                 schema_name);
  EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM business_ai_private_writer,private_writer_evidence_ingest',
                 schema_name);
  -- PostgreSQL exposes generated array types in pg_type, but their ACL is controlled through
  -- the element type and rejects a direct REVOKE ON TYPE against the array name.
  FOR type_row IN
   SELECT t.typname FROM pg_catalog.pg_type t
   WHERE t.typnamespace=(SELECT n.oid FROM pg_catalog.pg_namespace n
                         WHERE n.nspname=schema_name)
     AND t.typelem=0
  LOOP
   EXECUTE format('REVOKE USAGE ON TYPE %I.%I FROM business_ai_private_writer,private_writer_evidence_ingest',
                  schema_name,type_row.typname);
  END LOOP;
 END LOOP;
 FOR loid IN SELECT l.oid FROM pg_catalog.pg_largeobject_metadata l LOOP
  EXECUTE format('REVOKE ALL PRIVILEGES ON LARGE OBJECT %s FROM business_ai_private_writer,private_writer_evidence_ingest',
                 loid);
 END LOOP;

 -- Existing role names are accepted only after validating their role attributes and membership,
 -- but a pre-existing role may still carry direct grants from earlier provisioning. Normalize
 -- the complete schema before the explicit function allowlist below; a fixed new-table list is
 -- insufficient to prove that the service roles have no inherited legacy object access.
 REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA change_ledger
  FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
 REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA change_ledger
  FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
 REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA change_ledger
  FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
 REVOKE CREATE ON SCHEMA change_ledger
  FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
 -- Normalize element types only; PostgreSQL does not permit direct ACL changes on generated arrays.
 FOR type_row IN
  SELECT t.typname FROM pg_catalog.pg_type t
   JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='change_ledger' AND t.typelem=0
 LOOP
  EXECUTE format('REVOKE USAGE ON TYPE change_ledger.%I FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest',
                 type_row.typname);
 END LOOP;

 FOREACH tbl IN ARRAY ARRAY[
  'private_writer_service_bindings','private_writer_serving_fences','private_writer_signer_key_versions',
  'private_writer_service_instance_history',
  'private_writer_signer_key_scopes','private_writer_signer_key_revocations','private_writer_signer_key_rotations',
  'private_writer_process_attestations','private_writer_oracle_artifacts',
  'private_writer_outcome_version_floors','private_writer_trust_registry_revision',
  'private_writer_dispatch_intents','private_writer_permit_bindings','dispatch_attempts','private_writer_evidence',
  'private_writer_attempt_evidence','writer_barriers','writer_barrier_calls','writer_barrier_acknowledgements',
  'physical_base_slots'
 ] LOOP
  EXECUTE format('REVOKE ALL ON TABLE change_ledger.%I FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,requester_role,writer_role,worker_role',tbl);
 END LOOP;

 -- Direct grants have been removed above. Test effective reachability, not object ACLs in
 -- isolation: PostgreSQL also requires schema USAGE before a relation or routine can be named.
 -- This avoids treating PUBLIC routine grants in an inaccessible schema as usable authority.
 IF EXISTS (
   SELECT 1 FROM pg_catalog.pg_namespace n
    WHERE n.nspname<>'information_schema' AND n.nspname !~ '^pg_'
      AND (pg_catalog.has_schema_privilege('business_ai_private_writer',n.oid,'CREATE')
        OR pg_catalog.has_schema_privilege('private_writer_evidence_ingest',n.oid,'CREATE'))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname<>'information_schema' AND n.nspname !~ '^pg_'
      AND c.relkind IN ('r','p','v','m','f')
      AND ((pg_catalog.has_schema_privilege('business_ai_private_writer',n.oid,'USAGE')
             AND (pg_catalog.has_table_privilege('business_ai_private_writer',c.oid,
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR pg_catalog.has_any_column_privilege('business_ai_private_writer',c.oid,
                       'SELECT,INSERT,UPDATE,REFERENCES')))
        OR (pg_catalog.has_schema_privilege('private_writer_evidence_ingest',n.oid,'USAGE')
             AND (pg_catalog.has_table_privilege('private_writer_evidence_ingest',c.oid,
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR pg_catalog.has_any_column_privilege('private_writer_evidence_ingest',c.oid,
                       'SELECT,INSERT,UPDATE,REFERENCES'))))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname<>'information_schema' AND n.nspname !~ '^pg_' AND c.relkind='S'
      AND ((pg_catalog.has_schema_privilege('business_ai_private_writer',n.oid,'USAGE')
             AND pg_catalog.has_sequence_privilege('business_ai_private_writer',c.oid,'USAGE,SELECT,UPDATE'))
        OR (pg_catalog.has_schema_privilege('private_writer_evidence_ingest',n.oid,'USAGE')
             AND pg_catalog.has_sequence_privilege('private_writer_evidence_ingest',c.oid,'USAGE,SELECT,UPDATE')))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname<>'information_schema' AND n.nspname !~ '^pg_'
      AND ((pg_catalog.has_schema_privilege('business_ai_private_writer',n.oid,'USAGE')
             AND pg_catalog.has_function_privilege('business_ai_private_writer',p.oid,'EXECUTE'))
        OR (pg_catalog.has_schema_privilege('private_writer_evidence_ingest',n.oid,'USAGE')
             AND pg_catalog.has_function_privilege('private_writer_evidence_ingest',p.oid,'EXECUTE')))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_type t
    JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
    WHERE n.nspname<>'information_schema' AND n.nspname !~ '^pg_'
      AND ((pg_catalog.has_schema_privilege('business_ai_private_writer',n.oid,'USAGE')
             AND pg_catalog.has_type_privilege('business_ai_private_writer',t.oid,'USAGE'))
        OR (pg_catalog.has_schema_privilege('private_writer_evidence_ingest',n.oid,'USAGE')
             AND pg_catalog.has_type_privilege('private_writer_evidence_ingest',t.oid,'USAGE')))
   UNION ALL
   SELECT 1 FROM pg_catalog.pg_largeobject_metadata l
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      coalesce(l.lomacl,pg_catalog.acldefault('L',l.lomowner))) acl
    WHERE acl.grantee IN (0, (SELECT oid FROM pg_catalog.pg_roles WHERE rolname='business_ai_private_writer'),
                             (SELECT oid FROM pg_catalog.pg_roles WHERE rolname='private_writer_evidence_ingest'))
      AND acl.privilege_type IN ('SELECT','UPDATE')
 ) THEN
  RAISE EXCEPTION 'PRIVATE_WRITER_OUT_OF_SCOPE_PRIVILEGE';
 END IF;
END $acl$;

REVOKE ALL ON TYPE change_ledger.private_writer_permit_binding_v1
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON TYPE change_ledger.private_writer_evidence_attempt_v1
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,writer_role,worker_role,operator_role,approver_role,auditor_role,checkpoint_role;
REVOKE ALL ON TYPE change_ledger.private_writer_dispatch_intent_v1
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON TYPE change_ledger.private_writer_evidence
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON TYPE change_ledger.private_writer_barrier_ack_v1
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;

REVOKE ALL ON FUNCTION change_ledger.private_writer_lookup_v1(change_ledger.private_writer_identity_v1)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_resolve_signer_key_v1(
 text,text,text,text,text,text,text,text,text,timestamptz)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_load_trust_snapshot_v1(
 text,text,text,text,text,text[],text[],uuid[],text,text,boolean)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,requester_role,writer_role,worker_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_evidence_attempt_v1(uuid,uuid,text,text,text,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,writer_role,worker_role,operator_role,approver_role,auditor_role,checkpoint_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_load_evidence_records_v1(
 uuid,uuid,text,text,text,text,uuid,bigint,text,text[])
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_lookup_barrier_v1(uuid)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_startup_recovery_state_v1(text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_admit_v1(
 change_ledger.private_writer_identity_v1,text,bigint),
 change_ledger.private_writer_refusal_v1(change_ledger.private_writer_identity_v1,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_mark_invoking_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_begin_com_entry_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_issue_permit_v1(
 text,text,uuid,bigint,uuid,uuid,text,text,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.change_ledger_begin_apply_v1(text,text,uuid,uuid,text,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_dispatch_intent_for_call_v1(text,text,uuid)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_permit_binding_for_intent_v1(text,text,uuid)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_register_evidence_v1(
 change_ledger.private_writer_evidence)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_record_terminal_v1(
 change_ledger.private_writer_identity_v1,uuid,text,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_attach_recovered_receipt_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_record_verified_success_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_record_recovered_not_invoked_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_record_recovered_terminal_v1(
 change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text,text,text,uuid)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_close_and_advance_v1(
 text,change_ledger.private_writer_scope_v1,bigint,uuid,text,bigint)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_register_barrier_ack_v1(
 change_ledger.private_writer_barrier_ack_v1,text,bytea,bigint)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_lookup_barrier_ack_v1(uuid)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_load_barrier_ack_trust_v1(
 change_ledger.private_writer_barrier_ack_v1)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_finish_barrier_v1(
 change_ledger.private_writer_barrier_snapshot_v1,text,text,bigint)
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_evidence_binding_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_bump_trust_revision_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_trust_revision_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,writer_role,worker_role,operator_role,approver_role,auditor_role,checkpoint_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_lock_trust_revision_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest,
      requester_role,writer_role,worker_role,operator_role,approver_role,auditor_role,checkpoint_role;
REVOKE ALL ON FUNCTION change_ledger.private_writer_attempt_evidence_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_key_revocation_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_key_rotation_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_service_binding_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_serving_fence_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_attempt_transition_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_barrier_transition_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_base_slot_transition_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_barrier_ack_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_permit_signature_guard_v1()
 FROM PUBLIC,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_assert_transaction_v1()
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_take_switch_fence_v1(text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_take_base_fence_v1(text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_take_scope_fence_v1(text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_take_global_fences_v1(text[])
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.add_epoch_dependency_v1(text,text,uuid,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.bump_epoch_v1(text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.register_principal_v1(text,text,text,text,text[],boolean),
 change_ledger.register_target_v1(text,text,text,text,text,text,timestamptz),
 change_ledger.approve_registry_change_v1(text,text,uuid,text),
 change_ledger.register_verifier_key_v1(text,text,text,text,text),
 change_ledger.revoke_verifier_key_v1(text,text,text),
 change_ledger.enforce_registry_v1(text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.propose_registry_change_v1(text,text,uuid,text,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.require_dispatch_receipt_v1(text,text,uuid,bigint)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.record_dispatch_receipt_v1(text,text,uuid,bigint,text,text,text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.verify_dispatch_payload_v1(text,text,uuid,bigint,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.record_evidence_v1(
 text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.witness_cosign_signed_v1(text,text,uuid,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.anchor_gap_cosign_v1(text,text,uuid,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.set_sweep_policy_v1(text,text,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.bind_duplicate_override_v1(text,text,uuid,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.declare_business_key_v1(text,text,uuid,text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.budget_admin_v1(
 text,text,uuid,text,numeric,integer,integer,timestamptz,timestamptz)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.budget_revoke_v1(text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.declare_budget_v1(text,text,uuid,uuid,text,numeric,boolean,boolean)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.claim_v1(text,text,uuid,text,uuid,numeric,boolean,boolean,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.release_claim_v1(text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.renew_writer_lease_v1(text,text,uuid,bigint,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_open_hold_v1(text,text,text,text,text,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.declare_anchor_gap_v1(text,text,text,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.declare_unclean_restart_v1(text,text,text,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.check_anchor_v1(text,text,bigint,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.cancel_permit_v1(text,text,uuid,bigint)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.release_hold_v1(text,text,uuid,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.revoke_change_v1(text,text,uuid,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.revoke_stale_v1(text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.recover_sweep_v1(text,text,jsonb,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recover_sweep_core_v1(text,text,jsonb,uuid,boolean),
 change_ledger.private_writer_recover_sweep_deferred_v1(text,text,jsonb,uuid),
 change_ledger.private_writer_append_queued_events_v1(text,text,jsonb)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_has_eligible_v1(text,text,jsonb,text,timestamptz)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_gap_bound_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_gap_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_verify_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_t5x_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_permit_v1(text,text,uuid,bigint,jsonb,text,timestamptz,uuid,text,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.private_writer_recovery_t12_v1(text,text,uuid,jsonb,text,timestamptz,uuid,integer)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.kill_switch_v1(text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.retry_verify_v1(text,text,uuid,uuid,uuid,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.declare_target_class_v1(text,text,uuid,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.observe_target_v1(text,text,uuid,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
-- Candidate epoch/registry entries above intentionally have no application EXECUTE grants. Keep
-- them unreachable until every conflicting legacy entry has joined the same reviewed fence and
-- the effective-privilege plus disposable race gates are accepted.
-- The legacy claim(text,text,uuid,text,uuid,numeric,boolean,boolean) grant from migration 004 stays
-- as the stable caller boundary, but its body is bridged above to claim_v1's parent-first lock plan
-- and namespace-7 fence. Direct claim_v1 execution remains revoked; do not enable the adapter's
-- candidate flag until the full reachable graph and the bridged/flag-on race cases qualify. The
-- legacy release_claim signature is likewise bridged above so both old-name calls share the
-- candidate parent-first ordering without direct v1 grants.
-- T17 candidate closure. The legacy body is intentionally not exposed by the S13 adapter;
-- this additive route plans parent and resource identities before touching any business row.
CREATE FUNCTION change_ledger.operator_close_failed_verify_v1(
 t text,c text,p_change_id uuid,p_cosign_id uuid,p_effect_present boolean
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
DECLARE who text; rec_before change_ledger.records%ROWTYPE; rec change_ledger.records%ROWTYPE;
        cs_before change_ledger.witness_cosigns%ROWTYPE; cs change_ledger.witness_cosigns%ROWTYPE;
        parent_ids uuid[]; parent_plan jsonb; parent_now jsonb; global_keys text[]; key_keys text[];
        hold_plan jsonb; hold_now jsonb; reservation_plan jsonb; reservation_now jsonb;
        target_plan jsonb; target_now jsonb; key_plan jsonb; key_now jsonb;
        rid uuid; lock_hash integer; owner_id uuid; v_target_ref text; key_hash text; row_count integer;
BEGIN
 PERFORM change_ledger.assert_scope(t,c);
 PERFORM change_ledger.private_writer_assert_transaction_v1();
 who:=change_ledger.caller_role();
 IF NOT pg_catalog.pg_has_role(who::name,'operator_role','USAGE') THEN
  RAISE EXCEPTION 'NOT_ENTITLED' USING ERRCODE='42501';
 END IF;
 IF p_change_id IS NULL OR p_cosign_id IS NULL OR p_effect_present IS NULL
   OR p_change_id='00000000-0000-0000-0000-000000000000'
   OR p_cosign_id='00000000-0000-0000-0000-000000000000' THEN
  RAISE EXCEPTION 'SCHEMA_INVALID';
 END IF;
 SELECT * INTO rec_before FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'CHANGE_NOT_FOUND'; END IF;
 PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
  t,c,p_change_id,rec_before.base_fingerprint);
 v_target_ref:=coalesce(rec_before.target_ref,p_change_id::text);
 SELECT w.* INTO cs_before FROM change_ledger.witness_cosigns w
  WHERE w.change_id=p_change_id AND w.cosign_id=p_cosign_id;

 -- Freeze every parent that owns the contested target lock. Parent rows are later locked in
 -- canonical UUID order before any hold/cosign/reservation/resource child row.
 SELECT coalesce(array_agg(DISTINCT x.change_id ORDER BY x.change_id),ARRAY[p_change_id]::uuid[])
  INTO parent_ids
  FROM (SELECT p_change_id AS change_id UNION ALL
        SELECT tl.owner_change_id FROM change_ledger.target_locks tl
        WHERE tl.tenant_id=t AND tl.company_id=c AND tl.base_fingerprint=rec_before.base_fingerprint
          AND tl.target_ref=v_target_ref) x;
 SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
  INTO parent_plan FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(parent_ids);
 IF jsonb_array_length(parent_plan)<>cardinality(parent_ids) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
  INTO hold_plan FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL;
 SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
  INTO reservation_plan FROM change_ledger.reservations r WHERE r.change_id=p_change_id;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.base_fingerprint,x.target_ref),'[]'::jsonb)
  INTO target_plan FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=rec_before.base_fingerprint
   AND (x.owner_change_id=p_change_id OR x.target_ref=v_target_ref);
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO key_plan FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=rec_before.base_fingerprint AND x.owner_change_id=p_change_id;
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
    AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
      OR x.base_fingerprint IS DISTINCT FROM rec_before.base_fingerprint)) THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 row_count:=cardinality(parent_ids)+jsonb_array_length(hold_plan)
   +jsonb_array_length(reservation_plan)+jsonb_array_length(target_plan)+jsonb_array_length(key_plan)+3;
 IF cardinality(parent_ids)>200 OR jsonb_array_length(hold_plan)>1
   OR jsonb_array_length(target_plan)>200 OR jsonb_array_length(key_plan)>200
   OR row_count>200 THEN RAISE EXCEPTION 'MUTATION_TRANSACTION_INVALID'; END IF;

 global_keys:=ARRAY['record-change-id:v1:'||pg_catalog.lower(p_change_id::text),
   'witness-cosign-id:v1:'||pg_catalog.lower(p_cosign_id::text)];
 FOREACH rid IN ARRAY parent_ids LOOP
  IF rid<>p_change_id THEN
   global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(rid::text));
  END IF;
 END LOOP;
 FOR owner_id IN SELECT (x.value->>'hold_id')::uuid
  FROM pg_catalog.jsonb_array_elements(hold_plan) AS x(value)
 LOOP global_keys:=pg_catalog.array_append(global_keys,'hold-id:v1:'||pg_catalog.lower(owner_id::text)); END LOOP;
 key_keys:=ARRAY['target-lock:v1:'||t||':'||c||':'||rec_before.base_fingerprint||':'||v_target_ref];
 FOR v_target_ref IN SELECT x.value->>'target_ref'
  FROM pg_catalog.jsonb_array_elements(target_plan) AS x(value)
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,'target-lock:v1:'||t||':'||c||':'||
   rec_before.base_fingerprint||':'||v_target_ref);
 END LOOP;
 v_target_ref:=coalesce(rec_before.target_ref,p_change_id::text);
 FOR key_hash IN SELECT x.value->>'key_hash'
  FROM pg_catalog.jsonb_array_elements(key_plan) AS x(value)
 LOOP
  key_keys:=pg_catalog.array_append(key_keys,
   t||':'||c||':'||rec_before.base_fingerprint||':'||key_hash);
 END LOOP;

 PERFORM change_ledger.private_writer_take_scope_fence_v1(t,c);
 PERFORM 1 FROM change_ledger.lifecycle_fences f
  WHERE f.tenant_id=t AND f.company_id=c FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM change_ledger.lifecycle_fences f
   WHERE f.tenant_id=t AND f.company_id=c AND f.state IN ('NOT_READY','RECOVERING')) THEN
  RAISE EXCEPTION 'LIFECYCLE_NOT_READY';
 END IF;
 PERFORM change_ledger.private_writer_take_global_fences_v1(global_keys);
  PERFORM change_ledger.private_writer_assert_target_lease_owner_scope_v1(
   t,c,p_change_id,rec_before.base_fingerprint);
  PERFORM change_ledger.private_writer_assert_planned_resource_owner_scope_v1(
   t,c,parent_ids,rec_before.base_fingerprint,v_target_ref,NULL,false);
  IF EXISTS(SELECT 1 FROM change_ledger.key_locks x WHERE x.owner_change_id=p_change_id
      AND (x.tenant_id IS DISTINCT FROM t OR x.company_id IS DISTINCT FROM c
        OR x.base_fingerprint IS DISTINCT FROM rec_before.base_fingerprint))
    OR (SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
        FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
         AND x.base_fingerprint=rec_before.base_fingerprint AND x.owner_change_id=p_change_id)
      IS DISTINCT FROM key_plan THEN
   RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
  END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(3,pg_catalog.hashtext(t||':'||c||':FAILED_VERIFY_HALT'));
 FOR lock_hash IN SELECT DISTINCT pg_catalog.hashtext(k) FROM pg_catalog.unnest(key_keys) u(k) ORDER BY 1
 LOOP PERFORM pg_catalog.pg_advisory_xact_lock(4,lock_hash); END LOOP;
 -- Recompute the sorted parent set after the ranked fences; a changed owner invalidates the plan.
 IF EXISTS(SELECT 1 FROM change_ledger.target_locks tl
   WHERE tl.tenant_id=t AND tl.company_id=c AND tl.base_fingerprint=rec_before.base_fingerprint
    AND tl.target_ref=v_target_ref AND NOT tl.owner_change_id=ANY(parent_ids)) THEN
  RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001';
 END IF;
 FOR rid IN SELECT DISTINCT x FROM pg_catalog.unnest(parent_ids) u(x) ORDER BY x LOOP
  PERFORM 1 FROM change_ledger.records r
   WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=rid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
  INTO parent_now FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=ANY(parent_ids);
 IF parent_now IS DISTINCT FROM parent_plan THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO rec FROM change_ledger.records r
  WHERE r.tenant_id=t AND r.company_id=c AND r.change_id=p_change_id;
 PERFORM change_ledger.recheck_scope_locked(t,c);
 IF rec.verification_state<>'FAILED_VERIFY'
   OR EXISTS(SELECT 1 FROM change_ledger.change_closures cc WHERE cc.change_id=p_change_id)
   OR jsonb_array_length(hold_plan)<>1 THEN RAISE EXCEPTION 'FORBIDDEN_TRANSITION'; END IF;
 IF NOT p_effect_present AND rec.effect_known IS NOT DISTINCT FROM 'YES' THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 PERFORM 1 FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
  AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL
  ORDER BY h.hold_id FOR UPDATE;
 SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.hold_id),'[]'::jsonb)
  INTO hold_now FROM change_ledger.holds h WHERE h.tenant_id=t AND h.company_id=c
   AND h.change_id=p_change_id AND h.cause='FAILED_VERIFY_HALT' AND h.released_at IS NULL;
 IF hold_now IS DISTINCT FROM hold_plan THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.base_fingerprint=rec.base_fingerprint AND x.owner_change_id=p_change_id
  ORDER BY x.key_hash FOR UPDATE;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.base_fingerprint,x.key_hash),'[]'::jsonb)
  INTO key_now FROM change_ledger.key_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=rec.base_fingerprint AND x.owner_change_id=p_change_id;
 IF key_now IS DISTINCT FROM key_plan THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.reservations r WHERE r.change_id=p_change_id FOR UPDATE;
 SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.change_id),'[]'::jsonb)
  INTO reservation_now FROM change_ledger.reservations r WHERE r.change_id=p_change_id;
 IF reservation_now IS DISTINCT FROM reservation_plan THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 SELECT tl.owner_change_id INTO owner_id FROM change_ledger.target_locks tl
  WHERE tl.tenant_id=t AND tl.company_id=c AND tl.base_fingerprint=rec.base_fingerprint
   AND tl.target_ref=v_target_ref;
 IF owner_id IS NOT NULL AND owner_id<>p_change_id THEN RAISE EXCEPTION 'LOCK_BUSY'; END IF;
 PERFORM 1 FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
  AND x.base_fingerprint=rec.base_fingerprint
  AND (x.owner_change_id=p_change_id OR x.target_ref=v_target_ref)
  ORDER BY x.target_ref FOR UPDATE;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.base_fingerprint,x.target_ref),'[]'::jsonb)
  INTO target_now FROM change_ledger.target_locks x WHERE x.tenant_id=t AND x.company_id=c
   AND x.base_fingerprint=rec.base_fingerprint
   AND (x.owner_change_id=p_change_id OR x.target_ref=v_target_ref);
 IF target_now IS DISTINCT FROM target_plan THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 PERFORM 1 FROM change_ledger.witness_cosigns w WHERE w.change_id=p_change_id
  AND w.cosign_id=p_cosign_id FOR UPDATE;
 SELECT w.* INTO cs FROM change_ledger.witness_cosigns w
  WHERE w.change_id=p_change_id AND w.cosign_id=p_cosign_id;
 IF cs IS DISTINCT FROM cs_before THEN RAISE EXCEPTION 'LOCK_PLAN_STALE' USING ERRCODE='P0001'; END IF;
 IF EXISTS(SELECT 1 FROM change_ledger.change_closures cc WHERE cc.change_id=p_change_id) THEN
  RAISE EXCEPTION 'FORBIDDEN_TRANSITION';
 END IF;
 cs:=change_ledger.consume_two_person_cosign(rec,who,p_cosign_id);
 UPDATE change_ledger.holds SET released_at=clock_timestamp(),
  release_evidence=jsonb_build_object('closed_by_operator',who,'witness',cs.signer,
   'completion_proof',cs.completion_proof)
  WHERE tenant_id=t AND company_id=c AND change_id=p_change_id
   AND cause='FAILED_VERIFY_HALT' AND released_at IS NULL;
 DELETE FROM change_ledger.target_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 DELETE FROM change_ledger.key_locks WHERE tenant_id=t AND company_id=c
  AND base_fingerprint=rec.base_fingerprint AND owner_change_id=p_change_id;
 IF p_effect_present THEN
  UPDATE change_ledger.records SET effect_known='YES',updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 ELSE
  UPDATE change_ledger.reservations SET state='RELEASED' WHERE change_id=p_change_id AND state<>'RELEASED';
  UPDATE change_ledger.records SET effect_known='NO',reservation_state='RELEASED',updated_at=clock_timestamp()
   WHERE tenant_id=t AND company_id=c AND change_id=p_change_id;
 END IF;
 INSERT INTO change_ledger.change_closures(tenant_id,company_id,change_id,closed_by,witness,
  cosign_id,effect_present,completion_proof)
 VALUES(t,c,p_change_id,who,cs.signer,p_cosign_id,p_effect_present,cs.completion_proof);
 PERFORM change_ledger.append_event(t,c,p_change_id,'FAILED_VERIFY_CLOSED',
  jsonb_build_object('effect_present',p_effect_present,'cosign_id',p_cosign_id));
 RETURN 'CLOSED';
END $fn$;
ALTER FUNCTION change_ledger.operator_close_failed_verify_v1(text,text,uuid,uuid,boolean)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.operator_close_failed_verify_v1(text,text,uuid,uuid,boolean)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

-- Keep the owner-only provisioning API on the same ranked scope fence as S13 mutations.
-- It remains owner-only and is not granted to any application role by this candidate migration.
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
  VALUES(p_role,t,c) ON CONFLICT DO NOTHING;
END $fn$;
ALTER FUNCTION change_ledger.add_role_scope(text,text,text) OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.add_role_scope(text,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;

-- The old caller-facing signature is bridged below; the direct v1 entry remains revoked and
-- qualification is still required before this candidate migration is applied outside a disposable lane.
CREATE FUNCTION change_ledger.attach_permit_signature_v1(
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
ALTER FUNCTION change_ledger.attach_permit_signature_v1(text,text,uuid,bigint,text,text)
 OWNER TO ledger_owner;
REVOKE ALL ON FUNCTION change_ledger.attach_permit_signature_v1(text,text,uuid,bigint,text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;

REVOKE ALL ON FUNCTION change_ledger.verify_inconclusive_v1(text,text,uuid,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.store_approval_text_v1(text,text,uuid,text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.issue_approval_nonce_v1(text,text,uuid,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.reject_v1(text,text,uuid,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.approve_v1(text,text,uuid,text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.validate_v1(text,text,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION change_ledger.propose_v1(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,checkpoint_role,
 business_ai_private_writer,private_writer_evidence_ingest;
-- Keep the installed legacy signatures as the caller boundary while routing epoch and verifier
-- registry mutations through the common scope/material fences. These SECURITY DEFINER bridges
-- preserve existing EXECUTE ACLs and return contracts; versioned bodies stay ungranted to callers.
-- Migration 027 is transactional, so this bridge set becomes visible as one cutover.
CREATE OR REPLACE FUNCTION change_ledger.bump_epoch(t text,c text,p_key text) RETURNS bigint
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.bump_epoch_v1($1,$2,$3)
$fn$;
ALTER FUNCTION change_ledger.bump_epoch(text,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.register_principal(
 t text,c text,p_principal text,p_person_id text,p_capabilities text[],p_active boolean
) RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.register_principal_v1($1,$2,$3,$4,$5,$6)
$fn$;
ALTER FUNCTION change_ledger.register_principal(text,text,text,text,text[],boolean) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.register_target(
 t text,c text,p_base text,p_org text,p_class text,p_status text,p_permission_expires_at timestamptz
) RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.register_target_v1($1,$2,$3,$4,$5,$6,$7)
$fn$;
ALTER FUNCTION change_ledger.register_target(text,text,text,text,text,text,timestamptz) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.approve_registry_change(t text,c text,p_change_id uuid,p_digest text)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.approve_registry_change_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.approve_registry_change(text,text,uuid,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.add_epoch_dependency(t text,c text,p_change_id uuid,p_key text)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.add_epoch_dependency_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.add_epoch_dependency(text,text,uuid,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.register_verifier_key(
 t text,c text,p_key_id text,p_role_name text,p_key_material text
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.register_verifier_key_v1($1,$2,$3,$4,$5)
$fn$;
ALTER FUNCTION change_ledger.register_verifier_key(text,text,text,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.revoke_verifier_key(t text,c text,p_key_id text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.revoke_verifier_key_v1($1,$2,$3)
$fn$;
ALTER FUNCTION change_ledger.revoke_verifier_key(text,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.enforce_registry(t text,c text) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.enforce_registry_v1($1,$2)
$fn$;
ALTER FUNCTION change_ledger.enforce_registry(text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.propose_registry_change(t text,c text,p_kind text,p_params jsonb)
RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.propose_registry_change_v1(
  $1,$2,pg_catalog.gen_random_uuid(),$3,$4)
$fn$;
ALTER FUNCTION change_ledger.propose_registry_change(text,text,text,jsonb) OWNER TO ledger_owner;

-- Preserve the granted legacy proposal signature while routing it through the same global-ID,
-- scope, lifecycle, target and epoch fences as flag-on callers. The v1 signature remains revoked
-- from runtime roles; this source bridge and the epoch/registry bridge set are transactional.
CREATE OR REPLACE FUNCTION change_ledger.propose(
 t text,c text,p_change_id uuid,p_kind text,p_base_fingerprint text,p_organization_ref text,
 p_requester text,p_request_id text,p_payload_digest text,p_target_ref text,p_target_version text,
 p_parent_change_id uuid,p_expires_at timestamptz,p_repair_for uuid DEFAULT NULL
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.propose_v1(
  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
$fn$;
ALTER FUNCTION change_ledger.propose(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)
 OWNER TO ledger_owner;

-- Preserve the granted approval-family signatures while moving each caller onto the same scope,
-- lifecycle, nonce and global-ID fences. IDs/nonces are generated before ranked locks; direct v1
-- signatures remain revoked. The bridge set is installed atomically with expiry/recovery routes.
CREATE OR REPLACE FUNCTION change_ledger.issue_approval_nonce(t text,c text,p_change_id uuid)
RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.issue_approval_nonce_v1(
  $1,$2,$3,pg_catalog.replace(pg_catalog.gen_random_uuid()::text,'-','')||
                 pg_catalog.replace(pg_catalog.gen_random_uuid()::text,'-',''))
$fn$;
ALTER FUNCTION change_ledger.issue_approval_nonce(text,text,uuid) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.store_approval_text(
 t text,c text,p_change_id uuid,p_nonce text,p_text text
) RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.store_approval_text_v1($1,$2,$3,$4,$5,pg_catalog.gen_random_uuid())
$fn$;
ALTER FUNCTION change_ledger.store_approval_text(text,text,uuid,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.approve(
 t text,c text,p_change_id uuid,p_nonce text,p_digest text
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.approve_v1($1,$2,$3,$4,$5,pg_catalog.gen_random_uuid())
$fn$;
ALTER FUNCTION change_ledger.approve(text,text,uuid,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.reject(
 t text,c text,p_change_id uuid,p_nonce text
) RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.reject_v1($1,$2,$3,$4,pg_catalog.gen_random_uuid())
$fn$;
ALTER FUNCTION change_ledger.reject(text,text,uuid,text) OWNER TO ledger_owner;

-- Budget grant writers share the global grant-ID and FK-parent order. Keep each granted legacy
-- signature/ACL as an entry bridge; direct versioned signatures remain revoked.
CREATE OR REPLACE FUNCTION change_ledger.budget_admin(
 t text,c text,p_grant_id uuid,p_currency text,p_amount_limit numeric,p_count_limit integer,
 p_post_count_limit integer,p_window_start timestamptz,p_window_end timestamptz
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.budget_admin_v1($1,$2,$3,$4,$5,$6,$7,$8,$9)
$fn$;
ALTER FUNCTION change_ledger.budget_admin(text,text,uuid,text,numeric,integer,integer,timestamptz,timestamptz)
 OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.budget_revoke(t text,c text,p_grant_id uuid)
RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.budget_revoke_v1($1,$2,$3)
$fn$;
ALTER FUNCTION change_ledger.budget_revoke(text,text,uuid) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.declare_budget(
 t text,c text,p_change_id uuid,p_grant_id uuid,p_currency text,p_amount numeric,
 p_counts_create_update boolean,p_counts_post boolean
) RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.declare_budget_v1($1,$2,$3,$4,$5,$6,$7,$8)
$fn$;
ALTER FUNCTION change_ledger.declare_budget(text,text,uuid,uuid,text,numeric,boolean,boolean)
 OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.set_sweep_policy(t text,c text,p_params jsonb)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.set_sweep_policy_v1($1,$2,$3)
$fn$;
ALTER FUNCTION change_ledger.set_sweep_policy(text,text,jsonb) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.bind_duplicate_override(
 t text,c text,p_change_id uuid,p_override_digest text
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.bind_duplicate_override_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.bind_duplicate_override(text,text,uuid,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.observe_target(
 t text,c text,p_token_id uuid,p_fingerprint text,p_class text
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.observe_target_v1($1,$2,$3,$4,$5)
$fn$;
ALTER FUNCTION change_ledger.observe_target(text,text,uuid,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.declare_business_key(
 t text,c text,p_change_id uuid,p_key_hash text,p_override_of text DEFAULT NULL,
 p_justification text DEFAULT NULL
) RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.declare_business_key_v1($1,$2,$3,$4,$5,$6)
$fn$;
ALTER FUNCTION change_ledger.declare_business_key(text,text,uuid,text,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.declare_target_class(
 t text,c text,p_change_id uuid,p_class text
) RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.declare_target_class_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.declare_target_class(text,text,uuid,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.release_hold(
 t text,c text,p_hold_id uuid,p_release_evidence jsonb
) RETURNS timestamptz LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.release_hold_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.release_hold(text,text,uuid,jsonb) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.cancel_permit(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.cancel_permit_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.cancel_permit(text,text,uuid,bigint) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.renew_writer_lease(
 t text,c text,p_change_id uuid,p_generation bigint,p_ttl_seconds integer DEFAULT 300
) RETURNS timestamptz LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.renew_writer_lease_v1($1,$2,$3,$4,$5)
$fn$;
ALTER FUNCTION change_ledger.renew_writer_lease(text,text,uuid,bigint,integer) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.declare_anchor_gap(t text,c text,p_base text,p_detail jsonb)
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.declare_anchor_gap_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.declare_anchor_gap(text,text,text,jsonb) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.declare_unclean_restart(t text,c text,p_base text,p_detail jsonb)
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.declare_unclean_restart_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.declare_unclean_restart(text,text,text,jsonb) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.check_anchor(t text,c text,p_ext_seq bigint,p_ext_head_hash text)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.check_anchor_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.check_anchor(text,text,bigint,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.require_dispatch_receipt(
 t text,c text,p_change_id uuid,p_generation bigint
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.require_dispatch_receipt_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.require_dispatch_receipt(text,text,uuid,bigint) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.record_dispatch_receipt(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_received_sha text,
 p_new_version text,p_signature text
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.record_dispatch_receipt_v1(
  $1,$2,$3,$4,$5,$6,$7,$8,pg_catalog.gen_random_uuid())
$fn$;
ALTER FUNCTION change_ledger.record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text)
 OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.verify_dispatch_payload(
 t text,c text,p_change_id uuid,p_generation bigint,p_payload text
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.verify_dispatch_payload_v1(
  $1,$2,$3,$4,$5,pg_catalog.gen_random_uuid())
$fn$;
ALTER FUNCTION change_ledger.verify_dispatch_payload(text,text,uuid,bigint,text)
 OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.attach_permit_signature(
 t text,c text,p_change_id uuid,p_generation bigint,p_key_id text,p_signature text
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.attach_permit_signature_v1($1,$2,$3,$4,$5,$6)
$fn$;
ALTER FUNCTION change_ledger.attach_permit_signature(text,text,uuid,bigint,text,text)
 OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.kill_switch(t text,c text,p_mode text)
RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.kill_switch_v1($1,$2,$3)
$fn$;
ALTER FUNCTION change_ledger.kill_switch(text,text,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.revoke_change(t text,c text,p_change_id uuid,p_cause text)
RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.revoke_change_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.revoke_change(text,text,uuid,text) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.record_evidence(
 t text,c text,p_change_id uuid,p_kind text,p_content_hash text,p_observed_at timestamptz,
 p_content jsonb,p_key_id text,p_binding_hash text,p_signature text,p_generation bigint,p_call_id uuid
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.record_evidence_v1(
  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,pg_catalog.gen_random_uuid())
$fn$;
ALTER FUNCTION change_ledger.record_evidence(
 text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid)
 OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.witness_cosign_signed(
 t text,c text,p_change_id uuid,p_completion uuid
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.witness_cosign_signed_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.witness_cosign_signed(text,text,uuid,uuid) OWNER TO ledger_owner;

CREATE OR REPLACE FUNCTION change_ledger.anchor_gap_cosign(
 t text,c text,p_hold_id uuid,p_evidence jsonb
) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $fn$
 SELECT change_ledger.anchor_gap_cosign_v1($1,$2,$3,$4)
$fn$;
ALTER FUNCTION change_ledger.anchor_gap_cosign(text,text,uuid,jsonb) OWNER TO ledger_owner;

-- Legacy operator-resolution routes do not participate in the candidate scope/epoch fence.
-- Keep them unavailable to runtime roles until reviewed versioned replacements exist.
REVOKE ALL ON FUNCTION change_ledger.operator_resolve(text,text,uuid,uuid,boolean,boolean),
 change_ledger.operator_close_failed_verify(text,text,uuid,uuid,boolean)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION
 change_ledger.begin_apply(text,text,uuid,uuid,text,text),
 change_ledger.issue_permit(text,text,uuid,bigint),
 change_ledger.record_call(text,text,uuid,bigint,uuid),
 change_ledger.complete_signed(text,text,uuid,bigint,text,uuid),
 change_ledger.complete_lock_busy(text,text,uuid,bigint,uuid,jsonb),
 change_ledger.verify_signed(text,text,uuid,uuid,uuid,uuid),
 change_ledger.resolve_unknown_signed(text,text,uuid,uuid,uuid,boolean,boolean),
 change_ledger.verify_inconclusive(text,text,uuid,uuid),
 change_ledger.retry_verify(text,text,uuid,uuid,uuid,uuid),
 change_ledger.recover_sweep(text,text),
 change_ledger.recover_sweep(text,text,jsonb),
 change_ledger.revoke_stale(text,text)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;

-- The versioned entry points above now own the lifecycle/epoch checks under the ranked
-- namespace-2/8/7 fences. The historical row triggers would reacquire lifecycle_fences after
-- relation locks (and events_chain_guard's final namespace-1 lock), reversing that order.
-- Remove them only in this same transactional bridge cutover, after every legacy mutation is
-- either routed through its versioned body or revoked from runtime roles.
DROP TRIGGER IF EXISTS dispatch_permit_lifecycle_guard ON change_ledger.dispatch_permits;
DROP TRIGGER IF EXISTS events_lifecycle_fence_guard ON change_ledger.events;
REVOKE ALL ON FUNCTION
 change_ledger.lifecycle_writer_epoch(text,text,uuid,bigint,bigint)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION
 change_ledger.fence_check(text,text,uuid,bigint,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
REVOKE ALL ON FUNCTION
 change_ledger.dispatch_permit_lifecycle_guard(),
 change_ledger.events_lifecycle_fence_guard()
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
GRANT USAGE ON SCHEMA change_ledger TO business_ai_private_writer;
GRANT USAGE ON TYPE change_ledger.private_writer_identity_v1,
 change_ledger.private_writer_scope_v1,
 change_ledger.private_writer_admission_decision_v1,
 change_ledger.private_writer_call_snapshot_v1,
 change_ledger.private_writer_barrier_snapshot_v1,
 change_ledger.private_writer_startup_state_v1 TO business_ai_private_writer;
GRANT USAGE ON TYPE change_ledger.private_writer_dispatch_intent_v1
 TO requester_role,writer_role,worker_role;
GRANT USAGE ON TYPE change_ledger.private_writer_permit_binding_v1 TO worker_role;
GRANT USAGE ON SCHEMA change_ledger TO private_writer_evidence_ingest;
GRANT USAGE ON TYPE change_ledger.private_writer_evidence,
 change_ledger.private_writer_barrier_ack_v1 TO private_writer_evidence_ingest;
GRANT EXECUTE ON FUNCTION change_ledger.private_writer_lookup_v1(change_ledger.private_writer_identity_v1),
 change_ledger.private_writer_lookup_barrier_v1(uuid),
 change_ledger.private_writer_startup_recovery_state_v1(text) TO business_ai_private_writer;
GRANT EXECUTE ON FUNCTION change_ledger.change_ledger_begin_apply_v1(text,text,uuid,uuid,text,text)
 TO requester_role,writer_role;
-- Expose only the adapter bridge that carries the caller's preallocated token ID. Direct
-- claim_v1 execution remains revoked from runtime roles above.
REVOKE ALL ON FUNCTION change_ledger.claim_with_id_v1(
 text,text,uuid,text,uuid,numeric,boolean,boolean,uuid)
 FROM PUBLIC,requester_role,approver_role,operator_role,writer_role,worker_role,auditor_role,
 checkpoint_role,business_ai_private_writer,private_writer_evidence_ingest;
GRANT EXECUTE ON FUNCTION change_ledger.claim_with_id_v1(
 text,text,uuid,text,uuid,numeric,boolean,boolean,uuid) TO requester_role;
-- add_epoch_dependency_v1 intentionally has no application EXECUTE grant yet. Its fresh epoch
-- snapshot is valid only after every same-scope epoch writer has joined namespace 7; granting it
-- earlier would permit a stale dependency snapshot to race a legacy epoch mutation.
GRANT EXECUTE ON FUNCTION change_ledger.private_writer_dispatch_intent_for_call_v1(text,text,uuid)
 TO requester_role,writer_role,worker_role;
GRANT EXECUTE ON FUNCTION change_ledger.private_writer_permit_binding_for_intent_v1(text,text,uuid),
 change_ledger.private_writer_issue_permit_v1(text,text,uuid,bigint,uuid,uuid,text,text,text)
 TO worker_role;
GRANT EXECUTE ON FUNCTION change_ledger.private_writer_admit_v1(
 change_ledger.private_writer_identity_v1,text,bigint),
 change_ledger.private_writer_mark_invoking_v1(change_ledger.private_writer_identity_v1,uuid,text,bigint),
 change_ledger.private_writer_begin_com_entry_v1(change_ledger.private_writer_identity_v1,uuid,text,bigint),
 change_ledger.private_writer_record_terminal_v1(change_ledger.private_writer_identity_v1,uuid,text,text),
 change_ledger.private_writer_attach_recovered_receipt_v1(
  change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text),
 change_ledger.private_writer_record_verified_success_v1(
  change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text,text),
 change_ledger.private_writer_record_recovered_not_invoked_v1(
  change_ledger.private_writer_identity_v1,uuid,text,bigint,text),
 change_ledger.private_writer_record_recovered_terminal_v1(
  change_ledger.private_writer_identity_v1,uuid,text,bigint,text,text,text,text,uuid),
 change_ledger.private_writer_close_and_advance_v1(
  text,change_ledger.private_writer_scope_v1,bigint,uuid,text,bigint),
 change_ledger.private_writer_finish_barrier_v1(
  change_ledger.private_writer_barrier_snapshot_v1,text,text,bigint)
 TO business_ai_private_writer;
-- Keep evidence-ingest EXECUTE withheld until certificate-mapped identity isolation from the
-- writer process, authenticated build provenance, and the cross-tenant disclosure boundary pass
-- independent database/security review. Schema/type USAGE alone grants no table or function DML.
GRANT EXECUTE ON FUNCTION change_ledger.verify_inconclusive_v1(text,text,uuid,uuid) TO worker_role;

    $body$;
 END IF;
END $mig$;
COMMIT;
