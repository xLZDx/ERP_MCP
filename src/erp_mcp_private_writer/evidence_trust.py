"""Production evidence-trust data contract, separate from evaluation-only registries.

This module defines immutable trust snapshots and a provider protocol only. It does not load trust
data, verify signatures, authorize evidence, or make any service operational by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from business_ai_gateway.phase2.change_ledger.uuid_contract import (
    is_canonical_nonzero_uuid,
    is_canonical_process_instance_uuid,
)


_SIGNER_ROLES = frozenset({
    "writer_receipt", "verification_worker", "completion_supervisor", "read_attestor",
    "checkpoint_signer",
})
_OPERATION_KINDS = frozenset({"CREATE_DRAFT", "POST", "UNPOST"})
_MAX_POSTGRES_INTEGER = 2_147_483_647
_MAX_POSTGRES_BIGINT = 9_223_372_036_854_775_807


def is_canonical_positive_trust_revision(value: object) -> bool:
    """Accept only canonical positive decimal text for a PostgreSQL bigint revision."""
    return (type(value) is str and 0 < len(value) <= 19 and value[0] != "0"
            and all("0" <= character <= "9" for character in value)
            and int(value) <= _MAX_POSTGRES_BIGINT)


def _aware_utc(value: datetime, code: str) -> None:
    if (type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None
            or value.utcoffset().total_seconds() != 0):
        raise ValueError(code)


def _text(value: str, *, max_length: int = 512) -> None:
    if (type(value) is not str or not value or value != value.strip()
            or len(value) > max_length
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValueError("TRUST_SNAPSHOT_TEXT_INVALID")


@dataclass(frozen=True, slots=True)
class EvidenceScope:
    tenant_id: str
    company_id: str
    organization_ref: str
    base_fingerprint: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.company_id, self.organization_ref, self.base_fingerprint):
            _text(value)
        if (len(self.base_fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in self.base_fingerprint)):
            raise ValueError("EVIDENCE_SCOPE_FINGERPRINT_INVALID")


@dataclass(frozen=True, slots=True)
class SignerKeyRef:
    key_id: str
    key_version: str

    def __post_init__(self) -> None:
        _text(self.key_id, max_length=128)
        _text(self.key_version, max_length=64)


@dataclass(frozen=True, slots=True)
class TrustedSigner:
    key: SignerKeyRef
    public_key: bytes
    signer_role: str
    service_id: str
    host_id: str
    allowed_scopes: tuple[EvidenceScope, ...]
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None
    rotation_history: tuple[SignerKeyRef, ...]

    def __post_init__(self) -> None:
        if (type(self.key) is not SignerKeyRef or type(self.public_key) is not bytes
                or len(self.public_key) != 32 or type(self.signer_role) is not str
                or self.signer_role not in _SIGNER_ROLES):
            raise ValueError("TRUSTED_SIGNER_INVALID")
        _text(self.service_id)
        _text(self.host_id)
        if (type(self.allowed_scopes) is not tuple
                or any(type(scope) is not EvidenceScope for scope in self.allowed_scopes)
                or len(set(self.allowed_scopes)) != len(self.allowed_scopes)):
            raise ValueError("TRUSTED_SIGNER_SCOPES_INVALID")
        if (type(self.rotation_history) is not tuple or not self.rotation_history
                or any(type(item) is not SignerKeyRef for item in self.rotation_history)
                or len(set(self.rotation_history)) != len(self.rotation_history)
                or self.rotation_history[-1] != self.key):
            raise ValueError("TRUSTED_SIGNER_ROTATION_INVALID")
        _aware_utc(self.valid_from, "TRUSTED_SIGNER_VALID_FROM_INVALID")
        _aware_utc(self.valid_until, "TRUSTED_SIGNER_VALID_UNTIL_INVALID")
        if self.valid_until <= self.valid_from:
            raise ValueError("TRUSTED_SIGNER_VALIDITY_INVALID")
        if self.revoked_at is not None:
            _aware_utc(self.revoked_at, "TRUSTED_SIGNER_REVOCATION_INVALID")


@dataclass(frozen=True, slots=True)
class TrustedProcessBinding:
    process_instance_id: str
    host_boot_id: str
    service_id: str
    host_id: str
    os_pid: int
    process_created_at: datetime
    supervisor_key: SignerKeyRef
    signature: bytes

    def __post_init__(self) -> None:
        for value in (self.process_instance_id, self.host_boot_id, self.service_id,
                      self.host_id):
            _text(value)
        if (not is_canonical_process_instance_uuid(self.process_instance_id)
                or not is_canonical_nonzero_uuid(self.host_boot_id)):
            raise ValueError("TRUSTED_PROCESS_UUID_INVALID")
        if (type(self.os_pid) is not int or not 1 <= self.os_pid <= _MAX_POSTGRES_INTEGER
                or type(self.supervisor_key) is not SignerKeyRef
                or type(self.signature) is not bytes or len(self.signature) != 64):
            raise ValueError("TRUSTED_PROCESS_BINDING_INVALID")
        _aware_utc(self.process_created_at, "TRUSTED_PROCESS_CREATED_AT_INVALID")


@dataclass(frozen=True, slots=True)
class TrustedOracleArtifact:
    scope: EvidenceScope
    operation_kind: str
    oracle_id: str
    oracle_version: str
    document_shape_revision: str
    configuration_fingerprint: str
    oracle_digest: str
    expected_effect_schema_version: str

    def __post_init__(self) -> None:
        if (type(self.scope) is not EvidenceScope or type(self.operation_kind) is not str
                or self.operation_kind not in _OPERATION_KINDS):
            raise ValueError("TRUSTED_ORACLE_ARTIFACT_INVALID")
        for value in (self.oracle_id, self.oracle_version, self.document_shape_revision,
                      self.expected_effect_schema_version):
            _text(value)
        for value in (self.configuration_fingerprint, self.oracle_digest):
            if (type(value) is not str or len(value) != 64
                    or any(character not in "0123456789abcdef" for character in value)):
                raise ValueError("TRUSTED_ORACLE_DIGEST_INVALID")


@dataclass(frozen=True, slots=True)
class OutcomeVersionFloor:
    scope: EvidenceScope
    operation_kind: str
    minimum_version: int

    def __post_init__(self) -> None:
        if (type(self.scope) is not EvidenceScope or type(self.operation_kind) is not str
                or self.operation_kind not in _OPERATION_KINDS
                or type(self.minimum_version) is not int
                or self.minimum_version not in (1, 2, 3)):
            raise ValueError("OUTCOME_VERSION_FLOOR_INVALID")


@dataclass(frozen=True, slots=True)
class TrustSnapshotRequest:
    scope: EvidenceScope
    operation_kind: str
    signer_keys: tuple[SignerKeyRef, ...]
    process_instance_ids: tuple[str, ...]
    oracle_id: str | None = None
    oracle_version: str | None = None
    include_operation_oracle_policy: bool = False

    def __post_init__(self) -> None:
        if (type(self.scope) is not EvidenceScope or type(self.operation_kind) is not str
                or self.operation_kind not in _OPERATION_KINDS
                or type(self.signer_keys) is not tuple or type(self.process_instance_ids) is not tuple
                or any(type(key) is not SignerKeyRef for key in self.signer_keys)
                or not 1 <= len(self.signer_keys) <= 16
                or len(self.process_instance_ids) > 16
                or len(set(self.signer_keys)) != len(self.signer_keys)
                or any(type(value) is not str for value in self.process_instance_ids)
                or len(set(self.process_instance_ids)) != len(self.process_instance_ids)
                or type(self.include_operation_oracle_policy) is not bool
                or (self.include_operation_oracle_policy and self.oracle_id is not None)):
            raise ValueError("TRUST_SNAPSHOT_REQUEST_INVALID")
        for value in self.process_instance_ids:
            _text(value)
            if not is_canonical_process_instance_uuid(value):
                raise ValueError("TRUST_SNAPSHOT_REQUEST_INVALID")
        if (self.oracle_id is None) != (self.oracle_version is None):
            raise ValueError("TRUST_SNAPSHOT_ORACLE_REFERENCE_INVALID")
        if self.oracle_id is not None:
            _text(self.oracle_id)
            _text(self.oracle_version)


@dataclass(frozen=True, slots=True)
class EvidenceTrustSnapshot:
    revision: str
    loaded_at: datetime
    signers: tuple[TrustedSigner, ...]
    process_bindings: tuple[TrustedProcessBinding, ...]
    oracle_artifacts: tuple[TrustedOracleArtifact, ...]
    outcome_version_floors: tuple[OutcomeVersionFloor, ...]

    def __post_init__(self) -> None:
        if not is_canonical_positive_trust_revision(self.revision):
            raise ValueError("TRUST_SNAPSHOT_REVISION_INVALID")
        _aware_utc(self.loaded_at, "TRUST_SNAPSHOT_TIME_INVALID")
        groups = (
            (self.signers, TrustedSigner, lambda item: item.key),
            (self.process_bindings, TrustedProcessBinding, lambda item: item.process_instance_id),
            (self.oracle_artifacts, TrustedOracleArtifact,
             lambda item: (item.scope, item.operation_kind, item.oracle_id, item.oracle_version)),
            (self.outcome_version_floors, OutcomeVersionFloor,
             lambda item: (item.scope, item.operation_kind)),
        )
        for values, expected_type, key_of in groups:
            if (type(values) is not tuple or any(type(item) is not expected_type for item in values)
                    or len({key_of(item) for item in values}) != len(values)):
                raise ValueError("TRUST_SNAPSHOT_CONTENT_INVALID")
        if len({item.public_key for item in self.signers}) != len(self.signers):
            raise ValueError("TRUST_SNAPSHOT_PUBLIC_KEY_REUSE")
        signer_map = {item.key: item for item in self.signers}
        for signer in self.signers:
            for key_ref in signer.rotation_history:
                predecessor = signer_map.get(key_ref)
                if (predecessor is None or predecessor.signer_role != signer.signer_role
                        or predecessor.service_id != signer.service_id
                        or predecessor.host_id != signer.host_id):
                    raise ValueError("TRUST_SNAPSHOT_ROTATION_CHAIN_INVALID")
        independent_roles = (
            "writer_receipt", "verification_worker", "completion_supervisor",
            "read_attestor", "checkpoint_signer",
        )
        role_services = {
            role: {item.service_id for item in self.signers if item.signer_role == role}
            for role in independent_roles
        }
        if any(
                role_services[left] & role_services[right]
                for index, left in enumerate(independent_roles)
                for right in independent_roles[index + 1:]):
            raise ValueError("TRUST_SNAPSHOT_SERVICE_COLLISION")

    def signer(self, key: SignerKeyRef) -> TrustedSigner | None:
        return next((item for item in self.signers if item.key == key), None)

    def process(self, process_instance_id: str) -> TrustedProcessBinding | None:
        return next((item for item in self.process_bindings
                     if item.process_instance_id == process_instance_id), None)

    def oracle(self, scope: EvidenceScope, operation_kind: str, oracle_id: str,
               oracle_version: str) -> TrustedOracleArtifact | None:
        return next((item for item in self.oracle_artifacts
                     if (item.scope, item.operation_kind, item.oracle_id, item.oracle_version)
                     == (scope, operation_kind, oracle_id, oracle_version)), None)

    def minimum_outcome_version(self, scope: EvidenceScope, operation_kind: str) -> int | None:
        policy = next((item for item in self.outcome_version_floors
                       if (item.scope, item.operation_kind) == (scope, operation_kind)), None)
        return policy.minimum_version if policy is not None else None


class ProductionEvidenceTrustSource(Protocol):
    """Load one coherent authoritative snapshot and enforce registry-global invariants.

    The source must verify uniqueness/collision rules across the complete registry, not only the
    scoped records returned for this request. Revision and trust rows come from one database
    snapshot; loaded_at is a server-clock sample associated with the load, but is not guaranteed
    atomic with that MVCC snapshot. It must never authorize registration by itself: the final
    database registration transaction rechecks current revocation while holding the key-version
    row lock. The source must not return cached snapshots. Referenced supervisor keys and complete
    rotation chains are included even when they are not direct request keys. When
    ``include_operation_oracle_policy`` is true, return the complete oracle set for the exact
    requested scope and operation, bounded at 16 rows; never truncate it. Other requests return
    either the one exact requested oracle or no oracle rows.
    """

    async def load_snapshot(self, request: TrustSnapshotRequest) -> EvidenceTrustSnapshot: ...


__all__ = [
    "EvidenceScope", "EvidenceTrustSnapshot", "OutcomeVersionFloor", "ProductionEvidenceTrustSource",
    "SignerKeyRef", "TrustSnapshotRequest", "TrustedOracleArtifact", "TrustedProcessBinding",
    "TrustedSigner", "is_canonical_positive_trust_revision",
]
