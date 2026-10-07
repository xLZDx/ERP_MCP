"""NATIVE_COM_QUERY recomputation of the candidate assertions NR-01..NR-10 on the reference clone.

Comparison evidence only: each function recomputes the figure the candidate assertion states, from the clone's own
data through read-only COM queries, and reports AGREES / DISAGREES / NOT_COMPUTABLE.  None of this is native UI
report evidence and none of it can validate a semantic profile.
"""

from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path

from scripts.real1c.com_oracle import Oracle, dec

AUG_START = "ДАТАВРЕМЯ(2026,8,1)"
AUG_END = "ДАТАВРЕМЯ(2026,8,31,23,59,59)"
SEP_START = "ДАТАВРЕМЯ(2026,9,1)"
REG = "РегистрБухгалтерии.Хозрасчетный"
CANDIDATES = Path("D:/ERP_MCP_Testbed/1c/reference/scenario_pack/real_reference/candidate_assertions.json")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def load_assertions(path: Path = CANDIDATES) -> dict[str, dict]:
    """Candidate assertions come from the private owner file at run time; no business figure lives in this source."""
    import json

    return {c["id"]: c["assertion"] for c in json.loads(path.read_text(encoding="utf-8"))["cases"]}
REAL_REFERENCE = Path("D:/ERP_MCP_Testbed/1c/reference/scenario_pack/real_reference")


_SAFE_NUMBER = re.compile(r"[A-Za-z0-9/_.\-]+")
_SAFE_CODE = re.compile(r"[0-9.]+")
_SAFE_NAME = re.compile(r"[A-Za-z0-9 .\-]+")


def _safe(value: str, pattern: re.Pattern[str], what: str) -> str:
    """Values from the owner CSVs are interpolated into 1C queries: only plain tokens are accepted."""
    if not pattern.fullmatch(value):
        raise ValueError(f"unsafe {what} in an input file; refusing to build a query from it")
    return value


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


def check_211(o: Oracle, a: dict) -> dict:
    """Account 211 (and subaccounts) positions by analytics at 2026-08-31: closing balances, negatives, no movement."""

    def key(value) -> str:
        try:
            return o.guid(value)
        except (AttributeError, TypeError):  # a non-reference analytic value (string, number)
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
    ok = (len(balances) == a["nonzero_final"] and len(negative) == a["negative_final_positions"]
          and len(still) == a["no_movement_positions"] and value == money(a["no_movement_value"]))
    return {"assertion": {"nonzero_final": a["nonzero_final"], "negative_final_positions": a["negative_final_positions"],
                          "no_movement_positions": a["no_movement_positions"], "no_movement_value": str(money(a["no_movement_value"])),
                          "combinations": f"{a['combinations']} (history combos: not recomputed)"},
            "observed": observed, "verdict": "AGREES" if ok else "DISAGREES"}


def check_cash_241_1(o: Oracle, a: dict) -> dict:
    opening_where = f"И Т.Период < {AUG_START}"
    opening = _sum(o, "Дт", "241.1", opening_where) - _sum(o, "Кт", "241.1", opening_where)
    win = f"И Т.Период >= {AUG_START} И Т.Период < {SEP_START}"
    debit, credit = _sum(o, "Дт", "241.1", win), _sum(o, "Кт", "241.1", win)
    ending = opening + debit - credit
    return {"assertion": {"opening": str(money(a["opening"])), "payments": [str(money(x)) for x in a["payments"]],
                          "ending": str(money(a["ending"]))},
            "observed": {"opening": str(opening), "august_debit": str(debit), "august_credit": str(credit),
                         "ending": str(ending)},
            "verdict": "AGREES" if (opening == money(a["opening"]) and ending == money(a["ending"])) else "DISAGREES"}


