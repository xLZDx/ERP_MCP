"""Company-scoped cash and bank R1 tools through MCP Streamable HTTP."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from mcp.server.transport_security import TransportSecuritySettings
from scripts.synthetic_fixture_profiles import concept_mappings


COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000002")
COMPANY_EXTERNAL_REF = "00000000-0000-0000-0000-000000000101"
START = "2026-04-01T00:00:00+00:00"
END = "2026-05-01T00:00:00+00:00"
AS_OF = "2026-04-30T23:59:59+00:00"
CASH_RAW = [
    {
        "Period": "2026-04-12T12:30:00", "LineNumber": 1,
        "СчетДенежныхСредств_Key": "a0000000-0000-0000-0000-000000000001",
        "Валюта_Key": "b0000000-0000-0000-0000-000000000001",
        "Сумма": "110.00", "RecordType": "Receipt",
        "Recorder": "c0000000-0000-0000-0000-000000000001",
    },
    {
        "Period": "2026-04-18T08:05:00", "LineNumber": 2,
        "СчетДенежныхСредств_Key": "a0000000-0000-0000-0000-000000000002",
        "Валюта_Key": "b0000000-0000-0000-0000-000000000002",
        "Сумма": "10.00", "RecordType": "Expense",
        "Recorder": "c0000000-0000-0000-0000-000000000002",
    },
]
CASH_ROWS = [
    {
        "period": "2026-04-12T12:30:00", "line_number": 1,
        "cash_account_ref": "a0000000-0000-0000-0000-000000000001",
        "currency_ref": "b0000000-0000-0000-0000-000000000001",
        "amount_delta": "110.00", "direction": "receipt",
        "recorder_ref": "c0000000-0000-0000-0000-000000000001",
    },
    {
        "period": "2026-04-18T08:05:00", "line_number": 2,
        "cash_account_ref": "a0000000-0000-0000-0000-000000000002",
        "currency_ref": "b0000000-0000-0000-0000-000000000002",
        "amount_delta": "-10.00", "direction": "expense",
        "recorder_ref": "c0000000-0000-0000-0000-000000000002",
    },
]
BANK_RAW = [
    {
        "БанковскийСчет_Key": "d0000000-0000-0000-0000-000000000001",
        "Валюта_Key": "e0000000-0000-0000-0000-000000000001",
        "СуммаBalance": "250.00",
    },
]
BANK_ROWS = [
    {
        "bank_account_ref": "d0000000-0000-0000-0000-000000000001",
        "currency_ref": "e0000000-0000-0000-0000-000000000001",
        "amount": "250.00",
    },
]


class SyntheticCashBankRuntime:
    def __init__(self, profile_kind="VALIDATED_NATIVE"):
        self.audit_events = []
        self.trace = []
        self.entity_reads = []
        self.register_reads = []
        self.capability_calls = 0
        self.metadata_calls = 0
        self.mapping_calls = []
        self.mappings = concept_mappings()
        self.profile_kind = profile_kind

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
                assert (source_id, company_id) == ("tenant-a", COMPANY_ID)
                assert concept in {"cash.movements", "bank.balance"}
                self.mapping_calls.append(concept)
                detail_codes = {
                    "SYNTHETIC_FIXTURE": "SYNTHETIC_FIXTURE_PROFILE",
                    "UNVALIDATED_INDEPENDENT_RECONCILIATION": "PROVISIONAL_PROFILE",
                    "VALIDATED_MACHINE_RECONCILED": "MACHINE_RECONCILED_PROFILE",
                }
                return {
                    "mapping": self.mappings[concept],
                    "profile_fingerprint": f"{self.profile_kind.lower()}-{concept}-v1",
                    "profile_kind": self.profile_kind,
                    "audit_detail_code": detail_codes.get(self.profile_kind),
                    "reconciliation_basis": "two-source cash and bank reconciliation",
                }

        class Audit:
            async def write(inner, **event):
                self.audit_events.append(event)
                self.trace.append(("audit", event.copy()))

        class RateLimit:
            async def check(inner, *, subject, source_id, tool):
                assert (subject, source_id) == ("synthetic-user", "tenant-a")
                assert tool in {
                    "cash_movements", "bank_balance",
                    "cash_movements_with_provenance", "bank_balance_with_provenance",
                }

        class OneC:
            async def capabilities(inner, source, *, refresh=False):
                self.capability_calls += 1
                assert source.id == "tenant-a"
                return SimpleNamespace(
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    metadata_fingerprint="synthetic-metadata-cash-bank-v1",
                )

            async def metadata(inner, source):
                self.metadata_calls += 1
                assert source.id == "tenant-a"
                mapping = self.mappings["cash.movements"]
                fields = tuple(mapping["output_fields"].values()) + (
                    mapping["company_scope"]["field"],
                )
                return SimpleNamespace(
                    names={mapping["entity_set"]},
                    entities=[SimpleNamespace(name=mapping["entity_set"], properties=fields)],
                )

            async def read(
                inner, source, *, entity_set, select, filter_expr, orderby,
                expand, top, skip,
            ):
                assert source.id == "tenant-a"
                self.entity_reads.append({
                    "entity_set": entity_set, "select": select, "filter_expr": filter_expr,
                    "orderby": orderby, "expand": expand, "top": top, "skip": skip,
                })
                self.trace.append(("adapter_dispatch", entity_set))
                return {"value": [dict(row) for row in CASH_RAW], "page": {"has_more": False}}

            async def register_read(
                inner, source, *, register_set, method, arguments, top,
            ):
                assert source.id == "tenant-a"
                self.register_reads.append({
                    "register_set": register_set, "method": method,
                    "arguments": arguments, "top": top,
                })
                self.trace.append(("adapter_dispatch", register_set))
                return {"value": [dict(row) for row in BANK_RAW], "page": {"has_more": False}}

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
                "clientInfo": {"name": "tc001-cash-bank", "version": "1"},
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
            "profile_kind": profile_kind, "evidence_level": "L1",
            "native_reconciliation": "NOT_RUN",
            "warnings": ["SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE"],
        }
    if profile_kind == "UNVALIDATED_INDEPENDENT_RECONCILIATION":
        return {
            "profile_kind": profile_kind, "validation_status": profile_kind,
            "evidence_level": "L2_PROVISIONAL", "native_reconciliation": "NOT_RUN",
            "reconciliation_basis": "two-source cash and bank reconciliation",
            "warnings": ["UNVALIDATED_INDEPENDENT_RECONCILIATION_NOT_NATIVE_VALIDATED"],
        }
    if profile_kind == "VALIDATED_MACHINE_RECONCILED":
        return {
            "profile_kind": profile_kind, "evidence_level": "PROFILE_VALIDATED_MACHINE",
            "native_reconciliation": "MACHINE_TWO_SOURCE",
            "warnings": ["MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT"],
        }
    raise AssertionError(profile_kind)


def _assert_audit(runtime, tool_name):
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    outcomes = [event for event in events if event.get("record_tool_outcome") is not False]
    assert len(outcomes) == 1 and outcomes[0]["outcome"] == "success"
    concept = "cash.movements" if "cash_movements" in tool_name else "bank.balance"
    assert outcomes[0]["profile_fingerprint"] == f"{runtime.profile_kind.lower()}-{concept}-v1"
    receipts = [event for event in events if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    baseline = os.environ.get("TC001_BASELINE_EXPECT") == "1"
    assert len(receipts) == (0 if baseline else 1)
    kinds = [kind for kind, _ in runtime.trace]
    adapter_index = kinds.index("adapter_dispatch")
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
            if kind == "audit" and event.get("detail_code") == "ACCESS_AUTHORIZED"
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
        assert denied["content"] == [{
            "type": "text", "text": f"Error executing tool {tool_name}"
        }]
    assert runtime.capability_calls == runtime.metadata_calls == 0
    assert runtime.mapping_calls == []
    assert runtime.entity_reads == runtime.register_reads == []
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert len(events) == 1
    assert events[0]["outcome"] == "denied"
    assert events[0]["detail_code"] == "PermissionError"
    assert not any(event.get("detail_code") == "ACCESS_AUTHORIZED" for event in events)


def test_cash_movements_http_rows_provenance_query_and_company_denial(monkeypatch):
    runtime = SyntheticCashBankRuntime()
    result = _call_http_tool(runtime, "cash_movements", {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "start_period": START, "end_period": END, "top": 25, "skip": 2,
    }, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "concept": "cash.movements", "period": {"from": START, "to_exclusive": END},
        "profile_fingerprint": "validated_native-cash.movements-v1",
        "metadata_fingerprint": "synthetic-metadata-cash-bank-v1",
        "value": CASH_ROWS, "page": {"has_more": False},
        **_expected_provenance(),
    }
    assert runtime.entity_reads == [{
        "entity_set": "AccumulationRegister_CashMovements",
        "select": ["Period", "LineNumber", "СчетДенежныхСредств_Key", "Валюта_Key",
                   "Сумма", "RecordType", "Recorder"],
        "filter_expr": (
            f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}' and "
            "Period ge datetime'2026-04-01T00:00:00' and "
            "Period lt datetime'2026-05-01T00:00:00'"
        ),
        "orderby": "Period asc,Recorder asc,LineNumber asc", "expand": None,
        "top": 25, "skip": 2,
    }]
    assert runtime.register_reads == [] and runtime.metadata_calls == 1
    assert sum(Decimal(row["amount_delta"]) for row in payload["value"]) == Decimal(100)
    _assert_audit(runtime, "cash_movements")

    denied_runtime = SyntheticCashBankRuntime()
    denied = _call_http_tool(denied_runtime, "cash_movements", {
        "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID),
        "start_period": START, "end_period": END, "top": 25, "skip": 2,
    }, monkeypatch)
    _assert_foreign_company_denied(denied_runtime, "cash_movements", denied)


def test_bank_balance_http_rows_provenance_query_and_company_denial(monkeypatch):
    runtime = SyntheticCashBankRuntime()
    result = _call_http_tool(runtime, "bank_balance", {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": AS_OF,
    }, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "concept": "bank.balance", "period": AS_OF,
        "profile_fingerprint": "validated_native-bank.balance-v1",
        "metadata_fingerprint": "synthetic-metadata-cash-bank-v1",
        "value": BANK_ROWS, "page": {"has_more": False},
        **_expected_provenance(),
    }
    assert runtime.register_reads == [{
        "register_set": "AccumulationRegister_BankBalances", "method": "Balance",
        "arguments": {
            "Period": AS_OF,
            "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
        },
        "top": 200,
    }]
    assert runtime.entity_reads == [] and runtime.metadata_calls == 0
    assert sum(Decimal(row["amount"]) for row in payload["value"]) == Decimal(250)
    cash_total = sum(Decimal(row["amount_delta"]) for row in CASH_ROWS)
    bank_total = sum(Decimal(row["amount"]) for row in BANK_ROWS)
    assert cash_total + bank_total == Decimal(350)
    _assert_audit(runtime, "bank_balance")

    denied_runtime = SyntheticCashBankRuntime()
    denied = _call_http_tool(denied_runtime, "bank_balance", {
        "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "period": AS_OF,
    }, monkeypatch)
    _assert_foreign_company_denied(denied_runtime, "bank_balance", denied)


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="R1 fail-closed profile routing is a candidate change",
)
@pytest.mark.parametrize(
    ("tool_name", "profile_kind", "arguments", "concept"),
    [
        ("cash_movements", "SYNTHETIC_FIXTURE", {
            "source_id": "tenant-a", "company_id": str(COMPANY_ID),
            "start_period": START, "end_period": END, "top": 25, "skip": 2,
        }, "cash.movements"),
        ("cash_movements", "UNKNOWN_PROFILE", {
            "source_id": "tenant-a", "company_id": str(COMPANY_ID),
            "start_period": START, "end_period": END, "top": 25, "skip": 2,
        }, "cash.movements"),
        ("bank_balance", "SYNTHETIC_FIXTURE", {
            "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": AS_OF,
        }, "bank.balance"),
        ("bank_balance", "UNKNOWN_PROFILE", {
            "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": AS_OF,
        }, "bank.balance"),
    ],
)
def test_cash_bank_r1_rejects_nonnative_and_unknown_before_business_read(
    tool_name, profile_kind, arguments, concept, monkeypatch
):
    runtime = SyntheticCashBankRuntime(profile_kind)
    result = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert result.get("isError") is True
    assert result["content"] == [{"type": "text", "text": f"Error executing tool {tool_name}"}]
    assert runtime.capability_calls == 1
    assert runtime.mapping_calls == [concept]
    assert runtime.metadata_calls == 0
    assert runtime.entity_reads == [] and runtime.register_reads == []
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert [event.get("detail_code") for event in events] == [
        "ACCESS_AUTHORIZED", "SEMANTIC_PROFILE_UNVALIDATED",
    ]
    assert events[0].get("record_tool_outcome") is False
    assert events[1]["outcome"] == "denied"


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific cash/bank tools are R2 additions",
)
@pytest.mark.parametrize(
    ("tool_name", "profile_kind", "arguments", "concept", "rows"),
    [
        ("cash_movements_with_provenance", profile_kind, {
            "source_id": "tenant-a", "company_id": str(COMPANY_ID),
            "start_period": START, "end_period": END, "top": 25, "skip": 2,
        }, "cash.movements", CASH_ROWS)
        for profile_kind in (
            "SYNTHETIC_FIXTURE", "UNVALIDATED_INDEPENDENT_RECONCILIATION",
            "VALIDATED_MACHINE_RECONCILED",
        )
    ] + [
        ("bank_balance_with_provenance", profile_kind, {
            "source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": AS_OF,
        }, "bank.balance", BANK_ROWS)
        for profile_kind in (
            "SYNTHETIC_FIXTURE", "UNVALIDATED_INDEPENDENT_RECONCILIATION",
            "VALIDATED_MACHINE_RECONCILED",
        )
    ],
)
def test_cash_bank_r2_returns_exact_provenance_and_audit(
    tool_name, profile_kind, arguments, concept, rows, monkeypatch
):
    runtime = SyntheticCashBankRuntime(profile_kind)
    result = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    base = {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "concept": concept,
        "period": {"from": START, "to_exclusive": END}
        if concept == "cash.movements" else AS_OF,
        "profile_fingerprint": f"{profile_kind.lower()}-{concept}-v1",
        "metadata_fingerprint": "synthetic-metadata-cash-bank-v1",
        "value": rows, "page": {"has_more": False},
    }
    assert payload == {**base, **_expected_provenance(profile_kind)}
    _assert_audit(runtime, tool_name)
    if concept == "cash.movements":
        assert runtime.entity_reads == [{
            "entity_set": "AccumulationRegister_CashMovements",
            "select": ["Period", "LineNumber", "СчетДенежныхСредств_Key", "Валюта_Key",
                       "Сумма", "RecordType", "Recorder"],
            "filter_expr": (
                f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}' and "
                "Period ge datetime'2026-04-01T00:00:00' and "
                "Period lt datetime'2026-05-01T00:00:00'"
            ),
            "orderby": "Period asc,Recorder asc,LineNumber asc", "expand": None,
            "top": 25, "skip": 2,
        }]
        assert runtime.register_reads == []
    else:
        assert runtime.register_reads == [{
            "register_set": "AccumulationRegister_BankBalances", "method": "Balance",
            "arguments": {
                "Period": AS_OF,
                "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
            },
            "top": 200,
        }]
        assert runtime.entity_reads == []


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific cash/bank tools are R2 additions",
)
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("cash_movements_with_provenance", {
            "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID),
            "start_period": START, "end_period": END, "top": 25, "skip": 2,
        }),
        ("bank_balance_with_provenance", {
            "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "period": AS_OF,
        }),
    ],
)
def test_cash_bank_r2_foreign_company_denied_before_business_read(
    tool_name, arguments, monkeypatch
):
    runtime = SyntheticCashBankRuntime("SYNTHETIC_FIXTURE")
    denied = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    _assert_foreign_company_denied(runtime, tool_name, denied)
