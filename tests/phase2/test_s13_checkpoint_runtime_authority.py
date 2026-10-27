"""Unit-only orchestration tests for the S13 checkpoint runtime-authority boundary.

All collaborators below are test doubles. The authority harness deliberately reports the
production-facing sentinel required to enter enabled gate branches, but it has no provider
credentials, network access, authenticated policy source, or runtime qualification evidence.
These tests establish call ordering and fail-closed behavior only; they do not qualify a provider
or assert operational readiness.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    CheckpointUnavailable,
    DispatchGate,
    GateDisabled,
)
import business_ai_gateway.phase2.change_ledger.checkpoint as checkpoint_module


SCOPE = Scope("unit-tenant", "unit-company")
CHANGE_ID = uuid4()
CALL_ID = uuid4()
DISPATCH_INTENT_ID = uuid4()
EVENT_HASH = "a" * 64


class _UnitOnlyAuthorityHarness:
    """Unit-only policy decision double; never represents provider trust evidence."""

    # DispatchGate requires a non-test authority marker to exercise the enabled branch. This
    # harness is not operational authority: it only records and simulates allow/refuse decisions.
    is_test_double = False

    def __init__(self, events: list[str], *, provider_refuse_on_call: int | None = None,
                 provider_error: Exception | None = None,
                 readiness_error: Exception | None = None,
                 provider_result: object = None,
                 readiness_result: object = None,
                 hang_on: str | None = None) -> None:
        self.events = events
        self.provider_refuse_on_call = provider_refuse_on_call
        self.provider_error = provider_error
        self.readiness_error = readiness_error
        self.provider_result = provider_result
        self.readiness_result = readiness_result
        self.hang_on = hang_on
        self.provider_calls = 0

    async def require_provider_qualified(
            self, scope: Scope, *, sink_id: str, sink_kind: str,
            signer_key_id: str, signer_key_version: str | None) -> object:
        self.events.append("authority.provider")
        self.provider_calls += 1
        if self.hang_on == "provider":
            await asyncio.Event().wait()
        if (self.provider_refuse_on_call == self.provider_calls) and self.provider_error is not None:
            raise self.provider_error
        return self.provider_result

    async def require_admission_ready(self, scope: Scope) -> object:
        self.events.append("authority.readiness")
        if self.hang_on == "readiness":
            await asyncio.Event().wait()
        if self.readiness_error is not None:
            raise self.readiness_error
        return self.readiness_result


class _MarkedTestAuthority(_UnitOnlyAuthorityHarness):
    """An explicitly rejected authority double used to prove test doubles keep the gate off."""

    is_test_double = True


class _UnitOnlySigner:
    """Signature-output double; the returned hex is not a real signature."""

    is_test_double = False
    key_id = "unit-checkpoint-key"
    key_version = "unit-checkpoint-version"

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def sign(self, payload: bytes) -> str:
        self.events.append("signer.sign")
        return "b" * 128


class _UnitOnlyVerifier:
    """Signature-verification double; accepts only to exercise post-check ordering."""

    is_test_double = False

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool:
        self.events.append("verifier.verify")
        return True


class _UnitOnlySink:
    """In-memory sink double; not an append-only or authenticated provider."""

    is_test_double = True
    kind = "REAL"
    sink_id = "unit-only-sink"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.rows: dict[tuple[int, str, str], CheckpointRecord] = {}

    async def write(self, record: CheckpointRecord) -> None:
        self.events.append("sink.write")
        self.rows[(record.seq, record.tenant_id, record.company_id)] = record

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None:
        self.events.append("sink.read_back")
        return self.rows.get((seq, scope.tenant_id, scope.company_id))

    async def latest(self, scope: Scope) -> CheckpointRecord | None:
        self.events.append("sink.latest")
        matching = [record for record in self.rows.values()
                    if record.tenant_id == scope.tenant_id and record.company_id == scope.company_id]
        return max(matching, key=lambda record: record.seq) if matching else None


class _UnitOnlyLedger:
    """SQL boundary double: records calls but never opens a connection or mutates a database."""

    private_writer_schema_enabled = True

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.resolution = _resolution()

    async def dispatch_intent_for_call(self, scope: Scope, call_id: UUID,
                                       as_class: str = "worker") -> dict[str, object]:
        self.events.append("sql.dispatch_intent_for_call")
        return {
            "dispatch_intent_id": str(DISPATCH_INTENT_ID),
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "change_id": str(CHANGE_ID),
            "claim_generation": 3,
            "call_id": str(call_id),
            "auth_epoch": 7,
        }

    async def permit_binding_for_intent(self, scope: Scope, dispatch_intent_id: UUID,
                                        as_class: str = "worker") -> None:
        self.events.append("sql.permit_binding_for_intent")
        return None

    async def ledger_head(self, scope: Scope) -> dict[str, object]:
        self.events.append("sql.ledger_head")
        return {"seq": 41, "head_hash": EVENT_HASH}

    async def record_checkpoint_s13(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                    sink_id: str, key_id: str, signature: str,
                                    signed_at: datetime, read_back: bool) -> int:
        self.events.append("sql.record_checkpoint_s13")
        return seq

    async def issue_permit_s13(self, scope: Scope, change_id: UUID, generation: int,
                               dispatch_intent_id: UUID, permit_id: UUID,
                               signer_key_id: str, signer_key_version: str,
                               signature: str) -> dict[str, object]:
        self.events.append("sql.issue_permit_s13")
        return {
            "dispatch_intent_id": str(dispatch_intent_id),
            "permit_id": str(permit_id),
            "permit_digest": hashlib.sha256(
                f"{change_id}:{generation}:41".encode("utf-8")
            ).hexdigest(),
            "checkpoint_seq": 41,
            "signer_key_id": signer_key_id,
            "signer_key_version": signer_key_version,
        }

    async def operator_resolve_s13(
            self, scope: Scope, change_id: UUID, dispatch_cas_id: UUID, cosign_id: UUID,
            receipt_ref: str, completion_ref: str, outcome_ref: str,
            challenge_ref: str | None = None,
            read_attestation_ref: str | None = None) -> dict[str, object]:
        self.events.append("sql.operator_resolve_s13")
        return dict(self.resolution)

    async def release_hold(self, scope: Scope, hold_id: UUID,
                           release_evidence: dict[str, object]) -> datetime:
        self.events.append("sql.release_hold")
        return datetime.now(UTC)


def _resolution() -> dict[str, object]:
    return {
        "checkpoint_required": True,
        "execution_state": "APPLIED",
        "event_id": str(uuid4()),
        "hold_id": str(uuid4()),
        "event_seq": 17,
        "event_hash": EVENT_HASH,
        "checkpoint_signed_at": datetime.now(UTC),
        "checkpoint_hold_ids": [str(uuid4()), str(uuid4())],
    }


def _gate(*, authority: object | None, events: list[str] | None = None) -> tuple[DispatchGate, list[str]]:
    events = [] if events is None else events
    return DispatchGate(
        _UnitOnlyLedger(events), _UnitOnlySink(events), _UnitOnlySigner(events),
        _UnitOnlyVerifier(events), real_checkpoint_sink=True,
        private_writer_schema_enabled=True, runtime_authority=authority,
    ), events


@pytest.mark.parametrize("authority", [None, "unit-test-double"])
@pytest.mark.asyncio
async def test_gate_is_disabled_without_non_test_runtime_authority(authority: object | None) -> None:
    events: list[str] = []
    runtime_authority = None if authority is None else _MarkedTestAuthority(events)
    gate, _ = _gate(authority=runtime_authority, events=events)

    assert gate.enabled is False
    with pytest.raises(GateDisabled) as error:
        await gate.issue_permit(SCOPE, CHANGE_ID, 3, 10, CALL_ID)
    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert events == []


def test_constructor_rejects_incomplete_runtime_authority_contract() -> None:
    class IncompleteAuthority:
        is_test_double = False

        async def require_provider_qualified(self, *args: object, **kwargs: object) -> None:
            return None

    events: list[str] = []
    with pytest.raises(ValueError, match="S13_CHECKPOINT_RUNTIME_AUTHORITY_INCOMPLETE"):
        _gate(authority=IncompleteAuthority(), events=events)
    assert events == []


@pytest.mark.asyncio
async def test_provider_policy_refusal_blocks_issue_permit_before_sql_or_sink_side_effects() -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(
        events, provider_refuse_on_call=1,
        provider_error=CheckpointUnavailable("PRIVATE_PROVIDER_POLICY_DETAIL"),
    )
    gate, _ = _gate(authority=authority, events=events)

    with pytest.raises(GateDisabled) as error:
        await gate.issue_permit(SCOPE, CHANGE_ID, 3, 10, CALL_ID)

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert "PRIVATE_PROVIDER_POLICY_DETAIL" not in str(error.value)
    assert events == ["authority.provider"]


@pytest.mark.parametrize("method", ["provider", "readiness"])
@pytest.mark.parametrize("result", [False, "unexpected-policy-result"])
@pytest.mark.asyncio
async def test_non_none_authority_result_refuses_before_sql_or_sink_side_effects(
        method: str, result: object) -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(
        events,
        provider_result=result if method == "provider" else None,
        readiness_result=result if method == "readiness" else None,
    )
    gate, _ = _gate(authority=authority, events=events)

    with pytest.raises(GateDisabled) as error:
        await gate.issue_permit(SCOPE, CHANGE_ID, 3, 10, CALL_ID)

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    expected = ["authority.provider"]
    if method == "readiness":
        expected.append("authority.readiness")
    assert events == expected


@pytest.mark.parametrize("path,hang_on", [
    ("issue_permit", "provider"),
    ("issue_permit", "readiness"),
    ("resolve_t16", "provider"),
    ("resolve_t16", "readiness"),
])
@pytest.mark.asyncio
async def test_hanging_admission_authority_times_out_before_sql_or_checkpoint_side_effects(
        monkeypatch: pytest.MonkeyPatch, path: str, hang_on: str) -> None:
    # Preserve the production timeout behavior while keeping this deterministic unit case fast.
    monkeypatch.setattr(checkpoint_module, "_CHECKPOINT_RUNTIME_AUTHORITY_TIMEOUT_SECONDS", 0.01)
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(events, hang_on=hang_on)
    gate, _ = _gate(authority=authority, events=events)

    expected_error = GateDisabled if path == "issue_permit" else CheckpointUnavailable
    with pytest.raises(expected_error) as error:
        if path == "issue_permit":
            await gate.issue_permit(SCOPE, CHANGE_ID, 3, 10, CALL_ID)
        else:
            await gate.resolve_t16_s13(SCOPE, CHANGE_ID, uuid4(), uuid4(), "r", "c", "o")

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert not any(event.startswith("sql.") for event in events)
    assert not any(event.startswith("sink.") for event in events)
    assert "signer.sign" not in events


@pytest.mark.parametrize("reason", ["NOT_READY", "EXPIRED"])
@pytest.mark.asyncio
async def test_readiness_refusal_or_expiry_blocks_issue_permit_before_side_effects(reason: str) -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(
        events, readiness_error=CheckpointUnavailable(f"UNIT_ADMISSION_{reason}"),
    )
    gate, _ = _gate(authority=authority, events=events)

    with pytest.raises(GateDisabled) as error:
        await gate.issue_permit(SCOPE, CHANGE_ID, 3, 10, CALL_ID)

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert events == ["authority.provider", "authority.readiness"]


@pytest.mark.asyncio
async def test_successful_admission_readiness_precedes_issue_permit_sql_and_sink_calls() -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(events)
    gate, _ = _gate(authority=authority, events=events)

    result = await gate.issue_permit(SCOPE, CHANGE_ID, 3, 10, CALL_ID)

    assert result["dispatch_intent_id"] == str(DISPATCH_INTENT_ID)
    assert result["permit_id"]
    assert events[:2] == ["authority.provider", "authority.readiness"]
    assert events.index("authority.readiness") < events.index("sql.issue_permit_s13")
    assert events.index("authority.readiness") < events.index("sink.write")
    assert events.index("sink.read_back") < events.index("sql.record_checkpoint_s13")
    assert events.index("sql.record_checkpoint_s13") < events.index("sql.issue_permit_s13")


@pytest.mark.asyncio
async def test_t16_admission_precedes_operator_resolve_and_checkpoint_rechecks_provider() -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(events)
    gate, _ = _gate(authority=authority, events=events)

    result = await gate.resolve_t16_s13(
        SCOPE, CHANGE_ID, uuid4(), uuid4(), "receipt", "completion", "outcome",
    )

    resolve_index = events.index("sql.operator_resolve_s13")
    qualification_indexes = [i for i, event in enumerate(events) if event == "authority.provider"]
    checkpoint_recheck_index = qualification_indexes[1]
    assert events.index("authority.readiness") < resolve_index
    assert qualification_indexes[0] < resolve_index < checkpoint_recheck_index
    assert checkpoint_recheck_index < events.index("sink.read_back")
    assert events.index("sink.write") < events.index("sql.record_checkpoint_s13")
    assert events.index("sql.record_checkpoint_s13") < events.index("sql.release_hold")
    assert len(result["checkpoint"]["released_hold_ids"]) == 3


@pytest.mark.asyncio
async def test_t16_refuses_before_operator_resolve_when_admission_is_not_ready() -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(
        events, readiness_error=CheckpointUnavailable("UNIT_ADMISSION_EXPIRED"),
    )
    gate, _ = _gate(authority=authority, events=events)

    with pytest.raises(CheckpointUnavailable) as error:
        await gate.resolve_t16_s13(SCOPE, CHANGE_ID, uuid4(), uuid4(), "r", "c", "o")

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert str(error.value) == "UNIT_ADMISSION_EXPIRED"
    assert "sql.operator_resolve_s13" not in events
    assert not any(event.startswith("sink.") for event in events)


@pytest.mark.asyncio
async def test_t16_provider_policy_refusal_blocks_operator_resolve_and_sink_calls() -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(
        events, provider_refuse_on_call=1,
        provider_error=CheckpointUnavailable("UNIT_PROVIDER_NOT_QUALIFIED"),
    )
    gate, _ = _gate(authority=authority, events=events)

    with pytest.raises(CheckpointUnavailable) as error:
        await gate.resolve_t16_s13(SCOPE, CHANGE_ID, uuid4(), uuid4(), "r", "c", "o")

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert str(error.value) == "UNIT_PROVIDER_NOT_QUALIFIED"
    assert events == ["authority.provider"]


@pytest.mark.asyncio
async def test_t16_checkpoint_rechecks_policy_after_sql_before_provider_or_hold_release() -> None:
    events: list[str] = []
    authority = _UnitOnlyAuthorityHarness(
        events, provider_refuse_on_call=2,
        provider_error=CheckpointUnavailable("UNIT_PROVIDER_POLICY_EXPIRED"),
    )
    gate, _ = _gate(authority=authority, events=events)

    with pytest.raises(CheckpointUnavailable) as error:
        await gate.resolve_t16_s13(SCOPE, CHANGE_ID, uuid4(), uuid4(), "r", "c", "o")

    assert error.value.code == "CHECKPOINT_UNAVAILABLE"
    assert str(error.value) == "UNIT_PROVIDER_POLICY_EXPIRED"
    assert events.count("authority.provider") == 2
    assert "authority.readiness" in events
    assert "sql.operator_resolve_s13" in events
    assert not any(event.startswith("sink.") for event in events)
    assert "sql.record_checkpoint_s13" not in events
    assert "sql.release_hold" not in events
