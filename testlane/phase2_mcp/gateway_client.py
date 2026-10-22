"""Minimal read-only MCP client for a Release 1 gateway (streamable HTTP, bearer token).

Errors are reduced to fixed codes: no URL, token, body or business text is ever carried.
Numbers are parsed straight into ``Decimal`` so no float rounding can enter a comparison.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any, Protocol

from .config import GatewayConfig, TokenCredential, TokenUnavailable


class GatewayError(Exception):
    """Failure with a fixed, safe code (never the underlying exception text)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GatewayPort(Protocol):
    label: str

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class Gateway:
    def __init__(self, config: GatewayConfig, timeout: float = 240.0) -> None:
        self.label = config.label
        self._config = config
        self._timeout = timeout
        self._token: str | None = None
        self._token_refresh_at: float | None = None
        self._sid: str | None = None

    def _bearer(self) -> str:
        if (self._token is None or (self._token_refresh_at is not None
                                    and time.monotonic() >= self._token_refresh_at)):
            if self._config.token_provider is None:
                raise GatewayError("GATEWAY_TOKEN_UNAVAILABLE")
            try:
                credential = self._config.token_provider()
            except TokenUnavailable as exc:
                raise GatewayError("GATEWAY_TOKEN_UNAVAILABLE") from exc
            if isinstance(credential, TokenCredential):
                if not credential.access_token or credential.expires_in <= 0:
                    raise GatewayError("GATEWAY_TOKEN_UNAVAILABLE")
                self._token = credential.access_token
                # Refresh before expiry so a live MCP session is not left holding an
                # expired bearer. Static legacy providers have no known expiry.
                self._token_refresh_at = time.monotonic() + max(1, credential.expires_in - 60)
            elif isinstance(credential, str) and credential:
                self._token = credential
                self._token_refresh_at = None
            else:
                raise GatewayError("GATEWAY_TOKEN_UNAVAILABLE")
        return self._token

    def _clear_auth(self) -> None:
        self._token = None
        self._token_refresh_at = None
        self._sid = None

    def _rpc(self, method: str, params: dict[str, Any], *, notify: bool = False) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = 1
        headers = {
            "Authorization": "Bearer " + self._bearer(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._sid:
            headers["Mcp-Session-Id"] = self._sid
        request = urllib.request.Request(
            self._config.url, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                self._sid = response.headers.get("Mcp-Session-Id") or self._sid
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self._clear_auth()
            else:
                self._sid = None
            if exc.code in (401, 403):
                raise GatewayError("GATEWAY_AUTH_REJECTED") from None
            raise GatewayError("GATEWAY_HTTP_ERROR") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            self._sid = None
            raise GatewayError("GATEWAY_UNREACHABLE") from None
        if notify:
            return None
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                break
        try:
            return json.loads(raw, parse_float=Decimal)
        except ValueError:
            raise GatewayError("GATEWAY_BAD_RESPONSE") from None

    def _ensure_session(self) -> None:
        if self._sid:
            return
        self._rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "phase2-testlane", "version": "0"},
        })
        self._rpc("notifications/initialized", {}, notify=True)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(2):
            try:
                self._ensure_session()
                reply = self._rpc("tools/call", {"name": tool, "arguments": arguments})
                break
            except GatewayError as exc:
                # All tools exposed by this test lane are read-only. Re-mint once after
                # token rejection; never loop indefinitely on a real authorization error.
                if exc.code != "GATEWAY_AUTH_REJECTED" or attempt:
                    raise
                self._clear_auth()
        if not isinstance(reply, dict) or "error" in reply:
            raise GatewayError("GATEWAY_RPC_ERROR")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise GatewayError("GATEWAY_BAD_RESPONSE")
        if result.get("isError"):
            raise GatewayError("GATEWAY_TOOL_ERROR")
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            raise GatewayError("GATEWAY_BAD_RESPONSE")
        return payload