def check_receipts_31_aug(o: Oracle, a: dict) -> dict:
    """The candidate lists 7 receipts of 31-Aug that lack source documents: they must be a subset of the posted
    receipts of that day (the clone has 8; the 7-set equals the day's total minus exactly one receipt)."""
    rows = o.rows("ВЫБРАТЬ Т.СуммаДокумента КАК С ИЗ Документ.ПоступлениеТоваровУслуг КАК Т "
                  "ГДЕ Т.Дата >= ДАТАВРЕМЯ(2026,8,31) И Т.Дата < ДАТАВРЕМЯ(2026,9,1) И Т.Проведен", ("С",))
    amounts = [dec(r["С"]) for r in rows]
    total, target = sum(amounts, Decimal("0.00")), money(a["total_incl_vat"])
    leftover = total - target
    subset = len(amounts) == a["receipt_count"] + 1 and amounts.count(leftover) >= 1
    return {"assertion": {"receipt_count": a["receipt_count"], "total_incl_vat": str(target)},
            "observed": {"posted_receipts_on_2026-08-31": len(amounts), "day_total": str(total),
                         "day_total_minus_candidate": str(leftover),
                         "a_single_receipt_equals_the_difference": subset},
            "verdict": "AGREES" if subset else "DISAGREES",
            "notes": "consistent as a 7-of-8 subset; which receipts lack archive documents needs the owner manifest"}


def check_invoice_set(o: Oracle, a: dict) -> dict:
    """21 supplier invoices (hashed-id comparison): find each incoming number among purchase documents."""
    with (REAL_REFERENCE / "invoice_cases_21.csv").open(encoding="utf-8-sig", newline="") as fh:
        wanted = list(csv.DictReader(fh))
    found, found_total, missing = 0, Decimal("0.00"), 0
    for case in wanted:
        number = _safe(case["invoice_no"], _SAFE_NUMBER, "invoice number")
        rows = o.rows("ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К, СУММА(Т.СуммаДокумента) КАК С ИЗ Документ.ПоступлениеТоваровУслуг "
                      f'КАК Т ГДЕ Т.НомерВходящегоДокумента = "{number}" И Т.Проведен', ("К", "С"))
        if int(rows[0]["К"]):
            found += 1
            found_total += dec(rows[0]["С"])
        else:
            missing += 1
    expected_total = sum((Decimal(c["total_mdl"]) for c in wanted), Decimal("0.00"))
    return {"assertion": {"invoice_count": a["invoice_count"], "total_incl_vat": str(money(a["total_incl_vat"])),
                          "matching_invoice_count": a["matching_invoice_count"],
                          "matching_total_incl_vat": str(money(a["matching_total_incl_vat"]))},
            "observed": {"pdf_invoices_listed": len(wanted), "pdf_total_listed": str(expected_total),
                         "found_as_posted_purchase_by_incoming_number": found, "not_found": missing,
                         "found_documents_total": str(found_total)},
            "verdict": "AGREES" if (len(wanted) == a["invoice_count"] and expected_total == money(a["total_incl_vat"])
                                    and found == a["matching_invoice_count"]
                                    and found_total == money(a["matching_total_incl_vat"])) else "DISAGREES"}


def check_month_close(o: Oracle) -> dict:
    doc_names = o.document_names("Закрыт")
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


def run_all(o: Oracle, assertions: dict[str, dict] | None = None) -> dict[str, dict]:
    """NR-01..NR-10 -> comparison result.  NR-09 has no COM-computable form (document-level payment search)."""
    a = assertions if assertions is not None else load_assertions()
    plan = {
        "NR-01": lambda: check_month_close(o),
        "NR-02": lambda: check_ending_balance(o, "216.1", money(a["A-216-1"]["ending_reconstructed"])),
        "NR-03": lambda: check_turnover(o, "811.1", money(a["A-811-1"]["august_debit"]), money(a["A-811-1"]["august_credit"])),
        "NR-04": lambda: check_turnover(o, "821", money(a["A-821"]["august_debit"]), money(a["A-821"]["august_credit"])),
        "NR-05": lambda: check_211(o, a["A-211"]),
        "NR-06": lambda: check_211(o, a["A-211"]),
        "NR-07": lambda: check_cash_241_1(o, a["A-241-1"]),
        "NR-08": lambda: check_invoice_set(o, a["INV-SET"]),
        "NR-09": lambda: check_volta_metro(o, a["INV-MISSING"]),
        "NR-10": lambda: check_receipts_31_aug(o, a["MISSING-PRIMARY"]),
    }
    out = {}
    for case_id, check in plan.items():
        o.label = case_id
        out[case_id] = check()
    return out


