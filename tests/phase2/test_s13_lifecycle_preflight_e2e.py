"""Local orchestration-boundary E2E for the fail-closed S13 startup preflight.

This exercises the lifecycle coordinator with its real in-memory checkpoint implementation and
small port doubles. It is not evidence for PostgreSQL, an external anti-rollback provider, or 1C.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    FakeSigner,
    FakeVerifier,
    InMemoryCheckpointSink,
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
        ledger = LedgerPortDouble()
        coordinator = LifecycleCoordinator(ledger, sink, FakeVerifier())

        result = await coordinator.preflight(SCOPE)

        assert result.scope == SCOPE
        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.SHARED_FENCE_UNAVAILABLE
        assert (result.checkpoint_seq, result.checkpoint_hash, result.chain_count) == (12, HEAD_HASH, 7)
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == [SCOPE]
        assert sink.write_calls == 0
        assert sink.read_back_calls == 0
        # The current module boundary has no recovery or writer port to invoke.
        assert list(inspect.signature(LifecycleCoordinator).parameters) == [
            "ledger", "sink", "verifier"]
        assert not hasattr(coordinator, "recover")
        assert not hasattr(coordinator, "write")

    _run(scenario())


def test_s13_preflight_chain_failure_stops_before_checkpoint_provider():
    async def scenario():
        sink = RecordingCheckpointSink()
        ledger = LedgerPortDouble(error=RuntimeError("private connection detail"))
        result = await LifecycleCoordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_UNAVAILABLE
        assert result.checkpoint_seq is None
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_invalid_chain_stops_before_checkpoint_provider():
    async def scenario():
        sink = RecordingCheckpointSink()
        ledger = LedgerPortDouble(result={"ok": False, "count": 3})
        result = await LifecycleCoordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

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
        result = await LifecycleCoordinator(ledger, sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHAIN_INVALID
        assert ledger.calls == [SCOPE]
        assert sink.latest_calls == []
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())


def test_s13_preflight_missing_latest_checkpoint_stops_without_writer_effects():
    async def scenario():
        sink = RecordingCheckpointSink()
        result = await LifecycleCoordinator(
            LedgerPortDouble(), sink, FakeVerifier()).preflight(SCOPE)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.CHECKPOINT_MISSING
        assert result.chain_count == 7
        assert sink.latest_calls == [SCOPE]
        assert sink.write_calls == sink.read_back_calls == 0

    _run(scenario())
