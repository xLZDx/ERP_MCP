"""Verify and register complete S12 outcome evidence bundles for S13 recovery."""
from __future__ import annotations

import asyncio
import math
from typing import Awaitable, Callable, Protocol
from uuid import UUID

from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchReceipt,
    OutcomeEvidence,
    OutcomeEvidenceV2,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
)

from .postgres_evidence_registrar import PostgresWriterReceiptRegistrar
from .dependency_shape import has_static_callable_method
from .service import (
    CallIdentity,
    ConditionalConflictEvidenceRefs,
    OutcomeEvidenceProvider,
    SuccessfulOutcomeEvidence,
)


class OutcomeEvidenceBundleSource(Protocol):
    """Load original signed envelopes; this source is not itself a trust authority."""

    async def load_success_bundle(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str) -> tuple[bytes, ...]:
        """Return the exact receipt, independent outcome, and completion proof envelopes."""
        ...

    async def load_conditional_conflict_bundle(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str) -> tuple[bytes, ...]:
        """Return the five signed records in the entered-conflict causal chain."""
        ...


def _record_role(record: object) -> str | None:
    if type(record) is DispatchReceipt:
        return "receipt"
    if type(record) in (OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3):
        return "outcome"
    if type(record) is CompletionProof:
        return "completion"
    if type(record) is PostCompletionChallenge:
        return "challenge"
    if type(record) is PostCompletionReadAttestation:
        return "read_attestation"
    return None


