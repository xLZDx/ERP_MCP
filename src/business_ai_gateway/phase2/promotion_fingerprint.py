"""Canonical request fingerprinting for the bounded promotion-evidence contract.

This module only frames already-authenticated/resolved values. It performs no authorization,
evidence lookup, persistence, promotion, or runtime integration.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

__all__ = [
    "PromotionRequestFingerprintV1",
    "promotion_request_fingerprint_bytes_v1",
    "promotion_request_fingerprint_sha256_v1",
]

_DOMAIN = b"erp-mcp:promotion-request:v1\0"
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_MAX_FIELD_BYTES = 4096
_MAX_FINGERPRINT_BYTES = 65536
_CANONICAL_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PromotionRequestFingerprintV1:
    """Validated values, in the exact field order used by promotion-request-v1."""

    tenant: str
    source: str
    company: str
    model: str
    operation: str
    requested_rollback_version: int | None
    expected_version: int
    target_revision: str
    requester: str
    approver: str
    attestation: str
    evidence_reference: str
    artifact_version: str
    content_digest: str

    def __post_init__(self) -> None:
        if type(self.operation) is not str or self.operation not in ("promote", "rollback"):
            raise ValueError("FINGERPRINT_OPERATION_INVALID")

        for name in (
            "tenant", "source", "company", "model", "target_revision", "requester",
            "approver", "attestation", "evidence_reference", "artifact_version",
            "content_digest",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError("FINGERPRINT_FIELD_INVALID")
            if len(value) > _MAX_FIELD_BYTES:
                raise ValueError("FINGERPRINT_FIELD_TOO_LARGE")
            if "\0" in value:
                raise ValueError("FINGERPRINT_FIELD_INVALID")
            try:
                encoded = value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise ValueError("FINGERPRINT_FIELD_INVALID") from exc
            if len(encoded) > _MAX_FIELD_BYTES:
                raise ValueError("FINGERPRINT_FIELD_TOO_LARGE")

        if not _CANONICAL_UUID.fullmatch(self.target_revision):
            raise ValueError("FINGERPRINT_UUID_INVALID")
        if not _CANONICAL_UUID.fullmatch(self.attestation):
            raise ValueError("FINGERPRINT_UUID_INVALID")
        if not _SHA256_HEX.fullmatch(self.content_digest):
            raise ValueError("FINGERPRINT_DIGEST_INVALID")

        if (type(self.expected_version) is not int
                or not 0 <= self.expected_version <= _MAX_SIGNED_BIGINT):
            raise ValueError("FINGERPRINT_VERSION_INVALID")
        rollback_version = self.requested_rollback_version
        if self.operation == "promote":
            if rollback_version is not None:
                raise ValueError("FINGERPRINT_ROLLBACK_VERSION_INVALID")
        elif (type(rollback_version) is not int or not 1 <= rollback_version <= _MAX_SIGNED_BIGINT
              or rollback_version >= self.expected_version):
            raise ValueError("FINGERPRINT_ROLLBACK_VERSION_INVALID")


def promotion_request_fingerprint_bytes_v1(
    request: PromotionRequestFingerprintV1,
) -> bytes:
    """Return the v1 domain-separated, length-prefixed canonical request bytes."""
    if type(request) is not PromotionRequestFingerprintV1:
        raise ValueError("FINGERPRINT_REQUEST_INVALID")

    values: tuple[str | None, ...] = (
        request.tenant,
        request.source,
        request.company,
        request.model,
        request.operation,
        (None if request.requested_rollback_version is None
         else str(request.requested_rollback_version)),
        str(request.expected_version),
        request.target_revision,
        request.requester,
        request.approver,
        request.attestation,
        request.evidence_reference,
        request.artifact_version,
        request.content_digest,
    )
    framed = bytearray(_DOMAIN)
    for value in values:
        if value is None:
            framed.extend(b"0")
            continue
        encoded = value.encode("utf-8", errors="strict")
        framed.extend(b"1")
        framed.extend(str(len(encoded)).encode("ascii"))
        framed.extend(b":")
        framed.extend(encoded)
        if len(framed) > _MAX_FINGERPRINT_BYTES:
            raise ValueError("FINGERPRINT_TOO_LARGE")
    return bytes(framed)


def promotion_request_fingerprint_sha256_v1(
    request: PromotionRequestFingerprintV1,
) -> str:
    """Return the lowercase SHA-256 digest of the canonical v1 framing."""
    return hashlib.sha256(promotion_request_fingerprint_bytes_v1(request)).hexdigest()
