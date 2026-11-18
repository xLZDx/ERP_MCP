from __future__ import annotations

import asyncpg

from business_ai_gateway.db import SCHEMA_VERSION

EXPECTED_TABLES = {
    "schema_migrations",
    "sources",
    "companies",
    "access_grants",
    "audit_events",
    "source_capabilities",
    "capability_observations",
    "semantic_profiles",
    "semantic_mappings",
    "semantic_profile_events",
    "platform_role_bindings",
    "admin_audit_events",
    "admin_idempotency",
    "business_roles",
    "business_role_capabilities",
    "business_role_assignments",
    "capability_overrides",
    "company_scope_mappings",
}


async def verify_schema(conn: asyncpg.Connection) -> None:
    tables = set(
        await conn.fetch(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema='bag' AND table_type='BASE TABLE'"""
        )
    )
    table_names = {row["table_name"] for row in tables}
    missing = EXPECTED_TABLES - table_names
    if missing:
        raise AssertionError(f"missing schema tables: {sorted(missing)}")

    required_columns = {
        ("capability_observations", "source_row_version"),
        ("source_capabilities", "accepted_observation_id"),
    }
    actual_columns = {
        (row["table_name"], row["column_name"])
        for row in await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='bag'"
        )
    }
    if missing_columns := required_columns - actual_columns:
        raise AssertionError(f"missing capability observation columns: {sorted(missing_columns)}")

    history = await conn.fetchrow(
        """SELECT count(*) AS count, min(version) AS minimum, max(version) AS maximum,
                  bool_and(name IS NOT NULL AND checksum ~ '^[0-9a-f]{64}$') AS identified,
                  count(DISTINCT name) AS names
           FROM bag.schema_migrations"""
    )
    if (
        history["count"] != SCHEMA_VERSION
        or history["minimum"] != 1
        or history["maximum"] != SCHEMA_VERSION
        or not history["identified"]
        or history["names"] != SCHEMA_VERSION
    ):
        raise AssertionError(f"schema migration identity is incomplete: {dict(history)}")

    constraints = {
        row["conname"]
        for row in await conn.fetch(
            """SELECT conname FROM pg_constraint
               WHERE connamespace='bag'::regnamespace"""
        )
    }
    required_constraints = {
        "schema_migrations_checksum_format_check",
        "platform_role_bindings_scope_check",
        "semantic_mappings_confirmed_confidence_check",
        "source_capabilities_drift_status_check",
        "capability_observations_source_row_version_check",
        "source_capabilities_accepted_observation_id_check",
    }
    if missing_constraints := required_constraints - constraints:
        raise AssertionError(f"missing schema constraints: {sorted(missing_constraints)}")

    indexes = {
        row["relname"]
        for row in await conn.fetch(
            """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='bag' AND c.relkind='i'"""
        )
    }
    required_indexes = {
        "platform_role_bindings_active_uq",
        "admin_audit_time_idx",
        "schema_migrations_name_uq",
    }
    if missing_indexes := required_indexes - indexes:
        raise AssertionError(f"missing schema indexes: {sorted(missing_indexes)}")

    triggers = {
        row["tgname"]
        for row in await conn.fetch(
            """SELECT tgname FROM pg_trigger
               WHERE tgrelid IN ('bag.audit_events'::regclass,
                                 'bag.admin_audit_events'::regclass,
                                 'bag.semantic_mappings'::regclass,
                                 'bag.sources'::regclass)
                 AND NOT tgisinternal"""
        )
    }
    required_triggers = {
        "audit_events_no_update_delete",
        "admin_audit_events_no_update_delete",
        "semantic_mapping_change_invalidates_profile",
        "sources_row_version_bump",
    }
    if missing_triggers := required_triggers - triggers:
        raise AssertionError(f"missing schema triggers: {sorted(missing_triggers)}")

    required_functions = (
        "bag.reject_audit_mutation()",
        "bag.reject_admin_audit_mutation()",
        "bag.invalidate_validated_profile_on_mapping_change()",
        "bag.record_capability_observation(text,uuid,bigint,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)",
        "bag.accept_capability_observation(text,uuid,bigint)",
        "bag.read_accepted_capability_observation(text,uuid,bigint)",
        "bag.bump_source_row_version()",
    )
    for signature in required_functions:
        if not await conn.fetchval("SELECT to_regprocedure($1) IS NOT NULL", signature):
            raise AssertionError(f"missing schema function: {signature}")

    for role in (
        "business_ai_app", "business_ai_admin", "business_ai_control_api",
        "business_ai_capability_writer", "business_ai_capability_acceptor",
    ):
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
            raise AssertionError(f"required database role is missing: {role}")
    for role in ("business_ai_capability_writer", "business_ai_capability_acceptor"):
        if await conn.fetchval("SELECT rolcanlogin FROM pg_roles WHERE rolname=$1", role):
            raise AssertionError(f"capability authority group role must be NOLOGIN: {role}")
    capability_functions = {
        "record": "bag.record_capability_observation(text,uuid,bigint,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)",
        "accept": "bag.accept_capability_observation(text,uuid,bigint)",
        "read_accepted": "bag.read_accepted_capability_observation(text,uuid,bigint)",
    }
    function_oids = {
        name: await conn.fetchval("SELECT to_regprocedure($1)::oid", signature)
        for name, signature in capability_functions.items()
    }
    for name, function_oid in function_oids.items():
        if await conn.fetchval(
            """SELECT EXISTS (
                   SELECT 1 FROM pg_proc p
                   CROSS JOIN LATERAL aclexplode(
                       COALESCE(p.proacl, acldefault('f', p.proowner))
                   ) a
                   WHERE p.oid=$1 AND a.grantee=0 AND a.privilege_type='EXECUTE'
               )""",
            function_oid,
        ):
            raise AssertionError(f"PUBLIC must not execute capability {name} function")

    expected_functions = {
        "business_ai_app": (False, False, True),
        "business_ai_admin": (False, False, False),
        "business_ai_control_api": (False, False, False),
        "business_ai_capability_writer": (True, False, False),
        "business_ai_capability_acceptor": (False, True, False),
    }
    for role, (can_record, can_accept, can_read_accepted) in expected_functions.items():
        actual_record = await conn.fetchval(
            "SELECT has_function_privilege($1::name,$2::oid,'EXECUTE')",
            role, function_oids["record"],
        )
        actual_accept = await conn.fetchval(
            "SELECT has_function_privilege($1::name,$2::oid,'EXECUTE')",
            role, function_oids["accept"],
        )
        actual_read_accepted = await conn.fetchval(
            "SELECT has_function_privilege($1::name,$2::oid,'EXECUTE')",
            role, function_oids["read_accepted"],
        )
        if (actual_record, actual_accept, actual_read_accepted) != (
            can_record, can_accept, can_read_accepted
        ):
            raise AssertionError(
                f"capability function privilege mismatch for {role}: "
                f"record={actual_record}, accept={actual_accept}, "
                f"read_accepted={actual_read_accepted}"
            )
    for role in ("business_ai_app", "business_ai_admin", "business_ai_control_api"):
        if await conn.fetchval(
            "SELECT pg_has_role($1::name,'business_ai_capability_writer','MEMBER') "
            "OR pg_has_role($1::name,'business_ai_capability_acceptor','MEMBER')",
            role,
        ):
            raise AssertionError(f"{role} must not inherit capability writer or acceptor roles")
    if await conn.fetchval(
        "SELECT pg_has_role('business_ai_capability_writer','business_ai_capability_acceptor','MEMBER') "
        "OR pg_has_role('business_ai_capability_acceptor','business_ai_capability_writer','MEMBER')"
    ):
        raise AssertionError("capability writer and acceptor roles must not inherit each other")

    privilege_checks = {
        "control_can_insert_admin_audit": ("business_ai_control_api", "bag.admin_audit_events", "INSERT", True),
        "control_cannot_truncate_admin_audit": ("business_ai_control_api", "bag.admin_audit_events", "TRUNCATE", False),
        "app_cannot_mutate_admin_audit": ("business_ai_app", "bag.admin_audit_events", "INSERT,UPDATE,DELETE,TRUNCATE", False),
        "app_cannot_read_candidate_scope_mappings": ("business_ai_app", "bag.company_scope_mappings", "SELECT", False),
        "app_cannot_update_trusted_capability_rows": ("business_ai_app", "bag.source_capabilities", "UPDATE", False),
        "writer_cannot_update_accepted_capability_rows": ("business_ai_capability_writer", "bag.source_capabilities", "UPDATE", False),
        "acceptor_cannot_update_accepted_capability_rows": ("business_ai_capability_acceptor", "bag.source_capabilities", "UPDATE", False),
    }
    for label, (role, table, privilege, expected) in privilege_checks.items():
        actual = await conn.fetchval(
            "SELECT has_table_privilege($1,$2,$3)", role, table, privilege
        )
        if actual is not expected:
            raise AssertionError(f"database privilege mismatch {label}: {actual!r}")

