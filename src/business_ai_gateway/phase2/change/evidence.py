"""Closed v1 S12 evidence envelopes for local synthetic contract fixtures.

These value objects validate and serialize evidence; they do not establish a
trusted identity, authorize a write, or connect to a database/1C. Their Ed25519
helpers use the repository's explicitly test-lane, non-production implementation.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Final

from .. import ed25519

__all__ = [
    "DispatchReceipt", "OutcomeEvidence", "CompletionProof", "canonical_json_bytes",
    "DispatchAttempt", "record_digest", "verify_record_signature", "sign_record_fixture", "seal_record_fixture",
]

_HEX64: Final = re.compile(r"[0-9a-f]{64}\Z")
_HEX128: Final = re.compile(r"[0-9a-f]{128}\Z")
_UTC_MICROS: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z")
_UUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_OPERATIONS: Final = frozenset(("CREATE_DRAFT", "POST", "UNPOST"))
_WRITE_STAGES: Final = frozenset(("NOT_INVOKED", "INVOKED"))
_RESULT_CLASSES: Final = frozenset((
    "PRE_WRITE_NO_EFFECT", "CALL_RETURNED_SUCCESS", "CALL_RETURNED_ERROR", "POST_START_UNKNOWN",
    "RECEIPT_PERSISTENCE_UNKNOWN",
))
_COMPLETION_CLASSES: Final = frozenset(("WRITER_CALL_RETURNED", "INDEPENDENT_SESSION_AND_PROCESS_CLOSED"))
_SIGNER_ROLES: Final = frozenset(("writer_receipt", "verification_worker", "completion_supervisor"))
_DISPATCH_PREFIX: Final = b"ERP_MCP_R2:S12:DISPATCH-RECEIPT:v1\n"
_OUTCOME_PREFIX: Final = b"ERP_MCP_R2:S12:OUTCOME-EVIDENCE:v1\n"
_COMPLETION_PREFIX: Final = b"ERP_MCP_R2:S12:COMPLETION-PROOF:v1\n"


def _text(value: object, field: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise ValueError(f"{field.upper()}_INVALID")


def _timestamp(value: object, field: str) -> None:
    if type(value) is not str or _UTC_MICROS.fullmatch(value) is None:
        raise ValueError(f"{field.upper()}_INVALID")
    # strptime rejects impossible dates and the leap-second form.
    from datetime import datetime
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValueError(f"{field.upper()}_INVALID") from exc


def _freeze(value: object) -> object:
    if type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("INVALID_UNICODE") from exc
        return value
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is list or type(value) is tuple:
        return tuple(_freeze(v) for v in value)
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise ValueError("FIELD_NAME_INVALID")
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    # Floats, Decimal objects, bytes, enums and custom values are deliberately
    # rejected: envelopes have one JSON representation only.
    raise ValueError("NON_CANONICAL_VALUE")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if type(value) is tuple:
        return [_thaw(v) for v in value]
    return value


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    """Canonical S12 UTF-8 JSON: sorted keys, compact, ASCII escaped, no floats."""
    frozen = _freeze(value)
    encoded = _thaw(frozen)
    return json.dumps(encoded, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("JSON_CONSTANT_INVALID")


def _movement_bytes(movement: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(movement)


def _movement_summary(movements: tuple[Mapping[str, object], ...]) -> tuple[dict[str, int], dict[str, str], str]:
    by_register: dict[str, list[bytes]] = {}
    all_bytes: list[bytes] = []
    for movement in movements:
        name = str(movement["register"])
        raw = _movement_bytes(movement)
        by_register.setdefault(name, []).append(raw)
        all_bytes.append(raw)
    counts = {name: len(items) for name, items in sorted(by_register.items())}
    digests = {
        name: hashlib.sha256(b"[" + b",".join(sorted(items)) + b"]").hexdigest()
        for name, items in sorted(by_register.items())
    }
    total = hashlib.sha256(b"[" + b",".join(sorted(all_bytes)) + b"]").hexdigest()
    return counts, digests, total


@dataclass(frozen=True, slots=True)
class DispatchAttempt:
    """Authenticated dispatch-intent/CAS binding used before a receipt is durable.

    The enclosing service must obtain this value from its trusted attempt record;
    a caller-provided mapping is shape-validated but not authenticated here.
    """

    tenant_id: str
    company_id: str
    organization_ref: str
    base_fingerprint: str
    change_id: str
    claim_generation: int
    dispatch_generation: int
    dispatch_cas_id: str
    call_id: str
    operation_kind: str
    approval_digest: str
    auth_epoch: int
    permit_id: str
    permit_digest: str
    expected_target_ref: str | None
    expected_pre_version: str | None
    writer_service_id: str
    writer_host_id: str
    writer_process_instance_id: str
    onec_session_instance_id: str | None

    FIELDS: ClassVar[frozenset[str]] = frozenset((
        "tenant_id", "company_id", "organization_ref", "base_fingerprint", "change_id", "claim_generation",
        "dispatch_generation", "dispatch_cas_id", "call_id", "operation_kind", "approval_digest",
        "auth_epoch", "permit_id", "permit_digest",
        "expected_target_ref", "expected_pre_version", "writer_service_id", "writer_host_id",
        "writer_process_instance_id", "onec_session_instance_id",
    ))

    def __post_init__(self) -> None:
        for name in self.FIELDS - {"claim_generation", "dispatch_generation", "auth_epoch", "operation_kind",
                                   "approval_digest", "permit_digest",
                                   "expected_target_ref", "expected_pre_version", "onec_session_instance_id"}:
            _text(getattr(self, name), name)
        if type(self.claim_generation) is not int or self.claim_generation < 1:
            raise ValueError("CLAIM_GENERATION_INVALID")
        if type(self.dispatch_generation) is not int or self.dispatch_generation < 1:
            raise ValueError("DISPATCH_GENERATION_INVALID")
        if type(self.auth_epoch) is not int or self.auth_epoch < 1:
            raise ValueError("AUTH_EPOCH_INVALID")
        if self.operation_kind not in _OPERATIONS:
            raise ValueError("OPERATION_KIND_INVALID")
        if type(self.approval_digest) is not str or _HEX64.fullmatch(self.approval_digest) is None:
            raise ValueError("APPROVAL_DIGEST_INVALID")
        if type(self.permit_digest) is not str or _HEX64.fullmatch(self.permit_digest) is None:
            raise ValueError("PERMIT_DIGEST_INVALID")
        if _UUID.fullmatch(self.permit_id) is None:
            raise ValueError("PERMIT_ID_INVALID")
        _text(self.expected_target_ref, "expected_target_ref", nullable=True)
        _text(self.expected_pre_version, "expected_pre_version", nullable=True)
        if self.operation_kind == "CREATE_DRAFT":
            if self.expected_target_ref is not None or self.expected_pre_version is not None:
                raise ValueError("CREATE_DRAFT_PREIMAGE_INVALID")
        elif self.expected_target_ref is None or self.expected_pre_version is None:
            raise ValueError("OPERATION_PREIMAGE_REQUIRED")
        if _UUID.fullmatch(self.dispatch_cas_id) is None or _UUID.fullmatch(self.call_id) is None \
                or _UUID.fullmatch(self.change_id) is None or _UUID.fullmatch(self.writer_process_instance_id) is None:
            raise ValueError("DISPATCH_ATTEMPT_ID_INVALID")
        _text(self.onec_session_instance_id, "onec_session_instance_id", nullable=True)

    @classmethod
    def from_mapping(cls, fields: Mapping[str, object]) -> DispatchAttempt:
        if not isinstance(fields, Mapping) or set(fields) != cls.FIELDS:
            raise ValueError("DISPATCH_ATTEMPT_SCHEMA_INVALID")
        return cls(**dict(fields))  # type: ignore[arg-type]

    @classmethod
    def from_receipt(cls, receipt: DispatchReceipt) -> DispatchAttempt:
        return cls(
            tenant_id=receipt.tenant_id, company_id=receipt.company_id,
            organization_ref=receipt.organization_ref, base_fingerprint=receipt.base_fingerprint,
            change_id=receipt.change_id, claim_generation=receipt.claim_generation,
            dispatch_generation=receipt.dispatch_generation, dispatch_cas_id=receipt.dispatch_cas_id,
            call_id=receipt.call_id, operation_kind=receipt.operation_kind, approval_digest=receipt.approval_digest,
            auth_epoch=receipt.auth_epoch, permit_id=receipt.permit_id, permit_digest=receipt.permit_digest,
            expected_target_ref=receipt.expected_target_ref, expected_pre_version=receipt.expected_pre_version,
            writer_service_id=receipt.writer_service_id, writer_host_id=receipt.writer_host_id,
            writer_process_instance_id=receipt.writer_process_instance_id,
            onec_session_instance_id=receipt.onec_session_instance_id,
        )


def _attempt(value: DispatchAttempt | Mapping[str, object]) -> DispatchAttempt:
    return value if isinstance(value, DispatchAttempt) else DispatchAttempt.from_mapping(value)


def _assert_receipt_attempt(receipt: DispatchReceipt, attempt: DispatchAttempt) -> None:
    receipt_attempt = DispatchAttempt.from_receipt(receipt)
    if receipt_attempt != attempt:
        raise ValueError("RECEIPT_ATTEMPT_BINDING_INVALID")


class _Envelope:
    __slots__ = ("_fields",)
    PREFIX: ClassVar[bytes]
    SCHEMA: ClassVar[frozenset[str]]
    DIGEST_FIELD: ClassVar[str]

    def __init__(self, fields: Mapping[str, object]) -> None:
        if not isinstance(fields, Mapping) or any(type(k) is not str for k in fields):
            raise ValueError("SCHEMA_INVALID")
        supplied = set(fields)
        if supplied != self.SCHEMA:
            raise ValueError("SCHEMA_INVALID")
        frozen = {name: _freeze(value) for name, value in fields.items()}
        self._validate(frozen)
        object.__setattr__(self, "_fields", MappingProxyType(frozen))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("IMMUTABLE_RECORD")

    def __getattr__(self, name: str) -> object:
        try:
            return self._fields[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @classmethod
    def from_mapping(cls, fields: Mapping[str, object]):
        return cls(fields)

    @classmethod
    def from_json(cls, data: bytes):
        """Parse only byte-for-byte canonical UTF-8 JSON with no duplicate keys."""
        if type(data) is not bytes:
            raise ValueError("JSON_BYTES_REQUIRED")
        try:
            text = data.decode("utf-8", errors="strict")
            parsed = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("JSON_INVALID") from exc
        if not isinstance(parsed, dict) or canonical_json_bytes(parsed) != data:
            raise ValueError("JSON_NON_CANONICAL")
        return cls(parsed)

    def to_dict(self) -> dict[str, object]:
        return {k: _thaw(v) for k, v in self._fields.items()}

    def digest_preimage(self) -> bytes:
        body = {k: v for k, v in self._fields.items() if k not in (self.DIGEST_FIELD, "signature")}
        return self.PREFIX + canonical_json_bytes(body)

    def signature_preimage(self) -> bytes:
        body = {k: v for k, v in self._fields.items() if k != "signature"}
        return self.PREFIX + canonical_json_bytes(body)

    def calculated_digest(self) -> str:
        return hashlib.sha256(self.digest_preimage()).hexdigest()

    def _validate(self, fields: Mapping[str, object]) -> None:
        raise NotImplementedError


_DISPATCH_FIELDS: Final = frozenset((
    "receipt_version", "tenant_id", "company_id", "organization_ref", "base_fingerprint", "target_class",
    "expected_target_ref", "expected_pre_version", "change_id", "request_id", "claim_generation",
    "approval_digest_version", "approval_digest", "auth_epoch", "permit_id", "permit_digest", "receipt_id",
    "call_id", "dispatch_generation", "dispatch_cas_id", "writer_service_id", "writer_host_id",
    "writer_process_instance_id", "onec_session_id", "onec_session_instance_id", "operation_kind", "started_at",
    "write_invocation_stage", "call_returned", "returned_at", "result_class", "returned_target_ref",
    "returned_version", "no_effect_evidence_digest", "error_family", "mapping_version",
    "configuration_fingerprint", "approved_payload_digest", "mapped_property_manifest_sha256",
    "COM_operation_manifest_sha256", "signer_key_id", "key_version", "signer_role", "algorithm",
    "signed_payload_digest", "signature",
))


class DispatchReceipt(_Envelope):
    """Signed writer-side record of a bounded dispatch attempt."""
    PREFIX = _DISPATCH_PREFIX
    SCHEMA = _DISPATCH_FIELDS
    DIGEST_FIELD = "signed_payload_digest"

    def validate_attempt_binding(self, attempt: DispatchAttempt | Mapping[str, object]) -> None:
        """Bind this signed receipt to the immutable intent/CAS attempt."""
        _assert_receipt_attempt(self, _attempt(attempt))

    def _validate(self, f: Mapping[str, object]) -> None:
        if f["receipt_version"] != "1" or f["signer_role"] != "writer_receipt" or f["algorithm"] != "Ed25519":
            raise ValueError("DISPATCH_METADATA_INVALID")
        if f["operation_kind"] not in _OPERATIONS:
            raise ValueError("OPERATION_KIND_INVALID")
        if f["write_invocation_stage"] not in _WRITE_STAGES or f["result_class"] not in _RESULT_CLASSES:
            raise ValueError("DISPATCH_RESULT_ENUM_INVALID")
        for name in ("started_at",):
            _timestamp(f[name], name)
        for name in ("returned_at",):
            if f[name] is not None:
                _timestamp(f[name], name)
        nullable = {"expected_target_ref", "expected_pre_version", "onec_session_id", "onec_session_instance_id",
                    "returned_at", "returned_target_ref", "returned_version", "no_effect_evidence_digest", "error_family"}
        for name in self.SCHEMA - {"receipt_version", "claim_generation", "auth_epoch", "dispatch_generation",
                                   "operation_kind", "call_returned", "started_at", "returned_at",
                                   "signer_role", "algorithm", "signed_payload_digest", "signature"}:
            _text(f[name], name, nullable=name in nullable)
        for name in ("approval_digest", "permit_digest", "approved_payload_digest", "configuration_fingerprint",
                     "mapped_property_manifest_sha256", "COM_operation_manifest_sha256", "signed_payload_digest"):
            if type(f[name]) is not str or _HEX64.fullmatch(f[name]) is None:
                raise ValueError(f"{name.upper()}_INVALID")
        for name in ("claim_generation", "auth_epoch", "dispatch_generation"):
            if type(f[name]) is not int or f[name] < 1:
                raise ValueError(f"{name.upper()}_INVALID")
        if type(f["call_returned"]) is not bool:
            raise ValueError("CALL_RETURNED_INVALID")
        for name in ("receipt_id", "change_id", "request_id", "call_id", "dispatch_cas_id", "writer_process_instance_id"):
            if _UUID.fullmatch(str(f[name])) is None:
                raise ValueError(f"{name.upper()}_INVALID")
        if f["operation_kind"] == "CREATE_DRAFT" and (f["expected_target_ref"] is not None or f["expected_pre_version"] is not None):
            raise ValueError("CREATE_DRAFT_PREIMAGE_INVALID")
        if f["operation_kind"] in ("POST", "UNPOST") and (
            f["expected_target_ref"] is None or f["expected_pre_version"] is None
        ):
            raise ValueError("OPERATION_PREIMAGE_REQUIRED")
        if (f["onec_session_id"] is None) != (f["onec_session_instance_id"] is None):
            raise ValueError("SESSION_BINDING_INCOMPLETE")
        if f["write_invocation_stage"] == "NOT_INVOKED":
            if f["result_class"] != "PRE_WRITE_NO_EFFECT" or f["call_returned"] or f["returned_at"] is not None \
                    or f["returned_target_ref"] is not None or f["returned_version"] is not None or f["no_effect_evidence_digest"] is None:
                raise ValueError("PRE_WRITE_PROOF_INVALID")
        else:
            if f["result_class"] == "PRE_WRITE_NO_EFFECT" or f["no_effect_evidence_digest"] is not None:
                raise ValueError("NO_EFFECT_EVIDENCE_UNEXPECTED")
            if f["result_class"] in ("CALL_RETURNED_SUCCESS", "CALL_RETURNED_ERROR", "RECEIPT_PERSISTENCE_UNKNOWN"):
                if not f["call_returned"] or f["returned_at"] is None:
                    raise ValueError("RETURN_BOUNDARY_REQUIRED")
            elif f["result_class"] == "POST_START_UNKNOWN":
                if f["call_returned"] or f["returned_at"] is not None:
                    raise ValueError("UNKNOWN_RETURN_BOUNDARY_INVALID")
        if f["call_returned"] != (f["returned_at"] is not None):
            raise ValueError("RETURN_BOUNDARY_INVALID")
        if f["operation_kind"] in ("POST", "UNPOST") and f["returned_target_ref"] is not None \
                and f["returned_target_ref"] != f["expected_target_ref"]:
            raise ValueError("RETURNED_TARGET_MISMATCH")
        if f["result_class"] == "CALL_RETURNED_SUCCESS":
            if f["returned_target_ref"] is None or f["returned_version"] is None:
                raise ValueError("SUCCESS_RETURN_TARGET_AND_VERSION_REQUIRED")
            if f["operation_kind"] == "CREATE_DRAFT" and not f["returned_target_ref"]:
                raise ValueError("CREATE_DRAFT_RETURN_TARGET_REQUIRED")
            if f["operation_kind"] in ("POST", "UNPOST") and f["returned_target_ref"] != f["expected_target_ref"]:
                raise ValueError("RETURNED_TARGET_MISMATCH")
            _text(f["returned_version"], "returned_version")
        if type(f["signature"]) is not str or (f["signature"] != "" and _HEX128.fullmatch(f["signature"]) is None):
            raise ValueError("SIGNATURE_INVALID")
        if f["no_effect_evidence_digest"] is not None and (
            type(f["no_effect_evidence_digest"]) is not str or _HEX64.fullmatch(f["no_effect_evidence_digest"]) is None
        ):
            raise ValueError("NO_EFFECT_EVIDENCE_DIGEST_INVALID")


_OUTCOME_FIELDS: Final = frozenset((
    "evidence_version", "tenant_id", "company_id", "organization_ref", "base_fingerprint", "change_id",
    "claim_generation", "call_id", "dispatch_receipt_id", "approval_digest", "verifier_service_id",
    "verifier_host_id", "signer_key_id", "key_version", "algorithm", "role", "operation_kind", "observed_at",
    "read_session_id", "target_ref", "pre_version", "observed_version", "document_posting_state",
    "field_snapshot_digest", "lines_digest", "movement_multiset", "registrar", "register_catalogue_version",
    "movement_count_by_register", "movement_digest_by_register", "movement_multiset_digest",
    "expected_effect_digest", "observed_effect_digest", "fields_match", "movements_match", "version_relation",
    "reader_health", "observation_complete", "effect_presence", "effect_identity", "completion_proof_class",
    "attribution_result", "attribution_evidence_ref", "uncertainties", "canonical_evidence_digest", "signature",
))


class OutcomeEvidence(_Envelope):
    """Signed independent read-back; it is deliberately separate from writer evidence."""
    PREFIX = _OUTCOME_PREFIX
    SCHEMA = _OUTCOME_FIELDS
    DIGEST_FIELD = "canonical_evidence_digest"

    def _validate(self, f: Mapping[str, object]) -> None:
        if f["evidence_version"] != "1" or f["role"] != "verification_worker" or f["algorithm"] != "Ed25519":
            raise ValueError("OUTCOME_METADATA_INVALID")
        if f["operation_kind"] not in _OPERATIONS:
            raise ValueError("OPERATION_KIND_INVALID")
        _timestamp(f["observed_at"], "observed_at")
        for name in ("tenant_id", "company_id", "organization_ref", "base_fingerprint", "change_id", "call_id",
                     "approval_digest", "verifier_service_id", "verifier_host_id", "signer_key_id", "key_version",
                     "read_session_id", "target_ref", "observed_version", "document_posting_state", "registrar",
                     "register_catalogue_version", "version_relation", "reader_health", "effect_presence",
                     "effect_identity", "attribution_result", "canonical_evidence_digest"):
            _text(f[name], name)
        for name in ("field_snapshot_digest", "lines_digest", "movement_multiset_digest", "expected_effect_digest",
                     "observed_effect_digest", "canonical_evidence_digest"):
            if type(f[name]) is not str or _HEX64.fullmatch(f[name]) is None:
                raise ValueError(f"{name.upper()}_INVALID")
        if f["operation_kind"] == "CREATE_DRAFT":
            if f["pre_version"] is not None:
                raise ValueError("CREATE_DRAFT_PREVERSION_INVALID")
        else:
            _text(f["pre_version"], "pre_version")
        for name in ("dispatch_receipt_id", "completion_proof_class", "attribution_evidence_ref"):
            _text(f[name], name, nullable=True)
        for name in ("change_id", "call_id"):
            if _UUID.fullmatch(f[name]) is None:
                raise ValueError(f"{name.upper()}_INVALID")
        if f["dispatch_receipt_id"] is not None and _UUID.fullmatch(f["dispatch_receipt_id"]) is None:
            raise ValueError("DISPATCH_RECEIPT_ID_INVALID")
        for name in ("claim_generation",):
            if type(f[name]) is not int or f[name] < 1:
                raise ValueError(f"{name.upper()}_INVALID")
        if type(f["fields_match"]) is not bool or type(f["movements_match"]) is not bool or type(f["observation_complete"]) is not bool:
            raise ValueError("OUTCOME_BOOLEAN_INVALID")
        if type(f["movement_multiset"]) is not tuple:
            raise ValueError("MOVEMENT_MULTISET_INVALID")
        normalized_movements: list[Mapping[str, object]] = []
        for movement in f["movement_multiset"]:
            if not isinstance(movement, Mapping) or set(movement) != {"register", "registrar", "movement_digest"}:
                raise ValueError("MOVEMENT_ITEM_SCHEMA_INVALID")
            _text(movement["register"], "movement.register")
            _text(movement["registrar"], "movement.registrar")
            if movement["registrar"] != f["registrar"]:
                raise ValueError("MOVEMENT_REGISTRAR_MISMATCH")
            if type(movement["movement_digest"]) is not str or _HEX64.fullmatch(movement["movement_digest"]) is None:
                raise ValueError("MOVEMENT_CONTENT_DIGEST_INVALID")
            normalized_movements.append(movement)
        counts = f["movement_count_by_register"]
        digests = f["movement_digest_by_register"]
        if not isinstance(counts, Mapping) or any(type(v) is not int or v < 0 for v in counts.values()):
            raise ValueError("MOVEMENT_COUNTS_INVALID")
        if not isinstance(digests, Mapping) or any(type(v) is not str or _HEX64.fullmatch(v) is None for v in digests.values()):
            raise ValueError("MOVEMENT_DIGESTS_INVALID")
        expected_counts, expected_digests, expected_total = _movement_summary(tuple(normalized_movements))
        if dict(counts) != expected_counts or dict(digests) != expected_digests or f["movement_multiset_digest"] != expected_total:
            raise ValueError("MOVEMENT_SUMMARY_MISMATCH")
        if type(f["uncertainties"]) is not tuple or any(type(v) is not str or not v for v in f["uncertainties"]):
            raise ValueError("UNCERTAINTIES_INVALID")
        if type(f["signature"]) is not str or (f["signature"] != "" and _HEX128.fullmatch(f["signature"]) is None):
            raise ValueError("SIGNATURE_INVALID")

    def validate_attempt_binding(
        self,
        attempt: DispatchAttempt | Mapping[str, object],
        receipt: DispatchReceipt | None = None,
    ) -> None:
        """Bind outcome to the intent/CAS even when no durable receipt exists.

        Receipt absence is permitted only when the evidence's nullable receipt
        reference is null; this remains unresolved evidence and cannot by itself
        authorize APPLIED or VERIFIED.
        """
        bound = _attempt(attempt)
        if receipt is None:
            if self.dispatch_receipt_id is not None:
                raise ValueError("OUTCOME_RECEIPT_MISSING")
        else:
            _assert_receipt_attempt(receipt, bound)
            if self.dispatch_receipt_id != receipt.receipt_id:
                raise ValueError("OUTCOME_RECEIPT_BINDING_INVALID")
        pairs = {
            "tenant_id": "tenant_id", "company_id": "company_id", "organization_ref": "organization_ref",
            "base_fingerprint": "base_fingerprint", "change_id": "change_id", "claim_generation": "claim_generation",
            "call_id": "call_id", "approval_digest": "approval_digest", "operation_kind": "operation_kind",
        }
        if any(getattr(self, name) != getattr(bound, target) for name, target in pairs.items()):
            raise ValueError("OUTCOME_DISPATCH_BINDING_INVALID")
        if self.operation_kind == "CREATE_DRAFT":
            if bound.expected_target_ref is not None or bound.expected_pre_version is not None or self.pre_version is not None:
                raise ValueError("CREATE_DRAFT_BINDING_INVALID")
        elif self.target_ref != bound.expected_target_ref or self.pre_version != bound.expected_pre_version:
            raise ValueError("OUTCOME_PREIMAGE_BINDING_INVALID")

    def validate_dispatch_binding(self, receipt: DispatchReceipt) -> None:
        """Compatibility convenience for a receipt-backed observation."""
        self.validate_attempt_binding(DispatchAttempt.from_receipt(receipt), receipt)


_COMPLETION_FIELDS: Final = frozenset((
    "proof_version", "completion_proof_id", "tenant_id", "company_id", "organization_ref", "base_fingerprint",
    "change_id", "claim_generation", "dispatch_generation", "dispatch_cas_id", "call_id", "operation_kind",
    "writer_process_instance_id", "onec_session_instance_id", "proof_class", "source_service_id", "source_host_id",
    "source_process_instance_id", "source_session_instance_id", "observed_session_instance_id", "evidence_ref",
    "evidence_digest", "observed_at", "signer_key_id", "key_version", "signer_role", "algorithm",
    "canonical_evidence_digest", "signature",
))


class CompletionProof(_Envelope):
    """Signed proof of a specific writer return or independent process/session closure."""
    PREFIX = _COMPLETION_PREFIX
    SCHEMA = _COMPLETION_FIELDS
    DIGEST_FIELD = "canonical_evidence_digest"

    def _validate(self, f: Mapping[str, object]) -> None:
        if f["proof_version"] != "1" or f["algorithm"] != "Ed25519":
            raise ValueError("COMPLETION_METADATA_INVALID")
        if f["operation_kind"] not in _OPERATIONS:
            raise ValueError("OPERATION_KIND_INVALID")
        _timestamp(f["observed_at"], "observed_at")
        for name in ("onec_session_instance_id", "source_session_instance_id", "observed_session_instance_id"):
            _text(f[name], name, nullable=True)
        for name in ("completion_proof_id", "tenant_id", "company_id", "organization_ref", "base_fingerprint",
                     "change_id", "dispatch_cas_id", "call_id", "writer_process_instance_id", "proof_class",
                     "source_service_id", "source_host_id", "source_process_instance_id", "evidence_ref",
                     "signer_key_id", "key_version", "canonical_evidence_digest"):
            _text(f[name], name)
        for name in ("evidence_digest", "canonical_evidence_digest"):
            if type(f[name]) is not str or _HEX64.fullmatch(f[name]) is None:
                raise ValueError(f"{name.upper()}_INVALID")
        for name in ("claim_generation", "dispatch_generation"):
            if type(f[name]) is not int or f[name] < 1:
                raise ValueError(f"{name.upper()}_INVALID")
        for name in ("completion_proof_id", "change_id", "dispatch_cas_id", "call_id", "writer_process_instance_id",
                     "source_process_instance_id"):
            if _UUID.fullmatch(f[name]) is None:
                raise ValueError(f"{name.upper()}_INVALID")
        if f["proof_class"] not in _COMPLETION_CLASSES or f["signer_role"] not in _SIGNER_ROLES:
            raise ValueError("COMPLETION_ROLE_ENUM_INVALID")
        if f["proof_class"] == "WRITER_CALL_RETURNED":
            if f["signer_role"] != "writer_receipt" or f["source_process_instance_id"] != f["writer_process_instance_id"]:
                raise ValueError("WRITER_COMPLETION_BINDING_INVALID")
            if f["observed_session_instance_id"] != f["onec_session_instance_id"]:
                raise ValueError("WRITER_SESSION_BINDING_INVALID")
        elif f["proof_class"] == "INDEPENDENT_SESSION_AND_PROCESS_CLOSED":
            if f["signer_role"] != "completion_supervisor" or f["source_process_instance_id"] == f["writer_process_instance_id"]:
                raise ValueError("SUPERVISOR_COMPLETION_BINDING_INVALID")
            if f["observed_session_instance_id"] != f["onec_session_instance_id"]:
                raise ValueError("SUPERVISOR_SESSION_BINDING_INVALID")
        else:
            raise ValueError("PROOF_CLASS_INVALID")
        if type(f["signature"]) is not str or (f["signature"] != "" and _HEX128.fullmatch(f["signature"]) is None):
            raise ValueError("SIGNATURE_INVALID")

    def validate_attempt_binding(
        self,
        attempt: DispatchAttempt | Mapping[str, object],
        receipt: DispatchReceipt | None = None,
    ) -> None:
        """Bind completion to the exact dispatch attempt, receipt optional."""
        bound = _attempt(attempt)
        if receipt is not None:
            _assert_receipt_attempt(receipt, bound)
        pairs = {
            "tenant_id": "tenant_id", "company_id": "company_id", "organization_ref": "organization_ref",
            "base_fingerprint": "base_fingerprint", "change_id": "change_id", "claim_generation": "claim_generation",
            "dispatch_generation": "dispatch_generation", "dispatch_cas_id": "dispatch_cas_id", "call_id": "call_id",
            "operation_kind": "operation_kind", "writer_process_instance_id": "writer_process_instance_id",
        }
        if any(getattr(self, name) != getattr(bound, target) for name, target in pairs.items()):
            raise ValueError("COMPLETION_DISPATCH_BINDING_INVALID")
        if self.onec_session_instance_id != bound.onec_session_instance_id:
            raise ValueError("COMPLETION_SESSION_BINDING_INVALID")
        if self.proof_class == "WRITER_CALL_RETURNED":
            if self.source_service_id != bound.writer_service_id or self.source_host_id != bound.writer_host_id:
                raise ValueError("WRITER_SOURCE_BINDING_INVALID")
            if self.source_process_instance_id != bound.writer_process_instance_id:
                raise ValueError("WRITER_PROCESS_BINDING_INVALID")
        else:
            # Supervisor is independently identified but scoped to this writer host.
            if self.source_service_id == bound.writer_service_id or self.source_host_id != bound.writer_host_id:
                raise ValueError("SUPERVISOR_SOURCE_BINDING_INVALID")
            if self.source_process_instance_id == bound.writer_process_instance_id:
                raise ValueError("SUPERVISOR_PROCESS_BINDING_INVALID")

    def validate_dispatch_binding(self, receipt: DispatchReceipt) -> None:
        """Compatibility convenience for a receipt-backed completion proof."""
        self.validate_attempt_binding(DispatchAttempt.from_receipt(receipt), receipt)


def record_digest(record: _Envelope) -> str:
    """Compute the domain-separated digest over the closed record body."""
    return record.calculated_digest()


def sign_record_fixture(record: _Envelope, seed: bytes) -> str:
    """Return a lowercase-hex signature for a synthetic fixture seed only."""
    return ed25519.sign(seed, record.signature_preimage()).hex()


def seal_record_fixture(record_type: type[_Envelope], fields: Mapping[str, object], seed: bytes) -> _Envelope:
    """Build a complete signed local fixture from a schema-shaped field mapping.

    The caller supplies all fields including a placeholder digest and empty
    signature. This helper is intentionally named for fixtures: production
    signing and key custody are outside this module's authority.
    """
    draft_fields = dict(fields)
    draft_fields[record_type.DIGEST_FIELD] = "0" * 64
    draft_fields["signature"] = ""
    draft = record_type(draft_fields)
    draft_fields[record_type.DIGEST_FIELD] = draft.calculated_digest()
    unsigned = record_type(draft_fields)
    draft_fields["signature"] = sign_record_fixture(unsigned, seed)
    return record_type(draft_fields)


def verify_record_signature(record: _Envelope, public_key: bytes) -> bool:
    """Verify digest and Ed25519 signature; identity registry authorization is external."""
    fields = record.to_dict()
    digest = fields.get(record.DIGEST_FIELD)
    signature = fields.get("signature")
    if type(digest) is not str or digest != record.calculated_digest() or type(signature) is not str:
        return False
    try:
        raw_signature = bytes.fromhex(signature)
    except ValueError:
        return False
    return ed25519.verify(public_key, record.signature_preimage(), raw_signature)
