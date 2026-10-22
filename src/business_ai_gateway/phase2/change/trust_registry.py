"""Offline S12 identity-registry reference verifier (EVALUATION_ONLY).

The registry is supplied as an authenticated snapshot by its caller. This module never loads
private keys, opens a network connection, or establishes production key custody. Its signature
primitive is the repository's test-lane Ed25519 implementation and is not production approved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from .. import ed25519
from .evidence import (
    CompletionProof, DispatchAttempt, DispatchReceipt, OutcomeEvidence, _Envelope,
    canonical_json_bytes, verify_record_signature,
)

__all__ = [
    "IdentityScope", "KeyVersion", "ProcessInstanceAttestation", "SignerIdentity",
    "TrustedIdentityRegistry", "process_attestation_preimage", "verify_authorized_record",
]

_PROCESS_PREFIX = b"ERP_MCP_R2:S13:PROCESS-INSTANCE:v1\n"
_ROLES = frozenset(("writer_receipt", "verification_worker", "completion_supervisor", "checkpoint_signer"))


def _aware_utc(value: object, field: str) -> datetime:
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None or value.utcoffset().total_seconds() != 0):
        raise ValueError(f"{field}_INVALID")
    return value


def _record_time(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("RECORD_TIME_INVALID") from None


@dataclass(frozen=True, slots=True)
class IdentityScope:
    tenant_id: str
    company_id: str
    organization_ref: str
    base_fingerprint: str

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v or v != v.strip()
               or len(v) > 512
               for v in (self.tenant_id, self.company_id, self.organization_ref, self.base_fingerprint)):
            raise ValueError("IDENTITY_SCOPE_INVALID")


@dataclass(frozen=True, slots=True)
class KeyVersion:
    key_id: str
    version: str

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v or v != v.strip() for v in (self.key_id, self.version)):
            raise ValueError("KEY_VERSION_INVALID")


@dataclass(frozen=True, slots=True)
class SignerIdentity:
    key_id: str
    key_version: str
    public_key: bytes
    role: str
    service_id: str
    host_id: str
    allowed_scopes: tuple[IdentityScope, ...]
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None
    rotation_history: tuple[KeyVersion, ...]

    def __post_init__(self) -> None:
        if (any(type(v) is not str or not v or v != v.strip() or len(v) > 512
                for v in (self.key_id, self.key_version, self.role, self.service_id, self.host_id))
                or self.role not in _ROLES
                or type(self.public_key) is not bytes or len(self.public_key) != 32
                or type(self.allowed_scopes) is not tuple or not self.allowed_scopes
                or any(type(s) is not IdentityScope for s in self.allowed_scopes)
                or len(set(self.allowed_scopes)) != len(self.allowed_scopes)
                or type(self.rotation_history) is not tuple or not self.rotation_history
                or any(type(v) is not KeyVersion for v in self.rotation_history)
                or len(set(self.rotation_history)) != len(self.rotation_history)
                or self.rotation_history[-1] != KeyVersion(self.key_id, self.key_version)):
            raise ValueError("SIGNER_IDENTITY_INVALID")
        start = _aware_utc(self.valid_from, "VALID_FROM")
        end = _aware_utc(self.valid_until, "VALID_UNTIL")
        if end <= start:
            raise ValueError("KEY_VALIDITY_INVALID")
        if self.revoked_at is not None:
            _aware_utc(self.revoked_at, "REVOKED_AT")


@dataclass(frozen=True, slots=True)
class ProcessInstanceAttestation:
    """Supervisor-signed binding from a non-reusable service UUID to one host process instance."""

    process_instance_id: str
    host_boot_id: str
    service_id: str
    host_id: str
    os_pid: int
    process_created_at: datetime
    supervisor_key_id: str
    supervisor_key_version: str
    signature: str

    def unsigned_dict(self) -> dict[str, object]:
        created = _aware_utc(self.process_created_at, "PROCESS_CREATED_AT").astimezone(timezone.utc)
        return {
            "attestation_version": "1", "process_instance_id": self.process_instance_id,
            "host_boot_id": self.host_boot_id, "service_id": self.service_id, "host_id": self.host_id,
            "os_pid": self.os_pid,
            "process_created_at": created.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "supervisor_key_id": self.supervisor_key_id,
            "supervisor_key_version": self.supervisor_key_version,
        }

    def __post_init__(self) -> None:
        try:
            process_id = UUID(self.process_instance_id)
            boot_id = UUID(self.host_boot_id)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("PROCESS_INSTANCE_INVALID") from None
        if (str(process_id) != self.process_instance_id or process_id.int == 0
                or str(boot_id) != self.host_boot_id or boot_id.int == 0
                or any(type(v) is not str or not v or v != v.strip() or len(v) > 512
                       for v in (self.service_id, self.host_id, self.supervisor_key_id,
                                 self.supervisor_key_version))
                or type(self.os_pid) is not int or self.os_pid <= 0
                or type(self.signature) is not str or len(self.signature) != 128
                or any(ch not in "0123456789abcdef" for ch in self.signature)):
            raise ValueError("PROCESS_ATTESTATION_INVALID")
        _aware_utc(self.process_created_at, "PROCESS_CREATED_AT")


class TrustedIdentityRegistry:
    """Immutable evaluation registry snapshot; provider authenticity is an external prerequisite."""

    __slots__ = ("_keys", "_processes", "_frozen")

    def __init__(self, identities: tuple[SignerIdentity, ...],
                 process_instances: tuple[ProcessInstanceAttestation, ...] = ()) -> None:
        if type(identities) is not tuple or type(process_instances) is not tuple:
            raise ValueError("REGISTRY_SNAPSHOT_INVALID")
        keys: dict[tuple[str, str], SignerIdentity] = {}
        public_keys: set[bytes] = set()
        for item in identities:
            if type(item) is not SignerIdentity:
                raise ValueError("REGISTRY_IDENTITY_INVALID")
            ref = (item.key_id, item.key_version)
            if ref in keys:
                raise ValueError("REGISTRY_KEY_DUPLICATE")
            if item.public_key in public_keys:
                raise ValueError("PUBLIC_KEY_REUSE")
            keys[ref] = item
            public_keys.add(item.public_key)
        for item in keys.values():
            for version in item.rotation_history:
                previous = keys.get((version.key_id, version.version))
                if previous is None:
                    raise ValueError("ROTATION_HISTORY_INCOMPLETE")
                if (previous.role != item.role or previous.service_id != item.service_id
                        or previous.host_id != item.host_id):
                    raise ValueError("ROTATION_IDENTITY_MISMATCH")
        processes: dict[str, ProcessInstanceAttestation] = {}
        for item in process_instances:
            if type(item) is not ProcessInstanceAttestation or item.process_instance_id in processes:
                raise ValueError("PROCESS_INSTANCE_DUPLICATE")
            processes[item.process_instance_id] = item
        self._keys: Mapping[tuple[str, str], SignerIdentity] = MappingProxyType(keys)
        self._processes: Mapping[str, ProcessInstanceAttestation] = MappingProxyType(processes)
        self._frozen = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("IMMUTABLE_REGISTRY")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("IMMUTABLE_REGISTRY")
        object.__delattr__(self, name)

    def resolve_signer(self, key_id: str, key_version: str) -> SignerIdentity | None:
        return self._keys.get((key_id, key_version))

    def resolve_process(self, process_instance_id: str) -> ProcessInstanceAttestation | None:
        return self._processes.get(process_instance_id)


def process_attestation_preimage(attestation: ProcessInstanceAttestation) -> bytes:
    """Return domain-separated bytes for an authenticated host supervisor's process binding."""
    if type(attestation) is not ProcessInstanceAttestation:
        raise ValueError("PROCESS_ATTESTATION_INVALID")
    return _PROCESS_PREFIX + canonical_json_bytes(attestation.unsigned_dict())


