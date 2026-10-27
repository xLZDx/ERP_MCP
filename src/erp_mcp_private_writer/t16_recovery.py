"""Continue verified S12 conditional-conflict recovery through T16 and S13 terminalization."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.uuid_contract import is_canonical_nonzero_uuid
from business_ai_gateway.phase2.change_ledger.write_port import ApplyTicket, DispatchPermit

from .dependency_shape import has_static_callable_method
from .service import (
    AdmissionState,
    CallSnapshot,
    PrivateWriterService,
    ServiceError,
    T16ResolutionPreparation,
)

_LOG = logging.getLogger(__name__)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


class T16ResolutionGate(Protocol):
    """S12 ledger/checkpoint gate; the implementation owns cosign validation and read-back."""

    async def resolve_t16_s13(
            self, scope: Scope, change_id: UUID, dispatch_cas_id: UUID, cosign_id: UUID,
            receipt_ref: str, completion_ref: str, outcome_ref: str,
            challenge_ref: str, read_attestation_ref: str) -> dict[str, Any]:
        ...


class T16RecoveryError(RuntimeError):
    """Sanitized continuation failure; the durable T16 request may be replayed by cosign ID."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        self.code = code
        self.outcome_unknown = outcome_unknown
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class T16RecoveryResult:
    """Terminal S13 snapshot; event fields are absent only when lookup proves prior completion."""

    resolution_event_id: UUID | None
    resolution_event_seq: int | None
    checkpoint_seq: int | None
    call: CallSnapshot

    def __post_init__(self) -> None:
        fields = (self.resolution_event_id, self.resolution_event_seq, self.checkpoint_seq)
        if all(value is None for value in fields):
            if (type(self.call) is not CallSnapshot
                    or self.call.state is not AdmissionState.TERMINAL_WITH_EVIDENCE):
                raise ValueError("T16_RECOVERY_RESULT_INVALID")
            return
        if (type(self.resolution_event_id) is not UUID or self.resolution_event_id.int == 0
                or type(self.resolution_event_seq) is not int or self.resolution_event_seq < 1
                or type(self.checkpoint_seq) is not int or self.checkpoint_seq < 1
                or type(self.call) is not CallSnapshot
                or self.call.state is not AdmissionState.TERMINAL_WITH_EVIDENCE):
            raise ValueError("T16_RECOVERY_RESULT_INVALID")


