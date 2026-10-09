"""Phase 2 (R2-US-033): one data state for a comparison.

A comparison runs against an immutable snapshot identified by a canonical-JSON sha256 content
digest and a known-at instant. Both sides must reference the same snapshot, and each side reports
the digest it actually read; if the source changed between the two reads (a concurrent correction)
the run is INCONCLUSIVE with a reason, never PASS. A rerun (including a backdated one) is a NEW
run that supersedes the earlier one in the listing; the earlier record is never overwritten or
deleted and its numbers stay exactly as recorded.

Pure in-memory, thread-safe, injectable clock. A PASS here is numeric equality on one data state
only; it is NOT native evidence attestation or validation approval.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, Inexact, localcontext
from enum import StrEnum
from typing import Final

from ._identity import exact_text

__all__ = [
    "ComparisonSnapshotError", "ComparisonState", "RunLedger", "RunRecord", "RunView",
    "SideRead", "Snapshot", "SnapshotStore", "canonical_digest", "canonical_json",
]

_EXACT: Final = Context(prec=60, Emin=-999_999, Emax=999_999)
_EXACT.traps[Inexact] = True
_MAX_DEPTH: Final = 32
_MAX_EXPONENT: Final = 100

Clock = Callable[[], datetime]


class ComparisonSnapshotError(ValueError):
    """Invalid input or unusable reference. Only a fixed outward ``code`` is exposed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ComparisonState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ComparisonSnapshotError("TIMEZONE_REQUIRED")
    return value.astimezone(UTC)


def _dec(value: object) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ComparisonSnapshotError("FINITE_DECIMAL_REQUIRED")
    if abs(value.adjusted()) > _MAX_EXPONENT:
        raise ComparisonSnapshotError("DECIMAL_PRECISION_EXCEEDED")
    try:
        with localcontext(_EXACT):
            norm = value.normalize()
    except ArithmeticError:
        raise ComparisonSnapshotError("DECIMAL_PRECISION_EXCEEDED") from None
    return Decimal(0) if norm == 0 else norm


def _dec_text(value: Decimal) -> str:
    return format(_dec(value), "f")


