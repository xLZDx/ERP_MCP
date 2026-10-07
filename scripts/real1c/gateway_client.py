"""Thin clients for the isolated real-1C lane stack: IdP tokens, Admin API session (OIDC + CSRF) and MCP.

Mirrors the proven helpers in tests/e2e/conftest.py but is import-safe outside pytest.  Nothing here prints or
returns credentials; tokens stay in memory.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

DEFAULT_E2E_DIR = Path(r"D:\ERP_MCP_Testbed\real1c_e2e")


@dataclass(frozen=True)
class LaneEnv:
    raw: dict
    secrets: dict = field(repr=False)
    credentials: dict = field(repr=False)
    e2e_dir: Path

    @classmethod
    def load(cls, e2e_dir: Path | None = None) -> LaneEnv:
        d = Path(e2e_dir or os.environ.get("E2E_DIR") or DEFAULT_E2E_DIR)
        load = lambda name: json.loads((d / name).read_text(encoding="utf-8"))
        return cls(load("env.json"), load("secrets.json"), load("credentials.json"), d)

    @property
    def gateway(self) -> str:
        return self.raw["urls"]["gateway"]

    @property
    def mcp_url(self) -> str:
        return self.raw["urls"]["mcp"]

    @property
    def idp_url(self) -> str:
        return self.raw["urls"]["idp"]

    def password(self, user: str) -> str:
        return self.credentials["users"][user]["password"]

    def dsn(self, role: str) -> str:
        user, key = {
            "admin": ("business_ai_admin", "pg_admin_password"),
            "control": ("business_ai_control_api", "pg_control_password"),
            "app": ("business_ai_app", "pg_app_password"),
            "owner": ("business_ai", "pg_owner_password"),
        }[role]
        return (f"postgresql://{user}:{self.secrets[key]}@{self.raw['host']}:"
                f"{self.raw['ports']['postgres']}/business_ai")


class Idp:
    def __init__(self, env: LaneEnv):
        self.env = env
        self.token_url = env.raw["idp"]["token_endpoint"]

    def token_response(self, user: str, *, audience: str = "data", scope: str | None = None,
                       acr: str | None = None, auth_age: int | None = None,
                       ttl: int | None = None) -> httpx.Response:
        audiences = self.env.raw["audiences"]
        form = {
            "grant_type": "password", "client_id": self.env.raw["idp"]["headless_client_id"],
            "client_secret": self.env.secrets["headless_client_secret"], "username": user,
            "password": self.env.password(user), "audience": audiences.get(audience, audience),
            "scope": scope or self.env.raw["scopes"]["admin" if audience == "admin" else "data"],
        }
        if acr is not None:
            form["acr"] = acr
        if auth_age is not None:
            form["auth_age"] = str(auth_age)
        if ttl is not None:
            form["ttl"] = str(ttl)
        return httpx.post(self.token_url, data=form, trust_env=False, timeout=15)

    def token(self, user: str, **kwargs: Any) -> str:
        response = self.token_response(user, **kwargs)
        response.raise_for_status()
        return response.json()["access_token"]


class AdminSession:
    """Cookie + CSRF aware Admin API client authenticated through the real OIDC browser flow."""

    def __init__(self, env: LaneEnv, user: str, *, step_up: bool = False):
        self.env, self.user = env, user
        self.client = httpx.Client(base_url=env.gateway, follow_redirects=False, trust_env=False, timeout=60)
        self._login(step_up)
        me = self.client.get("/admin/v1/me")
        if me.status_code != 200:
            raise RuntimeError(f"admin /me failed for {user}: {me.status_code}")
        self.csrf = me.json().get("csrf_token")
        if not self.csrf:
            raise RuntimeError(f"no csrf token for {user}")

    def _login(self, step_up: bool) -> None:
        r = self.client.get("/admin/login", params={"step_up": "1"} if step_up else None)
        if r.status_code != 302:
            raise RuntimeError(f"admin login redirect expected, got {r.status_code}")
        page = self.client.get(r.headers["location"])
        req = re.search(r'name="req" value="([^"]+)"', page.text).group(1)
        action = re.search(r'action="([^"]+)"', page.text).group(1)
        sub = self.client.post(self.env.idp_url + action, data={
            "req": req, "username": self.user, "password": self.env.password(self.user)})
        cb = self.client.get(sub.headers["location"])
        if cb.status_code != 302:
            raise RuntimeError(f"admin callback failed: {cb.status_code}")

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def post(self, path: str, body: Any = None, *, csrf: bool = True,
             idempotency_key: str | None = None) -> httpx.Response:
        headers = {"X-CSRF-Token": self.csrf} if csrf and self.csrf else {}
        if path.startswith("/admin/v1/") and not path.endswith("source-probes"):
            headers["Idempotency-Key"] = idempotency_key or uuid.uuid4().hex
        return self.client.post(path, json=body, headers=headers)

    def close(self) -> None:
        self.client.close()


def tool_payload(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured.get("result", structured) if isinstance(structured, dict) else structured
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    return json.loads(texts[0]) if texts else None


@asynccontextmanager
async def mcp_session(env: LaneEnv, token: str | None) -> AsyncIterator[Any]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=60, trust_env=False) as http,
        streamable_http_client(env.mcp_url, http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        yield session


async def call_tool(session: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool; always return {'is_error': bool, 'payload': decoded, 'text': str}."""
    result = await session.call_tool(name, arguments)
    text = " ".join(c.text for c in result.content if getattr(c, "text", None))
    try:
        payload = tool_payload(result)
    except (ValueError, TypeError):
        payload = None
    return {"is_error": bool(getattr(result, "is_error", False)), "payload": payload, "text": text}
