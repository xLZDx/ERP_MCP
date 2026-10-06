from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
import uuid

import asyncpg

from business_ai_gateway.db import Database
from business_ai_gateway.principal import Principal
from business_ai_gateway.registry import Registry


async def run() -> dict:
    database_url = os.environ["BAG_PRIVILEGE_TEST_DATABASE_URL"]
    token = uuid.uuid4().hex
    source_ids = [f"load-{token}-{index}" for index in range(150)]
    company_ids = [uuid.uuid4() for _ in source_ids]
    principal = Principal(
        subject=f"load-user-{token}",
        client_id="synthetic-acl-load-drill",
        scopes=frozenset({"onec:read"}),
        groups=frozenset(),
        claims={},
    )
    conn = await asyncpg.connect(database_url)
    database = Database(database_url)
    try:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
                VALUES($1, 'onec', 'onec_odata', $2, $3)
                """,
                [
                    (
                        source_id,
                        f"Synthetic load source {index}",
                        f"https://load-{index}.example.test/odata",
                    )
                    for index, source_id in enumerate(source_ids)
                ],
            )
            await conn.executemany(
                """
                INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
                VALUES($1, $2, $3, $4)
                """,
                [
                    (company_id, source_id, f"ref-{index}", f"Synthetic company {index}")
                    for index, (source_id, company_id) in enumerate(
                        zip(source_ids, company_ids, strict=True)
                    )
                ],
            )
        await database.start()
        registry = Registry(database, production=True)
        results = []
        previous_size = 0
        for size in (30, 50, 100, 150):
            async with conn.transaction():
                await conn.executemany(
                    """
                    INSERT INTO bag.access_grants(
                      grant_id, principal_kind, principal_id, source_id, company_id, effect
                    ) VALUES($1, 'subject', $2, $3, $4, 'allow')
                    """,
                    [
                        (uuid.uuid4(), principal.subject, source_ids[index], company_ids[index])
                        for index in range(previous_size, size)
                    ],
                )

            async def request(expected_sources: int = size) -> float:
                started = time.perf_counter()
                allowed = await registry.list_allowed(principal)
                assert len(allowed) == expected_sources, (
                    f"expected {expected_sources} sources, got {len(allowed)}"
                )
                return (time.perf_counter() - started) * 1000

            await asyncio.gather(*(registry.list_allowed(principal) for _ in range(3)))
            started = time.perf_counter()
            latencies = await asyncio.gather(*(request() for _ in range(32)))
            elapsed_ms = (time.perf_counter() - started) * 1000
            results.append(
                {
                    "registered_sources": size,
                    "requests": len(latencies),
                    "max_in_flight": 10,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "mean_ms": round(statistics.mean(latencies), 2),
                    "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
                    "authorization_result": "PASS",
                }
            )
            previous_size = size
        return {
            "drill": "synthetic_postgres_acl_list_allowed",
            "real_1c_called": False,
            "pool_max_size": 10,
            "results": results,
        }
    finally:
        await database.close()
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM bag.access_grants WHERE principal_id=$1", principal.subject
            )
            await conn.execute(
                "DELETE FROM bag.companies WHERE source_id = ANY($1::text[])", source_ids
            )
            await conn.execute(
                "DELETE FROM bag.sources WHERE source_id = ANY($1::text[])", source_ids
            )
        await conn.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
