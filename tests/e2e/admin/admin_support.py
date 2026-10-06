"""Shared helpers for the Admin Control Center E2E suite (rows A01-A54).

Everything here talks to the real environment through the same boundaries the contract names:
the Admin plane only through ``/admin/`` (browser, or ``/admin/v1`` with a real OIDC session and
CSRF token), the data plane only through the public MCP endpoint with IdP-issued tokens, and
evidence reads through the read-only DB roles. Nothing here writes to PostgreSQL.

Design notes
------------
* ``World`` builds the order-dependent state (source, companies, role bindings, grants,
  capability evidence, profiles) THROUGH ``/admin/``. Each builder is cached under an explicit
  name and every consumer asks for the names it needs, so any single test can run alone and a
  failed precondition is reported with the offending response instead of being skipped.
* Redis limits the Admin API to 120 calls/minute/subject and ``/admin/login`` to 10/minute per
  client address. ``pace_api`` / ``pace_login`` keep this suite below those limits so the limiter
  never becomes a hidden source of flakiness (the limiter itself is not under test here).
* Outage helpers always restore components in ``finally`` and then wait for observable health.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
FAULT_SCRIPT = ROOT / "scripts" / "e2e" / "fault.ps1"
LOG_DIR = ROOT / ".e2e" / "logs"
JWT_LIKE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")
SESSION_COOKIE = "erp_mcp_admin_session"
SECRET_REFS = {"username": "FAKE1C_USERNAME", "password": "FAKE1C_PASSWORD"}
STEP_UP_MAX_AGE = 120  # seconds; the gateway accepts 300, stay well inside


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- rate-limit pacing
class _Window:
    def __init__(self, budget: int, period: float = 60.0):
        self.budget, self.period = budget, period
        self.stamps: deque[float] = deque()
        self.lock = threading.Lock()

    def take(self, n: int = 1) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.stamps and now - self.stamps[0] >= self.period:
                    self.stamps.popleft()
                if len(self.stamps) + n <= self.budget:
                    self.stamps.extend([now] * n)
                    return
                wait = self.stamps[0] + self.period - now
            time.sleep(max(wait, 0.05))


_API_WINDOWS: dict[str, _Window] = {}
_LOGIN_WINDOW = _Window(8)


def pace_api(subject: str, n: int = 1) -> None:
    window = _API_WINDOWS.setdefault(subject, _Window(100))
    window.take(n)


def pace_login() -> None:
    _LOGIN_WINDOW.take(1)


# --------------------------------------------------------------------------- waiting
def wait_until(cond: Callable[[], Any], *, timeout: float = 30.0, interval: float = 0.5,
               what: str = "condition") -> Any:
    """Poll an observable condition; fail with the last observed value on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = cond()
        except Exception as exc:  # noqa: BLE001 - condition probes may fail while converging
            value = None
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            last_error = ""
        if value:
            return value
        if time.monotonic() >= deadline:
            pytest.fail(f"timeout after {timeout}s waiting for {what} {last_error}")
        time.sleep(interval)


# --------------------------------------------------------------------------- HTTP records
TRANSCRIPT: list[Resp] = []


@dataclass
class Resp:
    method: str
    path: str
    status: int
    text: str
    headers: httpx.Headers
    request_id: str
    idem_key: str | None = None
    actor: str = ""

    @property
    def body(self) -> Any:
        try:
            return json.loads(self.text)
        except ValueError:
            return None

    @property
    def error(self) -> str | None:
        body = self.body
        return body.get("error") if isinstance(body, dict) else None

    @property
    def request_uuid(self) -> uuid.UUID:
        return uuid.UUID(self.request_id)

    def describe(self) -> str:
        return (f"{self.method} {self.path} -> {self.status} {self.text[:300]!r} "
                f"(request_id={self.request_id}, idempotency_key={self.idem_key})")


def expect(resp: Resp, status: int | tuple[int, ...], what: str = "") -> Resp:
    allowed = (status,) if isinstance(status, int) else status
    assert resp.status in allowed, f"{what}: expected {allowed}, got {resp.describe()}"
    return resp


