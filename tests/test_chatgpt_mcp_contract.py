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
from business_ai_gateway.principal import Principal
from business_ai_gateway.models import Source

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_all_public_mcp_tools_are_explicitly_read_only_for_chatgpt():
    tools = await build_mcp(Settings(_env_file=None), SimpleNamespace()).list_tools()
    expected_r1 = {
        "system_status", "sources_list", "source_health", "rsv_metadata", "companies_list",
        "onec_capabilities", "onec_metadata_summary", "onec_find_entities",
        "accounting_balance_and_turnovers", "inventory_balance", "inventory_movements",
        "accounting_posting_rows", "cash_movements", "bank_balance", "receivable_balance",
        "payable_balance", "sales_documents", "purchase_documents", "onec_read",
    }
    expected_additive = {
        "external_evidence_manifest", "accounting_balance_by_analytics", "counterparty_find",
        "receivable_aging", "payable_aging", "counterparty_duplicate_candidates",
        "onec_find_entities_with_property_types", "accounting_balance_and_turnovers_by_account",
        "purchase_documents_filtered", "onec_metadata_schema_detail",
    }
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == expected_r1 | expected_additive
    mcp = build_mcp(Settings(_env_file=None), SimpleNamespace())
    assert mcp._structured_error_tool_names == expected_additive

    # The old wire signatures remain frozen; the additive behavior has distinct names.
    assert set(by_name["onec_find_entities"].input_schema["properties"]) == {
        "source_id", "contains", "limit"
    }
    assert "include_property_types" not in by_name["onec_find_entities"].input_schema["properties"]
    assert set(by_name["accounting_balance_and_turnovers"].input_schema["properties"]) == {
        "source_id", "company_id", "start_period", "end_period"
    }
    assert set(by_name["purchase_documents"].input_schema["properties"]) == {
        "source_id", "company_id", "top", "skip"
    }
    detail_schema = by_name["onec_metadata_schema_detail"].input_schema
    assert detail_schema["required"] == ["source_id", "company_id"]
    assert detail_schema["additionalProperties"] is False

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


def _detail_source(source_id="detail-source"):
    return Source(
        id=source_id, project="onec", kind="onec_odata", display_name="test",
        base_url="https://example.test/odata", username_secret_ref=None,
        password_secret_ref=None, read_only=True, enabled=True, tags=(),
        entity_allow_patterns=("*",), entity_deny_patterns=(),
    )


def _detail_principal():
    return Principal("subject", "client", frozenset({"onec:read"}), frozenset(), {})


@pytest.mark.asyncio
async def test_metadata_detail_allowlist_refusal_precedes_success_audit_and_provider(monkeypatch):
    from unittest.mock import AsyncMock
    import business_ai_gateway.server as server_module

    audit = SimpleNamespace(write=AsyncMock())
    rate_limit = SimpleNamespace(check=AsyncMock())
    runtime = SimpleNamespace(audit=audit, rate_limit=rate_limit)
    settings = Settings(_env_file=None, business_capability_enforcement_enabled=False)
    monkeypatch.setattr(server_module, "current_principal", lambda **_kwargs: _detail_principal())
    mcp = build_mcp(settings, runtime)
    tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "onec_metadata_schema_detail")

    with pytest.raises(PermissionError, match="METADATA_DETAIL_SOURCE_NOT_ALLOWLISTED"):
        await tool.fn(source_id="detail-source", company_id="00000000-0000-0000-0000-000000000001")

    rate_limit.check.assert_awaited_once_with(
        subject="subject", source_id="__metadata_detail_scope__",
        tool="onec_metadata_schema_detail",
    )
    assert [call.kwargs["outcome"] for call in audit.write.await_args_list] == ["denied"]
    assert all(call.kwargs.get("detail_code") != "ACCESS_AUTHORIZED" for call in audit.write.await_args_list)


