"""R1 sales and purchase documents through the real MCP HTTP boundary."""
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
RAW_ROWS = [
    {
        "Ref_Key": "a0000000-0000-0000-0000-000000000001",
        "Number": "S-100", "Date": "2026-04-12T12:30:00",
        "Контрагент_Key": "b0000000-0000-0000-0000-000000000001",
        "Amount": "125.50", "Валюта_Key": "c0000000-0000-0000-0000-000000000001",
        "Posted": True,
    },
    {
        "Ref_Key": "a0000000-0000-0000-0000-000000000002",
        "Number": "S-101", "Date": "2026-04-18T08:05:00",
        "Контрагент_Key": "b0000000-0000-0000-0000-000000000002",
        "Amount": "10.25", "Валюта_Key": "c0000000-0000-0000-0000-000000000001",
        "Posted": False,
    },
]
NORMALIZED_ROWS = [
    {
        "document_ref": "a0000000-0000-0000-0000-000000000001",
        "document_number": "S-100", "date": "2026-04-12T12:30:00",
        "counterparty": "b0000000-0000-0000-0000-000000000001",
        "amount": "125.50", "currency": "c0000000-0000-0000-0000-000000000001",
        "posted": True,
    },
    {
        "document_ref": "a0000000-0000-0000-0000-000000000002",
        "document_number": "S-101", "date": "2026-04-18T08:05:00",
        "counterparty": "b0000000-0000-0000-0000-000000000002",
        "amount": "10.25", "currency": "c0000000-0000-0000-0000-000000000001",
        "posted": False,
    },
]
PAGE = {"has_more": False, "next_skip": None}


class SyntheticDocumentsRuntime:
    def __init__(self, profile_kind="VALIDATED_NATIVE"):
        self.audit_events = []
        self.trace = []
        self.reads = []
        self.capability_calls = 0
        self.metadata_calls = 0
        self.mapping_calls = []
        self.profile_kind = profile_kind
        self.mappings = concept_mappings()
        sales_mapping = self.mappings["sales"]
        self.mappings["purchases"] = {
            **sales_mapping,
            "entity_set": "Document_Purchase",
            "output_fields": dict(sales_mapping["output_fields"]),
        }

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
                assert concept in {"sales", "purchases"}
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
                    "reconciliation_basis": "two-source document reconciliation",
                }

        class Audit:
            async def write(inner, **event):
                self.audit_events.append(event)
                self.trace.append(("audit", event.copy()))

        class RateLimit:
            async def check(inner, *, subject, source_id, tool):
                assert (subject, source_id) == ("synthetic-user", "tenant-a")
                assert tool in {
                    "sales_documents", "purchase_documents",
                    "sales_documents_with_provenance", "purchase_documents_filtered",
                }

        class OneC:
            async def capabilities(inner, source, *, refresh=False):
                self.capability_calls += 1
                assert source.id == "tenant-a"
                return SimpleNamespace(
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    metadata_fingerprint="synthetic-metadata-documents-v1",
                )

            async def read(
                inner, source, *, entity_set, select, filter_expr, orderby,
                expand, top, skip,
            ):
                assert source.id == "tenant-a"
                self.reads.append({
                    "entity_set": entity_set, "select": select, "filter_expr": filter_expr,
                    "orderby": orderby, "expand": expand, "top": top, "skip": skip,
                })
                self.trace.append(("adapter_dispatch", entity_set))
                rows = RAW_ROWS
                if "Контрагент_Key eq guid'" in filter_expr and "Posted eq true" in filter_expr:
                    rows = [RAW_ROWS[0]]
                return {"value": [dict(row) for row in rows], "page": dict(PAGE)}

            async def metadata(inner, source):
                self.metadata_calls += 1
                raise AssertionError("document listing must not require metadata discovery")

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
                "clientInfo": {"name": "tc001-documents", "version": "1"},
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


