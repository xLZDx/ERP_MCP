"""Inventory R1 responses and company scope through MCP Streamable HTTP."""
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
PERIOD = "2026-04-30T23:59:59+00:00"
START = "2026-04-01T00:00:00+00:00"
END = "2026-05-01T00:00:00+00:00"

BALANCE_RAW = [
    {
        "Номенклатура_Key": "a0000000-0000-0000-0000-000000000001",
        "Склад_Key": "b0000000-0000-0000-0000-000000000001",
        "КоличествоBalance": "12.50",
    },
    {
        "Номенклатура_Key": "a0000000-0000-0000-0000-000000000002",
        "Склад_Key": "b0000000-0000-0000-0000-000000000002",
        "КоличествоBalance": "0",
    },
]
BALANCE_ROWS = [
    {
        "item_ref": "a0000000-0000-0000-0000-000000000001",
        "warehouse_ref": "b0000000-0000-0000-0000-000000000001",
        "quantity": "12.50",
    },
    {
        "item_ref": "a0000000-0000-0000-0000-000000000002",
        "warehouse_ref": "b0000000-0000-0000-0000-000000000002",
        "quantity": "0",
    },
]
MOVEMENT_RAW = [
    {
        "Period": "2026-04-12T12:30:00",
        "Номенклатура_Key": "a0000000-0000-0000-0000-000000000001",
        "Склад_Key": "b0000000-0000-0000-0000-000000000001",
        "Количество": "4.5",
        "RecordType": "Receipt",
        "Recorder_Key": "c0000000-0000-0000-0000-000000000001",
    },
    {
        "Period": "2026-04-18T08:05:00",
        "Номенклатура_Key": "a0000000-0000-0000-0000-000000000002",
        "Склад_Key": "b0000000-0000-0000-0000-000000000002",
        "Количество": "1.25",
        "RecordType": "Expense",
        "Recorder_Key": "c0000000-0000-0000-0000-000000000002",
    },
]
MOVEMENT_ROWS = [
    {
        "period": "2026-04-12T12:30:00",
        "item_ref": "a0000000-0000-0000-0000-000000000001",
        "warehouse_ref": "b0000000-0000-0000-0000-000000000001",
        "quantity_delta": "4.5",
        "direction": "receipt",
        "recorder_ref": "c0000000-0000-0000-0000-000000000001",
    },
    {
        "period": "2026-04-18T08:05:00",
        "item_ref": "a0000000-0000-0000-0000-000000000002",
        "warehouse_ref": "b0000000-0000-0000-0000-000000000002",
        "quantity_delta": "-1.25",
        "direction": "expense",
        "recorder_ref": "c0000000-0000-0000-0000-000000000002",
    },
]