def _record(resp: httpx.Response, method: str, path: str, rid: str, idem: str | None,
            actor: str) -> Resp:
    out = Resp(method, path, resp.status_code, resp.text[:400_000], resp.headers, rid, idem, actor)
    TRANSCRIPT.append(out)
    return out


class AdminSession:
    """Cookie + CSRF aware client authenticated through the real OIDC authorization-code flow."""

    def __init__(self, env, user: str, *, step_up: bool = False):
        self.env, self.user, self.step_up = env, user, step_up
        pace_login()
        self.client = httpx.Client(base_url=env.gateway, follow_redirects=False,
                                   trust_env=False, timeout=30)
        self.logged_in_at = time.monotonic()
        self._login()
        me = self.get("/admin/v1/me")
        self.csrf: str | None = me.body.get("csrf_token") if me.status == 200 else None

    def _login(self) -> None:
        env = self.env
        start = self.client.get("/admin/login", params={"step_up": "1"} if self.step_up else None)
        assert start.status_code == 302, f"login start for {self.user}: {start.status_code}"
        form_page = self.client.get(start.headers["location"])
        assert form_page.status_code == 200, f"IdP login page: {form_page.status_code}"
        req = re.search(r'name="req" value="([^"]+)"', form_page.text).group(1)
        action = re.search(r'action="([^"]+)"', form_page.text).group(1)
        submitted = self.client.post(env.idp_url + action, data={
            "req": req, "username": self.user, "password": env.password(self.user)})
        assert submitted.status_code == 302, f"IdP credential post: {submitted.status_code}"
        callback = self.client.get(submitted.headers["location"])
        assert callback.status_code == 302, (
            f"gateway callback for {self.user}: {callback.status_code} {callback.text[:200]}")
        assert SESSION_COOKIE in self.client.cookies, "session cookie was not issued"

    @property
    def age(self) -> float:
        return time.monotonic() - self.logged_in_at

    @property
    def cookie(self) -> str:
        return self.client.cookies.get(SESSION_COOKIE) or ""

    def request(self, method: str, path: str, body: Any = None, *, key: str | None = None,
                csrf: bool | str = True, headers: dict | None = None,
                params: dict | None = None, raw_json: bool = False) -> Resp:
        pace_api(self.user)
        rid = str(uuid.uuid4())
        merged = {"X-Request-Id": rid, "Accept": "application/json", **(headers or {})}
        idem = None
        kwargs: dict[str, Any] = {"headers": merged, "params": params}
        if method != "GET":
            if csrf is True and self.csrf:
                merged["X-CSRF-Token"] = self.csrf
            elif isinstance(csrf, str):
                merged["X-CSRF-Token"] = csrf
            idem = key or f"e2e-{uuid.uuid4()}"
            merged.setdefault("Idempotency-Key", idem)
            kwargs["json"] = {} if body is None else body
            if raw_json:
                kwargs.pop("json")
                kwargs["content"] = body
        response = self.client.request(method, path, **kwargs)
        return _record(response, method, path, rid, idem, self.user)

    def get(self, path: str, **kw: Any) -> Resp:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Resp:
        return self.request("POST", path, body, **kw)

    def patch(self, path: str, body: Any = None, **kw: Any) -> Resp:
        return self.request("PATCH", path, body, **kw)

    def logout(self) -> Resp:
        return self.post("/admin/logout")

    def alive(self) -> bool:
        return self.get("/admin/v1/me").status == 200

    def close(self) -> None:
        self.client.close()


def bearer(env, token: str, method: str, path: str, body: Any = None, *, subject: str = "bearer",
           key: str | None = None, params: dict | None = None) -> Resp:
    """Bearer-authenticated Admin API call (no session, no CSRF)."""
    pace_api(subject)
    rid = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}", "X-Request-Id": rid}
    idem = None
    kwargs: dict[str, Any] = {"headers": headers, "params": params}
    if method != "GET":
        idem = key or f"e2e-{uuid.uuid4()}"
        headers["Idempotency-Key"] = idem
        kwargs["json"] = {} if body is None else body
    response = httpx.request(method, env.gateway + path, trust_env=False, timeout=30, **kwargs)
    return _record(response, method, path, rid, idem, subject)


