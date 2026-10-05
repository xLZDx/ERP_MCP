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

    sql = Path("db/migrations/001_init.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT pg_advisory_lock(812347912341)")
        try:
            await conn.execute(sql)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(812347912341)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
