from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from business_ai_gateway.db import SCHEMA_VERSION
from business_ai_gateway.settings import Settings

_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$")
_LOCK_ID = 812347912341


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str
    sql: str


def load_migrations(directory: Path = Path("db/migrations")) -> list[Migration]:
    migrations: list[Migration] = []
    names: set[str] = set()
    versions: set[int] = set()
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"invalid migration filename: {path.name}")
        version = int(match.group("version"))
        name = match.group("name")
        if version in versions:
            raise RuntimeError(f"duplicate migration version: {version:03d}")
        if name in names:
            raise RuntimeError(f"duplicate migration identity: {name}")
        versions.add(version)
        names.add(name)
        content = path.read_bytes()
        migrations.append(
            Migration(
                version=version,
                name=name,
                path=path,
                checksum=hashlib.sha256(content).hexdigest(),
                sql=content.decode("utf-8"),
            )
        )
    if not migrations:
        raise RuntimeError("no SQL migrations found")
    expected = list(range(1, SCHEMA_VERSION + 1))
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise RuntimeError(
            f"migration versions must be contiguous through SCHEMA_VERSION={SCHEMA_VERSION}; "
            f"found {actual}"
        )
    return migrations


async def _migration_applied(conn, version: int) -> bool:
    history_exists = await conn.fetchval(
        "SELECT to_regclass('bag.schema_migrations') IS NOT NULL"
    )
    if not history_exists:
        return False
    return bool(
        await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM bag.schema_migrations WHERE version=$1)",
            version,
        )
    )


async def _ensure_history_identity(conn) -> None:
    if not await conn.fetchval("SELECT to_regclass('bag.schema_migrations') IS NOT NULL"):
        return
    await conn.execute("ALTER TABLE bag.schema_migrations ADD COLUMN IF NOT EXISTS name text")
    await conn.execute("ALTER TABLE bag.schema_migrations ADD COLUMN IF NOT EXISTS checksum text")
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS schema_migrations_name_uq "
        "ON bag.schema_migrations(name) WHERE name IS NOT NULL"
    )
    await conn.execute(
        """DO $$ BEGIN
             IF NOT EXISTS (
               SELECT 1 FROM pg_constraint
               WHERE conrelid='bag.schema_migrations'::regclass
                 AND conname='schema_migrations_checksum_format_check'
             ) THEN
               ALTER TABLE bag.schema_migrations
                 ADD CONSTRAINT schema_migrations_checksum_format_check
                 CHECK (checksum IS NULL OR checksum ~ '^[0-9a-f]{64}$');
             END IF;
           END $$"""
    )