class SyntheticInventoryRuntime:
    def __init__(self, profile_kind="VALIDATED_NATIVE"):
        self.audit_events = []
        self.trace = []
        self.register_reads = []
        self.entity_reads = []
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
                assert concept in {"inventory.balance", "inventory.movements"}
                self.mapping_calls.append(concept)
                fingerprint = f"{self.profile_kind.lower()}-{concept}-v1"
                audit_codes = {
                    "SYNTHETIC_FIXTURE": "SYNTHETIC_FIXTURE_PROFILE",
                    "UNVALIDATED_INDEPENDENT_RECONCILIATION": "PROVISIONAL_PROFILE",
                    "VALIDATED_MACHINE_RECONCILED": "MACHINE_RECONCILED_PROFILE",
                }
                return {
                    "mapping": self.mappings[concept],
                    "profile_fingerprint": fingerprint,
                    "profile_kind": self.profile_kind,
                    "audit_detail_code": audit_codes.get(self.profile_kind),
                    "reconciliation_basis": "two-source quantity reconciliation",
                }

        class Audit:
            async def write(inner, **event):
                self.audit_events.append(event)
                self.trace.append(("audit", event.copy()))

        class RateLimit:
            async def check(inner, *, subject, source_id, tool):
                assert (subject, source_id) == ("synthetic-user", "tenant-a")
                assert tool in {
                    "inventory_balance", "inventory_movements",
                    "inventory_balance_with_provenance", "inventory_movements_with_provenance",
                }

        class OneC:
            async def capabilities(inner, source, *, refresh=False):
                self.capability_calls += 1
                assert source.id == "tenant-a"
                return SimpleNamespace(
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    metadata_fingerprint="synthetic-metadata-inventory-v1",
                )

            async def metadata(inner, source):
                self.metadata_calls += 1
                assert source.id == "tenant-a"
                mapping = self.mappings["inventory.movements"]
                fields = tuple(mapping["output_fields"].values()) + (
                    mapping["company_scope"]["field"],
                )
                return SimpleNamespace(
                    names={mapping["entity_set"]},
                    entities=[SimpleNamespace(name=mapping["entity_set"], properties=fields)],
                )

            async def register_read(
                inner, source, *, register_set, method, arguments, top,
            ):
                assert source.id == "tenant-a"
                self.register_reads.append({
                    "register_set": register_set,
                    "method": method,
                    "arguments": arguments,
                    "top": top,
                })
                self.trace.append(("adapter_dispatch", register_set))
                return {"value": [dict(row) for row in BALANCE_RAW], "page": {"has_more": False}}

            async def read(
                inner, source, *, entity_set, select, filter_expr, orderby,
                expand, top, skip,
            ):
                assert source.id == "tenant-a"
                self.entity_reads.append({
                    "entity_set": entity_set,
                    "select": select,
                    "filter_expr": filter_expr,
                    "orderby": orderby,
                    "expand": expand,
                    "top": top,
                    "skip": skip,
                })
                self.trace.append(("adapter_dispatch", entity_set))
                return {"value": [dict(row) for row in MOVEMENT_RAW], "page": {"has_more": False}}

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
                "clientInfo": {"name": "tc001-inventory", "version": "1"},
            },
        })
        assert initialized.status_code == 200, initialized.text
        session = initialized.headers["mcp-session-id"]
        session_headers = {**headers, "mcp-session-id": session}
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


def _profile_extras(profile_kind):
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
            "reconciliation_basis": "two-source quantity reconciliation",
            "warnings": ["UNVALIDATED_INDEPENDENT_RECONCILIATION_NOT_NATIVE_VALIDATED"],
        }
    if profile_kind == "VALIDATED_MACHINE_RECONCILED":
        return {
            "profile_kind": profile_kind,
            "evidence_level": "PROFILE_VALIDATED_MACHINE",
            "native_reconciliation": "MACHINE_TWO_SOURCE",
            "warnings": ["MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT"],
        }
    raise AssertionError(f"unexpected fixture profile for this test: {profile_kind}")


def _assert_success_audit(runtime, tool_name):
    events = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    outcomes = [event for event in events if event.get("record_tool_outcome") is not False]
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"] == "success"
    concept_part = "balance" if "balance" in tool_name else "movements"
    assert outcomes[0]["profile_fingerprint"] == (
        f"{runtime.profile_kind.lower()}-inventory.{concept_part}-v1"
    )
    receipts = [event for event in events if event.get("detail_code") == "ACCESS_AUTHORIZED"]
    assert len(receipts) == (0 if os.environ.get("TC001_BASELINE_EXPECT") == "1" else 1)
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


def _assert_company_denial(runtime, tool_name, denied):
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
    assert runtime.capability_calls == 0
    assert runtime.metadata_calls == 0
    assert runtime.mapping_calls == []
    assert runtime.register_reads == []
    assert runtime.entity_reads == []
    audits = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert len(audits) == 1
    assert audits[0]["outcome"] == "denied"
    assert audits[0]["detail_code"] == "PermissionError"
    assert not any(event.get("detail_code") == "ACCESS_AUTHORIZED" for event in audits)


