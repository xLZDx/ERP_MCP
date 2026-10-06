from __future__ import annotations

import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from business_ai_gateway.admin_probe import (
    AdminSourceProbe,
    PinnedSourceTransport,
    SourceEgressDenied,
    SourceEgressPolicy,
)
from business_ai_gateway.compatibility import (
    AdapterProfile,
    CompatibilityStatus,
    OneCCapabilities,
)


@pytest.mark.asyncio
async def test_egress_policy_requires_exact_host_and_approved_network(monkeypatch):
    def resolved(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.44.1.7", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolved)
    policy = SourceEgressPolicy(
        allowed_hosts="onec.internal.example",
        allowed_cidrs="10.44.0.0/16",
    )

    result = await policy.validate("https://onec.internal.example/odata")

    assert result["host"] == "onec.internal.example"
    assert result["resolved_addresses"] == ["10.44.1.7"]


@pytest.mark.asyncio
async def test_egress_policy_rejects_unlisted_host_before_dns(monkeypatch):
    called = False

    def resolved(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(socket, "getaddrinfo", resolved)
    policy = SourceEgressPolicy(
        allowed_hosts="onec.internal.example",
        allowed_cidrs="10.44.0.0/16",
    )

    with pytest.raises(SourceEgressDenied):
        await policy.validate("https://evil.example/odata")

    assert called is False


@pytest.mark.asyncio
async def test_egress_policy_rejects_resolution_outside_approved_cidr(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))
        ],
    )
    policy = SourceEgressPolicy(
        allowed_hosts="onec.internal.example",
        allowed_cidrs="10.44.0.0/16",
    )

    with pytest.raises(SourceEgressDenied):
        await policy.validate("https://onec.internal.example/odata")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://u:p@onec.internal.example/odata", "https://onec.internal.example/odata?target=evil",
    "https://onec.internal.example/odata#fragment", "https://onec.internal.example:8443/odata",
    "file:///etc/passwd", "https://evil.example/odata",
])
async def test_probe_rejects_unsafe_authority_without_contacting_dns(monkeypatch, url):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid authority must not reach DNS")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    policy = SourceEgressPolicy(allowed_hosts="onec.internal.example", allowed_cidrs="10.44.0.0/16")
    with pytest.raises(SourceEgressDenied):
        await policy.validate(url)


@pytest.mark.asyncio
async def test_probe_returns_only_safe_capability_summary(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.44.1.7", 443))
        ],
    )
    capabilities = OneCCapabilities(
        source_id="ephemeral",
        platform_version="8.3.27",
        metadata_fingerprint="abc",
        metadata_supported=True,
        json_supported=True,
        atom_supported=False,
        expand_supported=True,
        entity_set_count=42,
        adapter_profile=AdapterProfile.ODATA_JSON_V3,
        compatibility_status=CompatibilityStatus.SUPPORTED,
        evidence={"metadata": "ok", "json_probe": "ok:Catalog_X"},
        register_capabilities={"internal": "not returned"},
    )
    onec = SimpleNamespace(
        health=AsyncMock(return_value={"status_code": 200, "ok": True}),
        capabilities=AsyncMock(return_value=capabilities),
        _metadata={},
        _capabilities={},
    )
    runtime = SimpleNamespace(
        settings=SimpleNamespace(environment="production"),
        onec=onec,
    )
    probe = AdminSourceProbe(
        runtime,
        SourceEgressPolicy(
            allowed_hosts="onec.internal.example",
            allowed_cidrs="10.44.0.0/16",
        ),
    )

    @asynccontextmanager
    async def approved(_url):
        yield onec, {"host": "onec.internal.example", "port": 443, "resolved_addresses": ["10.44.1.7"]}

    monkeypatch.setattr(probe, "approved_adapter", approved)

    result = await probe.probe(
        base_url="https://onec.internal.example/odata",
        username_secret_ref="ONEC_USER",
        password_secret_ref="ONEC_PASS",
    )

    assert result["health"] == {"status_code": 200, "ok": True}
    assert result["egress"] == {
        "host": "onec.internal.example",
        "port": 443,
        "resolved_count": 1,
    }
    assert "resolved_addresses" not in result["egress"]
    assert result["capabilities"]["source_id"] == "candidate"
    assert result["capabilities"]["register_capabilities"] == {}


@pytest.mark.asyncio
async def test_probe_pins_connect_address_before_credentials_are_sent(monkeypatch):
    answers = iter(
        [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.44.1.7", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.44.1.8", 443))],
        ]
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: next(answers))
    capabilities = OneCCapabilities(
        source_id="ephemeral",
        platform_version="8.3.27",
        metadata_fingerprint="abc",
        metadata_supported=True,
        json_supported=True,
        atom_supported=False,
        expand_supported=True,
        entity_set_count=42,
        adapter_profile=AdapterProfile.ODATA_JSON_V3,
        compatibility_status=CompatibilityStatus.SUPPORTED,
        evidence={"metadata": "ok"},
        register_capabilities={},
    )
    runtime = SimpleNamespace(
        settings=SimpleNamespace(environment="production"),
        onec=SimpleNamespace(
            health=AsyncMock(return_value={"status_code": 200, "ok": True}),
            capabilities=AsyncMock(return_value=capabilities),
            _metadata={},
            _capabilities={},
        ),
    )
    probe = AdminSourceProbe(
        runtime,
        SourceEgressPolicy(
            allowed_hosts="onec.internal.example",
            allowed_cidrs="10.44.0.0/16",
        ),
    )

    egress = await probe.policy.validate("https://onec.internal.example/odata")
    seen = []

    async def endpoint(request):
        seen.append(request)
        return httpx.Response(200, content=b"ok")

    transport = PinnedSourceTransport(
        "onec.internal.example", 443, egress["resolved_addresses"][0], httpx.MockTransport(endpoint)
    )
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        await client.get("https://onec.internal.example/odata/$metadata")
        with pytest.raises(SourceEgressDenied):
            await client.get("https://evil.example/odata")
        with pytest.raises(SourceEgressDenied):
            await client.post("https://onec.internal.example/odata")
    assert seen[0].url.host == "10.44.1.7"
    assert seen[0].headers["host"] == "onec.internal.example"
    assert seen[0].extensions["sni_hostname"] == "onec.internal.example"
    # Even a later DNS answer cannot select the connect target.
    changed = await probe.policy.validate("https://onec.internal.example/odata")
    assert changed["resolved_addresses"] == ["10.44.1.8"]
