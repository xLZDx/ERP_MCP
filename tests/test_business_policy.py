from __future__ import annotations

from uuid import UUID

import pytest

from business_ai_gateway.business_policy import CapabilityDenied, CapabilityPolicy
from business_ai_gateway.principal import Principal


class FakePool:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return next(self.values)


class FakeDB:
    def __init__(self, values):
        self.pool = FakePool(values)

    def require_pool(self):
        return self.pool


def principal():
    return Principal(
        subject="user-1",
        client_id="client-1",
        scopes=frozenset({"onec:read"}),
        groups=frozenset({"accounting"}),
        claims={},
    )


@pytest.mark.asyncio
async def test_capability_enforcement_can_be_disabled_without_changing_baseline():
    policy = CapabilityPolicy(FakeDB([]), enabled=False)

    assert await policy.require(principal(), "accounting.read", source_id="s1") is None


@pytest.mark.asyncio
async def test_explicit_capability_deny_wins():
    policy = CapabilityPolicy(FakeDB([True]), enabled=True)

    with pytest.raises(CapabilityDenied):
        await policy.require(
            principal(),
            "payroll.review",
            source_id="s1",
            company_id=UUID("28d72aed-bf8b-4ba0-9d0c-c556c0d64cb1"),
        )


@pytest.mark.asyncio
async def test_direct_allow_succeeds_after_no_deny():
    policy = CapabilityPolicy(FakeDB([False, True]), enabled=True)

    version = await policy.require(principal(), "accounting.read", source_id="s1")

    assert version == "rbac-v1"


@pytest.mark.asyncio
async def test_role_allow_succeeds_after_no_override():
    policy = CapabilityPolicy(FakeDB([False, False, True]), enabled=True)

    assert (
        await policy.require(principal(), "month_close.review", source_id="s1")
        == "rbac-v1"
    )


@pytest.mark.asyncio
async def test_missing_capability_fails_closed():
    policy = CapabilityPolicy(FakeDB([False, False, False]), enabled=True)

    with pytest.raises(CapabilityDenied):
        await policy.require(principal(), "unknown.capability", source_id="s1")