def anonymous(env, method: str, path: str, body: Any = None, *, headers: dict | None = None,
              cookie: str | None = None) -> Resp:
    rid = str(uuid.uuid4())
    merged = {"X-Request-Id": rid, **(headers or {})}
    if cookie:
        merged["Cookie"] = f"{SESSION_COOKIE}={cookie}"
    kwargs: dict[str, Any] = {"headers": merged}
    if method != "GET":
        kwargs["json"] = {} if body is None else body
    response = httpx.request(method, env.gateway + path, trust_env=False, timeout=30,
                             follow_redirects=False, **kwargs)
    return _record(response, method, path, rid, None, "anonymous")


# --------------------------------------------------------------------------- DB evidence
class Evidence:
    """Read-only evidence queries (control login role). Never mutates."""

    def __init__(self, db):
        self.db = db

    def rows(self, sql: str, *args: Any, role: str = "control") -> list[dict]:
        return self.db.fetch_sync(sql, *args, role=role)

    def one(self, sql: str, *args: Any, role: str = "control") -> dict | None:
        rows = self.rows(sql, *args, role=role)
        return rows[0] if rows else None

    def scalar(self, sql: str, *args: Any, role: str = "control") -> Any:
        row = self.one(sql, *args, role=role)
        return next(iter(row.values())) if row else None

    def now(self):
        return self.scalar("SELECT now() AS t")

    def count(self, table: str, where: str = "true", *args: Any) -> int:
        return int(self.scalar(f"SELECT count(*) AS n FROM bag.{table} WHERE {where}", *args))

    def admin_events(self, resp: Resp | str) -> list[dict]:
        rid = resp.request_uuid if isinstance(resp, Resp) else uuid.UUID(resp)
        return self.rows("SELECT * FROM bag.admin_audit_events WHERE request_id=$1 "
                         "ORDER BY occurred_at", rid)

    def admin_events_since(self, since, **filters: Any) -> list[dict]:
        clauses, args = ["occurred_at >= $1"], [since]
        for column, value in filters.items():
            args.append(value)
            clauses.append(f"{column} = ${len(args)}")
        return self.rows("SELECT * FROM bag.admin_audit_events WHERE " + " AND ".join(clauses)
                         + " ORDER BY occurred_at", *args)

    def audit_dump_text(self) -> str:
        """Every runtime and admin audit row plus idempotency results as one string."""
        parts = []
        for table in ("admin_audit_events", "audit_events", "admin_idempotency"):
            parts.append(json.dumps(self.rows(f"SELECT * FROM bag.{table}"), default=str))
        return "\n".join(parts)

    def snapshot(self) -> dict[str, int]:
        """Row counts of every domain table a forbidden admin mutation could touch."""
        tables = ("sources", "companies", "access_grants", "platform_role_bindings",
                  "semantic_profiles", "semantic_mappings", "company_scope_mappings",
                  "business_role_assignments", "capability_overrides")
        return {t: self.count(t) for t in tables}


# --------------------------------------------------------------------------- secrets scanning
def secret_values(env) -> dict[str, str]:
    values = {k: v for k, v in env.secrets.items() if isinstance(v, str) and len(v) >= 8}
    for user, data in env.credentials["users"].items():
        values[f"password:{user}"] = data["password"]
    return values


def find_leaks(text: str, values: dict[str, str]) -> list[str]:
    return sorted(name for name, value in values.items() if value and value in text)


# --------------------------------------------------------------------------- fault injection
def _powershell() -> str:
    found = shutil.which("powershell") or shutil.which("pwsh")
    if not found:
        pytest.fail("powershell/pwsh not found; fault.ps1 cannot run")
    return found


