"""Prepare the disposable Fake1C stack for a no-OAuth ChatGPT tunnel demo.

This script is intentionally test-only. It refuses to touch non-test environments,
non-synthetic sources, or any source other than the dedicated Fake1C E2E source.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg

from business_ai_gateway.settings import Settings

SUBJECT = "development-local"
DEFAULT_SOURCE_ID = "fake1c-e2e"


async def main() -> None:
    settings = Settings()
    source_id = os.getenv("ERP_MCP_CHATGPT_SOURCE_ID", DEFAULT_SOURCE_ID)

    if settings.environment != "test" or not settings.synthetic_fixture_profiles_file:
        raise RuntimeError("CHATGPT_LOCAL_PREPARE_REQUIRES_SYNTHETIC_TEST_ENVIRONMENT")
    if source_id != DEFAULT_SOURCE_ID:
        raise RuntimeError("CHATGPT_LOCAL_PREPARE_REFUSES_NON_FAKE1C_SOURCE")

    database_url = settings.admin_database_url or settings.database_url
    conn = await asyncpg.connect(database_url)
    try:
        source = await conn.fetchrow(
            "SELECT source_id, tags, read_only, enabled FROM bag.sources WHERE source_id=$1",
            source_id,
        )
        if source is None:
            raise RuntimeError("CHATGPT_LOCAL_PREPARE_SOURCE_MISSING")
        if "synthetic-fixture" not in tuple(source["tags"] or ()):
            raise RuntimeError("CHATGPT_LOCAL_PREPARE_SOURCE_NOT_SYNTHETIC")
        if not source["read_only"] or not source["enabled"]:
            raise RuntimeError("CHATGPT_LOCAL_PREPARE_SOURCE_NOT_SAFE")

        existing = await conn.fetchval(
            """
            SELECT grant_id FROM bag.access_grants
            WHERE principal_kind='subject'
              AND principal_id=$1
              AND source_id=$2
              AND company_id IS NULL
              AND effect='allow'
              AND revoked_at IS NULL
            ORDER BY created_at
            LIMIT 1
            """,
            SUBJECT,
            source_id,
        )
        if existing is None:
            grant_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO bag.access_grants(
                    grant_id, principal_kind, principal_id, source_id,
                    all_sources, company_id, effect
                )
                VALUES($1,'subject',$2,$3,false,NULL,'allow')
                """,
                grant_id,
                SUBJECT,
                source_id,
            )
            print("chatgpt local synthetic grant: created")
        else:
            print("chatgpt local synthetic grant: already present")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
