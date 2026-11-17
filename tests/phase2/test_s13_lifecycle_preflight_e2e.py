"""Local orchestration-boundary E2E for the fail-closed S13 startup preflight.

This exercises the lifecycle coordinator with its real in-memory checkpoint implementation and
small port doubles. It is not evidence for PostgreSQL, an external anti-rollback provider, or 1C.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect
from uuid import uuid4

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointKeyAuthorization,
    CheckpointKeyAuthorizationBasis,
    CheckpointLatestnessEvidence,
    CheckpointRecord,
    FakeSigner,
    FakeVerifier,
    InMemoryCheckpointSink,
    checkpoint_identity,
)
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator,
    LifecycleReason,
    LifecycleStatus,
)


SCOPE = Scope("T-S13", "C-S13")
OTHER_SCOPE = Scope("T-OTHER", "C-OTHER")
HEAD_HASH = "a" * 64


class LedgerPortDouble:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result if result is not None else {"ok": True, "count": 7}
        self.error = error
        self.calls: list[Scope] = []

    async def verify_chain(self, scope: Scope):
        self.calls.append(scope)
        if self.error:
            raise self.error
        return self.result


class ValidSuffixLedgerPortDouble(LedgerPortDouble):
    def __init__(self, result=None, error: Exception | None = None):
        super().__init__(result=result, error=error)
        self.suffix_calls = 0

    async def lifecycle_checkpoint_suffix(self, scope: Scope, checkpoint_seq: int, checkpoint_hash: str):
        self.suffix_calls += 1
        return {
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "checkpoint_seq": checkpoint_seq,
            "checkpoint_hash": checkpoint_hash,
            "anchor_matches": True,
            "head_seq": checkpoint_seq,
            "has_more": False,
            "events": [],
        }


class HangingLedgerPortDouble(LedgerPortDouble):
    def __init__(self):
        super().__init__()
        self.cancelled = False

    async def verify_chain(self, scope: Scope):
        self.calls.append(scope)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class HostileChainResult(dict):
    def get(self, key, default=None):
        raise RuntimeError("untrusted mapping access")


class RecordingCheckpointSink(InMemoryCheckpointSink):
    def __init__(self):
        super().__init__("s13-local-orchestration-e2e")
        self.write_calls = 0
        self.read_back_calls = 0
        self.latest_calls: list[Scope] = []

    async def write(self, record: CheckpointRecord) -> None:
        self.write_calls += 1
        await super().write(record)

    async def read_back(self, scope: Scope, seq: int):
        self.read_back_calls += 1
        return await super().read_back(scope, seq)

    async def latest(self, scope: Scope):
        self.latest_calls.append(scope)
        return await super().latest(scope)


class HangingCheckpointSink(RecordingCheckpointSink):
    def __init__(self):
        super().__init__()
        self.cancelled = False

    async def latest(self, scope: Scope):
        self.latest_calls.append(scope)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class HostileCheckpointRecord(CheckpointRecord):
    def __getattribute__(self, name):
        if name == "tenant_id":
            raise RuntimeError("untrusted record field access")
        return super().__getattribute__(name)


class HostileRecordCheckpointSink(RecordingCheckpointSink):
    def __init__(self, record):
        super().__init__()
        self.record = record

    async def latest(self, scope: Scope):
        self.latest_calls.append(scope)
        return self.record


class HostileScopeValue:
    def __eq__(self, other):
        raise RuntimeError("untrusted scope comparison")


class SyntheticLatestnessAuthority:
    """Explicit E2E test double; the in-memory sink cannot prove external freshness."""

    is_test_double = True

    def __init__(self, sink):
        self.sink = sink

    async def attest_latest(self, scope: Scope, record: CheckpointRecord, challenge_nonce: str):
        digest = None
        revision = 0
        event_id = None
        if record is not None:
            try:
                digest = checkpoint_identity(record)
            except Exception:
                digest = "e" * 64
            revision = max(1, getattr(record, "seq", 1))
            event_id = str(uuid4())
        return CheckpointLatestnessEvidence(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            checkpoint_digest=digest,
            challenge_nonce=challenge_nonce,
            provider_id="s13-local-orchestration-e2e",
            provider_revision=max(1, revision),
            authority_id="synthetic-test-authority",
            authority_revision=revision,
            authority_event_id=event_id,
            policy_version="synthetic-test-only-v1",
            proof_digest="f" * 64,
        )


class SyntheticKeyAuthority:
    """Explicit test double only; it is not a retained key-history authority."""

    is_test_double = True

    def __init__(self, verifier, *, public_key_digest: str | None = None):
        self.verifier = verifier
        self.public_key_digest_override = public_key_digest

    async def authorize_checkpoint(self, scope: Scope, record: CheckpointRecord,
                                   challenge_nonce: str):
        return CheckpointKeyAuthorization(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            key_id=record.key_id,
            public_key_digest=(self.public_key_digest_override
                               if self.public_key_digest_override is not None
                               else self.verifier.public_key_digest(record.key_id)),
            checkpoint_digest=checkpoint_identity(record),
            challenge_nonce=challenge_nonce,
            authority_id="synthetic-test-key-authority",
            authority_revision=1,
            authority_event_id="synthetic-test-key-event",
            policy_version="test-only-v1",
            basis=CheckpointKeyAuthorizationBasis.ACTIVE,
        )


def coordinator(ledger, sink, verifier, *, timeout=5.0, key_authority=None):
    return LifecycleCoordinator(
        ledger, sink, verifier,
        latestness_authority=SyntheticLatestnessAuthority(sink),
        key_authority=(key_authority if key_authority is not None
                       else SyntheticKeyAuthority(verifier)),
        dependency_timeout_seconds=timeout,
    )


def _record(scope: Scope, seq: int, signer: FakeSigner) -> CheckpointRecord:
    unsigned = CheckpointRecord(scope.tenant_id, scope.company_id, seq, HEAD_HASH,
                                datetime(2026, 10, 17, tzinfo=UTC), signer.key_id, "",
                                "s13-local-orchestration-e2e", "TEST")
    return CheckpointRecord(**{**unsigned.__dict__,
                               "signature": signer.sign(unsigned.signing_payload())})


def _run(coro):
    return asyncio.run(coro)


def test_s13_preflight_successful_chain_and_exact_scope_latest_stays_not_ready():
    async def scenario():
        signer = FakeSigner("s13-test-key")
        sink = RecordingCheckpointSink()
        # Fixture setup: a newer other-scope row must not shadow this scope's latest record.
        await sink.write(_record(SCOPE, 12, signer))
        await sink.write(_record(OTHER_SCOPE, 99, signer))
        sink.write_calls = 0
        ledger = ValidSuffixLedgerPortDouble(result={"ok": True, "count": 12})
        lifecycle = coordinator(ledger, sink, FakeVerifier())

        result = await lifecycle.preflight(SCOPE)

        assert result.scope == SCOPE
        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.SHARED_FENCE_UNAVAILABLE
        assert (result.checkpoint_seq, result.checkpoint_hash, result.chain_count) == (12, HEAD_HASH, 12)
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == [SCOPE]
        assert sink.write_calls == 0
        assert sink.read_back_calls == 0
        # The current module boundary has no recovery or writer port to invoke.
        assert list(inspect.signature(LifecycleCoordinator).parameters) == [
            "ledger", "sink", "verifier", "key_authority", "latestness_authority",
            "dependency_timeout_seconds", "base_preflight_timeout_seconds"]
        assert not hasattr(lifecycle, "recover")
        assert not hasattr(lifecycle, "write")

    _run(scenario())


def test_s13_preflight_mismatched_but_well_formed_key_digest_stops_before_suffix():
    async def scenario():
        verifier = FakeVerifier()
        signer = FakeSigner("s13-test-key")
        record = _record(SCOPE, 12, signer)
        sink = RecordingCheckpointSink()
        await sink.write(record)
        sink.write_calls = 0
        ledger = ValidSuffixLedgerPortDouble(result={"ok": True, "count": 12})
        mismatched_digest = "0" * 64
        assert mismatched_digest != verifier.public_key_digest(record.key_id)
        key_authority = SyntheticKeyAuthority(
            verifier, public_key_digest=mismatched_digest,
        )

        result = await coordinator(
            ledger, sink, verifier, key_authority=key_authority,
        ).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID
        assert ledger.suffix_calls == 0
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_chain_failure_stops_before_checkpoint_provider():
    async def scenario():
        sink = RecordingCheckpointSink()
        ledger = LedgerPortDouble(error=RuntimeError("private connection detail"))
        result = await coordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_UNAVAILABLE
        assert result.checkpoint_seq is None
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_chain_timeout_is_bounded_and_stops_before_checkpoint_provider():
    async def scenario():
        sink = RecordingCheckpointSink()
        ledger = HangingLedgerPortDouble()
        result = await coordinator(ledger, sink, FakeVerifier(), timeout=0.01).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_UNAVAILABLE
        assert result.chain_count is None
        assert ledger.calls == [SCOPE]
        assert ledger.cancelled is True
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_checkpoint_timeout_is_bounded_and_fail_closed():
    async def scenario():
        ledger = LedgerPortDouble()
        sink = HangingCheckpointSink()
        result = await coordinator(ledger, sink, FakeVerifier(), timeout=0.01).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHECKPOINT_UNAVAILABLE
        assert result.chain_count == 7
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == [SCOPE]
        assert sink.cancelled is True
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_invalid_chain_stops_before_checkpoint_provider():
    async def scenario():
        sink = RecordingCheckpointSink()
        ledger = LedgerPortDouble(result={"ok": False, "count": 3})
        result = await coordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_INVALID
        assert result.chain_count == 3
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_malformed_success_chain_count_stops_before_checkpoint_provider():
    async def scenario():
        sink = RecordingCheckpointSink()
        # bool is an int subclass in Python, but is not a valid event count.
        ledger = LedgerPortDouble(result={"ok": True, "count": True})
        result = await coordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_INVALID
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_chain_mapping_subclass_is_rejected_without_get_call():
    async def scenario():
        sink = RecordingCheckpointSink()
        ledger = LedgerPortDouble(result=HostileChainResult(ok=True, count=7))
        result = await coordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_INVALID
        assert result.chain_count is None
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_checkpoint_record_subclass_is_rejected_before_field_access():
    async def scenario():
        signer = FakeSigner("s13-test-key")
        hostile_record = HostileCheckpointRecord(**_record(SCOPE, 12, signer).__dict__)
        sink = HostileRecordCheckpointSink(hostile_record)
        result = await coordinator(LedgerPortDouble(), sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHECKPOINT_INVALID
        assert result.chain_count == 7
        assert sink.latest_calls == [SCOPE]
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_malformed_exact_record_scope_is_invalid_without_exception_escape():
    async def scenario():
        signer = FakeSigner("s13-test-key")
        valid = _record(SCOPE, 12, signer)
        malformed = CheckpointRecord(
            HostileScopeValue(), valid.company_id, valid.seq, valid.head_hash,
            valid.signed_at, valid.key_id, valid.signature, valid.sink_id, valid.sink_kind,
        )
        sink = HostileRecordCheckpointSink(malformed)
        result = await coordinator(LedgerPortDouble(), sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHECKPOINT_INVALID
        assert result.chain_count == 7
        assert sink.latest_calls == [SCOPE]
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_missing_latest_checkpoint_stops_without_writer_effects():
    async def scenario():
        sink = RecordingCheckpointSink()
        result = await coordinator(LedgerPortDouble(), sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHECKPOINT_MISSING
        assert result.chain_count == 7
        assert sink.latest_calls == [SCOPE]
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())