def check_volta_metro(o: Oracle, a: dict) -> dict:
    """The invoices recorded as 'payment found but receipt not found': does a posting with that exact amount exist in
    August and does the counterparty exist?  Names and amounts come from the owner CSV at run time; only counts leave."""
    with (REAL_REFERENCE / "invoice_cases_21.csv").open(encoding="utf-8-sig", newline="") as fh:
        wanted = [c for c in csv.DictReader(fh) if "not found" in c["result"].lower()]
    cases = []
    for index, case in enumerate(wanted, start=1):
        amount = str(Decimal(case["total_mdl"]).quantize(Decimal("0.01")))
        name = _safe(case["supplier"], _SAFE_NAME, "supplier name")
        postings = int(o.scalar(f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ {REG} КАК Т ГДЕ Т.Сумма = {amount} И Т.Активность "
                                f"И Т.Период >= {AUG_START} И Т.Период < {SEP_START}"))
        parties = int(o.scalar(f'ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Справочник.Контрагенты КАК Т ГДЕ Т.Наименование ПОДОБНО "%{name}%"'))
        cases.append({"index": index, "august_postings_with_exact_amount": postings, "matching_counterparties": parties})
    total = sum((Decimal(c["total_mdl"]) for c in wanted), Decimal("0.00"))
    ok = len(cases) == 2 and total == money(a["total"]) and all(c["august_postings_with_exact_amount"] >= 1 and c["matching_counterparties"] >= 1 for c in cases)
    return {"assertion": {"payment_found_receipt_not_found_cases": 2, "total": str(money(a["total"]))},
            "observed": {"cases": cases},
            "verdict": "AGREES" if ok else "DISAGREES",
            "notes": "a payment amount and the counterparty exist; the 'missing receipt' semantics need document-level owner review"}


def invoice_rows(o: Oracle) -> list[dict]:
    """Per supplier invoice of the 21-set: is it present as a posted purchase document and do date/total agree?
    Only an index, a short hash of the number and booleans are returned (no supplier names, no per-invoice amounts)."""
    import hashlib

    with (REAL_REFERENCE / "invoice_cases_21.csv").open(encoding="utf-8-sig", newline="") as fh:
        cases = list(csv.DictReader(fh))
    rows = []
    for index, case in enumerate(cases, start=1):
        o.label = f"INV-{index:02d}"
        number = _safe(case["invoice_no"], _SAFE_NUMBER, "invoice number")
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
        o.label = f"RULE-code {code}"
        if not _SAFE_CODE.fullmatch(code):  # a malformed code in the owner's rule book is reported, never queried
            out[code] = {"malformed": True, "exists_in_chart": False, "august_posting_rows": 0}
            continue
        exists = int(o.scalar(f'ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ ПланСчетов.Хозрасчетный КАК Т ГДЕ Т.Код = "{code}"'))
        moved = int(o.scalar(
            f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ {REG} КАК Т ГДЕ Т.Период >= {AUG_START} И Т.Период < {SEP_START} "
            f'И (Т.СчетДт.Код ПОДОБНО "{code}%" ИЛИ Т.СчетКт.Код ПОДОБНО "{code}%")')) if exists else 0
        out[code] = {"exists_in_chart": exists > 0, "august_posting_rows": moved}
    return out
