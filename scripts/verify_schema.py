from __future__ import annotations

import asyncpg

EXPECTED_TABLES = {
    "schema_migrations",
    "sources",
    "companies",
    "access_grants",
    "audit_events",
    "source_capabilities",
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

    history = await conn.fetchrow(
        """SELECT count(*) AS count, min(version) AS minimum, max(version) AS maximum,
                  bool_and(name IS NOT NULL AND checksum ~ '^[0-9a-f]{64}$') AS identified,
                  count(DISTINCT name) AS names
           FROM bag.schema_migrations"""
    )
    if (
        history["count"] != 13
        or history["minimum"] != 1
        or history["maximum"] != 13
        or not history["identified"]
        or history["names"] != 13
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
                                 'bag.semantic_mappings'::regclass)
                 AND NOT tgisinternal"""
        )
    }
    required_triggers = {
        "audit_events_no_update_delete",
        "admin_audit_events_no_update_delete",
        "semantic_mapping_change_invalidates_profile",
    }
    if missing_triggers := required_triggers - triggers:
        raise AssertionError(f"missing schema triggers: {sorted(missing_triggers)}")

    required_functions = (
        "bag.reject_audit_mutation()",
        "bag.reject_admin_audit_mutation()",
        "bag.invalidate_validated_profile_on_mapping_change()",
    )
    for signature in required_functions:
        if not await conn.fetchval("SELECT to_regprocedure($1) IS NOT NULL", signature):
            raise AssertionError(f"missing schema function: {signature}")

    for role in ("business_ai_app", "business_ai_admin", "business_ai_control_api"):
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role):
            raise AssertionError(f"required database role is missing: {role}")

    privilege_checks = {
        "control_can_insert_admin_audit": ("business_ai_control_api", "bag.admin_audit_events", "INSERT", True),
        "control_cannot_truncate_admin_audit": ("business_ai_control_api", "bag.admin_audit_events", "TRUNCATE", False),
        "app_cannot_mutate_admin_audit": ("business_ai_app", "bag.admin_audit_events", "INSERT,UPDATE,DELETE,TRUNCATE", False),
        "app_cannot_read_candidate_scope_mappings": ("business_ai_app", "bag.company_scope_mappings", "SELECT", False),
    }
    for label, (role, table, privilege, expected) in privilege_checks.items():
        actual = await conn.fetchval(
            "SELECT has_table_privilege($1,$2,$3)", role, table, privilege
        )
        if actual is not expected:
            raise AssertionError(f"database privilege mismatch {label}: {actual!r}")
