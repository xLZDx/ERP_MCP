"""Worker boundary checks for reserve-before-probe and exact reservation binding."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import asyncpg
import httpx
import pytest
from starlette.exceptions import HTTPException

from business_ai_gateway.compatibility import AdapterProfile, CompatibilityStatus, OneCCapabilities
from business_ai_gateway.models import Source

with patch.dict(os.environ, {
    "BAG_CAPABILITY_OBSERVATION_DATABASE_URL": "postgresql://test:test@127.0.0.1/unused",
    "BAG_CAPABILITY_WORKER_API_TOKEN": "test-worker-token-that-is-long-enough-for-import",
    "BAG_CAPABILITY_ACCEPTOR_URL": "http://acceptor.test",
    "BAG_CAPABILITY_ACCEPTOR_API_TOKEN": "test-acceptor-token-that-is-long-enough-for-import",
}):
    from business_ai_gateway.capability_observer_service import (
        CapabilityObservationWorker,
        RefreshRequest,
    )
    from business_ai_gateway import capability_observer_service as observer_service


class FakePool:
    def __init__(self, events, *, reserve_error=False):
        self.events = events
        self.reserve_error = reserve_error
        self.observation_id = 71

    async def fetchval(self, sql, *args):
        if "bag.reserve_capability_probe" in sql:
            self.events.append(("reserve", args))
            if self.reserve_error:
                raise asyncpg.PostgresError("reservation denied")
            return 41
        if "bag.record_capability_observation" in sql:
            self.events.append(("record", args))
            return self.observation_id
        raise AssertionError(f"unexpected SQL: {sql}")


class FakeOneC:
    def __init__(self, events, result):
        self.events = events
        self.result = result

    async def capabilities(self, source, *, refresh):
        self.events.append(("probe", source.id, refresh))
        return self.result


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


def _source() -> Source:
    return Source(
        id="onec-synthetic",
        project="onec",
        kind="onec_auto",
        display_name="synthetic",
        base_url="https://example.invalid/odata",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
        row_version=9,
    )


def _capabilities(source_id: str) -> OneCCapabilities:
    return OneCCapabilities(
        source_id=source_id,
        platform_version="8.3.synthetic",
        metadata_fingerprint="a" * 64,
        metadata_supported=True,
        json_supported=True,
        atom_supported=False,
        expand_supported=None,
        entity_set_count=3,
        adapter_profile=AdapterProfile.ODATA_JSON_V3,
        compatibility_status=CompatibilityStatus.SUPPORTED,
        evidence={"probe": "test"},
        register_capabilities={"read": True},
    )


def _worker(events, capabilities, *, reserve_error=False):
    worker = object.__new__(CapabilityObservationWorker)
    source = _source()
    worker.writer_db = SimpleNamespace(require_pool=lambda: FakePool(events, reserve_error=reserve_error))
    worker.onec = FakeOneC(events, capabilities)
    worker.acceptor_url = "http://acceptor.test"
    worker.acceptor_token = "test-acceptor-token"
    worker.acceptor_http = SimpleNamespace(post=AsyncMock())
    worker.acceptor_http.post.return_value = FakeResponse({
        "source_id": source.id,
        "request_id": "9ca25361-fdd4-46b8-ae35-59126c5ef8a1",
        "observation_id": 71,
        "drift_status": "STABLE",
    })
    worker._authorize_and_resolve_source = AsyncMock(return_value=source)
    return worker


@pytest.mark.asyncio
async def test_refresh_reserves_before_probe_and_forwards_exact_binding():
    events = []
    source = _source()
    request_id = UUID("9ca25361-fdd4-46b8-ae35-59126c5ef8a1")
    worker = _worker(events, _capabilities(source.id))

    result = await worker.refresh(RefreshRequest(source_id=source.id, request_id=request_id), authorization=None)

    assert [event[0] for event in events] == ["reserve", "probe", "record"]
    assert events[0] == ("reserve", (source.id, request_id, source.row_version))
    assert events[1] == ("probe", source.id, True)
    assert events[2][1][:4] == (source.id, request_id, 41, source.row_version)
    assert events[2][1][4:] == (
        "a" * 64,
        "8.3.synthetic",
        "SUPPORTED",
        "ODATA_JSON_V3",
        True,
        True,
        False,
        None,
        3,
        '{"probe": "test"}',
        '{"read": true}',
    )
    worker.acceptor_http.post.assert_awaited_once()
    accepted_request = worker.acceptor_http.post.await_args.kwargs["json"]
    assert accepted_request == {
        "source_id": source.id,
        "request_id": str(request_id),
        "observation_id": 71,
    }
    assert result == {
        "source_id": source.id,
        "request_id": str(request_id),
        "observation_id": 71,
        "status": "STABLE",
    }


@pytest.mark.asyncio
async def test_provider_source_mismatch_fails_without_record_or_accept():
    events = []
    source = _source()
    worker = _worker(events, _capabilities("different-source"))

    with pytest.raises(HTTPException) as raised:
        await worker.refresh(
            RefreshRequest(source_id=source.id, request_id=UUID("9ca25361-fdd4-46b8-ae35-59126c5ef8a1")),
            authorization=None,
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == "CAPABILITY_OBSERVER_UNAVAILABLE"
    assert [event[0] for event in events] == ["reserve", "probe"]
    worker.acceptor_http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_reservation_denial_fails_before_provider_probe():
    events = []
    source = _source()
    worker = _worker(events, _capabilities(source.id), reserve_error=True)

    with pytest.raises(HTTPException) as raised:
        await worker.refresh(
            RefreshRequest(source_id=source.id, request_id=UUID("9ca25361-fdd4-46b8-ae35-59126c5ef8a1")),
            authorization=None,
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == "CAPABILITY_OBSERVER_UNAVAILABLE"
    assert [event[0] for event in events] == ["reserve"]
    worker.acceptor_http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_http_route_requires_worker_token():
    previous = observer_service.worker
    fake_worker = SimpleNamespace(
        worker_token="route-test-worker-token",
        refresh=AsyncMock(),
    )
    observer_service.worker = fake_worker
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observer_service.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/v1/observe-capabilities",
                json={"source_id": "onec-synthetic", "request_id": "9ca25361-fdd4-46b8-ae35-59126c5ef8a1"},
            )
        assert response.status_code == 401
        assert response.json() == {"detail": "SERVICE_AUTH_REQUIRED"}
        fake_worker.refresh.assert_not_awaited()
    finally:
        observer_service.worker = previous


@pytest.mark.asyncio
async def test_internal_http_route_forwards_only_validated_request_to_worker():
    previous = observer_service.worker
    request_id = "9ca25361-fdd4-46b8-ae35-59126c5ef8a1"
    result = {
        "source_id": "onec-synthetic",
        "request_id": request_id,
        "observation_id": 71,
        "status": "STABLE",
    }
    fake_worker = SimpleNamespace(
        worker_token="route-test-worker-token",
        refresh=AsyncMock(return_value=result),
    )
    observer_service.worker = fake_worker
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observer_service.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/v1/observe-capabilities",
                headers={"x-capability-worker-token": fake_worker.worker_token,
                         "authorization": "Bearer synthetic-user-token"},
                json={"source_id": "onec-synthetic", "request_id": request_id},
            )
        assert response.status_code == 200
        assert response.json() == result
        body, kwargs = fake_worker.refresh.await_args.args[0], fake_worker.refresh.await_args.kwargs
        assert body.source_id == "onec-synthetic"
        assert str(body.request_id) == request_id
        assert kwargs == {"authorization": "Bearer synthetic-user-token"}
    finally:
        observer_service.worker = previous
