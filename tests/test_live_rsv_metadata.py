from __future__ import annotations

import os

import pytest

from business_ai_gateway.adapters.onec.rsv_bridge import (
    UPSTREAM_SHA,
    RSVDataBridgeClient,
)
from business_ai_gateway.models import Source


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_rsv_metadata_tools_are_read_only_allowlisted_and_normalized():
    executable = os.getenv("BAG_RSV_BRIDGE_EXECUTABLE")
    config_root = os.getenv("BAG_RSV_BRIDGE_CONFIG_ROOT")
    source_id = os.getenv("BAG_RSV_METADATA_TEST_SOURCE_ID")
    structure_object = os.getenv("BAG_RSV_METADATA_TEST_OBJECT")
    expected_sha256 = os.getenv("BAG_RSV_BRIDGE_EXECUTABLE_SHA256")
    if not all((executable, config_root, source_id, structure_object, expected_sha256)):
        pytest.skip("live synthetic RSV metadata bridge environment is not configured")

    client = RSVDataBridgeClient(
        executable=executable,
        config_root=config_root,
        timeout_seconds=40,
        expected_executable_sha256=expected_sha256,
    )
    source = Source(
        id=source_id,
        project="onec",
        kind="onec_auto",
        display_name="synthetic-live-rsv",
        base_url="https://localhost/metadata-only-test",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )
    calls = (
        ("ping", {}),
        ("config", {}),
        ("describe", {"type": "Справочник"}),
        ("get_structure", {"object": structure_object}),
        ("help", {"topic": "config"}),
    )
    for operation, arguments in calls:
        result = await client.metadata(
            source,
            operation=operation,
            arguments=arguments,
            max_response_bytes=5_000_000,
        )
        assert result["source_id"] == source.id
        assert result["adapter"]["upstream_source_sha"] == UPSTREAM_SHA
        assert result["adapter"]["executable_sha256"] == expected_sha256.lower()
        assert result["operation"] == operation
        assert "data" in result

