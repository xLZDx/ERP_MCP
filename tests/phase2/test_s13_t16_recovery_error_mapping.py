"""Error mapping of the T16 recovery coordinator (no database, no COM)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

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
    def __init__(self, preparation):
        self._preparation = preparation

    async def lookup(self, *_args):
        return None

    async def prepare_t16_resolution(self, *_args, **_kwargs):
        return self._preparation


class _Gate:
    def __init__(self, error: Exception | None = None):
        self.calls = 0
        self._error = error

    async def resolve_t16_s13(self, *_args):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return {}


def _coordinator(preparation, gate):
    coordinator = object.__new__(T16RecoveryCoordinator)
    coordinator._writer = _Writer(preparation)
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
