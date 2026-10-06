from __future__ import annotations

import asyncpg

SCHEMA_VERSION = 11


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def start(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                dsn=self.url,
                min_size=1,
                max_size=10,
                command_timeout=15,
                max_inactive_connection_lifetime=300,
            )

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("database not started")
        return self.pool

    async def ping(self) -> bool:
        return bool(await self.require_pool().fetchval("SELECT 1"))

    async def assert_schema(self):
        version = await self.require_pool().fetchval(
            "SELECT max(version) FROM bag.schema_migrations"
        )
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported or missing schema version: {version!r}; "
                f"expected {SCHEMA_VERSION}"
            )

    async def assert_control_api_role(self):
        row = await self.require_pool().fetchrow("""
            SELECT pg_has_role(current_user, 'business_ai_control_api', 'USAGE') AS control_member,
                   EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN (current_user, session_user)
                     AND (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls OR r.rolreplication)) AS elevated,
                   EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN ('business_ai_owner','business_ai_admin')
                     AND pg_has_role(session_user, r.oid, 'MEMBER')) AS privileged_member,
                   has_table_privilege(current_user, 'bag.admin_audit_events', 'UPDATE,DELETE') AS mutable_audit,
                   has_table_privilege(current_user, 'bag.sources', 'DELETE') AS can_delete,
                   has_table_privilege(current_user, 'bag.source_capabilities', 'UPDATE') AS broad_drift_update,
                   EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE n.nspname='bag' AND pg_has_role(session_user, c.relowner, 'MEMBER')) AS owns_schema_objects
        """)
        if not row["control_member"] or any(row[key] for key in (
            "elevated", "privileged_member", "mutable_audit", "can_delete", "broad_drift_update", "owns_schema_objects"
        )):
            raise RuntimeError("admin control database role violates least-privilege contract")
