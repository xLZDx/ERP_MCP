"""Strict source verifier for signed validator-build attestations.

This module verifies an attestation and compares it with independently supplied trust, policy,
clock, and runtime-artifact measurements. It deliberately does not provide those authorities.
Production composition must use the host-bound source; disposable tests use a distinct source and
cannot enter the production composition root.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from typing import Protocol

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes

from .dpapi_signer import verify_ed25519
from .json_preflight import check_json_document_limits


ATTESTATION_DOMAIN = b"ERP_MCP_R2:S13:VALIDATOR-BUILD-ATTESTATION:v1\n"
BUILD_ID_DOMAIN = b"ERP_MCP_R2:S13:VALIDATOR-BUILD-ID:v1\n"
MAX_ATTESTATION_BYTES = 64 * 1024
MAX_ATTESTATION_DEPTH = 4
MAX_ATTESTATION_NODES = 96
MAX_TRUST_SNAPSHOT_AGE_SECONDS = 3.0
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_CLAIM_FIELDS = frozenset({
    "schema_version", "issuer_id", "key_id", "key_version", "policy_id",
    "policy_version", "build_id", "image_digest", "source_revision",
    "build_provenance_digest", "validator_component", "deployment_id",
    "environment_id", "issued_at", "not_before", "expires_at", "attestation_id",
})
_ENVELOPE_FIELDS = frozenset({"claims", "signature"})
_PRODUCTION_BUILD_AUTHORITY_SEAL = object()
# Empty until a concrete host-bound source has been implemented and reviewed. The abstract
# ProductionValidatorBuildInputsSource marker by itself is deliberately not an authorization.
_PRODUCTION_INPUT_SOURCE_TYPES: tuple[type, ...] = ()


class ValidatorBuildAttestationError(RuntimeError):
    """Stable fail-closed errors without exposing signed claims or key material."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ValidatorBuildAttestationInputsSource(Protocol):
    """Read current attestation plus independently authenticated verification inputs."""

    async def load_current_inputs(self) -> ValidatorBuildAttestationInputs: ...


