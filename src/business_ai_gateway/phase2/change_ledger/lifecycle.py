"""Fail-closed startup checkpoint preflight for the PostgreSQL change ledger.

This module is deliberately not an admission hook. The repository does not yet have a shared
fence covering every ledger mutation and physical dispatch, a read-only S12 suffix inspector, or
a reviewed recovery-to-READY transition. A successful preflight therefore remains NOT_READY.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from ._common import Scope
from .checkpoint import CheckpointRecord, CheckpointSink, SignatureVerifier


class LifecycleReason(StrEnum):
    """Stable diagnostic codes; provider exceptions and untrusted text are never exposed."""

    CHAIN_UNAVAILABLE = "CHAIN_UNAVAILABLE"
    CHAIN_INVALID = "CHAIN_INVALID"
    CHECKPOINT_UNAVAILABLE = "CHECKPOINT_UNAVAILABLE"
    CHECKPOINT_MISSING = "CHECKPOINT_MISSING"
    CHECKPOINT_SCOPE_MISMATCH = "CHECKPOINT_SCOPE_MISMATCH"
    CHECKPOINT_INVALID = "CHECKPOINT_INVALID"
    CHECKPOINT_NOT_ANCESTOR = "CHECKPOINT_NOT_ANCESTOR"
    CHECKPOINT_SUFFIX_UNAVAILABLE = "CHECKPOINT_SUFFIX_UNAVAILABLE"
    CHECKPOINT_SUFFIX_INVALID = "CHECKPOINT_SUFFIX_INVALID"
    CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT = "CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT"
    CHECKPOINT_SUFFIX_UNSUPPORTED = "CHECKPOINT_SUFFIX_UNSUPPORTED"
    SHARED_FENCE_UNAVAILABLE = "SHARED_FENCE_UNAVAILABLE"


class LifecycleStatus(StrEnum):
    NOT_READY = "NOT_READY"


class LifecycleLedger(Protocol):
    async def verify_chain(self, scope: Scope) -> dict[str, Any]: ...
    async def lifecycle_checkpoint_suffix(self, scope: Scope, checkpoint_seq: int,
                                          checkpoint_hash: str, limit: int = 128) -> dict: ...


@dataclass(frozen=True)
class LifecycleResult:
    """Read-only preflight outcome. It never authorizes a writer or dispatch permit."""

    scope: Scope
    status: LifecycleStatus
    reason: LifecycleReason
    checkpoint_seq: int | None = None
    checkpoint_hash: str | None = None
    chain_count: int | None = None
    suffix_event_count: int | None = None
    suffix_head_seq: int | None = None


_REQUIRED_CHECKPOINT_EVENTS = {
    "APPROVED", "APPLYING", "COMPLETE_SUCCESS", "COMPLETE_PRE_WRITE_REFUSAL", "OPERATOR_RESOLVE",
}


def _is_hash(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value))


def _classify_checkpoint_suffix(scope: Scope, record: CheckpointRecord,
                                result: Any, expected_head_seq: int
                                ) -> tuple[LifecycleReason | None, int, int | None]:
    """Validate a bounded ordered tail; only proven, terminal T13 events may remain unanchored."""
    expected_keys = {"tenant_id", "company_id", "checkpoint_seq", "checkpoint_hash",
                     "anchor_matches", "head_seq", "head_hash", "has_more", "events"}
    if type(result) is not dict or set(result) != expected_keys:
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, None
    if (result["tenant_id"] != scope.tenant_id or result["company_id"] != scope.company_id
            or type(result["checkpoint_seq"]) is not int or result["checkpoint_seq"] != record.seq
            or result["checkpoint_hash"] != record.head_hash
            or type(result["anchor_matches"]) is not bool):
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, None
    if result["anchor_matches"] is not True:
        return LifecycleReason.CHECKPOINT_NOT_ANCESTOR, 0, None

    head_seq = result["head_seq"]
    head_hash = result["head_hash"]
    events = result["events"]
    if (type(head_seq) is not int or head_seq != expected_head_seq or head_seq < record.seq
            or type(result["has_more"]) is not bool or result["has_more"] is not False
            or type(events) is not list or len(events) > 128):
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, None
    if head_seq == 0:
        if head_hash is not None or events:
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, head_seq
    elif not _is_hash(head_hash):
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, head_seq

    seen_changes: set[UUID] = set()
    seen_events: set[UUID] = set()
    expected_seq = record.seq + 1
    for event in events:
        if type(event) is not dict or set(event) != {
                "seq", "event_id", "change_id", "event_type", "payload", "hash", "record"}:
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        try:
            event_id = UUID(event["event_id"])
            change_id = UUID(event["change_id"]) if event["change_id"] is not None else None
        except (ValueError, TypeError, AttributeError):
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        if event_id in seen_events:
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        seen_events.add(event_id)
        if (type(event["seq"]) is not int or event["seq"] != expected_seq
                or not _is_hash(event["hash"]) or not isinstance(event["event_type"], str)
                or type(event["payload"]) is not dict):
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        expected_seq += 1

        if event["event_type"] in _REQUIRED_CHECKPOINT_EVENTS:
            return LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT, len(events), head_seq
        if event["event_type"] == "RESOLVE_UNKNOWN":
            if event["payload"].get("found") is False:
                return LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT, len(events), head_seq
            return LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED, len(events), head_seq
        if event["event_type"] != "VERIFY_VERIFIED":
            return LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED, len(events), head_seq

        state = event["record"]
        if (change_id is None or type(state) is not dict or set(state) != {
                "execution_state", "verification_state", "call_ownership",
                "reservation_state", "dispatch_state"}):
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        if change_id in seen_changes:
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        seen_changes.add(change_id)
        if (state["execution_state"] != "APPLIED"
                or state["verification_state"] != "VERIFIED"
                or state["call_ownership"] != "PROVEN_FINISHED"
                or state["reservation_state"] != "CONSUMED"
                or state["dispatch_state"] != "DISPATCHED"
                or not event["payload"]):
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq

    if expected_seq - 1 != head_seq:
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
    if events and events[-1]["hash"] != head_hash:
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
    if not events and (head_seq != record.seq or head_hash != record.head_hash):
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, head_seq
    return None, len(events), head_seq


class LifecycleCoordinator:
    """Check chain integrity and the authenticated provider latest record without mutation.

    Dependency timeouts request cancellation; they are cooperative and are not a hard wall-clock
    guarantee if an adapter suppresses cancellation. Production adapters must enforce their own
    transport deadlines if startup liveness depends on a strict bound.

    The class intentionally has no READY result. Once a reviewed shared fence, suffix reader,
    bounded recovery contract, and durable READY transition exist, a separate implementation can
    extend this preflight without treating a checkpoint signature as proof of anti-rollback.
    """

    def __init__(self, ledger: LifecycleLedger, sink: CheckpointSink,
                 verifier: SignatureVerifier, *, dependency_timeout_seconds: float = 5.0):
        if (isinstance(dependency_timeout_seconds, bool)
                or not isinstance(dependency_timeout_seconds, (int, float))
                or not math.isfinite(dependency_timeout_seconds)
                or dependency_timeout_seconds <= 0):
            raise ValueError("dependency_timeout_seconds must be a finite positive number")
        self._ledger = ledger
        self._sink = sink
        self._verifier = verifier
        self._dependency_timeout_seconds = float(dependency_timeout_seconds)

    async def preflight(self, scope: Scope) -> LifecycleResult:
        """Return diagnostic state while keeping effectful admission disabled."""
        try:
            chain = await asyncio.wait_for(
                self._ledger.verify_chain(scope), timeout=self._dependency_timeout_seconds,
            )
        except Exception:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHAIN_UNAVAILABLE)

        count = chain.get("count") if type(chain) is dict else None
        if (type(chain) is not dict or chain.get("ok") is not True
                or type(count) is not int or count < 0):
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHAIN_INVALID,
                                   chain_count=count if isinstance(count, int) else None)
        chain_count = count

        try:
            record = await asyncio.wait_for(
                self._sink.latest(scope), timeout=self._dependency_timeout_seconds,
            )
        except Exception:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_UNAVAILABLE,
                                   chain_count=chain_count if isinstance(chain_count, int) else None)

        if record is None:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_MISSING,
                                   chain_count=chain_count if isinstance(chain_count, int) else None)
        if type(record) is not CheckpointRecord:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_INVALID,
                                   chain_count=chain_count if isinstance(chain_count, int) else None)
        try:
            scope_fields_valid = (
                type(record.tenant_id) is str and type(record.company_id) is str
                and type(scope.tenant_id) is str and type(scope.company_id) is str
            )
            scope_matches = (scope_fields_valid and record.tenant_id == scope.tenant_id
                             and record.company_id == scope.company_id)
        except Exception:
            scope_matches = False
            malformed_scope = True
        else:
            malformed_scope = not scope_fields_valid
        if malformed_scope:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_INVALID,
                                   chain_count=chain_count if isinstance(chain_count, int) else None)
        if not scope_matches:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_SCOPE_MISMATCH,
                                   chain_count=chain_count if isinstance(chain_count, int) else None)

        try:
            structurally_valid = (
                type(record.seq) is int and record.seq > 0
                and isinstance(record.head_hash, str) and len(record.head_hash) == 64
                and all(ch in "0123456789abcdef" for ch in record.head_hash)
                and isinstance(record.signature, str) and bool(record.signature)
                and bool(record.key_id) and bool(record.sink_id)
                and self._verifier.verify(record.key_id, record.signing_payload(), record.signature)
            )
        except Exception:
            structurally_valid = False
        if not structurally_valid:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_INVALID,
                                   chain_count=chain_count if isinstance(chain_count, int) else None)

        try:
            suffix = await asyncio.wait_for(
                self._ledger.lifecycle_checkpoint_suffix(scope, record.seq, record.head_hash),
                timeout=self._dependency_timeout_seconds,
            )
        except Exception:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_SUFFIX_UNAVAILABLE,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        suffix_reason, suffix_count, suffix_head = _classify_checkpoint_suffix(
            scope, record, suffix, chain_count,
        )
        if suffix_reason is not None:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY, suffix_reason,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count, suffix_event_count=suffix_count,
                                   suffix_head_seq=suffix_head)

        # This remains diagnostic only: no complete cross-process mutation/dispatch fence,
        # recovery-to-READY contract, or operational provider is available in this slice.
        return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                               LifecycleReason.SHARED_FENCE_UNAVAILABLE,
                               checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                               chain_count=chain_count, suffix_event_count=suffix_count,
                               suffix_head_seq=suffix_head)
