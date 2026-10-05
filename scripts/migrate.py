import asyncio
from pathlib import Path

import asyncpg

from business_ai_gateway.settings import Settings


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
                await conn.execute(path.read_text(encoding="utf-8"))
                print(f"applied {path}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock(812347912341)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
