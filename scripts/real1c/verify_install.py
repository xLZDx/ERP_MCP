"""Opt-in, non-mutating, privacy-safe MCP smoke against a registered real 1C L2 testbed.

Requires disposable E2E_REAL1C=1 bootstrap, read-only 1C publication and the
explicitly scoped test auditor data grant. Never seeds data or changes grants.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import asyncpg

from scripts.real1c.gateway_client import Idp, LaneEnv, call_tool, mcp_session
from scripts.real1c.lane_setup import SOURCE_DOWN, SOURCE_DRIFT, SOURCE_REAL


@dataclass(frozen=True)
class Check:
    principal: str
    tool: str
    source_id: str
    should_allow: bool


CHECKS = (
    Check("auditor", "source_health", SOURCE_REAL, True),
    Check("auditor", "onec_capabilities", SOURCE_REAL, True),
    Check("auditor", "source_health", SOURCE_DRIFT, False),
    Check("auditor", "onec_capabilities", SOURCE_DOWN, False),
    Check("user_company_one", "source_health", SOURCE_REAL, False),
    Check("user_company_one", "onec_capabilities", SOURCE_REAL, False),
    Check("user_no_access", "source_health", SOURCE_REAL, False),
)


def ensure_disposable(env: LaneEnv) -> None:
    """Refuse to run the test utility against a real production environment."""
    raw = env.raw
    if (
        raw.get("environment") != "test"
        or raw.get("real1c") is not True
        or raw.get("seed_mode") != "bootstrap-only"
        or raw.get("host") != "127.0.0.1"
        or not str(raw.get("project", "")).startswith("erpmcp-e2e")
        or not str(raw.get("urls", {}).get("gateway", "")).startswith("http://127.0.0.1:")
    ):
        raise RuntimeError("REAL1C_SMOKE_REQUIRES_DISPOSABLE_LOOPBACK_TEST")


async def audit_detail(conn: asyncpg.Connection, check: Check, since) -> str | None:
    for _ in range(8):
        detail = await conn.fetchval(
            """SELECT detail_code FROM bag.audit_events
               WHERE principal_subject=$1 AND tool_name=$2 AND source_id=$3
                 AND occurred_at >= $4
               ORDER BY occurred_at DESC LIMIT 1""",
            check.principal, check.tool, check.source_id, since,
        )
        if detail:
            return detail
        await asyncio.sleep(0.15)
    return None


async def run() -> int:
    env = LaneEnv.load()
    ensure_disposable(env)
    idp = Idp(env)
    conn = await asyncpg.connect(env.dsn("admin"), timeout=10)
    passed = 0
    try:
        for check in CHECKS:
            try:
                start = await conn.fetchval("SELECT clock_timestamp()")
                async with mcp_session(env, idp.token(check.principal)) as session:
                    result = await call_tool(session, check.tool, {"source_id": check.source_id})
                detail = await audit_detail(conn, check, start)
                payload = result["payload"] if isinstance(result["payload"], dict) else {}
                if check.should_allow:
                    ok = not result["is_error"]
                    if check.tool == "source_health":
                        ok = ok and payload.get("status_code") == 200
                    else:
                        ok = (
                            ok and payload.get("compatibility_status") == "SUPPORTED"
                            and isinstance(payload.get("entity_set_count"), int)
                            and payload["entity_set_count"] > 0
                        )
                    ok = ok and detail in (None, "ACCESS_AUTHORIZED")
                else:
                    ok = result["is_error"] and detail == "AccessDenied"
                print(
                    ("PASS" if ok else "FAIL"), check.principal,
                    check.tool, check.source_id, "denied" if not check.should_allow else "allowed",
                    "audit=" + str(detail),
                    flush=True,
                )
            except Exception as exc:  # explicit test failure, never print secrets, tokens, URLs or responses
                print("FAIL", check.principal, check.tool, type(exc).__name__, flush=True)
                ok = False
            passed += int(ok)
    finally:
        await conn.close()
    print(f"REAL1C_L2_INSTALL_SMOKE {passed}/{len(CHECKS)} PASS", flush=True)
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
