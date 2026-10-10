"""Phase 2 sprint S9 (R2-US-043, TC129): background interference and the background budget.

Offline, unwired, pure arithmetic over supplied numbers; it never measures anything. Authority is
``EVALUATION_ONLY`` and every output is stamped ``SCRIPTED_OFFLINE_FIXTURE`` unless a well-formed
operator ``MeasurementRef`` is supplied. Targets are PROPOSED values from the test plan, not measured
guarantees (``TARGET_LABEL``).

* ``interference(baseline_p95_us, loaded_p95_us, target=0.20)`` -> ``InterferenceResult``. Ratio is
  ``(loaded - baseline) / baseline``. The verdict uses an exact comparison
  ``loaded - baseline <= target * baseline`` (equal is ``WITHIN_TARGET``), never the rounded ratio; the
  displayed ratio is rounded half-even to 6 places. A missing/zero/negative/insufficient baseline is
  ``BASELINE_INVALID``. Inputs are integer microseconds or ``PercentileValue`` objects.
* ``BudgetPolicy`` / ``make_policy`` - ``min_background_slots >= 1`` (a policy that lets background starve
  is REFUSED as ``BACKGROUND_STARVED``), per-tenant ``tenant_share_slots``, conservative defaults
  ``capture_per_backend = 1`` and ``writer_per_source = 1``.
* ``plan_budget(policy, demand, budget, ids)`` -> ``BudgetPlan`` or ``OpsRefusal``. Pure: the slot limits
  are READ from the reused ``PhysicalBackendBudget`` (``per_backend_limit`` / ``total_limit``); aliases of
  one backend id (``DB-1``, `` db-1 ``) share one counter via ``BackendId.normalize``. Phases per backend:
  (A) background up to its guaranteed minimum, (B) interactive up to the remaining slots, (C) the rest of
  the background. Every grant is also bounded by the tenant's share on that backend, the capture/writer
  caps and the total limit; a cut demand is reported as deferred with ``TENANT_SHARE_EXCEEDED`` or
  ``BACKEND_BUDGET_EXCEEDED`` (the first limiting step of the last grant attempt). Input order is the priority order
  inside a phase; tenant fairness is bounded by the share only. Allocations refer to demand items by
  index and carry no tenant text.
* ``TenantSubShare(budget, per_tenant_share)`` - a runtime gate: ``reserve(tenant_id=, backend_id=)`` takes
  one slot from the tenant's own share first and then from the SHARED ``PhysicalBackendBudget`` (the only
  shared limiter); denial raises ``SubShareDenied`` with a fixed ``OpsReason``; slots are released on exit
  or exception.

Honest limits: single-process reference (the distributed atomic backend is production work); the real
interference on a real 1C is NOT_RUN; a plan is arithmetic over a scripted demand table.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal
from enum import StrEnum
from typing import Final

from .backend_budget import BackendCapacityError, BackendId, PhysicalBackendBudget
from .capacity_model import MAX_LATENCY_US, ConfiguredLimit, MeasurementRef, PercentileValue
from .comparison_snapshot import canonical_digest
from .ops_types import (
    AUTHORITY,
    Basis,
    OpsReason,
    OpsRefusal,
    TenantSlotCounter,
    is_digest,
    is_exact_decimal,
    is_exact_int,
    is_exact_str,
    is_identity_text,
    ops_refusal,
)

__all__ = [
    "DEFAULT_INTERFERENCE_TARGET", "MAX_DEMAND_ITEMS", "TARGET_LABEL", "Allocation", "BudgetPlan",
    "BudgetPolicy", "DemandItem", "InterferenceResult", "SubShareDenied", "TenantSubShare", "WorkClass",
    "interference", "make_policy", "plan_budget",
]

TARGET_LABEL: Final = "proposed target, not a measured guarantee"
DEFAULT_INTERFERENCE_TARGET: Final = Decimal("0.20")
MAX_DEMAND_ITEMS: Final = 1024
_MAX_SLOTS: Final = 10_000
_CTX: Final = Context(prec=60, rounding=ROUND_HALF_EVEN)
_SIX_PLACES: Final = Decimal("0.000001")


# --------------------------------------------------------------------------------------------------
# interference

@dataclass(frozen=True, slots=True)
class InterferenceResult:
    """``reason`` is ``WITHIN_TARGET`` / ``EXCEEDS_TARGET`` / ``BASELINE_INVALID`` / ``INSUFFICIENT_SAMPLES`` /
    ``INPUT_INVALID`` / ``CONFIG_LIMIT_NOT_CAPACITY`` / ``BASIS_NOT_REAL_MEASUREMENT``."""

    reason: OpsReason
    ratio: Decimal | None
    baseline_p95_us: int | None
    loaded_p95_us: int | None
    target: Decimal | None
    target_label: str
    basis: Basis
    measurement_ref_digest: str | None
    digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        if not (type(self.reason) is OpsReason and (self.ratio is None or is_exact_decimal(self.ratio))
                and (self.baseline_p95_us is None or is_exact_int(self.baseline_p95_us, 0, MAX_LATENCY_US))
                and (self.loaded_p95_us is None or is_exact_int(self.loaded_p95_us, 0, MAX_LATENCY_US))
                and (self.target is None or is_exact_decimal(self.target))
                and self.target_label == TARGET_LABEL and type(self.basis) is Basis
                and (self.measurement_ref_digest is None or is_digest(self.measurement_ref_digest))
                and (self.basis is Basis.OPERATOR_REFERENCE) is (self.measurement_ref_digest is not None)
                and is_digest(self.digest) and self.authority == AUTHORITY):
            raise ValueError("INTERFERENCE_RESULT_INVALID")

    def __repr__(self) -> str:
        return "InterferenceResult(<redacted>)"


def _digest(parts: dict[str, object]) -> str:
    return canonical_digest(parts)


def _result(reason: OpsReason, ratio: Decimal | None, baseline: int | None, loaded: int | None,
            target: Decimal | None, basis: Basis, ref_digest: str | None) -> InterferenceResult:
    digest = _digest({"reason": reason.value, "ratio": ratio, "baseline": baseline, "loaded": loaded,
                      "target": target, "basis": basis.value, "ref": ref_digest, "authority": AUTHORITY})
    return InterferenceResult(reason, ratio, baseline, loaded, target, TARGET_LABEL, basis, ref_digest,
                              digest)


def _p95_us(value: object) -> int | OpsReason:
    """An integer microsecond value, or the reason it cannot be used."""
    if type(value) is ConfiguredLimit:
        return OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    if type(value) is PercentileValue:
        try:
            number, reason = value.value, value.reason
        except AttributeError:
            return OpsReason.INPUT_INVALID
        if number is None:
            return reason if type(reason) is OpsReason else OpsReason.INPUT_INVALID
        value = number
    if not is_exact_int(value, 0, MAX_LATENCY_US):
        return OpsReason.INPUT_INVALID
    return value  # type: ignore[return-value]


def interference(baseline_p95_us: object, loaded_p95_us: object,
                 target: object = DEFAULT_INTERFERENCE_TARGET, *,
                 measurement_ref: object = None) -> InterferenceResult:
    """Foreground p95 increase caused by background load, against a proposed target. Never raises."""
    try:
        basis, ref_digest = Basis.SCRIPTED_OFFLINE_FIXTURE, None
        if measurement_ref is not None:
            if type(measurement_ref) is not MeasurementRef or not is_digest(measurement_ref.digest):
                return _result(OpsReason.BASIS_NOT_REAL_MEASUREMENT, None, None, None, None, basis, None)
            basis, ref_digest = Basis.OPERATOR_REFERENCE, measurement_ref.digest
        if not is_exact_decimal(target) or not Decimal(0) <= target <= Decimal(100):  # type: ignore[operator]
            return _result(OpsReason.INPUT_INVALID, None, None, None, None, basis, ref_digest)
        base, loaded = _p95_us(baseline_p95_us), _p95_us(loaded_p95_us)
        if base is OpsReason.CONFIG_LIMIT_NOT_CAPACITY or loaded is OpsReason.CONFIG_LIMIT_NOT_CAPACITY:
            return _result(OpsReason.CONFIG_LIMIT_NOT_CAPACITY, None, None, None, target, basis, ref_digest)  # type: ignore[arg-type]
        if type(base) is OpsReason or base == 0:
            return _result(OpsReason.BASELINE_INVALID, None, None, None, target, basis, ref_digest)  # type: ignore[arg-type]
        if type(loaded) is OpsReason:
            return _result(loaded, None, base, None, target, basis, ref_digest)  # type: ignore[arg-type]
        diff = Decimal(loaded - base)  # type: ignore[operator]
        within = diff <= _CTX.multiply(target, Decimal(base))  # type: ignore[arg-type]
        ratio = _CTX.quantize(_CTX.divide(diff, Decimal(base)), _SIX_PLACES)  # type: ignore[arg-type]
        return _result(OpsReason.WITHIN_TARGET if within else OpsReason.EXCEEDS_TARGET, ratio, base,
                       loaded, target, basis, ref_digest)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return _result(OpsReason.INTERNAL_REFUSED, None, None, None, None, Basis.SCRIPTED_OFFLINE_FIXTURE, None)


# --------------------------------------------------------------------------------------------------
# budget policy and plan

@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    min_background_slots: int
    tenant_share_slots: int
    capture_per_backend: int = 1
    writer_per_source: int = 1

    def __post_init__(self) -> None:
        if not all(is_exact_int(v, 1, _MAX_SLOTS) for v in (
                self.min_background_slots, self.tenant_share_slots, self.capture_per_backend,
                self.writer_per_source)):
            raise ValueError("BUDGET_POLICY_INVALID")


def _policy_ok(value: object) -> bool:
    if type(value) is not BudgetPolicy:
        return False
    try:
        BudgetPolicy(value.min_background_slots, value.tenant_share_slots, value.capture_per_backend,
                     value.writer_per_source)
    except (ValueError, AttributeError):
        return False
    return True


def make_policy(*, min_background_slots: object, tenant_share_slots: object, ids: object,
                capture_per_backend: object = 1, writer_per_source: object = 1) -> BudgetPolicy | OpsRefusal:
    """A ``BudgetPolicy`` or a refusal; a minimum below one slot is the refused POLICY ``BACKGROUND_STARVED``."""
    try:
        if type(min_background_slots) is int and min_background_slots < 1:
            return ops_refusal(OpsReason.BACKGROUND_STARVED, ids)
        return BudgetPolicy(min_background_slots, tenant_share_slots, capture_per_backend,  # type: ignore[arg-type]
                            writer_per_source)  # type: ignore[arg-type]
    except ValueError:
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    except Exception:  # noqa: BLE001
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)


class WorkClass(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    BACKGROUND = "BACKGROUND"
    CAPTURE = "CAPTURE"
    WRITER = "WRITER"


@dataclass(frozen=True, slots=True)
class DemandItem:
    """``count`` slots wanted by ``tenant_id`` on ``backend_id`` for ``source_id`` in class ``work``."""

    tenant_id: str
    backend_id: str
    source_id: str
    work: WorkClass
    count: int

    def __post_init__(self) -> None:
        if not (is_identity_text(self.tenant_id) and is_exact_str(self.backend_id)
                and is_identity_text(self.source_id) and type(self.work) is WorkClass
                and is_exact_int(self.count, 1, _MAX_SLOTS)):
            raise ValueError("DEMAND_ITEM_INVALID")

    def __repr__(self) -> str:
        return "DemandItem(<redacted>)"


@dataclass(frozen=True, slots=True)
class Allocation:
    """Outcome for demand item ``index``: ``granted + deferred == requested``; ``reason`` only if deferred."""

    index: int
    granted: int
    deferred: int
    reason: OpsReason | None


@dataclass(frozen=True, slots=True)
class BudgetPlan:
    allocations: tuple[Allocation, ...]
    interactive_granted: int
    background_granted: int
    per_backend_slots: int
    total_slots: int
    min_background_slots: int
    basis: Basis
    digest: str
    authority: str = AUTHORITY

    def __repr__(self) -> str:
        return "BudgetPlan(<redacted>)"


def _snapshot_demand(demand: object) -> tuple[tuple[str, str, str, WorkClass, int], ...] | None:
    """One-time copy: ``(tenant, normalized backend, source, work, count)`` per item, or ``None``."""
    if type(demand) not in (list, tuple):
        return None
    try:
        if len(demand) > MAX_DEMAND_ITEMS:  # type: ignore[arg-type]
            return None
        snap = tuple(demand)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    out = []
    for item in snap:
        if type(item) is not DemandItem:
            return None
        try:
            tenant, raw, source, work, count = item.tenant_id, item.backend_id, item.source_id, item.work, item.count
            DemandItem(tenant, raw, source, work, count)
            backend = BackendId.normalize(raw).value
        except (ValueError, AttributeError, BackendCapacityError):
            return None
        out.append((tenant, backend, source, work, count))
    return tuple(out)


class _Ledger:
    """Mutable counters of one ``plan_budget`` call (never shared, never stored)."""

    def __init__(self, policy: BudgetPolicy, per_limit: int, total_limit: int, n: int) -> None:
        self.policy, self.per_limit, self.total_limit = policy, per_limit, total_limit
        self.total = 0
        self.backend: dict[str, int] = {}
        self.tenant: dict[tuple[str, str], int] = {}
        self.capture: dict[str, int] = {}
        self.writer: dict[str, int] = {}
        self.granted = [0] * n
        self.reason: list[OpsReason | None] = [None] * n


def _grant(ledger: _Ledger, idx: int, item: tuple[str, str, str, WorkClass, int], pool_left: int) -> int:
    """Grant as much of item ``idx``'s unmet demand as every limit allows; returns the slots granted."""
    tenant, backend, source, work, count = item
    want = count - ledger.granted[idx]
    take, reason = want, None
    left = ledger.policy.tenant_share_slots - ledger.tenant.get((tenant, backend), 0)
    if take > left:
        take, reason = max(left, 0), OpsReason.TENANT_SHARE_EXCEEDED
    if work is WorkClass.CAPTURE:
        cap = ledger.policy.capture_per_backend - ledger.capture.get(backend, 0)
    elif work is WorkClass.WRITER:
        cap = ledger.policy.writer_per_source - ledger.writer.get(source, 0)
    else:
        cap = take
    for limit in (cap, pool_left, ledger.per_limit - ledger.backend.get(backend, 0),
                  ledger.total_limit - ledger.total):
        if take > limit:
            take, reason = max(limit, 0), reason or OpsReason.BACKEND_BUDGET_EXCEEDED
    ledger.granted[idx] += take
    ledger.total += take
    ledger.backend[backend] = ledger.backend.get(backend, 0) + take
    ledger.tenant[(tenant, backend)] = ledger.tenant.get((tenant, backend), 0) + take
    if work is WorkClass.CAPTURE:
        ledger.capture[backend] = ledger.capture.get(backend, 0) + take
    elif work is WorkClass.WRITER:
        ledger.writer[source] = ledger.writer.get(source, 0) + take
    ledger.reason[idx] = reason
    return take


