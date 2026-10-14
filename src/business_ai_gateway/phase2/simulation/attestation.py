"""Synthetic Ed25519 attestor for simulation scenarios (TEST lane only).

Offline and pure (stdlib only). ``SimulatedAttestor`` holds a synthetic seed (SHA-256 of a label) and signs the
canonical JSON (``canonical_json``, ASCII) of three attestation types: preview, state and receipt. The signed body
is every field except ``signature`` and ``public_key``; ``verify_attestation`` additionally requires the embedded
``public_key`` to equal the key it is asked to verify against and ``key_id`` to be derived from that key.
The signer is the stdlib reference implementation (not audited, not constant-time): synthetic keys only.
"""
from __future__ import annotations

import hashlib
import re
from typing import Final

from ..change.proposal import canonical_json
from ..change.types import is_identity_text
from ..ed25519 import public_key_from_seed, sign, verify

__all__ = ["SimulatedAttestor", "key_id_of", "verify_attestation"]

LANE: Final = "TEST"
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_UNSIGNED_FIELDS: Final = frozenset({"signature", "public_key"})
_TYPES: Final = {
    "PREVIEW": ("change_id", "target_ref", "target_version", "preview_sha256"),
    "STATE": ("change_id", "target_ref", "target_version", "business_state_digest"),
    "RECEIPT": ("change_id", "generation", "received_payload_sha256", "new_version"),
}


def key_id_of(public_key_hex: str) -> str:
    return "sim-key-" + hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()[:16]


def _digest(value: object) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError("ATTESTATION_FIELD_INVALID")
    return value


def _ident(value: object) -> str:
    if not is_identity_text(value):
        raise ValueError("ATTESTATION_FIELD_INVALID")
    return value  # type: ignore[return-value]


def _message(attestation: dict[str, object]) -> bytes:
    body = {k: v for k, v in attestation.items() if k not in _UNSIGNED_FIELDS}
    return canonical_json(body).encode("ascii")


class SimulatedAttestor:
    """A synthetic signer: seed = SHA-256 of ``label``; distinct labels give distinct keys."""

    def __init__(self, label: str = "SIM-ATTESTOR-A") -> None:
        if not is_identity_text(label):
            raise ValueError("ATTESTOR_LABEL_INVALID")
        self.label = label
        self._seed = hashlib.sha256(label.encode("ascii")).digest()
        self.public_key_hex = public_key_from_seed(self._seed).hex()
        self.key_id = key_id_of(self.public_key_hex)

    def _signed(self, kind: str, fields: dict[str, object]) -> dict[str, object]:
        attestation: dict[str, object] = {"type": kind, "lane": LANE, "key_id": self.key_id, **fields}
        attestation["signature"] = sign(self._seed, _message(attestation)).hex()
        attestation["public_key"] = self.public_key_hex
        return attestation

    def preview_attestation(self, change_id: str, target_ref: str | None, target_version: str | None,
                            preview_sha256: str) -> dict[str, object]:
        return self._signed("PREVIEW", {
            "change_id": _ident(change_id), "target_ref": _opt_ident(target_ref),
            "target_version": _opt_ident(target_version), "preview_sha256": _digest(preview_sha256)})

    def state_attestation(self, change_id: str, target_ref: str, target_version: str,
                          business_state_digest: str) -> dict[str, object]:
        return self._signed("STATE", {
            "change_id": _ident(change_id), "target_ref": _ident(target_ref), "target_version": _ident(target_version),
            "business_state_digest": _digest(business_state_digest)})

    def receipt_attestation(self, change_id: str, generation: int, received_payload_sha256: str,
                            new_version: str) -> dict[str, object]:
        if type(generation) is not int or generation < 0:
            raise ValueError("ATTESTATION_FIELD_INVALID")
        return self._signed("RECEIPT", {
            "change_id": _ident(change_id), "generation": generation,
            "received_payload_sha256": _digest(received_payload_sha256), "new_version": _ident(new_version)})


def _opt_ident(value: object) -> str | None:
    return None if value is None else _ident(value)


def verify_attestation(public_key_hex: str, attestation: dict[str, object]) -> bool:
    """True only for a well-formed attestation whose signature verifies under ``public_key_hex``. Never raises."""
    try:
        if type(attestation) is not dict or type(public_key_hex) is not str:
            return False
        fields = _TYPES.get(attestation.get("type"))  # type: ignore[arg-type]
        if fields is None or set(attestation) != {"type", "lane", "key_id", "signature", "public_key", *fields}:
            return False
        if (attestation["lane"] != LANE or attestation["public_key"] != public_key_hex
                or attestation["key_id"] != key_id_of(public_key_hex)):
            return False
        signature = attestation["signature"]
        if type(signature) is not str:
            return False
        return verify(bytes.fromhex(public_key_hex), _message(attestation), bytes.fromhex(signature))
    except (ValueError, TypeError, KeyError):
        return False
