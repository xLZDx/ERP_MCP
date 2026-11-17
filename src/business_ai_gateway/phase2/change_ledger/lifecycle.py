"""Fail-closed startup checkpoint preflight for the PostgreSQL change ledger.

This module is deliberately not an admission hook. The repository does not yet have a shared
fence covering every ledger mutation and physical dispatch, a qualified anti-rollback provider,
or a reviewed recovery-to-READY transition. A successful preflight therefore remains NOT_READY.
"""
from __future__ import annotations

import asyncio
import math
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from ._common import Scope
from .checkpoint import (
    CheckpointKeyAuthorization,
    CheckpointKeyAuthorizationAuthority,
    CheckpointKeyAuthorizationBasis,
    CheckpointLatestnessAuthority,
    CheckpointLatestnessEvidence,
    CheckpointRecord,
    CheckpointSink,
    SignatureVerifier,
    checkpoint_identity,
)


class LifecycleReason(StrEnum):
    """Stable diagnostic codes; provider exceptions and untrusted text are never exposed."""

    CHAIN_UNAVAILABLE = "CHAIN_UNAVAILABLE"
    CHAIN_INVALID = "CHAIN_INVALID"
    CHECKPOINT_UNAVAILABLE = "CHECKPOINT_UNAVAILABLE"
    CHECKPOINT_MISSING = "CHECKPOINT_MISSING"
    CHECKPOINT_SCOPE_MISMATCH = "CHECKPOINT_SCOPE_MISMATCH"
    CHECKPOINT_INVALID = "CHECKPOINT_INVALID"
    CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE = "CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE"
    CHECKPOINT_KEY_AUTHORIZATION_DENIED = "CHECKPOINT_KEY_AUTHORIZATION_DENIED"
    CHECKPOINT_KEY_AUTHORIZATION_INVALID = "CHECKPOINT_KEY_AUTHORIZATION_INVALID"
    CHECKPOINT_LATESTNESS_UNAVAILABLE = "CHECKPOINT_LATESTNESS_UNAVAILABLE"
    CHECKPOINT_LATESTNESS_INVALID = "CHECKPOINT_LATESTNESS_INVALID"
    CHECKPOINT_NOT_ANCESTOR = "CHECKPOINT_NOT_ANCESTOR"
    CHECKPOINT_SUFFIX_UNAVAILABLE = "CHECKPOINT_SUFFIX_UNAVAILABLE"
    CHECKPOINT_SUFFIX_INVALID = "CHECKPOINT_SUFFIX_INVALID"
    CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT = "CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT"
    CHECKPOINT_SUFFIX_UNSUPPORTED = "CHECKPOINT_SUFFIX_UNSUPPORTED"
    SHARED_FENCE_UNAVAILABLE = "SHARED_FENCE_UNAVAILABLE"
    BASE_PREFLIGHT_DEADLINE_EXCEEDED = "BASE_PREFLIGHT_DEADLINE_EXCEEDED"


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


@dataclass(frozen=True)
class BaseRecoverySnapshot:
    """Exact bounded begin-recovery response used only to bind diagnostic preflight results."""

    base_fingerprint: str
    epoch: int
    manifest_digest: str
    scopes: tuple[Scope, ...]

    def __post_init__(self) -> None:
        if (type(self.base_fingerprint) is not str or not self.base_fingerprint
                or self.base_fingerprint != self.base_fingerprint.strip()
                or type(self.epoch) is not int or self.epoch < 1
                or not _is_hash(self.manifest_digest)
                or type(self.scopes) is not tuple or not 1 <= len(self.scopes) <= 64
                or any(type(scope) is not Scope for scope in self.scopes)):
            raise ValueError("BASE_RECOVERY_SNAPSHOT_INVALID")
        identities = tuple((scope.tenant_id, scope.company_id) for scope in self.scopes)
        if (any(not tenant or not company for tenant, company in identities)
                or identities != tuple(sorted(set(identities)))):
            raise ValueError("BASE_RECOVERY_SNAPSHOT_INVALID")

    @classmethod
    def from_begin_result(cls, base_fingerprint: str, result: Any) -> BaseRecoverySnapshot:
        """Parse the exact SQL result shape; reject partial or reordered manifests before I/O."""
        expected = {"base_fingerprint", "state", "epoch", "manifest_digest", "scope_count",
                    "scope_manifest"}
        if (type(result) is not dict or set(result) != expected
                or result.get("base_fingerprint") != base_fingerprint
                or result.get("state") != "RECOVERING"):
            raise ValueError("BASE_RECOVERY_SNAPSHOT_INVALID")
        raw_manifest = result.get("scope_manifest")
        if (type(result.get("scope_count")) is not int
                or type(raw_manifest) is not list
                or result["scope_count"] != len(raw_manifest)):
            raise ValueError("BASE_RECOVERY_SNAPSHOT_INVALID")
        scopes: list[Scope] = []
        for item in raw_manifest:
            if (type(item) is not dict or set(item) != {"tenant_id", "company_id"}
                    or type(item["tenant_id"]) is not str or not item["tenant_id"]
                    or type(item["company_id"]) is not str or not item["company_id"]):
                raise ValueError("BASE_RECOVERY_SNAPSHOT_INVALID")
            scopes.append(Scope(item["tenant_id"], item["company_id"]))
        return cls(base_fingerprint, result.get("epoch"), result.get("manifest_digest"),
                   tuple(scopes))


