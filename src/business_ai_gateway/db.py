from __future__ import annotations

import asyncpg

SCHEMA_VERSION = 3


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
