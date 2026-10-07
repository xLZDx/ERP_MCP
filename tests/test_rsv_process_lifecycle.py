"""Exercise production client using actual SDK sessions and disposable child processes."""
from __future__ import annotations

import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import mcp.client.stdio as sdk_stdio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters

from business_ai_gateway.adapters.onec import rsv_privacy
from business_ai_gateway.adapters.onec.rsv_bridge import RSVBridgeUnavailable, RSVDataBridgeClient
from business_ai_gateway.adapters.onec.rsv_privacy import quiet_stdio_client
from business_ai_gateway.models import Source

FAKE = Path(__file__).resolve().parents[1] / "scripts" / "mcp_rsv_fixture.py"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["crash", "timeout", "malformed", "wire_flood", "wire_oversized_json"])
async def test_actual_mcp_process_failure_then_new_process_recovers(tmp_path, mode, monkeypatch, caplog):
    parsed_private_lines = []
    malformed_parsed = []
    enforced_wire_limits = []
    if mode.startswith('wire_'):
        parse_line = sdk_stdio._parse_line
        original_limit_error = rsv_privacy.RSVWireLimitExceeded

        class ObservedWireLimit(original_limit_error):
            def __init__(self, *args):
                enforced_wire_limits.append(True)
                super().__init__(*args)

        monkeypatch.setattr(rsv_privacy, 'RSVWireLimitExceeded', ObservedWireLimit)

        def record_parser(line):
            if 'WIRE_PRIVATE_SECRET' in line:
                parsed_private_lines.append(True)
            return parse_line(line)

        monkeypatch.setattr(sdk_stdio, '_parse_line', record_parser)
    elif mode == 'malformed':
        parse_line = sdk_stdio._parse_line

        def record_malformed(line):
            if '"result":[]' in line:
                malformed_parsed.append(True)
            return parse_line(line)

        monkeypatch.setattr(sdk_stdio, '_parse_line', record_malformed)
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
        async with quiet_stdio_client(child) as streams:
            yield streams

    class BoundedToolSession(ClientSession):
        async def call_tool(self, name, arguments):
            return await super().call_tool(name, arguments, read_timeout_seconds=20 if mode.startswith('wire_') else 2)

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
    assert 'WIRE_PRIVATE_SECRET' not in str(failure.value) + caplog.text
    assert parsed_private_lines == []  # both undelimited and valid oversized responses blocked before JSON parse
    if mode.startswith('wire_'):
        assert enforced_wire_limits  # timeout alone is not evidence that the guard rejected stdout
    if mode == 'malformed':
        assert malformed_parsed  # handler stdout diversion must not turn this into another timeout-only case
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