def _expected_profile_fields(profile_kind):
    if os.environ.get("TC001_BASELINE_EXPECT") == "1":
        return {"warnings": []}
    if profile_kind == "VALIDATED_NATIVE":
        return {
            "profile_kind": profile_kind, "evidence_level": "PROFILE_VALIDATED",
            "native_reconciliation": "PROFILE_EVIDENCE_ON_FILE", "warnings": [],
        }
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
            "reconciliation_basis": "two-source document reconciliation",
            "warnings": ["UNVALIDATED_INDEPENDENT_RECONCILIATION_NOT_NATIVE_VALIDATED"],
        }
    if profile_kind == "VALIDATED_MACHINE_RECONCILED":
        return {
            "profile_kind": profile_kind, "evidence_level": "PROFILE_VALIDATED_MACHINE",
            "native_reconciliation": "MACHINE_TWO_SOURCE",
            "warnings": ["MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT"],
        }
    raise AssertionError(profile_kind)


def _expected_candidate_totals(rows):
    amount = "135.75" if len(rows) == 2 else "125.5"
    return {
        "amount_totals": [{
            "currency": "c0000000-0000-0000-0000-000000000001",
            "amount": amount, "document_count": len(rows),
        }],
        "amount_totals_complete": True,
    }


@pytest.mark.parametrize(
    ("tool_name", "concept", "entity_set"),
    [
        ("sales_documents", "sales", "Document_Sales"),
        ("purchase_documents", "purchases", "Document_Purchase"),
    ],
)
def test_document_r1_native_http_rows_query_response_and_company_denial(
    tool_name, concept, entity_set, monkeypatch
):
    runtime = SyntheticDocumentsRuntime()
    arguments = {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "top": 2, "skip": 1}
    result = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "concept": concept,
        "profile_fingerprint": f"validated_native-{concept}-v1",
        "metadata_fingerprint": "synthetic-metadata-documents-v1",
        "value": NORMALIZED_ROWS, "page": PAGE,
        "warnings": [],
    }
    assert runtime.reads == [{
        "entity_set": entity_set,
        "select": ["Ref_Key", "Number", "Date", "Контрагент_Key", "Amount", "Валюта_Key", "Posted"],
        "filter_expr": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
        "orderby": "Date desc", "expand": None, "top": 2, "skip": 1,
    }]
    assert runtime.capability_calls == 1 and runtime.mapping_calls == [concept]
    assert runtime.metadata_calls == 0

    outcomes = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    completed = [
        event for event in outcomes
        if event.get("record_tool_outcome") is not False and event.get("outcome") == "success"
    ]
    assert len(completed) == 1
    assert len(outcomes) == (1 if os.environ.get("TC001_BASELINE_EXPECT") == "1" else 2)
    assert completed[0]["tool"] == tool_name
    assert completed[0]["source_id"] == "tenant-a"
    assert completed[0]["returned_items"] == 2
    assert completed[0]["company_id"] == COMPANY_ID
    assert completed[0]["adapter_kind"] == "ODATA_JSON_V3"
    assert completed[0]["metadata_fingerprint"] == "synthetic-metadata-documents-v1"
    assert completed[0]["profile_fingerprint"] == f"validated_native-{concept}-v1"
    assert completed[0]["response_bytes"] == len(
        json.dumps(NORMALIZED_ROWS, ensure_ascii=False, default=str).encode("utf-8")
    )
    expected_query = {
        "company_id": str(COMPANY_ID), "concept": concept, "top": 2, "skip": 1,
    }
    if os.environ.get("TC001_BASELINE_EXPECT") == "1":
        assert "detail_code" not in completed[0]
    else:
        assert completed[0]["detail_code"] is None
    assert completed[0]["query"] == expected_query
    receipt_events = [event for event in outcomes if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    baseline = os.environ.get("TC001_BASELINE_EXPECT") == "1"
    assert len(receipt_events) == (0 if baseline else 1)
    if receipt_events:
        assert receipt_events[0]["record_tool_outcome"] is False
        assert receipt_events[0]["tool"] == tool_name
        assert receipt_events[0]["outcome"] == "success"
        assert receipt_events[0]["source_id"] == completed[0]["source_id"] == "tenant-a"
        assert receipt_events[0]["company_id"] == completed[0]["company_id"] == COMPANY_ID
        assert receipt_events[0]["query"] == expected_query
        assert receipt_events[0]["policy_version"] == "predispatch-audit-v1"
        kinds = [kind for kind, _ in runtime.trace]
        receipt_index = next(i for i, (kind, event) in enumerate(runtime.trace)
                             if kind == "audit" and event.get("detail_code") == "ACCESS_AUTHORIZED")
        dispatch_index = kinds.index("adapter_dispatch")
        outcome_index = next(i for i, (kind, event) in enumerate(runtime.trace)
                             if kind == "audit" and event.get("record_tool_outcome") is not False
                             and event.get("outcome") == "success")
        assert receipt_index < dispatch_index < outcome_index

    denied_runtime = SyntheticDocumentsRuntime()
    denied = _call_http_tool(denied_runtime, tool_name, {
        **arguments, "company_id": str(OTHER_COMPANY_ID),
    }, monkeypatch)
    assert denied.get("isError") is True
    assert denied["content"] == [{"type": "text", "text": f"Error executing tool {tool_name}"}]
    assert denied_runtime.capability_calls == 0
    assert denied_runtime.mapping_calls == []
    assert denied_runtime.reads == []
    denied_events = [event for event in denied_runtime.audit_events if event.get("tool") == tool_name]
    assert len(denied_events) == 1
    assert denied_events[0]["outcome"] == "denied"
    assert denied_events[0]["detail_code"] == "PermissionError"
    assert not any(event.get("detail_code") == "ACCESS_AUTHORIZED" for event in denied_events)


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="R1 fail-closed profile routing is a candidate change",
)
@pytest.mark.parametrize(
    ("tool_name", "concept", "profile_kind"),
    [
        (tool, concept, profile_kind)
        for tool, concept in (("sales_documents", "sales"), ("purchase_documents", "purchases"))
        for profile_kind in ("SYNTHETIC_FIXTURE", "UNKNOWN_PROFILE")
    ],
)
def test_r1_documents_rejects_non_native_and_unknown_before_read(
    tool_name, concept, profile_kind, monkeypatch
):
    runtime = SyntheticDocumentsRuntime(profile_kind)
    result = _call_http_tool(runtime, tool_name, {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "top": 2, "skip": 0,
    }, monkeypatch)
    assert result.get("isError") is True
    assert result["content"] == [{"type": "text", "text": f"Error executing tool {tool_name}"}]
    assert runtime.capability_calls == 1
    assert runtime.mapping_calls == [concept]
    assert runtime.reads == []
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert [event.get("detail_code") for event in events] == [
        "ACCESS_AUTHORIZED", "SEMANTIC_PROFILE_UNVALIDATED",
    ]
    assert events[0].get("record_tool_outcome") is False
    assert events[1].get("outcome") == "denied"


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific document tools are candidate additions",
)
@pytest.mark.parametrize(
    ("tool_name", "concept", "entity_set", "profile_kind"),
    [
        (tool, concept, entity, profile_kind)
        for tool, concept, entity in (
            ("sales_documents_with_provenance", "sales", "Document_Sales"),
            ("purchase_documents_filtered", "purchases", "Document_Purchase"),
        )
        for profile_kind in (
            "SYNTHETIC_FIXTURE", "UNVALIDATED_INDEPENDENT_RECONCILIATION",
            "VALIDATED_MACHINE_RECONCILED",
        )
    ],
)
def test_r2_documents_expose_provenance_totals_and_filtered_query(
    tool_name, concept, entity_set, profile_kind, monkeypatch
):
    runtime = SyntheticDocumentsRuntime(profile_kind)
    arguments = {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "top": 2, "skip": 1}
    expected_rows = NORMALIZED_ROWS
    expected_filter = f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'"
    if tool_name == "purchase_documents_filtered":
        arguments.update({
            "counterparty_ref": "b0000000-0000-0000-0000-000000000001",
            "posted_only": True,
        })
        expected_rows = NORMALIZED_ROWS[:1]
        expected_filter += (
            " and Контрагент_Key eq guid'b0000000-0000-0000-0000-000000000001'"
            " and Posted eq true"
        )
    result = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID), "concept": concept,
        "profile_fingerprint": f"{profile_kind.lower()}-{concept}-v1",
        "metadata_fingerprint": "synthetic-metadata-documents-v1",
        "value": expected_rows, "page": PAGE,
        **_expected_candidate_totals(expected_rows),
        **_expected_profile_fields(profile_kind),
    }
    assert runtime.reads == [{
        "entity_set": entity_set,
        "select": ["Ref_Key", "Number", "Date", "Контрагент_Key", "Amount", "Валюта_Key", "Posted"],
        "filter_expr": expected_filter, "orderby": "Date desc", "expand": None,
        "top": 2, "skip": 1,
    }]
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    completion = [event for event in events if event.get("record_tool_outcome") is not False]
    assert len(completion) == 1 and completion[0]["outcome"] == "success"
    assert completion[0]["detail_code"] == {
        "SYNTHETIC_FIXTURE": "SYNTHETIC_FIXTURE_PROFILE",
        "UNVALIDATED_INDEPENDENT_RECONCILIATION": "PROVISIONAL_PROFILE",
        "VALIDATED_MACHINE_RECONCILED": "MACHINE_RECONCILED_PROFILE",
    }[profile_kind]
    assert completion[0]["query"] == {
        "company_id": str(COMPANY_ID), "concept": concept, "top": 2, "skip": 1,
        "counterparty_ref": arguments.get("counterparty_ref"),
        "posted_only": arguments.get("posted_only", False),
    }
    receipt = [event for event in events if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    assert len(receipt) == 1 and receipt[0].get("record_tool_outcome") is False
    assert receipt[0]["source_id"] == completion[0]["source_id"] == "tenant-a"
    assert receipt[0]["company_id"] == completion[0]["company_id"] == COMPANY_ID
    receipt_index = next(i for i, (kind, event) in enumerate(runtime.trace)
                         if kind == "audit" and event.get("detail_code") == "ACCESS_AUTHORIZED")
    dispatch_index = next(i for i, (kind, _) in enumerate(runtime.trace) if kind == "adapter_dispatch")
    completion_index = next(i for i, (kind, event) in enumerate(runtime.trace)
                            if kind == "audit" and event.get("record_tool_outcome") is not False)
    assert receipt_index < dispatch_index < completion_index


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific document tools are candidate additions",
)
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("sales_documents_with_provenance", {
            "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "top": 2, "skip": 0,
        }),
        ("purchase_documents_filtered", {
            "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "top": 2, "skip": 0,
        }),
    ],
)
def test_r2_documents_foreign_company_denied_before_business_read(
    tool_name, arguments, monkeypatch
):
    runtime = SyntheticDocumentsRuntime("SYNTHETIC_FIXTURE")
    denied = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert denied.get("isError") is True
    assert len(denied["content"]) == 1
    error = json.loads(denied["content"][0]["text"])["error"]
    assert {
        "code": error["code"], "category": error["category"], "retryable": error["retryable"],
        "safe_message": error["safe_message"], "tool": error["tool"],
        "source_id": error["source_id"], "operation": error["operation"],
    } == {
        "code": "ACCESS_DENIED", "category": "authorization", "retryable": False,
        "safe_message": "The caller is not authorized for this source, company or operation.",
        "tool": tool_name, "source_id": "tenant-a", "operation": tool_name,
    }
    assert str(UUID(error["correlation_id"])) == error["correlation_id"]
    assert runtime.capability_calls == 0 and runtime.mapping_calls == [] and runtime.reads == []
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert len(events) == 1 and events[0]["outcome"] == "denied"
    assert events[0]["detail_code"] == "PermissionError"
