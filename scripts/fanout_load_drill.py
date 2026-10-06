"""Synthetic gateway→PostgreSQL ACL→Redis rate limit→OData adapter→Fake1C load drill."""

from __future__ import annotations

import asyncio
import json
import os
import time
import tracemalloc
import uuid
from collections import Counter
from dataclasses import dataclass

import asyncpg
import httpx
from redis.asyncio import Redis

from business_ai_gateway.adapters.onec.client import OneCReadClient
from business_ai_gateway.db import Database
from business_ai_gateway.fanout import FanoutExecutor
from business_ai_gateway.principal import Principal
from business_ai_gateway.rate_limit import RateLimiter
from business_ai_gateway.registry import Registry
from business_ai_gateway.testbed.fake1c import create_app


@dataclass
class AuthorizedSource:
    source: object
    latency_ms: float


class ObservedPool:
    def __init__(self, pool):
        self.pool = pool
        self.acquire_wait_ms: list[float] = []
        self.checked_out = 0
        self.peak_checked_out = 0

    def __getattr__(self, name):
        return getattr(self.pool, name)

    async def fetchrow(self, *args, **kwargs):
        started = time.perf_counter()
        async with self.pool.acquire() as connection:
            self.acquire_wait_ms.append((time.perf_counter() - started) * 1000)
            self.checked_out += 1
            self.peak_checked_out = max(self.peak_checked_out, self.checked_out)
            try:
                return await connection.fetchrow(*args, **kwargs)
            finally:
                self.checked_out -= 1


class ObservedDatabase:
    def __init__(self, pool):
        self.pool = pool

    def require_pool(self):
        return self.pool


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return round(ordered[index], 3)


