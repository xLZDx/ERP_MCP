"""Behavioral contract for bounded, read-only base recovery preflight."""
from __future__ import annotations

import asyncio

import pytest

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    BaseRecoveryPreflightResult,
    BaseRecoverySnapshot,
    LifecycleCoordinator,
    LifecycleReason,
    LifecycleResult,
    LifecycleStatus,
)


def _begin(scopes: list[Scope], **overrides):
    result = {
        "base_fingerprint": "base-1",
        "state": "RECOVERING",
        "epoch": 7,
        "manifest_digest": "a" * 64,
        "scope_count": len(scopes),
        "scope_manifest": [
            {"tenant_id": scope.tenant_id, "company_id": scope.company_id}
            for scope in scopes
        ],
    }
    result.update(overrides)
    return result


def _coordinator(**kwargs):
    return LifecycleCoordinator(object(), object(), object(), **kwargs)


def test_snapshot_is_canonical_and_bounded_at_64_scopes():
    scopes = [Scope("tenant-a", f"company-{i:02d}") for i in range(64)]
    snapshot = BaseRecoverySnapshot.from_begin_result("base-1", _begin(scopes))
    assert snapshot == BaseRecoverySnapshot("base-1", 7, "a" * 64, tuple(scopes))
    with pytest.raises(ValueError):
        BaseRecoverySnapshot.from_begin_result(
            "base-1", _begin(scopes + [Scope("tenant-a", "company-64")]),
        )


@pytest.mark.parametrize("base_fingerprint,overrides", [
    ("base-1", {"result": None}),
    ("base-1", {"state": "READY"}),
    ("base-1", {"extra": "unknown"}),
    ("base-2", {}),
    ("base-1", {"epoch": True}),
    ("base-1", {"epoch": 0}),
    ("base-1", {"manifest_digest": "A" * 64}),
    ("base-1", {"scope_count": 1}),
    ("base-1", {"scope_count": True}),
    ("base-1", {"scope_manifest": [{"tenant_id": "tenant-a"}]}),
    ("base-1", {"scope_count": 0, "scope_manifest": []}),
    ("base-1", {"scope_manifest": [
        {"tenant_id": "tenant-a", "company_id": "company-b"},
        {"tenant_id": "tenant-a", "company_id": "company-a"},
    ]}),
    ("base-1", {"scope_manifest": [
        {"tenant_id": "tenant-a", "company_id": "company-a"},
        {"tenant_id": "tenant-a", "company_id": "company-a"},
    ]}),
    (" base-1 ", {}),
])
def test_malformed_begin_result_is_rejected_before_any_scope_preflight(
        base_fingerprint, overrides):
    scopes = [Scope("tenant-a", "company-a"), Scope("tenant-a", "company-b")]
    result = (overrides.pop("result") if "result" in overrides
              else _begin(scopes, **overrides))
    coordinator = _coordinator()
    calls = []

    async def unexpected(scope):
        calls.append(scope)
        return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                               LifecycleReason.CHAIN_UNAVAILABLE)

    coordinator.preflight = unexpected
    with pytest.raises(ValueError):
        asyncio.run(coordinator.preflight_base_recovery(base_fingerprint, result))
    assert calls == []


def test_preflight_is_concurrency_bounded_manifest_ordered_and_never_ready():
    scopes = tuple(Scope("tenant-a", f"company-{i:02d}") for i in range(9))
    coordinator = _coordinator()
    calls = []
    active = peak = 0

    async def preflight(scope):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(scope)
        try:
            await asyncio.sleep((9 - int(scope.company_id[-2:])) * 0.001)
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHAIN_UNAVAILABLE)
        finally:
            active -= 1

    coordinator.preflight = preflight
    result = asyncio.run(coordinator.preflight_base_recovery(
        "base-1", _begin(list(scopes)),
    ))
    assert isinstance(result, BaseRecoveryPreflightResult)
    assert tuple(row.scope for row in result.scope_results) == scopes
    assert set(calls) == set(scopes)
    assert peak == 4
    assert all(row.status is LifecycleStatus.NOT_READY for row in result.scope_results)
    assert not hasattr(result, "ready")


def test_caller_cancellation_cancels_only_active_bounded_reads():
    scopes = tuple(Scope("tenant-a", f"company-{i:02d}") for i in range(8))
    coordinator = _coordinator()
    started = asyncio.Event()
    cancelled = []

    async def wait_for_external(scope):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(scope)
            raise

    coordinator.preflight = wait_for_external

    async def exercise():
        task = asyncio.create_task(coordinator.preflight_base_recovery(
            "base-1", _begin(list(scopes)),
        ))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert 1 <= len(cancelled) <= 4


def test_deadline_preserves_completed_reads_and_marks_pending_as_timed_out():
    scopes = tuple(Scope("tenant-a", f"company-{i:02d}") for i in range(4))
    coordinator = _coordinator(base_preflight_timeout_seconds=0.05)
    completed, cancelled = [], []

    async def bounded_read(scope):
        index = int(scope.company_id[-2:])
        if index < 2:
            await asyncio.sleep(0.001)
            completed.append(scope)
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHAIN_UNAVAILABLE)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(scope)
            raise

    coordinator.preflight = bounded_read
    result = asyncio.run(coordinator.preflight_base_recovery(
        "base-1", _begin(list(scopes)),
    ))
    assert tuple(completed) == scopes[:2]
    assert tuple(row.scope for row in result.scope_results) == scopes
    assert [row.reason for row in result.scope_results[:2]] == [
        LifecycleReason.CHAIN_UNAVAILABLE, LifecycleReason.CHAIN_UNAVAILABLE,
    ]
    assert all(row.reason is LifecycleReason.BASE_PREFLIGHT_DEADLINE_EXCEEDED
               for row in result.scope_results[2:])
    assert set(cancelled) == set(scopes[2:])
