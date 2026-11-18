"""Read-only, bounded service adapter for the authenticated S17 workbench."""
from __future__ import annotations

import asyncio
from uuid import UUID

import asyncpg

from ._common import Scope
from .sql_ledger import SqlChangeLedger


class WorkbenchLedgerReader:
    """Expose only the existing auditor-scoped change-list and status projections."""

    def __init__(self, database_url: str):
        if (not isinstance(database_url, str)
                or not database_url.startswith(("postgresql://", "postgres://"))):
            raise ValueError("CHANGE_LEDGER_DATABASE_URL_INVALID")
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        if self._pool is not None:
            return
        pool = await asyncpg.create_pool(
            dsn=self._database_url,
            min_size=1,
            max_size=4,
            timeout=10,
            command_timeout=15,
            max_inactive_connection_lifetime=300,
        )
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('SET LOCAL ROLE "auditor_role"')
                    if await conn.fetchval("SELECT current_user::text") != "auditor_role":
                        raise RuntimeError("CHANGE_LEDGER_READER_NOT_READY")
                    ready = await conn.fetchval(
                        """SELECT pg_catalog.to_regprocedure(
                            'change_ledger.list_inflight(text,text,integer,integer)') IS NOT NULL
                          AND pg_catalog.to_regprocedure(
                            'change_ledger.operator_status(text,text,uuid)') IS NOT NULL
                          AND pg_catalog.has_function_privilege(
                            current_user,
                            'change_ledger.list_inflight(text,text,integer,integer)', 'EXECUTE')
                          AND pg_catalog.has_function_privilege(
                            current_user,
                            'change_ledger.operator_status(text,text,uuid)', 'EXECUTE')"""
                    )
            if ready is not True:
                raise RuntimeError("CHANGE_LEDGER_READER_NOT_READY")
        except asyncio.CancelledError:
            await pool.close()
            raise
        except Exception:
            await pool.close()
            raise RuntimeError("CHANGE_LEDGER_READER_NOT_READY") from None
        self._pool = pool

    async def ready(self) -> bool:
        if self._pool is None:
            return False
        try:
            return await self._pool.fetchval("SELECT 1") == 1
        except Exception:
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def list_inflight(self, scope: Scope, *, limit: int, offset: int) -> list[dict]:
        if self._pool is None:
            raise RuntimeError("CHANGE_LEDGER_READER_NOT_STARTED")
        async with self._pool.acquire() as conn:
            ledger = SqlChangeLedger(conn, actors={"auditor": "auditor_role"})
            return await ledger.list_inflight(scope, limit, offset, as_class="auditor")

    async def operator_status(self, scope: Scope, change_id: UUID) -> dict:
        if self._pool is None:
            raise RuntimeError("CHANGE_LEDGER_READER_NOT_STARTED")
        async with self._pool.acquire() as conn:
            ledger = SqlChangeLedger(conn, actors={"auditor": "auditor_role"})
            return await ledger.operator_status(scope, change_id, as_class="auditor")