def plan_budget(policy: object, demand: object, budget: object, ids: object) -> BudgetPlan | OpsRefusal:
    """Split the shared backend slots between interactive and background demand. Pure; never raises.

    ``budget`` is only READ (``per_backend_limit`` / ``total_limit``), never reserved. A budget that cannot
    keep at least one slot for interactive work next to ``min_background_slots`` is
    ``BACKEND_BUDGET_EXCEEDED`` (the guarantee cannot be honoured), not a silent partial plan.
    """
    try:
        if type(budget) is not PhysicalBackendBudget or not _policy_ok(policy):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        per_limit, total_limit = budget.per_backend_limit, budget.total_limit
        items = _snapshot_demand(demand)
        if items is None or not (is_exact_int(per_limit, 1, _MAX_SLOTS) and is_exact_int(total_limit, 1, _MAX_SLOTS)):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if policy.min_background_slots >= per_limit:  # type: ignore[attr-defined]
            return ops_refusal(OpsReason.BACKEND_BUDGET_EXCEEDED, ids)
        ledger = _Ledger(policy, per_limit, total_limit, len(items))  # type: ignore[arg-type]
        interactive = [i for i, it in enumerate(items) if it[3] is WorkClass.INTERACTIVE]
        background = [i for i, it in enumerate(items) if it[3] is not WorkClass.INTERACTIVE]
        min_bg = policy.min_background_slots  # type: ignore[attr-defined]
        guaranteed: dict[str, int] = {}
        for i in background:  # phase A: background up to its guaranteed minimum per backend
            backend = items[i][1]
            guaranteed[backend] = guaranteed.get(backend, 0) + _grant(
                ledger, i, items[i], min_bg - guaranteed.get(backend, 0))
        for i in interactive:  # phase B: interactive takes what the guarantee leaves
            _grant(ledger, i, items[i], per_limit - ledger.backend.get(items[i][1], 0))
        for i in background:  # phase C: remaining background demand
            _grant(ledger, i, items[i], per_limit - ledger.backend.get(items[i][1], 0))
        allocations = tuple(
            Allocation(i, ledger.granted[i], items[i][4] - ledger.granted[i],
                       ledger.reason[i] if items[i][4] > ledger.granted[i] else None)
            for i in range(len(items)))
        inter = sum(ledger.granted[i] for i in interactive)
        digest = canonical_digest({
            "demand": [[t, b, s, w.value, c] for t, b, s, w, c in items],
            "allocations": [[a.index, a.granted, a.deferred, None if a.reason is None else a.reason.value]
                            for a in allocations],
            "limits": [per_limit, total_limit, min_bg, policy.tenant_share_slots,  # type: ignore[attr-defined]
                       policy.capture_per_backend, policy.writer_per_source],  # type: ignore[attr-defined]
            "authority": AUTHORITY})
        return BudgetPlan(allocations, inter, ledger.total - inter, per_limit, total_limit, min_bg,
                          Basis.SCRIPTED_OFFLINE_FIXTURE, digest)
    except Exception:  # noqa: BLE001
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)


