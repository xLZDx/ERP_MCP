"""Execution context of the real-1C lane: MCP calls with audit correlation, proxy control and DB evidence reads."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx

from scripts.real1c.gateway_client import Idp, LaneEnv, call_tool, mcp_session

SRC_REAL = "onec-818ha-reference"
SRC_DRIFT = "onec-818ha-drift"
SRC_DOWN = "onec-818ha-down"
PROXY_PORT = {SRC_REAL: 8191, SRC_DRIFT: 8192, SRC_DOWN: 8193}
MUTATING_NAME = r"(?i)(^|_)(create|update|delete|remove|post|write|send|merge|close|execute|insert|upsert|import|set|approve|submit)(_|$)"


class ProxyCtl:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}/__lane__"

    def mode(self, name: str, delay: float | None = None) -> dict:
        params: dict[str, Any] = {"name": name}
        if delay is not None:
            params["delay"] = delay
        return httpx.post(f"{self.base}/mode", params=params, timeout=10, trust_env=False).json()

    def requests(self) -> dict:
        return httpx.get(f"{self.base}/requests", timeout=10, trust_env=False).json()

    def reset(self) -> None:
        httpx.post(f"{self.base}/reset", timeout=10, trust_env=False)


@dataclass
class Lane:
    env: LaneEnv
    idp: Idp
    db: asyncpg.Connection
    real_company: str
    syn_company: str
    _tokens: dict[str, tuple[float, str]] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)
    _db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

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
        try:
            async with mcp_session(self.env, self.token(user)) as session:
                result = await call_tool(session, tool, args)
        except Exception as exc:  # noqa: BLE001 - transport failures are observations
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
        record = {"user": user, "tool": tool, "ms": elapsed_ms, "is_error": result["is_error"],
                  "payload": result["payload"], "text": result["text"][:200],
                  "audit": dict(audit) if audit else None}
        self.calls.append({**{k: record[k] for k in ("user", "tool", "ms", "is_error", "audit")},
                           "expected": correlate and expect_audit})
        return record

    async def list_tools(self, user: str) -> list[dict[str, str]]:
        async with mcp_session(self.env, self.token(user)) as session:
            listed = await session.list_tools()
        return [{"name": t.name, "description": (t.description or "")} for t in listed.tools]

    async def audit_rows_since(self, since: Any) -> list[dict]:
        rows = await self.db.fetch(
            "select tool_name, principal_subject, outcome, detail_code, source_id, company_id "
            "from bag.audit_events where occurred_at >= $1 order by occurred_at", since)
        return [dict(r) for r in rows]