@dataclass(frozen=True)
class BaseRecoveryPreflightResult:
    """Per-scope diagnostics bound to one begin snapshot; never an admission/readiness result."""

    snapshot: BaseRecoverySnapshot
    scope_results: tuple[LifecycleResult, ...]

    def __post_init__(self) -> None:
        if (type(self.snapshot) is not BaseRecoverySnapshot
                or type(self.scope_results) is not tuple
                or len(self.scope_results) != len(self.snapshot.scopes)):
            raise ValueError("BASE_RECOVERY_PREFLIGHT_INVALID")
        for scope, result in zip(self.snapshot.scopes, self.scope_results, strict=True):
            if (type(result) is not LifecycleResult or result.scope != scope
                    or result.status is not LifecycleStatus.NOT_READY):
                raise ValueError("BASE_RECOVERY_PREFLIGHT_INVALID")


_BASE_RECOVERY_PREFLIGHT_CONCURRENCY = 4


_REQUIRED_CHECKPOINT_EVENTS = frozenset({
    "APPROVED", "APPLYING", "COMPLETE_SUCCESS", "COMPLETE_PRE_WRITE_REFUSAL", "OPERATOR_RESOLVE",
})


def _is_hash(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value))


def _valid_key_authorization(scope: Scope, record: CheckpointRecord,
                             evidence: Any, *, verified_public_key_digest: str,
                             challenge_nonce: str) -> bool:
    """Check strict response shape and binding after the trusted port verifies its history."""
    if type(evidence) is not CheckpointKeyAuthorization:
        return False
    if (type(evidence.tenant_id) is not str or evidence.tenant_id != scope.tenant_id
            or type(evidence.company_id) is not str or evidence.company_id != scope.company_id
            or type(evidence.key_id) is not str or evidence.key_id != record.key_id
            or not _is_hash(evidence.public_key_digest)
            or evidence.public_key_digest != verified_public_key_digest
            or not _is_hash(evidence.checkpoint_digest)
            or not _is_hash(evidence.challenge_nonce)
            or evidence.challenge_nonce != challenge_nonce
            or type(evidence.authority_id) is not str or not evidence.authority_id
            or len(evidence.authority_id) > 128
            or type(evidence.authority_revision) is not int
            or evidence.authority_revision < 1
            or type(evidence.authority_event_id) is not str or not evidence.authority_event_id
            or len(evidence.authority_event_id) > 128
            or type(evidence.policy_version) is not str or not evidence.policy_version
            or len(evidence.policy_version) > 128
            or type(evidence.basis) is not CheckpointKeyAuthorizationBasis):
        return False
    try:
        if evidence.checkpoint_digest != checkpoint_identity(record):
            return False
    except Exception:
        return False

    if evidence.basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT:
        accepted_at = evidence.accepted_at
        return (type(evidence.receipt_id) is str and bool(evidence.receipt_id)
                and len(evidence.receipt_id) <= 256
                and type(accepted_at) is datetime
                and accepted_at.tzinfo is not None and accepted_at.utcoffset() is not None)
    if evidence.basis is CheckpointKeyAuthorizationBasis.ACTIVE:
        return evidence.receipt_id is None and evidence.accepted_at is None
    return False


