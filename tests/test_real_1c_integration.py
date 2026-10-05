import os

import pytest

from business_ai_gateway.adapters.onec.client import OneCReadClient
from business_ai_gateway.compatibility import CompatibilityStatus, OneCCapabilityDetector
from business_ai_gateway.models import Source
from business_ai_gateway.secrets import EnvSecrets


BASE_URL = os.getenv("ONEC_TEST_BASE_URL")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not BASE_URL, reason="ONEC_TEST_BASE_URL is not configured")
async def test_real_1c_read_only_capability_handshake():
    username = os.getenv("ONEC_TEST_USERNAME")
    password = os.getenv("ONEC_TEST_PASSWORD")
    if (username is None) != (password is None):
        pytest.fail("ONEC_TEST_USERNAME and ONEC_TEST_PASSWORD must be set together")

    source = Source(
        id="real-1c-test",
        project="onec",
        kind="onec_auto",
        display_name="Real 1C testbed",
        base_url=BASE_URL,
        username_secret_ref="ONEC_TEST_USERNAME" if username else None,
        password_secret_ref="ONEC_TEST_PASSWORD" if password else None,
        read_only=True,
        enabled=True,
        tags=("integration",),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
        platform_version_hint=os.getenv("ONEC_TEST_PLATFORM_VERSION_HINT"),
    )

    client = OneCReadClient(timeout_seconds=30, max_response_bytes=5_000_000)
    try:
        detector = OneCCapabilityDetector(client=client, secrets=EnvSecrets())
        capabilities, index = await detector.detect(source)
        assert capabilities.compatibility_status in {
            CompatibilityStatus.SUPPORTED,
            CompatibilityStatus.SUPPORTED_WITH_FALLBACK,
        }
        assert index is not None or (
            capabilities.compatibility_status
            == CompatibilityStatus.SUPPORTED_WITH_FALLBACK
        )
    finally:
        await client.close()