def _record_identity(record: _Envelope) -> tuple[str, str, str, str, IdentityScope, str]:
    if isinstance(record, DispatchReceipt):
        return (record.signer_key_id, record.key_version, record.signer_role, record.writer_service_id,
                IdentityScope(record.tenant_id, record.company_id, record.organization_ref, record.base_fingerprint),
                record.writer_host_id)
    if isinstance(record, OutcomeEvidence):
        return (record.signer_key_id, record.key_version, record.role, record.verifier_service_id,
                IdentityScope(record.tenant_id, record.company_id, record.organization_ref, record.base_fingerprint),
                record.verifier_host_id)
    if isinstance(record, CompletionProof):
        return (record.signer_key_id, record.key_version, record.signer_role, record.source_service_id,
                IdentityScope(record.tenant_id, record.company_id, record.organization_ref, record.base_fingerprint),
                record.source_host_id)
    raise ValueError("EVIDENCE_TYPE_UNSUPPORTED")


def _verify_process_attestation(registry: TrustedIdentityRegistry, process_id: str,
                                service_id: str, host_id: str, scope: IdentityScope,
                                event_at: datetime, now: datetime) -> None:
    attestation = registry.resolve_process(process_id)
    if (attestation is None or attestation.service_id != service_id or attestation.host_id != host_id
            or attestation.process_created_at > event_at):
        raise ValueError("PROCESS_BINDING_UNTRUSTED")
    supervisor = registry.resolve_signer(attestation.supervisor_key_id, attestation.supervisor_key_version)
    if (supervisor is None or supervisor.role != "completion_supervisor"
            or supervisor.host_id != host_id or supervisor.service_id == service_id
            or scope not in supervisor.allowed_scopes):
        raise ValueError("PROCESS_SUPERVISOR_UNTRUSTED")
    _check_key_time(supervisor, attestation.process_created_at, now)
    if not ed25519.verify(supervisor.public_key, process_attestation_preimage(attestation),
                          bytes.fromhex(attestation.signature)):
        raise ValueError("PROCESS_ATTESTATION_INVALID")


