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
    SHARED_FENCE_UNAVAILABLE = "SHARED_FENCE_UNAVAILABLE"


class LifecycleStatus(StrEnum):
    NOT_READY = "NOT_READY"


class LifecycleLedger(Protocol):
    async def verify_chain(self, scope: Scope) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LifecycleResult:
    """Read-only preflight outcome. It never authorizes a writer or dispatch permit."""

    scope: Scope
    status: LifecycleStatus
    reason: LifecycleReason
    checkpoint_seq: int | None = None
    checkpoint_hash: str | None = None
    chain_count: int | None = None


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
            scope_matches = (record.tenant_id == scope.tenant_id
                             and record.company_id == scope.company_id)
        except Exception:
            scope_matches = False
            malformed_scope = True
        else:
            malformed_scope = False
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

        # The checks above are diagnostic only: no cross-process mutation/dispatch fence,
        # ordered-suffix validation, or durable READY transition is available in this slice.
        return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                               LifecycleReason.SHARED_FENCE_UNAVAILABLE,
                               checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                               chain_count=chain_count if isinstance(chain_count, int) else None)
