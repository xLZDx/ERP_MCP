"""Reconciliation service of the test lane: reads two gateways, runs R2 reference comparisons.

Honesty rules enforced here (see docs/phase2/artifacts/PHASE2_TESTLANE_MCP_DESIGN.md):
- MATCH is numeric agreement of two machine reads, never a native PASS.
- Incomplete data yields INCONCLUSIVE (R2 decides it), never a fake MATCH.
- Partial comparisons use their own state vocabulary (PARTIAL_*) so they cannot be mistaken for
  the R2 six-column MATCH.
- Amounts and names appear in a response only when ``show_values`` is true. Nothing is logged.
"""
from __future__ import annotations

import hashlib
import json
import pkgutil
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from business_ai_gateway import phase2 as _phase2_pkg
from business_ai_gateway.phase2.reconciliation import (
    BalanceSix,
    Comparison,
    ComparisonState,
    LedgerRow,
    LedgerScope,
    LedgerStatement,
    TolerancePolicy,
    compare_statements,
)

from .gateway_client import GatewayError, GatewayPort

AUTHORITY = "EVALUATION_ONLY"
STATUS_CEILING = "IMPLEMENTED_UNVERIFIED"
RELEASE2_VERDICT = "NO-GO"
POLICY_ID = "TESTLANE_EXACT_ZERO_TOLERANCE"
MAX_LISTED_DIFFS = 50
MATCH_NOTE = ("MATCH/PARTIAL_MATCH is numeric agreement between two machine reads of copies of the "
              "same base; it is NOT a native 1C PASS and NOT accounting approval.")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

# R2 BalanceSix field -> key in the gateway row of accounting_balance_and_turnovers
_SIX_MAP = {
    "opening_debit": "opening_debit",
    "opening_credit": "opening_credit",
    "turnover_debit": "debit_turnover",
    "turnover_credit": "credit_turnover",
    "closing_debit": "closing_debit",
    "closing_credit": "closing_credit",
}
SIX_FIELDS = tuple(_SIX_MAP)


class ShapeError(Exception):
    """A gateway response does not have the documented shape (fixed code, no payload text)."""


