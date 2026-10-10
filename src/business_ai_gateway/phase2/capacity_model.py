"""Phase 2 sprint S9 (R2-US-043, TC127/TC128): capacity ACCOUNTING over supplied samples.

Offline, unwired, in-memory, pure. No load generator and no measurement: every function here computes
from samples handed to it and never produces one. Nothing in this module can say "capacity proven":
``CapacityReport`` has no such field, every report is stamped ``basis = SCRIPTED_OFFLINE_FIXTURE`` unless
a well-formed operator-supplied ``MeasurementRef`` accompanies samples that themselves carry
``OPERATOR_REFERENCE`` (and even then no "proven" field exists). Authority is ``EVALUATION_ONLY``.

Four separate axes (TC127): ``SessionCount``, ``ActiveClientCount``, ``SourceCount``, ``BackendCount`` are
distinct frozen types that do not convert to each other and are refused in each other's place. A
``GridCell`` is the tuple ``(sources, active_clients, sessions, backends, cache_state, discovery,
workload)`` taken from the fixed TEST_PLAN section 5 matrix (``MATRIX_*``). ``make_cell`` maps refusals:
no active-client dimension -> ``SESSIONS_NOT_ACTIVE_CLIENTS``; sessions < active clients ->
``GRID_CELL_INCONSISTENT``; no backend count -> ``BACKEND_COUNT_MISSING``; a ``ConfiguredLimit`` (pool,
budget, ``max_sessions``, the Release 1 constants in ``R1_LIMITS``) anywhere -> ``CONFIG_LIMIT_NOT_CAPACITY``.

Refusals are not throughput (TC128): every ``RequestSample`` has one closed ``OutcomeClass``. Business
throughput and business percentiles use ``BUSINESS_OK`` only; profile/ACL/budget/auth refusals have their
own counters and their own latency percentiles. A refusal fraction above ``ReportPolicy.refusal_bound``
adds the flags ``REFUSALS_DOMINATE`` and ``UNRELIABLE_REFUSALS``.

Percentiles are exact nearest-rank over integer microseconds: rank = ceil(p * n / 100), value =
sorted[rank - 1]. Minimum samples: p50 >= 1, p95 >= 20, p99 >= 100, otherwise ``INSUFFICIENT_SAMPLES``
(no number is invented). Throughput is a ``Decimal`` rate (business reads per second) over the declared
window, rounded half-even to 6 places.

Public names: axis types, ``ConfiguredLimit`` / ``LimitLayer`` / ``R1_LIMITS``, ``CacheState`` /
``DiscoveryState`` / ``WorkloadClass`` / ``GridCell`` / ``make_cell``, ``OutcomeClass`` /
``RequestSample`` / ``make_sample``, ``PercentileValue`` / ``percentile``, ``Summary`` / ``summarize``,
``throughput``, ``ReportPolicy``, ``MeasurementRef``, ``CapacityStore``, ``CapacityReport`` /
``build_report`` / ``read_report`` / ``is_valid_report``. Honest limit: the logic has never seen a
sample from a real 1C or a real stand; it proves classification and arithmetic over scripted inputs only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .comparison_snapshot import canonical_digest
from .ops_types import (
    AUTHORITY,
    Basis,
    OpsReason,
    OpsRefusal,
    TenantBoundedMap,
    check_scope_order,
    is_aware_datetime,
    is_digest,
    is_exact_decimal,
    is_exact_int,
    is_identity_text,
    is_valid_scope,
    ops_refusal,
)
from .workbench_types import correlation_ok

__all__ = [
    "MATRIX_ACTIVE_CLIENTS",
    "MATRIX_SESSIONS",
    "MATRIX_SOURCES",
    "MAX_LATENCY_US",
    "MAX_SAMPLES",
    "PERCENTILE_MIN_SAMPLES",
    "R1_LIMITS",
    "ActiveClientCount",
    "BackendCount",
    "CacheState",
    "CapacityReport",
    "CapacityStore",
    "ConfiguredLimit",
    "DiscoveryState",
    "GridCell",
    "LimitLayer",
    "MeasurementRef",
    "OutcomeClass",
    "PercentileValue",
    "ReportPolicy",
    "RequestSample",
    "SessionCount",
    "SourceCount",
    "Summary",
    "WorkloadClass",
    "build_report",
    "is_valid_cell",
    "is_valid_report",
    "is_valid_sample",
    "make_cell",
    "make_sample",
    "percentile",
    "read_report",
    "summarize",
    "throughput",
]

MATRIX_SOURCES: Final = (30, 50, 100, 150)
MATRIX_ACTIVE_CLIENTS: Final = (1, 5, 10, 20, 50, 100)
MATRIX_SESSIONS: Final = (50, 100, 500, 1000)
MAX_BACKENDS: Final = 64
MAX_LATENCY_US: Final = 3_600_000_000  # one hour, integer microseconds
MAX_SAMPLES: Final = 100_000
MAX_WINDOW_US: Final = 7 * 24 * 3600 * 1_000_000
PERCENTILE_MIN_SAMPLES: Final = MappingProxyType({50: 1, 95: 20, 99: 100})
_RATE_CTX: Final = Context(prec=40, rounding=ROUND_HALF_EVEN)
_SIX_PLACES: Final = Decimal("0.000001")
_ZERO_RATE: Final = Decimal("0.000000")


# --------------------------------------------------------------------------------------------------
# four separate axes

@dataclass(frozen=True, slots=True)
class _Axis:
    value: int

    def __post_init__(self) -> None:
        if not is_exact_int(self.value, 1, 1_000_000):
            raise ValueError("AXIS_INVALID")


@dataclass(frozen=True, slots=True)
class SessionCount(_Axis):
    """Open sessions (NOT active clients)."""


@dataclass(frozen=True, slots=True)
class ActiveClientCount(_Axis):
    """Clients actively issuing requests (each has a session)."""


@dataclass(frozen=True, slots=True)
class SourceCount(_Axis):
    """Registered sources (NOT physical backends)."""


@dataclass(frozen=True, slots=True)
class BackendCount(_Axis):
    """Physical 1C backends (several sources may share one; one source may span several)."""

    def __post_init__(self) -> None:
        if not is_exact_int(self.value, 1, MAX_BACKENDS):
            raise ValueError("AXIS_INVALID")


def _axis_ok(value: object, cls: type) -> bool:
    if type(value) is not cls:
        return False
    try:
        return is_exact_int(value.value, 1, MAX_BACKENDS if cls is BackendCount else 1_000_000)  # type: ignore[attr-defined]
    except AttributeError:  # forged object.__new__ instance
        return False


class LimitLayer(StrEnum):
    R1_SESSIONS = "R1_SESSIONS"
    R1_POOL = "R1_POOL"
    R1_SIDECAR = "R1_SIDECAR"
    R1_FANOUT_TOTAL = "R1_FANOUT_TOTAL"
    R1_FANOUT_PER_BACKEND = "R1_FANOUT_PER_BACKEND"
    BUDGET = "BUDGET"
    MAX_SESSIONS = "MAX_SESSIONS"
    POOL_SIZE = "POOL_SIZE"


@dataclass(frozen=True, slots=True)
class ConfiguredLimit:
    """A configured limit. It can never be a capacity axis or a sample: ``CONFIG_LIMIT_NOT_CAPACITY``."""

    layer: LimitLayer
    value: int

    def __post_init__(self) -> None:
        if type(self.layer) is not LimitLayer or not is_exact_int(self.value, 0, 1_000_000):
            raise ValueError("CONFIGURED_LIMIT_INVALID")


R1_LIMITS: Final = MappingProxyType({
    layer: ConfiguredLimit(layer, number) for layer, number in (
        (LimitLayer.R1_SESSIONS, 1000), (LimitLayer.R1_POOL, 10), (LimitLayer.R1_SIDECAR, 4),
        (LimitLayer.R1_FANOUT_TOTAL, 20), (LimitLayer.R1_FANOUT_PER_BACKEND, 2))
})


class CacheState(StrEnum):
    COLD = "COLD"
    WARM = "WARM"


class DiscoveryState(StrEnum):
    OFF = "OFF"
    ON = "ON"


class WorkloadClass(StrEnum):
    METADATA = "METADATA"
    DOCUMENTS = "DOCUMENTS"
    BALANCES = "BALANCES"
    CAPTURE = "CAPTURE"


@dataclass(frozen=True, slots=True)
class GridCell:
    sources: SourceCount
    active_clients: ActiveClientCount
    sessions: SessionCount
    backends: BackendCount
    cache_state: CacheState
    discovery: DiscoveryState
    workload: WorkloadClass

    def __post_init__(self) -> None:
        if not (_axis_ok(self.sources, SourceCount) and _axis_ok(self.active_clients, ActiveClientCount)
                and _axis_ok(self.sessions, SessionCount) and _axis_ok(self.backends, BackendCount)
                and type(self.cache_state) is CacheState and type(self.discovery) is DiscoveryState
                and type(self.workload) is WorkloadClass
                and self.sources.value in MATRIX_SOURCES
                and self.active_clients.value in MATRIX_ACTIVE_CLIENTS
                and self.sessions.value in MATRIX_SESSIONS
                and self.sessions.value >= self.active_clients.value):
            raise ValueError("GRID_CELL_INVALID")

    def axes(self) -> tuple[tuple[str, int], ...]:
        """The four axes, rendered separately and never merged."""
        return (("sources", self.sources.value), ("active_clients", self.active_clients.value),
                ("sessions", self.sessions.value), ("backends", self.backends.value))

    def _payload(self) -> dict[str, object]:
        return {"axes": [list(pair) for pair in self.axes()], "cache": self.cache_state.value,
                "discovery": self.discovery.value, "workload": self.workload.value}

    def __repr__(self) -> str:
        return "GridCell(" + ", ".join(f"{name}={number}" for name, number in self.axes()) + ")"


def is_valid_cell(value: object) -> bool:
    if type(value) is not GridCell:
        return False
    try:
        GridCell(value.sources, value.active_clients, value.sessions, value.backends,
                 value.cache_state, value.discovery, value.workload)
    except (ValueError, AttributeError):
        return False
    return True


def make_cell(sources: object, active_clients: object, sessions: object, backends: object,
              cache_state: object, discovery: object, workload: object, ids: object) -> GridCell | OpsRefusal:
    """A ``GridCell`` or a fixed refusal; never raises. Check order is documented in the module docstring."""
    try:
        parts = (sources, active_clients, sessions, backends, cache_state, discovery, workload)
        if any(type(part) is ConfiguredLimit for part in parts):
            return ops_refusal(OpsReason.CONFIG_LIMIT_NOT_CAPACITY, ids)
        if not (_axis_ok(sources, SourceCount) and _axis_ok(sessions, SessionCount)
                and type(cache_state) is CacheState and type(discovery) is DiscoveryState
                and type(workload) is WorkloadClass):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if active_clients is None:
            return ops_refusal(OpsReason.SESSIONS_NOT_ACTIVE_CLIENTS, ids)
        if backends is None:
            return ops_refusal(OpsReason.BACKEND_COUNT_MISSING, ids)
        if not (_axis_ok(active_clients, ActiveClientCount) and _axis_ok(backends, BackendCount)):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if not (sources.value in MATRIX_SOURCES and active_clients.value in MATRIX_ACTIVE_CLIENTS  # type: ignore[attr-defined]
                and sessions.value in MATRIX_SESSIONS):  # type: ignore[attr-defined]
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if sessions.value < active_clients.value:  # type: ignore[attr-defined]
            return ops_refusal(OpsReason.GRID_CELL_INCONSISTENT, ids)
        return GridCell(sources, active_clients, sessions, backends,  # type: ignore[arg-type]
                        cache_state, discovery, workload)
    except Exception:  # noqa: BLE001 - hostile input must end in a fixed refusal
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)


# --------------------------------------------------------------------------------------------------
# samples and outcome classes

class OutcomeClass(StrEnum):
    BUSINESS_OK = "BUSINESS_OK"
    BUSINESS_ERROR = "BUSINESS_ERROR"
    TIMEOUT = "TIMEOUT"
    PROFILE_REFUSED = "PROFILE_REFUSED"
    ACL_REFUSED = "ACL_REFUSED"
    BUDGET_REFUSED = "BUDGET_REFUSED"
    AUTH_REFUSED = "AUTH_REFUSED"


_REFUSAL_CLASSES: Final = frozenset({OutcomeClass.PROFILE_REFUSED, OutcomeClass.ACL_REFUSED,
                                     OutcomeClass.BUDGET_REFUSED, OutcomeClass.AUTH_REFUSED})


@dataclass(frozen=True, slots=True)
class RequestSample:
    """One request outcome with an exact integer-microsecond latency. Carries its own ``basis``."""

    outcome: OutcomeClass
    latency_us: int
    basis: Basis = Basis.SCRIPTED_OFFLINE_FIXTURE

    def __post_init__(self) -> None:
        if (type(self.outcome) is not OutcomeClass or not is_exact_int(self.latency_us, 0, MAX_LATENCY_US)
                or type(self.basis) is not Basis):
            raise ValueError("SAMPLE_INVALID")

    def __repr__(self) -> str:
        return "RequestSample(<redacted>)"


def is_valid_sample(value: object) -> bool:
    if type(value) is not RequestSample:
        return False
    try:
        return (type(value.outcome) is OutcomeClass and is_exact_int(value.latency_us, 0, MAX_LATENCY_US)
                and type(value.basis) is Basis)
    except AttributeError:
        return False


def make_sample(outcome: object, latency_us: object, ids: object,
                basis: object = Basis.SCRIPTED_OFFLINE_FIXTURE) -> RequestSample | OpsRefusal:
    """A sample from an ``OutcomeClass`` or its exact string; an unknown outcome is ``INPUT_INVALID``."""
    try:
        if type(outcome) is ConfiguredLimit or type(latency_us) is ConfiguredLimit:
            return ops_refusal(OpsReason.CONFIG_LIMIT_NOT_CAPACITY, ids)
        if type(outcome) is str:
            outcome = next((c for c in OutcomeClass if c.value == outcome), None)
        if type(outcome) is not OutcomeClass or type(basis) is not Basis:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        return RequestSample(outcome, latency_us, basis)  # type: ignore[arg-type]
    except ValueError:
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    except Exception:  # noqa: BLE001
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)


# --------------------------------------------------------------------------------------------------
# percentiles, summary, throughput

@dataclass(frozen=True, slots=True)
class PercentileValue:
    """``value`` is an exact microsecond number, or ``None`` with the reason it is absent."""

    p: int
    n: int
    value: int | None
    reason: OpsReason | None

    def __post_init__(self) -> None:
        if not (is_exact_int(self.p, 0, 100) and is_exact_int(self.n, 0, MAX_SAMPLES)
                and (self.value is None or is_exact_int(self.value, 0, MAX_LATENCY_US))
                and (self.reason is None or type(self.reason) is OpsReason)
                and (self.value is None) is (self.reason is not None)):
            raise ValueError("PERCENTILE_INVALID")

    def _payload(self) -> list[object]:
        return [self.p, self.n, self.value, None if self.reason is None else self.reason.value]


def _valid_percentile_value(value: object) -> bool:
    if type(value) is not PercentileValue:
        return False
    try:
        PercentileValue(value.p, value.n, value.value, value.reason)
    except (ValueError, AttributeError):
        return False
    return True


def percentile(values: object, p: object) -> PercentileValue:
    """Exact nearest-rank percentile of integer microseconds; never raises.

    ``p`` must be 50, 95 or 99. Fewer samples than ``PERCENTILE_MIN_SAMPLES[p]`` gives ``INSUFFICIENT_SAMPLES``
    (``value=None``); unusable input gives ``INPUT_INVALID``.
    """
    pv = p if type(p) is int and p in PERCENTILE_MIN_SAMPLES else 0
    if pv == 0 or type(values) not in (list, tuple) or len(values) > MAX_SAMPLES:  # type: ignore[arg-type]
        return PercentileValue(pv, 0, None, OpsReason.INPUT_INVALID)
    try:
        snap = tuple(values)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return PercentileValue(pv, 0, None, OpsReason.INPUT_INVALID)
    if not all(is_exact_int(v, 0, MAX_LATENCY_US) for v in snap):
        return PercentileValue(pv, 0, None, OpsReason.INPUT_INVALID)
    n = len(snap)
    if n < PERCENTILE_MIN_SAMPLES[pv]:
        return PercentileValue(pv, n, None, OpsReason.INSUFFICIENT_SAMPLES)
    rank = (pv * n + 99) // 100  # ceil(p * n / 100), 1-based, integer arithmetic only
    return PercentileValue(pv, n, sorted(snap)[rank - 1], None)


def throughput(ok_count: object, window_us: object) -> Decimal | None:
    """Business reads per second: ``ok_count * 1_000_000 / window_us`` (6 places, half-even); ``None`` if unusable."""
    if not (is_exact_int(ok_count, 0, MAX_SAMPLES) and is_exact_int(window_us, 1, MAX_WINDOW_US)):
        return None
    rate = _RATE_CTX.divide(_RATE_CTX.multiply(Decimal(ok_count), Decimal(1_000_000)), Decimal(window_us))
    return _RATE_CTX.quantize(rate, _SIX_PLACES)


@dataclass(frozen=True, slots=True)
class Summary:
    """Per-class counts plus SEPARATE business and refusal latency percentiles (p50, p95, p99 each)."""

    total: int
    counts: tuple[tuple[str, int], ...]
    business_ok: int
    refused: int
    business: tuple[PercentileValue, PercentileValue, PercentileValue]
    refusal_latency: tuple[PercentileValue, PercentileValue, PercentileValue]

    def count_of(self, outcome: OutcomeClass) -> int:
        return dict(self.counts).get(outcome.value, 0)

    def __repr__(self) -> str:
        return "Summary(<redacted>)"


def _snapshot_samples(samples: object) -> tuple[RequestSample, ...] | OpsReason:
    """One-time copy of the caller's samples; a reason code when unusable."""
    if type(samples) not in (list, tuple):
        return OpsReason.INPUT_INVALID
    try:
        if len(samples) > MAX_SAMPLES:  # type: ignore[arg-type]
            return OpsReason.INPUT_INVALID
        snap = tuple(samples)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return OpsReason.INPUT_INVALID
    if any(type(item) is ConfiguredLimit for item in snap):
        return OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    if not all(is_valid_sample(item) for item in snap):
        return OpsReason.INPUT_INVALID
    return snap  # type: ignore[return-value]


