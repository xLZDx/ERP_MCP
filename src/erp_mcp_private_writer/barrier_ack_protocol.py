"""Canonical validation and signature verification for S13 physical barrier acknowledgements.

The signed-message shape follows ``BarrierAcknowledgement.signature_preimage`` and the candidate
writer-barrier registry contract. This module does not load trust, attest a process, or persist an
acknowledgement; callers must perform those checks independently.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from uuid import UUID

from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement
from business_ai_gateway.phase2.change_ledger.uuid_contract import (
    is_canonical_nonzero_uuid,
    is_canonical_process_instance_uuid,
)

from .dpapi_signer import verify_ed25519


_DOMAIN = b"ERP_MCP_R2:S13:PHYSICAL-WRITER-BARRIER:v1\n"
_REFERENCE_DOMAIN = b"ERP_MCP_R2:S13:PHYSICAL-WRITER-BARRIER-REF:v1\n"
_MAX_SIGNED_BYTES = 2 * 1024 * 1024
_MAX_BIGINT = 9_223_372_036_854_775_807
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z",
)


class BarrierAcknowledgementProtocolError(ValueError):
    """Stable refusal for malformed or non-canonical acknowledgement data."""

    def __init__(self) -> None:
        super().__init__("BARRIER_ACK_PROTOCOL_INVALID")


def _valid_text(value: object, maximum: int) -> bool:
    return (type(value) is str and bool(value) and value == value.strip()
            and len(value) <= maximum
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def validate_barrier_acknowledgement(ack: BarrierAcknowledgement) -> None:
    """Reject values outside the exact S13 signed-message contract before crypto or SQL."""
    if type(ack) is not BarrierAcknowledgement:
        raise BarrierAcknowledgementProtocolError()
    if (not _valid_text(ack.base_fingerprint, 64)
            or _FINGERPRINT.fullmatch(ack.base_fingerprint) is None
            or not _valid_text(ack.tenant_id, 512)
            or not _valid_text(ack.company_id, 512)
            or type(ack.barrier_id) is not UUID
            or not is_canonical_nonzero_uuid(str(ack.barrier_id))):
        raise BarrierAcknowledgementProtocolError()
    for value, limit in (
        (ack.barrier_origin_instance_id, 36),
        (ack.key_id, 128), (ack.key_version, 64),
        (ack.writer_service_id, 512), (ack.writer_host_id, 512),
        (ack.host_boot_id, 36), (ack.writer_process_instance_id, 36),
        (ack.process_attestation_ref, 512),
    ):
        if not _valid_text(value, limit):
            raise BarrierAcknowledgementProtocolError()
    if (not is_canonical_process_instance_uuid(ack.barrier_origin_instance_id)
            or not is_canonical_process_instance_uuid(ack.host_boot_id)
            or not is_canonical_process_instance_uuid(ack.writer_process_instance_id)):
        raise BarrierAcknowledgementProtocolError()
    if ack.process_attestation_ref != ack.writer_process_instance_id:
        raise BarrierAcknowledgementProtocolError()
    for number in (ack.lifecycle_epoch, ack.barrier_origin_service_epoch,
                   ack.writer_queue_epoch):
        if type(number) is not int or not 1 <= number <= _MAX_BIGINT:
            raise BarrierAcknowledgementProtocolError()
    if ack.local_queue_closed is not True:
        raise BarrierAcknowledgementProtocolError()
    if (type(ack.call_ids) is not tuple
            or len(ack.call_ids) > _MAX_SIGNED_BYTES // 40
            or any(not is_canonical_nonzero_uuid(call_id) for call_id in ack.call_ids)
            or ack.call_ids != tuple(sorted(set(ack.call_ids)))):
        raise BarrierAcknowledgementProtocolError()
    if (type(ack.signed_at) is not str
            or _UTC_TIMESTAMP.fullmatch(ack.signed_at) is None):
        raise BarrierAcknowledgementProtocolError()
    try:
        datetime.strptime(ack.signed_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise BarrierAcknowledgementProtocolError() from None
    if type(ack.signature) is not bytes or len(ack.signature) != 64:
        raise BarrierAcknowledgementProtocolError()
    signed_bytes = ack.signature_preimage()
    if (type(signed_bytes) is not bytes or not signed_bytes.startswith(_DOMAIN)
            or len(signed_bytes) > _MAX_SIGNED_BYTES):
        raise BarrierAcknowledgementProtocolError()


def barrier_acknowledgement_signed_bytes(ack: BarrierAcknowledgement) -> bytes:
    """Return the exact domain-prefixed canonical JSON message signed by Ed25519."""
    validate_barrier_acknowledgement(ack)
    return ack.signature_preimage()


def barrier_acknowledgement_ref(ack: BarrierAcknowledgement) -> str:
    """Derive a stable, versioned ref from length-framed signed bytes and signer identity."""
    message = barrier_acknowledgement_signed_bytes(ack)
    parts = (message, ack.signature, ack.key_id.encode("utf-8"),
             ack.key_version.encode("utf-8"))
    framed = bytearray(_REFERENCE_DOMAIN)
    for part in parts:
        framed.extend(len(part).to_bytes(4, "big", signed=False))
        framed.extend(part)
    return "barrier-ack:v1:" + hashlib.sha256(framed).hexdigest()


def barrier_acknowledgement_record_json(ack: BarrierAcknowledgement) -> str:
    """Serialize the exact PostgreSQL composite input shape used by trust and registry routines."""
    validate_barrier_acknowledgement(ack)
    return json.dumps({
        "base_fingerprint": ack.base_fingerprint,
        "scope": {"tenant_id": ack.tenant_id, "company_id": ack.company_id},
        "lifecycle_epoch": ack.lifecycle_epoch,
        "barrier_id": str(ack.barrier_id),
        "barrier_origin_instance_id": ack.barrier_origin_instance_id,
        "barrier_origin_service_epoch": ack.barrier_origin_service_epoch,
        "call_ids": list(ack.call_ids),
        "key_id": ack.key_id,
        "key_version": ack.key_version,
        "writer_service_id": ack.writer_service_id,
        "writer_host_id": ack.writer_host_id,
        "host_boot_id": ack.host_boot_id,
        "writer_process_instance_id": ack.writer_process_instance_id,
        "process_attestation_ref": ack.process_attestation_ref,
        "writer_queue_epoch": ack.writer_queue_epoch,
        "local_queue_closed": ack.local_queue_closed,
        "signed_at": ack.signed_at,
        "signature": "\\x" + ack.signature.hex(),
    }, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def verify_barrier_acknowledgement_signature(
        ack: BarrierAcknowledgement, public_key: bytes) -> bool:
    """Verify only the cryptographic signature; trust and persistence remain separate gates."""
    try:
        signed_bytes = barrier_acknowledgement_signed_bytes(ack)
    except BarrierAcknowledgementProtocolError:
        return False
    return verify_ed25519(
        public_key=public_key,
        message=signed_bytes,
        signature=ack.signature,
    )


__all__ = [
    "BarrierAcknowledgementProtocolError",
    "barrier_acknowledgement_record_json",
    "barrier_acknowledgement_ref",
    "barrier_acknowledgement_signed_bytes",
    "validate_barrier_acknowledgement",
    "verify_barrier_acknowledgement_signature",
]
