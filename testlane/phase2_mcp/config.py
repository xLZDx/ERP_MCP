"""Configuration from the environment only. Token values are never stored in reprs or logs."""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SOURCE_ID = "onec-818ha-reference"
DEFAULT_A_URL = "http://127.0.0.1:21000/mcp"
DEFAULT_B_URL = "http://100.88.71.74:21000/mcp"
DEFAULT_IVAN_SSH_TARGET = "koros@100.88.71.74"
DEFAULT_IVAN_MINT_SCRIPT = r"D:\1c\mcp\mint-token.ps1"
TOKEN_TTL_SECONDS = 3600


@dataclass(frozen=True)
class TokenCredential:
    """Short-lived token held only in process memory, with its refresh interval."""

    access_token: str = field(repr=False)
    expires_in: int = TOKEN_TTL_SECONDS


class TokenUnavailable(Exception):
    """No bearer token could be obtained; carries no token or path text."""


def _from_claude_json(path: Path, server_name: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TokenUnavailable("CLAUDE_JSON_UNREADABLE") from None

    def find(node: object) -> object | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == server_name and isinstance(value, dict):
                    return value
                found = find(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find(item)
                if found is not None:
                    return found
        return None

    entry = find(data)
    try:
        header = entry["headers"]["Authorization"]  # type: ignore[index]
        token = str(header).split()[-1]
    except (KeyError, TypeError, IndexError):
        raise TokenUnavailable("CLAUDE_JSON_SERVER_NOT_FOUND") from None
    if not token:
        raise TokenUnavailable("CLAUDE_JSON_SERVER_NOT_FOUND")
    return token


def _from_ssh_mint(target: str, script: str = DEFAULT_IVAN_MINT_SCRIPT) -> TokenCredential:
    # Pin the operator-approved host/account and fixed remote command. Strict SSH host-key
    # verification uses the user's known_hosts file; no remote script path comes from env.
    if target != DEFAULT_IVAN_SSH_TARGET:
        raise TokenUnavailable("TOKEN_MINT_TARGET_REJECTED")
    if script != DEFAULT_IVAN_MINT_SCRIPT:
        raise TokenUnavailable("TOKEN_MINT_SCRIPT_REJECTED")
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
             "-o", "IdentitiesOnly=yes", target,
             ("powershell -NoProfile -ExecutionPolicy Bypass -File "
              "D:\\1c\\mcp\\mint-token.ps1 -Ttl 3600")],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # CalledProcessError and TimeoutExpired can retain captured stdout, which is the token.
        raise TokenUnavailable("TOKEN_MINT_FAILED") from None
    token = done.stdout.strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise TokenUnavailable("TOKEN_MINT_FAILED")
    return TokenCredential(token, TOKEN_TTL_SECONDS)


def _from_local_idp() -> TokenCredential:
    # Load the lane's existing secret provider in-process. Neither the token nor the
    # LaneEnv values are included in exceptions, reprs, or logs.
    try:
        from scripts.real1c.gateway_client import Idp, LaneEnv

        token = Idp(LaneEnv.load()).token("auditor", ttl=TOKEN_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - expose only a fixed credential error
        raise TokenUnavailable("LOCAL_TOKEN_MINT_FAILED") from None
    if not token:
        raise TokenUnavailable("LOCAL_TOKEN_MINT_FAILED")
    return TokenCredential(token, TOKEN_TTL_SECONDS)


@dataclass(frozen=True)
class GatewayConfig:
    label: str
    url: str
    token_provider: Callable[[], str | TokenCredential] | None = field(default=None, repr=False)

    @property
    def configured(self) -> bool:
        return self.token_provider is not None


@dataclass(frozen=True)
class ServerConfig:
    side_a: GatewayConfig
    side_b: GatewayConfig
    source_id: str
    host: str
    port: int
    inbound_token: str | None = field(default=None, repr=False)
    allowed_hosts: tuple[str, ...] = ()


def _provider(env: Mapping[str, str], prefix: str, claude_json: Path
              ) -> Callable[[], str | TokenCredential] | None:
    direct = env.get(f"{prefix}_TOKEN")
    if direct:
        return lambda: direct
    server = env.get(f"{prefix}_CLAUDE_JSON_SERVER")
    if server:
        return lambda: _from_claude_json(claude_json, server)
    target = env.get(f"{prefix}_MINT_SSH_TARGET")
    if target:
        script = env.get(f"{prefix}_MINT_SCRIPT", DEFAULT_IVAN_MINT_SCRIPT)
        return lambda: _from_ssh_mint(target, script)
    if f"{prefix}_MINT_SCRIPT" in env:
        raise TokenUnavailable("TOKEN_MINT_TARGET_REQUIRED")
    if prefix == "TESTLANE_A":
        return _from_local_idp
    if prefix == "TESTLANE_B":
        return lambda: _from_ssh_mint(DEFAULT_IVAN_SSH_TARGET)
    return None


def load_config(env: Mapping[str, str] | None = None) -> ServerConfig:
    env = os.environ if env is None else env
    claude_json = Path(env.get("TESTLANE_CLAUDE_JSON") or (Path.home() / ".claude.json"))
    hosts = tuple(h.strip() for h in env.get("TESTLANE_ALLOWED_HOSTS", "").split(",") if h.strip())
    try:
        port = int(env.get("TESTLANE_PORT", "21200"))
    except ValueError as exc:
        raise ValueError("TESTLANE_PORT_INVALID") from exc
    return ServerConfig(
        side_a=GatewayConfig("A", env.get("TESTLANE_A_URL", DEFAULT_A_URL),
                             _provider(env, "TESTLANE_A", claude_json)),
        side_b=GatewayConfig("B", env.get("TESTLANE_B_URL", DEFAULT_B_URL),
                             _provider(env, "TESTLANE_B", claude_json)),
        source_id=env.get("TESTLANE_SOURCE_ID", DEFAULT_SOURCE_ID),
        host=env.get("TESTLANE_HOST", "127.0.0.1"),
        port=port,
        inbound_token=env.get("TESTLANE_INBOUND_TOKEN") or None,
        allowed_hosts=hosts,
    )