def _check_key_time(identity: SignerIdentity, signed_at: datetime, now: datetime) -> None:
    if signed_at > now:
        raise ValueError("SIGNATURE_FROM_FUTURE")
    if (identity.revoked_at is not None and now >= identity.revoked_at):
        raise ValueError("SIGNER_KEY_REVOKED")
    if not (identity.valid_from <= signed_at < identity.valid_until
            and identity.valid_from <= now < identity.valid_until):
        raise ValueError("SIGNER_KEY_OUTSIDE_VALIDITY")


def verify_authorized_record(record: _Envelope, registry: TrustedIdentityRegistry, *,
                             expected_scope: IdentityScope, attempt: DispatchAttempt,
                             now: datetime | None = None,
                             receipt: DispatchReceipt | None = None) -> None:
    """Verify signature, current key authorization, scope, attempt binding, and process identity.

    Raises only fixed refusal codes. A trusted registry snapshot and audited production Ed25519
    provider are required before this evaluation-only reference may be used for real actions.
    """
    current = _aware_utc(now or datetime.now(timezone.utc), "NOW")
    if type(record) not in (DispatchReceipt, OutcomeEvidence, CompletionProof):
        raise ValueError("EVIDENCE_TYPE_UNSUPPORTED")
    if type(registry) is not TrustedIdentityRegistry or type(expected_scope) is not IdentityScope:
        raise ValueError("TRUST_CONTEXT_INVALID")
    if type(attempt) is not DispatchAttempt:
        raise ValueError("ATTEMPT_REQUIRED")
    if isinstance(record, DispatchReceipt):
        record.validate_attempt_binding(attempt)
        signed_at = _record_time(record.started_at)
    elif isinstance(record, OutcomeEvidence):
        record.validate_attempt_binding(attempt, receipt)
        signed_at = _record_time(record.observed_at)
    else:
        record.validate_attempt_binding(attempt, receipt)
        signed_at = _record_time(record.observed_at)
    key_id, version, role, service_id, scope, host_id = _record_identity(record)
    if scope != expected_scope:
        raise ValueError("EVIDENCE_SCOPE_MISMATCH")
    identity = registry.resolve_signer(key_id, version)
    if identity is None:
        raise ValueError("SIGNER_IDENTITY_UNKNOWN")
    if (identity.role != role or identity.service_id != service_id or identity.host_id != host_id
            or scope not in identity.allowed_scopes):
        raise ValueError("SIGNER_IDENTITY_MISMATCH")
    _check_key_time(identity, signed_at, current)
    if not verify_record_signature(record, identity.public_key):
        raise ValueError("EVIDENCE_SIGNATURE_INVALID")
    if isinstance(record, DispatchReceipt):
        _verify_process_attestation(registry, record.writer_process_instance_id,
                                    record.writer_service_id, record.writer_host_id, scope, signed_at, current)
    elif isinstance(record, CompletionProof):
        attempt_time = _record_time(record.observed_at)
        _verify_process_attestation(registry, record.writer_process_instance_id,
                                    attempt.writer_service_id, attempt.writer_host_id, scope, attempt_time, current)
        if record.proof_class == "INDEPENDENT_SESSION_AND_PROCESS_CLOSED":
            _verify_process_attestation(registry, record.source_process_instance_id,
                                        record.source_service_id, record.source_host_id, scope, signed_at, current)
