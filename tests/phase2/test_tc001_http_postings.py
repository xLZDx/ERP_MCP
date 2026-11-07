"""Company-scoped accounting posting rows through MCP Streamable HTTP."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from scripts.synthetic_fixture_profiles import concept_mappings

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000002")
COMPANY_EXTERNAL_REF = "00000000-0000-0000-0000-000000000101"
START = "2026-04-01T00:00:00+00:00"
END = "2026-05-01T00:00:00+00:00"
ENTITY_SET = "AccountingRegister_Ledger"
RAW_ROWS = [
    {
        "Period": "2026-04-12T12:30:00",
        "Recorder": "a0000000-0000-0000-0000-000000000001",
        "LineNumber": 1,
        "Active": True,
        "AccountDr_Key": "b0000000-0000-0000-0000-000000000001",
        "AccountCr_Key": "c0000000-0000-0000-0000-000000000001",
    },
    {
        "Period": "2026-04-18T08:05:00",
        "Recorder": "a0000000-0000-0000-0000-000000000002",
        "LineNumber": 2,
        "Active": False,
        "AccountDr_Key": "b0000000-0000-0000-0000-000000000002",
        "AccountCr_Key": "c0000000-0000-0000-0000-000000000002",
    },
]
EXPECTED_ROWS = [
    {
        "period": "2026-04-12T12:30:00",
        "recorder_ref": "a0000000-0000-0000-0000-000000000001",
        "line_number": 1,
        "active": True,
        "account_dr_ref": "b0000000-0000-0000-0000-000000000001",
        "account_cr_ref": "c0000000-0000-0000-0000-000000000001",
    },
    {
        "period": "2026-04-18T08:05:00",
        "recorder_ref": "a0000000-0000-0000-0000-000000000002",
        "line_number": 2,
        "active": False,
        "account_dr_ref": "b0000000-0000-0000-0000-000000000002",
        "account_cr_ref": "c0000000-0000-0000-0000-000000000002",
    },
]


class SyntheticPostingRuntime:
    def __init__(self):
        self.audit_events = []
        self.trace = []
        self.reads = []
        self.capability_calls = 0
        self.metadata_calls = 0
        self.mapping_calls = 0
        self.mapping = concept_mappings()["accounting.posting_rows"]

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
                    "tenant-a", COMPANY_ID, "accounting.posting_rows"
                )
                self.mapping_calls += 1
                return {
                    "mapping": self.mapping,
                    "profile_fingerprint": "synthetic-postings-v1",
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
                    "accounting_posting_rows",
                    "accounting_posting_rows_with_provenance",
                }

        class OneC:
            async def capabilities(inner, source, *, refresh=False):
                self.capability_calls += 1
                assert source.id == "tenant-a"
                return SimpleNamespace(
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    metadata_fingerprint="synthetic-metadata-postings-v1",
                )

            async def metadata(inner, source):
                self.metadata_calls += 1
                assert source.id == "tenant-a"
                fields = tuple(self.mapping["output_fields"].values()) + ("Организация_Key",)
                return SimpleNamespace(
                    names={ENTITY_SET},
                    entities=[SimpleNamespace(name=ENTITY_SET, properties=fields)],
                )

            async def read(
                inner, source, *, entity_set, select, filter_expr, orderby,
                expand, top, skip,
            ):
                assert source.id == "tenant-a"
                self.reads.append({
                    "entity_set": entity_set,
                    "select": select,
                    "filter_expr": filter_expr,
                    "orderby": orderby,
                    "expand": expand,
                    "top": top,
                    "skip": skip,
                })
                self.trace.append(("adapter_dispatch", entity_set))
                return {"value": [dict(row) for row in RAW_ROWS], "page": {"has_more": False}}

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
        initialized = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "tc001-postings", "version": "1"},
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
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]


def _arguments(company_id=COMPANY_ID):
    return {
        "source_id": "tenant-a",
        "company_id": str(company_id),
        "start_period": START,
        "end_period": END,
        "top": 25,
        "skip": 2,
    }


def _assert_audit_order(runtime, tool_name, *, baseline=False):
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    outcomes = [event for event in events if event.get("record_tool_outcome") is not False]
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["outcome"] == "success"
    assert outcome["profile_fingerprint"] == "synthetic-postings-v1"
    if baseline:
        assert outcome.get("detail_code") is None
    else:
        assert outcome["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE"

    receipts = [event for event in events if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    assert len(receipts) == (0 if baseline else 1)
    trace_kinds = [kind for kind, _ in runtime.trace]
    adapter_index = trace_kinds.index("adapter_dispatch")
    outcome_index = next(
        index for index, (kind, event) in enumerate(runtime.trace)
        if kind == "audit" and event.get("tool") == tool_name
        and event.get("record_tool_outcome") is not False
    )
    if receipts:
        receipt = receipts[0]
        assert receipt.get("record_tool_outcome") is False
        assert receipt["source_id"] == outcome["source_id"] == "tenant-a"
        assert receipt["company_id"] == outcome["company_id"] == COMPANY_ID
        receipt_index = next(
            index for index, (kind, event) in enumerate(runtime.trace)
            if kind == "audit" and event.get("tool") == tool_name
            and event.get("detail_code") == "ACCESS_AUTHORIZED"
        )
        assert receipt_index < adapter_index < outcome_index
    else:
        assert adapter_index < outcome_index


def test_accounting_postings_r1_http_exact_rows_and_company_rejection(monkeypatch):
    runtime = SyntheticPostingRuntime()
    result = _call_http_tool(runtime, "accounting_posting_rows", _arguments(), monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])

    base_response = {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "concept": "accounting.posting_rows",
        "period": {"from": START, "to_exclusive": END},
        "profile_fingerprint": "synthetic-postings-v1",
        "metadata_fingerprint": "synthetic-metadata-postings-v1",
        "value": EXPECTED_ROWS,
        "page": {"has_more": False},
    }
    expected_response = {
        **base_response,
        "warnings": ["Rows are not a native accounting report reconciliation."],
    }
    assert payload == expected_response
    assert runtime.reads == [{
        "entity_set": ENTITY_SET,
        "select": ["Period", "Recorder", "LineNumber", "Active", "AccountDr_Key", "AccountCr_Key"],
        "filter_expr": (
            f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}' and "
            "Period ge datetime'2026-04-01T00:00:00' and "
            "Period lt datetime'2026-05-01T00:00:00'"
        ),
        "orderby": "Period asc,Recorder asc,LineNumber asc",
        "expand": None,
        "top": 25,
        "skip": 2,
    }]
    _assert_audit_order(
        runtime, "accounting_posting_rows",
        baseline=os.environ.get("TC001_BASELINE_EXPECT") == "1",
    )

    rejected_runtime = SyntheticPostingRuntime()
    denied = _call_http_tool(
        rejected_runtime, "accounting_posting_rows", _arguments(OTHER_COMPANY_ID), monkeypatch
    )
    assert denied.get("isError") is True
    assert denied["content"] == [{
        "type": "text", "text": "Error executing tool accounting_posting_rows"
    }]
    assert rejected_runtime.capability_calls == 0
    assert rejected_runtime.metadata_calls == 0
    assert rejected_runtime.mapping_calls == 0
    assert rejected_runtime.reads == []
    denied_audits = [
        event for event in rejected_runtime.audit_events
        if event.get("tool") == "accounting_posting_rows"
    ]
    assert len(denied_audits) == 1
    assert denied_audits[0]["outcome"] == "denied"
    assert denied_audits[0]["detail_code"] == "PermissionError"


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="accounting_posting_rows_with_provenance is an R2 addition",
)
def test_accounting_postings_r2_http_provenance_and_company_denial(monkeypatch):
    runtime = SyntheticPostingRuntime()
    result = _call_http_tool(
        runtime,
        "accounting_posting_rows_with_provenance",
        _arguments(),
        monkeypatch,
    )
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "concept": "accounting.posting_rows",
        "period": {"from": START, "to_exclusive": END},
        "profile_fingerprint": "synthetic-postings-v1",
        "metadata_fingerprint": "synthetic-metadata-postings-v1",
        "value": EXPECTED_ROWS,
        "page": {"has_more": False},
        "profile_kind": "SYNTHETIC_FIXTURE",
        "evidence_level": "L1",
        "native_reconciliation": "NOT_RUN",
        "warnings": [
            "Rows are not a native accounting report reconciliation.",
            "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE",
        ],
    }
    _assert_audit_order(runtime, "accounting_posting_rows_with_provenance")

    rejected_runtime = SyntheticPostingRuntime()
    denied = _call_http_tool(
        rejected_runtime,
        "accounting_posting_rows_with_provenance",
        _arguments(OTHER_COMPANY_ID),
        monkeypatch,
    )
    assert denied.get("isError") is True
    assert len(denied["content"]) == 1
    error = json.loads(denied["content"][0]["text"])["error"]
    assert {
        "code": error["code"],
        "category": error["category"],
        "retryable": error["retryable"],
        "safe_message": error["safe_message"],
        "tool": error["tool"],
        "source_id": error["source_id"],
        "operation": error["operation"],
    } == {
        "code": "ACCESS_DENIED",
        "category": "authorization",
        "retryable": False,
        "safe_message": "The caller is not authorized for this source, company or operation.",
        "tool": "accounting_posting_rows_with_provenance",
        "source_id": "tenant-a",
        "operation": "accounting_posting_rows_with_provenance",
    }
    assert str(UUID(error["correlation_id"])) == error["correlation_id"]
    assert rejected_runtime.capability_calls == 0
    assert rejected_runtime.metadata_calls == 0
    assert rejected_runtime.mapping_calls == 0
    assert rejected_runtime.reads == []
    denied_audits = [
        event for event in rejected_runtime.audit_events
        if event.get("tool") == "accounting_posting_rows_with_provenance"
    ]
    assert len(denied_audits) == 1
    assert denied_audits[0]["outcome"] == "denied"
    assert denied_audits[0]["detail_code"] == "PermissionError"
    assert not any(
        event.get("detail_code") == "ACCESS_AUTHORIZED"
        for event in rejected_runtime.audit_events
    )
