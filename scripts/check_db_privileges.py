"""Verify production runtime/admin PostgreSQL grants against a disposable CI database."""

from __future__ import annotations

import asyncio
import os

import asyncpg

EXPECTED = {
    "business_ai_app": {
        "bag.sources": {"SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False},
        "bag.access_grants": {
            "SELECT": True,
            "INSERT": False,
            "UPDATE": False,
            "DELETE": False,
        },
        "bag.companies": {"SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False},
        "bag.audit_events": {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False},
        "bag.source_capabilities": {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": True,
            "DELETE": False,
        },
    },
    "business_ai_admin": {
        "bag.sources": {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False},
        "bag.access_grants": {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": True,
            "DELETE": False,
        },
        "bag.companies": {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False},
        "bag.audit_events": {
            "SELECT": True,
            "INSERT": False,
            "UPDATE": False,
            "DELETE": False,
        },
    },
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
        if failures:
            raise RuntimeError("\n".join(failures))
        print("database role privilege policy: PASS")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