def fault(component: str, action: str) -> None:
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(FAULT_SCRIPT),
         "-Component", component, "-Action", action],
        cwd=ROOT, capture_output=True, text=True, timeout=420, check=False)
    if result.returncode != 0:
        pytest.fail(f"fault.ps1 {component} {action} failed rc={result.returncode}: "
                    f"{(result.stdout + result.stderr)[-600:]}")


def component_healthy(env, component: str) -> bool:
    try:
        if component == "fake1c":
            return httpx.get(env.fake1c_url + "/$metadata", trust_env=False,
                             timeout=4).status_code == 200
        if component == "idp":
            return httpx.get(env.idp_url + "/healthz", trust_env=False,
                             timeout=4).status_code == 200
        if component == "gateway":
            return httpx.get(env.gateway + "/readyz", trust_env=False,
                             timeout=4).status_code == 200
        if component == "redis":
            from redis import Redis

            client = Redis.from_url(env.redis_url, socket_connect_timeout=3)
            try:
                return bool(client.ping())
            finally:
                client.close()
        if component == "postgres":
            import asyncpg

            async def probe():
                conn = await asyncpg.connect(env.dsn("control"), timeout=4)
                try:
                    return await conn.fetchval("SELECT 1") == 1
                finally:
                    await conn.close()

            box: dict[str, Any] = {}

            def run():
                try:
                    box["ok"] = asyncio.run(probe())
                except Exception:  # noqa: BLE001
                    box["ok"] = False

            thread = threading.Thread(target=run)
            thread.start()
            thread.join(10)
            return bool(box.get("ok"))
    except Exception:  # noqa: BLE001 - health probes report False while a component is down
        return False
    raise ValueError(component)


def wait_healthy(env, *components: str, timeout: float = 120.0) -> None:
    for component in components:
        wait_until(lambda c=component: component_healthy(env, c), timeout=timeout,
                   interval=1.0, what=f"{component} healthy")


def restore(env, component: str) -> None:
    fault(component, "start")
    wait_healthy(env, component)
    if component in {"postgres", "redis"}:
        wait_healthy(env, "gateway")


@contextlib.contextmanager
def outage(env, component: str) -> Iterator[None]:
    """Stop a component for the duration of the block; ALWAYS start it again afterwards."""
    fault(component, "stop")
    try:
        assert not component_healthy(env, component), f"{component} still healthy after stop"
        yield
    finally:
        restore(env, component)


# --------------------------------------------------------------------------- ASGI stubs
class AsgiServer:
    """Runs an ASGI app on 127.0.0.1:port in a thread (used to stand in for Fake1C / canaries)."""

    def __init__(self, app, port: int):
        import uvicorn

        self.port = port
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> AsgiServer:
        self.thread.start()
        wait_until(lambda: self.server.started, timeout=15, interval=0.1,
                   what=f"stub server on {self.port}")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.should_exit = True
        self.thread.join(15)
        assert not self.thread.is_alive(), f"stub server on {self.port} did not stop"


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def recorder_app(hits: list[tuple[str, str]], *, redirect_to: str | None = None,
                 broken: bool = False):
    """Starlette app recording every request. Optional 302 redirect or broken metadata."""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route

    async def handler(request):
        hits.append((request.method, request.url.path))
        if redirect_to:
            return Response(status_code=302, headers={"Location": redirect_to})
        if broken:
            return Response("<html>this is not OData metadata</html>", status_code=200,
                            media_type="text/html")
        return Response(status_code=200)

    methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    return Starlette(routes=[Route("/{path:path}", handler, methods=methods)])


def drifted_fake1c_app():
    """The real Fake1C app serving metadata with one extra EntitySet (fingerprint drift)."""
    from business_ai_gateway.testbed import fake1c

    extra_type = (b'<EntityType Name="Catalog_E2EDrift"><Property Name="Ref_Key" '
                  b'Type="Edm.Guid"/></EntityType>\n      <EntityContainer')
    extra_set = (b'<EntitySet Name="Catalog_E2EDrift" EntityType="Fake1C.Catalog_E2EDrift"/>\n'
                 b'      </EntityContainer>')
    patched = fake1c.METADATA.replace(b"<EntityContainer", extra_type, 1)
    patched = patched.replace(b"</EntityContainer>", extra_set, 1)
    assert patched != fake1c.METADATA, "drift patch did not change metadata"
    return fake1c, patched


