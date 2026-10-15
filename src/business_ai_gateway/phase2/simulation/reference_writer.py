"""Reference writer for the simulation (workstream P4, closes F-01 in simulation).

Offline and pure (stdlib only). ``ReferenceWriter`` sends EXACTLY the approved payload bytes to a ``SimulatedOneC``
and accepts the write as successful only when a signed receipt over the clone's received-bytes digest verifies under
the trusted key and that digest equals the approved digest. Every other outcome is an explicit non-success status;
there is no silent success path.

Outcomes (``WriteStatus``)
* ``APPLIED_VERIFIED``  - clone applied, receipt signature valid, received digest == approved digest.
* ``TAMPER_DETECTED``   - the clone's received digest differs from the approved digest (bad transport). The write
  may or may not have been applied; the caller must treat the target as needing reconciliation.
* ``RECEIPT_INVALID``   - clone reported success but the receipt does not verify or binds other values.
* ``REJECTED``          - definite refusal by the clone (``code`` carries the reason, e.g. ``STALE_VERSION``).
* ``UNKNOWN_TIMEOUT`` / ``UNKNOWN_CRASH`` - outcome unknown to the caller; never retried or reported as success.

A pre-send digest mismatch raises ``ApprovedDigestMismatch`` and nothing is sent.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..change.types import ChangeKind
from .attestation import SimulatedAttestor, verify_attestation
from .clone_1c import ApplyResult, CloneCrash, CloneRejected, CloneTimeout, SimulatedOneC

__all__ = ["ApprovedDigestMismatch", "ReferenceWriter", "WriteOutcome", "WriteStatus"]

_HEX64: Final = re.compile(r"[0-9a-f]{64}")


class ApprovedDigestMismatch(Exception):
    """sha256(payload bytes) differs from the approved digest; raised BEFORE anything is sent."""

    def __init__(self) -> None:
        super().__init__("APPROVED_DIGEST_MISMATCH")
        self.code = "APPROVED_DIGEST_MISMATCH"


class WriteStatus(StrEnum):
    APPLIED_VERIFIED = "APPLIED_VERIFIED"
    TAMPER_DETECTED = "TAMPER_DETECTED"
    RECEIPT_INVALID = "RECEIPT_INVALID"
    REJECTED = "REJECTED"
    UNKNOWN_TIMEOUT = "UNKNOWN_TIMEOUT"
    UNKNOWN_CRASH = "UNKNOWN_CRASH"


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    status: WriteStatus
    code: str
    approved_payload_sha256: str
    received_payload_sha256: str | None = None
    new_version: str | None = None
    receipt: dict[str, object] | None = None

    @property
    def success(self) -> bool:
        return self.status is WriteStatus.APPLIED_VERIFIED


class ReferenceWriter:
    """Sends approved bytes to the simulated clone and verifies the signed receipt (see module docstring)."""

    def __init__(self, clone: SimulatedOneC, attestor: SimulatedAttestor,
                 trusted_public_key_hex: str | None = None) -> None:
        self._clone = clone
        self._attestor = attestor
        self._trusted_key = trusted_public_key_hex if trusted_public_key_hex is not None else attestor.public_key_hex

    def write(self, change_id: str, generation: int, kind: ChangeKind, payload_bytes: bytes,
              approved_payload_sha256: str, target_ref: str | None, expected_version: str | None) -> WriteOutcome:
        if (not isinstance(payload_bytes, (bytes, bytearray)) or type(approved_payload_sha256) is not str
                or _HEX64.fullmatch(approved_payload_sha256) is None):
            raise ApprovedDigestMismatch()
        data = bytes(payload_bytes)
        if hashlib.sha256(data).hexdigest() != approved_payload_sha256:
            raise ApprovedDigestMismatch()
        approved = approved_payload_sha256
        try:
            result = self._clone.apply(kind, data, target_ref, expected_version)
        except CloneTimeout:
            return WriteOutcome(WriteStatus.UNKNOWN_TIMEOUT, "TIMEOUT", approved)
        except CloneCrash:
            return WriteOutcome(WriteStatus.UNKNOWN_CRASH, "CRASH", approved)
        except CloneRejected as exc:
            received = exc.received_payload_sha256
            if received is not None and received != approved:
                return WriteOutcome(WriteStatus.TAMPER_DETECTED, "RECEIVED_DIGEST_MISMATCH", approved, received)
            return WriteOutcome(WriteStatus.REJECTED, exc.code, approved, received)
        return self._verify(change_id, generation, result, approved)

    def _verify(self, change_id: str, generation: int, result: ApplyResult, approved: str) -> WriteOutcome:
        received = result.received_payload_sha256
        try:
            receipt = self._attestor.receipt_attestation(change_id, generation, received, result.new_version)
        except ValueError:
            return WriteOutcome(WriteStatus.RECEIPT_INVALID, "RECEIPT_UNOBTAINABLE", approved, received)
        if not verify_attestation(self._trusted_key, receipt):
            return WriteOutcome(WriteStatus.RECEIPT_INVALID, "RECEIPT_SIGNATURE_INVALID", approved, received,
                                None, receipt)
        if (receipt.get("received_payload_sha256") != received or receipt.get("new_version") != result.new_version
                or receipt.get("change_id") != change_id or receipt.get("generation") != generation):
            return WriteOutcome(WriteStatus.RECEIPT_INVALID, "RECEIPT_BINDING_MISMATCH", approved, received,
                                None, receipt)
        if received != approved:
            return WriteOutcome(WriteStatus.TAMPER_DETECTED, "RECEIVED_DIGEST_MISMATCH", approved, received,
                                result.new_version, receipt)
        return WriteOutcome(WriteStatus.APPLIED_VERIFIED, "OK", approved, received, result.new_version, receipt)
