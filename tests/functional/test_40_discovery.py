"""U01/U02-style discovery, live-metadata and bounded-output checks through public tools."""

from __future__ import annotations

from tests.functional.support import harness as h

EXPECTED_TOOLS = {
    "system_status", "sources_list", "source_health", "external_evidence_manifest", "rsv_metadata",
    "companies_list", "onec_capabilities", "onec_metadata_summary", "onec_find_entities",
    "accounting_balance_and_turnovers", "inventory_balance", "inventory_movements",
    "accounting_posting_rows", "cash_movements", "bank_balance", "receivable_balance",
    "payable_balance", "sales_documents", "purchase_documents", "onec_read",
    "receivable_aging", "payable_aging",
}


async def test_tool_surface_is_exactly_the_reviewed_read_only_set():
    names = set(await h.list_tool_names())
    assert names == EXPECTED_TOOLS, f"new/removed tools - re-evaluate SC mapping: +{names - EXPECTED_TOOLS} -{EXPECTED_TOOLS - names}"


async def test_discovery_lists_fake1c_source_and_both_companies():
    st = await h.call("system_status")
    assert st.ok and st.data["read_only"] is True and st.data["subject"] == h.PRINCIPAL
    src = await h.call("sources_list")
    assert [s["id"] for s in src.data] == [h.SOURCE_ID] and src.data[0]["read_only"] is True
    comp = await h.call("companies_list", {"source_id": h.SOURCE_ID})
    assert {c["company_id"] for c in comp.data} == {h.COMPANY_ONE, h.COMPANY_TWO}
    health = await h.call("source_health", {"source_id": h.SOURCE_ID})
    assert health.ok and health.data["ok"] is True


async def test_live_metadata_lists_only_synthetic_entities():
    summ = await h.call("onec_metadata_summary", {"source_id": h.SOURCE_ID, "refresh": True})
    assert summ.ok and summ.data["entity_set_count"] == 12
    assert summ.data["groups"] == {"AccountingRegister": 1, "AccumulationRegister": 7, "Catalog": 2, "Document": 2}
    cap = await h.call("onec_capabilities", {"source_id": h.SOURCE_ID})
    assert cap.ok and cap.data["compatibility_status"] == "SUPPORTED"
    found = await h.call("onec_find_entities", {"source_id": h.SOURCE_ID, "contains": "AccountingRegister"})
    assert found.ok and [e["name"] for e in found.data] == ["AccountingRegister_Ledger"]
    ghost = await h.call("onec_find_entities", {"source_id": h.SOURCE_ID, "contains": "VAT"})
    assert ghost.ok and ghost.data == [], "no VAT entity may be advertised (SC06 stays gated)"
    assert h.no_write_reached_1c(found) and h.no_write_reached_1c(cap) and h.no_write_reached_1c(summ)


async def test_result_bounds_top_and_row_cap():
    st = await h.call("system_status")
    cap = st.data["max_rows"]
    one = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales", "top": 1})
    assert one.ok and len(one.data["value"]) == 1
    big = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales", "top": 10**6})
    assert len(big.data["value"]) <= cap if big.ok else big.is_error
    assert h.final_audit(big)["returned_items"] is None or h.final_audit(big)["returned_items"] <= cap
