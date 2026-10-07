"""Execution context of the real-1C lane: MCP calls with audit correlation, proxy control and DB evidence reads."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx

from scripts.real1c.gateway_client import Idp, LaneEnv, call_tool, mcp_session
from scripts.real1c.sanitize import redact_text

SRC_REAL = "onec-818ha-reference"
SRC_DRIFT = "onec-818ha-drift"
SRC_DOWN = "onec-818ha-down"
PROXY_PORT = {SRC_REAL: 8191, SRC_DRIFT: 8192, SRC_DOWN: 8193}
MUTATING_NAME = r"(?i)(^|_)(create|update|delete|remove|post|write|send|merge|close|execute|insert|upsert|import|set|approve|submit)(_|$)"


_RESPONSE_SCALARS = {"ok", "status", "status_code", "detail", "code", "error", "count", "has_more", "truncated", "mode",
                     "drift_status", "compatibility_status", "read_only", "business_acceptance", "native_approval_inferred"}


def _safe_args(value: Any, depth: int = 0) -> Any:
    """Arguments of a tool call for the test documentation: identifiers hashed, long lists cut."""
    if isinstance(value, str):
        return redact_text(value)[:160]
    if isinstance(value, dict):
        return {str(k): _safe_args(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_safe_args(v, depth + 1) for v in value[:12]] + (["…"] if len(value) > 12 else [])
    return value


def summarize_response(payload: Any, text: str, is_error: bool) -> dict[str, Any]:
    """Shape of a tool answer without any business value: key names, row counts and an allowlist of status scalars."""
    out: dict[str, Any] = {}
    if isinstance(payload, dict):
        out["keys"] = sorted(str(k) for k in payload)[:14]
        for key in _RESPONSE_SCALARS & set(payload):
            if isinstance(payload[key], (str, int, float, bool)) or payload[key] is None:
                out[key] = payload[key] if not isinstance(payload[key], str) else redact_text(payload[key])[:120]
        if isinstance(payload.get("value"), list):
            out["rows"] = len(payload["value"])
        page = payload.get("page")
        if isinstance(page, dict):
            out["page"] = {k: page[k] for k in ("has_more", "truncated", "returned") if k in page}
    elif isinstance(payload, list):
        out["items"] = len(payload)
    if is_error or not out:
        out["text"] = redact_text(text or "")[:200]
    return out


class ProxyCtl:
    """Control channel of one loopback proxy; every call is checked, a silent failure would void the injected fault."""

    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}/__lane__"

    def mode(self, name: str, delay: float | None = None) -> dict:
        params: dict[str, Any] = {"name": name}
        if delay is not None:
            params["delay"] = delay
        r = httpx.post(f"{self.base}/mode", params=params, timeout=10, trust_env=False)
        r.raise_for_status()
        body = r.json()
        if body.get("mode") != name:
            raise RuntimeError(f"proxy {self.base} did not switch to {name!r}: {body}")
        return body

    def requests(self) -> dict:
        r = httpx.get(f"{self.base}/requests", timeout=10, trust_env=False)
        r.raise_for_status()
        body = r.json()
        if "by_method" not in body:
            raise RuntimeError(f"proxy {self.base} returned an unusable request snapshot")
        return body

    def reset(self) -> None:
        httpx.post(f"{self.base}/reset", timeout=10, trust_env=False).raise_for_status()


@dataclass
class Lane:
    env: LaneEnv = field(repr=False)
    idp: Idp = field(repr=False)
    db: asyncpg.Connection
    real_company: str
    syn_company: str
    _tokens: dict[str, tuple[float, str]] = field(default_factory=dict, repr=False)
    calls: list[dict] = field(default_factory=list)
    _db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    call_log: list = field(default_factory=list, repr=False)
    probe_label: str = ""

    @classmethod
    async def open(cls) -> Lane:
        env = LaneEnv.load()
        db = await asyncpg.connect(env.dsn("admin"))
        rows = await db.fetch("select company_id, display_name from bag.companies where source_id=$1", SRC_REAL)
        real = next(str(r["company_id"]) for r in rows if "real reference" in r["display_name"])
        synthetic = next(str(r["company_id"]) for r in rows if "SYNTHETIC" in r["display_name"])
        return cls(env, Idp(env), db, real, synthetic)

    async def close(self) -> None:
        await self.db.close()

    def proxy(self, source_id: str) -> ProxyCtl:
        return ProxyCtl(PROXY_PORT[source_id])

    def token(self, user: str) -> str:
        cached = self._tokens.get(user)
        if cached and time.monotonic() - cached[0] < 120:
            return cached[1]
        token = self.idp.token(user)
        self._tokens[user] = (time.monotonic(), token)
        return token

    async def call(self, user: str, tool: str, args: dict[str, Any] | None = None, *,
                   correlate: bool = True, expect_audit: bool = True) -> dict[str, Any]:
        """One MCP tool call as `user`, correlated with its audit row (typed outcome / detail code).

        correlate=False is for deliberately concurrent calls: the caller reads audit rows per source afterwards."""
        args = args or {}
        async with self._db_lock:
            started_at = await self.db.fetchval("select clock_timestamp()")
        t0 = time.monotonic()
        transport_error = False
        try:
            async with mcp_session(self.env, self.token(user)) as session:
                result = await call_tool(session, tool, args)
        except Exception as exc:  # noqa: BLE001 - transport failures are observations, flagged so no story can read them as a refusal
            transport_error = True
            result = {"is_error": True, "payload": None, "text": f"{type(exc).__name__}"}
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        audit = None
        for _ in range(8 if correlate else 0):
            async with self._db_lock:
                audit = await self.db.fetchrow(
                    "select outcome, detail_code, returned_items from bag.audit_events "
                    "where tool_name=$1 and principal_subject=$2 and occurred_at >= $3 "
                    "order by occurred_at desc limit 1", tool, user, started_at)
            if audit is not None:
                break
            await asyncio.sleep(0.1)
        record = {"user": user, "tool": tool, "ms": elapsed_ms, "is_error": result["is_error"], "transport_error": transport_error,
                  "payload": result["payload"], "text": result["text"][:200],
                  "audit": dict(audit) if audit else None}
        self.calls.append({**{k: record[k] for k in ("user", "tool", "ms", "is_error", "audit")},
                           "expected": correlate and expect_audit})
        self.log_call(user, tool, args, record)
        return record

    def log_call(self, user: str, tool: str, args: dict[str, Any], record: dict[str, Any]) -> None:
        """Documentation trace of one tool call (what was sent, what shape came back); no business values are kept."""
        audit = record.get("audit") or {}
        self.call_log.append({
            "probe": self.probe_label, "principal": user, "tool": tool, "arguments": _safe_args(args),
            "is_error": record["is_error"], "transport_error": record.get("transport_error", False), "ms": record.get("ms"),
            "audit_outcome": audit.get("outcome"), "detail_code": audit.get("detail_code"),
            "returned_items": audit.get("returned_items"),
            "response": summarize_response(record.get("payload"), record.get("text", ""), record["is_error"])})

    async def list_tools(self, user: str) -> list[dict[str, str]]:
        async with mcp_session(self.env, self.token(user)) as session:
            listed = await session.list_tools()
        return [{"name": t.name, "description": (t.description or "")} for t in listed.tools]

    async def audit_rows_since(self, since: Any) -> list[dict]:
        rows = await self.db.fetch(
            "select tool_name, principal_subject, outcome, detail_code, source_id, company_id "
            "from bag.audit_events where occurred_at >= $1 order by occurred_at", since)
        return [dict(r) for r in rows]
