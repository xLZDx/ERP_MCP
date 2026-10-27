"""Fail-closed production verifier candidate for canonical S12 evidence envelopes.

The verifier is inert until a trusted snapshot source and caller are injected. It never registers
evidence or opens a database/1C connection. Validation time comes from the authoritative trust
snapshot load's server timestamp; a timestamp inside a signed envelope is not itself a trusted
clock reading. Its result is provisional and cannot authorize evidence registration without the
database's current-key/revocation recheck.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeAlias

from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    OutcomeEvidenceV2,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
    _Envelope,
    canonical_json_bytes,
    validate_conditional_conflict_terminal_evidence,
)

from .dpapi_signer import verify_ed25519
from .dependency_shape import has_static_callable_method
from .json_preflight import (
    MAX_JSON_DOCUMENT_DEPTH,
    MAX_JSON_DOCUMENT_STRUCTURAL_NODES,
    check_json_document_limits,
)
from .evidence_trust import (
    EvidenceScope,
    EvidenceTrustSnapshot,
    ProductionEvidenceTrustSource,
    SignerKeyRef,
    TrustSnapshotRequest,
    TrustedProcessBinding,
    TrustedSigner,
    is_canonical_positive_trust_revision,
)

EvidenceRecord: TypeAlias = (
    DispatchReceipt | OutcomeEvidence | OutcomeEvidenceV2 | OutcomeEvidenceV3 | CompletionProof
    | PostCompletionChallenge | PostCompletionReadAttestation
)
_RECORD_TYPES: tuple[type[_Envelope], ...] = (
    DispatchReceipt, OutcomeEvidenceV3, OutcomeEvidenceV2, OutcomeEvidence,
    CompletionProof, PostCompletionChallenge, PostCompletionReadAttestation,
)
_PROCESS_ATTESTATION_PREFIX = b"ERP_MCP_R2:S13:PROCESS-INSTANCE:v1\n"
_MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
_MIN_EVIDENCE_INTEGER = -(2 ** 63)
_MAX_EVIDENCE_INTEGER = 2 ** 63 - 1


def _bounded_evidence_integer(value: str) -> int:
    """Decode only values representable by the PostgreSQL BIGINT evidence fields."""
    max_digits = 20 if value.startswith("-") else 19
    if len(value) > max_digits:
        raise ValueError
    parsed = int(value)
    if not _MIN_EVIDENCE_INTEGER <= parsed <= _MAX_EVIDENCE_INTEGER:
        raise ValueError
    return parsed


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError


def _reject_json_float(_value: str) -> object:
    """The S12 canonical JSON contract represents evidence numbers as integers only."""
    raise ValueError


class ProductionEvidenceVerificationError(RuntimeError):
    """Stable refusals that do not expose key bytes, evidence contents, or source details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class VerifiedEvidenceRecord:
    """Provisional envelope verification; not authority to register or terminalize evidence."""

    record: EvidenceRecord
    trust_revision: str
    validated_at: datetime
    envelope_sha256: str

    def __post_init__(self) -> None:
        if type(self.record) not in _RECORD_TYPES:
            raise ValueError("VERIFIED_EVIDENCE_RECORD_INVALID")
        if (not is_canonical_positive_trust_revision(self.trust_revision)
                or type(self.validated_at) is not datetime or self.validated_at.tzinfo is None
                or self.validated_at.utcoffset() is None
                or self.validated_at.utcoffset().total_seconds() != 0
                or type(self.envelope_sha256) is not str or len(self.envelope_sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.envelope_sha256)):
            raise ValueError("VERIFIED_EVIDENCE_METADATA_INVALID")