def _valid_latestness_evidence(scope: Scope, record: CheckpointRecord,
                               evidence: Any, *, challenge_nonce: str) -> bool:
    """Check strict receipt shape and exact record/challenge binding after authority verification."""
    if type(evidence) is not CheckpointLatestnessEvidence:
        return False
    if (type(evidence.tenant_id) is not str or evidence.tenant_id != scope.tenant_id
            or type(evidence.company_id) is not str or evidence.company_id != scope.company_id
            or not _is_hash(evidence.checkpoint_digest)
            or type(evidence.challenge_nonce) is not str
            or evidence.challenge_nonce != challenge_nonce
            or type(evidence.provider_id) is not str or not evidence.provider_id
            or len(evidence.provider_id) > 128
            or type(record.sink_id) is not str or evidence.provider_id != record.sink_id
            or type(evidence.provider_revision) is not int or evidence.provider_revision < 1
            or type(evidence.authority_id) is not str or not evidence.authority_id
            or len(evidence.authority_id) > 128
            or type(evidence.authority_revision) is not int or evidence.authority_revision < 1
            or type(evidence.authority_event_id) is not str or not evidence.authority_event_id
            or len(evidence.authority_event_id) > 128
            or type(evidence.policy_version) is not str or not evidence.policy_version
            or len(evidence.policy_version) > 128
            or not _is_hash(evidence.proof_digest)):
        return False
    try:
        return evidence.checkpoint_digest == checkpoint_identity(record)
    except Exception:
        return False


def _classify_checkpoint_suffix(scope: Scope, record: CheckpointRecord,
                                result: Any, expected_head_seq: int
                                ) -> tuple[LifecycleReason | None, int, int | None]:
    """Validate a bounded ordered tail; only proven, terminal T13 events may remain unanchored."""
    expected_keys = {"tenant_id", "company_id", "checkpoint_seq", "checkpoint_hash",
                     "anchor_matches", "head_seq", "has_more", "events"}
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
    events = result["events"]
    if (type(head_seq) is not int or head_seq != expected_head_seq or head_seq < record.seq
            or type(result["has_more"]) is not bool or result["has_more"] is not False
            or type(events) is not list or len(events) > 128):
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, None
    seen_changes: set[UUID] = set()
    seen_events: set[UUID] = set()
    expected_seq = record.seq + 1
    for event in events:
        if type(event) is not dict or set(event) != {
                "seq", "event_id", "change_id", "event_type", "payload_found",
                "payload_nonempty", "record"}:
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
                or type(event["event_type"]) is not str
                or (event["payload_found"] is not None
                    and type(event["payload_found"]) is not bool)
                or type(event["payload_nonempty"]) is not bool):
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
        expected_seq += 1

        if event["event_type"] in _REQUIRED_CHECKPOINT_EVENTS:
            return LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT, len(events), head_seq
        if event["event_type"] == "RESOLVE_UNKNOWN":
            if type(event["payload_found"]) is not bool or event["payload_nonempty"] is not False:
                return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
            if event["payload_found"] is False:
                return LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT, len(events), head_seq
            return LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED, len(events), head_seq
        if event["event_type"] != "VERIFY_VERIFIED":
            if event["payload_found"] is not None or event["payload_nonempty"] is not False:
                return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
            return LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED, len(events), head_seq
        if event["payload_found"] is not None:
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq

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
                or event["payload_nonempty"] is not True):
            return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq

    if expected_seq - 1 != head_seq:
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, len(events), head_seq
    if not events and head_seq != record.seq:
        return LifecycleReason.CHECKPOINT_SUFFIX_INVALID, 0, head_seq
    return None, len(events), head_seq


