from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from scripts.migrate import load_migrations, migrate
from scripts.verify_schema import verify_schema


def _database_url(base_url: str, database: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, ""))


async def _with_database(base_url: str, *, upgrade_from_integration_v9: bool) -> None:
    name = f"acc_migration_{uuid.uuid4().hex[:16]}"
    maintenance_url = _database_url(base_url, "postgres")
    maintenance = await asyncpg.connect(maintenance_url)
    try:
        await maintenance.execute(f'CREATE DATABASE "{name}"')
        database_url = _database_url(base_url, name)
        conn = await asyncpg.connect(database_url)
        try:
            migrations = load_migrations()
            if upgrade_from_integration_v9:
                for migration in migrations[:9]:
                    await conn.execute(migration.sql)
                before = await conn.fetchval("SELECT max(version) FROM bag.schema_migrations")
                if before != 9:
                    raise AssertionError(f"integration fixture ended at v{before}, expected v9")
            await migrate(conn, migrations)
            await verify_schema(conn)
        finally:
            await conn.close()
    finally:
        await maintenance.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await maintenance.close()


async def _verify_legacy_admin_refusal(base_url: str) -> None:
    name = f"acc_legacy_admin_{uuid.uuid4().hex[:16]}"
    maintenance = await asyncpg.connect(_database_url(base_url, "postgres"))
    try:
        await maintenance.execute(f'CREATE DATABASE "{name}"')
        conn = await asyncpg.connect(_database_url(base_url, name))
        try:
            await conn.execute("CREATE SCHEMA bag")
            await conn.execute(
                "CREATE TABLE bag.schema_migrations(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            await conn.executemany(
                "INSERT INTO bag.schema_migrations(version) VALUES($1)",
                [(version,) for version in range(1, 12)],
            )
            try:
                await migrate(conn, load_migrations())
            except RuntimeError as exc:
                if "colliding version-only history" not in str(exc):
                    raise
            else:
                raise AssertionError("ambiguous legacy Admin history was accepted")
            columns = await conn.fetch(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema='bag' AND table_name='schema_migrations'"""
            )
            names = {row["column_name"] for row in columns}
            if {"name", "checksum"} & names:
                raise AssertionError("legacy Admin history was modified before refusal")
            if await conn.fetchval("SELECT max(version) FROM bag.schema_migrations") != 11:
                raise AssertionError("legacy Admin migration versions changed")
        finally:
            await conn.close()
    finally:
        await maintenance.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await maintenance.close()


async def _verify_future_version_refusal(base_url: str) -> None:
    name = f"acc_future_schema_{uuid.uuid4().hex[:16]}"
    maintenance = await asyncpg.connect(_database_url(base_url, "postgres"))
    try:
        await maintenance.execute(f'CREATE DATABASE "{name}"')
        conn = await asyncpg.connect(_database_url(base_url, name))
        try:
            await conn.execute("CREATE SCHEMA bag")
            await conn.execute(
                """CREATE TABLE bag.schema_migrations(
                     version integer PRIMARY KEY, name text NOT NULL,
                     checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
                   )"""
            )
            await conn.execute(
                "INSERT INTO bag.schema_migrations(version,name,checksum) VALUES($1,$2,$3)",
                15,
                "future",
                "0" * 64,
            )
            try:
                await migrate(conn, load_migrations())
            except RuntimeError as exc:
                if "unknown to this release" not in str(exc):
                    raise
            else:
                raise AssertionError("ahead-of-code schema version was accepted")
            tables = await conn.fetch(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema='bag' ORDER BY table_name"""
            )
            if [row["table_name"] for row in tables] != ["schema_migrations"]:
                raise AssertionError("future-version refusal mutated the schema")
            row = await conn.fetchrow("SELECT version,name,checksum FROM bag.schema_migrations")
            if (row["version"], row["name"], row["checksum"]) != (15, "future", "0" * 64):
                raise AssertionError("future-version refusal modified the migration ledger")
        finally:
            await conn.close()
    finally:
        await maintenance.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await maintenance.close()


async def main() -> None:
    base_url = os.environ.get("BAG_PRIVILEGE_TEST_DATABASE_URL")
    if not base_url:
        raise RuntimeError("BAG_PRIVILEGE_TEST_DATABASE_URL is required")
    await _with_database(base_url, upgrade_from_integration_v9=False)
    print("fresh PostgreSQL migration schema: PASS")
    await _with_database(base_url, upgrade_from_integration_v9=True)
    print("integration v9 -> Admin v14 PostgreSQL upgrade: PASS")
    await _verify_legacy_admin_refusal(base_url)
    print("ambiguous legacy Admin v11 refusal without DB changes: PASS")
    await _verify_future_version_refusal(base_url)
    print("ahead-of-code schema v15 refusal without DB changes: PASS")


if __name__ == "__main__":
    asyncio.run(main())
