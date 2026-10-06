"""Shared helpers for the data-plane User suite (U01-U18). Public MCP endpoint only.

Nothing here imports gateway internals: tools are called through a real MCP Streamable-HTTP
session with IdP-issued bearer tokens; evidence comes from read-only DB queries, the Fake1C
recording wrapper (``/__ft__/requests``) and the test IdP.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "e2e"
E2E_DIR = Path(os.environ.get("E2E_DIR") or ROOT / ".e2e")
SEED_PATH = ROOT / "testbed" / "fake1c" / "fixtures" / "seed.json"

READ_ONLY_METHODS = {"GET", "HEAD"}
AUDIT_COLUMNS = (
    "event_id, occurred_at, principal_subject, client_id, tool_name, source_id, outcome, "
    "query_fingerprint, query_json, returned_items, duration_ms, detail_code, request_id, "
    "company_id, adapter_kind, policy_version, metadata_fingerprint, profile_fingerprint, "
    "response_bytes, truncated"
)


# --------------------------------------------------------------------------- tool calls


@dataclass
class ToolOutcome:
    tool: str
    args: dict
    is_error: bool
    text: str
    payload: Any
    elapsed: float
    transport_error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.is_error and self.transport_error is None


def _leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _decode(result) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    try:
        return json.loads(texts[0]) if texts else None
    except ValueError:
        return None


async def call_tool(mcp_client, token: str | None, tool: str,
                    args: dict | None = None) -> ToolOutcome:
    """One public MCP tool call. Protocol/transport failures are returned, not raised."""
    args = args or {}
    started = time.monotonic()
    try:
        async with mcp_client(token) as session:
            result = await session.call_tool(tool, args)
            text = " ".join(getattr(c, "text", "") or "" for c in result.content)
            payload = None if result.is_error else _decode(result)
            return ToolOutcome(tool, args, bool(result.is_error), text, payload,
                               time.monotonic() - started)
    except BaseException as exc:  # noqa: BLE001 - transport failure is evidence
        leaf = _leaf(exc)
        return ToolOutcome(tool, args, True, "", None, time.monotonic() - started,
                           f"{type(leaf).__name__}: {str(leaf)[:200]}")


# --------------------------------------------------------------------------- raw MCP HTTP

_INIT_BODY = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "e2e-user", "version": "0"}},
}


def raw_initialize(mcp_url: str, token: str | None) -> httpx.Response:
    """Bare initialize POST: lets tests assert the exact HTTP status of token rejection."""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.post(mcp_url, json=_INIT_BODY, headers=headers, trust_env=False, timeout=20)


# --------------------------------------------------------------------------- Fake1C log


class Fake1cLog:
    """Reader for the recording Fake1C wrapper (testbed/fake1c/app.py)."""

    def __init__(self, root_url: str):
        self.root = root_url.rstrip("/")
        self.url = self.root + "/__ft__/requests"

    def _get(self, since: int) -> dict:
        response = httpx.get(self.url, params={"since": since}, trust_env=False, timeout=10)
        response.raise_for_status()
        return response.json()

    def mark(self) -> int:
        return self._get(10**9)["last_seq"]

    def since(self, mark: int, *, gateway_only: bool = True) -> list[dict]:
        items = self._get(mark)["requests"]
        if gateway_only:
            items = [i for i in items if i["user_agent"].startswith("erp-mcp/")]
        return items

    def all_methods_read_only(self, mark: int) -> bool:
        return {i["method"] for i in self._get(mark)["requests"]} <= READ_ONLY_METHODS

    @staticmethod
    def entity_paths(items: list[dict]) -> set[str]:
        return {i["path"].rsplit("/", 1)[-1] for i in items if not i["path"].endswith("$metadata")}


# --------------------------------------------------------------------------- DB evidence


async def db_clock(db) -> Any:
    return (await db.fetch("SELECT clock_timestamp() AS now", role="admin"))[0]["now"]


async def audit_since(db, since, *, subject: str | None = None, tool: str | None = None,
                      company_id: str | None = None) -> list[dict]:
    """Audit rows read through the read-only evidence role (business_ai_admin: SELECT only)."""
    clauses, args = ["occurred_at >= $1"], [since]
    for column, value, cast in (("principal_subject", subject, ""), ("tool_name", tool, ""),
                                ("company_id", company_id, "::uuid")):
        if value is not None:
            args.append(value)
            clauses.append(f"{column} = ${len(args)}{cast}")
    sql = (f"SELECT {AUDIT_COLUMNS} FROM bag.audit_events WHERE {' AND '.join(clauses)} "
           "ORDER BY occurred_at, event_id")
    return await db.fetch(sql, *args, role="admin")


def completion_rows(rows: list[dict]) -> list[dict]:
    """Rows that record the final outcome (the pre-dispatch receipt is ACCESS_AUTHORIZED)."""
    return [r for r in rows if r["detail_code"] != "ACCESS_AUTHORIZED"]


def receipts(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["detail_code"] == "ACCESS_AUTHORIZED"]


async def validated_profile_exists(db, company_id: str, concept: str) -> bool:
    rows = await db.fetch(
        "SELECT 1 FROM bag.semantic_profiles p JOIN bag.semantic_mappings m "
        "ON m.profile_id=p.profile_id WHERE p.company_id=$1::uuid AND p.status='VALIDATED' "
        "AND m.canonical_concept=$2 AND m.mapping_status='CONFIRMED' LIMIT 1",
        company_id, concept, role="admin")
    return bool(rows)


def seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- secrets scan

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_USERINFO = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]*@", re.IGNORECASE)


def secret_values(env) -> list[str]:
    values = [str(v) for v in env.secrets.values()]
    values += [u["password"] for u in env.credentials["users"].values()]
    return [v for v in values if len(v) >= 6]


def find_leaks(blob: str, env, *, extra: tuple[str, ...] = ()) -> list[str]:
    """Names (never values) of secret classes present in `blob`."""
    leaks = []
    if any(v in blob for v in secret_values(env)):
        leaks.append("env-secret-value")
    if any(t and t in blob for t in extra):
        leaks.append("token")
    if _JWT.search(blob):
        leaks.append("jwt-shaped-string")
    if _USERINFO.search(blob):
        leaks.append("url-userinfo")
    if re.search(r"bearer\s+[A-Za-z0-9._-]{16,}", blob, re.IGNORECASE):
        leaks.append("bearer-header")
    return leaks


def jsonable(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


# --------------------------------------------------------------------------- admin grants


class GrantAdmin:
    """Grant lifecycle through the real Admin API (platform_admin session + CSRF)."""

    def __init__(self, admin, source_id: str):
        self.admin, self.source_id = admin, source_id

    def list(self) -> list[dict]:
        response = self.admin.get("/admin/v1/grants")
        assert response.status_code == 200, response.text
        return response.json()["items"]

    def active(self, principal_kind: str, principal_id: str, company_id: str | None):
        for item in self.list():
            if (item["principal_kind"] == principal_kind and item["principal_id"] == principal_id
                    and item["source_id"] == self.source_id and item["effect"] == "allow"
                    and item["revoked_at"] is None
                    and (str(item["company_id"]) if item["company_id"] else None) == company_id):
                return item
        return None

    def create(self, principal_kind: str, principal_id: str, company_id: str | None,
               reason: str) -> dict:
        response = self.admin.post(
            "/admin/v1/grants",
            {"principal_kind": principal_kind, "principal_id": principal_id,
             "source_id": self.source_id, "company_id": company_id, "effect": "allow",
             "reason": reason},
            headers={"Idempotency-Key": uuid.uuid4().hex})
        assert response.status_code == 201, (response.status_code, response.text[:300])
        grant = self.active(principal_kind, principal_id, company_id)
        assert grant is not None, "created grant not visible in /admin/v1/grants"
        return grant

    def revoke(self, grant: dict, reason: str) -> None:
        response = self.admin.post(
            f"/admin/v1/grants/{grant['grant_id']}/revoke",
            {"expected_version": grant["row_version"], "reason": reason},
            headers={"Idempotency-Key": uuid.uuid4().hex})
        assert response.status_code == 200, (response.status_code, response.text[:300])

    def ensure(self, principal_kind: str, principal_id: str, company_id: str | None,
               reason: str) -> dict:
        return (self.active(principal_kind, principal_id, company_id)
                or self.create(principal_kind, principal_id, company_id, reason))

    @contextmanager
    def temporary_source_wide(self, subject: str):
        """Source-level tools need a source-wide allow grant (company grants do not open them)."""
        grant = self.create("subject", subject, None, "E2E temporary source-wide access")
        try:
            yield grant
        finally:
            current = self.active("subject", subject, None)
            if current is not None:
                self.revoke(current, "E2E temporary source-wide access removed")


# --------------------------------------------------------------------------- fault injection


def run_fault(component: str, action: str, *, timeout: int = 300) -> None:
    """scripts/e2e/fault.ps1 (disposable environment only)."""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(SCRIPTS / "fault.ps1"), "-Component", component, "-Action", action],
        capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"fault.ps1 {component} {action} failed: "
                           f"{(completed.stderr or completed.stdout)[-400:]}")


@contextmanager
def outage(component: str):
    """Stop `component`; ALWAYS start it again, even when the stop or the body raised."""
    try:
        run_fault(component, "stop")
        yield
    finally:
        try:
            run_fault(component, "start")
        except (RuntimeError, subprocess.TimeoutExpired):
            try:  # one retry: a half-started component is worse than a slow one
                run_fault(component, "start")
            except (RuntimeError, subprocess.TimeoutExpired) as second:
                raise RuntimeError(f"{component} could NOT be restarted after the outage; "
                                   "the environment is degraded") from second


def wait_until(predicate, *, timeout: float, interval: float = 1.0, what: str = "condition"):
    """Poll an observable condition; returns the first truthy value or fails with `what`."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:  # noqa: BLE001 - not ready yet
            last = exc
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what} (last={last!r})")


def gateway_ready(env) -> bool:
    return httpx.get(env.gateway + "/readyz", trust_env=False, timeout=5).status_code == 200


async def await_until(factory, *, timeout: float, interval: float = 1.0, what: str = "condition"):
    """Async twin of wait_until: poll `await factory()` until truthy (observable condition)."""
    import asyncio

    deadline = time.monotonic() + timeout
    attempts, last = 0, None
    while time.monotonic() < deadline:
        attempts += 1
        last = await factory()
        if last:
            return last
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s ({attempts} attempts) waiting for {what}")
