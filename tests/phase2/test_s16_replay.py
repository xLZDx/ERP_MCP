"""REQ-013 / V2-S16-05: replay labeled client-shaped fixtures through the serialized tool boundary."""
import asyncio

from erp_mcp_s16.tools import register_s16_tools
from tests.phase2.s16_helpers import build_env, raw_create
from tests.phase2.test_s16_tools import Server


def test_recorded_chatgpt_and_claude_shaped_fixtures_replay_without_claim_authority():
    env, server = build_env(), Server()
    register_s16_tools(server, env.change_service, lambda context: context)
    fixtures = (
        {"provenance": "hand-authored-chatgpt-shape-fixture", "tool": "propose",
         "arguments": {"request": raw_create()}},
        {"provenance": "hand-authored-claude-shape-fixture", "tool": "status",
         "arguments": {"change_id": "00000000-0000-4000-8000-000000000001"}},
    )
    result = []
    for item in fixtures:
        response = asyncio.run(server.handlers[item["tool"]][0](item["arguments"], env.requester))
        assert item["provenance"].startswith("hand-authored-")
        result.append(response)
    assert result[0]["isError"] is False
    assert result[1]["isError"] is True
    assert env.apply_port.calls == 0

