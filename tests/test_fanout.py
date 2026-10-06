from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import httpx
import pytest

from business_ai_gateway.fanout import FanoutExecutor, FanoutPolicyError
from business_ai_gateway.testbed.fake1c import create_app


@dataclass
class FakeSource:
    source_id: str
    client: httpx.AsyncClient


@pytest.mark.asyncio
async def test_fanout_authorizes_before_dispatch_and_preserves_partial_failures():
    source_ids = ["healthy", "timeout", "denied", "malformed", "upstream-403"]
    clients = {
        source_id: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app("json")),
            base_url=f"http://{source_id}.fake.test",
        )
        for source_id in source_ids
    }
    targets = [(source_id, uuid.uuid4()) for source_id in source_ids]
    executor = FanoutExecutor(
        max_sources=8,
        global_concurrency=3,
        per_source_concurrency=1,
        deadline_seconds=1,
        per_source_timeout_seconds=0.2,
        max_rows_per_source=1,
    )
    dispatched = []

    async def authorize(source_id, company_id):
        await asyncio.sleep(0)
        assert not dispatched, "adapter dispatch started before every ACL decision completed"
        if source_id == "denied":
            raise PermissionError("synthetic ACL deny")
        return FakeSource(source_id, clients[source_id])

    async def fetch(source):
        dispatched.append(source.source_id)
        if source.source_id == "timeout":
            await asyncio.sleep(0.5)
        if source.source_id == "malformed":
            return object()
        if source.source_id == "upstream-403":
            request = source.client.build_request("GET", "/missing")
            response = httpx.Response(403, request=request)
            response.raise_for_status()
        response = await source.client.get(
            "/odata/standard.odata/Catalog_Organizations",
            params={"$top": 5},
        )
        response.raise_for_status()
        return response.json()["d"]["results"]

    try:
        result = await executor.run(targets, authorize=authorize, fetch=fetch)
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()))

    assert [item["source_id"] for item in result["results"]] == source_ids
    assert result["requested_sources"] == 5
    assert result["successful_sources"] == 1, result["results"]
    assert result["failed_sources"] == 4
    assert result["complete"] is False
    assert [item["error_code"] for item in result["failures"]] == [
        "SOURCE_TIMEOUT",
        "ACCESS_DENIED",
        "MALFORMED_RESPONSE",
        "SOURCE_ERROR",
    ]
    denied = result["results"][2]
    assert denied["error_code"] == "ACCESS_DENIED"
    assert "denied" not in dispatched
    healthy = result["results"][0]
    assert healthy["rows_returned"] == 1
    assert healthy["truncated"] is True
    assert result["rows_returned"] == 1


@pytest.mark.asyncio
async def test_fanout_enforces_global_limit_and_source_cap_across_calls():
    executor = FanoutExecutor(
        max_sources=12,
        global_concurrency=3,
        per_source_concurrency=1,
        deadline_seconds=2,
        per_source_timeout_seconds=1,
    )
    company = uuid.uuid4()
    targets = [(f"source-{index}", uuid.uuid4()) for index in range(12)]
    active = 0
    peak = 0

    async def authorize(source_id, _company_id):
        return source_id

    async def fetch(source_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.005)
        active -= 1
        return [{"id": source_id}]

    await asyncio.gather(
        executor.run(targets, authorize=authorize, fetch=fetch),
        executor.run(targets, authorize=authorize, fetch=fetch),
    )
    assert peak <= 3

    with pytest.raises(FanoutPolicyError, match="at most 12") as exc:
        await executor.run([*targets, ("source-extra", company)], authorize=authorize, fetch=fetch)
    assert exc.value.code == "FANOUT_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_fanout_per_source_byte_limit_and_overall_deadline_are_explicit():
    executor = FanoutExecutor(
        max_sources=4,
        global_concurrency=2,
        per_source_concurrency=1,
        deadline_seconds=0.02,
        per_source_timeout_seconds=1,
        max_bytes_per_source=30,
    )
    targets = [("large", uuid.uuid4()), ("slow", uuid.uuid4())]

    async def authorize(source_id, _company_id):
        return source_id

    async def fetch(source_id):
        if source_id == "slow":
            await asyncio.sleep(0.2)
        return {"value": [], "payload": "x" * 128}

    result = await executor.run(targets, authorize=authorize, fetch=fetch)
    assert [item["error_code"] for item in result["failures"]] == [
        "SOURCE_RESPONSE_TOO_LARGE",
        "DEADLINE_EXCEEDED",
    ]


def test_fanout_rejects_duplicate_sources_before_authorization():
    executor = FanoutExecutor()
    company = uuid.uuid4()

    async def unused(*_args):
        pytest.fail("must reject duplicate source ids before callbacks")

    with pytest.raises(FanoutPolicyError) as exc:
        asyncio.run(
            executor.run(
                [("same", company), ("same", uuid.uuid4())],
                authorize=unused,
                fetch=unused,
            )
        )
    assert exc.value.code == "DUPLICATE_SOURCE"
