"""Focused source-level acceptance cases for R2-US-006 (TC016 and TC017).

TC018 is already covered by tests/test_secrets.py::
test_file_secret_provider_observes_rotation_and_revocation_without_restart.
These tests are authored from the bounded local contract; they do not establish
production-provider approval or a live gateway-process restart scenario.
"""

import json
import logging

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.adapters.onec.adapter import OneCAdapter
from business_ai_gateway.models import Source
from business_ai_gateway.settings import Settings
from business_ai_gateway.tool_errors import StructuredErrorMCPServer


def _source(*, username_ref: str | None, password_ref: str | None) -> Source:
    return Source(
        id="secret-acceptance-source",
        project="phase2",
        kind="onec_odata",
        display_name="Secret acceptance source",
        base_url="https://1c.example.test/odata/standard.odata",
        username_secret_ref=username_ref,
        password_secret_ref=password_ref,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )


@pytest.mark.asyncio
async def test_tc016_call_tool_does_not_leak_secret_in_error_payload_or_logs(caplog):
    secret_value = "synthetic-credential-value-7b190d"
    server = StructuredErrorMCPServer("tc016")

    @server.tool()
    async def source_health(source_id: str) -> dict:
        raise RuntimeError(f"credential value: {secret_value}")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(UnexpectedToolError) as raised:
            await server.call_tool("source_health", {"source_id": secret_value})

    # source_id is request-controlled and can itself contain credential-like material.
    assert secret_value not in str(raised.value)
    assert secret_value not in caplog.text
    payload = json.loads(str(raised.value))
    assert payload["error"]["source_id"] is None


def test_tc016_untrusted_value_error_text_is_not_echoed():
    from business_ai_gateway.tool_errors import classify

    failure = classify(ValueError("unexpected value secret-value-93c1"))

    assert failure.code == "INVALID_ARGUMENT"
    assert failure.safe_message == "Invalid argument."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username_ref", "password_ref"),
    [
        ("username-ref", None),
        (None, "password-ref"),
        ("   ", "password-ref"),
        ("username-ref", "\t "),
    ],
)
async def test_tc017_unpaired_credentials_fail_before_secret_lookup_or_source_io(
    username_ref, password_ref
):
    class Secrets:
        def __init__(self):
            self.calls = []

        async def get(self, ref: str) -> str:
            self.calls.append(ref)
            return f"value-for-{ref}"

    class Client:
        def __init__(self):
            self.calls = []

        async def head_metadata(self, source, *, username, password):
            self.calls.append((source.id, username, password))
            return {"status": "ok"}

    client = Client()
    secrets = Secrets()
    adapter = OneCAdapter(Settings(), secrets, client)

    with pytest.raises(RuntimeError, match="username/password secret refs must be paired"):
        await adapter.health(
            _source(username_ref=username_ref, password_ref=password_ref)
        )

    assert secrets.calls == []
    assert client.calls == []
    # This adapter seam can prove that the failed preflight performs no source request.
    # It cannot establish process-level /healthz availability; no isolated app/runtime seam is
    # present here, and manufacturing one would only simulate the gateway guarantee.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username_ref", "password_ref"),
    [("", ""), (" \t", "   ")],
)
async def test_tc017_both_blank_refs_normalize_to_anonymous_without_secret_lookup(
    username_ref, password_ref
):
    class Secrets:
        def __init__(self):
            self.calls = []

        async def get(self, ref: str) -> str:
            self.calls.append(ref)
            return f"value-for-{ref}"

    secrets = Secrets()
    adapter = OneCAdapter(Settings(), secrets, client=object())

    assert await adapter.credentials(
        _source(username_ref=username_ref, password_ref=password_ref)
    ) == (None, None)
    assert secrets.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username_ref", "password_ref"),
    [
        ("username-ref", None),
        (None, "password-ref"),
        ("   ", "password-ref"),
        ("username-ref", "\t "),
    ],
)
async def test_tc017_capabilities_rejects_unpaired_refs_before_secret_or_metadata_io(
    username_ref, password_ref
):
    class Secrets:
        def __init__(self):
            self.calls = []

        async def get(self, ref: str) -> str:
            self.calls.append(ref)
            return f"value-for-{ref}"

    class MetadataClient:
        def __init__(self):
            self.calls = []

        async def get_bytes(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("metadata must not be requested without a credential pair")

    secrets = Secrets()
    client = MetadataClient()
    adapter = OneCAdapter(Settings(), secrets, client)

    with pytest.raises(RuntimeError, match="username/password secret refs must be paired"):
        await adapter.capabilities(
            _source(username_ref=username_ref, password_ref=password_ref)
        )

    assert secrets.calls == []
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_value_ref", "invalid_value"),
    [
        ("username-ref", None),
        ("username-ref", ""),
        ("username-ref", " \t"),
        ("password-ref", None),
        ("password-ref", ""),
        ("password-ref", " \t"),
    ],
)
async def test_tc017_capabilities_rejects_invalid_resolved_secret_before_metadata_io(
    invalid_value_ref,
    invalid_value,
):
    class Secrets:
        def __init__(self):
            self.calls = []

        async def get(self, ref: str) -> str | None:
            self.calls.append(ref)
            return invalid_value if ref == invalid_value_ref else f"value-for-{ref}"

    class MetadataClient:
        def __init__(self):
            self.calls = []

        async def get_bytes(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("metadata must not be requested with incomplete credentials")

    secrets = Secrets()
    client = MetadataClient()
    adapter = OneCAdapter(Settings(), secrets, client)

    with pytest.raises(RuntimeError, match="username/password secret refs must be paired"):
        await adapter.capabilities(
            _source(username_ref="username-ref", password_ref="password-ref")
        )

    assert secrets.calls == ["username-ref", "password-ref"]
    assert client.calls == []