class LifecycleCoordinator:
    """Check chain integrity and the authenticated provider latest record without mutation.

    Dependency timeouts request cancellation; they are cooperative and are not a hard wall-clock
    guarantee if an adapter suppresses cancellation. Production adapters must enforce their own
    transport deadlines if startup liveness depends on a strict bound.

        The class intentionally has no READY result. Once a reviewed shared fence, bounded recovery
        contract, authenticated anti-rollback provider, and durable READY transition exist, a separate
        implementation can extend this preflight without treating a checkpoint signature as proof of
        anti-rollback.
    """

    def __init__(self, ledger: LifecycleLedger, sink: CheckpointSink,
                 verifier: SignatureVerifier, *,
                 key_authority: CheckpointKeyAuthorizationAuthority | None = None,
                 latestness_authority: CheckpointLatestnessAuthority | None = None,
                 dependency_timeout_seconds: float = 5.0,
                 base_preflight_timeout_seconds: float = 30.0):
        if (isinstance(dependency_timeout_seconds, bool)
                or not isinstance(dependency_timeout_seconds, (int, float))
                or not math.isfinite(dependency_timeout_seconds)
                or dependency_timeout_seconds <= 0):
            raise ValueError("dependency_timeout_seconds must be a finite positive number")
        if (isinstance(base_preflight_timeout_seconds, bool)
                or not isinstance(base_preflight_timeout_seconds, (int, float))
                or not math.isfinite(base_preflight_timeout_seconds)
                or base_preflight_timeout_seconds <= 0):
            raise ValueError("base_preflight_timeout_seconds must be a finite positive number")
        self._ledger = ledger
        self._sink = sink
        self._verifier = verifier
        self._key_authority = key_authority
        self._latestness_authority = latestness_authority
        self._dependency_timeout_seconds = float(dependency_timeout_seconds)
        self._base_preflight_timeout_seconds = float(base_preflight_timeout_seconds)

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
            verified_public_key_digest = self._verifier.public_key_digest(record.key_id)
        except Exception:
            verified_public_key_digest = None
        if not _is_hash(verified_public_key_digest):
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_INVALID,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)

        if self._latestness_authority is None:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        try:
            challenge_nonce = secrets.token_hex(32)
            latestness = await asyncio.wait_for(
                self._latestness_authority.attest_latest(scope, record, challenge_nonce),
                timeout=self._dependency_timeout_seconds,
            )
        except Exception:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        if latestness is None:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        if not _valid_latestness_evidence(
                scope, record, latestness, challenge_nonce=challenge_nonce):
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_LATESTNESS_INVALID,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)

        if self._key_authority is None:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        try:
            key_authorization_nonce = secrets.token_hex(32)
            key_authorization = await asyncio.wait_for(
                self._key_authority.authorize_checkpoint(scope, record, key_authorization_nonce),
                timeout=self._dependency_timeout_seconds,
            )
        except Exception:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        if key_authorization is None:
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_DENIED,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)
        if not _valid_key_authorization(
                scope, record, key_authorization,
                verified_public_key_digest=verified_public_key_digest,
                challenge_nonce=key_authorization_nonce):
            return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                                   LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID,
                                   checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                                   chain_count=chain_count)

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

    async def preflight_base_recovery(
            self, base_fingerprint: str, begin_result: Any,
    ) -> BaseRecoveryPreflightResult:
        """Inspect every scope from one exact begin result without mutating recovery state.

        Results stay tied to the returned epoch and manifest digest, but are diagnostics only:
        any later completion must reload the base row and revalidate its epoch and digest. The
        aggregate deadline is cooperative; adapters must enforce transport deadlines and promptly
        propagate cancellation for cleanup to remain bounded.
        """
        snapshot = BaseRecoverySnapshot.from_begin_result(base_fingerprint, begin_result)
        semaphore = asyncio.Semaphore(_BASE_RECOVERY_PREFLIGHT_CONCURRENCY)

        async def inspect(scope: Scope) -> LifecycleResult:
            async with semaphore:
                result = await self.preflight(scope)
            if (type(result) is not LifecycleResult or result.scope != scope
                    or result.status is not LifecycleStatus.NOT_READY):
                raise ValueError("BASE_RECOVERY_PREFLIGHT_INVALID")
            return result

        tasks = [asyncio.create_task(inspect(scope)) for scope in snapshot.scopes]
        try:
            done, pending = await asyncio.wait(
                tasks, timeout=self._base_preflight_timeout_seconds,
            )
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        results: list[LifecycleResult] = []
        try:
            for scope, task in zip(snapshot.scopes, tasks, strict=True):
                if task in done:
                    results.append(task.result())
                else:
                    results.append(LifecycleResult(
                        scope, LifecycleStatus.NOT_READY,
                        LifecycleReason.BASE_PREFLIGHT_DEADLINE_EXCEEDED,
                    ))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        for task in pending:
            task.cancel()
        try:
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return BaseRecoveryPreflightResult(snapshot, tuple(results))

        # This remains diagnostic only: no complete cross-process mutation/dispatch fence,
        # recovery-to-READY contract, or operational provider is available in this slice.
        return LifecycleResult(scope, LifecycleStatus.NOT_READY,
                               LifecycleReason.SHARED_FENCE_UNAVAILABLE,
                               checkpoint_seq=record.seq, checkpoint_hash=record.head_hash,
                               chain_count=chain_count, suffix_event_count=suffix_count,
                               suffix_head_seq=suffix_head)
