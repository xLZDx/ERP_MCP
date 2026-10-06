from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from business_ai_gateway.admin_probe import (
    AdminSourceProbe,
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

    result = await probe.probe(
        base_url="https://onec.internal.example/odata",
        username_secret_ref="ONEC_USER",
        password_secret_ref="ONEC_PASS",
    )

    assert result["health"] == {"status_code": 200, "ok": True}
    assert result["capabilities"]["source_id"] == "candidate"
    assert result["capabilities"]["register_capabilities"] == {}


@pytest.mark.asyncio
async def test_probe_rejects_dns_resolution_change_during_probe(monkeypatch):
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

    with pytest.raises(SourceEgressDenied, match="DNS resolution changed"):
        await probe.probe(
            base_url="https://onec.internal.example/odata",
            username_secret_ref="ONEC_USER",
            password_secret_ref="ONEC_PASS",
        )