async def _prepare_history_identity(conn, migrations: list[Migration]) -> None:
    if not await conn.fetchval("SELECT to_regclass('bag.schema_migrations') IS NOT NULL"):
        return
    columns = {
        row["column_name"]
        for row in await conn.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='bag' AND table_name='schema_migrations'"""
        )
    }
    identity_columns = {"name", "checksum"}
    present = columns & identity_columns
    if present and present != identity_columns:
        raise RuntimeError("migration ledger has partial identity columns; manual repair required")
    if not present:
        rows = await conn.fetch("SELECT version FROM bag.schema_migrations ORDER BY version")
        versions = [int(row["version"]) for row in rows]
        if versions:
            maximum = max(versions)
            if maximum > 9:
                raise RuntimeError(
                    "legacy Admin development schema has colliding version-only history; "
                    "use the documented non-destructive remap procedure"
                )
            if versions != list(range(1, maximum + 1)):
                raise RuntimeError("legacy migration history is not contiguous; manual repair required")
            if maximum >= 8 and not await _verify_integration_legacy_signature(conn, maximum):
                raise RuntimeError(
                    "legacy migration v8/v9 does not match the integration lineage; "
                    "refusing to adopt ambiguous Admin history"
                )
    await _ensure_history_identity(conn)


async def _verify_integration_legacy_signature(conn, version: int) -> bool:
    confirmed_mapping = await conn.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM pg_constraint
             WHERE conrelid=to_regclass('bag.semantic_mappings')
               AND conname='semantic_mappings_confirmed_confidence_check'
           )"""
    )
    invalidation_trigger = await conn.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM pg_trigger
             WHERE tgrelid=to_regclass('bag.semantic_mappings')
               AND tgname='semantic_mapping_change_invalidates_profile'
               AND NOT tgisinternal
           )"""
    )
    invalidation_function = await conn.fetchval(
        """SELECT to_regprocedure('bag.invalidate_validated_profile_on_mapping_change()') IS NOT NULL"""
    )
    if not (confirmed_mapping and invalidation_trigger and invalidation_function):
        return False
    if version >= 9:
        return bool(
            await conn.fetchval(
                """SELECT EXISTS (
                     SELECT 1 FROM information_schema.columns
                     WHERE table_schema='bag' AND table_name='audit_events'
                       AND column_name='profile_fingerprint'
                   )"""
            )
        )
    return True


async def _adopt_legacy_history(conn, migrations: list[Migration]) -> None:
    rows = await conn.fetch(
        "SELECT version, name, checksum FROM bag.schema_migrations ORDER BY version"
    )
    if not rows:
        return
    has_metadata = [row["name"] is not None or row["checksum"] is not None for row in rows]
    if any(has_metadata):
        if not all(row["name"] is not None and row["checksum"] is not None for row in rows):
            raise RuntimeError("migration ledger has partial immutable identities; manual repair required")
        return

    applied = [int(row["version"]) for row in rows]
    maximum = max(applied)
    if applied != list(range(1, maximum + 1)):
        raise RuntimeError("legacy migration history is not contiguous; manual repair required")
    if maximum > 9:
        raise RuntimeError(
            "legacy Admin development schema has colliding version-only history; "
            "use the documented non-destructive remap procedure"
        )
    if maximum >= 8 and not await _verify_integration_legacy_signature(conn, maximum):
        raise RuntimeError(
            "legacy migration v8/v9 does not match the integration lineage; "
            "refusing to adopt ambiguous Admin history"
        )

    by_version = {migration.version: migration for migration in migrations}
    async with conn.transaction():
        for version in applied:
            migration = by_version.get(version)
            if migration is None:
                raise RuntimeError(f"no migration file for legacy version {version}")
            await conn.execute(
                "UPDATE bag.schema_migrations SET name=$2, checksum=$3 WHERE version=$1",
                version,
                migration.name,
                migration.checksum,
            )


async def _assert_history_identity(conn, migration: Migration) -> None:
    row = await conn.fetchrow(
        "SELECT name, checksum FROM bag.schema_migrations WHERE version=$1",
        migration.version,
    )
    if row is None:
        return
    if row["name"] != migration.name or row["checksum"] != migration.checksum:
        raise RuntimeError(
            f"applied migration {migration.version:03d} identity/checksum changed; "
            "manual migration review required"
        )


async def _preflight_history(conn, migrations: list[Migration]) -> None:
    """Reject unknown or changed ledger history before performing any DDL."""
    if not await conn.fetchval("SELECT to_regclass('bag.schema_migrations') IS NOT NULL"):
        return
    columns = {
        row["column_name"]
        for row in await conn.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='bag' AND table_name='schema_migrations'"""
        )
    }
    rows = await conn.fetch("SELECT * FROM bag.schema_migrations ORDER BY version")
    versions = [int(row["version"]) for row in rows]
    if not versions:
        return
    by_version = {migration.version: migration for migration in migrations}
    unknown = [version for version in versions if version not in by_version]
    if unknown:
        raise RuntimeError(
            f"database schema history contains versions unknown to this release: {unknown}"
        )
    if versions != list(range(1, max(versions) + 1)):
        raise RuntimeError("migration history is not contiguous; refusing before schema changes")

    identity_columns = {"name", "checksum"}
    present = columns & identity_columns
    if present and present != identity_columns:
        raise RuntimeError("migration ledger has partial identity columns; manual repair required")
    if not present:
        if max(versions) > 9:
            raise RuntimeError(
                "legacy Admin development schema has colliding version-only history; "
                "follow the non-destructive legacy recovery runbook"
            )
        if max(versions) >= 8 and not await _verify_integration_legacy_signature(
            conn, max(versions)
        ):
            raise RuntimeError(
                "legacy migration v8/v9 does not match the integration lineage; "
                "refusing to adopt ambiguous Admin history"
            )
        return

    for row in rows:
        migration = by_version[int(row["version"])]
        if row["name"] is None or row["checksum"] is None:
            raise RuntimeError("migration ledger has partial immutable identities; manual repair required")
        if row["name"] != migration.name or row["checksum"] != migration.checksum:
            raise RuntimeError(
                f"applied migration {migration.version:03d} identity/checksum changed; "
                "manual migration review required"
            )


async def _apply(conn, migration: Migration) -> None:
    if migration.version <= 9:
        # The frozen integration migrations own their historical BEGIN/COMMIT and version INSERT.
        await conn.execute(migration.sql)
        await _ensure_history_identity(conn)
        await conn.execute(
            "UPDATE bag.schema_migrations SET name=$2, checksum=$3 WHERE version=$1",
            migration.version,
            migration.name,
            migration.checksum,
        )
        return
    async with conn.transaction():
        await conn.execute(migration.sql)
        await conn.execute(
            "INSERT INTO bag.schema_migrations(version, name, checksum) VALUES($1,$2,$3)",
            migration.version,
            migration.name,
            migration.checksum,
        )


async def migrate(conn, migrations: list[Migration]) -> None:
    await conn.execute(f"SELECT pg_advisory_lock({_LOCK_ID})")
    try:
        if await conn.fetchval("SELECT to_regclass('bag.schema_migrations') IS NOT NULL"):
            await _preflight_history(conn, migrations)
            await _prepare_history_identity(conn, migrations)
            await _adopt_legacy_history(conn, migrations)
        for migration in migrations:
            if await _migration_applied(conn, migration.version):
                await _assert_history_identity(conn, migration)
                print(f"verified {migration.version:03d}_{migration.name}")
                continue
            for prior in migrations:
                if prior.version >= migration.version:
                    break
                if not await _migration_applied(conn, prior.version):
                    raise RuntimeError(
                        f"cannot apply migration {migration.version:03d} before "
                        f"{prior.version:03d}"
                    )
                await _assert_history_identity(conn, prior)
            await _apply(conn, migration)
            if not await _migration_applied(conn, migration.version):
                raise RuntimeError(f"migration {migration.version:03d} did not record its version")
            await _assert_history_identity(conn, migration)
            print(f"applied {migration.version:03d}_{migration.name}")
    finally:
        await conn.execute(f"SELECT pg_advisory_unlock({_LOCK_ID})")


async def main():
    settings = Settings()
    dsn = settings.migration_database_url
    if settings.environment == "production" and not dsn:
        raise RuntimeError("production migration requires BAG_MIGRATION_DATABASE_URL")
    dsn = dsn or settings.database_url
    migrations = load_migrations()
    conn = await asyncpg.connect(dsn)
    try:
        await migrate(conn, migrations)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