def test_inventory_balance_http_normalization_query_provenance_and_denial(monkeypatch):
    runtime = SyntheticInventoryRuntime("VALIDATED_NATIVE")
    arguments = {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD}
    result = _call_http_tool(runtime, "inventory_balance", arguments, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    base = {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "concept": "inventory.balance",
        "period": PERIOD,
        "profile_fingerprint": "validated_native-inventory.balance-v1",
        "metadata_fingerprint": "synthetic-metadata-inventory-v1",
        "value": BALANCE_ROWS,
        "page": {"has_more": False},
    }
    expected = {**base, "warnings": []}
    assert payload == expected
    assert runtime.register_reads == [{
        "register_set": "AccumulationRegister_InventoryBalances",
        "method": "Balance",
        "arguments": {
            "Period": "2026-04-30T23:59:59+00:00",
            "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
        },
        "top": 200,
    }]
    assert runtime.entity_reads == []
    _assert_success_audit(runtime, "inventory_balance")

    denied_runtime = SyntheticInventoryRuntime()
    denied = _call_http_tool(denied_runtime, "inventory_balance", {
        **arguments, "company_id": str(OTHER_COMPANY_ID),
    }, monkeypatch)
    _assert_company_denial(denied_runtime, "inventory_balance", denied)


def test_inventory_movements_http_normalization_query_provenance_and_denial(monkeypatch):
    runtime = SyntheticInventoryRuntime("VALIDATED_NATIVE")
    arguments = {
        "source_id": "tenant-a", "company_id": str(COMPANY_ID),
        "start_period": START, "end_period": END, "top": 25, "skip": 2,
    }
    result = _call_http_tool(runtime, "inventory_movements", arguments, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    base = {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "concept": "inventory.movements",
        "period": {"from": START, "to_exclusive": END},
        "profile_fingerprint": "validated_native-inventory.movements-v1",
        "metadata_fingerprint": "synthetic-metadata-inventory-v1",
        "value": MOVEMENT_ROWS,
        "page": {"has_more": False},
    }
    expected = {**base, "warnings": []}
    assert payload == expected
    assert runtime.entity_reads == [{
        "entity_set": "AccumulationRegister_InventoryMovements",
        "select": [
            "Period", "Номенклатура_Key", "Склад_Key", "Количество",
            "RecordType", "Recorder_Key",
        ],
        "filter_expr": (
            f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}' and "
            "Period ge datetime'2026-04-01T00:00:00' and "
            "Period lt datetime'2026-05-01T00:00:00'"
        ),
        "orderby": "Period asc",
        "expand": None,
        "top": 25,
        "skip": 2,
    }]
    assert runtime.register_reads == []
    assert runtime.metadata_calls == 1
    _assert_success_audit(runtime, "inventory_movements")

    denied_runtime = SyntheticInventoryRuntime()
    denied = _call_http_tool(denied_runtime, "inventory_movements", {
        **arguments, "company_id": str(OTHER_COMPANY_ID),
    }, monkeypatch)
    _assert_company_denial(denied_runtime, "inventory_movements", denied)


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="fail-closed profile routing is the candidate R1/R2 contract",
)
@pytest.mark.parametrize(
    ("tool_name", "profile_kind", "arguments", "concept"),
    [
        (
            "inventory_balance", "SYNTHETIC_FIXTURE",
            {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD},
            "inventory.balance",
        ),
        (
            "inventory_balance", "UNKNOWN_PROFILE",
            {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD},
            "inventory.balance",
        ),
        (
            "inventory_movements", "SYNTHETIC_FIXTURE",
            {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "start_period": START,
             "end_period": END, "top": 25, "skip": 2},
            "inventory.movements",
        ),
        (
            "inventory_movements", "UNKNOWN_PROFILE",
            {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "start_period": START,
             "end_period": END, "top": 25, "skip": 2},
            "inventory.movements",
        ),
    ],
)
def test_inventory_r1_rejects_non_native_and_unknown_before_business_read(
    tool_name, profile_kind, arguments, concept, monkeypatch
):
    runtime = SyntheticInventoryRuntime(profile_kind)
    result = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert result.get("isError") is True
    assert result["content"] == [{
        "type": "text", "text": f"Error executing tool {tool_name}"
    }]
    assert runtime.capability_calls == 1
    assert runtime.mapping_calls == [concept]
    assert runtime.metadata_calls == 0
    assert runtime.register_reads == []
    assert runtime.entity_reads == []
    audits = [event for event in runtime.audit_events if event.get("tool") == tool_name]
    assert [event.get("detail_code") for event in audits] == [
        "ACCESS_AUTHORIZED", "SEMANTIC_PROFILE_UNVALIDATED",
    ]
    assert audits[0].get("record_tool_outcome") is False
    assert audits[1]["outcome"] == "denied"


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific inventory tools are R2 additions",
)
@pytest.mark.parametrize(
    ("tool_name", "profile_kind", "arguments", "concept", "rows"),
    [
        (
            "inventory_balance_with_provenance", profile_kind,
            {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "period": PERIOD},
            "inventory.balance", BALANCE_ROWS,
        )
        for profile_kind in (
            "SYNTHETIC_FIXTURE", "UNVALIDATED_INDEPENDENT_RECONCILIATION",
            "VALIDATED_MACHINE_RECONCILED",
        )
    ] + [
        (
            "inventory_movements_with_provenance", profile_kind,
            {"source_id": "tenant-a", "company_id": str(COMPANY_ID), "start_period": START,
             "end_period": END, "top": 25, "skip": 2},
            "inventory.movements", MOVEMENT_ROWS,
        )
        for profile_kind in (
            "SYNTHETIC_FIXTURE", "UNVALIDATED_INDEPENDENT_RECONCILIATION",
            "VALIDATED_MACHINE_RECONCILED",
        )
    ],
)
def test_inventory_r2_http_returns_explicit_profile_provenance(
    tool_name, profile_kind, arguments, concept, rows, monkeypatch
):
    runtime = SyntheticInventoryRuntime(profile_kind)
    result = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    assert not result.get("isError"), result
    payload = json.loads(result["content"][0]["text"])
    base = {
        "source_id": "tenant-a",
        "company_id": str(COMPANY_ID),
        "concept": concept,
        "period": PERIOD if concept == "inventory.balance" else {
            "from": START, "to_exclusive": END,
        },
        "profile_fingerprint": f"{profile_kind.lower()}-{concept}-v1",
        "metadata_fingerprint": "synthetic-metadata-inventory-v1",
        "value": rows,
        "page": {"has_more": False},
    }
    assert payload == {**base, **_profile_extras(profile_kind)}
    _assert_success_audit(runtime, tool_name)
    if concept == "inventory.balance":
        assert runtime.register_reads == [{
            "register_set": "AccumulationRegister_InventoryBalances",
            "method": "Balance",
            "arguments": {
                "Period": "2026-04-30T23:59:59+00:00",
                "Condition": f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}'",
            },
            "top": 200,
        }]
        assert runtime.entity_reads == []
    else:
        assert runtime.entity_reads == [{
            "entity_set": "AccumulationRegister_InventoryMovements",
            "select": [
                "Period", "Номенклатура_Key", "Склад_Key", "Количество",
                "RecordType", "Recorder_Key",
            ],
            "filter_expr": (
                f"Организация_Key eq guid'{COMPANY_EXTERNAL_REF}' and "
                "Period ge datetime'2026-04-01T00:00:00' and "
                "Period lt datetime'2026-05-01T00:00:00'"
            ),
            "orderby": "Period asc", "expand": None, "top": 25, "skip": 2,
        }]
        assert runtime.register_reads == []


@pytest.mark.skipif(
    os.environ.get("TC001_BASELINE_EXPECT") == "1",
    reason="provenance-specific inventory tools are R2 additions",
)
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("inventory_balance_with_provenance", {
            "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID), "period": PERIOD,
        }),
        ("inventory_movements_with_provenance", {
            "source_id": "tenant-a", "company_id": str(OTHER_COMPANY_ID),
            "start_period": START, "end_period": END, "top": 25, "skip": 2,
        }),
    ],
)
def test_inventory_r2_http_denies_foreign_company_before_business_read(
    tool_name, arguments, monkeypatch
):
    runtime = SyntheticInventoryRuntime("SYNTHETIC_FIXTURE")
    denied = _call_http_tool(runtime, tool_name, arguments, monkeypatch)
    _assert_company_denial(runtime, tool_name, denied)