async def run() -> dict:
    database_url = os.environ["BAG_PRIVILEGE_TEST_DATABASE_URL"]
    redis_url = os.getenv("BAG_REDIS_URL", "redis://localhost:6379/0")
    token = uuid.uuid4().hex
    source_ids = [f"fanout-{token}-{index}" for index in range(150)]
    company_ids = [uuid.uuid4() for _ in source_ids]
    subject = f"fanout-user-{token}"
    deny_source_id = source_ids[0]
    timeout_source_id = source_ids[1]
    malformed_source_id = source_ids[2]
    db = Database(database_url)
    connection = await asyncpg.connect(database_url)
    redis = Redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
    transport = httpx.ASGITransport(app=create_app("json"))
    odata = OneCReadClient(
        timeout_seconds=2,
        max_response_bytes=1_000_000,
        transport=transport,
    )
    principal = Principal(
        subject=subject,
        client_id="synthetic-fanout-load",
        scopes=frozenset({"onec:read"}),
        groups=frozenset(),
        claims={},
    )
    limiter = RateLimiter(redis, per_minute=500)
    active = 0
    peak_active = 0
    adapter_latencies: list[float] = []
    authorization_latencies: list[float] = []
    rate_limit_latencies: list[float] = []
    batch_latencies: list[float] = []
    source_outcomes: Counter[str] = Counter()
    denied_dispatches = 0
    truncations = 0
    denied_requests = 0
    tracemalloc.start()
    try:
        await redis.ping()
        async with connection.transaction():
            await connection.executemany(
                """
                INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
                VALUES($1, 'onec', 'onec_odata', $2, $3)
                """,
                [
                    (
                        source_id,
                        f"Synthetic fan-out source {index}",
                        f"http://source-{index}.fake.test/odata",
                    )
                    for index, source_id in enumerate(source_ids)
                ],
            )
            await connection.executemany(
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
            grants = [
                (uuid.uuid4(), subject, source_id, company_id, "allow")
                for source_id, company_id in zip(source_ids, company_ids, strict=True)
            ]
            grants.append((uuid.uuid4(), subject, deny_source_id, company_ids[0], "deny"))
            await connection.executemany(
                """
                INSERT INTO bag.access_grants(
                  grant_id, principal_kind, principal_id, source_id, company_id, effect
                ) VALUES($1, 'subject', $2, $3, $4, $5)
                """,
                grants,
            )
        await db.start()
        observed_pool = ObservedPool(db.require_pool())
        registry = Registry(ObservedDatabase(observed_pool), production=False)
        fanout = FanoutExecutor(
            max_sources=16,
            global_concurrency=20,
            per_source_concurrency=2,
            deadline_seconds=10,
            per_source_timeout_seconds=0.05,
            max_rows_per_source=1,
            max_bytes_per_source=1_000_000,
        )
        per_source_ms: list[float] = []

        async def authorize(source_id: str, company_id: uuid.UUID) -> AuthorizedSource:
            started = time.perf_counter()
            source = await registry.require_source_for_company(principal, source_id, company_id)
            rate_limit_started = time.perf_counter()
            await limiter.check(
                subject=principal.subject,
                source_id=source_id,
                tool="synthetic_fanout_load",
            )
            rate_limit_latencies.append((time.perf_counter() - rate_limit_started) * 1000)
            elapsed = (time.perf_counter() - started) * 1000
            authorization_latencies.append(elapsed)
            return AuthorizedSource(source=source, latency_ms=elapsed)

        async def fetch(authorized: AuthorizedSource):
            nonlocal active, peak_active, denied_dispatches
            source = authorized.source
            if source.id == deny_source_id:
                denied_dispatches += 1
            active += 1
            peak_active = max(peak_active, active)
            started = time.perf_counter()
            try:
                if source.id == timeout_source_id:
                    await asyncio.sleep(0.2)
                if source.id == malformed_source_id:
                    return object()
                payload = await odata.get_bytes(
                    source,
                    "standard.odata/Catalog_Organizations",
                    username=None,
                    password=None,
                    params={"$top": 10},
                )
                return json.loads(payload)["d"]["results"]
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                per_source_ms.append(elapsed)
                adapter_latencies.append(elapsed)
                active -= 1

        tracemalloc.reset_peak()
        scenario_results = []
        for registered_count in (30, 50, 100, 150):
            stage_started = time.perf_counter()
            stage_results = []
            targets = list(
                zip(source_ids[:registered_count], company_ids[:registered_count], strict=True)
            )
            # The scheduling window is always <=16; portfolio size never becomes a single unbounded wave.
            for offset in range(0, registered_count, fanout.max_sources):
                batch = targets[offset : offset + fanout.max_sources]
                stage_results.append(await fanout.run(batch, authorize=authorize, fetch=fetch))
            stage_ms = (time.perf_counter() - stage_started) * 1000
            outcomes = [item for batch in stage_results for item in batch["results"]]
            stage_errors = {
                item["source_id"]: item.get("error_code")
                for item in outcomes
                if item["outcome"] != "SUCCESS"
            }
            expected_errors = {
                deny_source_id: "ACCESS_DENIED",
                timeout_source_id: "SOURCE_TIMEOUT",
                malformed_source_id: "MALFORMED_RESPONSE",
            }
            if any(
                stage_errors.get(source_id) != code for source_id, code in expected_errors.items()
            ):
                raise AssertionError("synthetic partial-failure contract did not hold")
            if set(stage_errors) != set(expected_errors):
                raise AssertionError("unexpected synthetic source failure in load scenario")
            denied_requests += sum(code == "ACCESS_DENIED" for code in stage_errors.values())
            for item in outcomes:
                source_outcomes[item["outcome"]] += 1
                if item.get("truncated"):
                    truncations += 1
            stage_latencies = [batch["duration_ms"] for batch in stage_results]
            batch_latencies.extend(stage_latencies)
            scenario_results.append(
                {
                    "registered_sources": registered_count,
                    "bounded_batches": len(stage_results),
                    "max_sources_per_batch": fanout.max_sources,
                    "source_outcomes": dict(Counter(item["outcome"] for item in outcomes)),
                    "elapsed_ms": round(stage_ms, 3),
                    "batch_p50_ms": percentile(stage_latencies, 0.50),
                    "batch_p95_ms": percentile(stage_latencies, 0.95),
                    "batch_p99_ms": percentile(stage_latencies, 0.99),
                    "throughput_sources_per_second": round(
                        registered_count / max(stage_ms / 1000, 0.001), 2
                    ),
                    "error_rate": round(
                        sum(item["outcome"] != "SUCCESS" for item in outcomes)
                        / max(len(outcomes), 1),
                        4,
                    ),
                    "peak_adapter_concurrency": peak_active,
                    "complete_failure_envelope": all(
                        "error_code" in item for item in outcomes if item["outcome"] != "SUCCESS"
                    ),
                }
            )
        _, memory_peak = tracemalloc.get_traced_memory()
        if denied_dispatches != 0 or peak_active > 20:
            raise AssertionError("ACL isolation or global concurrency limit was violated")
        pool = db.require_pool()
        return {
            "kind": "SYNTHETIC_GATEWAY_ACL_REDIS_ODATA_FAKE1C_LOAD",
            "real_1c_called": False,
            "registered_portfolio_sizes": [30, 50, 100, 150],
            "global_concurrency_limit": 20,
            "per_source_concurrency_limit": 2,
            "max_sources_per_fanout_request": 16,
            "db_pool_max_size": 10,
            "db_pool_size_observed": pool.get_size(),
            "db_pool_peak_checked_out": observed_pool.peak_checked_out,
            "db_pool_acquire_p50_ms": percentile(observed_pool.acquire_wait_ms, 0.50),
            "db_pool_acquire_p95_ms": percentile(observed_pool.acquire_wait_ms, 0.95),
            "redis_ping": "PASS",
            "denied_source_adapter_dispatches": denied_dispatches,
            "denied_source_requests": denied_requests,
            "authorization_p50_ms": percentile(authorization_latencies, 0.50),
            "authorization_p95_ms": percentile(authorization_latencies, 0.95),
            "redis_rate_limit_p50_ms": percentile(rate_limit_latencies, 0.50),
            "redis_rate_limit_p95_ms": percentile(rate_limit_latencies, 0.95),
            "adapter_p50_ms": percentile(adapter_latencies, 0.50),
            "adapter_p95_ms": percentile(adapter_latencies, 0.95),
            "batch_p50_ms": percentile(batch_latencies, 0.50),
            "batch_p95_ms": percentile(batch_latencies, 0.95),
            "batch_p99_ms": percentile(batch_latencies, 0.99),
            "peak_adapter_concurrency": peak_active,
            "max_response_rows_per_source": 1,
            "truncated_source_responses": truncations,
            "synthetic_peak_traced_memory_bytes": memory_peak,
            "outcomes_across_scenarios": dict(source_outcomes),
            "scenarios": scenario_results,
            "results": "PASS",
        }
    finally:
        tracemalloc.stop()
        await odata.close()
        await db.close()
        await redis.aclose()
        async with connection.transaction():
            await connection.execute("DELETE FROM bag.access_grants WHERE principal_id=$1", subject)
            await connection.execute(
                "DELETE FROM bag.companies WHERE source_id = ANY($1::text[])", source_ids
            )
            await connection.execute(
                "DELETE FROM bag.sources WHERE source_id = ANY($1::text[])", source_ids
            )
        await connection.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