def _summarize(snap: tuple[RequestSample, ...]) -> Summary:
    counts = {c: 0 for c in OutcomeClass}
    ok_values: list[int] = []
    refused_values: list[int] = []
    for sample in snap:
        counts[sample.outcome] += 1
        if sample.outcome is OutcomeClass.BUSINESS_OK:
            ok_values.append(sample.latency_us)
        elif sample.outcome in _REFUSAL_CLASSES:
            refused_values.append(sample.latency_us)
    return Summary(
        total=len(snap), counts=tuple((c.value, counts[c]) for c in OutcomeClass),
        business_ok=counts[OutcomeClass.BUSINESS_OK], refused=len(refused_values),
        business=(percentile(ok_values, 50), percentile(ok_values, 95), percentile(ok_values, 99)),
        refusal_latency=(percentile(refused_values, 50), percentile(refused_values, 95),
                         percentile(refused_values, 99)))


def summarize(samples: object, ids: object) -> Summary | OpsRefusal:
    """Counts and percentiles over a one-time snapshot of ``samples``; a fixed refusal for unusable input."""
    snap = _snapshot_samples(samples)
    if type(snap) is OpsReason:
        return ops_refusal(snap, ids)
    return _summarize(snap)


# --------------------------------------------------------------------------------------------------
# policy, operator reference, store