@pytest.mark.asyncio
async def test_metadata_detail_always_requires_metadata_grant_before_provider(monkeypatch):
    from unittest.mock import AsyncMock
    import business_ai_gateway.server as server_module

    source = _detail_source()
    grant_error = PermissionError("missing metadata.read")
    registry = SimpleNamespace(require_source_for_company=AsyncMock(return_value=source))
    policy = SimpleNamespace(require=AsyncMock(side_effect=grant_error), POLICY_VERSION="test-policy")
    audit = SimpleNamespace(write=AsyncMock())
    rate_limit = SimpleNamespace(check=AsyncMock())
    onec = SimpleNamespace(summary=AsyncMock(return_value={"entity_set_count": 0}))
    runtime = SimpleNamespace(
        registry=registry, capability_policy=policy, audit=audit,
        rate_limit=rate_limit, onec=onec,
    )
    settings = Settings(
        _env_file=None, business_capability_enforcement_enabled=False,
        metadata_detail_source_allowlist="detail-source",
    )
    monkeypatch.setattr(server_module, "current_principal", lambda **_kwargs: _detail_principal())
    mcp = build_mcp(settings, runtime)
    tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "onec_metadata_schema_detail")

    with pytest.raises(PermissionError, match="missing metadata.read"):
        await tool.fn(source_id="detail-source", company_id="00000000-0000-0000-0000-000000000001")

    policy.require.assert_awaited_once_with(
        _detail_principal(), "metadata.read", source_id="detail-source",
        company_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000001"),
    )
    onec.summary.assert_not_awaited()
    assert [call.kwargs["outcome"] for call in audit.write.await_args_list] == ["denied"]


@pytest.mark.asyncio
async def test_metadata_detail_source_company_acl_denial_precedes_authorized_receipt_and_provider(monkeypatch):
    from unittest.mock import AsyncMock
    import business_ai_gateway.server as server_module

    events = []
    async def deny_source(*_args):
        events.append("source_acl")
        raise PermissionError("company access denied")

    async def rate_check(**_kwargs):
        events.append("rate_limit")

    async def audit_write(**kwargs):
        events.append(kwargs.get("detail_code") or kwargs["outcome"])

    registry = SimpleNamespace(require_source_for_company=AsyncMock(side_effect=deny_source))
    policy = SimpleNamespace(require=AsyncMock(return_value=None), POLICY_VERSION="test-policy")
    audit = SimpleNamespace(write=AsyncMock(side_effect=audit_write))
    rate_limit = SimpleNamespace(check=AsyncMock(side_effect=rate_check))
    onec = SimpleNamespace(summary=AsyncMock(return_value={"entity_set_count": 0}))
    runtime = SimpleNamespace(
        registry=registry, capability_policy=policy, audit=audit,
        rate_limit=rate_limit, onec=onec,
    )
    settings = Settings(
        _env_file=None, business_capability_enforcement_enabled=False,
        metadata_detail_source_allowlist="detail-source",
    )
    monkeypatch.setattr(server_module, "current_principal", lambda **_kwargs: _detail_principal())
    mcp = build_mcp(settings, runtime)
    tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "onec_metadata_schema_detail")

    with pytest.raises(PermissionError, match="company access denied"):
        await tool.fn(source_id="detail-source", company_id="00000000-0000-0000-0000-000000000001")

    assert events == ["rate_limit", "source_acl", "PermissionError"]
    policy.require.assert_not_awaited()
    onec.summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_metadata_detail_success_after_all_grants_is_marked_metadata_only(monkeypatch):
    from unittest.mock import AsyncMock
    import uuid
    import business_ai_gateway.server as server_module

    source = _detail_source()
    registry = SimpleNamespace(require_source_for_company=AsyncMock(return_value=source))
    policy = SimpleNamespace(require=AsyncMock(return_value=None), POLICY_VERSION="test-policy")
    audit = SimpleNamespace(write=AsyncMock())
    rate_limit = SimpleNamespace(check=AsyncMock())
    onec = SimpleNamespace(summary=AsyncMock(return_value={"entity_set_count": 0}))
    runtime = SimpleNamespace(
        registry=registry, capability_policy=policy, audit=audit,
        rate_limit=rate_limit, onec=onec,
    )
    settings = Settings(
        _env_file=None, business_capability_enforcement_enabled=False,
        metadata_detail_source_allowlist="detail-source",
    )
    monkeypatch.setattr(server_module, "current_principal", lambda **_kwargs: _detail_principal())
    mcp = build_mcp(settings, runtime)
    tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "onec_metadata_schema_detail")

    response = await tool.fn(
        source_id="detail-source", company_id="00000000-0000-0000-0000-000000000001"
    )

    policy.require.assert_awaited_once()
    onec.summary.assert_awaited_once_with(
        source, include_information_register_schemas=False,
        include_period_schema_candidates=True,
    )
    assert response == {"entity_set_count": 0, "evidence_kind": "METADATA_ONLY"}
    assert [call.kwargs.get("detail_code") for call in audit.write.await_args_list] == [
        "ACCESS_AUTHORIZED", None
    ]