# --------------------------------------------------------------------------------------------------
# runtime sub-share over the shared budget

class SubShareDenied(RuntimeError):
    """A reservation was refused; the message and ``reason`` are fixed ``OpsReason`` text only."""

    def __init__(self, reason: OpsReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class TenantSubShare:
    """Per-tenant sub-share on top of the reused, shared ``PhysicalBackendBudget``.

    The tenant's own counter (per tenant and backend) is checked and incremented atomically first; only then
    is a slot taken from the shared budget. Both are released on exit or exception. One tenant at its share
    never blocks another tenant's share; the shared budget remains the only global limiter.
    """

    def __init__(self, budget: object, per_tenant_share: object) -> None:
        if type(budget) is not PhysicalBackendBudget:
            raise ValueError("SUB_SHARE_INVALID")
        self._budget = budget
        self._counter = TenantSlotCounter(per_tenant_share)

    def __repr__(self) -> str:
        return "TenantSubShare(<redacted>)"

    def active(self, tenant_id: object, backend_id: object) -> int:
        try:
            return self._counter.active(tenant_id, backend_id.value)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return 0

    @contextmanager
    def reserve(self, *, tenant_id: object, backend_id: object) -> Iterator[None]:
        try:
            if type(backend_id) is not BackendId or not is_identity_text(tenant_id):
                raise SubShareDenied(OpsReason.INPUT_INVALID)
            key = backend_id.value
            if not is_exact_str(key):
                raise SubShareDenied(OpsReason.INPUT_INVALID)
        except AttributeError:  # forged BackendId
            raise SubShareDenied(OpsReason.INPUT_INVALID) from None
        if not self._counter.try_acquire(tenant_id, key):
            raise SubShareDenied(OpsReason.TENANT_SHARE_EXCEEDED)
        try:
            with ExitStack() as stack:
                try:
                    stack.enter_context(self._budget.reserve(trusted_backend_id=backend_id))
                except BackendCapacityError as exc:
                    code = (OpsReason.BACKEND_BUDGET_EXCEEDED if str(exc) == "BACKEND_CAPACITY_EXCEEDED"
                            else OpsReason.INPUT_INVALID)
                    raise SubShareDenied(code) from None
                yield
        finally:
            self._counter.release(tenant_id, key)
