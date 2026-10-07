from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from business_ai_gateway.server import (
    CHATGPT_READ_ONLY_ANNOTATIONS,
    CHATGPT_SERVER_INSTRUCTIONS,
    build_mcp,
)
from business_ai_gateway.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_all_public_mcp_tools_are_explicitly_read_only_for_chatgpt():
    tools = await build_mcp(Settings(_env_file=None), SimpleNamespace()).list_tools()
    assert len(tools) >= 19

    for tool in tools:
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name
        wire = tool.annotations.model_dump(by_alias=True)
        assert wire["readOnlyHint"] is True, tool.name
        assert wire["destructiveHint"] is False, tool.name
        assert wire["openWorldHint"] is True, tool.name


def test_chatgpt_server_instructions_preserve_policy_boundaries():
    text = CHATGPT_SERVER_INSTRUCTIONS.lower()
    assert "read-only" in text
    assert "never invent identifiers" in text
    assert "company" in text
    assert "credentials" in text
    assert "synthetic" in text
    assert CHATGPT_READ_ONLY_ANNOTATIONS.read_only_hint is True
    assert CHATGPT_READ_ONLY_ANNOTATIONS.destructive_hint is False


def test_chatgpt_local_scripts_do_not_embed_openai_api_keys():
    scripts = list((ROOT / "scripts" / "chatgpt").glob("*"))
    assert scripts
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in scripts if path.is_file()
    )
    assert "sk-" not in combined
    assert "CONTROL_PLANE_API_KEY" in combined
    assert "sample_mcp_remote_no_auth" in combined
    assert "OPENAI_ADMIN_KEY" not in combined


def test_chatgpt_local_prepare_is_hard_scoped_to_synthetic_fake1c():
    text = (ROOT / "scripts" / "chatgpt" / "local_prepare.py").read_text(encoding="utf-8")
    assert 'DEFAULT_SOURCE_ID = "fake1c-e2e"' in text
    assert "CHATGPT_LOCAL_PREPARE_REQUIRES_SYNTHETIC_TEST_ENVIRONMENT" in text
    assert "CHATGPT_LOCAL_PREPARE_REFUSES_NON_FAKE1C_SOURCE" in text
    assert '"synthetic-fixture"' in text


def test_tunnel_installer_is_pinned_and_checksum_verified():
    text = (ROOT / "scripts" / "chatgpt" / "install-tunnel-client.ps1").read_text(
        encoding="utf-8"
    )
    assert "[string]$Version = 'v0.0.16'" in text
    assert "SHA256SUMS.txt" in text
    assert "Get-FileHash" in text
    assert "archive SHA256 mismatch" in text


def test_chatgpt_docs_exist_and_keep_admin_out_of_tunnel():
    doc = (ROOT / "docs" / "CHATGPT_MCP_INTEGRATION.md").read_text(encoding="utf-8")
    assert "Secure MCP Tunnel" in doc
    assert "Admin API/UI" in doc
    assert "read-only" in doc
    assert "production" in doc.lower()
