"""A<->B comparison logic (S15, E15-3): pure functions over injected lane read results.

A MATCH here is a machine-read agreement of two reads, never a native 1C PASS. Differences are
signed multisets: ``count_in_B - count_in_A`` per item. The unrelated baseline difference (captured
before the operation) is subtracted, so it neither masks an expected effect nor imitates one.
Incomplete data gives INCONCLUSIVE, and so do lanes that are not provably distinct: the two
canonical lane identities (strip/casefold) must differ (SAME_LANE / LANE_IDENTITY_UNKNOWN), and a
baseline is bound to the identity pair it was captured for (BASELINE_PROVENANCE_MISMATCH). Keys and values are hidden unless ``show_values=True``.
Output is machine verified, not accountant attested.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .labels import LABEL_MACHINE_READ, LABEL_MACHINE_VERIFIED

__all__ = [
    "ComparisonResult",
    "ComparisonStatus",
    "DiffItem",
    "ExpectedDifferences",
    "LaneBaseline",
    "LaneReader",
    "LaneSnapshot",
    "compare_ab",
    "compare_via_readers",
    "signed_difference",
]


_KINDS = frozenset({"document", "movement", "balance"})
_DECIMAL_TEXT = re.compile(r"-?[0-9]+(\.[0-9]+)?\Z")


class ComparisonStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class DiffItem:
    """One comparable fact: kind is ``document``, ``movement`` or ``balance``.

    ``movement`` and ``balance`` items must carry a decimal ``value`` text. Balance items are
    DELTAS (pre-computed change of a balance caused by the operation), never absolute balances;
    the reader of a lane is responsible for producing them that way.
    """

    kind: str
    key: str
    value: str = ""


@dataclass(frozen=True, slots=True)
class LaneSnapshot:
    """Read result of one lane; ``complete`` False means the read was partial or failed."""

    complete: bool
    items: tuple[DiffItem, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpectedDifferences:
    """Items expected to exist only in B (``added``) or only in A (``removed``)."""

    added: tuple[DiffItem, ...] = ()
    removed: tuple[DiffItem, ...] = ()


@dataclass(frozen=True, slots=True)
class LaneBaseline:
    """Baseline snapshots bound to the (lane_a_identity, lane_b_identity) pair they were read
    from; ``compare_via_readers`` refuses a baseline whose pair differs from the current one."""

    snapshot_a: LaneSnapshot
    snapshot_b: LaneSnapshot
    lane_a_identity: str
    lane_b_identity: str


class LaneReader(Protocol):
    def source_identity(self, lane: str) -> str:
        """Canonical, non-empty identity of the physical source behind ``lane`` (for example the
        gateway base id). Two lanes are distinct only when their identities differ."""

    def read_snapshot(self, lane: str) -> LaneSnapshot:
        """Read-only snapshot of ``lane`` (through the test-lane MCP); may raise on failure.

        Balance items in the snapshot are pre-computed DELTAS, not absolute balances."""


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    status: ComparisonStatus
    label: str
    attestation: str
    extra_count: int = 0
    missing_count: int = 0
    # Only filled when show_values=True: (item, signed surplus) pairs.
    extra_items: tuple[tuple[DiffItem, int], ...] = ()
    missing_items: tuple[tuple[DiffItem, int], ...] = ()
    # Why the status is INCONCLUSIVE when it is caused by lane identity or provenance:
    # SAME_LANE, LANE_IDENTITY_UNKNOWN, BASELINE_PROVENANCE_MISMATCH. Codes only.
    reason: str = ""


def signed_difference(a: Iterable[DiffItem], b: Iterable[DiffItem]) -> Counter[DiffItem]:
    """Per item ``count_in_B - count_in_A``, zero entries dropped."""
    signed: Counter[DiffItem] = Counter(b)
    signed.subtract(Counter(a))
    return Counter({k: v for k, v in signed.items() if v != 0})


def _item_valid(item: object) -> bool:
    if (type(item) is not DiffItem or type(item.kind) is not str or item.kind not in _KINDS
            or type(item.key) is not str or type(item.value) is not str):
        return False
    if item.kind in ("movement", "balance"):
        return _DECIMAL_TEXT.fullmatch(item.value) is not None
    return True


def _items_valid(items: object) -> bool:
    return isinstance(items, (tuple, list)) and all(_item_valid(i) for i in items)


def _result(status: ComparisonStatus, extra: Counter[DiffItem] | None = None,
            missing: Counter[DiffItem] | None = None, show_values: bool = False,
            reason: str = "") -> ComparisonResult:
    extra = extra or Counter()
    missing = missing or Counter()
    return ComparisonResult(
        status, LABEL_MACHINE_READ, LABEL_MACHINE_VERIFIED,
        sum(extra.values()), sum(missing.values()),
        tuple(extra.items()) if show_values else (),
        tuple(missing.items()) if show_values else (), reason)


def _canonical(identity: object) -> str | None:
    if type(identity) is not str:
        return None
    return identity.strip().casefold() or None


def _identity_reason(identity_a: object, identity_b: object) -> str:
    """"" when the two identities are present and distinct, else the INCONCLUSIVE reason."""
    ca, cb = _canonical(identity_a), _canonical(identity_b)
    if ca is None or cb is None:
        return "LANE_IDENTITY_UNKNOWN"
    return "SAME_LANE" if ca == cb else ""


def compare_ab(baseline_a: LaneSnapshot, baseline_b: LaneSnapshot, post_a: LaneSnapshot,
               post_b: LaneSnapshot, expected: ExpectedDifferences, *,
               show_values: bool = False, lane_a_identity: str | None = None,
               lane_b_identity: str | None = None) -> ComparisonResult:
    """Compare the observed A<->B difference, net of the baseline, with the expected multiset.

    Extra = observed but not expected; missing = expected but not observed. Any incomplete
    snapshot, an unknown item kind, or a movement/balance item without a decimal value yields
    INCONCLUSIVE (never MATCH). Identities are optional for this pure function, but when either
    is given both must be present and differ after strip/casefold, else INCONCLUSIVE with reason
    SAME_LANE or LANE_IDENTITY_UNKNOWN.
    """
    if lane_a_identity is not None or lane_b_identity is not None:
        why = _identity_reason(lane_a_identity, lane_b_identity)
        if why:
            return _result(ComparisonStatus.INCONCLUSIVE, reason=why)
    for snap in (baseline_a, baseline_b, post_a, post_b):
        if (type(snap) is not LaneSnapshot or snap.complete is not True
                or not _items_valid(snap.items)):
            return _result(ComparisonStatus.INCONCLUSIVE)
    if (type(expected) is not ExpectedDifferences or not _items_valid(expected.added)
            or not _items_valid(expected.removed)):
        return _result(ComparisonStatus.INCONCLUSIVE)
    observed = signed_difference(post_a.items, post_b.items)
    observed.subtract(signed_difference(baseline_a.items, baseline_b.items))
    wanted = signed_difference(expected.removed, expected.added)
    observed.subtract(wanted)
    leftover = {k: v for k, v in observed.items() if v != 0}
    if not leftover:
        return _result(ComparisonStatus.MATCH, show_values=show_values)
    extra = Counter({k: v for k, v in leftover.items() if v > 0})
    missing = Counter({k: -v for k, v in leftover.items() if v < 0})
    return _result(ComparisonStatus.MISMATCH, extra, missing, show_values)


def compare_via_readers(reader: LaneReader, lane_a: str, lane_b: str,
                        baseline: LaneBaseline, expected: ExpectedDifferences, *,
                        show_values: bool = False) -> ComparisonResult:
    """Read both lanes through the injected reader, then compare; a failed read is INCONCLUSIVE.

    The lanes must have distinct canonical names and distinct canonical source identities
    (``reader.source_identity``), and ``baseline`` must have been captured for exactly this
    identity pair; otherwise INCONCLUSIVE (SAME_LANE, LANE_IDENTITY_UNKNOWN or
    BASELINE_PROVENANCE_MISMATCH).
    """
    if _canonical(lane_a) is None or _canonical(lane_b) is None:
        return _result(ComparisonStatus.INCONCLUSIVE, reason="LANE_IDENTITY_UNKNOWN")
    if _canonical(lane_a) == _canonical(lane_b):
        return _result(ComparisonStatus.INCONCLUSIVE, reason="SAME_LANE")
    try:
        identity_a = reader.source_identity(lane_a)
        identity_b = reader.source_identity(lane_b)
    except Exception:  # noqa: BLE001 - an unknown identity is never proof of distinct lanes
        return _result(ComparisonStatus.INCONCLUSIVE, reason="LANE_IDENTITY_UNKNOWN")
    why = _identity_reason(identity_a, identity_b)
    if why:
        return _result(ComparisonStatus.INCONCLUSIVE, reason=why)
    if (type(baseline) is not LaneBaseline
            or _canonical(baseline.lane_a_identity) != _canonical(identity_a)
            or _canonical(baseline.lane_b_identity) != _canonical(identity_b)):
        return _result(ComparisonStatus.INCONCLUSIVE, reason="BASELINE_PROVENANCE_MISMATCH")
    try:
        post_a = reader.read_snapshot(lane_a)
        post_b = reader.read_snapshot(lane_b)
    except Exception:  # noqa: BLE001 - a failed read is incomplete data, never agreement
        return _result(ComparisonStatus.INCONCLUSIVE)
    return compare_ab(baseline.snapshot_a, baseline.snapshot_b, post_a, post_b, expected,
                      show_values=show_values, lane_a_identity=identity_a,
                      lane_b_identity=identity_b)