def _dec(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ShapeError("NUMBER_INVALID")
    if isinstance(value, Decimal | int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            raise ShapeError("NUMBER_INVALID") from None
    else:
        raise ShapeError("NUMBER_INVALID")
    if not number.is_finite():
        raise ShapeError("NUMBER_INVALID")
    return number


def _canon(value: Decimal) -> str:
    return format(value.normalize(), "f") if value != 0 else "0"


def _digest(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _labels(resp: dict[str, Any]) -> dict[str, Any]:
    def text(key: str) -> str:
        value = resp.get(key)
        return value if isinstance(value, str) and value else "ABSENT"

    warnings = resp.get("warnings")
    codes = [w for w in warnings if isinstance(w, str)] if isinstance(warnings, list) else []
    return {
        "profile_kind": text("profile_kind"),
        "evidence_level": text("evidence_level"),
        "native_reconciliation": text("native_reconciliation"),
        "warnings": codes,
    }


def _snapshot_ref(resp: dict[str, Any]) -> str:
    profile, metadata = resp.get("profile_fingerprint"), resp.get("metadata_fingerprint")
    if not (isinstance(profile, str) and profile and isinstance(metadata, str) and metadata):
        raise ShapeError("FINGERPRINT_ABSENT")
    return f"{profile}|{metadata}"


# ----------------------------------------------------------------------------- input validation


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime


def _aware(text: object) -> datetime:
    if not isinstance(text, str):
        raise ValueError("TIMESTAMP_INVALID")  # noqa: TRY004 - callers catch ValueError only
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("TIMESTAMP_INVALID") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMEZONE_OFFSET_REQUIRED")
    return value


def _refuse(code: str) -> dict[str, Any]:
    return {"state": "REFUSED", "reason_code": code, "authority": AUTHORITY,
            "note": "Input was refused before any gateway call."}


def validate_common(company_id: object, start: object, end: object) -> Period | dict[str, Any]:
    if not isinstance(company_id, str) or not _GUID.match(company_id):
        return _refuse("COMPANY_ID_INVALID")
    try:
        start_dt, end_dt = _aware(start), _aware(end)
    except ValueError as exc:
        return _refuse(f"PERIOD_{exc}")
    if start_dt >= end_dt:
        return _refuse("PERIOD_ORDER_INVALID")
    if start_dt.utcoffset() != end_dt.utcoffset():
        return _refuse("PERIOD_OFFSET_CHANGE_UNQUALIFIED")
    return Period(start_dt, end_dt)


# ----------------------------------------------------------------------------- six-column statement


@dataclass(frozen=True)
class SideTurnover:
    rows: dict[str, dict[str, Decimal]]  # account -> R2 BalanceSix field -> summed value
    rows_fetched: int
    complete: bool
    has_more: bool
    snapshot_ref: str
    labels: dict[str, Any]


def parse_turnover(resp: dict[str, Any]) -> SideTurnover:
    value, page = resp.get("value"), resp.get("page")
    if not isinstance(value, list) or not isinstance(page, dict):
        raise ShapeError("TURNOVER_SHAPE_INVALID")
    rows: dict[str, dict[str, Decimal]] = {}
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("account"), str) or not raw["account"]:
            raise ShapeError("TURNOVER_SHAPE_INVALID")
        acc = rows.setdefault(raw["account"], dict.fromkeys(SIX_FIELDS, Decimal(0)))
        for r2_name, wire_name in _SIX_MAP.items():
            acc[r2_name] += _dec(raw.get(wire_name))
    has_more, truncated = page.get("has_more"), page.get("truncated")
    if type(has_more) is not bool or type(truncated) is not bool:
        raise ShapeError("TURNOVER_SHAPE_INVALID")
    complete = (not has_more) and (not truncated) and page.get("returned") == len(value)
    return SideTurnover(rows, len(value), complete, has_more, _snapshot_ref(resp), _labels(resp))


def _scope(source_id: str, company_id: str, period: Period) -> LedgerScope:
    return LedgerScope(
        tenant_id="testlane", source_id=source_id, company_id=company_id,
        account="ALL_ACCOUNTS", start_inclusive=period.start, end_exclusive=period.end,
        currency_code="UNSPECIFIED", timezone_name=f"UTC{period.start.strftime('%z')}",
        grouping=("account",),
    )


def _statement(
    side: SideTurnover, scope: LedgerScope, *, force_complete: bool,
    perturb: tuple[str, str, Decimal] | None = None,
) -> LedgerStatement:
    balances: dict[str, BalanceSix] = {}
    for account, cols in side.rows.items():
        cols = dict(cols)
        if perturb is not None and perturb[0] == account:
            cols[perturb[1]] = cols[perturb[1]] + perturb[2]
        balances[account] = BalanceSix(**cols)
    zero = Decimal(0)
    # Totals are derived from the fetched rows (the gateway reports none), so the R2
    # aggregate-consistency guard is satisfied by construction. Documented limitation.
    totals = BalanceSix(**{
        name: sum((getattr(b, name) for b in balances.values()), zero) for name in SIX_FIELDS})
    return LedgerStatement(
        scope=scope, snapshot_ref=side.snapshot_ref, totals=totals,
        rows=tuple(LedgerRow(account, "ACCOUNT_LEVEL", bal) for account, bal in sorted(balances.items())),
        complete=True if force_complete else side.complete,
        report_revision=side.snapshot_ref,
    )


def _render_comparison(comp: Comparison, show_values: bool) -> dict[str, Any]:
    diffs: list[dict[str, Any]] = []
    for d in comp.differences[:MAX_LISTED_DIFFS]:
        entry: dict[str, Any] = {
            "level": "TOTAL" if d.row_key is None else "ROW",
            "measure": d.measure,
        }
        if d.row_key is not None:
            entry["account_digest"] = _short(d.row_key[0])
        if show_values:
            if d.row_key is not None:
                entry["account_ref"] = d.row_key[0]
            if d.expected is not None and d.actual is not None:
                entry["side_a"] = _canon(d.expected)
                entry["side_b"] = _canon(d.actual)
                entry["delta_b_minus_a"] = _canon(d.actual - d.expected)
        diffs.append(entry)
    return {
        "state": str(comp.state), "reason_code": comp.reason_code, "policy_id": comp.policy_id,
        "authority": comp.authority, "difference_count": len(comp.differences),
        "differences": diffs, "differences_truncated": len(comp.differences) > MAX_LISTED_DIFFS,
    }


def _side_summary(side: SideTurnover) -> dict[str, Any]:
    return {
        "rows_fetched": side.rows_fetched, "accounts": len(side.rows),
        "has_more": side.has_more, "page_complete": side.complete,
        "rows_digest": _digest({a: {k: _canon(v) for k, v in c.items()} for a, c in side.rows.items()}),
        **side.labels,
    }


def six_column_section(
    a: SideTurnover, b: SideTurnover, source_id: str, company_id: str, period: Period,
    show_values: bool, *, force_complete: bool = False,
    perturb_b: tuple[str, str, Decimal] | None = None,
) -> dict[str, Any]:
    try:
        scope = _scope(source_id, company_id, period)
        stmt_a = _statement(a, scope, force_complete=force_complete)
        stmt_b = _statement(b, scope, force_complete=force_complete, perturb=perturb_b)
    except ValueError as exc:
        return {"state": "ERROR", "reason_code": f"R2_INPUT_REFUSED_{exc}"}
    comp = compare_statements(
        stmt_a, stmt_b, policy=TolerancePolicy(POLICY_ID, Decimal(0)))
    out = _render_comparison(comp, show_values)
    out.update({
        "comparison": "R2_RECONCILIATION_COMPARE_STATEMENTS",
        "adaptation": ("per-ACCOUNT rows (gateway rows summed per account) used as the analytic key; "
                       "contract_ref is the constant ACCOUNT_LEVEL; totals are derived from the fetched "
                       "rows; side A takes R2's 'native' slot and side B the 'gateway' slot only "
                       "positionally (neither is a native 1C report)."),
        "side_a": _side_summary(a), "side_b": _side_summary(b),
    })
    out["reason_code_side_mapping"] = "NATIVE_* refers to side A, GATEWAY_* refers to side B"
    if out["state"] == "INCONCLUSIVE":
        out["inconclusive_explanation"] = (
            "R2 refuses to call MATCH or MISMATCH on this input (see reason_code); "
            "the gateway tool has no paging argument, so a page with has_more=true can never be complete."
            if (a.has_more or b.has_more) else "R2 refuses to call MATCH or MISMATCH on this input.")
    return out


# ----------------------------------------------------------------------------- 521.1 partial


def _analytics_rows(resp: dict[str, Any]) -> dict[tuple[str, ...], tuple[Decimal, Decimal]]:
    rows = resp.get("rows")
    if not isinstance(rows, list):
        raise ShapeError("ANALYTICS_SHAPE_INVALID")
    out: dict[tuple[str, ...], tuple[Decimal, Decimal]] = {}
    for raw in rows:
        if not isinstance(raw, dict) or not isinstance(raw.get("account_key"), str):
            raise ShapeError("ANALYTICS_SHAPE_INVALID")
        analytics = raw.get("analytics")
        if not isinstance(analytics, list):
            raise ShapeError("ANALYTICS_SHAPE_INVALID")
        parts: list[str] = [raw["account_key"]]
        for item in analytics:
            if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
                raise ShapeError("ANALYTICS_SHAPE_INVALID")
            parts.append(f"{item.get('slot')}:{item['ref']}")
        key = tuple(parts)
        debit, credit = _dec(raw.get("balance_debit")), _dec(raw.get("balance_credit"))
        old = out.get(key, (Decimal(0), Decimal(0)))
        out[key] = (old[0] + debit, old[1] + credit)
    return out


def _analytics_ready(resp: dict[str, Any]) -> str | None:
    summary = resp.get("supplier_summary")
    if not isinstance(summary, dict) or summary.get("status") != "COMPLETE":
        return "SUPPLIER_SUMMARY_NOT_COMPLETE"
    if resp.get("truncated") is not False:
        return "ANALYTICS_TRUNCATED"
    rows = resp.get("rows")
    if not isinstance(rows, list) or not rows or resp.get("row_count") != len(rows):
        return "ANALYTICS_ROWS_INCOMPLETE"
    return None


def supplier_partial_section(
    resp_a: dict[str, Any], resp_b: dict[str, Any], show_values: bool,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "comparison": "PARTIAL_521_1_CLOSING_BALANCES",
        "partial_note": ("Only closing debit/credit exist in this tool; no opening balance and no "
                         "turnovers, so this is NOT the six-column R2 comparison. Plain exact-decimal "
                         "comparison per analytic row."),
        "authority": AUTHORITY,
        "side_a": _labels(resp_a), "side_b": _labels(resp_b),
    }
    try:
        rows_a, rows_b = _analytics_rows(resp_a), _analytics_rows(resp_b)
        ref_a, ref_b = _snapshot_ref(resp_a), _snapshot_ref(resp_b)
    except ShapeError as exc:
        return {**base, "state": "ERROR", "reason_code": str(exc)}
    base["side_a"]["rows"], base["side_b"]["rows"] = len(rows_a), len(rows_b)
    base["side_a"]["rows_digest"] = _digest({"|".join(k): [_canon(v[0]), _canon(v[1])] for k, v in rows_a.items()})
    base["side_b"]["rows_digest"] = _digest({"|".join(k): [_canon(v[0]), _canon(v[1])] for k, v in rows_b.items()})
    for tag, resp in (("SIDE_A", resp_a), ("SIDE_B", resp_b)):
        problem = _analytics_ready(resp)
        if problem:
            return {**base, "state": "INCONCLUSIVE", "reason_code": f"{tag}_{problem}",
                    "difference_count": 0, "differences": []}
    if ref_a != ref_b:
        return {**base, "state": "INCONCLUSIVE", "reason_code": "SOURCE_SNAPSHOT_MISMATCH",
                "difference_count": 0, "differences": []}
    diffs: list[dict[str, Any]] = []
    count = 0
    for key in sorted(rows_a.keys() | rows_b.keys()):
        va, vb = rows_a.get(key), rows_b.get(key)
        entries: list[dict[str, Any]] = []
        if va is None or vb is None:
            entries.append({"measure": "ROW_MISSING_IN_A" if va is None else "ROW_MISSING_IN_B"})
        else:
            for idx, name in enumerate(("closing_debit", "closing_credit")):
                if va[idx] != vb[idx]:
                    entry: dict[str, Any] = {"measure": name}
                    if show_values:
                        entry.update({"side_a": _canon(va[idx]), "side_b": _canon(vb[idx]),
                                      "delta_b_minus_a": _canon(vb[idx] - va[idx])})
                    entries.append(entry)
        for entry in entries:
            count += 1
            if len(diffs) < MAX_LISTED_DIFFS:
                entry["row_digest"] = _short("|".join(key))
                if show_values:
                    entry["analytic_refs"] = list(key)
                diffs.append(entry)
    state = "PARTIAL_MISMATCH" if count else "PARTIAL_MATCH"
    return {**base, "state": state,
            "reason_code": "CLOSING_VALUES_DIFFER" if count else "CLOSING_VALUES_EQUAL",
            "difference_count": count, "differences": diffs,
            "differences_truncated": count > MAX_LISTED_DIFFS}


# ----------------------------------------------------------------------------- purchases

# Fields compare_posted_purchases needs that purchase_documents does not deliver.
_PURCHASE_REQUIRED_BY_R2 = ("contract_ref", "deletion_mark")


def _purchase_rows(resp: dict[str, Any]) -> tuple[dict[str, tuple[str, ...]], bool, set[str]]:
    value, page = resp.get("value"), resp.get("page")
    if not isinstance(value, list) or not isinstance(page, dict):
        raise ShapeError("PURCHASE_SHAPE_INVALID")
    rows: dict[str, tuple[str, ...]] = {}
    keys: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("document_ref"), str):
            raise ShapeError("PURCHASE_SHAPE_INVALID")
        keys.update(raw)
        if raw["document_ref"] in rows:
            raise ShapeError("PURCHASE_DUPLICATE_REF")
        rows[raw["document_ref"]] = (
            str(raw.get("counterparty")), str(raw.get("currency")), str(raw.get("date")),
            str(raw.get("document_number")), _canon(_dec(raw.get("amount"))), str(raw.get("posted")),
        )
    return rows, page.get("has_more") is not False, keys


def purchases_section(
    resp_a: dict[str, Any], resp_b: dict[str, Any], show_values: bool,
) -> dict[str, Any]:
    try:
        rows_a, more_a, keys_a = _purchase_rows(resp_a)
        rows_b, more_b, keys_b = _purchase_rows(resp_b)
    except ShapeError as exc:
        return {"comparison": "PURCHASE_DOCUMENTS", "state": "ERROR", "reason_code": str(exc)}
    missing = [f for f in _PURCHASE_REQUIRED_BY_R2 if f not in keys_a or f not in keys_b]
    reasons = [f"PURCHASE_FIELD_NOT_PROVIDED_{f.upper()}" for f in missing]
    reasons.append("PURCHASE_LISTING_SPANS_COUNTERPARTIES_R2_SCOPE_IS_ONE")
    if more_a or more_b:
        reasons.append("PURCHASE_PAGE_INCOMPLETE_NO_PAGING_ARGUMENT")
    diff_count = sum(1 for k in rows_a.keys() | rows_b.keys() if rows_a.get(k) != rows_b.get(k))
    return {
        "comparison": "PURCHASE_DOCUMENTS",
        "state": "NOT_SUPPORTED",
        "reason_codes": reasons,
        "explanation": ("R2 compare_posted_purchases needs contract_ref, deletion_mark and a "
                        "single-counterparty complete listing; the gateway listing lacks them. No "
                        "values were invented to force a call."),
        "authority": AUTHORITY,
        "informational_first_page": {
            "label": "PARTIAL_FIRST_PAGE_ONLY_NOT_AN_R2_RESULT",
            "state": "PARTIAL_MISMATCH" if diff_count else "PARTIAL_MATCH",
            "documents_a": len(rows_a), "documents_b": len(rows_b),
            "differing_documents": diff_count,
            "digest_a": _digest({k: list(v) for k, v in rows_a.items()}),
            "digest_b": _digest({k: list(v) for k, v in rows_b.items()}),
            **({"differing_document_refs": sorted(
                k for k in rows_a.keys() | rows_b.keys() if rows_a.get(k) != rows_b.get(k)
            )[:MAX_LISTED_DIFFS]} if show_values else {}),
        },
        "side_a": _labels(resp_a), "side_b": _labels(resp_b),
    }


# ----------------------------------------------------------------------------- service


def _error_entry(exc: GatewayError) -> dict[str, Any]:
    entry: dict[str, Any] = {"state": "ERROR", "reason_code": exc.code}
    if exc.detail_code:
        entry["detail_code"] = exc.detail_code
    return entry


def _safe(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except GatewayError as exc:
        return _error_entry(exc)
    except ShapeError as exc:
        return {"state": "ERROR", "reason_code": str(exc)}


class Reconciler:
    def __init__(self, side_a: GatewayPort, side_b: GatewayPort, source_id: str) -> None:
        self._a, self._b, self._source_id = side_a, side_b, source_id

    def _fetch(self, gateway: GatewayPort, calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for tool, args in calls:
            try:
                out[tool] = gateway.call(tool, args)
            except GatewayError as exc:
                out[tool] = exc
        return out

    def _fetch_both(self, calls: list[tuple[str, dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(self._fetch, self._a, calls)
            fb = pool.submit(self._fetch, self._b, calls)
            return fa.result(), fb.result()

    def reconcile_two_bases(
        self, company_id: str, as_of: str, start_period: str, end_period: str,
        show_values: bool = False,
    ) -> dict[str, Any]:
        period = validate_common(company_id, start_period, end_period)
        if isinstance(period, dict):
            return period
        try:
            _aware(as_of)
        except ValueError as exc:
            return _refuse(f"AS_OF_{exc}")
        src = self._source_id
        calls: list[tuple[str, dict[str, Any]]] = [
            ("accounting_balance_and_turnovers",
             {"source_id": src, "company_id": company_id,
              "start_period": start_period, "end_period": end_period}),
            ("accounting_balance_by_analytics",
             {"source_id": src, "company_id": company_id, "as_of": as_of}),
            # The gateway tool takes only source_id/company_id/top/skip; period arguments are rejected.
            ("purchase_documents", {"source_id": src, "company_id": company_id}),
        ]
        ra, rb = self._fetch_both(calls)

        def pair(tool: str, build: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
            for side in (ra[tool], rb[tool]):
                if isinstance(side, GatewayError):
                    return _error_entry(side)
            return _safe(lambda: build(ra[tool], rb[tool]))

        def six(resp_a: dict[str, Any], resp_b: dict[str, Any]) -> dict[str, Any]:
            return six_column_section(
                parse_turnover(resp_a), parse_turnover(resp_b), src, company_id, period, show_values)

        return {
            "tool": "phase2_reconcile_two_bases", "label": "TESTLANE_RECONCILIATION",
            "authority": AUTHORITY, "status_ceiling": STATUS_CEILING,
            "release2_verdict": RELEASE2_VERDICT, "native_pass": False, "note": MATCH_NOTE,
            "independence_note": ("Both gateways read copies of the same base through the same "
                                  "source_id and company_id: this is a copy-consistency check, not "
                                  "independent-origin evidence."),
            "show_values": show_values,
            "sections": {
                "six_column_per_account": pair("accounting_balance_and_turnovers", six),
                "supplier_521_1_closing_partial": pair(
                    "accounting_balance_by_analytics",
                    lambda x, y: supplier_partial_section(x, y, show_values)),
                "purchase_documents": pair(
                    "purchase_documents", lambda x, y: purchases_section(x, y, show_values)),
            },
        }

    def negative_control(
        self, company_id: str, start_period: str, end_period: str,
        delta: str = "1", measure: str = "closing_debit", show_values: bool = False,
    ) -> dict[str, Any]:
        period = validate_common(company_id, start_period, end_period)
        if isinstance(period, dict):
            return period
        if measure not in SIX_FIELDS:
            return _refuse("MEASURE_INVALID")
        try:
            delta_value = _dec(delta)
        except ShapeError:
            return _refuse("DELTA_INVALID")
        if delta_value == 0 or abs(delta_value) > Decimal(1000000000000):
            return _refuse("DELTA_INVALID")
        call = ("accounting_balance_and_turnovers",
                {"source_id": self._source_id, "company_id": company_id,
                 "start_period": start_period, "end_period": end_period})
        ra, rb = self._fetch_both([call])
        for side in (ra[call[0]], rb[call[0]]):
            if isinstance(side, GatewayError):
                return {"tool": "phase2_reconcile_negative_control", **_error_entry(side),
                        "label": "SYNTHETIC_NEGATIVE_CONTROL"}

        def run() -> dict[str, Any]:
            a, b = parse_turnover(ra[call[0]]), parse_turnover(rb[call[0]])
            if not b.rows:
                return {"state": "INCONCLUSIVE", "reason_code": "SIDE_B_EMPTY"}
            account = min(b.rows)
            baseline = six_column_section(
                a, b, self._source_id, company_id, period, show_values, force_complete=True)
            perturbed = six_column_section(
                a, b, self._source_id, company_id, period, show_values, force_complete=True,
                perturb_b=(account, measure, delta_value))
            found = _control_expectation_met(baseline, perturbed, account, measure, delta_value, a, b)
            return {
                "state": "CONTROL_DETECTED" if found else "CONTROL_NOT_DETECTED",
                "reason_code": ("EXACT_INJECTED_DIFFERENCE_FOUND" if found
                                else "INJECTED_DIFFERENCE_NOT_ISOLATED"),
                "baseline_state": baseline["state"],
                "perturbed_state": perturbed["state"],
                "injected": {"side": "B", "measure": measure, "delta": _canon(delta_value),
                             "account_digest": _short(account),
                             **({"account_ref": account} if show_values else {})},
                "perturbed_differences": perturbed["differences"],
                "perturbed_difference_count": perturbed["difference_count"],
                "baseline_difference_count": baseline["difference_count"],
                "side_a": baseline["side_a"], "side_b": baseline["side_b"],
            }

        body = _safe(run)
        return {
            "tool": "phase2_reconcile_negative_control", "label": "SYNTHETIC_NEGATIVE_CONTROL",
            "authority": AUTHORITY, "status_ceiling": STATUS_CEILING, "native_pass": False,
            "synthetic_completeness_assumed": True,
            "note": ("The fetched page is TREATED AS COMPLETE only so the detector can be shown; the "
                     "live statement itself may be incomplete. One side-B row was changed in memory by "
                     "a known delta; nothing was written to any base. This proves the comparison logic "
                     "detects a known difference, not that the real bases agree."),
            "show_values": show_values, **body,
        }


def _control_expectation_met(
    baseline: dict[str, Any], perturbed: dict[str, Any], account: str, measure: str,
    delta: Decimal, a: SideTurnover, b: SideTurnover,
) -> bool:
    if baseline.get("state") != "MATCH" or perturbed.get("state") != "MISMATCH":
        return False
    if perturbed.get("difference_count") != 2 or perturbed.get("differences_truncated"):
        return False
    levels = {(d.get("level"), d.get("measure")) for d in perturbed["differences"]}
    if levels != {("ROW", measure), ("TOTAL", measure)}:
        return False
    return all(d.get("account_digest", _short(account)) == _short(account)
               for d in perturbed["differences"]) and a.rows.keys() == b.rows.keys()


def capabilities(config_state: dict[str, bool]) -> dict[str, Any]:
    exposed = {
        "reconciliation": "phase2_reconcile_two_bases, phase2_reconcile_negative_control",
        "purchase_reconciliation": "NOT_SUPPORTED on the current gateway shape (see purchase section)",
    }
    modules = sorted(m.name for m in pkgutil.iter_modules(_phase2_pkg.__path__)
                     if not m.name.startswith("_"))
    return {
        "tool": "phase2_capabilities", "server_status": "TESTLANE_EVALUATION_ONLY",
        "phase2_status_ceiling": STATUS_CEILING, "release2_verdict": RELEASE2_VERDICT,
        "authority": AUTHORITY, "gates_passed": [],
        "statement": ("Phase 2 modules are offline reference code, unwired, NO-GO; tests prove "
                      "classification over scripted inputs, not product acceptance. This server only "
                      "feeds two of them with real read-only gateway data."),
        "phase2_modules": [
            {"module": m, "status": STATUS_CEILING, "authority": AUTHORITY,
             "exposed_in_testlane": exposed.get(m)} for m in modules],
        "tools": ["phase2_capabilities", "phase2_reconcile_two_bases",
                  "phase2_reconcile_negative_control"],
        "not_covered": [
            "S8 job API endpoints ENQUEUE_JOB/RERUN/PAUSE_SOURCE/REVOKE_ATTESTATION/READ_JOB/READ_RESULT",
            "living.* SQL ports and any persistence",
            "Google Drive connector",
            "native 1C report capture and evidence attestation",
            "complete six-column statements (gateway tool returns at most 200 rows, no paging)",
        ],
        "gateways_configured": config_state,
        "honesty_rules": [
            "MATCH is never native PASS",
            "incomplete data gives INCONCLUSIVE, never a fake MATCH",
            "amounts and names only with show_values=true (default false); nothing is logged",
        ],
    }


__all__ = ["ComparisonState", "Reconciler", "capabilities", "validate_common"]
