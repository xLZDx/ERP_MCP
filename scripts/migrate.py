import asyncio
from pathlib import Path

import asyncpg

from business_ai_gateway.settings import Settings


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


async def main():
    settings = Settings()
    dsn = settings.migration_database_url
    if settings.environment == "production" and not dsn:
        raise RuntimeError(
            "production migration requires BAG_MIGRATION_DATABASE_URL"
        )
    dsn = dsn or settings.database_url

    migrations = sorted(Path("db/migrations").glob("*.sql"))
    if not migrations:
        raise RuntimeError("no SQL migrations found")

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT pg_advisory_lock(812347912341)")
        try:
            for path in migrations:
                version = int(path.name.split("_", 1)[0])
                if await _migration_applied(conn, version):
                    print(f"skipped {path} (already applied)")
                    continue
                await conn.execute(path.read_text(encoding="utf-8"))
                if not await _migration_applied(conn, version):
                    raise RuntimeError(f"migration {path} did not record its version")
                print(f"applied {path}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock(812347912341)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
