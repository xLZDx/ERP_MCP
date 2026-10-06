"""Verify production PostgreSQL role grants against a disposable CI database."""

from __future__ import annotations

import asyncio
import os

import asyncpg

CRUD = ("SELECT", "INSERT", "UPDATE", "DELETE")


def p(select=False, insert=False, update=False, delete=False):
    return dict(zip(CRUD, (select, insert, update, delete), strict=True))


READ_POLICY_TABLES = (
    "bag.business_roles",
    "bag.business_role_capabilities",
    "bag.business_role_assignments",
    "bag.capability_overrides",
)

EXPECTED = {
    "business_ai_app": {
        "bag.sources": p(select=True),
        "bag.access_grants": p(select=True),
        "bag.companies": p(select=True),
        "bag.audit_events": p(select=True, insert=True),
        "bag.source_capabilities": p(select=True, insert=True, update=True),
        "bag.semantic_profiles": p(select=True),
        "bag.semantic_mappings": p(select=True),
        "bag.semantic_profile_events": p(select=True),
        "bag.platform_role_bindings": p(select=True),
        "bag.company_scope_mappings": p(),
        "bag.admin_audit_events": p(),
        "bag.admin_idempotency": p(),
        **{table: p(select=True) for table in READ_POLICY_TABLES},
    },
    "business_ai_admin": {
        "bag.sources": p(select=True, insert=True, update=True),
        "bag.access_grants": p(select=True, insert=True, update=True),
        "bag.companies": p(select=True, insert=True, update=True),
        "bag.audit_events": p(select=True),
        "bag.source_capabilities": p(select=True),
        "bag.semantic_profiles": p(select=True, insert=True, update=True),
        "bag.semantic_mappings": p(select=True, insert=True, update=True),
        "bag.semantic_profile_events": p(select=True, insert=True),
        "bag.platform_role_bindings": p(select=True, insert=True, update=True),
        "bag.company_scope_mappings": p(select=True, insert=True, update=True),
        "bag.admin_audit_events": p(),
        "bag.admin_idempotency": p(),
        **{
            table: p(select=True, insert=True, update=True)
            for table in READ_POLICY_TABLES
        },
    },
    "business_ai_control_api": {
        "bag.sources": p(select=True, insert=True, update=True),
        "bag.access_grants": p(select=True, insert=True, update=True),
        "bag.companies": p(select=True, insert=True, update=True),
        "bag.audit_events": p(select=True),
        "bag.source_capabilities": p(select=True),
        "bag.semantic_profiles": p(select=True, insert=True, update=True),
        "bag.semantic_mappings": p(select=True, insert=True, update=True),
        "bag.semantic_profile_events": p(select=True, insert=True),
        "bag.platform_role_bindings": p(select=True, insert=True, update=True),
        "bag.company_scope_mappings": p(select=True, insert=True, update=True),
        "bag.admin_audit_events": p(select=True, insert=True),
        "bag.admin_idempotency": p(select=True, insert=True, update=True),
        "bag.business_roles": p(select=True),
        "bag.business_role_capabilities": p(select=True),
        "bag.business_role_assignments": p(select=True, insert=True, update=True),
        "bag.capability_overrides": p(select=True, insert=True, update=True),
    },
}

COLUMN_EXPECTED = {
    ("business_ai_control_api", "bag.source_capabilities", "drift_status", "UPDATE"): True,
    (
        "business_ai_control_api",
        "bag.source_capabilities",
        "drift_acknowledged_at",
        "UPDATE",
    ): True,
}

TRUNCATE_EXPECTED = {
    ("business_ai_app", "bag.audit_events"): False,
    ("business_ai_app", "bag.admin_audit_events"): False,
    ("business_ai_control_api", "bag.admin_audit_events"): False,
    ("business_ai_control_api", "bag.audit_events"): False,
    ("business_ai_admin", "bag.audit_events"): False,
    ("business_ai_admin", "bag.admin_audit_events"): False,
}


async def main() -> None:
    dsn = os.environ.get("BAG_PRIVILEGE_TEST_DATABASE_URL")
    if not dsn:
        raise RuntimeError("BAG_PRIVILEGE_TEST_DATABASE_URL must target a disposable test DB")

    conn = await asyncpg.connect(dsn)
    try:
        failures = []
        for role, tables in EXPECTED.items():
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=$1)", role
            )
            if not exists:
                failures.append(f"missing role {role}")
                continue
            for table, privileges in tables.items():
                for privilege, expected in privileges.items():
                    actual = await conn.fetchval(
                        "SELECT has_table_privilege($1, $2, $3)",
                        role,
                        table,
                        privilege,
                    )
                    if actual is not expected:
                        failures.append(
                            f"{role} {privilege} {table}: expected {expected}, got {actual}"
                        )
        for (role, table, column, privilege), expected in COLUMN_EXPECTED.items():
            actual = await conn.fetchval(
                "SELECT has_column_privilege($1, $2, $3, $4)",
                role,
                table,
                column,
                privilege,
            )
            if actual is not expected:
                failures.append(
                    f"{role} {privilege} {table}.{column}: expected {expected}, got {actual}"
                )
        for (role, table), expected in TRUNCATE_EXPECTED.items():
            actual = await conn.fetchval(
                "SELECT has_table_privilege($1, $2, 'TRUNCATE')", role, table
            )
            if actual is not expected:
                failures.append(
                    f"{role} TRUNCATE {table}: expected {expected}, got {actual}"
                )
        if failures:
            raise RuntimeError("\n".join(failures))
        print("database role privilege policy: PASS")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