@dataclass(frozen=True, slots=True)
class ReportPolicy:
    """Report parameters: the measurement window and the declared refusal-fraction bound (default 1/2)."""

    window_us: int
    refusal_bound: Decimal = Decimal("0.5")

    def __post_init__(self) -> None:
        if not (is_exact_int(self.window_us, 1, MAX_WINDOW_US) and is_exact_decimal(self.refusal_bound)
                and Decimal(0) <= self.refusal_bound <= Decimal(1)):
            raise ValueError("REPORT_POLICY_INVALID")


def _policy_ok(value: object) -> bool:
    if type(value) is not ReportPolicy:
        return False
    try:
        ReportPolicy(value.window_us, value.refusal_bound)
    except (ValueError, AttributeError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class MeasurementRef:
    """An operator-supplied reference to a real measurement (id + sha256 digest). Never read or validated."""

    ref_id: str
    digest: str

    def __post_init__(self) -> None:
        if not (is_identity_text(self.ref_id) and is_digest(self.digest)):
            raise ValueError("MEASUREMENT_REF_INVALID")

    def __repr__(self) -> str:
        return "MeasurementRef(<redacted>)"


def _ref_ok(value: object) -> bool:
    if type(value) is not MeasurementRef:
        return False
    try:
        return is_identity_text(value.ref_id) and is_digest(value.digest)
    except AttributeError:
        return False


class CapacityStore:
    """Per-tenant bounded report store. Ids come from ``report_ids``; owners are registered via a callable.

    ``register_owner(tenant_id, company_id, kind, ref)`` is called once per stored report with
    ``kind="report_id"`` (for tests: ``FakeOwnership().add``). ``ids`` supplies refusal correlation ids.
    """

    def __init__(self, per_tenant_cap: object, report_ids: object, register_owner: object, ids: object) -> None:
        self._map = TenantBoundedMap(per_tenant_cap, ids)
        if not callable(register_owner):
            raise ValueError("CAPACITY_STORE_INVALID")  # noqa: TRY004 - fixed code, same family as the others
        self._report_ids = report_ids
        self._register = register_owner
        self.ids = ids

    def __repr__(self) -> str:
        return "CapacityStore(<redacted>)"

    def has_room(self, tenant_id: object) -> bool:
        return self._map.has_room(tenant_id)

    def count(self, tenant_id: object) -> int:
        return self._map.count(tenant_id)

    def _mint(self) -> str | None:
        try:
            value = self._report_ids.next_id()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        return value if correlation_ok(value) else None

    def _put(self, scope: object, report: CapacityReport) -> OpsRefusal | None:
        refusal = self._map.insert(scope.tenant_id, report.report_id, report)  # type: ignore[attr-defined]
        if refusal is not None:
            return refusal
        try:
            self._register(scope.tenant_id, scope.company_id, "report_id", report.report_id)  # type: ignore[attr-defined,operator]
        except Exception:  # noqa: BLE001 - an unregistered report would be unreadable: undo, fail closed
            self._map.remove(scope.tenant_id, report.report_id)  # type: ignore[attr-defined]
            return ops_refusal(OpsReason.DEPENDENCY_FAILED, self.ids)
        return None

    def _get(self, tenant_id: object, report_id: object) -> object:
        return self._map.get(tenant_id, report_id)


# --------------------------------------------------------------------------------------------------
# the report

def _flags(summary: Summary, bound: Decimal) -> tuple[OpsReason, ...]:
    flags: list[OpsReason] = []
    if summary.total and Decimal(summary.refused) > _RATE_CTX.multiply(bound, Decimal(summary.total)):
        flags += [OpsReason.REFUSALS_DOMINATE, OpsReason.UNRELIABLE_REFUSALS]
    if any(pv.reason is OpsReason.INSUFFICIENT_SAMPLES for pv in summary.business):
        flags.append(OpsReason.INSUFFICIENT_SAMPLES)
    return tuple(flags)


_PAYLOAD_FIELDS: Final = (
    "report_id", "grid", "created_at", "window_us", "total_samples", "counts", "business",
    "refusal_latency", "throughput_per_s", "refusal_fraction", "flags", "basis",
    "measurement_ref_digest", "authority",
)


def _payload_of(f: dict[str, object]) -> dict[str, object]:
    """The digest preimage: plain JSON-able values only (enums as their text, nested types flattened)."""
    return {
        "report_id": f["report_id"], "grid": f["grid"]._payload(),  # type: ignore[attr-defined]
        "created_at": f["created_at"], "window_us": f["window_us"], "total_samples": f["total_samples"],
        "counts": [list(pair) for pair in f["counts"]],  # type: ignore[attr-defined]
        "business": [pv._payload() for pv in f["business"]],  # type: ignore[attr-defined]
        "refusal_latency": [pv._payload() for pv in f["refusal_latency"]],  # type: ignore[attr-defined]
        "throughput_per_s": f["throughput_per_s"], "refusal_fraction": f["refusal_fraction"],
        "flags": [flag.value for flag in f["flags"]],  # type: ignore[attr-defined]
        "basis": f["basis"].value,  # type: ignore[attr-defined]
        "measurement_ref_digest": f["measurement_ref_digest"], "authority": f["authority"],
    }


@dataclass(frozen=True, slots=True, repr=False)
class CapacityReport:
    """Derived, frozen, digest-bound. There is deliberately NO field that can express "capacity proven"."""

    report_id: str
    grid: GridCell
    created_at: datetime
    window_us: int
    total_samples: int
    counts: tuple[tuple[str, int], ...]
    business: tuple[PercentileValue, PercentileValue, PercentileValue]
    refusal_latency: tuple[PercentileValue, PercentileValue, PercentileValue]
    throughput_per_s: Decimal
    refusal_fraction: Decimal
    flags: tuple[OpsReason, ...]
    basis: Basis
    measurement_ref_digest: str | None
    digest: str
    authority: str = AUTHORITY

    def _payload(self) -> dict[str, object]:
        return _payload_of({name: getattr(self, name) for name in _PAYLOAD_FIELDS})

    def __post_init__(self) -> None:
        try:
            ok = (correlation_ok(self.report_id) and is_valid_cell(self.grid)
                  and is_aware_datetime(self.created_at) and is_exact_int(self.window_us, 1, MAX_WINDOW_US)
                  and is_exact_int(self.total_samples, 0, MAX_SAMPLES)
                  and type(self.counts) is tuple and len(self.counts) == len(OutcomeClass)
                  and all(type(c) is tuple and len(c) == 2 and type(c[0]) is str and is_exact_int(c[1], 0, MAX_SAMPLES)
                          for c in self.counts)
                  and type(self.business) is tuple and len(self.business) == 3
                  and all(_valid_percentile_value(v) for v in self.business)
                  and type(self.refusal_latency) is tuple and len(self.refusal_latency) == 3
                  and all(_valid_percentile_value(v) for v in self.refusal_latency)
                  and is_exact_decimal(self.throughput_per_s) and is_exact_decimal(self.refusal_fraction)
                  and type(self.flags) is tuple and all(type(f) is OpsReason for f in self.flags)
                  and type(self.basis) is Basis
                  and (self.measurement_ref_digest is None or is_digest(self.measurement_ref_digest))
                  and (self.basis is Basis.OPERATOR_REFERENCE) is (self.measurement_ref_digest is not None)
                  and self.authority == AUTHORITY and is_digest(self.digest)
                  and self.digest == canonical_digest(self._payload()))
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            raise ValueError("CAPACITY_REPORT_INVALID")

    def __repr__(self) -> str:
        return "CapacityReport(<redacted>)"


def is_valid_report(value: object) -> bool:
    if type(value) is not CapacityReport:
        return False
    try:
        CapacityReport(value.report_id, value.grid, value.created_at, value.window_us, value.total_samples,
                       value.counts, value.business, value.refusal_latency, value.throughput_per_s,
                       value.refusal_fraction, value.flags, value.basis, value.measurement_ref_digest,
                       value.digest, value.authority)
    except (ValueError, AttributeError):
        return False
    return True


def _clock_now(clock: object) -> datetime | None:
    try:
        now = clock.now()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None
    return now if is_aware_datetime(now) else None


def _basis_for(snap: tuple[RequestSample, ...], ref: object) -> tuple[Basis, str | None] | OpsReason:
    if ref is None:
        return Basis.SCRIPTED_OFFLINE_FIXTURE, None
    if not _ref_ok(ref) or not all(s.basis is Basis.OPERATOR_REFERENCE for s in snap) or not snap:
        return OpsReason.BASIS_NOT_REAL_MEASUREMENT
    return Basis.OPERATOR_REFERENCE, ref.digest  # type: ignore[attr-defined]


def build_report(scope: object, ownership: object, entitlement: object, store: object, grid_cell: object,
                 samples: object, policy: object, clock: object, *,
                 measurement_ref: object = None) -> CapacityReport | OpsRefusal:
    """Build, store and return a ``CapacityReport`` for the scope's tenant, or a fixed ``OpsRefusal``.

    Fixed order: structure (cell, policy, clock, one-time sample snapshot, reference) -> entitlement ->
    ownership (no stored object is referenced when building) -> per-tenant quota -> compute. The tenant's
    report quota is advisory-checked first and enforced atomically by the store insert. Samples may carry
    ``OPERATOR_REFERENCE`` only together with a well-formed ``MeasurementRef``; otherwise the report is
    stamped ``SCRIPTED_OFFLINE_FIXTURE``. Never raises.
    """
    if type(store) is not CapacityStore:
        return ops_refusal(OpsReason.INPUT_INVALID, None)
    ids = store.ids
    try:
        if not (is_valid_scope(scope) and is_valid_cell(grid_cell) and _policy_ok(policy)
                and callable(getattr(clock, "now", None))):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        snap = _snapshot_samples(samples)
        if type(snap) is OpsReason:
            return ops_refusal(snap, ids)
        basis = _basis_for(snap, measurement_ref)
        if type(basis) is OpsReason:
            return ops_refusal(basis, ids)
        refusal = check_scope_order(scope, (), ownership, entitlement, ids,
                                    quota=lambda: store.has_room(scope.tenant_id))  # type: ignore[attr-defined]
        if refusal is not None:
            return refusal
        created_at = _clock_now(clock)
        report_id = store._mint()
        if created_at is None or report_id is None:
            return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
        summary = _summarize(snap)
        rate = throughput(summary.business_ok, policy.window_us)  # type: ignore[attr-defined]
        fraction = (_RATE_CTX.quantize(_RATE_CTX.divide(Decimal(summary.refused), Decimal(summary.total)),
                                       _SIX_PLACES) if summary.total else _ZERO_RATE)
        fields: dict[str, object] = {
            "report_id": report_id, "grid": grid_cell, "created_at": created_at,
            "window_us": policy.window_us, "total_samples": summary.total,  # type: ignore[attr-defined]
            "counts": summary.counts, "business": summary.business,
            "refusal_latency": summary.refusal_latency, "throughput_per_s": rate,
            "refusal_fraction": fraction, "flags": _flags(summary, policy.refusal_bound),  # type: ignore[attr-defined]
            "basis": basis[0], "measurement_ref_digest": basis[1], "authority": AUTHORITY,
        }
        digest = _digest_of(fields)
        report = CapacityReport(digest=digest, **fields)  # type: ignore[arg-type]
        stored = store._put(scope, report)
        return report if stored is None else stored
    except Exception:  # noqa: BLE001 - hostile input must end in a fixed refusal
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)


def _digest_of(fields: dict[str, object]) -> str:
    return canonical_digest(_payload_of(fields))


def read_report(scope: object, report_id: object, ownership: object, entitlement: object,
                store: object) -> CapacityReport | OpsRefusal:
    """Return a stored report. Entitlement, then ownership of ``report_id``, BEFORE the store is read.

    A foreign id and an unknown id give the identical ``NOT_FOUND`` refusal and the same port calls.
    """
    if type(store) is not CapacityStore:
        return ops_refusal(OpsReason.INPUT_INVALID, None)
    ids = store.ids
    try:
        refusal = check_scope_order(scope, (("report_id", report_id),), ownership, entitlement, ids)
        if refusal is not None:
            return refusal
        found = store._get(scope.tenant_id, report_id)  # type: ignore[attr-defined]
        if not is_valid_report(found):
            return ops_refusal(OpsReason.NOT_FOUND, ids)
        return found  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)
