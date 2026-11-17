"""Error mapping of the T16 recovery coordinator (no database, no COM)."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from business_ai_gateway.phase2.change_ledger.checkpoint import DatabaseTargetIdentity
from erp_mcp_private_writer.service import AdmissionState, CallSnapshot
from erp_mcp_private_writer.service import ServiceError, T16ResolutionPreparation
from erp_mcp_private_writer.t16_recovery import T16RecoveryCoordinator, T16RecoveryError


def _preparation(change_id: str) -> T16ResolutionPreparation:
    # __post_init__ is bypassed on purpose: the coordinator only reads these attributes.
    preparation = object.__new__(T16ResolutionPreparation)
    refs = SimpleNamespace(
        completion_proof_ref="a", outcome_evidence_ref="b",
        post_completion_challenge_ref="c", read_attestation_ref="d",
    )
    values = {
        "identity": SimpleNamespace(scope=object(), change_id=change_id),
        "dispatch_cas_id": uuid4(),
        "receipt_ref": "r",
        "evidence_refs": refs,
    }
    for name, value in values.items():
        object.__setattr__(preparation, name, value)
    return preparation


class _Writer:
    def __init__(self, preparation, *, database_identity=None, identity_error=None):
        self._preparation = preparation
        self._database_identity = database_identity or DatabaseTargetIdentity(123, 16384)
        self._identity_error = identity_error
        self.terminal_calls = []

    async def database_target_identity(self):
        if self._identity_error:
            raise self._identity_error
        return self._database_identity

    async def lookup(self, *_args):
        return None

    async def prepare_t16_resolution(self, *_args, **_kwargs):
        return self._preparation

    async def record_recovered_terminal(self, *_args):
        self.terminal_calls.append(_args)
        return None


class _Gate:
    def __init__(self, error: Exception | None = None, result=None, *,
                 database_identity=None, identity_error=None):
        self.calls = 0
        self._error = error
        self._result = result
        self._database_identity = database_identity or DatabaseTargetIdentity(123, 16384)
        self._identity_error = identity_error
        self.arguments = []

    async def database_target_identity(self):
        if self._identity_error:
            raise self._identity_error
        return self._database_identity

    async def resolve_t16_s13(self, *_args):
        self.calls += 1
        self.arguments.append(_args)
        if self._error is not None:
            raise self._error
        return deepcopy(self._result)


def _coordinator(preparation, gate, *, writer=None):
    coordinator = object.__new__(T16RecoveryCoordinator)
    coordinator._writer = _Writer(preparation) if writer is None else writer
    coordinator._resolution_gate = gate
    return coordinator


def _run(coordinator):
    return asyncio.run(coordinator.resolve_conditional_conflict(
        object(), object(), UUID("11111111-1111-4111-8111-111111111111"),
    ))


def test_a_malformed_change_id_is_a_local_rejection_and_never_reaches_the_gate():
    gate = _Gate()
    with pytest.raises(T16RecoveryError) as raised:
        _run(_coordinator(_preparation("not-a-uuid"), gate))

    assert raised.value.code == "T16_CHANGE_ID_INVALID"
    assert raised.value.outcome_unknown is False
    assert gate.calls == 0


def test_a_definitive_gate_refusal_keeps_its_code_and_flag():
    gate = _Gate(ServiceError("GATE_REFUSED", outcome_unknown=False))
    with pytest.raises(T16RecoveryError) as raised:
        _run(_coordinator(_preparation(str(uuid4())), gate))

    assert (raised.value.code, raised.value.outcome_unknown) == ("GATE_REFUSED", False)
    assert gate.calls == 1


def test_an_unexpected_gate_error_stays_outcome_unknown():
    gate = _Gate(RuntimeError("boom"))
    with pytest.raises(T16RecoveryError) as raised:
        _run(_coordinator(_preparation(str(uuid4())), gate))

    assert (raised.value.code, raised.value.outcome_unknown) == (
        "T16_RESOLUTION_OUTCOME_UNKNOWN", True)


def _valid_resolution_result():
    event_id = "22222222-2222-4222-8222-222222222222"
    anchor_hold_id = "33333333-3333-4333-8333-333333333333"
    hold_id = "44444444-4444-4444-8444-444444444444"
    return {
        "resolution": {
            "event_id": event_id,
            "event_seq": 7,
            "event_hash": "a" * 64,
            "hold_id": hold_id,
            "checkpoint_hold_ids": [anchor_hold_id],
            "execution_state": "FAILED_APPLY",
            "checkpoint_required": True,
        },
        "checkpoint": {
            "event_id": event_id,
            "event_seq": 7,
            "checkpoint_seq": 8,
            "released_hold_ids": [anchor_hold_id, hold_id],
        },
    }


def _invalidate_resolution_result(result, case):
    resolution = result["resolution"]
    checkpoint = result["checkpoint"]
    if case == "missing_resolution_event_seq":
        del resolution["event_seq"]
    elif case == "missing_checkpoint_seq":
        del checkpoint["checkpoint_seq"]
    elif case == "missing_checkpoint_required":
        del resolution["checkpoint_required"]
    elif case == "contradictory_execution_state":
        resolution["execution_state"] = "APPLIED"
    elif case == "checkpoint_event_mismatch":
        checkpoint["event_id"] = "55555555-5555-4555-8555-555555555555"
    elif case == "checkpoint_hold_mismatch":
        checkpoint["released_hold_ids"] = [resolution["hold_id"]]
    elif case == "missing_checkpoint_hold_ids":
        del resolution["checkpoint_hold_ids"]
    elif case == "empty_checkpoint_hold_ids":
        resolution["checkpoint_hold_ids"] = []
        checkpoint["released_hold_ids"] = [resolution["hold_id"]]
    elif case == "malformed_checkpoint_hold_ids":
        resolution["checkpoint_hold_ids"] = ["not-a-canonical-uuid"]
        checkpoint["released_hold_ids"] = ["not-a-canonical-uuid", resolution["hold_id"]]
    elif case == "duplicate_checkpoint_hold_ids":
        anchor_hold_id = resolution["checkpoint_hold_ids"][0]
        resolution["checkpoint_hold_ids"] = [anchor_hold_id, anchor_hold_id]
        checkpoint["released_hold_ids"] = [anchor_hold_id, anchor_hold_id, resolution["hold_id"]]
    else:
        raise AssertionError(f"unknown malformed-result case: {case}")
    return result


@pytest.mark.parametrize(
    "case",
    [
        "missing_resolution_event_seq",
        "missing_checkpoint_seq",
        "missing_checkpoint_required",
        "contradictory_execution_state",
        "checkpoint_event_mismatch",
        "checkpoint_hold_mismatch",
        "missing_checkpoint_hold_ids",
        "empty_checkpoint_hold_ids",
        "malformed_checkpoint_hold_ids",
        "duplicate_checkpoint_hold_ids",
    ],
)
def test_malformed_checkpoint_response_keeps_private_call_unresolved(case):
    preparation = _preparation(str(uuid4()))
    result = _invalidate_resolution_result(_valid_resolution_result(), case)
    gate = _Gate(result=result)
    writer = _Writer(preparation)

    with pytest.raises(T16RecoveryError) as raised:
        _run(_coordinator(preparation, gate, writer=writer))

    assert (raised.value.code, raised.value.outcome_unknown) == (
        "T16_CHECKPOINT_RESULT_INVALID", True,
    )
    assert gate.calls == 1
    assert writer.terminal_calls == []


def test_mismatched_database_binding_stops_before_gate():
    preparation = _preparation(str(uuid4()))
    gate = _Gate(database_identity=DatabaseTargetIdentity(124, 16384))

    with pytest.raises(T16RecoveryError) as raised:
        _run(_coordinator(preparation, gate))

    assert (raised.value.code, raised.value.outcome_unknown) == (
        "T16_DATABASE_BINDING_MISMATCH", False,
    )
    assert gate.calls == 0


def test_database_binding_unavailable_fails_before_gate():
    preparation = _preparation(str(uuid4()))
    gate = _Gate()
    writer = _Writer(preparation, identity_error=RuntimeError("private db detail"))

    with pytest.raises(T16RecoveryError) as raised:
        _run(_coordinator(preparation, gate, writer=writer))

    assert (raised.value.code, raised.value.outcome_unknown) == (
        "T16_DATABASE_BINDING_UNAVAILABLE", False,
    )
    assert gate.calls == 0