def _encode(value: object, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise ComparisonSnapshotError("PAYLOAD_TOO_DEEP")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return {"$dec": _dec_text(value)}
    if isinstance(value, datetime):
        return {"$ts": _utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ComparisonSnapshotError("PAYLOAD_KEY_NOT_TEXT")
            out[key] = _encode(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_encode(item, depth + 1) for item in value]
    # float is refused on purpose: binary rounding must never reach a financial digest.
    raise ComparisonSnapshotError("PAYLOAD_TYPE_UNSUPPORTED")


def canonical_json(payload: object) -> str:
    """Sorted-key, compact, ASCII JSON; Decimals normalised, datetimes aware-UTC."""
    return json.dumps(_encode(payload), sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def canonical_digest(payload: object) -> str:
    return _sha(canonical_json(payload))


def _ident(value: object, code: str) -> str:
    text = exact_text(value)
    if not text:
        raise ComparisonSnapshotError(code)
    return text


@dataclass(frozen=True, slots=True)
class Snapshot:
    tenant_id: str
    snapshot_id: str
    digest: str
    known_at: datetime
    canonical: str


class SnapshotStore:
    """Write-once snapshot registry. A snapshot cannot be replaced; identical re-create is idempotent."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._items: dict[tuple[str, str], Snapshot] = {}

    def now(self) -> datetime:
        return _utc(self._clock())

    def create(self, tenant_id: str, payload: object, *, known_at: datetime | None = None) -> Snapshot:
        tenant = _ident(tenant_id, "TENANT_REQUIRED")
        now = self.now()
        instant = now if known_at is None else _utc(known_at)
        if instant > now:
            raise ComparisonSnapshotError("KNOWN_AT_IN_FUTURE")
        text = canonical_json(payload)
        digest = _sha(text)
        stamp = instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        snapshot_id = "snap-" + _sha(json.dumps([tenant, digest, stamp]))[:24]
        with self._lock:
            existing = self._items.get((tenant, snapshot_id))
            if existing is not None:
                return existing
            snap = Snapshot(tenant, snapshot_id, digest, instant, text)
            self._items[(tenant, snapshot_id)] = snap
            return snap

    def get(self, tenant_id: str, snapshot_id: str) -> Snapshot | None:
        with self._lock:
            return self._items.get((exact_text(tenant_id), exact_text(snapshot_id)))


@dataclass(frozen=True, slots=True)
class SideRead:
    """What one side observed: the snapshot it was told to read, the digest it actually saw, its numbers."""

    side: str
    snapshot_id: str
    observed_digest: str
    values: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    seq: int
    tenant_id: str
    comparison_key: str
    state: ComparisonState
    reason_code: str
    snapshot_id: str
    snapshot_digest: str
    known_at: datetime
    recorded_at: datetime
    native_values: tuple[tuple[str, Decimal], ...]
    gateway_values: tuple[tuple[str, Decimal], ...]
    differences: tuple[str, ...]
    supersedes: str | None
    authority: str = "EVALUATION_ONLY"


@dataclass(frozen=True, slots=True)
class RunView:
    record: RunRecord
    status: str  # "CURRENT" or "SUPERSEDED"
    superseded_by: str | None


def _values(read: SideRead) -> tuple[tuple[str, Decimal], ...]:
    if not isinstance(read, SideRead) or not isinstance(read.values, Mapping):
        raise ComparisonSnapshotError("SIDE_READ_INVALID")
    out = []
    for key, value in read.values.items():
        if not isinstance(key, str) or not key:
            raise ComparisonSnapshotError("SIDE_READ_INVALID")
        out.append((key, _dec(value)))
    return tuple(sorted(out, key=lambda kv: kv[0]))


class RunLedger:
    """Append-only run history. Supersession is a listing relation; no record is ever mutated or removed."""

    def __init__(self, store: SnapshotStore) -> None:
        self._store = store
        self._lock = threading.RLock()
        self._runs: list[RunRecord] = []
        self._superseded_by: dict[str, str] = {}

    def run(self, tenant_id: str, comparison_key: str, native: SideRead, gateway: SideRead,
            *, snapshot_id: str, rerun_of: str | None = None) -> RunRecord:
        tenant = _ident(tenant_id, "TENANT_REQUIRED")
        key = _ident(comparison_key, "COMPARISON_KEY_REQUIRED")
        snap_ref = _ident(snapshot_id, "SNAPSHOT_REF_REQUIRED")
        n_vals, g_vals = _values(native), _values(gateway)
        recorded_at = self._store.now()
        snap = self._store.get(tenant, snap_ref)
        state, reason, diffs = self._decide(snap, snap_ref, native, gateway, n_vals, g_vals)
        with self._lock:
            if rerun_of is not None:
                prior = self._find(tenant, rerun_of)
                if prior is None or prior.comparison_key != key:
                    raise ComparisonSnapshotError("RERUN_TARGET_UNKNOWN")
                if prior.run_id in self._superseded_by:
                    raise ComparisonSnapshotError("RERUN_TARGET_ALREADY_SUPERSEDED")
            seq = len(self._runs) + 1
            record = RunRecord(
                run_id=f"run-{seq:06d}", seq=seq, tenant_id=tenant, comparison_key=key,
                state=state, reason_code=reason, snapshot_id=snap_ref,
                snapshot_digest=snap.digest if snap else "", known_at=snap.known_at if snap else recorded_at,
                recorded_at=recorded_at, native_values=n_vals, gateway_values=g_vals,
                differences=diffs, supersedes=rerun_of)
            self._runs.append(record)
            if rerun_of is not None:
                self._superseded_by[rerun_of] = record.run_id
            return record

    @staticmethod
    def _decide(snap: Snapshot | None, snap_ref: str, native: SideRead, gateway: SideRead,
                n_vals: tuple[tuple[str, Decimal], ...], g_vals: tuple[tuple[str, Decimal], ...],
                ) -> tuple[ComparisonState, str, tuple[str, ...]]:
        inc = ComparisonState.INCONCLUSIVE
        if native.snapshot_id != gateway.snapshot_id or native.snapshot_id != snap_ref:
            return inc, "SNAPSHOT_REFERENCE_MISMATCH", ()
        if snap is None:
            return inc, "SNAPSHOT_UNKNOWN", ()
        if _sha(snap.canonical) != snap.digest:
            return inc, "SNAPSHOT_INTEGRITY_FAILED", ()
        if native.observed_digest != gateway.observed_digest:
            return inc, "SOURCE_CHANGED_BETWEEN_READS", ()
        if native.observed_digest != snap.digest:
            return inc, "SNAPSHOT_DIGEST_MISMATCH", ()
        if not n_vals or not g_vals:
            return inc, "NO_OBSERVATIONS", ()
        n_map, g_map = dict(n_vals), dict(g_vals)
        diffs = tuple(k for k in sorted(n_map.keys() | g_map.keys()) if n_map.get(k) != g_map.get(k))
        if diffs:
            return ComparisonState.FAIL, "VALUES_DIFFER", diffs
        return ComparisonState.PASS, "ALL_VALUES_EQUAL", ()

    def _find(self, tenant: str, run_id: str) -> RunRecord | None:
        for rec in self._runs:
            if rec.run_id == run_id and rec.tenant_id == tenant:
                return rec
        return None

    def get(self, tenant_id: str, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._find(exact_text(tenant_id), exact_text(run_id))

    def list_runs(self, tenant_id: str, comparison_key: str) -> tuple[RunView, ...]:
        tenant, key = exact_text(tenant_id), exact_text(comparison_key)
        with self._lock:
            return tuple(
                RunView(r, "SUPERSEDED" if r.run_id in self._superseded_by else "CURRENT",
                        self._superseded_by.get(r.run_id))
                for r in self._runs if r.tenant_id == tenant and r.comparison_key == key)