class PostgresOutcomeEvidenceProvider(OutcomeEvidenceProvider):
    """Register exact signed bundles before returning references to terminal routines.

    The supplied source may locate or fetch envelopes, but it cannot authorize them. The registrar
    reloads the exact dispatch attempt, verifies the whole set against one current trust snapshot,
    checks signed identities and build provenance, then durably registers each immutable record.
    """

    __slots__ = ("_source", "_registrar", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("OUTCOME_EVIDENCE_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("OUTCOME_EVIDENCE_CONFIGURATION_IMMUTABLE")

    def __init__(self, source: OutcomeEvidenceBundleSource,
                 registrar: PostgresWriterReceiptRegistrar, *,
                 timeout_seconds: float = 5.0) -> None:
        if any(not has_static_callable_method(source, method) for method in (
                "load_success_bundle", "load_conditional_conflict_bundle")):
            raise ValueError("OUTCOME_EVIDENCE_SOURCE_INVALID")
        if not isinstance(registrar, PostgresWriterReceiptRegistrar):
            raise ValueError("OUTCOME_EVIDENCE_REGISTRAR_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 5.0
                or not math.isfinite(timeout_seconds)):
            raise ValueError("OUTCOME_EVIDENCE_TIMEOUT_INVALID")
        self._source = source
        self._registrar = registrar
        self._timeout = float(timeout_seconds)

    @staticmethod
    def _validated_roles(
            envelopes: object, *, conflict: bool) -> tuple[tuple[bytes, ...], dict[str, int]]:
        expected_roles = (
            {"receipt", "outcome", "completion", "challenge", "read_attestation"}
            if conflict else {"receipt", "outcome", "completion"}
        )
        if (type(envelopes) is not tuple or len(envelopes) != len(expected_roles)
                or any(type(envelope) is not bytes or not envelope for envelope in envelopes)):
            raise ValueError("OUTCOME_EVIDENCE_BUNDLE_INVALID")
        try:
            records = tuple(PostgresWriterReceiptRegistrar.parse_envelope(envelope)
                            for envelope in envelopes)
        except Exception:
            raise ValueError("OUTCOME_EVIDENCE_BUNDLE_INVALID") from None
        roles = tuple(_record_role(record) for record in records)
        if (any(role is None for role in roles) or set(roles) != expected_roles
                or len(set(roles)) != len(roles)):
            raise ValueError("OUTCOME_EVIDENCE_BUNDLE_INVALID")
        if conflict and type(records[roles.index("outcome")]) not in (
                OutcomeEvidenceV3,):
            # The S13 conditional-conflict path requires the nonce-bound V3 read attestation.
            raise ValueError("OUTCOME_EVIDENCE_BUNDLE_INVALID")
        return envelopes, {role: index for index, role in enumerate(roles) if role is not None}

    async def _load_bundle(self, loader: Callable[..., Awaitable[tuple[bytes, ...]]],
                           identity: CallIdentity, dispatch_cas_id: UUID,
                           receipt_ref: str) -> tuple[bytes, ...]:
        """Keep locator failures out of callers while preserving cancellation semantics."""
        try:
            return await loader(identity, dispatch_cas_id, receipt_ref)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ValueError("OUTCOME_EVIDENCE_SOURCE_UNAVAILABLE") from None

    async def verify_success(self, identity: CallIdentity, dispatch_cas_id: UUID,
                             receipt_ref: str) -> SuccessfulOutcomeEvidence:
        if (type(identity) is not CallIdentity or type(dispatch_cas_id) is not UUID
                or dispatch_cas_id.int == 0 or type(receipt_ref) is not str or not receipt_ref):
            raise ValueError("OUTCOME_EVIDENCE_REQUEST_INVALID")
        try:
            async with asyncio.timeout(self._timeout):
                return await self._verify_success(identity, dispatch_cas_id, receipt_ref)
        except TimeoutError:
            raise ValueError("OUTCOME_EVIDENCE_TIMEOUT") from None

    async def _verify_success(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              receipt_ref: str) -> SuccessfulOutcomeEvidence:
        envelopes, role_indexes = self._validated_roles(
            await self._load_bundle(
                self._source.load_success_bundle, identity, dispatch_cas_id, receipt_ref,
            ),
            conflict=False,
        )
        parsed_receipt = PostgresWriterReceiptRegistrar.parse_envelope(
            envelopes[role_indexes["receipt"]],
        )
        if (type(parsed_receipt) is not DispatchReceipt
                or parsed_receipt.result_class != "CALL_RETURNED_SUCCESS"
                or parsed_receipt.write_invocation_stage != "ENTERED"
                or parsed_receipt.call_returned is not True
                or PostgresWriterReceiptRegistrar.evidence_ref(parsed_receipt) != receipt_ref):
            raise ValueError("OUTCOME_EVIDENCE_RECEIPT_INVALID")
        completion = PostgresWriterReceiptRegistrar.parse_envelope(
            envelopes[role_indexes["completion"]],
        )
        if (type(completion) is not CompletionProof
                or completion.proof_class != "WRITER_CALL_RETURNED"):
            raise ValueError("OUTCOME_EVIDENCE_COMPLETION_INVALID")

        refs = await self._registrar.verify_set_and_store(identity, dispatch_cas_id, envelopes)
        if type(refs) is not tuple or len(refs) != len(envelopes):
            raise ValueError("OUTCOME_EVIDENCE_REGISTRATION_INVALID")
        outcome_ref = refs[role_indexes["outcome"]]
        completion_ref = refs[role_indexes["completion"]]
        if any(type(value) is not str or not value for value in (outcome_ref, completion_ref)):
            raise ValueError("OUTCOME_EVIDENCE_REGISTRATION_INVALID")
        return SuccessfulOutcomeEvidence(outcome_ref, completion_ref)

    async def verify_conditional_conflict(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str) -> ConditionalConflictEvidenceRefs:
        if (type(identity) is not CallIdentity or type(dispatch_cas_id) is not UUID
                or dispatch_cas_id.int == 0 or type(receipt_ref) is not str or not receipt_ref):
            raise ValueError("OUTCOME_EVIDENCE_REQUEST_INVALID")
        try:
            async with asyncio.timeout(self._timeout):
                return await self._verify_conditional_conflict(
                    identity, dispatch_cas_id, receipt_ref,
                )
        except TimeoutError:
            raise ValueError("OUTCOME_EVIDENCE_TIMEOUT") from None

    async def _verify_conditional_conflict(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str) -> ConditionalConflictEvidenceRefs:
        envelopes, role_indexes = self._validated_roles(
            await self._load_bundle(
                self._source.load_conditional_conflict_bundle,
                identity, dispatch_cas_id, receipt_ref,
            ),
            conflict=True,
        )
        parsed_receipt = PostgresWriterReceiptRegistrar.parse_envelope(
            envelopes[role_indexes["receipt"]],
        )
        if (type(parsed_receipt) is not DispatchReceipt
                or parsed_receipt.result_class != "CONDITIONAL_VERSION_CONFLICT"
                or parsed_receipt.write_invocation_stage != "ENTERED"
                or parsed_receipt.call_returned is not True
                or PostgresWriterReceiptRegistrar.evidence_ref(parsed_receipt) != receipt_ref):
            raise ValueError("OUTCOME_EVIDENCE_RECEIPT_INVALID")
        completion = PostgresWriterReceiptRegistrar.parse_envelope(
            envelopes[role_indexes["completion"]],
        )
        if (type(completion) is not CompletionProof
                or completion.proof_class != "WRITER_CALL_RETURNED"):
            raise ValueError("OUTCOME_EVIDENCE_COMPLETION_INVALID")

        refs = await self._registrar.verify_set_and_store(identity, dispatch_cas_id, envelopes)
        if type(refs) is not tuple or len(refs) != len(envelopes):
            raise ValueError("OUTCOME_EVIDENCE_REGISTRATION_INVALID")
        result = ConditionalConflictEvidenceRefs(
            completion_proof_ref=refs[role_indexes["completion"]],
            post_completion_challenge_ref=refs[role_indexes["challenge"]],
            outcome_evidence_ref=refs[role_indexes["outcome"]],
            read_attestation_ref=refs[role_indexes["read_attestation"]],
        )
        return result


__all__ = ["OutcomeEvidenceBundleSource", "PostgresOutcomeEvidenceProvider"]