class ProductionValidatorBuildInputsSource(ABC):
    """Base type reserved for the future host-authorized source implementation.

    The abstract base itself cannot be instantiated and does not confer production authority.
    Only an exact concrete type in ``_PRODUCTION_INPUT_SOURCE_TYPES`` is accepted by the
    verifier/registrar. That allowlist is empty until a host-bound implementation and its
    independently authorized trust inputs are reviewed.
    """

    @abstractmethod
    async def load_current_inputs(self) -> ValidatorBuildAttestationInputs:
        """Read from externally authorized host trust, policy, clock and measurement sources."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ValidatorBuildTrustKey:
    issuer_id: str
    key_id: str
    key_version: str
    signer_role: str
    public_key: bytes
    valid_from: datetime
    valid_until: datetime


@dataclass(frozen=True, slots=True)
class ValidatorBuildPolicy:
    policy_id: str
    policy_version: str
    validator_component: str
    environment_id: str
    max_attestation_lifetime_seconds: int
    allowed_signer_key_versions: frozenset[tuple[str, str, str]]
    allowed_image_digests: frozenset[str]
    allowed_build_provenance_digests: frozenset[str]
    allowed_source_revisions: frozenset[str]
    allowed_deployment_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ValidatorBuildTrustSnapshot:
    revision: str
    keys: tuple[ValidatorBuildTrustKey, ...]
    policies: tuple[ValidatorBuildPolicy, ...]
    revoked_key_versions: frozenset[tuple[str, str]]
    revoked_policy_versions: frozenset[tuple[str, str]]
    revoked_attestation_ids: frozenset[str]
    revoked_build_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class RuntimeValidatorArtifact:
    """Independently measured identity of the validator currently executing this operation."""

    image_digest: str
    source_revision: str
    build_provenance_digest: str
    validator_component: str
    deployment_id: str
    environment_id: str
    measured_at: datetime


@dataclass(frozen=True, slots=True)
class ValidatorBuildAttestationInputs:
    signed_envelope: bytes
    trust_snapshot: ValidatorBuildTrustSnapshot
    runtime_artifact: RuntimeValidatorArtifact
    trust_snapshot_fetched_at: datetime
    authenticated_now: datetime


@dataclass(frozen=True, slots=True)
class ApprovedValidatorBuild:
    """A verifier-produced build identity; never construct from a caller-supplied build string."""

    build_id: str
    policy_id: str
    policy_version: str
    attestation_id: str
    image_digest: str
    source_revision: str
    deployment_id: str
    environment_id: str
    trust_revision: str
    validated_at: datetime
    attestation_sha256: str
    _verification_seal: object
    _production_authority_seal: object | None = None

    def __post_init__(self) -> None:
        if (self._verification_seal is not _VERIFICATION_SEAL
                or (self._production_authority_seal is not None
                    and self._production_authority_seal is not _PRODUCTION_BUILD_AUTHORITY_SEAL)):
            raise ValueError("VALIDATOR_BUILD_NOT_VERIFIED")


_VERIFICATION_SEAL = object()


class ValidatorBuildAttestationVerifier:
    """Fetch and verify one canonical signed attestation before returning a build identity."""

    __slots__ = ("_source", "_timeout_seconds")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("VALIDATOR_BUILD_VERIFIER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("VALIDATOR_BUILD_VERIFIER_CONFIGURATION_IMMUTABLE")

    @property
    def has_production_authority_source(self) -> bool:
        """Accept only an exact, explicitly reviewed host-source type; never a marker subclass."""
        return type(self._source) in _PRODUCTION_INPUT_SOURCE_TYPES

    def __init__(self, source: ValidatorBuildAttestationInputsSource, *,
                 timeout_seconds: float = 3.0) -> None:
        from .dependency_shape import has_static_callable_method

        if not has_static_callable_method(source, "load_current_inputs"):
            raise ValueError("VALIDATOR_BUILD_INPUT_SOURCE_INVALID")
        if (isinstance(timeout_seconds, bool) or type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 5 or not math.isfinite(timeout_seconds)):
            raise ValueError("VALIDATOR_BUILD_TIMEOUT_INVALID")
        self._source = source
        self._timeout_seconds = float(timeout_seconds)

    async def load_current_approved_build(self) -> ApprovedValidatorBuild:
        import asyncio

        try:
            async with asyncio.timeout(self._timeout_seconds):
                inputs = await self._source.load_current_inputs()
        except (TimeoutError, asyncio.TimeoutError):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ATTESTATION_TIMEOUT") from None
        except Exception:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ATTESTATION_UNAVAILABLE") from None
        try:
            verified = self.verify(inputs)
            if not self.has_production_authority_source:
                return verified
            return ApprovedValidatorBuild(
                build_id=verified.build_id,
                policy_id=verified.policy_id,
                policy_version=verified.policy_version,
                attestation_id=verified.attestation_id,
                image_digest=verified.image_digest,
                source_revision=verified.source_revision,
                deployment_id=verified.deployment_id,
                environment_id=verified.environment_id,
                trust_revision=verified.trust_revision,
                validated_at=verified.validated_at,
                attestation_sha256=verified.attestation_sha256,
                _verification_seal=_VERIFICATION_SEAL,
                _production_authority_seal=_PRODUCTION_BUILD_AUTHORITY_SEAL,
            )
        except ValidatorBuildAttestationError:
            raise
        except Exception:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ATTESTATION_INVALID") from None

    @staticmethod
    def verify(inputs: ValidatorBuildAttestationInputs) -> ApprovedValidatorBuild:
        """Verify signed claims, current policy and measured artifact without external I/O."""
        if type(inputs) is not ValidatorBuildAttestationInputs:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_INPUT_INVALID")
        if (type(inputs.signed_envelope) is not bytes or not inputs.signed_envelope
                or len(inputs.signed_envelope) > MAX_ATTESTATION_BYTES):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ENVELOPE_INVALID")
        trust = inputs.trust_snapshot
        runtime = inputs.runtime_artifact
        now = inputs.authenticated_now
        fetched_at = inputs.trust_snapshot_fetched_at
        if (type(trust) is not ValidatorBuildTrustSnapshot
                or type(runtime) is not RuntimeValidatorArtifact
                or type(fetched_at) is not datetime or fetched_at.tzinfo is None
                or fetched_at.utcoffset() is None or fetched_at.utcoffset().total_seconds() != 0
                or type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None
                or now.utcoffset().total_seconds() != 0):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_AUTHORITY_INPUT_INVALID")
        snapshot_age = (now.astimezone(timezone.utc) - fetched_at.astimezone(timezone.utc)).total_seconds()
        if not 0 <= snapshot_age <= MAX_TRUST_SNAPSHOT_AGE_SECONDS:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_TRUST_SNAPSHOT_STALE")
        measured_at = runtime.measured_at
        if (type(measured_at) is not datetime or measured_at.tzinfo is None
                or measured_at.utcoffset() is None or measured_at.utcoffset().total_seconds() != 0):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_RUNTIME_MEASUREMENT_INVALID")
        measurement_age = (now.astimezone(timezone.utc)
                           - measured_at.astimezone(timezone.utc)).total_seconds()
        if not 0 <= measurement_age <= MAX_TRUST_SNAPSHOT_AGE_SECONDS:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_RUNTIME_MEASUREMENT_STALE")
        try:
            document = inputs.signed_envelope.decode("utf-8", errors="strict")
            check_json_document_limits(
                document, max_depth=MAX_ATTESTATION_DEPTH,
                max_structural_nodes=MAX_ATTESTATION_NODES,
            )
            parsed = json.loads(
                document, object_pairs_hook=_unique_object,
                parse_float=_reject_json_float, parse_constant=_reject_json_constant,
                parse_int=_bounded_integer,
            )
        except Exception:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ENVELOPE_INVALID") from None
        if (type(parsed) is not dict or set(parsed) != _ENVELOPE_FIELDS
                or canonical_json_bytes(parsed) != inputs.signed_envelope):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ENVELOPE_NONCANONICAL")
        claims = parsed.get("claims")
        encoded_signature = parsed.get("signature")
        if type(claims) is not dict or set(claims) != _CLAIM_FIELDS:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_CLAIMS_INVALID")
        signature = _decode_signature(encoded_signature)
        _validate_claim_shapes(claims)

        key_matches = tuple(key for key in trust.keys if (
            type(key) is ValidatorBuildTrustKey
            and key.issuer_id == claims["issuer_id"]
            and key.key_id == claims["key_id"]
            and key.key_version == claims["key_version"]
        ))
        policy_matches = tuple(policy for policy in trust.policies if (
            type(policy) is ValidatorBuildPolicy
            and policy.policy_id == claims["policy_id"]
            and policy.policy_version == claims["policy_version"]
        ))
        if len(key_matches) != 1 or len(policy_matches) != 1:
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_TRUST_ENTRY_UNKNOWN")
        key, policy = key_matches[0], policy_matches[0]
        _validate_trust_policy(key, policy, trust)
        if ((key.key_id, key.key_version) in trust.revoked_key_versions
                or (policy.policy_id, policy.policy_version) in trust.revoked_policy_versions
                or claims["attestation_id"] in trust.revoked_attestation_ids
                or claims["build_id"] in trust.revoked_build_ids):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_REVOKED")
        if (type(key.public_key) is not bytes or len(key.public_key) != 32
                or not verify_ed25519(
                    public_key=key.public_key,
                    message=ATTESTATION_DOMAIN + canonical_json_bytes(claims),
                    signature=signature,
                )):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_SIGNATURE_INVALID")

        issued = _parse_canonical_utc(claims["issued_at"])
        not_before = _parse_canonical_utc(claims["not_before"])
        expires = _parse_canonical_utc(claims["expires_at"])
        now_utc = now.astimezone(timezone.utc)
        if (type(key.valid_from) is not datetime or type(key.valid_until) is not datetime
                or key.valid_from.tzinfo is None or key.valid_until.tzinfo is None
                or key.valid_from.utcoffset() is None or key.valid_until.utcoffset() is None
                or not key.valid_from <= issued < key.valid_until
                or not key.valid_from <= now_utc < key.valid_until
                or not issued <= now_utc or not not_before <= now_utc < expires
                or expires <= issued
                or (expires - issued).total_seconds() > policy.max_attestation_lifetime_seconds):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_ATTESTATION_TIME_INVALID")

        expected_build_id = derive_validator_build_id(
            image_digest=claims["image_digest"],
            source_revision=claims["source_revision"],
            build_provenance_digest=claims["build_provenance_digest"],
            validator_component=claims["validator_component"],
        )
        if (claims["build_id"] != expected_build_id
                or not _runtime_matches(claims, runtime, policy)
                or claims["source_revision"] not in policy.allowed_source_revisions):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_RUNTIME_MISMATCH")
        if type(trust.revision) is not str or not _IDENTIFIER.fullmatch(trust.revision):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_TRUST_REVISION_INVALID")

        return ApprovedValidatorBuild(
            build_id=claims["build_id"], policy_id=claims["policy_id"],
            policy_version=claims["policy_version"], attestation_id=claims["attestation_id"],
            image_digest=claims["image_digest"], source_revision=claims["source_revision"],
            deployment_id=claims["deployment_id"], environment_id=claims["environment_id"],
            trust_revision=trust.revision, validated_at=now_utc,
            attestation_sha256=hashlib.sha256(inputs.signed_envelope).hexdigest(),
            _verification_seal=_VERIFICATION_SEAL,
        )


def derive_validator_build_id(*, image_digest: str, source_revision: str,
                              build_provenance_digest: str,
                              validator_component: str) -> str:
    body = {
        "build_provenance_digest": build_provenance_digest,
        "image_digest": image_digest,
        "source_revision": source_revision,
        "validator_component": validator_component,
    }
    return hashlib.sha256(BUILD_ID_DOMAIN + canonical_json_bytes(body)).hexdigest()


def _runtime_matches(claims: dict[str, object], runtime: RuntimeValidatorArtifact,
                     policy: ValidatorBuildPolicy) -> bool:
    if type(runtime) is not RuntimeValidatorArtifact or type(policy) is not ValidatorBuildPolicy:
        return False
    if (runtime.image_digest != claims["image_digest"]
            or runtime.source_revision != claims["source_revision"]
            or runtime.build_provenance_digest != claims["build_provenance_digest"]
            or runtime.validator_component != claims["validator_component"]
            or runtime.deployment_id != claims["deployment_id"]
            or runtime.environment_id != claims["environment_id"]):
        return False
    return (policy.validator_component == claims["validator_component"]
            and policy.environment_id == claims["environment_id"]
            and claims["image_digest"] in policy.allowed_image_digests
            and claims["build_provenance_digest"]
            in policy.allowed_build_provenance_digests
            and claims["deployment_id"] in policy.allowed_deployment_ids)


def _validate_trust_policy(key: ValidatorBuildTrustKey, policy: ValidatorBuildPolicy,
                           trust: ValidatorBuildTrustSnapshot) -> None:
    if (type(trust.keys) is not tuple or type(trust.policies) is not tuple
            or not trust.keys or not trust.policies
            or type(key.issuer_id) is not str or not _IDENTIFIER.fullmatch(key.issuer_id)
            or type(key.key_id) is not str or not _IDENTIFIER.fullmatch(key.key_id)
            or type(key.key_version) is not str or not _IDENTIFIER.fullmatch(key.key_version)
            or key.signer_role != "validator_build_attestation"
            or type(policy.policy_id) is not str or not _IDENTIFIER.fullmatch(policy.policy_id)
            or type(policy.policy_version) is not str
            or not _IDENTIFIER.fullmatch(policy.policy_version)
            or type(policy.validator_component) is not str
            or not _IDENTIFIER.fullmatch(policy.validator_component)
            or type(policy.environment_id) is not str
            or not _IDENTIFIER.fullmatch(policy.environment_id)
            or type(policy.max_attestation_lifetime_seconds) is not int
            or not 0 < policy.max_attestation_lifetime_seconds <= 365 * 24 * 60 * 60
            or type(policy.allowed_signer_key_versions) is not frozenset
            or not policy.allowed_signer_key_versions
            or any(type(entry) is not tuple or len(entry) != 3
                   or any(type(part) is not str or not _IDENTIFIER.fullmatch(part)
                          for part in entry)
                   for entry in policy.allowed_signer_key_versions)
            or type(policy.allowed_image_digests) is not frozenset
            or not policy.allowed_image_digests
            or any(type(value) is not str or not _HEX_256.fullmatch(value)
                   for value in policy.allowed_image_digests)
            or type(policy.allowed_build_provenance_digests) is not frozenset
            or not policy.allowed_build_provenance_digests
            or any(type(value) is not str or not _HEX_256.fullmatch(value)
                   for value in policy.allowed_build_provenance_digests)
            or type(policy.allowed_source_revisions) is not frozenset
            or not policy.allowed_source_revisions
            or any(type(revision) is not str or not _GIT_REVISION.fullmatch(revision)
                   for revision in policy.allowed_source_revisions)
            or type(policy.allowed_deployment_ids) is not frozenset
            or not policy.allowed_deployment_ids
            or any(type(value) is not str or not _IDENTIFIER.fullmatch(value)
                   for value in policy.allowed_deployment_ids)
            or type(trust.revoked_key_versions) is not frozenset
            or type(trust.revoked_policy_versions) is not frozenset
            or type(trust.revoked_attestation_ids) is not frozenset
            or type(trust.revoked_build_ids) is not frozenset
            or any(type(pair) is not tuple or len(pair) != 2
                   or any(type(part) is not str or not _IDENTIFIER.fullmatch(part)
                          for part in pair)
                   for pair in trust.revoked_key_versions | trust.revoked_policy_versions)
            or any(type(value) is not str or not _IDENTIFIER.fullmatch(value)
                   for value in trust.revoked_attestation_ids)
            or any(type(value) is not str or not _HEX_256.fullmatch(value)
                   for value in trust.revoked_build_ids)):
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_TRUST_POLICY_INVALID")
    if (key.signer_role != "validator_build_attestation"
            or (key.issuer_id, key.key_id, key.key_version)
            not in policy.allowed_signer_key_versions):
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_SIGNER_NOT_AUTHORIZED")


def _validate_claim_shapes(claims: dict[str, object]) -> None:
    if type(claims["schema_version"]) is not int or claims["schema_version"] != 1:
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_SCHEMA_UNSUPPORTED")
    for field in _CLAIM_FIELDS - {"schema_version", "source_revision", "issued_at",
                                  "not_before", "expires_at"}:
        if type(claims[field]) is not str or not _IDENTIFIER.fullmatch(claims[field]):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_CLAIMS_INVALID")
    for field in ("build_id", "image_digest", "build_provenance_digest"):
        if not _HEX_256.fullmatch(claims[field]):
            raise ValidatorBuildAttestationError("VALIDATOR_BUILD_CLAIMS_INVALID")
    if not _GIT_REVISION.fullmatch(claims["source_revision"]):
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_CLAIMS_INVALID")
    for field in ("issued_at", "not_before", "expires_at"):
        _parse_canonical_utc(claims[field])


def _parse_canonical_utc(value: object) -> datetime:
    if type(value) is not str or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value):
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_TIME_NONCANONICAL")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_TIME_INVALID") from None


def _decode_signature(value: object) -> bytes:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{86}", value):
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_SIGNATURE_INVALID")
    try:
        decoded = base64.b64decode(value + "==", altchars=b"-_", validate=True)
    except Exception:
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_SIGNATURE_INVALID") from None
    if (len(decoded) != 64
            or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value):
        raise ValidatorBuildAttestationError("VALIDATOR_BUILD_SIGNATURE_INVALID")
    return decoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_float(_value: str) -> object:
    raise ValueError("floating point is forbidden")


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _bounded_integer(value: str) -> int:
    if len(value) > 20:
        raise ValueError("integer too large")
    return int(value)


__all__ = [
    "ApprovedValidatorBuild",
    "ATTESTATION_DOMAIN",
    "MAX_ATTESTATION_BYTES",
    "MAX_TRUST_SNAPSHOT_AGE_SECONDS",
    "ProductionValidatorBuildInputsSource",
    "RuntimeValidatorArtifact",
    "ValidatorBuildAttestationError",
    "ValidatorBuildAttestationInputs",
    "ValidatorBuildAttestationInputsSource",
    "ValidatorBuildAttestationVerifier",
    "ValidatorBuildPolicy",
    "ValidatorBuildProvenanceSource",
    "ValidatorBuildTrustKey",
    "ValidatorBuildTrustSnapshot",
    "derive_validator_build_id",
]

# Compatibility import name, now bound to the cryptographic verifier rather than an arbitrary
# object that may self-assert an ApprovedValidatorBuild.
ValidatorBuildProvenanceSource = ValidatorBuildAttestationVerifier
