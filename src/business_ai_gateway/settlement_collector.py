"""Receivable/payable open-item aging collector (read-only, profile-confirmed record set).

Turns normalized register rows of a source-confirmed settlement record set into a
SettlementObservation and delegates all aging arithmetic to settlement_aging.evaluate_aging.
validated_profiles is derived server-side from the profile in use, never from tool input.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .external_evidence import EvidenceScope
from .semantic import (
    SemanticMappingUnconfirmed,
    build_company_filter,
)
from .settlement_aging import (
    AgingProfile,
    SettlementAllocation,
    SettlementDocument,
    SettlementObservation,
    SettlementPayment,
    evaluate_aging,
)

RECEIVABLE_OPEN_ITEMS_CONCEPT = "receivable.open_items"
PAYABLE_OPEN_ITEMS_CONCEPT = "payable.open_items"
OPEN_ITEMS_CONCEPTS = {
    RECEIVABLE_OPEN_ITEMS_CONCEPT: "AR",
    PAYABLE_OPEN_ITEMS_CONCEPT: "AP",
}
OPEN_ITEM_FIELDS = (
    "counterparty_ref",
    "contract_ref",
    "document_ref",
    "date",
    "due_date",
    "amount",
    "record_type",
    "settled_document_ref",
)
MAX_OPEN_ITEM_ROWS = 2000
# Reasons that mean the source answer cannot be trusted; the tool audits them as outcome=error.
OPEN_ITEMS_FAILURE_REASONS = frozenset({
    "COMPANY_SCOPE_MISMATCH", "SETTLEMENT_FACT_INVALID", "AGING_ROWS_TRUNCATED",
    "SOURCE_RESPONSE_INVALID",
})
_RECORD_REGISTER = re.compile(r"^(?:Accumulation|Information)Register_[\w\u0080-￿]+$")
_PROPERTY = re.compile(r"^[\w\u0080-￿]+$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")


def validate_open_items_mapping(concept: str, mapping: dict[str, Any]) -> str:
    """Validate a reviewed open-item record-set mapping; returns AR or AP."""
    kind = OPEN_ITEMS_CONCEPTS.get(concept)
    allowed = {
        "entity_set", "company_scope", "output_fields", "record_type_values", "currency",
        "opening_items_known", "evidence_level", "required_register_capabilities",
    }
    if kind is None or not isinstance(mapping, dict) or set(mapping) - allowed:
        raise SemanticMappingUnconfirmed("open-item mapping concept/object is unsupported")
    scope = mapping.get("company_scope")
    fields = mapping.get("output_fields")
    values = mapping.get("record_type_values")
    entity_set = mapping.get("entity_set")
    if (
        not isinstance(entity_set, str)
        or not _RECORD_REGISTER.fullmatch(entity_set)
        or not isinstance(scope, dict)
        or set(scope) != {"field", "value_type"}
        or not isinstance(scope.get("field"), str)
        or not _PROPERTY.fullmatch(scope["field"])
        or scope.get("value_type") not in {"guid", "string"}
        or not isinstance(fields, dict)
        or set(fields) != set(OPEN_ITEM_FIELDS)
        or any(not isinstance(v, str) or not _PROPERTY.fullmatch(v) for v in fields.values())
        or len(set(fields.values())) != len(OPEN_ITEM_FIELDS)
        or scope["field"] in fields.values()
        or not isinstance(values, dict)
        or set(values) != {"charge", "payment"}
        or any(
            not isinstance(v, list) or not v or any(not isinstance(x, str) or not x for x in v)
            for v in values.values()
        )
        or set(values["charge"]) & set(values["payment"])
        or not isinstance(mapping.get("currency"), str)
        or not re.fullmatch(r"[A-Z]{3}", mapping["currency"])
        or type(mapping.get("opening_items_known")) is not bool
        or mapping.get("required_register_capabilities", []) != []
        or mapping.get("evidence_level", "L1") not in {"L1", "L2-A", "L2-B", "L3"}
    ):
        raise SemanticMappingUnconfirmed("open-item mapping is incomplete or unsupported")
    return kind


def build_open_items_query(
    concept: str, mapping: dict[str, Any], *, company_external_ref: str
) -> tuple[str, list[str], str, str]:
    validate_open_items_mapping(concept, mapping)
    fields = mapping["output_fields"]
    select = [*fields.values(), mapping["company_scope"]["field"]]
    orderby = f"{fields['date']} asc,{fields['document_ref']} asc"
    return mapping["entity_set"], select, build_company_filter(mapping, company_external_ref), orderby


class OpenItemsInvalid(ValueError):
    pass


def _amount(raw: Any) -> Decimal:
    """Exact Decimal of a source amount; imprecise binary floats are rejected, never rounded."""
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise OpenItemsInvalid("amount")
        # A JSON number parsed as float keeps at most 15 reliable significant digits.
        if len(Decimal(repr(raw)).normalize().as_tuple().digits) > 15:
            raise OpenItemsInvalid("amount")
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise OpenItemsInvalid("amount") from None


def _day(value: Any) -> date:
    if not isinstance(value, str) or len(value) < 10:
        raise OpenItemsInvalid("date")
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise OpenItemsInvalid("date") from None


@dataclass(frozen=True, slots=True)
class OpenItemsResult:
    body: dict[str, Any]
    status: str


def _result(
    kind: str, status: str, reason: str, *, rows=None, anomalies=None, summary=None,
    evidence_level=None, truncated=False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": status,
        "reason": reason,
        "rows": rows or [],
        "summary": summary or [],
        "anomalies": anomalies or [],
        "evidence_level": evidence_level,
        "truncated": truncated,
        "native_approval_inferred": False,
        "human_review_required": True,
    }


def evaluate_open_items(
    concept: str,
    mapping: dict[str, Any],
    raw_rows: Any,
    *,
    source_id: str,
    company_id: str,
    company_external_ref: str,
    as_of: date,
    row_limit: int,
    metadata_fingerprint: str,
    profile_fingerprint: str,
    synthetic: bool,
    source_truncated: bool = False,
) -> dict[str, Any]:
    """Return the aging payload (PASS/FINDING/INCONCLUSIVE); never raises on bad business data."""
    kind = validate_open_items_mapping(concept, mapping)
    fields = mapping["output_fields"]
    if not isinstance(raw_rows, list):
        return _result(kind, "INCONCLUSIVE", "SOURCE_RESPONSE_INVALID")
    truncated = source_truncated or len(raw_rows) >= row_limit
    if truncated:
        return _result(kind, "INCONCLUSIVE", "AGING_ROWS_TRUNCATED", truncated=True)
    if not mapping["opening_items_known"]:
        return _result(kind, "INCONCLUSIVE", "OPENING_ITEMS_UNCONFIRMED")
    directions = {
        value: direction
        for direction, values in mapping["record_type_values"].items()
        for value in values
    }
    scope_field = mapping["company_scope"]["field"]
    documents: list[SettlementDocument] = []
    payments: list[SettlementPayment] = []
    allocations: list[SettlementAllocation] = []
    try:
        for row in raw_rows:
            if not isinstance(row, dict) or any(
                f not in row for f in (*fields.values(), scope_field)
            ):
                raise OpenItemsInvalid("row")
            if str(row[scope_field]).lower() != company_external_ref.lower():
                return _result(kind, "INCONCLUSIVE", "COMPANY_SCOPE_MISMATCH")
            record_type = row[fields["record_type"]]
            raw_amount = row[fields["amount"]]
            if (
                not isinstance(record_type, str)
                or directions.get(record_type) is None
                or isinstance(raw_amount, bool)
            ):
                raise OpenItemsInvalid("row")
            direction = directions[record_type]
            amount = _amount(raw_amount)
            counterparty = str(row[fields["counterparty_ref"]])
            contract = str(row[fields["contract_ref"]])
            ref = str(row[fields["document_ref"]])
            business_date = _day(row[fields["date"]])
            if direction == "charge":
                documents.append(
                    SettlementDocument(
                        ref, counterparty, contract, business_date,
                        _day(row[fields["due_date"]]), amount,
                    )
                )
            else:
                payments.append(
                    SettlementPayment(ref, counterparty, contract, business_date, amount)
                )
                settled = row[fields["settled_document_ref"]]
                if settled not in (None, ""):
                    allocations.append(
                        SettlementAllocation(
                            f"alloc-{ref}", ref, str(settled), business_date, amount
                        )
                    )
    except OpenItemsInvalid:
        return _result(kind, "INCONCLUSIVE", "SETTLEMENT_FACT_INVALID")
    # Anything raised below is an internal or configuration defect, not bad source data:
    # it propagates so the tool audits outcome=error instead of a silent INCONCLUSIVE.
    all_dates = [d.document_date for d in documents] + [p.payment_date for p in payments]
    period_start = min([as_of, *all_dates])
    period_end = as_of + timedelta(days=1)
    digest = profile_fingerprint.split(":", 1)[-1]
    if not _HEX64.fullmatch(digest) or not _HEX64.fullmatch(metadata_fingerprint or ""):
        raise ValueError("OPEN_ITEMS_FINGERPRINT_INVALID")
    scope = EvidenceScope(
        source_id, company_id, metadata_fingerprint, digest, period_start, period_end,
        mapping["currency"], "UTC",
    )
    level = "L1" if synthetic else mapping.get("evidence_level", "")
    profile = AgingProfile(
        scope, metadata_fingerprint, "open-items-v1", kind, as_of, period_start,
        period_end, "source-confirmed-due", "source-explicit-allocation", "native-not-run",
    )
    observation = SettlementObservation(
        scope, profile.fingerprint(), metadata_fingerprint, digest, level, True,
        True, tuple(documents), tuple(payments), tuple(allocations),
    )
    outcome = evaluate_aging(
        profile, observation, validated_profiles=frozenset({profile.fingerprint()})
    )
    summary: list[dict[str, str]] = []
    if outcome["status"] in {"PASS", "FINDING"}:
        summary = _summary(documents, payments, allocations)
    result = _result(
        kind, outcome["status"], outcome["reason"], rows=outcome["rows"],
        anomalies=outcome["anomalies"], summary=summary, evidence_level=outcome["evidence_level"],
    )
    return result


def _summary(documents, payments, allocations) -> list[dict[str, str]]:
    with localcontext() as context:
        context.prec = 120
        paid = {d.document_ref: Decimal(0) for d in documents}
        used = {p.payment_ref: Decimal(0) for p in payments}
        for allocation in allocations:
            paid[allocation.document_ref] += allocation.amount
            used[allocation.payment_ref] += allocation.amount
        totals: dict[str, dict[str, Decimal]] = {}

        def bucket(party: str) -> dict[str, Decimal]:
            return totals.setdefault(
                party,
                {"charged": Decimal(0), "applied": Decimal(0), "open": Decimal(0),
                 "credit": Decimal(0)},
            )

        for document in documents:
            entry = bucket(document.counterparty_ref)
            entry["charged"] += document.amount
            entry["applied"] += paid[document.document_ref]
            remaining = document.amount - paid[document.document_ref]
            if remaining > 0:
                entry["open"] += remaining
            else:
                entry["credit"] += -remaining
        for payment in payments:
            bucket(payment.counterparty_ref)["credit"] += payment.amount - used[payment.payment_ref]
    return [
        {
            "counterparty_id": party,
            "charged_total": str(v["charged"]),
            "payments_applied": str(v["applied"]),
            "open_balance": str(v["open"]),
            "unapplied_credit": str(v["credit"]),
        }
        for party, v in sorted(totals.items())
    ]


def parse_as_of(as_of: str) -> date:
    try:
        point = datetime.fromisoformat(as_of)
    except (TypeError, ValueError) as exc:
        raise ValueError("as_of must be an ISO-8601 timestamp") from exc
    if point.tzinfo is None:
        raise ValueError("as_of must include an explicit timezone")
    return point.date()
