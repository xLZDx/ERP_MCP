"""Read-only presentation of validated 521.1 analytics as supplier credit/debit balances.

This is NOT a general AP/open-item report. It never matches payments to invoices,
nets advances, infers currency, or upgrades machine evidence to native UI evidence.
"""
from __future__ import annotations

from decimal import Context, Decimal, InvalidOperation

_MATH = Context(prec=80)
from typing import Any
from uuid import UUID

ACCOUNT = "521.1"
COUNTERPARTY_TYPE = "Catalog.Контрагенты"


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("SUPPLIER_SUMMARY_INVALID_REF")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("SUPPLIER_SUMMARY_INVALID_REF") from exc


def _money(value: object) -> Decimal:
    if not isinstance(value, str) or len(value) > 90:
        raise ValueError("SUPPLIER_SUMMARY_INVALID_AMOUNT")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("SUPPLIER_SUMMARY_INVALID_AMOUNT") from exc
    # Bounded decimal contract: reject giant exponent/precision before string formatting.
    if (not amount.is_finite() or amount < 0 or amount.adjusted() > 25
            or amount.as_tuple().exponent < -8 or len(amount.as_tuple().digits) > 38):
        raise ValueError("SUPPLIER_SUMMARY_INVALID_AMOUNT")
    return amount


def supplier_refs(rows: list[dict[str, Any]]) -> list[str]:
    """Return only exact GUIDs proven by the account analytics result."""
    refs: set[str] = set()
    for row in rows:
        if row.get("account") != ACCOUNT:
            return []
        analytics = row.get("analytics")
        if not isinstance(analytics, list):
            raise TypeError("SUPPLIER_SUMMARY_INVALID_ANALYTICS")
        candidates = [a for a in analytics if isinstance(a, dict) and a.get("role") == "counterparty"]
        if len(candidates) != 1 or candidates[0].get("type") != COUNTERPARTY_TYPE:
            raise ValueError("SUPPLIER_SUMMARY_INVALID_ANALYTICS")
        refs.add(_uuid(candidates[0].get("ref")))
    return sorted(refs)


def supplier_filter_batches(
    refs: list[str], *, max_filter_chars: int
) -> list[tuple[list[str], str]]:
    """Bound exact-key OData filters; no arbitrary selectors or untrusted raw text."""
    groups: list[tuple[list[str], str]] = []
    selected: list[str] = []
    parts: list[str] = []
    size = 0
    for raw in refs:
        ref = _uuid(raw)
        clause = f"Ref_Key eq guid'{ref}'"
        if len(clause) > max_filter_chars:
            raise ValueError("SUPPLIER_CATALOG_FILTER_LIMIT")
        additional = len(clause) + (4 if parts else 0)
        if parts and size + additional > max_filter_chars:
            groups.append((selected, " or ".join(parts)))
            selected, parts, size = [], [], 0
        selected.append(ref)
        parts.append(clause)
        size += len(clause) + (4 if len(parts) > 1 else 0)
    if parts:
        groups.append((selected, " or ".join(parts)))
    return groups


def _sum_amounts(items: list[dict[str, Any]], field: str) -> str:
    total = Decimal(0)
    for item in items:
        total = _MATH.add(total, Decimal(item[field]))
    return format(total, "f")


def summarize_supplier_5211(
    rows: list[dict[str, Any]],
    *,
    names: dict[str, str] | None = None,
    truncated: bool = False,
    max_rows: int = 200,
) -> dict[str, Any]:
    """Aggregate gross credit and debit separately; never assert a net settlement."""
    base: dict[str, Any] = {
        "account": ACCOUNT,
        "scope": "ACCOUNT_521_1_ONLY",
        "not_an_aging_report": True,
        "netting_performed": False,
    }
    if truncated or len(rows) >= max_rows:
        return {**base, "status": "INCOMPLETE", "reason": "SOURCE_TRUNCATED"}
    if any(row.get("account") != ACCOUNT for row in rows):
        return {**base, "status": "NOT_APPLICABLE", "reason": "PROFILE_HAS_OTHER_ACCOUNTS"}
    valid_refs = supplier_refs(rows)
    names = names or {}
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in rows:
        counterparty = next(a for a in row["analytics"] if a["role"] == "counterparty")
        ref = _uuid(counterparty["ref"])
        currency = row.get("currency_ref")
        currency = _uuid(currency) if currency is not None else None
        key = (ref, currency)
        item = grouped.setdefault(key, {"counterparty_ref": ref, "currency_ref": currency,
                                        "credit": Decimal(0), "debit": Decimal(0),
                                        "contracts": set(), "missing_contract_rows": 0})
        item["credit"] = _MATH.add(item["credit"], _money(row.get("balance_credit")))
        item["debit"] = _MATH.add(item["debit"], _money(row.get("balance_debit")))
        contracts = [a for a in row["analytics"] if a.get("role") == "contract"]
        if len(contracts) > 1:
            raise ValueError("SUPPLIER_SUMMARY_INVALID_ANALYTICS")
        if contracts and contracts[0].get("ref") is not None:
            item["contracts"].add(_uuid(contracts[0]["ref"]))
        else:
            item["missing_contract_rows"] += 1
    items = []
    for value in grouped.values():
        ref = value["counterparty_ref"]
        candidate_name = names.get(ref)
        name = candidate_name if isinstance(candidate_name, str) and candidate_name.strip() else None
        items.append({
            "counterparty_ref": ref, "supplier_name": name,
            "currency_ref": value["currency_ref"],
            "balance_credit": format(value["credit"], "f"),
            "balance_debit": format(value["debit"], "f"),
            "contract_refs": sorted(value["contracts"]),
            "contract_refs_complete": value["missing_contract_rows"] == 0,
        })
    items.sort(key=lambda item: (-Decimal(item["balance_credit"]),
                                 -Decimal(item["balance_debit"]), item["counterparty_ref"]))
    currencies = {item["currency_ref"] for item in items}
    mixed = len(currencies) > 1
    return {
        **base,
        "status": "COMPLETE",
        "source_row_count": len(rows),
        "counterparty_count": len(valid_refs),
        "currency_status": "MIXED_NO_AGGREGATION" if mixed else
                           ("UNKNOWN" if not currencies or None in currencies else "IDENTIFIED"),
        "total_balance_credit": None if mixed else _sum_amounts(items, "balance_credit"),
        "total_balance_debit": None if mixed else _sum_amounts(items, "balance_debit"),
        "suppliers": items,
    }
