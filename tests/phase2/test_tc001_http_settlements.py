"""Company-scoped receivable/payable balance tools through MCP Streamable HTTP."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from mcp.server.transport_security import TransportSecuritySettings


COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000002")
COMPANY_EXTERNAL_REF = "00000000-0000-0000-0000-000000000101"
PERIOD = "2026-04-30T23:59:59+00:00"
PROFILES = {
    "receivable_balance": {
        "concept": "receivable.balance",
        "register": "AccumulationRegister_TestReceivables",
        "fingerprint": "synthetic-receivable.balance-v1",
        "raw": [
            {"Контрагент_Key": "party-1", "Договор_Key": "contract-1", "СуммаBalance": "9.50"},
            {"Контрагент_Key": "party-2", "Договор_Key": "contract-2", "СуммаBalance": "0"},
        ],
        "rows": [
            {"counterparty_ref": "party-1", "contract_ref": "contract-1", "amount": "9.50"},
            {"counterparty_ref": "party-2", "contract_ref": "contract-2", "amount": "0"},
        ],
    },
    "payable_balance": {
        "concept": "payable.balance",
        "register": "AccumulationRegister_TestPayables",
        "fingerprint": "synthetic-payable.balance-v1",
        "raw": [
            {"Контрагент_Key": "vendor-1", "Договор_Key": "supply-1", "СуммаBalance": "14.25"},
            {"Контрагент_Key": "vendor-2", "Договор_Key": "supply-2", "СуммаBalance": "0"},
        ],
        "rows": [
            {"counterparty_ref": "vendor-1", "contract_ref": "supply-1", "amount": "14.25"},
            {"counterparty_ref": "vendor-2", "contract_ref": "supply-2", "amount": "0"},
        ],
    },
}


class SyntheticSettlementRuntime:
    def __init__(self, tool_name, profile_kind="VALIDATED_NATIVE"):
        self.tool_name = tool_name
        base_name = tool_name.removesuffix("_with_provenance")
        self.profile = dict(PROFILES[base_name])
        self.profile_kind = profile_kind
        self.profile["fingerprint"] = f"{profile_kind.lower()}-{self.profile['concept']}-v1"
        self.audit_events = []
        self.trace = []
        self.register_reads = []
        self.capability_calls = 0
        self.mapping_calls = []

        class Registry:
            async def require_source(inner, principal, source_id):
                assert principal.subject == "synthetic-user"
                assert source_id == "tenant-a"
                return SimpleNamespace(id=source_id, kind="synthetic")

            async def require_source_for_company(inner, principal, source_id, company_id):
                assert principal.subject == "synthetic-user"
                assert source_id == "tenant-a"
                if company_id != COMPANY_ID:
                    raise PermissionError("company access denied")
                return SimpleNamespace(id=source_id, kind="synthetic")

            async def require_company(inner, principal, source_id, company_id):
                assert principal.subject == "synthetic-user"
                assert source_id == "tenant-a"
                if company_id != COMPANY_ID:
                    raise PermissionError("company access denied")
                return SimpleNamespace(external_ref=COMPANY_EXTERNAL_REF)

            async def save_capabilities(inner, _capabilities):
                return {"drift_status": "UNCHANGED"}

            async def require_semantic_mapping(inner, source_id, company_id, concept):
                assert (source_id, company_id, concept) == (
                    "tenant-a", COMPANY_ID, self.profile["concept"],
                )
                self.mapping_calls.append(concept)
                detail_codes = {
                    "SYNTHETIC_FIXTURE": "SYNTHETIC_FIXTURE_PROFILE",
                    "UNVALIDATED_INDEPENDENT_RECONCILIATION": "PROVISIONAL_PROFILE",
                    "VALIDATED_MACHINE_RECONCILED": "MACHINE_RECONCILED_PROFILE",
                }
                return {
                    "mapping": {
                        "entity_set": self.profile["register"],
                        "method": "Balance",
                        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
                        "output_fields": {
                            "counterparty_ref": "Контрагент_Key",
                            "contract_ref": "Договор_Key",
                            "amount": "СуммаBalance",
                        },
                        "required_register_capabilities": [{
                            "entity_set": self.profile["register"], "method": "Balance",
                        }],
                    },
                    "profile_fingerprint": self.profile["fingerprint"],
                    "profile_kind": self.profile_kind,
                    "audit_detail_code": detail_codes.get(self.profile_kind),
                    "reconciliation_basis": "two-source counterparty balance reconciliation",
                }

        class Audit:
            async def write(inner, **event):
                self.audit_events.append(event)
                self.trace.append(("audit", event.copy()))

        class RateLimit:
            async def check(inner, *, subject, source_id, tool):
                assert (subject, source_id, tool) == (
                    "synthetic-user", "tenant-a", self.tool_name,
                )

        class OneC:
            async def capabilities(inner, source, *, refresh=False):
                self.capability_calls += 1
                assert source.id == "tenant-a"
                return SimpleNamespace(
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    metadata_fingerprint="synthetic-metadata-settlement-v1",
                )

            async def register_read(inner, source, *, register_set, method, arguments, top):
                assert source.id == "tenant-a"
                self.register_reads.append({
                    "register_set": register_set, "method": method,
                    "arguments": arguments, "top": top,
                })
                self.trace.append(("adapter_dispatch", register_set))
                return {
                    "value": [dict(row) for row in self.profile["raw"]],
                    "page": {"has_more": False},
                }

        self.registry = Registry()
        self.audit = Audit()
        self.rate_limit = RateLimit()
        self.onec = OneC()
        self.capability_policy = None

    async def start(self):
        return None

    async def close(self):
        return None


def _call_http_tool(runtime, tool_name, arguments, monkeypatch):
    import business_ai_gateway.server as server_module

    expected_server = os.environ.get("TC001_EXPECT_SERVER_FILE")
    if expected_server:
        assert Path(server_module.__file__).resolve() == Path(expected_server).resolve()
    from business_ai_gateway.principal import Principal

    monkeypatch.setattr(server_module, "current_principal", lambda *, oauth_enabled: Principal(
        subject="synthetic-user", client_id="synthetic-client",
        scopes=frozenset({"onec:read"}), groups=frozenset(), claims={},
    ))
    mcp = build_mcp(Settings(environment="test", public_mcp_url="http://testserver/mcp"), runtime)
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp", json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        initialized = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "tc001-settlements", "version": "1"},
            },
        })
        assert initialized.status_code == 200, initialized.text
        session_headers = {**headers, "mcp-session-id": initialized.headers["mcp-session-id"]}
        notification = client.post(
            "/mcp", headers=session_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert notification.status_code == 202, notification.text
        response = client.post("/mcp", headers=session_headers, json={
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        assert response.status_code == 200, response.text
        return response.json()["result"]


def _expected_provenance(profile_kind="VALIDATED_NATIVE"):
    if os.environ.get("TC001_BASELINE_EXPECT") == "1":
        return {"warnings": []}
    if profile_kind == "VALIDATED_NATIVE":
        return {"warnings": []}
    if profile_kind == "SYNTHETIC_FIXTURE":
        return {
            "profile_kind": profile_kind,
            "evidence_level": "L1",
            "native_reconciliation": "NOT_RUN",
            "warnings": ["SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE"],
        }
    if profile_kind == "UNVALIDATED_INDEPENDENT_RECONCILIATION":
        return {
            "profile_kind": profile_kind,
            "validation_status": profile_kind,
            "evidence_level": "L2_PROVISIONAL",
            "native_reconciliation": "NOT_RUN",
            "reconciliation_basis": "two-source counterparty balance reconciliation",
            "warnings": ["UNVALIDATED_INDEPENDENT_RECONCILIATION_NOT_NATIVE_VALIDATED"],
        }
    if profile_kind == "VALIDATED_MACHINE_RECONCILED":
        return {
            "profile_kind": profile_kind,
            "evidence_level": "PROFILE_VALIDATED_MACHINE",
            "native_reconciliation": "MACHINE_TWO_SOURCE",
            "warnings": ["MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT"],
        }
    raise AssertionError(profile_kind)


def _assert_success_audit(runtime, tool_name):
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    outcomes = [event for event in events if event.get("record_tool_outcome") is not False]
    assert len(outcomes) == 1 and outcomes[0]["outcome"] == "success"
    assert outcomes[0]["profile_fingerprint"] == runtime.profile["fingerprint"]
    receipts = [event for event in events if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    baseline = os.environ.get("TC001_BASELINE_EXPECT") == "1"
    assert len(receipts) == (0 if baseline else 1)
    trace_kinds = [kind for kind, _ in runtime.trace]
    adapter_index = trace_kinds.index("adapter_dispatch")
    outcome_index = next(
        i for i, (kind, event) in enumerate(runtime.trace)
        if kind == "audit" and event.get("tool") == tool_name
        and event.get("record_tool_outcome") is not False
    )
    if receipts:
        receipt = receipts[0]
        assert receipt.get("record_tool_outcome") is False
        assert receipt["source_id"] == outcomes[0]["source_id"] == "tenant-a"
        assert receipt["company_id"] == outcomes[0]["company_id"] == COMPANY_ID
        receipt_index = next(
            i for i, (kind, event) in enumerate(runtime.trace)
            if kind == "audit" and event.get("tool") == tool_name
            and event.get("detail_code") == "ACCESS_AUTHORIZED"
        )
        assert receipt_index < adapter_index < outcome_index
    else:
        assert adapter_index < outcome_index


def _assert_foreign_company_denied(runtime, tool_name, denied):
    assert denied.get("isError") is True
    if tool_name.endswith("_with_provenance"):
        assert len(denied["content"]) == 1
        error = json.loads(denied["content"][0]["text"])["error"]
        assert {
            "code": error["code"], "category": error["category"],
            "retryable": error["retryable"], "safe_message": error["safe_message"],
            "tool": error["tool"], "source_id": error["source_id"],
            "operation": error["operation"],
        } == {
            "code": "ACCESS_DENIED", "category": "authorization", "retryable": False,
            "safe_message": "The caller is not authorized for this source, company or operation.",
            "tool": tool_name, "source_id": "tenant-a", "operation": tool_name,
        }
        assert str(UUID(error["correlation_id"])) == error["correlation_id"]
    else:
        assert denied["content"] == [{"type": "text", "text": f"Error executing tool {tool_name}"}]
    assert runtime.capability_calls == 0
    assert runtime.mapping_calls == []
    assert runtime.register_reads == []
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert len(events) == 1
    assert events[0]["outcome"] == "denied"
    assert events[0]["detail_code"] == "PermissionError"
    assert not any(event.get("detail_code") == "ACCESS_AUTHORIZED" for event in events)


def _exercise_settlement_balance_http(tool_name, monkeypatch):
    runtime = SyntheticSettlementRuntime(tool_name)
    profile = runtime.profile
    result = _call_http_tool(runtime, tool_name, {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD,
    }, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "concept": profile["concept"], "period": PERIOD,
        "profile_fingerprint": profile["fingerprint"],
        "metadata_fingerprint": "synthetic-metadata-settlement-v1",
        "value": profile["rows"], "page": {"has_more": False},
        **_expected_provenance(runtime.profile_kind),
    }
    assert runtime.register_reads == [{
        "register_set": profile["register"],
        "method": "Balance",
        "arguments": {
            "Period": "2026-04-30T23:59:59+00:00",
            "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
        },
        "top": 200,
    }]
    _assert_success_audit(runtime, tool_name)

    denied_runtime = SyntheticSettlementRuntime(tool_name)
    denied = _call_http_tool(denied_runtime, tool_name, {
        "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "period": PERIOD,
    }, monkeypatch)
    _assert_foreign_company_denied(denied_runtime, tool_name, denied)


@pytest.mark.parametrize("tool_name", ["receivable_balance", "payable_balance"])
def test_receivable_and_payable_balance_contracts(tool_name, monkeypatch):
    _exercise_settlement_balance_http(tool_name, monkeypatch)


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="candidate R1 fail-closed routing is not present on baseline",
)
@pytest.mark.parametrize(
    ("tool_name", "profile_kind"),
    [
        (tool_name, profile_kind)
        for tool_name in ("receivable_balance", "payable_balance")
        for profile_kind in ("SYNTHETIC_FIXTURE", "UNKNOWN_PROFILE")
    ],
)
def test_settlement_r1_rejects_nonnative_and_unknown_before_register_read(
    tool_name, profile_kind, monkeypatch
):
    runtime = SyntheticSettlementRuntime(tool_name, profile_kind)
    result = _call_http_tool(runtime, tool_name, {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD,
    }, monkeypatch)
    assert result.get("isError") is True
    assert result["content"] == [{"type": "text", "text": f"Error executing tool {tool_name}"}]
    assert runtime.capability_calls == 1
    assert runtime.mapping_calls == [runtime.profile["concept"]]
    assert runtime.register_reads == []
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert [event.get("detail_code") for event in events] == [
        "ACCESS_AUTHORIZED", "SEMANTIC_PROFILE_UNVALIDATED",
    ]
    assert events[0].get("record_tool_outcome") is False
    assert events[1]["outcome"] == "denied"


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific settlement tools are R2 additions",
)
@pytest.mark.parametrize(
    ("tool_name", "profile_kind"),
    [
        (tool_name, profile_kind)
        for tool_name in ("receivable_balance_with_provenance", "payable_balance_with_provenance")
        for profile_kind in (
            "SYNTHETIC_FIXTURE", "UNVALIDATED_INDEPENDENT_RECONCILIATION",
            "VALIDATED_MACHINE_RECONCILED",
        )
    ],
)
def test_settlement_r2_returns_provenance_and_foreign_company_denial(
    tool_name, profile_kind, monkeypatch
):
    runtime = SyntheticSettlementRuntime(tool_name, profile_kind)
    profile = runtime.profile
    result = _call_http_tool(runtime, tool_name, {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD,
    }, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "concept": profile["concept"], "period": PERIOD,
        "profile_fingerprint": profile["fingerprint"],
        "metadata_fingerprint": "synthetic-metadata-settlement-v1",
        "value": profile["rows"], "page": {"has_more": False},
        **_expected_provenance(profile_kind),
    }
    assert runtime.register_reads == [{
        "register_set": profile["register"], "method": "Balance",
        "arguments": {
            "Period": "2026-04-30T23:59:59+00:00",
            "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
        },
        "top": 200,
    }]
    _assert_success_audit(runtime, tool_name)

    denied_runtime = SyntheticSettlementRuntime(tool_name, "SYNTHETIC_FIXTURE")
    denied = _call_http_tool(denied_runtime, tool_name, {
        "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "period": PERIOD,
    }, monkeypatch)
    _assert_foreign_company_denied(denied_runtime, tool_name, denied)
