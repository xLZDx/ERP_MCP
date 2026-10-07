from dataclasses import replace

import httpx
import pytest

from business_ai_gateway.adapters.onec.adapter import OneCAdapter
from business_ai_gateway.adapters.onec.client import OneCReadClient
from business_ai_gateway.adapters.onec.metadata import parse_metadata
from business_ai_gateway.compatibility import (
    AdapterProfile,
    CompatibilityStatus,
    OneCCapabilities,
    OneCCapabilityDetector,
)
from business_ai_gateway.models import Source
from business_ai_gateway.settings import Settings
from business_ai_gateway.testbed.fake1c import create_app


class NoSecrets:
    async def get(self, ref: str) -> str:
        raise AssertionError("fixture source has no secret references")


def source():
    return Source(
        id="fake",
        project="onec",
        kind="onec_auto",
        display_name="Fake1C",
        base_url="http://fake/odata/standard.odata",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=("testbed",),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )


@pytest.mark.asyncio
async def test_capability_detector_prefers_json_profile():
    client = OneCReadClient(
        timeout_seconds=5,
        max_response_bytes=100000,
        transport=httpx.ASGITransport(app=create_app("json")),
    )
    try:
        detector = OneCCapabilityDetector(client=client, secrets=NoSecrets())
        caps, index = await detector.detect(source())
        assert caps.compatibility_status == CompatibilityStatus.SUPPORTED
        assert caps.adapter_profile == AdapterProfile.ODATA_JSON_V3
        assert caps.json_supported is True
        assert caps.atom_supported is True
        assert index is not None
        assert caps.entity_set_count == 12
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_capability_detector_falls_back_to_atom_profile():
    client = OneCReadClient(
        timeout_seconds=5,
        max_response_bytes=100000,
        transport=httpx.ASGITransport(app=create_app("atom")),
    )
    try:
        detector = OneCCapabilityDetector(client=client, secrets=NoSecrets())
        caps, _ = await detector.detect(source())
        assert caps.compatibility_status == CompatibilityStatus.SUPPORTED
        assert caps.adapter_profile == AdapterProfile.ODATA_ATOM_V3
        assert caps.json_supported is False
        assert caps.atom_supported is True
    finally:
        await client.close()


class UnavailableMetadataClient:
    async def get_bytes(self, *_args, **_kwargs):
        raise httpx.ConnectError("metadata endpoint unavailable")


@pytest.mark.asyncio
async def test_capability_detector_reports_unsupported_without_safe_route():
    detector = OneCCapabilityDetector(client=UnavailableMetadataClient(), secrets=NoSecrets())

    capabilities, index = await detector.detect(source())

    assert capabilities.compatibility_status == CompatibilityStatus.UNSUPPORTED
    assert capabilities.adapter_profile == AdapterProfile.UNSUPPORTED
    assert capabilities.metadata_fingerprint is None
    assert index is None


@pytest.mark.asyncio
async def test_capability_detector_selects_only_explicitly_configured_fallback():
    candidate = replace(
        source(),
        fallback_kind="onec_http_query",
        fallback_base_url="https://bridge.example.test/onec",
    )
    detector = OneCCapabilityDetector(client=UnavailableMetadataClient(), secrets=NoSecrets())

    capabilities, index = await detector.detect(candidate)

    assert capabilities.compatibility_status == CompatibilityStatus.SUPPORTED_WITH_FALLBACK
    assert capabilities.adapter_profile == AdapterProfile.HTTP_QUERY_FALLBACK
    assert index is None


@pytest.mark.asyncio
async def test_unimplemented_fallback_fails_closed_without_network_call():
    candidate = replace(
        source(),
        fallback_kind="onec_http_query",
        fallback_base_url="https://bridge.example.test/onec",
    )

    class NoRequestsClient:
        def __init__(self):
            self.calls = []

        async def get_bytes(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("fallback route must not be used before it is implemented")

    client = NoRequestsClient()
    adapter = OneCAdapter(Settings(require_metadata_entity=False), NoSecrets(), client)
    adapter._capabilities[candidate.id] = OneCCapabilities(
        source_id=candidate.id,
        platform_version=None,
        metadata_fingerprint="a" * 64,
        metadata_supported=False,
        json_supported=False,
        atom_supported=False,
        expand_supported=None,
        entity_set_count=0,
        adapter_profile=AdapterProfile.HTTP_QUERY_FALLBACK,
        compatibility_status=CompatibilityStatus.SUPPORTED_WITH_FALLBACK,
        evidence={"metadata": "ConnectError"},
    )
    adapter._capabilities_expires_at[candidate.id] = 10**9

    with pytest.raises(NotImplementedError, match="read-only HTTP/query fallback"):
        await adapter.read(
            candidate,
            entity_set="Invoices",
            select=None,
            filter_expr=None,
            orderby=None,
            expand=None,
            top=10,
            skip=0,
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_capability_and_metadata_cache_expiry_observes_schema_drift():
    adapter = OneCAdapter(Settings(metadata_cache_ttl_seconds=5), NoSecrets(), object())
    now = [100.0]
    adapter._clock = lambda: now[0]

    class ChangingDetector:
        calls = 0

        async def detect(self, _source):
            self.calls += 1
            entity_set = f"Catalog_Items_v{self.calls}"
            index = parse_metadata(
                f'<Edmx><EntityType Name="T{self.calls}"><Property Name="Name" />'
                f'</EntityType><EntitySet Name="{entity_set}" EntityType="T{self.calls}" />'
                "</Edmx>".encode()
            )
            capabilities = OneCCapabilities(
                source_id="fake",
                platform_version="8.3.test",
                metadata_fingerprint=f"{self.calls:064x}",
                metadata_supported=True,
                json_supported=True,
                atom_supported=False,
                expand_supported=True,
                entity_set_count=len(index.entities),
                adapter_profile=AdapterProfile.ODATA_JSON_V3,
                compatibility_status=CompatibilityStatus.SUPPORTED,
                evidence={"metadata": "test"},
            )
            return capabilities, index

    detector = ChangingDetector()
    adapter._detector = detector

    first = await adapter.capabilities(source())
    cached = await adapter.capabilities(source())
    assert cached.metadata_fingerprint == first.metadata_fingerprint
    assert detector.calls == 1

    now[0] += 5.01
    second = await adapter.capabilities(source())
    assert second.metadata_fingerprint != first.metadata_fingerprint
    assert detector.calls == 2
    assert (await adapter.metadata(source())).names == {"Catalog_Items_v2"}

    relocated = replace(source(), base_url="http://fake-next/odata/standard.odata")
    third = await adapter.capabilities(relocated)
    assert third.metadata_fingerprint != second.metadata_fingerprint
    assert detector.calls == 3
    assert (await adapter.metadata(relocated)).names == {"Catalog_Items_v3"}


@pytest.mark.asyncio
async def test_html_metadata_response_gets_no_fingerprint():
    """An HTML 200 for $metadata is a failed observation, not new metadata truth (P4)."""

    def handler(_request):
        return httpx.Response(200, content=b"<html>this is not OData metadata</html>",
                              headers={"content-type": "text/html"})

    client = OneCReadClient(
        timeout_seconds=5,
        max_response_bytes=100000,
        transport=httpx.MockTransport(handler),
    )
    try:
        detector = OneCCapabilityDetector(client=client, secrets=NoSecrets())
        caps, index = await detector.detect(source())
        assert index is None
        assert caps.metadata_supported is False
        assert caps.metadata_fingerprint is None
        assert caps.compatibility_status == CompatibilityStatus.UNSUPPORTED
    finally:
        await client.close()
