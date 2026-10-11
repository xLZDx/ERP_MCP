"""Configuration from the environment only. Token values are never stored in reprs or logs."""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SOURCE_ID = "onec-818ha-reference"
DEFAULT_A_URL = "http://127.0.0.1:21000/mcp"
DEFAULT_B_URL = "http://100.88.71.74:21000/mcp"
DEFAULT_MINT_SCRIPT = r"D:\1c\mcp\mint-token.ps1"


class TokenUnavailable(Exception):
    """No bearer token could be obtained; carries no token or path text."""


def _from_claude_json(path: Path, server_name: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TokenUnavailable("CLAUDE_JSON_UNREADABLE") from exc

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
    except (KeyError, TypeError, IndexError) as exc:
        raise TokenUnavailable("CLAUDE_JSON_SERVER_NOT_FOUND") from exc
    if not token:
        raise TokenUnavailable("CLAUDE_JSON_SERVER_NOT_FOUND")
    return token


def _from_ssh_mint(target: str, script: str) -> str:
    # Fixed argument vector, no shell. The script prints only the token to stdout.
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", target,
             f"powershell -NoProfile -ExecutionPolicy Bypass -File {script}"],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TokenUnavailable("TOKEN_MINT_FAILED") from exc
    token = done.stdout.strip()
    if not token:
        raise TokenUnavailable("TOKEN_MINT_FAILED")
    return token


@dataclass(frozen=True)
class GatewayConfig:
    label: str
    url: str
    token_provider: Callable[[], str] | None = field(default=None, repr=False)

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


def _provider(env: Mapping[str, str], prefix: str, claude_json: Path) -> Callable[[], str] | None:
    direct = env.get(f"{prefix}_TOKEN")
    if direct:
        return lambda: direct
    server = env.get(f"{prefix}_CLAUDE_JSON_SERVER")
    if server:
        return lambda: _from_claude_json(claude_json, server)
    target = env.get(f"{prefix}_MINT_SSH_TARGET")
    if target:
        script = env.get(f"{prefix}_MINT_SCRIPT", DEFAULT_MINT_SCRIPT)
        return lambda: _from_ssh_mint(target, script)
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
