"""Fixtures specific to the data-plane User suite (U01-U18).

Lane A's tests/e2e/conftest.py provides e2e_env, idp, mcp_client, admin_http, db and
tool_payload; this module only adds user-suite fixtures on top (nothing there is modified).
"""

from __future__ import annotations

import httpx
import pytest
from user_support import GrantAdmin, UpstreamLog, call_tool


@pytest.fixture(scope="session")
def ids(e2e_env):
    """Stable identifiers of the baseline seed."""
    return {
        "source": e2e_env.raw["source_id"],
        "one": e2e_env.raw["companies"]["one"],
        "two": e2e_env.raw["companies"]["two"],
        "uc1": "user_company_one", "uc2": "user_company_two", "una": "user_no_access",
    }


@pytest.fixture
def fake1c_log(e2e_env) -> UpstreamLog:
    """Recording reader over Fake1C AND the fake sidecar (all gateway upstream traffic).

    Fails (never skips) when Fake1C runs without the recorder."""
    host, ports = e2e_env.raw["host"], e2e_env.raw["ports"]
    log = UpstreamLog(f"http://{host}:{ports['fake1c']}", f"http://{host}:{ports['sidecar']}")
    before = log.mark()
    probe = httpx.get(e2e_env.fake1c_url + "/$metadata", trust_env=False, timeout=10,
                      headers={"User-Agent": "e2e-recorder-probe"})
    assert probe.status_code == 200
    after = log.since(before, gateway_only=False)
    assert any(r["user_agent"] == "e2e-recorder-probe" for r in after), (
        "Fake1C is not running the recording wrapper (testbed/fake1c/app.py); restart it: "
        "scripts/e2e/fault.ps1 -Component fake1c -Action restart")
    return log


@pytest.fixture
def grants(admin_http, ids) -> GrantAdmin:
    """Grant lifecycle via the Admin API as the bootstrapped PLATFORM_ADMIN."""
    return GrantAdmin(admin_http("platform_admin"), ids["source"])


@pytest.fixture
def uc1_company_grant(grants, ids):
    """Guarantee the baseline UC1 -> company one grant exists again after the test."""
    grants.ensure("subject", ids["uc1"], ids["one"], "E2E baseline grant (setup)")
    yield grants
    grants.ensure("subject", ids["uc1"], ids["one"], "E2E baseline grant (restore)")


@pytest.fixture
def tokens(idp, ids):
    """Fresh data-plane tokens for the three user identities."""
    return {"uc1": idp.token(ids["uc1"]), "uc2": idp.token(ids["uc2"]),
            "una": idp.token(ids["una"])}


@pytest.fixture
def call(mcp_client):
    """``await call(token, tool, args)`` -> ToolOutcome."""

    async def _call(token, tool, args=None):
        return await call_tool(mcp_client, token, tool, args)

    return _call
