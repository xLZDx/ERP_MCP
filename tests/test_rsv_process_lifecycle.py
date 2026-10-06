"""Exercise production client using actual SDK sessions and disposable child processes."""
from __future__ import annotations

import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from business_ai_gateway.adapters.onec.rsv_bridge import RSVBridgeUnavailable, RSVDataBridgeClient
from business_ai_gateway.models import Source

FAKE = Path(__file__).resolve().parents[1] / "scripts" / "mcp_rsv_fixture.py"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["crash", "timeout", "malformed"])
async def test_actual_mcp_process_failure_then_new_process_recovers(tmp_path, mode):
    source = Source(id="synthetic", project="onec", kind="onec_auto", display_name="synthetic",
                    base_url="https://example.invalid", username_secret_ref=None,
                    password_secret_ref=None, read_only=True, enabled=True, tags=(),
                    entity_allow_patterns=(), entity_deny_patterns=())
    state = {"mode": mode, "generation": 1}
    paths = []
    launches = []

    async def loader(_reference):
        return json.dumps({"generation": state["generation"]})

    @asynccontextmanager
    async def actual_stdio(parameters):
        config = Path(parameters.args[-1])
        paths.append(config)
        launches.append(state["mode"])
        child = StdioServerParameters(command=sys.executable,
                                      args=[str(FAKE), state["mode"], str(config), str(tmp_path / "called")],
                                      env=parameters.env)
        async with stdio_client(child) as streams:
            yield streams

    class BoundedToolSession(ClientSession):
        async def call_tool(self, name, arguments):
            return await super().call_tool(name, arguments, read_timeout_seconds=2)

    client = RSVDataBridgeClient(executable=sys.executable, config_root=str(tmp_path),
                                stdio_factory=actual_stdio, session_factory=BoundedToolSession,
                                timeout_seconds=45,
                                config_secret_loader=loader, config_secret_ref="synthetic-config")
    started = time.monotonic()
    with pytest.raises(RSVBridgeUnavailable) as failure:
        await client.health(source)
    assert time.monotonic() - started < 55
    assert (tmp_path / "called").read_text(encoding="utf-8") == mode
    assert "generation" not in str(failure.value)
    assert all(not path.exists() for path in paths)
    state.update(mode="healthy", generation=2)
    result = await client.metadata(source, operation="config")
    assert result["data"] == {"generation": 2}
    assert launches == [mode, "healthy"]
    assert all(not path.exists() for path in paths)
    state["generation"] = 3
    rotated = await client.metadata(source, operation="config")
    assert rotated["data"] == {"generation": 3}
    assert len(paths) == 3 and len(set(paths)) == 3
    assert all(not path.exists() for path in paths)
