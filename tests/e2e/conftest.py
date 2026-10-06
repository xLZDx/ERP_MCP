"""Fixtures for the end-to-end suites that run against the disposable local environment.

Start the environment with ``scripts/e2e/up.ps1`` and run ``scripts/e2e/test.ps1``. Everything
here reads ``.e2e/`` (git-ignored): ``env.json`` (topology), ``secrets.json`` and
``credentials.json``. Later suites (U01-U18, A01-A54) build on these fixtures:

* ``e2e_env``      - parsed environment description (URLs, ports, identities, seed mode).
* ``idp``          - token minting through the test IdP's headless client.
* ``mcp_client``   - async context manager yielding a real MCP Streamable-HTTP ClientSession.
* ``admin_http``   - factory for a cookie/CSRF-aware Admin session obtained through the real
                     OIDC authorization-code + PKCE flow (no browser).
* ``admin_browser``- factory for a logged-in Playwright page (real browser OIDC login).
* ``db``           - evidence reads using the admin/control login roles (read-only helper).

Skip rule: tests are skipped ONLY when ``.e2e/env.json`` is absent and ``ERP_MCP_E2E_NO_SKIP``
is not set. With ``ERP_MCP_E2E_NO_SKIP=1`` (set by scripts/e2e/test.ps1) a missing
environment is an error. An existing but unhealthy environment is always a failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = Path(os.environ.get("E2E_DIR") or ROOT / ".e2e")
NO_SKIP_VAR = "ERP_MCP_E2E_NO_SKIP"


def _env_present() -> bool:
    return (E2E_DIR / "env.json").exists()


def pytest_collection_modifyitems(config, items):
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.e2e)
            if not _env_present() and not os.environ.get(NO_SKIP_VAR):
                item.add_marker(pytest.mark.skip(
                    reason=f"{E2E_DIR / 'env.json'} absent: run scripts/e2e/up.ps1 "
                           f"(set {NO_SKIP_VAR}=1 to make this an error)"))


@dataclass(frozen=True)
class E2eEnv:
    raw: dict
    secrets: dict
    credentials: dict

    @property
    def gateway(self) -> str:
        return self.raw["urls"]["gateway"]

    @property
    def mcp_url(self) -> str:
        return self.raw["urls"]["mcp"]

    @property
    def admin_url(self) -> str:
        return self.raw["urls"]["admin"]

    @property
    def idp_url(self) -> str:
        return self.raw["urls"]["idp"]

    @property
    def fake1c_url(self) -> str:
        return self.raw["urls"]["fake1c"]

    @property
    def issuer(self) -> str:
        return self.raw["issuer"]

    @property
    def identities(self) -> list[str]:
        return list(self.raw["identities"])

    @property
    def seed_mode(self) -> str:
        return self.raw["seed_mode"]

    def password(self, user: str) -> str:
        return self.credentials["users"][user]["password"]

    def dsn(self, role: str) -> str:
        user, key = {
            "admin": ("business_ai_admin", "pg_admin_password"),
            "control": ("business_ai_control_api", "pg_control_password"),
            "app": ("business_ai_app", "pg_app_password"),
            "owner": ("business_ai", "pg_owner_password"),
        }[role]
        port = self.raw["ports"]["postgres"]
        return f"postgresql://{user}:{self.secrets[key]}@{self.raw['host']}:{port}/business_ai"

    @property
    def redis_url(self) -> str:
        return (f"redis://:{self.secrets['redis_password']}@{self.raw['host']}:"
                f"{self.raw['ports']['redis']}/0")


@pytest.fixture(scope="session")
def e2e_env() -> E2eEnv:
    if not _env_present():
        message = f"{E2E_DIR / 'env.json'} missing: run scripts/e2e/up.ps1"
        if os.environ.get(NO_SKIP_VAR):
            pytest.fail(message)
        pytest.skip(message)
    load = lambda name: json.loads((E2E_DIR / name).read_text(encoding="utf-8"))
    return E2eEnv(load("env.json"), load("secrets.json"), load("credentials.json"))


class IdpClient:
    """Mints tokens through the IdP headless client (password grant, test-only)."""

    def __init__(self, env: E2eEnv):
        self.env = env
        self.token_url = env.raw["idp"]["token_endpoint"]

    def token_response(self, user: str, *, audience: str = "data", scope: str | None = None,
                       acr: str | None = None, auth_age: int | None = None,
                       ttl: int | None = None, password: str | None = None) -> httpx.Response:
        """Raw token response. `audience` is data|admin or a literal audience URL."""
        audiences = self.env.raw["audiences"]
        form = {
            "grant_type": "password", "client_id": self.env.raw["idp"]["headless_client_id"],
            "client_secret": self.env.secrets["headless_client_secret"], "username": user,
            "password": password if password is not None else self.env.password(user),
            "audience": audiences.get(audience, audience),
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

    def step_up_token(self, user: str, **kwargs: Any) -> str:
        """Admin-audience token carrying the configured step-up ACR and a fresh auth_time."""
        return self.token(user, audience="admin", acr=self.env.raw["step_up_acr"],
                          auth_age=0, **kwargs)


@pytest.fixture(scope="session")
def idp(e2e_env: E2eEnv) -> IdpClient:
    return IdpClient(e2e_env)


@pytest.fixture
def mcp_client(e2e_env: E2eEnv):
    """``async with mcp_client(token) as session`` -> initialized mcp ClientSession."""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    @asynccontextmanager
    async def connect(token: str | None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=30) as http,
            streamable_http_client(e2e_env.mcp_url, http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            yield session

    return connect


def _tool_payload(result) -> Any:
    """Decode a CallToolResult into JSON (structuredContent first, then text content)."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured.get("result", structured) if isinstance(structured, dict) else structured
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    return json.loads(texts[0]) if texts else None


