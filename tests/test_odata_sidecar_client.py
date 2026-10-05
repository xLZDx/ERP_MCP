import json

import httpx
import pytest

from business_ai_gateway.adapters.onec.adapter import OneCAdapter
from business_ai_gateway.adapters.onec.sidecar_client import (
    UPSTREAM_SHA,
    ODataSidecarClient,
    ODataSidecarError,
)
from business_ai_gateway.compatibility import AdapterProfile, CompatibilityStatus, OneCCapabilities
from business_ai_gateway.models import Source
from business_ai_gateway.settings import Settings


def source():
    return Source(
        id="source-1",
        project="onec",
        kind="onec_odata",
        display_name="test",
        base_url="https://onec.example.test/odata/standard.odata",
        username_secret_ref="onec-user",
        password_secret_ref="onec-password",
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=("Document_*",),
        entity_deny_patterns=(),
    )


def envelope(source_id="source-1", *, sha=UPSTREAM_SHA):
    return {
        "source_id": source_id,
        "adapter": {"kind": "ODATA_JSON_V3", "upstream_sha": sha},
        "operation": "query",
        "data": [{"Ref_Key": "r1"}],
    }


@pytest.mark.asyncio
async def test_sidecar_client_sends_server_owned_source_and_secret_header():
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json=envelope())

    client = ODataSidecarClient(
        base_url="http://odata-sidecar:8765",
        token="t" * 48,
        timeout_seconds=2,
        max_response_bytes=10000,
        max_rows=200,
        transport=httpx.MockTransport(respond),
    )
    try:
        result = await client.read(
            source(),
            username="service-user",
            password="secret-password",
            entity_set="Document_Invoice",
            select=["Ref_Key"],
            filter_expr="DeletionMark eq false",
            orderby="Date desc",
            expand=None,
            top=20,
            skip=0,
        )
        assert result == {"value": [{"Ref_Key": "r1"}]}
        req = requests[0]
        body = json.loads(req.content)
        assert str(req.url) == "http://odata-sidecar:8765/v1/read"
        assert req.headers["authorization"] == "Bearer " + "t" * 48
        assert body["base_url"] == source().base_url
        assert body["username"] == "service-user"
        assert body["password"] == "secret-password"
        assert body["orderby"] == ["Date desc"]
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,match",
    [
        (envelope("other-source"), "provenance mismatch"),
        (envelope(sha="0" * 40), "pin mismatch"),
    ],
)
async def test_sidecar_client_fails_closed_on_provenance_mismatch(payload, match):
    client = ODataSidecarClient(
        base_url="http://sidecar",
        token="s" * 48,
        timeout_seconds=2,
        max_response_bytes=10000,
        max_rows=200,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(ODataSidecarError, match=match):
            await client.read(
                source(),
                username="u",
                password="p",
                entity_set="Document_Invoice",
                select=None,
                filter_expr=None,
                orderby=None,
                expand=None,
                top=5,
                skip=0,
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_sidecar_client_normalizes_count_and_keyed_read():
    class SequenceTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.payloads = [
                {**envelope(), "operation": "count", "data": [{"count": 17}]},
                {**envelope(), "operation": "entity_get", "data": [{"Ref_Key": "r1"}]},
                {
                    **envelope(),
                    "operation": "register_read",
                    "data": [{"Quantity": "3"}],
                    "page": {"returned": 1, "has_more": False, "truncated": False},
                },
            ]
            self.requests = []

        async def handle_async_request(self, request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=self.payloads.pop(0))

    transport = SequenceTransport()
    client = ODataSidecarClient(
        base_url="http://sidecar",
        token="s" * 48,
        timeout_seconds=2,
        max_response_bytes=10000,
        max_rows=200,
        transport=transport,
    )
    try:
        assert (
            await client.count(
                source(),
                username="u",
                password="p",
                entity_set="Document_Invoice",
                filter_expr=None,
            )
            == 17
        )
        result = await client.get(
            source(),
            username="u",
            password="p",
            entity_set="Document_Invoice",
            key="123e4567-e89b-12d3-a456-426614174000",
        )
        assert result == {"value": [{"Ref_Key": "r1"}]}
        assert transport.requests[0]["operation"] == "count"
        assert transport.requests[1]["key"] == "123e4567-e89b-12d3-a456-426614174000"
        register = await client.register_read(
            source(),
            username="u",
            password="p",
            register_set="AccumulationRegister_Inventory",
            method="turnovers",
            arguments={"Period": {"from": "2025-01-01T00:00:00Z"}},
            top=10,
        )
        assert register["value"] == [{"Quantity": "3"}]
        assert transport.requests[2]["register_method"] == "turnovers"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_sidecar_client_bounds_response_and_sanitizes_upstream_error():
    client = ODataSidecarClient(
        base_url="http://sidecar",
        token="s" * 48,
        timeout_seconds=2,
        max_response_bytes=32,
        max_rows=200,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(502, text="secret upstream detail")
        ),
    )
    try:
        with pytest.raises(ODataSidecarError, match="HTTP 502") as error:
            await client.read(
                source(),
                username="u",
                password="p",
                entity_set="Document_Invoice",
                select=None,
                filter_expr=None,
                orderby=None,
                expand=None,
                top=5,
                skip=0,
            )
        assert "secret upstream detail" not in str(error.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_sidecar_client_rejects_more_rows_than_gateway_limit():
    payload = envelope()
    payload["data"] = [{"n": 1}, {"n": 2}]
    client = ODataSidecarClient(
        base_url="http://sidecar",
        token="s" * 48,
        timeout_seconds=2,
        max_response_bytes=10000,
        max_rows=1,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(ODataSidecarError, match="contract mismatch"):
            await client.read(
                source(),
                username="u",
                password="p",
                entity_set="Document_Invoice",
                select=None,
                filter_expr=None,
                orderby=None,
                expand=None,
                top=5,
                skip=0,
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_adapter_routes_only_detected_json_profile_to_sidecar():
    candidate = source()

    class Secrets:
        async def get(self, ref):
            return {"onec-user": "u", "onec-password": "p"}[ref]

    class DirectClient:
        async def get_bytes(self, *_args, **_kwargs):
            raise AssertionError("modern JSON profile should be routed through the sidecar")

    class Sidecar:
        def __init__(self):
            self.calls = []

        async def read(self, source_arg, **kwargs):
            self.calls.append((source_arg, kwargs))
            return {"value": [{"Ref_Key": "r1"}]}

    sidecar = Sidecar()
    adapter = OneCAdapter(
        Settings(require_metadata_entity=False), Secrets(), DirectClient(), sidecar
    )
    adapter._capabilities[candidate.id] = OneCCapabilities(
        source_id=candidate.id,
        platform_version=None,
        metadata_fingerprint="a" * 64,
        metadata_supported=True,
        json_supported=True,
        atom_supported=True,
        expand_supported=True,
        entity_set_count=1,
        adapter_profile=AdapterProfile.ODATA_JSON_V3,
        compatibility_status=CompatibilityStatus.SUPPORTED,
        evidence={"json_probe": "ok"},
    )

    result = await adapter.read(
        candidate,
        entity_set="Document_Invoice",
        select=["Ref_Key"],
        filter_expr="DeletionMark eq false",
        orderby="Date desc",
        expand=None,
        top=20,
        skip=3,
    )
    assert result == {"value": [{"Ref_Key": "r1"}]}
    assert sidecar.calls[0][1]["top"] == 20
    assert sidecar.calls[0][1]["skip"] == 3
