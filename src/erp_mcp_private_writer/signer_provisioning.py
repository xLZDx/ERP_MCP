"""Create a CurrentUser-DPAPI-protected Ed25519 seed for the private writer host.

Run this only while logged in as the dedicated Windows service account on its authorized host.
The encrypted blob is account-bound, but any process under that account can unprotect it. This
helper does not establish host/service identity, set file ACLs, register a public key, or approve a
role/scope/validity window. The caller must use an account-private directory that is not
concurrently writable by an untrusted process, and submit the returned public key through the
separately reviewed S13 registry workflow. Private bytes exist transiently in process memory;
Python cannot guarantee their zeroization.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


_SEED_BYTES = 32
_PUBLIC_KEY_BYTES = 32
_MAX_PROTECTED_BLOB_BYTES = 64 * 1024
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SignerProvisioningError(RuntimeError):
    """Stable provisioning failures that do not expose cryptographic or filesystem details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProvisionedEd25519PublicKey:
    """Public result only; the private seed is never returned by the provisioning API."""

    protected_seed_path: Path
    public_key_bytes: bytes
    public_key_sha256: str


def provision_windows_dpapi_ed25519_key(
    protected_seed_path: Path,
) -> ProvisionedEd25519PublicKey:
    """Create a new Ed25519 key and exclusively persist only its CurrentUser DPAPI blob.

    The destination must be an absolute path whose parent already exists in the dedicated
    service account's private configuration directory, which the caller keeps from concurrent
    untrusted modification. Existing files are never overwritten.
    This function emits no key material and has no registry or database side effects.
    """
    if sys.platform != "win32":
        raise SignerProvisioningError("SIGNER_PROVISIONING_PLATFORM_UNSUPPORTED")
    if (not isinstance(protected_seed_path, Path)
            or not protected_seed_path.is_absolute()
            or not protected_seed_path.parent.is_dir()):
        raise SignerProvisioningError("SIGNER_PROVISIONING_PATH_INVALID")

    try:
        import win32crypt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except Exception:
        raise SignerProvisioningError("SIGNER_PROVISIONING_DEPENDENCY_UNAVAILABLE") from None

    seed = b""
    private_key = None
    completed = False
    temporary_path: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    descriptor: int | None = None
    try:
        private_key = Ed25519PrivateKey.generate()
        seed = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        if (type(seed) is not bytes or len(seed) != _SEED_BYTES
                or type(public_key) is not bytes or len(public_key) != _PUBLIC_KEY_BYTES):
            raise SignerProvisioningError("SIGNER_PROVISIONING_OUTPUT_INVALID")

        protected = win32crypt.CryptProtectData(
            seed,
            "ERP_MCP private writer Ed25519 seed",
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
        )
        # pywin32 CryptProtectData returns the protected bytes directly. Its unprotect
        # counterpart returns (description, plaintext), but accepting that tuple shape here
        # could accidentally persist a description as if it were a DPAPI blob.
        if (type(protected) is not bytes or not protected
                or len(protected) > _MAX_PROTECTED_BLOB_BYTES):
            raise SignerProvisioningError("SIGNER_PROVISIONING_OUTPUT_INVALID")

        # Refuse to publish a key that this account cannot immediately recover. This proves
        # only the current-user DPAPI round trip; it does not establish that the intended service
        # account, host identity, parent ACL, or registry scope is correct.
        try:
            unprotected = win32crypt.CryptUnprotectData(protected, None, None, None, 0)
        except Exception:
            raise SignerProvisioningError("SIGNER_PROVISIONING_ROUNDTRIP_FAILED") from None
        recovered_seed = unprotected[1] if type(unprotected) is tuple and len(unprotected) == 2 else None
        if (type(recovered_seed) is not bytes
                or not hmac.compare_digest(recovered_seed, seed)):
            raise SignerProvisioningError("SIGNER_PROVISIONING_ROUNDTRIP_FAILED")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{protected_seed_path.name}.",
            suffix=".pending",
            dir=protected_seed_path.parent,
        )
        temporary_path = Path(temporary_name)
        temporary_stat = os.fstat(descriptor)
        if not temporary_stat.st_ino:
            raise SignerProvisioningError("SIGNER_PROVISIONING_FILE_ID_UNAVAILABLE")
        temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            view = memoryview(protected)
            written = 0
            while written < len(view):
                count = destination.write(view[written:])
                if not count:
                    raise OSError("short write")
                written += count
            destination.flush()
            os.fsync(destination.fileno())

        # On Windows, rename fails when the destination already exists; it does not replace it.
        # Keeping the temporary file beside the destination also keeps publication on one volume.
        os.rename(temporary_path, protected_seed_path)
        published_stat = protected_seed_path.stat()
        if (published_stat.st_dev, published_stat.st_ino) != temporary_identity:
            raise SignerProvisioningError("SIGNER_PROVISIONING_PUBLICATION_CONFLICT")
        temporary_path = None

        result = ProvisionedEd25519PublicKey(
            protected_seed_path=protected_seed_path,
            public_key_bytes=public_key,
            public_key_sha256=hashlib.sha256(public_key).hexdigest(),
        )
        completed = True
        return result
    except SignerProvisioningError:
        raise
    except FileExistsError:
        raise SignerProvisioningError("SIGNER_PROVISIONING_DESTINATION_EXISTS") from None
    except Exception:
        raise SignerProvisioningError("SIGNER_PROVISIONING_FAILED") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_stat = temporary_path.stat()
                if (temporary_identity is None
                        or (temporary_stat.st_dev, temporary_stat.st_ino) == temporary_identity):
                    temporary_path.unlink()
            except OSError:
                pass
        if not completed and temporary_identity is not None:
            try:
                published_stat = protected_seed_path.stat()
                if (published_stat.st_dev, published_stat.st_ino) == temporary_identity:
                    protected_seed_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        seed = b""
        recovered_seed = b""
        private_key = None


__all__ = [
    "ProvisionedEd25519PublicKey",
    "SignerProvisioningError",
    "provision_windows_dpapi_ed25519_key",
]
