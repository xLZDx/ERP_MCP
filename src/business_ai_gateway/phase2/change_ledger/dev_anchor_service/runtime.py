"""Windows CurrentUser-DPAPI runtime loader for the explicitly dev-only anchor process.

This loader never creates keys or prints tokens. Provision the two authority keys separately,
then set the non-secret public roots and protected-blob paths plus dev-only bearer tokens in the
service account environment before running ``python -m ...dev_anchor_service``.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from .service import (
    AnchorServiceError,
    DevAnchorConfig,
    DevAnchorSigner,
    KEY_AUTH_SIGNING_DOMAIN,
    LATESTNESS_SIGNING_DOMAIN,
    create_app,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[5]


def _required(name: str) -> str:
    value = os.environ.get(name)
    if type(value) is not str or not value or value != value.strip():
        raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
    return value


def _public_key(name: str) -> bytes:
    raw = _required(name)
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
    return bytes.fromhex(raw)


def _check_signer(signer: DevAnchorSigner, domain: bytes) -> None:
    """Prove the configured CurrentUser DPAPI blob is usable before serving health requests."""
    message = domain + b"\nruntime-self-check:" + secrets.token_bytes(32)
    try:
        signature = signer.sign(message)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(signer.public_key_bytes).verify(signature, message)
    except Exception:
        raise AnchorServiceError("ANCHOR_RUNTIME_SIGNER_UNAVAILABLE") from None


def load_dev_runtime():
    """Load protected signers/config and return a standalone ASGI app; never generate keys."""
    if sys.platform != "win32":
        raise AnchorServiceError("ANCHOR_RUNTIME_PLATFORM_UNSUPPORTED")
    if _required("ERP_MCP_DEV_ANCHOR_MODE") != "dev":
        raise AnchorServiceError("DEV_ONLY_REQUIRED")
    try:
        from erp_mcp_private_writer.dpapi_signer import WindowsDpapiEd25519Signer
    except Exception:
        raise AnchorServiceError("ANCHOR_RUNTIME_SIGNER_UNAVAILABLE") from None

    state_path_text = os.environ.get("ERP_MCP_DEV_ANCHOR_DB_PATH")
    if state_path_text is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
        database_path = Path(local_app_data) / "ERP_MCP" / "dev-anchor" / "anchor.sqlite3"
    else:
        database_path = Path(state_path_text)
    if not database_path.is_absolute():
        raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")

    latestness_key_id = _required("ERP_MCP_DEV_ANCHOR_LATEST_AUTHORITY_ID")
    latestness_public = _public_key("ERP_MCP_DEV_ANCHOR_LATEST_PUBLIC_KEY_HEX")
    key_authority_id = _required("ERP_MCP_DEV_ANCHOR_KEY_AUTHORITY_ID")
    key_authority_public = _public_key("ERP_MCP_DEV_ANCHOR_KEY_AUTHORITY_PUBLIC_KEY_HEX")
    latestness_signer = WindowsDpapiEd25519Signer(
        key_id=latestness_key_id,
        key_version="dev-v1",
        signer_role="checkpoint_latestness_authority",
        protected_seed_path=Path(_required("ERP_MCP_DEV_ANCHOR_LATEST_SEED_PATH")),
        expected_public_key=latestness_public,
    )
    key_authority_signer = WindowsDpapiEd25519Signer(
        key_id=key_authority_id,
        key_version="dev-v1",
        signer_role="checkpoint_key_authority",
        protected_seed_path=Path(_required("ERP_MCP_DEV_ANCHOR_KEY_AUTHORITY_SEED_PATH")),
        expected_public_key=key_authority_public,
    )
    if (not latestness_signer.public_key_bytes or not key_authority_signer.public_key_bytes
            or latestness_signer.signer_role != "checkpoint_latestness_authority"
            or key_authority_signer.signer_role != "checkpoint_key_authority"):
        raise AnchorServiceError("ANCHOR_RUNTIME_SIGNER_UNAVAILABLE")
    # The signer rejects any message outside its role prefix. These checks make a mismatched
    # DPAPI role/configuration fail at process startup rather than at the first checkpoint read.
    if (not LATESTNESS_SIGNING_DOMAIN.startswith(b"ERP_MCP:S13:ANCHOR-LATESTNESS")
            or not KEY_AUTH_SIGNING_DOMAIN.startswith(b"ERP_MCP:S13:ANCHOR-KEY-AUTH")):
        raise AnchorServiceError("ANCHOR_RUNTIME_SIGNER_UNAVAILABLE")
    _check_signer(latestness_signer, LATESTNESS_SIGNING_DOMAIN)
    _check_signer(key_authority_signer, KEY_AUTH_SIGNING_DOMAIN)

    config = DevAnchorConfig(
        service_id=os.environ.get("ERP_MCP_DEV_ANCHOR_SERVICE_ID", "erp-mcp-dev-anchor-local"),
        database_path=database_path,
        project_root=_PROJECT_ROOT,
        mode="dev",
        bind_host="127.0.0.1",
        bearer_token=_required("ERP_MCP_DEV_ANCHOR_BEARER_TOKEN"),
        admin_token=_required("ERP_MCP_DEV_ANCHOR_ADMIN_TOKEN"),
        latestness_authority_id=latestness_key_id,
        latestness_signer=latestness_signer,
        key_authority_id=key_authority_id,
        key_authority_signer=key_authority_signer,
    )
    return create_app(config)


def run_dev_runtime() -> None:
    """Run one service instance on IPv4 loopback; no key material/tokens are logged."""
    if _required("ERP_MCP_DEV_ANCHOR_MODE") != "dev":
        raise AnchorServiceError("DEV_ONLY_REQUIRED")
    port_text = os.environ.get("ERP_MCP_DEV_ANCHOR_PORT", "8194")
    if not port_text.isascii() or not port_text.isdigit():
        raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
    port = int(port_text)
    if not 1024 <= port <= 65535:
        raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
    state_path_text = os.environ.get("ERP_MCP_DEV_ANCHOR_DB_PATH")
    if state_path_text is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
        database_path = Path(local_app_data) / "ERP_MCP" / "dev-anchor" / "anchor.sqlite3"
    else:
        database_path = Path(state_path_text)
    if not database_path.is_absolute():
        raise AnchorServiceError("ANCHOR_RUNTIME_CONFIGURATION_INVALID")
    database_path = database_path.resolve()
    try:
        database_path.relative_to(_PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise AnchorServiceError("ANCHOR_STATE_MUST_BE_OUTSIDE_REPOSITORY")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = (database_path.with_suffix(database_path.suffix + ".instance.lock")).open("a+b")
    try:
        import msvcrt

        lock_handle.seek(0, os.SEEK_END)
        if lock_handle.tell() == 0:
            lock_handle.write(b"\0")
            lock_handle.flush()
        lock_handle.seek(0)
        try:
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise AnchorServiceError("ANCHOR_INSTANCE_ALREADY_RUNNING") from None
    except Exception:
        lock_handle.close()
        raise
    try:
        import uvicorn
    except Exception:
        lock_handle.close()
        raise AnchorServiceError("ANCHOR_RUNTIME_SERVER_UNAVAILABLE") from None
    try:
        uvicorn.run(load_dev_runtime(), host="127.0.0.1", port=port,
                    log_level="warning", access_log=False)
    finally:
        try:
            import msvcrt

            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        lock_handle.close()
