"""R1 turnover compatibility and scoped R2 totals through MCP Streamable HTTP."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from scripts.synthetic_fixture_profiles import concept_mappings

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")
COMPANY_EXTERNAL_REF = "00000000-0000-0000-0000-000000000101"
ACCOUNT_KEY = "11111111-1111-4111-8111-111111111111"
RAW_ROW = {
    "Account_Key": ACCOUNT_KEY,
    "OpeningDebit": 100,
    "OpeningCredit": 0,
    "DebitTurnover": 40,
    "CreditTurnover": 15,
    "ClosingDebit": 125,
    "ClosingCredit": 0,
}
NORMALIZED_ROW = {
    "account": ACCOUNT_KEY,
    "opening_debit": 100,
    "opening_credit": 0,
    "debit_turnover": 40,
    "credit_turnover": 15,
    "closing_debit": 125,
    "closing_credit": 0,
}


class SyntheticRuntime:
    def __init__(self, *, scoped: bool):
        self.audit_events = []
        self.trace = []
        self.register_reads = []
        self.mapping = concept_mappings()["account.balance_and_turnovers"]
        if scoped:
            self.mapping["account_field"] = "Account_Key"
            self.mapping["accounts"] = [{"code": "60.01", "account_key": ACCOUNT_KEY}]

        class Registry:
            async def require_source(inner, principal, source_id):
                assert principal.subject == "synthetic-user"
                assert source_id == "tenant-a"
                return SimpleNamespace(id=source_id, kind="synthetic")

            async def require_company(inner, principal, source_id, company_id):
                assert principal.subject == "synthetic-user"
                assert source_id == "tenant-a"
                assert company_id == COMPANY_ID
                return SimpleNamespace(external_ref=COMPANY_EXTERNAL_REF)

            async def require_source_for_company(inner, principal, source_id, company_id):
                assert principal.subject == "synthetic-user"
                assert (source_id, company_id) == ("tenant-a", COMPANY_ID)
                return SimpleNamespace(id=source_id, kind="synthetic")

            async def save_capabilities(inner, _capabilities):
                return {"drift_status": "UNCHANGED"}

            async def require_account_turnovers_mapping(inner, source_id, company_id):
                assert (source_id, company_id) == ("tenant-a", COMPANY_ID)
                return {
                    "mapping": self.mapping,
                    "profile_fingerprint": "synthetic-profile-v1",
                    "profile_kind": "SYNTHETIC_FIXTURE",
                    "audit_detail_code": "SYNTHETIC_FIXTURE_PROFILE",
                }

        class Audit:
            async def write(inner, **event):
                self.audit_events.append(event)
                self.trace.append(("audit", event.copy()))

        class RateLimit:
            async def check(inner, *, subject, source_id, tool):
                assert (subject, source_id) == ("synthetic-user", "tenant-a")
                assert tool in {
                    "accounting_balance_and_turnovers",
                    "accounting_balance_and_turnovers_by_account",
                }

        class OneC:
            async def capabilities(inner, source, *, refresh=False):
                return SimpleNamespace(
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    metadata_fingerprint="synthetic-metadata-v1",
                )

            async def register_read(inner, source, *, register_set, method, arguments, top):
                assert source.id == "tenant-a"
                assert register_set == "AccountingRegister_Ledger"
                assert method == "balanceAndTurnovers"
                assert arguments["Condition"] == f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'"
                assert arguments["Period"] == {
                    "from": "2026-04-01T00:00:00+00:00",
                    "to": "2026-04-30T00:00:00+00:00",
                }
                self.register_reads.append((register_set, method, arguments, top))
                self.trace.append(("adapter_dispatch", arguments.copy()))
                return {"value": [dict(RAW_ROW)], "page": {"has_more": False}}

        self.registry = Registry()
        self.audit = Audit()
        self.rate_limit = RateLimit()
        self.onec = OneC()
        self.capability_policy = None

    async def start(self):
        return None

    async def close(self):
        return None


def _call_http_tool(runtime: SyntheticRuntime, name: str, arguments: dict, monkeypatch):
    import business_ai_gateway.server as server_module

    expected_server = os.environ.get("TC001_EXPECT_SERVER_FILE")
    if expected_server:
        assert Path(server_module.__file__).resolve() == Path(expected_server).resolve()

    from business_ai_gateway.principal import Principal

    monkeypatch.setattr(server_module, "current_principal", lambda *, oauth_enabled: Principal(
        subject="synthetic-user", client_id="synthetic-client",
        scopes=frozenset({"onec:read"}), groups=frozenset(), claims={},
    ))
    settings = Settings(environment="test", public_mcp_url="http://testserver/mcp")
    mcp = build_mcp(settings, runtime)
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp", json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        initialized = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "tc001-turnover", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        session = initialized.headers["mcp-session-id"]
        notification = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "mcp-session-id": session},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert notification.status_code == 202, notification.text
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "mcp-session-id": session},
            json={
                "jsonrpc": "2.0", "id": 9, "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError"), result
        return json.loads(result["content"][0]["text"])


def _request_args() -> dict:
    return {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "start_period": "2026-04-01T00:00:00+00:00",
        "end_period": "2026-04-30T00:00:00+00:00",
    }


def _assert_one_business_outcome_and_ordered_optional_receipt(runtime: SyntheticRuntime, tool: str):
    tool_events = [event for event in runtime.audit_events if event.get("tool") == tool]
    outcomes = [event for event in tool_events if event.get("record_tool_outcome") is not False]
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"] == "success"
    assert outcomes[0].get("profile_fingerprint") == "synthetic-profile-v1"
    assert outcomes[0].get("detail_code") in {None, "SYNTHETIC_FIXTURE_PROFILE"}

    receipts = [event for event in tool_events if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    is_baseline = os.environ.get("TC001_BASELINE_EXPECT") == "1"
    assert len(receipts) == (0 if is_baseline else 1)
    if receipts:
        receipt = receipts[0]
        assert receipt.get("record_tool_outcome") is False
        assert receipt.get("source_id") == outcomes[0].get("source_id") == "tenant-a"
        assert receipt.get("company_id") == outcomes[0].get("company_id") == COMPANY_ID
        trace_kinds = [kind for kind, _ in runtime.trace]
        receipt_index = next(
            i for i, (kind, event) in enumerate(runtime.trace)
            if kind == "audit" and event.get("detail_code") == "ACCESS_AUTHORIZED"
        )
        adapter_index = trace_kinds.index("adapter_dispatch")
    else:
        trace_kinds = [kind for kind, _ in runtime.trace]
        adapter_index = trace_kinds.index("adapter_dispatch")
        receipt_index = None
    outcome_index = next(
        i for i, (kind, event) in enumerate(runtime.trace)
        if kind == "audit" and event.get("record_tool_outcome") is not False
        and event.get("tool") == tool
    )
    if receipt_index is not None:
        assert receipt_index < adapter_index < outcome_index
    else:
        assert adapter_index < outcome_index


def test_turnovers_r1_original_response_unchanged_through_streamable_http(monkeypatch):
    runtime = SyntheticRuntime(scoped=False)
    payload = _call_http_tool(
        runtime, "accounting_balance_and_turnovers", _request_args(), monkeypatch
    )

    assert payload == {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "concept": "account.balance_and_turnovers",
        "profile_fingerprint": "synthetic-profile-v1",
        "metadata_fingerprint": "synthetic-metadata-v1",
        "value": [NORMALIZED_ROW],
        "page": {"has_more": False},
        "warnings": [],
    }
    assert runtime.register_reads == [(
        "AccountingRegister_Ledger", "balanceAndTurnovers",
        {
            "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
            "Period": {"from": "2026-04-01T00:00:00+00:00", "to": "2026-04-30T00:00:00+00:00"},
        }, 200,
    )]
    _assert_one_business_outcome_and_ordered_optional_receipt(
        runtime, "accounting_balance_and_turnovers"
    )


def test_turnovers_r2_by_account_returns_scoped_totals_through_streamable_http(monkeypatch):
    runtime = SyntheticRuntime(scoped=True)
    arguments = {**_request_args(), "account_code": "60.01"}
    payload = _call_http_tool(
        runtime, "accounting_balance_and_turnovers_by_account", arguments, monkeypatch
    )

    assert runtime.register_reads[0][2]["AccountCondition"] == (
        f"Account_Key eq guid'{ACCOUNT_KEY}'"
    )
    assert payload["value"] == [NORMALIZED_ROW]
    assert payload["totals"] == [{
        "account": "60.01", "row_count": 1,
        "opening_debit": "100", "opening_credit": "0",
        "debit_turnover": "40", "credit_turnover": "15",
        "closing_debit": "125", "closing_credit": "0",
    }]
    assert payload["totals_complete"] is True
    assert payload["truncated"] is False
    assert payload["profile_kind"] == "SYNTHETIC_FIXTURE"
    assert payload["evidence_level"] == "L1"
    assert payload["native_reconciliation"] == "NOT_RUN"
    assert payload["warnings"] == ["SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE"]
    _assert_one_business_outcome_and_ordered_optional_receipt(
        runtime, "accounting_balance_and_turnovers_by_account"
    )
    outcome = next(
        event for event in runtime.audit_events
        if event.get("tool") == "accounting_balance_and_turnovers_by_account"
        and event.get("record_tool_outcome") is not False
    )
    assert outcome["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE"
