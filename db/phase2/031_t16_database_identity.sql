-- S13-T16-RUNTIME-DB-BINDING-01: bounded, read-only PostgreSQL target identity.
-- Candidate only; installation and runtime qualification are separate acceptance steps.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('031', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','028','029','030']) THEN
 EXECUTE $body$

DO $roles$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='ledger_owner')
    OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='business_ai_private_writer')
    OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='operator_role') THEN
  RAISE EXCEPTION 'T16_DATABASE_IDENTITY_REQUIRED_ROLE_MISSING';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='t16_database_identity_owner') THEN
  CREATE ROLE t16_database_identity_owner NOLOGIN INHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
 ELSIF EXISTS (SELECT 1 FROM pg_catalog.pg_roles
   WHERE rolname='t16_database_identity_owner'
     AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication OR NOT rolinherit)) THEN
  RAISE EXCEPTION 'T16_DATABASE_IDENTITY_OWNER_UNSAFE';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
   WHERE m.roleid=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname='t16_database_identity_owner')
      OR (m.member=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname='t16_database_identity_owner')
          AND m.roleid IS DISTINCT FROM
              (SELECT oid FROM pg_catalog.pg_roles WHERE rolname='pg_monitor'))) THEN
  RAISE EXCEPTION 'T16_DATABASE_IDENTITY_OWNER_MEMBERSHIP_UNSAFE';
 END IF;
 IF pg_catalog.pg_has_role('business_ai_private_writer','t16_database_identity_owner','MEMBER')
    OR pg_catalog.pg_has_role('operator_role','t16_database_identity_owner','MEMBER') THEN
  RAISE EXCEPTION 'T16_DATABASE_IDENTITY_RUNTIME_ROLE_MEMBERSHIP_UNSAFE';
 END IF;
END $roles$;

-- Only the non-login SECURITY DEFINER owner receives pg_monitor. Keep the membership
-- non-delegable while allowing the function owner to inherit the narrowly needed read access.
GRANT pg_monitor TO t16_database_identity_owner
 WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;
DO $owner_membership$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_catalog.pg_auth_members m
   WHERE m.roleid=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname='pg_monitor')
     AND m.member=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname='t16_database_identity_owner')
     AND NOT m.admin_option AND m.inherit_option AND m.set_option
 ) THEN
  RAISE EXCEPTION 'T16_DATABASE_IDENTITY_OWNER_MONITOR_MEMBERSHIP_UNSAFE';
 END IF;
END $owner_membership$;
GRANT USAGE, CREATE ON SCHEMA change_ledger TO t16_database_identity_owner;

CREATE FUNCTION change_ledger.t16_database_identity_v1()
RETURNS TABLE(system_identifier bigint, database_oid oid)
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
 SELECT (pg_catalog.pg_control_system()).system_identifier,
        d.oid
   FROM pg_catalog.pg_database AS d
  WHERE d.datname = pg_catalog.current_database()
$fn$;

ALTER FUNCTION change_ledger.t16_database_identity_v1() OWNER TO t16_database_identity_owner;
REVOKE CREATE ON SCHEMA change_ledger FROM t16_database_identity_owner;
REVOKE ALL ON FUNCTION change_ledger.t16_database_identity_v1() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION change_ledger.t16_database_identity_v1()
 TO business_ai_private_writer, operator_role;

-- Fail closed if an app role has inherited any monitoring privilege through role membership.
DO $membership$
BEGIN
 IF pg_catalog.pg_has_role('business_ai_private_writer','pg_monitor','MEMBER')
    OR pg_catalog.pg_has_role('operator_role','pg_monitor','MEMBER') THEN
  RAISE EXCEPTION 'T16_DATABASE_IDENTITY_RUNTIME_MONITOR_MEMBERSHIP_UNSAFE';
 END IF;
END $membership$;

 $body$;
 END IF;
END $mig$;
COMMIT;

