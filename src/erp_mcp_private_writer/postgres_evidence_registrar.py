"""Fail-closed persistence for validated S12 writer-receipt envelopes.

This adapter uses a separately injected evidence-ingest pool. It preserves the original signed
bytes, obtains the immutable attempt from PostgreSQL, validates the signature and trust snapshot,
then asks the database routine to recheck current key revocation and exact attempt binding while
registering the evidence. A host-owned authenticated build-attestation source is mandatory; a plain
configuration string is not accepted as validator provenance. It does not invoke COM or
terminalize an attempt.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime
from uuid import UUID

import asyncpg

from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    OutcomeEvidenceV2,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
    outcome_observation_digest,
)
from business_ai_gateway.phase2.change_ledger.uuid_contract import (
    is_canonical_process_instance_uuid as _canonical_process_instance_id,
)

from .postgres_attempt_source import (
    EvidenceAttemptContext,
    EvidenceAttemptSourceError,
    PostgresEvidenceAttemptSource,
)
from .postgres_identity import (
    EVIDENCE_INGEST_SESSION_USER,
    has_expected_database_identity,
)
from .production_evidence_verifier import (
    ProductionEvidenceVerificationError,
    ProductionEvidenceVerifier,
)
from .service import CallIdentity
from .validator_build_attestation import (
    _PRODUCTION_BUILD_AUTHORITY_SEAL,
    ApprovedValidatorBuild,
    ValidatorBuildAttestationError,
    ValidatorBuildAttestationVerifier,
)

_MAX_TIMEOUT_SECONDS = 5.0


class EvidenceRegistrationError(RuntimeError):
    """Stable registration errors without PostgreSQL or signed-envelope details."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