class T16RecoveryCoordinator:
    """Orchestrate prepare → operator/witness T16 → checkpoint → S13 physical-slot terminality."""

    def __init__(self, writer_service: PrivateWriterService,
                 resolution_gate: T16ResolutionGate) -> None:
        if not isinstance(writer_service, PrivateWriterService):
            raise ValueError("T16_WRITER_SERVICE_INVALID")
        if not has_static_callable_method(resolution_gate, "resolve_t16_s13"):
            raise ValueError("T16_RESOLUTION_GATE_INVALID")
        self._writer = writer_service
        self._resolution_gate = resolution_gate

    async def resolve_conditional_conflict(
            self, ticket: ApplyTicket, permit: DispatchPermit, cosign_id: UUID,
            *, require_startup_inventory: bool = True) -> T16RecoveryResult:
        """Commit/replay the exact T16 event, then release the private physical-base hold.

        T16 evidence is prepared and cross-validated before the signed operator/witness decision.
        The checkpoint gate must return only after exact external read-back, database registration,
        and linked stop-effects hold release. The final private-writer transition then binds the
        same T16 event to the immutable call and releases the physical-base slot. Every step is
        replayable; this coordinator never invokes COM.
        """
        if (type(cosign_id) is not UUID
                or not is_canonical_nonzero_uuid(str(cosign_id))):
            raise T16RecoveryError("T16_COSIGN_ID_INVALID")
        try:
            existing = await self._writer.lookup(ticket, permit)
        except ServiceError as exc:
            raise T16RecoveryError(exc.code, outcome_unknown=exc.outcome_unknown) from None
        except Exception as exc:
            _LOG.error("T16 lookup raised unexpected %s", type(exc).__name__)
            raise T16RecoveryError("T16_RECOVERY_LOOKUP_UNAVAILABLE",
                                   outcome_unknown=True) from None
        if (type(existing) is CallSnapshot
                and existing.state is AdmissionState.TERMINAL_WITH_EVIDENCE):
            return T16RecoveryResult(None, None, None, existing)
        try:
            preparation = await self._writer.prepare_t16_resolution(
                ticket, permit, require_startup_inventory=require_startup_inventory,
            )
        except ServiceError as exc:
            raise T16RecoveryError(exc.code, outcome_unknown=exc.outcome_unknown) from None
        except Exception as exc:
            _LOG.error("T16 preparation raised unexpected %s", type(exc).__name__)
            raise T16RecoveryError("T16_EVIDENCE_PREPARATION_UNAVAILABLE",
                                   outcome_unknown=True) from None
        if type(preparation) is not T16ResolutionPreparation:
            raise T16RecoveryError("T16_EVIDENCE_PREPARATION_INVALID", outcome_unknown=True)

        identity = preparation.identity
        refs = preparation.evidence_refs
        try:
            change_uuid = UUID(identity.change_id)
        except (TypeError, ValueError, AttributeError):
            # Nothing has been sent to the gate yet, so this is a definitive local rejection.
            raise T16RecoveryError("T16_CHANGE_ID_INVALID") from None
        try:
            result = await self._resolution_gate.resolve_t16_s13(
                identity.scope,
                change_uuid,
                preparation.dispatch_cas_id,
                cosign_id,
                preparation.receipt_ref,
                refs.completion_proof_ref,
                refs.outcome_evidence_ref,
                refs.post_completion_challenge_ref,
                refs.read_attestation_ref,
            )
        except ServiceError as exc:
            raise T16RecoveryError(exc.code, outcome_unknown=exc.outcome_unknown) from None
        except Exception as exc:
            _LOG.error("T16 resolution gate raised unexpected %s", type(exc).__name__)
            raise T16RecoveryError("T16_RESOLUTION_OUTCOME_UNKNOWN",
                                   outcome_unknown=True) from None

        try:
            if type(result) is not dict:
                raise TypeError
            resolution = result["resolution"]
            checkpoint = result["checkpoint"]
            if type(resolution) is not dict or type(checkpoint) is not dict:
                raise TypeError
            event_id_raw = resolution["event_id"]
            event_seq = resolution["event_seq"]
            event_hash = resolution["event_hash"]
            hold_id = resolution["hold_id"]
            anchor_hold_ids = resolution["checkpoint_hold_ids"]
            resolution_state = resolution["execution_state"]
            checkpoint_ids = checkpoint["released_hold_ids"]
            event_id = UUID(event_id_raw)
            checkpoint_event_id = UUID(checkpoint["event_id"])
            checkpoint_seq = checkpoint["checkpoint_seq"]
            checkpoint_event_seq = checkpoint["event_seq"]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise T16RecoveryError("T16_CHECKPOINT_RESULT_INVALID", outcome_unknown=True) from None

        expected_released = [*anchor_hold_ids, hold_id] if type(anchor_hold_ids) is list else None
        if (resolution_state != "FAILED_APPLY"
                or type(resolution.get("checkpoint_required")) is not bool
                or resolution["checkpoint_required"] is not True
                or type(event_id_raw) is not str or str(event_id) != event_id_raw
                or event_id.int == 0
                or type(event_seq) is not int or event_seq < 1
                or type(event_hash) is not str or _SHA256_HEX.fullmatch(event_hash) is None
                or type(hold_id) is not str or not is_canonical_nonzero_uuid(hold_id)
                or type(anchor_hold_ids) is not list
                or not anchor_hold_ids
                or any(not is_canonical_nonzero_uuid(item) for item in anchor_hold_ids)
                or len(set(anchor_hold_ids)) != len(anchor_hold_ids)
                or hold_id in anchor_hold_ids
                or type(checkpoint["event_id"]) is not str
                or str(checkpoint_event_id) != checkpoint["event_id"]
                or checkpoint_event_id != event_id
                or type(checkpoint_seq) is not int or checkpoint_seq < 1
                or type(checkpoint_event_seq) is not int or checkpoint_event_seq != event_seq
                or type(checkpoint_ids) is not list or checkpoint_ids != expected_released):
            raise T16RecoveryError("T16_CHECKPOINT_RESULT_INVALID", outcome_unknown=True)

        try:
            call = await self._writer.record_recovered_terminal(
                ticket,
                permit,
                refs.outcome_evidence_ref,
                refs.completion_proof_ref,
                refs.post_completion_challenge_ref,
                refs.read_attestation_ref,
                event_id,
            )
        except ServiceError as exc:
            raise T16RecoveryError(exc.code, outcome_unknown=exc.outcome_unknown) from None
        except Exception as exc:
            _LOG.error("S13 terminalization raised unexpected %s", type(exc).__name__)
            raise T16RecoveryError("S13_TERMINALIZATION_OUTCOME_UNKNOWN",
                                   outcome_unknown=True) from None
        if (type(call) is not CallSnapshot or call.identity != identity
                or call.dispatch_cas_id != preparation.dispatch_cas_id
                or call.state is not AdmissionState.TERMINAL_WITH_EVIDENCE):
            raise T16RecoveryError("S13_TERMINAL_SNAPSHOT_INVALID", outcome_unknown=True)
        return T16RecoveryResult(event_id, event_seq, checkpoint_seq, call)


__all__ = ["T16RecoveryCoordinator", "T16RecoveryError", "T16RecoveryResult"]