@contextlib.contextmanager
def fake1c_replaced_by(env, make_app: Callable[[], Any], *, before: Callable[[], None] | None = None
                       ) -> Iterator[AsgiServer]:
    """Stop the real Fake1C, serve ``make_app()`` on its port, ALWAYS restore Fake1C after."""
    port = env.raw["ports"]["fake1c"]
    fault("fake1c", "stop")
    server: AsgiServer | None = None
    try:
        server = AsgiServer(make_app(), port).__enter__()
        yield server
    finally:
        if server is not None:
            server.__exit__(None, None, None)
        restore(env, "fake1c")


# --------------------------------------------------------------------------- data plane (MCP)
def _decode(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured) if isinstance(structured, dict) else structured
    texts = [c.text for c in getattr(result, "content", []) if getattr(c, "text", None)]
    try:
        return json.loads(texts[0]) if texts else None
    except ValueError:
        return texts[0] if texts else None


@dataclass
class DataView:
    """What the data plane exposes to one token: sources and company ids it may list."""

    sources: list[str] = field(default_factory=list)
    companies: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    def sees_source(self, source_id: str) -> bool:
        return source_id in self.sources

    def sees_company(self, company_id: str) -> bool:
        return company_id in self.companies


def data_view(env, token: str | None, source_id: str, tools: tuple[str, ...] = ()) -> DataView:
    """Call sources_list + companies_list over the real MCP endpoint (sync wrapper)."""
    box: dict[str, Any] = {}

    async def go() -> DataView:
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        view = DataView()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx2.AsyncClient(headers=headers, timeout=30) as http, \
                streamable_http_client(env.mcp_url, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.call_tool("sources_list", {})
                if getattr(listed, "is_error", False) or getattr(listed, "isError", False):
                    view.errors.append("sources_list:error")
                else:
                    payload = _decode(listed) or []
                    view.sources = [i.get("id") for i in payload if isinstance(i, dict)]
                companies = await session.call_tool("companies_list", {"source_id": source_id})
                if getattr(companies, "is_error", False) or getattr(companies, "isError", False):
                    view.errors.append("companies_list:error")
                else:
                    payload = _decode(companies) or []
                    view.companies = {i.get("company_id") for i in payload
                                      if isinstance(i, dict)}
        return view

    def run() -> None:
        try:
            box["view"] = asyncio.run(go())
        except BaseException as exc:  # noqa: BLE001 - transport errors are a denial signal
            box["view"] = DataView(errors=[f"transport:{type(exc).__name__}"])

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(90)
    assert "view" in box, "MCP data-plane call did not finish within 90s"
    return box["view"]


# --------------------------------------------------------------------------- world state
@dataclass
class Step:
    name: str
    resp: Resp | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = False


class World:
    """Order-dependent state for the Admin suite, built through /admin/ with explicit names."""

    PRIMARY = "source"
    SECOND = "source_b"

    def __init__(self, env, evidence: Evidence, idp):
        self.env, self.ev, self.idp = env, evidence, idp
        self.steps: dict[str, Step] = {}
        self.sessions: dict[tuple[str, bool], AdminSession] = {}
        self.source_id: str = env.raw["source_id"]
        self.source_b_id: str = f"{self.source_id}-b"
        self.t0 = evidence.now()
        self._check_bootstrap_state()

    # ----- sessions
    def session(self, user: str, *, step_up: bool = False) -> AdminSession:
        key = (user, step_up)
        current = self.sessions.get(key)
        stale = current is not None and (
            (step_up and current.age > STEP_UP_MAX_AGE) or not current.alive())
        if current is None or stale:
            if current is not None:
                current.close()
            current = AdminSession(self.env, user, step_up=step_up)
            self.sessions[key] = current
        return current

    @property
    def pa(self) -> AdminSession:
        return self.session("platform_admin")

    def pa_step_up(self) -> AdminSession:
        return self.session("platform_admin", step_up=True)

    def role_session(self, role: str) -> AdminSession:
        user = {"SOURCE_ADMIN": "source_admin", "ACCESS_ADMIN": "access_admin",
                "PROFILE_ADMIN": "profile_admin", "AUDITOR": "auditor"}[role]
        self.need("roles")
        return self.session(user)

    def close(self) -> None:
        for session in self.sessions.values():
            session.close()

    # ----- identity helpers
    def sub(self, user: str) -> str:
        return self.env.raw["identities"][user]["sub"]

    def group_of(self, user: str) -> str:
        return self.env.raw["identities"][user]["groups"][0]

    def data_token(self, user: str) -> str:
        return self.idp.token(user)

    def data_view(self, user: str) -> DataView:
        return data_view(self.env, self.data_token(user), self.source_id)

    # ----- preconditions
    def _check_bootstrap_state(self) -> None:
        seed = self.env.seed_mode
        if seed != "bootstrap-only":
            pytest.fail(f"Admin suite requires seed mode bootstrap-only, environment has {seed!r}: "
                        "run scripts/e2e/reset.ps1 -Seed bootstrap-only")
        counts = {t: self.ev.count(t) for t in ("sources", "companies", "access_grants")}
        active = self.ev.rows("SELECT principal_id, role_name FROM bag.platform_role_bindings "
                              "WHERE revoked_at IS NULL")
        if any(counts.values()) or [(r["principal_id"], r["role_name"]) for r in active] != [
                ("platform_admin", "PLATFORM_ADMIN")]:
            pytest.fail("environment is not in pristine bootstrap-only state "
                        f"(counts={counts}, active bindings={active}): "
                        "run scripts/e2e/reset.ps1 -Seed bootstrap-only before the Admin suite")

    # ----- step plumbing
    def ensure(self, name: str) -> Step:
        if name not in self.steps:
            self.steps[name] = getattr(self, f"_b_{name}")()
        return self.steps[name]

    def need(self, *names: str) -> Step:
        step = None
        for name in names:
            step = self.ensure(name)
            if not step.ok:
                detail = step.resp.describe() if step.resp else "no response"
                pytest.fail(f"precondition '{name}' failed: {detail}")
        assert step is not None
        return step

    def reason(self, text: str) -> str:
        return f"E2E admin suite: {text}"

    # ----- builders (every one goes through /admin/)
    def _create_source(self, name: str, source_id: str, display: str) -> Step:
        body = {"source_id": source_id, "display_name": display, "base_url": self.env.fake1c_url,
                "username_secret_ref": SECRET_REFS["username"],
                "password_secret_ref": SECRET_REFS["password"], "tags": ["e2e"],
                "reason": self.reason(f"register {source_id}")}
        resp = self.pa.post("/admin/v1/sources", body)
        return Step(name, resp, {"source_id": source_id, "body": body}, resp.status == 201)

    def _b_source(self) -> Step:
        return self._create_source("source", self.source_id, "Fake1C E2E synthetic source")

    def _b_source_b(self) -> Step:
        return self._create_source("source_b", self.source_b_id, "Fake1C E2E second source")

    def _create_company(self, name: str, source_id: str, external_ref: str, display: str,
                        default: bool) -> Step:
        self.need("source" if source_id == self.source_id else "source_b")
        body = {"source_id": source_id, "external_ref": external_ref, "display_name": display,
                "is_default": default, "reason": self.reason(f"register {display}")}
        resp = self.pa.post("/admin/v1/companies", body)
        data = {"body": body, "company_id": (resp.body or {}).get("id")}
        return Step(name, resp, data, resp.status == 201)

    def _b_company_one(self) -> Step:
        return self._create_company("company_one", self.source_id,
                                    self.env.raw["companies"]["one"], "Synthetic Company One", True)

    def _b_company_two(self) -> Step:
        return self._create_company("company_two", self.source_id,
                                    self.env.raw["companies"]["two"], "Synthetic Company Two",
                                    False)

    def _b_company_b(self) -> Step:
        return self._create_company("company_b", self.source_b_id, unique("e2e-b-org"),
                                    "Second Source Company", False)

    def _b_roles(self) -> Step:
        self.need("source")
        session = self.pa_step_up()
        ids: dict[str, str] = {}
        last = None
        for user, role in (("source_admin", "SOURCE_ADMIN"), ("access_admin", "ACCESS_ADMIN"),
                           ("profile_admin", "PROFILE_ADMIN"), ("auditor", "AUDITOR")):
            body = {"principal_kind": "subject", "principal_id": self.sub(user),
                    "role_name": role, "source_id": self.source_id,
                    "reason": self.reason(f"bind {role} to {user}")}
            last = session.post("/admin/v1/platform-role-bindings", body)
            if last.status != 201:
                return Step("roles", last, {"bound": ids}, False)
            ids[role] = last.body["id"]
        return Step("roles", last, {"bound": ids}, True)

    def _b_uc1_grant(self) -> Step:
        self.need("roles", "company_one")
        resp = self.role_session("ACCESS_ADMIN").post("/admin/v1/grants", {
            "principal_kind": "subject", "principal_id": self.sub("user_company_one"),
            "source_id": self.source_id, "company_id": self.company_id("one"), "effect": "allow",
            "reason": self.reason("grant user_company_one to company one")})
        return Step("uc1_grant", resp, {"grant_id": (resp.body or {}).get("id")},
                    resp.status == 201)

    def _b_group_grant(self) -> Step:
        self.need("roles", "company_two")
        group = self.group_of("user_company_two")
        resp = self.role_session("ACCESS_ADMIN").post("/admin/v1/grants", {
            "principal_kind": "group", "principal_id": group, "source_id": self.source_id,
            "company_id": self.company_id("two"), "effect": "allow",
            "reason": self.reason("grant company-two readers group to company two")})
        return Step("group_grant", resp, {"grant_id": (resp.body or {}).get("id"), "group": group},
                    resp.status == 201)

    def _refresh_caps(self, name: str, source_id: str) -> Step:
        resp = self.pa.post(f"/admin/v1/sources/{source_id}/capability-refresh",
                            {"reason": self.reason(f"refresh metadata of {source_id}")})
        ok = resp.status == 200 and bool((resp.body or {}).get("metadata_fingerprint"))
        data = {"result": resp.body}
        if ok:
            row = self.ev.one("SELECT drift_status, metadata_fingerprint FROM "
                              "bag.source_capabilities WHERE source_id=$1", source_id)
            if row and row["drift_status"] == "DRIFTED":
                ack = self.pa.post(f"/admin/v1/sources/{source_id}/drift-acknowledgements", {
                    "expected_fingerprint": row["metadata_fingerprint"],
                    "reason": self.reason("acknowledge first observation")})
                data["ack"] = ack.status
                ok = ack.status == 200
        return Step(name, resp, data, ok)

    def _b_caps(self) -> Step:
        self.need("source")
        return self._refresh_caps("caps", self.source_id)

    def _b_caps_b(self) -> Step:
        self.need("source_b")
        return self._refresh_caps("caps_b", self.source_b_id)

    def create_profile(self, session: AdminSession, source_id: str, name: str | None = None
                       ) -> Resp:
        return session.post("/admin/v1/semantic-profiles", {
            "source_id": source_id, "company_id": None, "preset_id": "bp30",
            "profile_name": name or unique("e2e-profile"), "profile_definition": {},
            "reason": self.reason("create draft semantic profile")})

    def _b_profile(self) -> Step:
        self.need("caps", "roles")
        resp = self.create_profile(self.role_session("PROFILE_ADMIN"), self.source_id)
        return Step("profile", resp, {"profile_id": (resp.body or {}).get("id")},
                    resp.status == 201)

    def _b_profile_b(self) -> Step:
        self.need("caps_b", "roles")
        resp = self.create_profile(self.pa, self.source_b_id)
        return Step("profile_b", resp, {"profile_id": (resp.body or {}).get("id")},
                    resp.status == 201)

    def _b_grant_b(self) -> Step:
        self.need("source_b", "company_b")
        resp = self.pa.post("/admin/v1/grants", {
            "principal_kind": "subject", "principal_id": unique("e2e-scratch"),
            "source_id": self.source_b_id, "company_id": self.company_id("b"), "effect": "allow",
            "reason": self.reason("grant on the second source")})
        return Step("grant_b", resp, {"grant_id": (resp.body or {}).get("id")}, resp.status == 201)

    # ----- accessors
    def company_id(self, which: str) -> str:
        return self.need(f"company_{which}").data["company_id"]

    def scratch_grant(self, session: AdminSession, *, effect: str = "allow",
                      principal: str | None = None, company: str | None = None,
                      kind: str = "subject") -> Resp:
        return session.post("/admin/v1/grants", {
            "principal_kind": kind, "principal_id": principal or unique("e2e-scratch"),
            "source_id": self.source_id, "company_id": company, "effect": effect,
            "reason": self.reason("scratch grant")})

    def revoke_grant(self, session: AdminSession, grant_id: str, version: int = 1) -> Resp:
        return session.post(f"/admin/v1/grants/{grant_id}/revoke", {
            "expected_version": version, "reason": self.reason("revoke grant")})

    def grant_row(self, grant_id: str) -> dict | None:
        return self.ev.one("SELECT * FROM bag.access_grants WHERE grant_id=$1",
                           uuid.UUID(grant_id))

    def ensure_uc1_access(self) -> str:
        """Make sure user_company_one holds exactly one active allow grant to company one."""
        row = self.ev.one(
            "SELECT grant_id FROM bag.access_grants WHERE principal_kind='subject' AND "
            "principal_id=$1 AND company_id=$2 AND effect='allow' AND revoked_at IS NULL",
            self.sub("user_company_one"), uuid.UUID(self.company_id("one")))
        if row:
            return str(row["grant_id"])
        resp = self.role_session("ACCESS_ADMIN").post("/admin/v1/grants", {
            "principal_kind": "subject", "principal_id": self.sub("user_company_one"),
            "source_id": self.source_id, "company_id": self.company_id("one"), "effect": "allow",
            "reason": self.reason("restore user_company_one baseline access")})
        expect(resp, 201, "restore UC1 baseline grant")
        return resp.body["id"]

    # ----- profile lifecycle helpers
    def add_mapping(self, session: AdminSession, profile_id: str,
                    required: list[dict] | None = None, concept: str = "sales") -> Resp:
        return session.post(f"/admin/v1/semantic-profiles/{profile_id}/mappings", {
            "canonical_concept": concept,
            "mapping": {"required_register_capabilities": required or []},
            "evidence": {"evidence_refs": ["synthetic-e2e://not-native-evidence"],
                         "notes": "synthetic E2E mapping, not native reconciliation"},
            "reason": self.reason("add mapping")})

    @staticmethod
    def evidence_manifest() -> dict:
        return {"native_reconciliation_cases": [
            {"case_id": f"SYNTHETIC-E2E-{i:02d}",
             "native_report_ref": f"synthetic-e2e://not-native/{i}", "status": "PASS"}
            for i in range(10)]}

    def validate_profile(self, session: AdminSession, profile_id: str) -> Resp:
        return session.post(f"/admin/v1/semantic-profiles/{profile_id}/validate", {
            "validation_evidence": self.evidence_manifest(),
            "reason": self.reason("validate synthetic profile")})


READ_PATHS = (
    "/admin/v1/overview", "/admin/v1/sources", "/admin/v1/companies", "/admin/v1/capabilities",
    "/admin/v1/grants", "/admin/v1/platform-role-bindings", "/admin/v1/business-roles",
    "/admin/v1/business-role-assignments", "/admin/v1/capability-overrides",
    "/admin/v1/company-scope-mappings", "/admin/v1/semantic-profiles", "/admin/v1/audit",
)
