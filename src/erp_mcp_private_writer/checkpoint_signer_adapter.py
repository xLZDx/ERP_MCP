"""Adapter from raw DPAPI Ed25519 bytes to the checkpoint contract's hex representation.

This adapter is inert until ``sign`` is called. It does not register, provision, or approve a key.
"""
from __future__ import annotations

from .dpapi_signer import DpapiSignerError, WindowsDpapiEd25519Signer


class CheckpointSignerHexAdapter:
    """Expose only a checkpoint-role signer as lowercase hexadecimal signature text."""

    __slots__ = ("_signer",)
    is_test_double = False

    def __init__(self, signer: WindowsDpapiEd25519Signer) -> None:
        if (type(signer) is not WindowsDpapiEd25519Signer
                or signer.signer_role != "checkpoint_signer"):
            raise DpapiSignerError("SIGNER_CONFIGURATION_INVALID")
        self._signer = signer

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("SIGNER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SIGNER_CONFIGURATION_IMMUTABLE")

    def __repr__(self) -> str:
        return "CheckpointSignerHexAdapter(<redacted>)"

    @property
    def key_id(self) -> str:
        return self._signer.key_id

    @property
    def key_version(self) -> str:
        return self._signer.key_version

    def sign(self, payload: bytes) -> str:
        signature = self._signer.sign(payload)
        if type(signature) is not bytes or len(signature) != 64:
            raise DpapiSignerError("SIGNER_OUTPUT_INVALID")
        return signature.hex()


__all__ = ["CheckpointSignerHexAdapter"]
