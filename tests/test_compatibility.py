from dataclasses import replace

import httpx
import pytest

from business_ai_gateway.adapters.onec.client import OneCReadClient
from business_ai_gateway.compatibility import (
    AdapterProfile,
    CompatibilityStatus,
    OneCCapabilityDetector,
)
from business_ai_gateway.models import Source
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
        assert caps.entity_set_count == 3
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
