# ruff: noqa: SIM117
"""Black-box harness: real MCP Streamable-HTTP client + read-only evidence readers.

No gateway internals are imported. Environment contract (also in docs/FUNCTIONAL_TESTER...):

  FT_MCP_URL                 required  gateway MCP endpoint, e.g. http://127.0.0.1:28000/mcp
  FT_ADMIN_DATABASE_URL      required  DSN used ONLY for setup (scripts/admin.py) and audit reads
  FT_FAKE1C_URL              required  base URL of the recording Fake1C wrapper
  FT_SOURCE_ID               default fake1c-local
  FT_COMPANY_ONE_ID/TWO_ID   default synthetic org one/two UUIDs
  FT_PRINCIPAL               subject whose grant is revoked/re-added (default FT_DEV_PRINCIPAL
                             or development-local); in OIDC mode the token subject
  FT_BEARER_TOKEN            optional  main identity token (omit in dev mode)
  FT_BEARER_TOKEN_NO_ACCESS  optional  identity with no grants (activates needs-oidc cases)
  FT_BEARER_TOKEN_COMPANY_TWO optional identity granted company two only
  FT_GATEWAY_LOG             optional  gateway log file (stdout; '.err' sibling also scanned)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

REPO_ROOT = Path(__file__).resolve().parents[3]
MISSING = "functional stack env absent (set FT_MCP_URL, FT_ADMIN_DATABASE_URL, FT_FAKE1C_URL; see scripts/ft/setup.ps1)"


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value else default


def stack_configured() -> bool:
    return all(env(n) for n in ("FT_MCP_URL", "FT_ADMIN_DATABASE_URL", "FT_FAKE1C_URL"))


SOURCE_ID = env("FT_SOURCE_ID", "fake1c-local")
COMPANY_ONE = env("FT_COMPANY_ONE_ID", "00000000-0000-0000-0000-000000000001")
COMPANY_TWO = env("FT_COMPANY_TWO_ID", "00000000-0000-0000-0000-000000000002")
PRINCIPAL = env("FT_PRINCIPAL") or env("FT_DEV_PRINCIPAL", "development-local")


@dataclass
class Outcome:
    tool: str
    is_error: bool
    data: Any = None
    text: str = ""
    transport_error: str | None = None
    started_db: Any = None
    fake_seq: int = 0
    audit: list[dict] = field(default_factory=list)
    upstream: list[dict] = field(default_factory=list)
    sidecar: list[dict] = field(default_factory=list)
    sidecar_seq: int = 0

    @property
    def ok(self) -> bool:
        return not self.is_error and self.transport_error is None


def _unwrap(structured: Any) -> Any:
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]
    return structured


async def _raw_call(tool: str, args: dict, token: str | None) -> Outcome:
    client = None
    token = token or env("FT_BEARER_TOKEN")
    if token:
        client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60)
    try:
        async with streamable_http_client(env("FT_MCP_URL"), http_client=client) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                text = " ".join(getattr(c, "text", "") or "" for c in res.content)
                return Outcome(
                    tool, bool(res.is_error), _unwrap(res.structured_content), text
                )
    except BaseException as exc:  # noqa: BLE001 - transport/protocol failure is evidence
        leaf = exc
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        return Outcome(tool, True, None, "", f"{type(leaf).__name__}: {str(leaf)[:200]}")
    finally:
        if client is not None:
            await client.aclose()


async def list_tool_names(token: str | None = None) -> list[str]:
    token = token or env("FT_BEARER_TOKEN")
    client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) if token else None
    try:
        async with streamable_http_client(env("FT_MCP_URL"), http_client=client) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return sorted(t.name for t in (await session.list_tools()).tools)
    finally:
        if client is not None:
            await client.aclose()


async def db_fetch(sql: str, *args):
    conn = await asyncpg.connect(env("FT_ADMIN_DATABASE_URL"))
    try:
        return [dict(r) for r in await conn.fetch(sql, *args)]
    finally:
        await conn.close()


async def db_now():
    return (await db_fetch("SELECT clock_timestamp() AS now"))[0]["now"]


def _requests_of(url: str | None, since: int) -> dict:
    if not url:
        return {"last_seq": 0, "requests": []}
    r = httpx.get(url.rstrip("/") + "/__ft__/requests", params={"since": since}, timeout=10)
    r.raise_for_status()
    return r.json()


def fake_requests(since: int = 0) -> dict:
    return _requests_of(env("FT_FAKE1C_URL"), since)


def sidecar_requests(since: int = 0) -> dict:
    """Requests seen by the recording fake-sidecar wrapper (empty when FT_SIDECAR_URL is unset)."""
    return _requests_of(env("FT_SIDECAR_URL"), since)


SIDECAR_READ_PATHS = {"/v1/read", "/v1/capabilities/registers"}


def fake_mark() -> int:
    return fake_requests(10**9)["last_seq"]


async def call(tool: str, args: dict | None = None, *, token: str | None = None) -> Outcome:
    """Call one public MCP tool and attach the audit rows + upstream requests it caused."""
    args = args or {}
    started = await db_now()
    seq = fake_mark()
    sc_seq = sidecar_requests(10**9)["last_seq"]
    out = await _raw_call(tool, args, token)
    out.started_db, out.fake_seq, out.sidecar_seq = started, seq, sc_seq
    # Audit append is awaited before the response, but poll briefly for visibility.
    for _ in range(20):
        out.audit = await db_fetch(
            "SELECT * FROM bag.audit_events WHERE occurred_at >= $1 AND tool_name=$2 "
            "ORDER BY occurred_at, event_id",
            started,
            tool,
        )
        if out.audit:
            break
        await asyncio.sleep(0.25)
    out.upstream = fake_requests(seq)["requests"]
    out.sidecar = sidecar_requests(sc_seq)["requests"]
    return out


def no_write_reached_1c(out: Outcome) -> bool:
    """Fake1C saw only GET/HEAD; the read-only sidecar protocol saw only POST /v1/read|capabilities."""
    return ({r["method"] for r in out.upstream} <= {"GET", "HEAD"}
            and all(r["method"] == "POST" and r["path"] in SIDECAR_READ_PATHS for r in out.sidecar))


def business_reads(out: Outcome) -> list[dict]:
    """Requests that could carry business data: Fake1C filtered GETs or any sidecar read."""
    return ([r for r in out.upstream if "$filter" in r["query_keys"]]
            + [r for r in out.sidecar if r["path"] == "/v1/read"])


def entity_gets(out: Outcome) -> list[dict]:
    """Upstream requests that touched business data (not $metadata)."""
    return [r for r in out.upstream if "$metadata" not in r["path"]]


def final_audit(out: Outcome) -> dict:
    assert out.audit, f"no audit row for {out.tool}"
    return out.audit[-1]


def gateway_log_text() -> str | None:
    base = env("FT_GATEWAY_LOG")
    if not base:
        return None
    parts = []
    for p in (base, base + ".err"):
        if os.path.exists(p):
            parts.append(Path(p).read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def log_has_request_id(request_id: str, wait: float = 5.0) -> bool:
    # uvicorn wraps long log lines on a console-width; strip whitespace/newlines before matching.
    deadline = time.time() + wait
    while time.time() < deadline:
        text = gateway_log_text()
        if text is None:
            return False
        if request_id in re.sub(r"\s+", "", text):
            return True
        time.sleep(0.3)
    return False


def admin_cli(*cli_args: str) -> subprocess.CompletedProcess:
    """Run scripts/admin.py with the evidence/setup DSN (dev-mode grant revoke/re-add)."""
    e = dict(os.environ)
    e["BAG_ADMIN_DATABASE_URL"] = env("FT_ADMIN_DATABASE_URL")
    e["BAG_DATABASE_URL"] = env("FT_ADMIN_DATABASE_URL")
    e["BAG_ENVIRONMENT"] = env("BAG_ENVIRONMENT", "development")
    e["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "admin.py"), *cli_args],
        cwd=REPO_ROOT, env=e, capture_output=True, text=True, timeout=60, check=True,
    )


def rand_uuid() -> str:
    return str(uuid.uuid4())


def dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
