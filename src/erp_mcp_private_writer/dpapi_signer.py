"""Fail-closed Ed25519 signer backed by a Windows CurrentUser DPAPI blob.

This primitive is for the separately hosted private disposable-writer boundary. It does not
generate keys, register public keys, establish signer identity, or make a test key production
approved. The caller must pin the registered public key and keep the blob accessible only to the
dedicated writer account. Private seed bytes are decrypted only for one operation and are never
stored on the signer instance or included in errors/repr.
"""

from __future__ import annotations

import hmac
from pathlib import Path
from types import MappingProxyType

_SEED_BYTES = 32
_PUBLIC_KEY_BYTES = 32
_MAX_SIGNING_MESSAGE_BYTES = 2 * 1024 * 1024
_ROLE_MESSAGE_PREFIXES = MappingProxyType({
    "writer_receipt": (
        b"ERP_MCP_R2:S12:DISPATCH-RECEIPT:v1\n",
        b"ERP_MCP_R2:S13:PHYSICAL-WRITER-BARRIER:v1\n",
    ),
    "verification_worker": (
        b"ERP_MCP_R2:S12:OUTCOME-EVIDENCE:v1\n",
        b"ERP_MCP_R2:S12:OUTCOME-EVIDENCE:v2\n",
    ),
    "completion_supervisor": (
        b"ERP_MCP_R2:S12:COMPLETION-PROOF:v1\n",
        b"ERP_MCP_R2:S13:POST-COMPLETION-CHALLENGE:v1\n",
    ),
    "read_attestor": (b"ERP_MCP_R2:S13:POST-COMPLETION-READ-ATTESTATION:v1\n",),
    # S13 uses one separately registered key for checkpoint envelopes and permit signatures.
    "checkpoint_signer": (
        b"change-ledger-checkpoint|v2|",
        b"change-ledger-permit|v1|",
    ),
})


class DpapiSignerError(RuntimeError):
    """Stable signer errors that never expose DPAPI, file, or cryptographic details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def verify_ed25519(*, public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify raw Ed25519 bytes with the audited cryptography backend; malformed input is false."""
    if (type(public_key) is not bytes or len(public_key) != _PUBLIC_KEY_BYTES
            or type(message) is not bytes or not message or len(message) > _MAX_SIGNING_MESSAGE_BYTES
            or type(signature) is not bytes or len(signature) != 64):
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except Exception:
        return False


class WindowsDpapiEd25519Signer:
    """Sign bytes with one pinned Ed25519 key protected by CurrentUser DPAPI.

    ``protected_seed_path`` contains only the DPAPI-protected 32-byte Ed25519 seed. The expected
    public key must come from the trusted, scope-appropriate key registry; deriving a different
    public key from the blob causes a refusal before any signature is returned. This class is
    inert until ``sign`` is called and cannot be used off Windows.
    """

    __slots__ = (
        "_key_id",
        "_key_version",
        "_protected_seed_path",
        "_public_key_bytes",
        "_signer_role",
    )

    def __init__(self, *, key_id: str, key_version: str, signer_role: str,
                 protected_seed_path: Path, expected_public_key: bytes) -> None:
        if (type(key_id) is not str or not key_id or key_id != key_id.strip()
                or len(key_id) > 128
                or type(key_version) is not str or not key_version
                or key_version != key_version.strip() or len(key_version) > 64
                or type(signer_role) is not str or signer_role not in _ROLE_MESSAGE_PREFIXES
                or not isinstance(protected_seed_path, Path)
                or not protected_seed_path.is_absolute()
                or type(expected_public_key) is not bytes
                or len(expected_public_key) != _PUBLIC_KEY_BYTES):
            raise DpapiSignerError("SIGNER_CONFIGURATION_INVALID")
        self._key_id = key_id
        self._key_version = key_version
        self._signer_role = signer_role
        self._protected_seed_path = protected_seed_path
        self._public_key_bytes = expected_public_key

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("SIGNER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SIGNER_CONFIGURATION_IMMUTABLE")

    def __repr__(self) -> str:
        return "WindowsDpapiEd25519Signer(<redacted>)"

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def key_version(self) -> str:
        return self._key_version

    @property
    def signer_role(self) -> str:
        return self._signer_role

    @property
    def public_key_bytes(self) -> bytes:
        """Return the pinned public key; this does not read or decrypt the private blob."""
        return self._public_key_bytes

    def sign(self, message: bytes) -> bytes:
        if type(message) is not bytes or not message or len(message) > _MAX_SIGNING_MESSAGE_BYTES:
            raise DpapiSignerError("SIGNER_MESSAGE_INVALID")
        if not any(message.startswith(prefix) for prefix in _ROLE_MESSAGE_PREFIXES[self._signer_role]):
            raise DpapiSignerError("SIGNER_DOMAIN_REFUSED")
        seed = self._unprotect_seed()
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            private_key = Ed25519PrivateKey.from_private_bytes(seed)
            public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            if not hmac.compare_digest(public_key, self._public_key_bytes):
                raise DpapiSignerError("SIGNER_KEY_MISMATCH")
            signature = private_key.sign(message)
            if type(signature) is not bytes or len(signature) != 64:
                raise DpapiSignerError("SIGNER_OUTPUT_INVALID")
            return signature
        except DpapiSignerError:
            raise
        except Exception:
            raise DpapiSignerError("SIGNER_OPERATION_FAILED") from None
        finally:
            # Python cannot guarantee zeroization of immutable byte objects. Keep lifetime local
            # to this call and never retain either the seed or private-key object on the instance.
            seed = b""

    def _unprotect_seed(self) -> bytes:
        try:
            if not self._protected_seed_path.is_file():
                raise DpapiSignerError("SIGNER_KEY_UNAVAILABLE")
            with self._protected_seed_path.open("rb") as source:
                protected = source.read(64 * 1024 + 1)
            if not protected or len(protected) > 64 * 1024:
                raise DpapiSignerError("SIGNER_KEY_UNAVAILABLE")
            import win32crypt

            result = win32crypt.CryptUnprotectData(protected, None, None, None, 0)
            seed = result[1] if type(result) is tuple and len(result) == 2 else None
            if type(seed) is not bytes or len(seed) != _SEED_BYTES:
                raise DpapiSignerError("SIGNER_KEY_UNAVAILABLE")
            return seed
        except DpapiSignerError:
            raise
        except Exception:
            raise DpapiSignerError("SIGNER_KEY_UNAVAILABLE") from None