class PostgresWriterReceiptRegistrar:
    """Verify and register one exact writer receipt using the evidence-ingest principal."""

    __slots__ = (
        "_approved_build_policy_id",
        "_attempt_source",
        "_build_provenance_source",
        "_pool",
        "_timeout",
        "_verifier",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("EVIDENCE_REGISTER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("EVIDENCE_REGISTER_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, attempt_source: PostgresEvidenceAttemptSource,
                 verifier: ProductionEvidenceVerifier, *,
                 build_provenance_source: ValidatorBuildAttestationVerifier,
                 approved_build_policy_id: str,
                 timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("EVIDENCE_REGISTER_POOL_INVALID")
        if not isinstance(attempt_source, PostgresEvidenceAttemptSource):
            raise ValueError("EVIDENCE_REGISTER_ATTEMPT_SOURCE_INVALID")
        if not isinstance(verifier, ProductionEvidenceVerifier):
            raise ValueError("EVIDENCE_REGISTER_VERIFIER_INVALID")
        if type(build_provenance_source) is not ValidatorBuildAttestationVerifier:
            raise ValueError("EVIDENCE_REGISTER_BUILD_SOURCE_INVALID")
        if not build_provenance_source.has_production_authority_source:
            raise ValueError("EVIDENCE_REGISTER_BUILD_AUTHORITY_NOT_PRODUCTION")
        if (type(approved_build_policy_id) is not str or not approved_build_policy_id
                or approved_build_policy_id != approved_build_policy_id.strip()
                or len(approved_build_policy_id) > 128
                or any(ord(character) < 32 or ord(character) == 127
                       for character in approved_build_policy_id)):
            raise ValueError("EVIDENCE_REGISTER_BUILD_POLICY_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("EVIDENCE_REGISTER_TIMEOUT_INVALID")
        self._pool = pool
        self._attempt_source = attempt_source
        self._verifier = verifier
        self._build_provenance_source = build_provenance_source
        self._approved_build_policy_id = approved_build_policy_id
        self._timeout = float(timeout_seconds)

    @staticmethod
    def parse_envelope(envelope: bytes) -> object:
        """Parse a bounded canonical evidence envelope using the production verifier contract."""
        return ProductionEvidenceVerifier.parse_envelope(envelope)

    @staticmethod
    def evidence_ref(record: object) -> str:
        """Return the same immutable reference used by registration, without storing the record."""
        if type(record) is DispatchReceipt:
            record_type = ("DISPATCH_NO_ENTRY_RECEIPT_V1"
                           if record.result_class == "PRE_WRITE_NO_EFFECT"
                           else "DISPATCH_RECEIPT_V1")
        elif type(record) in (OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3):
            record_type = f"OUTCOME_EVIDENCE_V{int(record.evidence_version)}"
        elif type(record) is CompletionProof:
            record_type = "COMPLETION_PROOF_V1"
        elif type(record) is PostCompletionChallenge:
            record_type = "POST_COMPLETION_CHALLENGE_V1"
        elif type(record) is PostCompletionReadAttestation:
            record_type = "POST_COMPLETION_READ_ATTESTATION_V1"
        else:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_RECORD_TYPE_INVALID")
        return f"private-writer:evidence:v1:{record_type}:{record.calculated_digest()}"

    async def verify_and_store(self, identity: CallIdentity, dispatch_cas_id: UUID,
                               process_instance_id: str, receipt_envelope: bytes) -> str:
        """Persist a receipt only after exact identity, signature, trust, and CAS checks."""
        self._require_registration_authority(None)
        if (type(identity) is not CallIdentity or type(dispatch_cas_id) is not UUID
                or dispatch_cas_id.int == 0
                or not _canonical_process_instance_id(process_instance_id)
                or type(receipt_envelope) is not bytes or not receipt_envelope):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_REQUEST_INVALID")
        try:
            receipt = self._verifier.parse_envelope(receipt_envelope)
            if type(receipt) is not DispatchReceipt:
                raise ValueError
            context = await self._attempt_source.load_for_record(receipt)
            attempt = context.attempt
            self._check_identity(
                identity, dispatch_cas_id, process_instance_id, receipt, attempt,
                context.payload_digest, context.repair_authorization_id,
            )
            verified = await self._verifier.verify(receipt_envelope, attempt=attempt)
            approved_validator_build = await self._approved_validator_build()
        except EvidenceRegistrationError:
            raise
        except (EvidenceAttemptSourceError, ProductionEvidenceVerificationError, ValueError):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_VALIDATION_FAILED") from None
        except Exception:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_VALIDATION_FAILED") from None

        payload, evidence_ref = self._record_payload(
            dispatch_cas_id, process_instance_id, receipt_envelope, receipt, context,
            approved_validator_build.build_id, int(verified.trust_revision),
        )
        return await self._register(payload, evidence_ref, approved_validator_build)

    async def verify_set_and_store(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                   envelopes: tuple[bytes, ...]) -> tuple[str, ...]:
        """Verify one causal evidence set against one trust snapshot, then register each record.

        Each insert is committed separately. Partial registration is safely replayable while the
        attempt stays held; terminal routines alone associate evidence refs or release holds.
        """
        self._require_registration_authority(None)
        if (type(identity) is not CallIdentity or type(dispatch_cas_id) is not UUID
                or dispatch_cas_id.int == 0
                or type(envelopes) is not tuple or not 1 <= len(envelopes) <= 5
                or any(type(value) is not bytes or not value for value in envelopes)):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_REQUEST_INVALID")
        try:
            records = tuple(self._verifier.parse_envelope(value) for value in envelopes)
            for record in records:
                if any(getattr(record, field, None) != expected for field, expected in (
                    ("tenant_id", identity.tenant_id),
                    ("company_id", identity.company_id),
                    ("organization_ref", identity.organization_ref),
                    ("base_fingerprint", identity.base_fingerprint),
                    ("change_id", identity.change_id),
                    ("claim_generation", identity.generation),
                    ("call_id", identity.call_id),
                    ("operation_kind", identity.operation),
                )) or (hasattr(record, "dispatch_cas_id")
                       and record.dispatch_cas_id != str(dispatch_cas_id)):
                    raise EvidenceRegistrationError("EVIDENCE_REGISTER_IDENTITY_MISMATCH")
            context = await self._attempt_source.load_for_identity(
                dispatch_cas_id=dispatch_cas_id,
                call_id=identity.call_id,
                tenant_id=identity.tenant_id,
                company_id=identity.company_id,
                organization_ref=identity.organization_ref,
                base_fingerprint=identity.base_fingerprint,
            )
            self._check_attempt_identity(
                identity, dispatch_cas_id, context.attempt, context.payload_digest,
                context.repair_authorization_id,
            )
            verified = await self._verifier.verify_set(envelopes, attempt=context.attempt)
            approved_validator_build = await self._approved_validator_build()
        except EvidenceRegistrationError:
            raise
        except (EvidenceAttemptSourceError, ProductionEvidenceVerificationError, ValueError):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_VALIDATION_FAILED") from None
        except Exception:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_VALIDATION_FAILED") from None

        refs: list[str] = []
        for envelope, verified_record in zip(envelopes, verified, strict=True):
            try:
                record = verified_record.record
                if type(record) is DispatchReceipt:
                    if record.approved_payload_digest != context.payload_digest:
                        raise EvidenceRegistrationError("EVIDENCE_REGISTER_IDENTITY_MISMATCH")
                    payload, evidence_ref = self._record_payload(
                        dispatch_cas_id, context.attempt.writer_process_instance_id,
                        envelope, record, context, approved_validator_build.build_id,
                        int(verified_record.trust_revision),
                    )
                else:
                    payload, evidence_ref = self._typed_record_payload(
                        dispatch_cas_id, envelope, record, context,
                        approved_validator_build.build_id,
                        int(verified_record.trust_revision),
                    )
            except EvidenceRegistrationError:
                raise
            except Exception:
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_PROJECTION_INVALID") from None
            refs.append(await self._register(payload, evidence_ref, approved_validator_build))
        return tuple(refs)

    async def _approved_validator_build(self) -> ApprovedValidatorBuild:
        """Resolve only a cryptographically verified build attestation from the configured source."""
        self._require_registration_authority(None)
        try:
            async with asyncio.timeout(self._timeout):
                provenance = await self._build_provenance_source.load_current_approved_build()
        except TimeoutError:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_PROVENANCE_TIMEOUT") from None
        except ValidatorBuildAttestationError:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_PROVENANCE_INVALID") from None
        except Exception:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_PROVENANCE_UNAVAILABLE") from None
        if (type(provenance) is not ApprovedValidatorBuild
                or provenance.policy_id != self._approved_build_policy_id
                or type(provenance.build_id) is not str or len(provenance.build_id) != 64
                or any(character not in "0123456789abcdef" for character in provenance.build_id)):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_PROVENANCE_INVALID")
        self._require_registration_authority(provenance)
        return provenance

    def _require_registration_authority(
            self, provenance: ApprovedValidatorBuild | None) -> None:
        """Fence direct registrar calls as well as the runtime composition path."""
        if not self._build_provenance_source.has_production_authority_source:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_AUTHORITY_NOT_PRODUCTION")
        if (provenance is not None
                and (type(provenance) is not ApprovedValidatorBuild
                     or provenance._production_authority_seal
                     is not _PRODUCTION_BUILD_AUTHORITY_SEAL)):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_AUTHORITY_NOT_PRODUCTION")

    @staticmethod
    def _check_identity(identity: CallIdentity, dispatch_cas_id: UUID,
                        process_instance_id: str, receipt: DispatchReceipt,
                        attempt: object, payload_digest: str,
                        repair_authorization_id: str | None) -> None:
        PostgresWriterReceiptRegistrar._check_attempt_identity(
            identity, dispatch_cas_id, attempt, payload_digest, repair_authorization_id,
        )
        if (receipt.approved_payload_digest != identity.payload_digest
                or receipt.writer_process_instance_id != process_instance_id
                or receipt.writer_host_id != identity.host_id):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_IDENTITY_MISMATCH")

    @staticmethod
    def _check_attempt_identity(identity: CallIdentity, dispatch_cas_id: UUID,
                                attempt: object, payload_digest: str,
                                repair_authorization_id: str | None) -> None:
        expected = {
            "tenant_id": identity.tenant_id,
            "company_id": identity.company_id,
            "organization_ref": identity.organization_ref,
            "base_fingerprint": identity.base_fingerprint,
            "change_id": identity.change_id,
            "claim_generation": identity.generation,
            "dispatch_cas_id": str(dispatch_cas_id),
            "call_id": identity.call_id,
            "operation_kind": identity.operation,
            "auth_epoch": identity.epoch,
            "permit_id": identity.permit_id,
            "permit_digest": identity.permit_digest,
            "expected_target_ref": identity.target_ref,
            "expected_pre_version": identity.target_version,
            "writer_host_id": identity.host_id,
        }
        if (type(attempt) is not DispatchAttempt
                or any(getattr(attempt, name, object()) != value for name, value in expected.items())
                or payload_digest != identity.payload_digest
                or repair_authorization_id != identity.repair_authorization_id):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_IDENTITY_MISMATCH")

    def _record_payload(self, dispatch_cas_id: UUID, process_instance_id: str,
                        envelope: bytes, receipt: DispatchReceipt,
                        context: EvidenceAttemptContext,
                        validator_build_id: str,
                        trust_registry_revision: int) -> tuple[str, str]:
        if type(context) is not EvidenceAttemptContext:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_CONTEXT_INVALID")
        if (type(trust_registry_revision) is not int or trust_registry_revision <= 0
                or trust_registry_revision > 9_223_372_036_854_775_807):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_TRUST_REVISION_INVALID")
        digest = receipt.calculated_digest()
        record_type = ("DISPATCH_NO_ENTRY_RECEIPT_V1"
                       if receipt.result_class == "PRE_WRITE_NO_EFFECT"
                       else "DISPATCH_RECEIPT_V1")
        evidence_ref = self.evidence_ref(receipt)
        attempt = context.attempt
        record = {
            "evidence_ref": evidence_ref,
            "record_type": record_type,
            "writer_receipt_id": receipt.receipt_id,
            "writer_invocation_stage": receipt.write_invocation_stage,
            "writer_result_class": receipt.result_class,
            "writer_call_returned": receipt.call_returned,
            "writer_returned_at": receipt.returned_at,
            "writer_returned_target_ref": receipt.returned_target_ref,
            "writer_returned_version": receipt.returned_version,
            "no_effect_evidence_digest": receipt.no_effect_evidence_digest,
            "signed_bytes": "\\x" + envelope.hex(),
            "record_digest": digest,
            "tenant_id": attempt.tenant_id,
            "company_id": attempt.company_id,
            "organization_ref": attempt.organization_ref,
            "base_fingerprint": attempt.base_fingerprint,
            "change_id": attempt.change_id,
            "claim_generation": attempt.claim_generation,
            "dispatch_generation": attempt.dispatch_generation,
            "call_id": attempt.call_id,
            "dispatch_cas_id": str(dispatch_cas_id),
            "dispatch_intent_id": context.dispatch_intent_id,
            "operation_kind": attempt.operation_kind,
            "approval_digest": attempt.approval_digest,
            "payload_digest": context.payload_digest,
            "permit_id": attempt.permit_id,
            "permit_digest": attempt.permit_digest,
            "target_ref": attempt.expected_target_ref,
            "pre_version": attempt.expected_pre_version,
            "auth_epoch": attempt.auth_epoch,
            "repair_authorization_id": context.repair_authorization_id,
            "signer_key_id": receipt.signer_key_id,
            "signer_key_version": receipt.key_version,
            "signer_role": receipt.signer_role,
            "signer_service_id": receipt.writer_service_id,
            "signer_host_id": receipt.writer_host_id,
            "signed_at": datetime.strptime(
                receipt.started_at, "%Y-%m-%dT%H:%M:%S.%fZ",
            ).isoformat() + "+00:00",
            "trust_registry_revision": trust_registry_revision,
            "validator_build_id": validator_build_id,
            "process_instance_id": process_instance_id,
            "session_instance_id": receipt.onec_session_instance_id,
        }
        return (json.dumps(record, ensure_ascii=True, separators=(",", ":"), allow_nan=False),
                evidence_ref)

    def _typed_record_payload(self, dispatch_cas_id: UUID, envelope: bytes, record: object,
                              context: EvidenceAttemptContext,
                              validator_build_id: str,
                              trust_registry_revision: int) -> tuple[str, str]:
        if type(context) is not EvidenceAttemptContext:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_CONTEXT_INVALID")
        if (type(trust_registry_revision) is not int or trust_registry_revision <= 0
                or trust_registry_revision > 9_223_372_036_854_775_807):
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_TRUST_REVISION_INVALID")
        attempt = context.attempt
        if type(record) in (OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3):
            record_type = f"OUTCOME_EVIDENCE_V{int(record.evidence_version)}"
            signer_role = record.role
            signer_service_id = record.verifier_service_id
            signer_host_id = record.verifier_host_id
            signed_at = record.observed_at
            process_instance_id = None
            session_instance_id = None
            projection = {
                "outcome_evidence_version": int(record.evidence_version),
                "outcome_dispatch_receipt_id": record.dispatch_receipt_id,
                "outcome_target_ref": record.target_ref,
                "outcome_pre_version": record.pre_version,
                "outcome_observed_version": record.observed_version,
                "outcome_expected_effect_digest": record.expected_effect_digest,
                "outcome_observed_effect_digest": record.observed_effect_digest,
                "outcome_fields_match": record.fields_match,
                "outcome_movements_match": record.movements_match,
                "outcome_observation_complete": record.observation_complete,
                "outcome_reader_health": record.reader_health,
                "outcome_effect_presence": record.effect_presence,
                "outcome_effect_identity": record.effect_identity,
                "outcome_version_relation": record.version_relation,
                "outcome_attribution_result": record.attribution_result,
                "outcome_attribution_evidence_ref": record.attribution_evidence_ref,
                "outcome_uncertainty_count": len(record.uncertainties),
                "outcome_completion_proof_class": record.completion_proof_class,
                "outcome_completion_proof_digest": (
                    record.completion_proof_digest
                    if type(record) is OutcomeEvidenceV3 else None
                ),
                "outcome_challenge_id": (
                    record.post_completion_challenge_id
                    if type(record) is OutcomeEvidenceV3 else None
                ),
                "outcome_verification_sequence": (
                    record.verification_sequence
                    if type(record) is OutcomeEvidenceV3 else None
                ),
                "outcome_observation_digest": (
                    outcome_observation_digest(record)
                    if type(record) is OutcomeEvidenceV3 else None
                ),
                "outcome_read_attestation_digest": (
                    record.read_attestation_digest
                    if type(record) is OutcomeEvidenceV3 else None
                ),
            }
        elif type(record) is CompletionProof:
            record_type = "COMPLETION_PROOF_V1"
            signer_role = record.signer_role
            signer_service_id = record.source_service_id
            signer_host_id = record.source_host_id
            signed_at = record.observed_at
            process_instance_id = record.source_process_instance_id
            session_instance_id = record.observed_session_instance_id
            projection = {
                "completion_proof_id": record.completion_proof_id,
                "completion_proof_class": record.proof_class,
            }
        elif type(record) is PostCompletionChallenge:
            record_type = "POST_COMPLETION_CHALLENGE_V1"
            signer_role = record.signer_role
            signer_service_id = record.issuer_service_id
            signer_host_id = record.issuer_host_id
            signed_at = record.issued_at
            process_instance_id = None
            session_instance_id = None
            projection = {
                "challenge_id": record.challenge_id,
                "challenge_sequence_floor": record.verification_sequence_floor,
            }
        elif type(record) is PostCompletionReadAttestation:
            record_type = "POST_COMPLETION_READ_ATTESTATION_V1"
            signer_role = record.signer_role
            signer_service_id = record.attestor_service_id
            signer_host_id = record.attestor_host_id
            signed_at = record.completed_at
            process_instance_id = record.process_instance_id
            session_instance_id = None
            projection = {
                "read_attestation_sequence": record.verification_sequence,
                "read_attestation_outcome_digest": record.outcome_observation_digest,
            }
        else:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_RECORD_TYPE_INVALID")

        digest = record.calculated_digest()
        evidence_ref = self.evidence_ref(record)
        values = {
            "evidence_ref": evidence_ref,
            "record_type": record_type,
            "signed_bytes": "\\x" + envelope.hex(),
            "record_digest": digest,
            "tenant_id": attempt.tenant_id,
            "company_id": attempt.company_id,
            "organization_ref": attempt.organization_ref,
            "base_fingerprint": attempt.base_fingerprint,
            "change_id": attempt.change_id,
            "claim_generation": attempt.claim_generation,
            "dispatch_generation": attempt.dispatch_generation,
            "call_id": attempt.call_id,
            "dispatch_cas_id": str(dispatch_cas_id),
            "dispatch_intent_id": context.dispatch_intent_id,
            "operation_kind": attempt.operation_kind,
            "approval_digest": attempt.approval_digest,
            "payload_digest": context.payload_digest,
            "permit_id": attempt.permit_id,
            "permit_digest": attempt.permit_digest,
            "target_ref": attempt.expected_target_ref,
            "pre_version": attempt.expected_pre_version,
            "auth_epoch": attempt.auth_epoch,
            "repair_authorization_id": context.repair_authorization_id,
            "signer_key_id": record.signer_key_id,
            "signer_key_version": record.key_version,
            "signer_role": signer_role,
            "signer_service_id": signer_service_id,
            "signer_host_id": signer_host_id,
            "signed_at": datetime.strptime(
                signed_at, "%Y-%m-%dT%H:%M:%S.%fZ",
            ).isoformat() + "+00:00",
            "trust_registry_revision": trust_registry_revision,
            "validator_build_id": validator_build_id,
            "process_instance_id": process_instance_id,
            "session_instance_id": session_instance_id,
            **projection,
        }
        return (json.dumps(values, ensure_ascii=True, separators=(",", ":"), allow_nan=False),
                evidence_ref)

    async def _register(self, record_json: str, expected_ref: str,
                        approved_build: ApprovedValidatorBuild) -> str:
        self._require_registration_authority(approved_build)
        deadline = time.monotonic() + self._timeout
        try:
            # Re-read the current attestation/policy immediately before registration. A policy,
            # revocation, deployment or artifact change between envelope verification and this
            # point refuses before opening the evidence transaction or issuing its INSERT.
            current_build = await self._approved_validator_build()
            if not self._same_validator_build_authority(approved_build, current_build):
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_BUILD_POLICY_STALE")
            async with asyncio.timeout(self._timeout):
                async with self._pool.acquire(timeout=self._timeout) as conn:
                    if conn.is_in_transaction():
                        raise EvidenceRegistrationError(
                            "EVIDENCE_REGISTER_OUTCOME_UNKNOWN", outcome_unknown=True,
                        )
                    return await self._register_on_connection(
                        conn, record_json, expected_ref, deadline,
                    )
        except EvidenceRegistrationError:
            raise
        except TimeoutError:
            raise EvidenceRegistrationError(
                "EVIDENCE_REGISTER_TIMEOUT", outcome_unknown=True,
            ) from None
        except Exception:
            raise EvidenceRegistrationError("EVIDENCE_REGISTER_UNAVAILABLE") from None

    @staticmethod
    def _same_validator_build_authority(expected: ApprovedValidatorBuild,
                                        current: ApprovedValidatorBuild) -> bool:
        return (type(expected) is ApprovedValidatorBuild
                and type(current) is ApprovedValidatorBuild
                and expected.build_id == current.build_id
                and expected.policy_id == current.policy_id
                and expected.policy_version == current.policy_version
                and expected.attestation_id == current.attestation_id
                and expected.image_digest == current.image_digest
                and expected.source_revision == current.source_revision
                and expected.deployment_id == current.deployment_id
                and expected.environment_id == current.environment_id
                and expected.trust_revision == current.trust_revision
                and expected.attestation_sha256 == current.attestation_sha256
                and expected._production_authority_seal
                is current._production_authority_seal)

    async def _register_on_connection(self, conn: asyncpg.Connection, record_json: str,
                                      expected_ref: str, deadline: float) -> str:
        attempted = False
        transaction = conn.transaction()
        try:
            try:
                await transaction.start()
            except BaseException:
                conn.terminate()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            await conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            await conn.execute(
                "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                f"{max(1, math.ceil(remaining * 1000))}ms",
            )
            if not await has_expected_database_identity(
                    conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_DATABASE_IDENTITY_INVALID")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            attempted = True
            async with asyncio.timeout(remaining):
                evidence_ref = await conn.fetchval(
                    "SELECT change_ledger.private_writer_register_evidence_v1("
                    "pg_catalog.jsonb_populate_record("
                    "NULL::change_ledger.private_writer_evidence, $1::jsonb))",
                    record_json,
                )
            if type(evidence_ref) is not str or evidence_ref != expected_ref:
                raise EvidenceRegistrationError(
                    "EVIDENCE_REGISTER_OUTCOME_UNKNOWN", outcome_unknown=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                await transaction.commit()
            return evidence_ref
        except EvidenceRegistrationError:
            await self._rollback_or_terminate(conn, transaction, deadline)
            raise
        except asyncpg.PostgresError as exc:
            await self._rollback_or_terminate(conn, transaction, deadline)
            sqlstate = getattr(exc, "sqlstate", None)
            message = getattr(exc, "message", None)
            if sqlstate == "57014":
                raise EvidenceRegistrationError(
                    "EVIDENCE_REGISTER_TIMEOUT", outcome_unknown=attempted,
                ) from None
            if sqlstate == "42501" and message == "NOT_ENTITLED":
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_NOT_ENTITLED") from None
            if sqlstate == "P0001" and message == "EVIDENCE_IDENTITY_CONFLICT":
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_IDENTITY_CONFLICT") from None
            if sqlstate == "P0001" and message == "RECOVERY_EVIDENCE_REJECTED":
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_REJECTED") from None
            if sqlstate == "P0001" and message == "EVIDENCE_TRUST_REVISION_STALE":
                raise EvidenceRegistrationError("EVIDENCE_REGISTER_TRUST_REVISION_STALE") from None
            raise EvidenceRegistrationError(
                "EVIDENCE_REGISTER_OUTCOME_UNKNOWN" if attempted
                else "EVIDENCE_REGISTER_UNAVAILABLE",
                outcome_unknown=attempted,
            ) from None
        except TimeoutError:
            await self._rollback_or_terminate(conn, transaction, deadline)
            raise EvidenceRegistrationError(
                "EVIDENCE_REGISTER_TIMEOUT", outcome_unknown=attempted,
            ) from None
        except Exception:
            await self._rollback_or_terminate(conn, transaction, deadline)
            raise EvidenceRegistrationError(
                "EVIDENCE_REGISTER_OUTCOME_UNKNOWN" if attempted
                else "EVIDENCE_REGISTER_UNAVAILABLE",
                outcome_unknown=attempted,
            ) from None

    @staticmethod
    async def _rollback_or_terminate(conn: asyncpg.Connection,
                                     transaction: asyncpg.Transaction,
                                     deadline: float) -> None:
        try:
            if conn.is_in_transaction():
                remaining = max(0.001, min(1.0, deadline - time.monotonic()))
                async with asyncio.timeout(remaining):
                    await transaction.rollback()
        except BaseException:
            conn.terminate()


__all__ = ["EvidenceRegistrationError", "PostgresWriterReceiptRegistrar"]
