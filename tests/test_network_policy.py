from __future__ import annotations

import socket

import pytest

from business_ai_gateway.network_policy import EgressPolicyError, validate_resolved_egress


@pytest.mark.asyncio
async def test_egress_policy_allows_all_resolved_addresses(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert await validate_resolved_egress(
        "https://onec.internal.example/odata", ("10.0.0.0/8",)
    ) == ("10.20.30.40",)


@pytest.mark.asyncio
async def test_egress_policy_rejects_mixed_dns_answers(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(EgressPolicyError, match="outside"):
        await validate_resolved_egress(
            "https://onec.internal.example/odata", ("10.0.0.0/8",)
        )


@pytest.mark.asyncio
async def test_egress_policy_sanitizes_resolution_failure(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        raise OSError("resolver secret=DO_NOT_LEAK")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(EgressPolicyError, match="resolution failed") as exc:
        await validate_resolved_egress("https://onec.internal.example", ("10.0.0.0/8",))
    assert "DO_NOT_LEAK" not in str(exc.value)