class ProductionEvidenceVerifier:
    """Validate one canonical signed record against a single authoritative trust snapshot.

    This candidate is intentionally separate from the evaluation-only registry verifier. The
    source must load a coherent authoritative snapshot and include supervisor keys referenced by
    requested process bindings. A conditional-conflict outcome also requires the related typed
    records for structural cross-binding, but callers must separately verify each related record's
    original bytes before using the complete set. The writer-receipt registrar composes the
    single-receipt path; related outcome and completion records still require their own adapters.
    """

    __slots__ = ("_source", "_max_snapshot_age")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("EVIDENCE_VERIFIER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("EVIDENCE_VERIFIER_CONFIGURATION_IMMUTABLE")

    def __init__(self, source: ProductionEvidenceTrustSource, *,
                 max_snapshot_age_seconds: float = 3.0) -> None:
        if not has_static_callable_method(source, "load_snapshot"):
            raise ValueError("EVIDENCE_TRUST_SOURCE_INVALID")
        if (isinstance(max_snapshot_age_seconds, bool)
                or not isinstance(max_snapshot_age_seconds, (int, float))
                or not 0 < max_snapshot_age_seconds <= 10.0
                or not math.isfinite(max_snapshot_age_seconds)):
            raise ValueError("EVIDENCE_TRUST_SNAPSHOT_AGE_INVALID")
        self._source = source
        self._max_snapshot_age = float(max_snapshot_age_seconds)

    @staticmethod
    def parse_envelope(envelope: bytes) -> EvidenceRecord:
        """Parse one bounded canonical envelope before an exact-attempt lookup is available."""
        return ProductionEvidenceVerifier._parse(envelope)

    async def verify(self, envelope: bytes, *, attempt: DispatchAttempt,
                     receipt: DispatchReceipt | None = None,
                     completion: CompletionProof | None = None,
                     challenge: PostCompletionChallenge | None = None,
                     read_attestation: PostCompletionReadAttestation | None = None) -> VerifiedEvidenceRecord:
        """Verify one envelope's exact signed bytes; never persists the record.

        Optional related records are checked for cross-binding only. Their own signatures are not
        vouched for by this call and each original envelope must be passed to ``verify`` separately.
        The trust source must return a fresh, non-cached snapshot whose loaded_at is its
        server-clock sample; snapshot loading and validation share one monotonic freshness
        deadline. The result remains provisional: registration must recheck current revocation
        under the database key-version lock before accepting the record.
        """
        if (type(envelope) is not bytes or not envelope or len(envelope) > _MAX_ENVELOPE_BYTES
                or type(attempt) is not DispatchAttempt):
            raise ProductionEvidenceVerificationError("EVIDENCE_VALIDATION_CONTEXT_INVALID")
        try:
            record = self._parse(envelope)
            scope = EvidenceScope(
                attempt.tenant_id, attempt.company_id, attempt.organization_ref,
                attempt.base_fingerprint,
            )
            self._validate_binding(record, attempt, receipt, completion, challenge, read_attestation)
            signer_key, signer_role, service_id, host_id, signed_at = self._signer_fields(record)
            process_ids = self._process_ids(record)
            oracle_id, oracle_version = self._oracle_fields(record)
            request = TrustSnapshotRequest(
                scope=scope,
                operation_kind=record.operation_kind,
                signer_keys=(signer_key,),
                process_instance_ids=process_ids,
                oracle_id=oracle_id,
                oracle_version=oracle_version,
                include_operation_oracle_policy=type(record) is OutcomeEvidence,
            )
        except ProductionEvidenceVerificationError:
            raise
        except Exception:
            raise ProductionEvidenceVerificationError("EVIDENCE_ENVELOPE_OR_BINDING_INVALID") from None

        snapshot_started = time.monotonic()
        try:
            async with asyncio.timeout(self._max_snapshot_age):
                snapshot = await self._source.load_snapshot(request)
        except (TimeoutError, asyncio.TimeoutError):
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SOURCE_TIMEOUT") from None
        except Exception:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SOURCE_UNAVAILABLE") from None
        if type(snapshot) is not EvidenceTrustSnapshot:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INVALID")
        validation_time = snapshot.loaded_at
        if time.monotonic() - snapshot_started > self._max_snapshot_age:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_STALE")
        self._check_snapshot(snapshot, request)
        signer = snapshot.signer(signer_key)
        if signer is None:
            raise ProductionEvidenceVerificationError("EVIDENCE_SIGNER_UNKNOWN")
        self._check_signer(signer, signer_key, signer_role, service_id, host_id,
                           scope, signed_at, validation_time)
        self._check_record_signature(record, signer)
        self._check_policy(record, snapshot, scope)
        self._check_process_bindings(record, attempt, snapshot, scope, validation_time)
        if time.monotonic() - snapshot_started > self._max_snapshot_age:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_STALE")
        return VerifiedEvidenceRecord(
            record=record,
            trust_revision=snapshot.revision,
            validated_at=validation_time,
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
        )

    async def verify_set(self, envelopes: tuple[bytes, ...], *,
                         attempt: DispatchAttempt) -> tuple[VerifiedEvidenceRecord, ...]:
        """Verify one causal evidence set against exactly one fresh trust snapshot.

        Every envelope is parsed and structurally bound before the sole trust-source call. The
        set accepts at most one record of each causal role (and one outcome version), preventing
        callers from selecting competing records while still allowing the full five-record
        conditional-conflict chain.
        """
        if (type(envelopes) is not tuple or not 1 <= len(envelopes) <= 5
                or type(attempt) is not DispatchAttempt):
            raise ProductionEvidenceVerificationError("EVIDENCE_VALIDATION_CONTEXT_INVALID")
        records = tuple(self._parse(envelope) for envelope in envelopes)
        if len({type(record) for record in records}) != len(records):
            raise ProductionEvidenceVerificationError("EVIDENCE_ENVELOPE_INVALID")

        by_type = {type(record): record for record in records}
        outcomes = tuple(record for record in records if type(record) in (
            OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3,
        ))
        if len(outcomes) > 1:
            raise ProductionEvidenceVerificationError("EVIDENCE_ENVELOPE_INVALID")
        receipt = by_type.get(DispatchReceipt)
        completion = by_type.get(CompletionProof)
        challenge = by_type.get(PostCompletionChallenge)
        read_attestation = by_type.get(PostCompletionReadAttestation)
        try:
            for record in records:
                self._validate_binding(
                    record, attempt, receipt, completion, challenge, read_attestation,
                )
            signer_values = tuple(self._signer_fields(record) for record in records)
            signer_keys = tuple(sorted(
                {value[0] for value in signer_values},
                key=lambda key: (key.key_id, key.key_version),
            ))
            process_ids = tuple(sorted({
                process_id for record in records for process_id in self._process_ids(record)
            }))
            oracle_refs = set()
            for record in records:
                oracle_ref = self._oracle_fields(record)
                if oracle_ref[0] is not None:
                    oracle_refs.add(oracle_ref)
            if len(oracle_refs) > 1:
                raise ValueError("EVIDENCE_ORACLE_SET_CONFLICT")
            oracle_id, oracle_version = next(iter(oracle_refs), (None, None))
            request = TrustSnapshotRequest(
                scope=EvidenceScope(
                    attempt.tenant_id, attempt.company_id, attempt.organization_ref,
                    attempt.base_fingerprint,
                ),
                operation_kind=attempt.operation_kind,
                signer_keys=signer_keys,
                process_instance_ids=process_ids,
                oracle_id=oracle_id,
                oracle_version=oracle_version,
                include_operation_oracle_policy=any(
                    type(record) is OutcomeEvidence for record in outcomes
                ),
            )
        except ProductionEvidenceVerificationError:
            raise
        except Exception:
            raise ProductionEvidenceVerificationError(
                "EVIDENCE_ENVELOPE_OR_BINDING_INVALID",
            ) from None

        snapshot_started = time.monotonic()
        try:
            async with asyncio.timeout(self._max_snapshot_age):
                snapshot = await self._source.load_snapshot(request)
        except (TimeoutError, asyncio.TimeoutError):
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SOURCE_TIMEOUT") from None
        except Exception:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SOURCE_UNAVAILABLE") from None
        if type(snapshot) is not EvidenceTrustSnapshot:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INVALID")
        validation_time = snapshot.loaded_at
        if time.monotonic() - snapshot_started > self._max_snapshot_age:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_STALE")
        self._check_snapshot(snapshot, request)

        verified: list[VerifiedEvidenceRecord] = []
        for envelope, record, signer_fields in zip(
                envelopes, records, signer_values, strict=True):
            signer_key, signer_role, service_id, host_id, signed_at = signer_fields
            signer = snapshot.signer(signer_key)
            if signer is None:
                raise ProductionEvidenceVerificationError("EVIDENCE_SIGNER_UNKNOWN")
            self._check_signer(
                signer, signer_key, signer_role, service_id, host_id,
                request.scope, signed_at, validation_time,
            )
            self._check_record_signature(record, signer)
            self._check_policy(record, snapshot, request.scope)
            self._check_process_bindings(
                record, attempt, snapshot, request.scope, validation_time,
            )
            if time.monotonic() - snapshot_started > self._max_snapshot_age:
                raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_STALE")
            verified.append(VerifiedEvidenceRecord(
                record=record,
                trust_revision=snapshot.revision,
                validated_at=validation_time,
                envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            ))
        return tuple(verified)

    @staticmethod
    def _parse(envelope: bytes) -> EvidenceRecord:
        try:
            if type(envelope) is not bytes or not envelope or len(envelope) > _MAX_ENVELOPE_BYTES:
                raise ValueError
            document = envelope.decode("utf-8", errors="strict")
            check_json_document_limits(
                document,
                max_depth=MAX_JSON_DOCUMENT_DEPTH,
                max_structural_nodes=MAX_JSON_DOCUMENT_STRUCTURAL_NODES,
            )
            parsed = json.loads(
                document,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
                parse_float=_reject_json_float,
                parse_int=_bounded_evidence_integer,
            )
            if type(parsed) is not dict:
                raise ValueError
            matches = [record_type for record_type in _RECORD_TYPES
                       if set(parsed) == record_type.SCHEMA]
            if len(matches) != 1 or canonical_json_bytes(parsed) != envelope:
                raise ValueError
            return matches[0].from_mapping(parsed)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
            raise ProductionEvidenceVerificationError("EVIDENCE_ENVELOPE_INVALID") from None


    @staticmethod
    def _validate_binding(record: EvidenceRecord, attempt: DispatchAttempt,
                          receipt: DispatchReceipt | None,
                          completion: CompletionProof | None,
                          challenge: PostCompletionChallenge | None,
                          read_attestation: PostCompletionReadAttestation | None) -> None:
        if type(record) is DispatchReceipt:
            record.validate_attempt_binding(attempt)
        elif type(record) in (OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3):
            record.validate_attempt_binding(attempt, receipt)
            if (type(record) is OutcomeEvidenceV3 and receipt is not None
                    and receipt.result_class == "CONDITIONAL_VERSION_CONFLICT"):
                if (type(completion) is not CompletionProof
                        or type(challenge) is not PostCompletionChallenge
                        or type(read_attestation) is not PostCompletionReadAttestation):
                    raise ValueError("CONFLICT_TERMINAL_EVIDENCE_REQUIRED")
                validate_conditional_conflict_terminal_evidence(
                    attempt, receipt, record, completion, challenge, read_attestation,
                )
        elif type(record) is CompletionProof:
            record.validate_attempt_binding(attempt, receipt)
        elif type(record) is PostCompletionChallenge:
            if type(completion) is not CompletionProof:
                raise ValueError("COMPLETION_PROOF_REQUIRED")
            record.validate_attempt_binding(attempt, completion)
        elif type(record) is PostCompletionReadAttestation:
            if type(challenge) is not PostCompletionChallenge:
                raise ValueError("POST_COMPLETION_CHALLENGE_REQUIRED")
            record.validate_attempt_binding(attempt, challenge)
        else:
            raise ValueError("EVIDENCE_TYPE_UNSUPPORTED")

    @staticmethod
    def _signer_fields(record: EvidenceRecord) -> tuple[SignerKeyRef, str, str, str, datetime]:
        if type(record) is DispatchReceipt:
            values = (record.signer_key_id, record.key_version, record.signer_role,
                      record.writer_service_id, record.writer_host_id, record.started_at)
        elif type(record) in (OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3):
            values = (record.signer_key_id, record.key_version, record.role,
                      record.verifier_service_id, record.verifier_host_id, record.observed_at)
        elif type(record) is CompletionProof:
            values = (record.signer_key_id, record.key_version, record.signer_role,
                      record.source_service_id, record.source_host_id, record.observed_at)
        elif type(record) is PostCompletionChallenge:
            values = (record.signer_key_id, record.key_version, record.signer_role,
                      record.issuer_service_id, record.issuer_host_id, record.issued_at)
        elif type(record) is PostCompletionReadAttestation:
            values = (record.signer_key_id, record.key_version, record.signer_role,
                      record.attestor_service_id, record.attestor_host_id, record.completed_at)
        else:
            raise ValueError("EVIDENCE_TYPE_UNSUPPORTED")
        key_id, key_version, role, service_id, host_id, signed_time = values
        signed_at = datetime.strptime(signed_time, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc,
        )
        return SignerKeyRef(key_id, key_version), role, service_id, host_id, signed_at

    @staticmethod
    def _process_ids(record: EvidenceRecord) -> tuple[str, ...]:
        if type(record) is DispatchReceipt:
            values = (record.writer_process_instance_id,)
        elif type(record) is CompletionProof:
            values = (record.writer_process_instance_id, record.source_process_instance_id)
        elif type(record) is PostCompletionReadAttestation:
            values = (record.process_instance_id,)
        else:
            values = ()
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _oracle_fields(record: EvidenceRecord) -> tuple[str | None, str | None]:
        if type(record) in (OutcomeEvidenceV2, OutcomeEvidenceV3):
            return record.oracle_id, record.oracle_version
        if type(record) is OutcomeEvidence:
            return None, None
        return None, None

    def _check_snapshot(self, snapshot: EvidenceTrustSnapshot, request: TrustSnapshotRequest) -> None:
        if not is_canonical_positive_trust_revision(snapshot.revision):
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INVALID")
        if (len(snapshot.outcome_version_floors) > 1
                or any(floor.scope != request.scope
                       or floor.operation_kind != request.operation_kind
                       for floor in snapshot.outcome_version_floors)):
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INVALID")
        if (len(snapshot.oracle_artifacts) > 16
                or any(artifact.scope != request.scope
                       or artifact.operation_kind != request.operation_kind
                       for artifact in snapshot.oracle_artifacts)
                or (request.oracle_id is not None and any(
                    (artifact.oracle_id, artifact.oracle_version)
                    != (request.oracle_id, request.oracle_version)
                    for artifact in snapshot.oracle_artifacts
                ))
                or (request.oracle_id is None
                    and not request.include_operation_oracle_policy
                    and snapshot.oracle_artifacts)):
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INVALID")
        for signer_key in request.signer_keys:
            if snapshot.signer(signer_key) is None:
                raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INCOMPLETE")
        for process_id in request.process_instance_ids:
            binding = snapshot.process(process_id)
            if binding is None or snapshot.signer(binding.supervisor_key) is None:
                raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INCOMPLETE")
        if request.oracle_id is not None and snapshot.oracle(
                request.scope, request.operation_kind, request.oracle_id,
                request.oracle_version or "") is None:
            raise ProductionEvidenceVerificationError("EVIDENCE_TRUST_SNAPSHOT_INCOMPLETE")

    @staticmethod
    def _check_signer(signer: TrustedSigner, key: SignerKeyRef, role: str,
                      service_id: str, host_id: str, scope: EvidenceScope,
                      signed_at: datetime, validation_time: datetime) -> None:
        if (signer.key != key or signer.signer_role != role or signer.service_id != service_id
                or signer.host_id != host_id or scope not in signer.allowed_scopes):
            raise ProductionEvidenceVerificationError("EVIDENCE_SIGNER_IDENTITY_MISMATCH")
        if signed_at > validation_time:
            raise ProductionEvidenceVerificationError("EVIDENCE_SIGNED_TIME_FUTURE")
        if (signer.revoked_at is not None and validation_time >= signer.revoked_at
                or not (signer.valid_from <= signed_at < signer.valid_until)
                or not (signer.valid_from <= validation_time < signer.valid_until)):
            raise ProductionEvidenceVerificationError("EVIDENCE_SIGNER_NOT_CURRENTLY_AUTHORIZED")

    @staticmethod
    def _check_record_signature(record: EvidenceRecord, signer: TrustedSigner) -> None:
        if record.calculated_digest() != getattr(record, record.DIGEST_FIELD):
            raise ProductionEvidenceVerificationError("EVIDENCE_DIGEST_INVALID")
        try:
            signature = bytes.fromhex(record.signature)
        except (TypeError, ValueError):
            raise ProductionEvidenceVerificationError("EVIDENCE_SIGNATURE_INVALID") from None
        if not verify_ed25519(
                public_key=signer.public_key, message=record.signature_preimage(),
                signature=signature):
            raise ProductionEvidenceVerificationError("EVIDENCE_SIGNATURE_INVALID")

    @staticmethod
    def _check_policy(record: EvidenceRecord, snapshot: EvidenceTrustSnapshot,
                      scope: EvidenceScope) -> None:
        if type(record) in (OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3):
            floor = snapshot.minimum_outcome_version(scope, record.operation_kind)
            if floor is None:
                raise ProductionEvidenceVerificationError("EVIDENCE_VERSION_POLICY_UNAVAILABLE")
            version = int(record.evidence_version)
            # A scoped oracle is the canonical S12 v2 contract pin. Keep the explicit
            # version floor as an independently managed policy, but never let a stale or
            # inconsistent floor re-enable legacy v1 for an operation with a v2 oracle.
            pinned_to_v2_oracle = any(
                artifact.scope == scope and artifact.operation_kind == record.operation_kind
                for artifact in snapshot.oracle_artifacts
            )
            required_version = max(floor, 2 if pinned_to_v2_oracle else 1)
            if version < required_version:
                raise ProductionEvidenceVerificationError("OUTCOME_VERSION_DOWNGRADE")
            if type(record) in (OutcomeEvidenceV2, OutcomeEvidenceV3):
                artifact = snapshot.oracle(
                    scope, record.operation_kind, record.oracle_id, record.oracle_version,
                )
                if (artifact is None
                        or artifact.document_shape_revision != record.document_shape_revision
                        or artifact.configuration_fingerprint != record.configuration_fingerprint
                        or artifact.oracle_digest != record.oracle_digest
                        or artifact.expected_effect_schema_version != record.expected_effect_schema_version):
                    raise ProductionEvidenceVerificationError("EVIDENCE_ORACLE_ARTIFACT_UNTRUSTED")

    def _check_process_bindings(self, record: EvidenceRecord, attempt: DispatchAttempt,
                                snapshot: EvidenceTrustSnapshot, scope: EvidenceScope,
                                validation_time: datetime) -> None:
        if type(record) is DispatchReceipt:
            self._verify_process(
                snapshot, record.writer_process_instance_id, record.writer_service_id,
                record.writer_host_id, scope, self._parse_time(record.started_at), validation_time,
            )
        elif type(record) is CompletionProof:
            self._verify_process(
                snapshot, record.writer_process_instance_id, attempt.writer_service_id,
                attempt.writer_host_id, scope, self._parse_time(record.observed_at), validation_time,
            )
            if record.proof_class == "INDEPENDENT_SESSION_AND_PROCESS_CLOSED":
                self._verify_process(
                    snapshot, record.source_process_instance_id, record.source_service_id,
                    record.source_host_id, scope, self._parse_time(record.observed_at), validation_time,
                )
        elif type(record) is PostCompletionReadAttestation:
            self._verify_process(
                snapshot, record.process_instance_id, record.attestor_service_id,
                record.attestor_host_id, scope, self._parse_time(record.completed_at), validation_time,
            )

    def _verify_process(self, snapshot: EvidenceTrustSnapshot, process_id: str,
                        service_id: str, host_id: str, scope: EvidenceScope,
                        event_at: datetime, validation_time: datetime) -> None:
        process = snapshot.process(process_id)
        if (type(process) is not TrustedProcessBinding or process.service_id != service_id
                or process.host_id != host_id or process.process_created_at > event_at):
            raise ProductionEvidenceVerificationError("EVIDENCE_PROCESS_BINDING_UNTRUSTED")
        supervisor = snapshot.signer(process.supervisor_key)
        if (supervisor is None or supervisor.signer_role != "completion_supervisor"
                or supervisor.host_id != host_id or supervisor.service_id == service_id
                or scope not in supervisor.allowed_scopes):
            raise ProductionEvidenceVerificationError("EVIDENCE_PROCESS_SUPERVISOR_UNTRUSTED")
        self._check_signer(
            supervisor, process.supervisor_key, "completion_supervisor", supervisor.service_id,
            host_id, scope, process.process_created_at, validation_time,
        )
        preimage = _PROCESS_ATTESTATION_PREFIX + canonical_json_bytes({
            "attestation_version": "1",
            "process_instance_id": process.process_instance_id,
            "host_boot_id": process.host_boot_id,
            "service_id": process.service_id,
            "host_id": process.host_id,
            "os_pid": process.os_pid,
            "process_created_at": process.process_created_at.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "supervisor_key_id": process.supervisor_key.key_id,
            "supervisor_key_version": process.supervisor_key.key_version,
        })
        if not verify_ed25519(
                public_key=supervisor.public_key, message=preimage,
                signature=process.signature):
            raise ProductionEvidenceVerificationError("EVIDENCE_PROCESS_ATTESTATION_INVALID")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


__all__ = [
    "EvidenceRecord", "ProductionEvidenceVerificationError", "ProductionEvidenceVerifier",
    "VerifiedEvidenceRecord",
]
