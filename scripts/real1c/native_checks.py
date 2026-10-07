"""NATIVE_COM_QUERY recomputation of the candidate assertions NR-01..NR-10 on the reference clone.

Comparison evidence only: each function recomputes the figure the candidate assertion states, from the clone's own
data through read-only COM queries, and reports AGREES / DISAGREES / NOT_COMPUTABLE.  None of this is native UI
report evidence and none of it can validate a semantic profile.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from scripts.real1c.com_oracle import Oracle, dec

AUG_START = "ДАТАВРЕМЯ(2026,8,1)"
AUG_END = "ДАТАВРЕМЯ(2026,8,31,23,59,59)"
SEP_START = "ДАТАВРЕМЯ(2026,9,1)"
REG = "РегистрБухгалтерии.Хозрасчетный"
REAL_REFERENCE = Path("D:/ERP_MCP_Testbed/1c/reference/scenario_pack/real_reference")


def _sum(o: Oracle, side: str, code: str, where: str, *, tree: bool = False) -> Decimal:
    account = f'Т.Счет{side}.Код ПОДОБНО "{code}%"' if tree else f'Т.Счет{side}.Код = "{code}"'
    return dec(o.scalar(f"ВЫБРАТЬ СУММА(Т.Сумма) КАК К ИЗ {REG} КАК Т ГДЕ {account} И Т.Активность {where}"))


def check_ending_balance(o: Oracle, code: str, expected: Decimal) -> dict:
    where = f"И Т.Период < {SEP_START}"
    exact = _sum(o, "Дт", code, where) - _sum(o, "Кт", code, where)
    tree = _sum(o, "Дт", code, where, tree=True) - _sum(o, "Кт", code, where, tree=True)
    return {"assertion": {"ending_net_dr_minus_cr_at_2026-08-31": str(expected)},
            "observed": {"exact_account": str(exact), "account_and_subaccounts": str(tree)},
            "verdict": "AGREES" if exact == expected else "DISAGREES"}


def check_turnover(o: Oracle, code: str, debit: Decimal, credit: Decimal) -> dict:
    where = f"И Т.Период >= {AUG_START} И Т.Период < {SEP_START}"
    d, c = _sum(o, "Дт", code, where), _sum(o, "Кт", code, where)
    d_t, c_t = _sum(o, "Дт", code, where, tree=True), _sum(o, "Кт", code, where, tree=True)
    return {"assertion": {"august_debit": str(debit), "august_credit": str(credit)},
            "observed": {"exact_debit": str(d), "exact_credit": str(c), "tree_debit": str(d_t),
                         "tree_credit": str(c_t)},
            "verdict": "AGREES" if (d == debit and c == credit) else "DISAGREES"}


def check_211(o: Oracle) -> dict:
    """Account 211 (and subaccounts) positions by analytics at 2026-08-31: closing balances, negatives, no movement."""

    def key(value) -> str:
        try:
            return o.guid(value)
        except Exception:  # noqa: BLE001 - non-reference analytic value
            return str(value)

    balances = o.rows(
        "ВЫБРАТЬ Т.Счет.Код КАК Ак, Т.Субконто1 КАК С1, Т.Субконто2 КАК С2, Т.СуммаОстатокДт КАК Д, "
        "Т.СуммаОстатокКт КАК К, Т.КоличествоОстатокДт КАК КД, Т.КоличествоОстатокКт КАК КК "
        f'ИЗ {REG}.Остатки({SEP_START}, Счет.Код ПОДОБНО "211%", , ) КАК Т', ("Ак", "С1", "С2", "Д", "К", "КД", "КК"))
    movements = o.rows(
        "ВЫБРАТЬ Т.Счет.Код КАК Ак, Т.Субконто1 КАК С1, Т.Субконто2 КАК С2, Т.СуммаОборотДт КАК ОД, "
        "Т.СуммаОборотКт КАК ОК "
        f'ИЗ {REG}.Обороты({AUG_START}, {AUG_END}, , Счет.Код ПОДОБНО "211%", , ) КАК Т', ("Ак", "С1", "С2", "ОД", "ОК"))
    moved = {(str(r["Ак"]), key(r["С1"]), key(r["С2"])) for r in movements if dec(r["ОД"]) != 0 or dec(r["ОК"]) != 0}
    negative = [r for r in balances if dec(r["К"]) != 0 or dec(r["КК"]) != 0 or dec(r["Д"]) < 0 or dec(r["КД"]) < 0]
    still = [r for r in balances if (str(r["Ак"]), key(r["С1"]), key(r["С2"])) not in moved]
    value = sum((dec(r["Д"]) - dec(r["К"]) for r in still), Decimal("0.00"))
    observed = {"nonzero_final_positions": len(balances), "negative_final_positions": len(negative),
                "no_movement_positions": len(still), "no_movement_value": str(value)}
    ok = (len(balances) == 37 and not negative and len(still) == 18 and str(value) == "17902.29")
    return {"assertion": {"nonzero_final": 37, "negative_final_positions": 0, "no_movement_positions": 18,
                          "no_movement_value": "17902.29", "combinations": "202 (history combos: not recomputed)"},
            "observed": observed, "verdict": "AGREES" if ok else "DISAGREES"}


def check_cash_241_1(o: Oracle) -> dict:
    opening_where = f"И Т.Период < {AUG_START}"
    opening = _sum(o, "Дт", "241.1", opening_where) - _sum(o, "Кт", "241.1", opening_where)
    win = f"И Т.Период >= {AUG_START} И Т.Период < {SEP_START}"
    debit, credit = _sum(o, "Дт", "241.1", win), _sum(o, "Кт", "241.1", win)
    ending = opening + debit - credit
    return {"assertion": {"opening": "8004.96", "payments": ["-4195.70", "-3000.00"], "ending": "809.26"},
            "observed": {"opening": str(opening), "august_debit": str(debit), "august_credit": str(credit),
                         "ending": str(ending)},
            "verdict": "AGREES" if (str(opening) == "8004.96" and str(ending) == "809.26") else "DISAGREES"}


def check_receipts_31_aug(o: Oracle) -> dict:
    """The candidate lists 7 receipts of 31-Aug that lack source documents: they must be a subset of the posted
    receipts of that day (the clone has 8; the 7-set equals the day's total minus exactly one receipt)."""
    rows = o.rows("ВЫБРАТЬ Т.СуммаДокумента КАК С ИЗ Документ.ПоступлениеТоваровУслуг КАК Т "
                  "ГДЕ Т.Дата >= ДАТАВРЕМЯ(2026,8,31) И Т.Дата < ДАТАВРЕМЯ(2026,9,1) И Т.Проведен", ("С",))
    amounts = [dec(r["С"]) for r in rows]
    total, target = sum(amounts, Decimal("0.00")), Decimal("140250.45")
    leftover = total - target
    subset = len(amounts) >= 8 and amounts.count(leftover) >= 1
    return {"assertion": {"receipt_count": 7, "total_incl_vat": str(target)},
            "observed": {"posted_receipts_on_2026-08-31": len(amounts), "day_total": str(total),
                         "day_total_minus_candidate": str(leftover),
                         "a_single_receipt_equals_the_difference": subset},
            "verdict": "AGREES" if subset else "DISAGREES",
            "notes": "consistent as a 7-of-8 subset; which receipts lack archive documents needs the owner manifest"}


def check_invoice_set(o: Oracle) -> dict:
    """21 supplier invoices (hashed-id comparison): find each incoming number among purchase documents."""
    with (REAL_REFERENCE / "invoice_cases_21.csv").open(encoding="utf-8-sig", newline="") as fh:
        wanted = list(csv.DictReader(fh))
    found, found_total, missing = 0, Decimal("0.00"), 0
    for case in wanted:
        number = case["invoice_no"].replace('"', "")
        rows = o.rows("ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К, СУММА(Т.СуммаДокумента) КАК С ИЗ Документ.ПоступлениеТоваровУслуг "
                      f'КАК Т ГДЕ Т.НомерВходящегоДокумента = "{number}" И Т.Проведен', ("К", "С"))
        if int(rows[0]["К"]):
            found += 1
            found_total += dec(rows[0]["С"])
        else:
            missing += 1
    expected_total = sum((Decimal(c["total_mdl"]) for c in wanted), Decimal("0.00"))
    return {"assertion": {"invoice_count": 21, "total_incl_vat": "266614.64", "matching_invoice_count": 19,
                          "matching_total_incl_vat": "264772.82"},
            "observed": {"pdf_invoices_listed": len(wanted), "pdf_total_listed": str(expected_total),
                         "found_as_posted_purchase_by_incoming_number": found, "not_found": missing,
                         "found_documents_total": str(found_total)},
            "verdict": "AGREES" if (len(wanted) == 21 and str(expected_total) == "266614.64"
                                    and found == 19 and str(found_total) == "264772.82") else "DISAGREES"}


def check_month_close(o: Oracle) -> dict:
    doc_names = [d.Name for d in o.conn.Metadata.Documents if "Закрыт" in d.Name]
    closing = {}
    for name in doc_names:
        n = o.scalar(f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Документ.{name} КАК Т "
                     f"ГДЕ Т.Дата >= {AUG_START} И Т.Дата < {SEP_START} И Т.Проведен")
        closing[name] = int(n)
    residual = {}
    for code in ("811.1", "821", "216.1"):
        residual[code] = str(_sum(o, "Дт", code, f"И Т.Период < {SEP_START}")
                             - _sum(o, "Кт", code, f"И Т.Период < {SEP_START}"))
    return {"assertion": {"month_closure_confirmable": False},
            "observed": {"closing_document_types": doc_names, "posted_in_august": closing,
                         "residual_net_at_2026-08-31": residual},
            "verdict": "NOT_COMPUTABLE"}


def run_all(o: Oracle) -> dict[str, dict]:
    """NR-01..NR-10 -> comparison result.  NR-09 has no COM-computable form (document-level payment search)."""
    return {
        "NR-01": check_month_close(o),
        "NR-02": check_ending_balance(o, "216.1", Decimal("-1052.52")),
        "NR-03": check_turnover(o, "811.1", Decimal("197569.43"), Decimal("0.00")),
        "NR-04": check_turnover(o, "821", Decimal("48081.56"), Decimal("0.00")),
        "NR-05": check_211(o),
        "NR-06": check_211(o),
        "NR-07": check_cash_241_1(o),
        "NR-08": check_invoice_set(o),
        "NR-09": check_volta_metro(o),
        "NR-10": check_receipts_31_aug(o),
    }


def check_volta_metro(o: Oracle) -> dict:
    """VOLTA 216.00 and METRO 1625.82: both amounts exist as August postings; counterparties exist."""
    found = {}
    for label, amount in (("VOLTA", "216"), ("METRO", "1625.82")):
        rows = o.rows(f"ВЫБРАТЬ Т.Период КАК П, Т.СчетДт.Код КАК Д, Т.СчетКт.Код КАК К ИЗ {REG} КАК Т "
                      f"ГДЕ Т.Сумма = {amount} И Т.Активность И Т.Период >= {AUG_START} И Т.Период < {SEP_START}",
                      ("П", "Д", "К"))
        found[label] = [{"date": str(r["П"])[:10], "dr": str(r["Д"]), "cr": str(r["К"])} for r in rows]
    names = o.rows('ВЫБРАТЬ Т.Наименование КАК Н ИЗ Справочник.Контрагенты КАК Т ГДЕ Т.Наименование ПОДОБНО "%VOLTA%" '
                   'ИЛИ Т.Наименование ПОДОБНО "%METRO%"', ("Н",))
    ok = all(len(v) >= 1 for v in found.values()) and len(names) >= 2
    return {"assertion": {"volta": "216.00", "metro": "1625.82", "total": "1841.82"},
            "observed": {"postings_by_amount": found, "matching_counterparties": len(names)},
            "verdict": "AGREES" if ok else "DISAGREES",
            "notes": "amounts exist as postings; the 'missing receipt' semantics need document-level owner review"}


def invoice_rows(o: Oracle) -> list[dict]:
    """Per supplier invoice of the 21-set: is it present as a posted purchase document and do date/total agree?
    Only an index, a short hash of the number and booleans are returned (no supplier names, no per-invoice amounts)."""
    import hashlib

    with (REAL_REFERENCE / "invoice_cases_21.csv").open(encoding="utf-8-sig", newline="") as fh:
        cases = list(csv.DictReader(fh))
    rows = []
    for index, case in enumerate(cases, start=1):
        number = case["invoice_no"].replace('"', "")
        docs = o.rows("ВЫБРАТЬ Т.Дата КАК Д, Т.СуммаДокумента КАК С ИЗ Документ.ПоступлениеТоваровУслуг КАК Т "
                      f'ГДЕ Т.НомерВходящегоДокумента = "{number}" И Т.Проведен', ("Д", "С"))
        expected_total = Decimal(case["total_mdl"]).quantize(Decimal("0.01"))
        expected_date = case["onec_registration_date"].strip()
        found = len(docs) > 0
        amount_match = found and any(dec(d["С"]) == expected_total for d in docs)
        date_match = found and any(str(d["Д"])[:10] == expected_date for d in docs) if re_date(expected_date) else None
        rows.append({"index": index, "number_sha8": hashlib.sha256(number.encode()).hexdigest()[:8], "found": found,
                     "documents": len(docs), "amount_match": amount_match, "date_match": date_match,
                     "pdf_date_in_july_registration": expected_date.startswith("2026-07")})
    return rows


def re_date(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


def rule_applicability(o: Oracle, codes: set[str]) -> dict[str, dict]:
    """For every account code named by the month-close rule book: does it exist in the chart and did it move in 2026-08?"""
    out: dict[str, dict] = {}
    for code in sorted(codes):
        exists = int(o.scalar(f'ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ ПланСчетов.Хозрасчетный КАК Т ГДЕ Т.Код = "{code}"'))
        moved = int(o.scalar(
            f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ {REG} КАК Т ГДЕ Т.Период >= {AUG_START} И Т.Период < {SEP_START} "
            f'И (Т.СчетДт.Код ПОДОБНО "{code}%" ИЛИ Т.СчетКт.Код ПОДОБНО "{code}%")')) if exists else 0
        out[code] = {"exists_in_chart": exists > 0, "august_posting_rows": moved}
    return out
