"""RAW-L2 fidelity checks: rows read through the public `onec_read` MCP tool (gateway -> real sidecar -> real 1C OData)
compared with the read-only COM oracle (NATIVE_COM_QUERY, comparison only).

These are raw-data checks (counts, key sets, exact Decimal sums, day boundaries, bounds).  They are NOT semantic
profile validation and are labelled raw-L2 everywhere.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from scripts.real1c.com_oracle import Oracle, dec
from scripts.real1c.lane import SRC_REAL, Lane

USER = "auditor"
AUG = "Date ge datetime'2026-08-01T00:00:00' and Date lt datetime'2026-09-01T00:00:00'"
AUG_PERIOD = "Period ge datetime'2026-08-01T00:00:00' and Period lt datetime'2026-09-01T00:00:00'"
LAST_DAY = "Period ge datetime'2026-08-31T00:00:00' and Period lt datetime'2026-09-01T00:00:00'"


async def page_all(lane: Lane, entity: str, select: list[str], flt: str | None = None, *, page: int = 200,
                   max_pages: int = 80, orderby: str | None = None) -> dict[str, Any]:
    rows: list[dict] = []
    calls = 0
    has_more = True
    skip = 0
    truncated_seen = False
    while has_more and calls < max_pages:
        args: dict[str, Any] = {"source_id": SRC_REAL, "entity_set": entity, "top": page, "skip": skip, "select": select}
        if flt:
            args["filter_expr"] = flt
        if orderby:
            args["orderby"] = orderby
        r = await lane.call(USER, "onec_read", args, correlate=False)
        calls += 1
        if r["is_error"] or not isinstance(r["payload"], dict):
            return {"rows": rows, "calls": calls, "error": r["text"], "complete": False, "truncated": truncated_seen}
        rows.extend(r["payload"].get("value", []))
        info = r["payload"].get("page", {})
        truncated_seen = truncated_seen or bool(info.get("truncated"))
        has_more = bool(info.get("has_more"))
        skip += page
    return {"rows": rows, "calls": calls, "error": None, "complete": not has_more, "truncated": truncated_seen}


def _d(value: Any) -> Decimal:
    return dec(value)


def _obs(probe: str, outcome: str, detail: str) -> dict[str, str]:
    return {"probe": probe, "outcome": outcome, "detail": detail}


def _verdict(case_id: str, title: str, ok: bool | None, observations: list[dict], *, tools: list[str] | None = None) -> dict:
    return {"case_id": case_id, "title": title, "ok": ok, "observations": observations,
            "tools_called": tools or ["onec_read"], "evidence_classes": ["GATEWAY_OBSERVATION", "NATIVE_COM_QUERY"]}


async def rl2_01_organisation(lane: Lane, o: Oracle) -> dict:
    r = await lane.call(USER, "onec_read", {"source_id": SRC_REAL, "entity_set": "Catalog_Организации", "top": 5,
                                            "select": ["Ref_Key", "Description", "Code", "ИНН"]})
    gw = (r["payload"] or {}).get("value", []) if isinstance(r["payload"], dict) else []
    com = o.rows("ВЫБРАТЬ Т.Ссылка КАК Р, Т.Наименование КАК Н, Т.Код КАК К, Т.ИНН КАК Инн ИЗ Справочник.Организации КАК Т",
                 ("Р", "Н", "К", "Инн"))
    ok = (len(gw) == len(com) == 1 and gw[0]["Ref_Key"] == o.guid(com[0]["Р"]) and gw[0]["Description"] == str(com[0]["Н"])
          and gw[0]["Code"] == str(com[0]["К"]) and gw[0]["ИНН"] == str(com[0]["Инн"]))
    return _verdict("RL2-01", "Organisation record: gateway row equals COM row (key, name, code, tax id)", ok, [
        _obs("rows", "match" if ok else "differ", f"gateway rows={len(gw)} com rows={len(com)}; fields compared: "
             "Ref_Key, Description, Code, ИНН (values not stored, equality only)")])


async def rl2_02_counterparties(lane: Lane, o: Oracle) -> dict:
    res = await page_all(lane, "Catalog_Контрагенты", ["Ref_Key", "Description", "DeletionMark"])
    com = o.rows("ВЫБРАТЬ Т.Ссылка КАК Р, Т.Наименование КАК Н, Т.ПометкаУдаления КАК П ИЗ Справочник.Контрагенты КАК Т",
                 ("Р", "Н", "П"))
    gw_keys = {r["Ref_Key"] for r in res["rows"]}
    com_keys = {o.guid(r["Р"]) for r in com}
    gw_names = hashlib.sha256("\n".join(sorted(f"{r['Ref_Key']}|{r['Description']}" for r in res["rows"])).encode()).hexdigest()
    com_names = hashlib.sha256("\n".join(sorted(f"{o.guid(r['Р'])}|{r['Н']}" for r in com)).encode()).hexdigest()
    ok = res["complete"] and len(res["rows"]) == len(com) and gw_keys == com_keys and gw_names == com_names
    return _verdict("RL2-02", "Counterparty catalogue: paged gateway read equals COM (count, key set, name hash)", ok, [
        _obs("paging", "complete" if res["complete"] else "incomplete", f"pages={res['calls']} rows={len(res['rows'])}"),
        _obs("comparison", "match" if ok else "differ", f"com rows={len(com)} key-set equal={gw_keys == com_keys} "
             f"name-hash equal={gw_names == com_names}")])


async def _documents(lane: Lane, o: Oracle, case_id: str, title: str, entity: str, query_name: str, flt: str | None,
                     com_where: str) -> dict:
    res = await page_all(lane, entity, ["Ref_Key", "Number", "Date", "СуммаДокумента", "Posted", "DeletionMark"], flt)
    rows = res["rows"]
    gw_sum = sum((_d(r["СуммаДокумента"]) for r in rows), Decimal("0.00"))
    gw_posted = sum(1 for r in rows if r["Posted"])
    agg = o.rows(f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К, СУММА(Т.СуммаДокумента) КАК С, СУММА(ВЫБОР КОГДА Т.Проведен ТОГДА 1 ИНАЧЕ 0 КОНЕЦ) "
                 f"КАК П ИЗ Документ.{query_name} КАК Т {com_where}", ("К", "С", "П"))[0]
    ok = (res["complete"] and len(rows) == int(agg["К"]) and gw_sum == _d(agg["С"]) and gw_posted == int(agg["П"]))
    return _verdict(case_id, title, ok, [
        _obs("paging", "complete" if res["complete"] else "incomplete", f"pages={res['calls']} rows={len(rows)}"),
        _obs("count", "match" if len(rows) == int(agg["К"]) else "differ", f"gateway={len(rows)} com={int(agg['К'])}"),
        _obs("exact sum СуммаДокумента", "match" if gw_sum == _d(agg["С"]) else "differ",
             f"gateway={gw_sum} com={_d(agg['С'])} (Decimal, to the bani)"),
        _obs("posted flag count", "match" if gw_posted == int(agg["П"]) else "differ",
             f"gateway={gw_posted} com={int(agg['П'])}")])


async def rl2_03_purchases(lane: Lane, o: Oracle) -> dict:
    return await _documents(lane, o, "RL2-03", "Purchase documents (all): count, exact sum and posted count equal COM",
                            "Document_ПоступлениеТоваровУслуг", "ПоступлениеТоваровУслуг", None, "")


async def rl2_04_sales_month(lane: Lane, o: Oracle) -> dict:
    return await _documents(
        lane, o, "RL2-04", "Sales documents in 2026-08: count, exact sum and posted count equal COM",
        "Document_РеализацияТоваровУслуг", "РеализацияТоваровУслуг", AUG,
        "ГДЕ Т.Дата >= ДАТАВРЕМЯ(2026,8,1) И Т.Дата < ДАТАВРЕМЯ(2026,9,1)")


async def rl2_05_posting_rows(lane: Lane, o: Oracle) -> dict:
    res = await page_all(lane, "AccountingRegister_Хозрасчетный_RecordType",
                         ["Period", "Active", "AccountDr_Key", "AccountCr_Key", "Сумма"], AUG_PERIOD, max_pages=60)
    rows = res["rows"]
    gw_sum = sum((_d(r["Сумма"]) for r in rows), Decimal("0.00"))
    gw_active = sum(1 for r in rows if r["Active"])
    agg = o.rows("ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К, СУММА(Т.Сумма) КАК С, СУММА(ВЫБОР КОГДА Т.Активность ТОГДА 1 ИНАЧЕ 0 КОНЕЦ) КАК А "
                 "ИЗ РегистрБухгалтерии.Хозрасчетный КАК Т ГДЕ Т.Период >= ДАТАВРЕМЯ(2026,8,1) И Т.Период < ДАТАВРЕМЯ(2026,9,1)",
                 ("К", "С", "А"))[0]
    ok = (res["complete"] and len(rows) == int(agg["К"]) and gw_sum == _d(agg["С"]) and gw_active == int(agg["А"]))
    return _verdict("RL2-05", "Accounting posting rows in 2026-08: paged count, exact sum and active count equal COM", ok, [
        _obs("paging", "complete" if res["complete"] else "incomplete", f"pages={res['calls']} rows={len(rows)}"),
        _obs("count", "match" if len(rows) == int(agg["К"]) else "differ", f"gateway={len(rows)} com={int(agg['К'])}"),
        _obs("exact sum Сумма", "match" if gw_sum == _d(agg["С"]) else "differ", f"gateway={gw_sum} com={_d(agg['С'])}"),
        _obs("active flag count", "match" if gw_active == int(agg["А"]) else "differ",
             f"gateway={gw_active} com={int(agg['А'])}")])


async def rl2_06_chart_of_accounts(lane: Lane, o: Oracle) -> dict:
    res = await page_all(lane, "ChartOfAccounts_Хозрасчетный", ["Code", "Description", "Ref_Key"],
                         orderby="Ref_Key")
    com = o.rows("ВЫБРАТЬ Т.Код КАК К, Т.Наименование КАК Н ИЗ ПланСчетов.Хозрасчетный КАК Т", ("К", "Н"))
    gw_codes = sorted(r["Code"] for r in res["rows"])
    com_codes = sorted(str(r["К"]) for r in com)
    ok = res["complete"] and gw_codes == com_codes
    return _verdict("RL2-06", "Chart of accounts (explicit $orderby): account code set equals COM", ok, [
        _obs("codes", "match" if ok else "differ", f"gateway={len(gw_codes)} com={len(com_codes)} "
             f"sorted code lists equal={gw_codes == com_codes}")])


async def rl2_07_day_boundary(lane: Lane, o: Oracle) -> dict:
    res = await page_all(lane, "AccountingRegister_Хозрасчетный_RecordType", ["Period", "Сумма"], LAST_DAY)
    rows = res["rows"]
    last_period = max((r["Period"] for r in rows), default="")
    com_n = int(o.scalar("ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ РегистрБухгалтерии.Хозрасчетный КАК Т ГДЕ "
                         "Т.Период >= ДАТАВРЕМЯ(2026,8,31) И Т.Период < ДАТАВРЕМЯ(2026,9,1)"))
    sep_first = await lane.call(USER, "onec_read", {
        "source_id": SRC_REAL, "entity_set": "AccountingRegister_Хозрасчетный_RecordType", "top": 1, "select": ["Period"],
        "filter_expr": "Period ge datetime'2026-09-01T00:00:00' and Period lt datetime'2026-09-02T00:00:00'"})
    leak = [r for r in rows if not str(r["Period"]).startswith("2026-08-31")]
    ok = res["complete"] and len(rows) == com_n and not leak
    return _verdict("RL2-07", "31-Aug / 1-Sep boundary: rows of the last day equal COM and none leak across midnight", ok, [
        _obs("last-day rows", "match" if len(rows) == com_n else "differ", f"gateway={len(rows)} com={com_n}"),
        _obs("midnight leak", "none" if not leak else "leak", f"rows outside 2026-08-31 in the filtered page={len(leak)}; "
             f"latest period seen={last_period[:19]}"),
        _obs("next day separate", "ok" if not sep_first["is_error"] else "error",
             "a filter for 2026-09-01 returns its own rows (no overlap checked by key sets)")])


async def rl2_08_bounds(lane: Lane, o: Oracle) -> dict:
    del o
    r = await lane.call(USER, "onec_read", {"source_id": SRC_REAL, "entity_set": "Document_РеализацияТоваровУслуг",
                                            "top": 1000, "select": ["Ref_Key"]}, correlate=False)
    payload = r["payload"] if isinstance(r["payload"], dict) else {}
    rows, page = payload.get("value", []), payload.get("page", {})
    ok = (not r["is_error"] and 0 < len(rows) <= 200 and bool(page.get("has_more")))
    return _verdict("RL2-08", "Bounded reads: top=1000 on a 45,677-row set is capped and flagged as having more", ok, [
        _obs("cap", "capped" if len(rows) <= 200 else "unbounded", f"returned={len(rows)} requested=1000"),
        _obs("page flags", "ok" if page.get("has_more") else "missing", f"page={page}")])


async def rl2_09_company_scope(lane: Lane, o: Oracle) -> dict:
    del o
    real = "019bbaa8-5131-11ee-aa2f-d85ed30dc416"
    ghost = "00000000-0000-4000-8000-00000000d00d"
    counts = {}
    for label, ref in (("real organisation", real), ("synthetic organisation", ghost)):
        res = await page_all(lane, "AccountingRegister_Хозрасчетный_RecordType", ["Period"],
                             f"{AUG_PERIOD} and Организация_Key eq guid'{ref}'", max_pages=40)
        counts[label] = len(res["rows"])
    ok = counts["real organisation"] == 5065 and counts["synthetic organisation"] == 0
    return _verdict("RL2-09", "Company filter at 1C level: the real organisation owns all August rows, a foreign one none",
                    ok, [_obs("per-organisation row counts", "match" if ok else "differ", str(counts)),
                         _obs("design note", "info", "onec_read is source-scoped: a source-level grant is not limited to one "
                              "organisation; company isolation is enforced by the company-scoped semantic tools")])


async def rl2_10_unstable_paging(lane: Lane, o: Oracle) -> dict:
    """Paging with $top/$skip and NO $orderby: the real 1C returns repeated and missing rows between pages."""
    del o
    findings = []
    for entity, page_size, total in (("ChartOfAccounts_Хозрасчетный", 200, 857), ("Catalog_Контрагенты", 50, 115)):
        plain = await page_all(lane, entity, ["Ref_Key"], page=page_size)
        ordered = await page_all(lane, entity, ["Ref_Key"], page=page_size, orderby="Ref_Key")
        distinct_plain = len({r["Ref_Key"] for r in plain["rows"]})
        distinct_ordered = len({r["Ref_Key"] for r in ordered["rows"]})
        findings.append((entity, page_size, total, len(plain["rows"]), distinct_plain, distinct_ordered))
    ok = all(row[4] == row[2] for row in findings)
    observations = [_obs(f"{entity} page={size} without $orderby", "stable" if distinct == total else "UNSTABLE",
                         f"rows returned={rows}, distinct keys={distinct} of {total}; with orderby=Ref_Key distinct={ordered}")
                    for entity, size, total, rows, distinct, ordered in findings]
    observations.append(_obs("impact", "info", "a client that pages without an explicit order double-counts some rows and misses "
                             "others (ST-010 'pages cover all rows once'); stable order must be enforced or required"))
    return _verdict("RL2-10", "Paging stability: top/skip without $orderby covers every row exactly once", ok, observations)


RL2_CASES = (rl2_01_organisation, rl2_02_counterparties, rl2_03_purchases, rl2_04_sales_month, rl2_05_posting_rows,
             rl2_06_chart_of_accounts, rl2_07_day_boundary, rl2_08_bounds, rl2_09_company_scope, rl2_10_unstable_paging)