class AdminHttp:
    """Cookie + CSRF aware Admin API client authenticated via the real OIDC browser flow."""

    def __init__(self, env: E2eEnv, user: str, *, step_up: bool = False):
        self.env, self.user = env, user
        self.client = httpx.Client(base_url=env.gateway, follow_redirects=False,
                                   trust_env=False, timeout=30)
        self._login(step_up)
        self.csrf = self.get("/admin/v1/me").json().get("csrf_token")

    def _login(self, step_up: bool) -> None:
        response = self.client.get("/admin/login", params={"step_up": "1"} if step_up else None)
        assert response.status_code == 302, response.text
        form_page = self.client.get(response.headers["location"])
        assert form_page.status_code == 200, form_page.text
        req = re.search(r'name="req" value="([^"]+)"', form_page.text).group(1)
        action = re.search(r'action="([^"]+)"', form_page.text).group(1)
        submitted = self.client.post(self.env.idp_url + action, data={
            "req": req, "username": self.user, "password": self.env.password(self.user)})
        assert submitted.status_code == 302, submitted.text
        callback = self.client.get(submitted.headers["location"])
        assert callback.status_code == 302, (callback.status_code, callback.text[:200])

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def post(self, path: str, json_body: Any = None, *, csrf: bool = True,
             headers: dict | None = None) -> httpx.Response:
        merged = dict(headers or {})
        if csrf and self.csrf:
            merged.setdefault("X-CSRF-Token", self.csrf)
        return self.client.post(path, json=json_body, headers=merged)

    def logout(self) -> httpx.Response:
        return self.post("/admin/logout")

    def close(self) -> None:
        self.client.close()


@pytest.fixture
def admin_http(e2e_env: E2eEnv):
    sessions: list[AdminHttp] = []

    def login(user: str, *, step_up: bool = False) -> AdminHttp:
        session = AdminHttp(e2e_env, user, step_up=step_up)
        sessions.append(session)
        return session

    yield login
    for session in sessions:
        session.close()


@pytest.fixture(scope="session")
def _playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def admin_browser(e2e_env: E2eEnv, _playwright):
    """``admin_browser(user, step_up=False)`` -> Playwright page signed in through the IdP UI.

    Use from synchronous tests (Playwright's sync API cannot run inside an event loop).
    """
    contexts = []

    def login(user: str, *, step_up: bool = False):
        context = _playwright.new_context()
        contexts.append(context)
        page = context.new_page()
        suffix = "?step_up=1" if step_up else ""
        page.goto(f"{e2e_env.gateway}/admin/login{suffix}")
        page.fill("#username", user)
        page.fill("#password", e2e_env.password(user))
        page.click("#login-submit")
        page.wait_for_url(re.compile(r".*/admin/?$"))
        return page

    yield login
    for context in contexts:
        context.close()


class DbHelper:
    """Read helper for evidence queries. Mutations go through the product, not this helper."""

    def __init__(self, env: E2eEnv):
        self.env = env

    async def fetch(self, sql: str, *args: Any, role: str = "control") -> list[dict]:
        conn = await asyncpg.connect(self.env.dsn(role), timeout=10)
        try:
            return [dict(r) for r in await conn.fetch(sql, *args)]
        finally:
            await conn.close()

    def fetch_sync(self, sql: str, *args: Any, role: str = "control") -> list[dict]:
        """Blocking variant for synchronous tests (runs in a helper thread)."""
        box: dict[str, Any] = {}

        def run():
            box["rows"] = asyncio.run(self.fetch(sql, *args, role=role))

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        return box["rows"]


@pytest.fixture(scope="session")
def db(e2e_env: E2eEnv) -> DbHelper:
    return DbHelper(e2e_env)


@pytest.fixture(scope="session")
def tool_payload():
    """Decoder for CallToolResult objects (structured content first, then text JSON)."""
    return _tool_payload
