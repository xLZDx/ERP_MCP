"""Duplicate-counterparty candidate collector (read-only, pure, SC08).

Implements docs/SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md sections 2-8 and 11 without any I/O.
The server issues the (at most two) reads, calls evaluate_duplicate_candidates and merges the
profile provenance block last; this module never carries an evidence-level key and never logs
or returns anything beyond the documented result schema.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any
from uuid import UUID

from .semantic import SemanticMappingUnconfirmed, build_company_filter

DUPLICATE_CONCEPT = "counterparty.duplicate_candidates"
MATCH_RULE = "normalized_name_v1"
MAX_ROWS = 2000
# Reasons that mean the source answer cannot be trusted; the tool audits them as outcome=error.
DUPLICATE_FAILURE_REASONS = frozenset({
    "COUNTERPARTY_ROWS_TRUNCATED", "SOURCE_RESPONSE_INVALID", "COUNTERPARTY_FACT_INVALID",
    "COMPANY_SCOPE_MISMATCH",
})
OUTPUT_FIELDS = ("counterparty_ref", "code", "name")
_CATALOG = re.compile(r"^Catalog_[\w\u0080-￿]+$")
_RECORD_REGISTER = re.compile(r"^(?:Accumulation|Information)Register_[\w\u0080-￿]+$")
_PROPERTY = re.compile(r"^[\w\u0080-￿]+$")
_NON_WORD_RUN = re.compile(r"[\W_]+")
_ZERO_GUID = "00000000-0000-0000-0000-000000000000"


def normalize_name(value: str) -> str:
    """normalized_name_v1 (contract section 3); an empty result means 'excluded from matching'."""
    text = unicodedata.normalize("NFKC", value).casefold()
    return _NON_WORD_RUN.sub(" ", text).strip()


def group_id(match_key: str) -> str:
    """Stable group identifier (contract section 5)."""
    digest = hashlib.sha256(MATCH_RULE.encode() + b"\0" + match_key.encode("utf-8"))
    return "dup-" + digest.hexdigest()[:16]


def rows_truncated(rows: list[Any], row_limit: int, page_truncated: bool) -> bool:
    """A read is truncated at len(rows) >= row_limit (exactly at the limit) or a page flag."""
    return bool(page_truncated) or len(rows) >= row_limit


def is_conclusive(result: dict[str, Any]) -> bool:
    """False when the result is an INCONCLUSIVE outcome the tool must audit as error."""
    return not (
        result.get("status") == "INCONCLUSIVE" and result.get("reason") in DUPLICATE_FAILURE_REASONS
    )


class DuplicateResponseTooLarge(Exception):
    """The (NFKC-expanded) result exceeds the gateway response budget; carries no data."""

    code = "RESPONSE_TOO_LARGE"

    def __init__(self) -> None:
        super().__init__("duplicate-counterparty result exceeds the response size limit")


def _canonical_guid(value: str) -> str | None:
    """Canonical lower-case GUID text, or None when the value is not a GUID."""
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _utf8_safe(*values: str) -> bool:
    """False for text with lone surrogates, which cannot be serialised into the response."""
    try:
        for value in values:
            value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _unconfirmed() -> SemanticMappingUnconfirmed:
    return SemanticMappingUnconfirmed("duplicate-counterparty mapping is incomplete or unsupported")


def validate_duplicate_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate a reviewed duplicate-counterparty mapping (contract section 11); returns a copy."""
    allowed = {
        "entity_set", "output_fields", "company_activity", "match_rule",
        "required_register_capabilities",
    }
    if not isinstance(mapping, dict) or set(mapping) - allowed:
        raise _unconfirmed()
    entity_set = mapping.get("entity_set")
    fields = mapping.get("output_fields")
    activity = mapping.get("company_activity")
    if (
        not isinstance(entity_set, str)
        or not _CATALOG.fullmatch(entity_set)
        or not isinstance(fields, dict)
        or set(fields) != set(OUTPUT_FIELDS)
        or any(not isinstance(v, str) or not _PROPERTY.fullmatch(v) for v in fields.values())
        or len(set(fields.values())) != len(OUTPUT_FIELDS)
        or not isinstance(activity, dict)
        or set(activity) != {"entity_set", "counterparty_field", "company_scope"}
        or not isinstance(activity.get("entity_set"), str)
        or not _RECORD_REGISTER.fullmatch(activity["entity_set"])
        or not isinstance(activity.get("counterparty_field"), str)
        or not _PROPERTY.fullmatch(activity["counterparty_field"])
    ):
        raise _unconfirmed()
    scope = activity["company_scope"]
    if (
        not isinstance(scope, dict)
        or set(scope) != {"field", "value_type"}
        or not isinstance(scope.get("field"), str)
        or not _PROPERTY.fullmatch(scope["field"])
        or scope.get("value_type") != "guid"
        or scope["field"] == activity["counterparty_field"]
        or mapping.get("match_rule") != MATCH_RULE
        or mapping.get("required_register_capabilities") != []
    ):
        raise _unconfirmed()
    return {
        "entity_set": entity_set,
        "output_fields": dict(fields),
        "company_activity": {
            "entity_set": activity["entity_set"],
            "counterparty_field": activity["counterparty_field"],
            "company_scope": {"field": scope["field"], "value_type": "guid"},
        },
        "match_rule": MATCH_RULE,
        "required_register_capabilities": [],
    }


def build_activity_query(mapping: dict[str, Any], company_id: str, row_limit: int) -> dict[str, Any]:
    """Company-filtered activity read (contract section 6, step 1)."""
    valid = validate_duplicate_mapping(mapping)
    activity = valid["company_activity"]
    party = activity["counterparty_field"]
    return {
        "entity_set": activity["entity_set"],
        "select": [party, activity["company_scope"]["field"]],
        "filter_expr": build_company_filter(activity, company_id),
        "orderby": f"{party} asc",
        "top": row_limit,
    }


def build_catalog_query(mapping: dict[str, Any], row_limit: int) -> dict[str, Any]:
    """Unfiltered catalog read (the catalog has no company dimension; contract section 6, step 3)."""
    valid = validate_duplicate_mapping(mapping)
    fields = valid["output_fields"]
    return {
        "entity_set": valid["entity_set"],
        "select": [fields["counterparty_ref"], fields["code"], fields["name"]],
        "filter_expr": None,
        "orderby": f"{fields['counterparty_ref']} asc",
        "top": row_limit,
    }


def _result(status: str, reason: str, *, groups=None, truncated: bool = False) -> dict[str, Any]:
    groups = groups or []
    return {
        "concept": DUPLICATE_CONCEPT,
        "match_rule": MATCH_RULE,
        "status": status,
        "reason": reason,
        "candidate_count": sum(len(g["members"]) for g in groups),
        "group_count": len(groups),
        "merge_count": 0,
        "groups": groups,
        "truncated": truncated,
        "native_approval_inferred": False,
        "human_review_required": True,
    }


def _inconclusive(reason: str) -> dict[str, Any]:
    return _result("INCONCLUSIVE", reason, truncated=reason == "COUNTERPARTY_ROWS_TRUNCATED")


def _activity_set(rows: list[Any], mapping: dict[str, Any], company_id: str) -> set[str] | str:
    """Lower-cased counterparty GUIDs with company activity, or a failure reason."""
    activity = mapping["company_activity"]
    party_field = activity["counterparty_field"]
    scope_field = activity["company_scope"]["field"]
    parties: set[str] = set()
    company = _canonical_guid(company_id)
    if company is None:
        raise _unconfirmed()
    for row in rows:
        if not isinstance(row, dict) or party_field not in row or scope_field not in row:
            return "COUNTERPARTY_FACT_INVALID"
        scope_value = row[scope_field]
        if not isinstance(scope_value, str) or _canonical_guid(scope_value) != company:
            return "COMPANY_SCOPE_MISMATCH"
        value = row[party_field]
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            return "COUNTERPARTY_FACT_INVALID"
        try:
            ref = str(UUID(value))
        except ValueError:
            return "COUNTERPARTY_FACT_INVALID"
        if ref != _ZERO_GUID:
            parties.add(ref)
    return parties


def evaluate_duplicate_candidates(
    mapping: dict[str, Any],
    *,
    company_id: str,
    row_limit: int,
    activity_rows: Any,
    activity_truncated: bool,
    catalog_rows: Any,
    catalog_truncated: bool,
) -> dict[str, Any]:
    """Pure evaluation (contract sections 4-8); never raises on bad business data.

    catalog_rows is None when the catalog read was not issued (truncated activity read). The
    result excludes the profile provenance block, which the server merges last.
    """
    valid = validate_duplicate_mapping(mapping)
    if not isinstance(activity_rows, list):
        return _inconclusive("SOURCE_RESPONSE_INVALID")
    if rows_truncated(activity_rows, row_limit, activity_truncated):
        return _inconclusive("COUNTERPARTY_ROWS_TRUNCATED")
    activity = _activity_set(activity_rows, valid, company_id)
    if isinstance(activity, str):
        return _inconclusive(activity)
    if not isinstance(catalog_rows, list):
        return _inconclusive("SOURCE_RESPONSE_INVALID")
    if rows_truncated(catalog_rows, row_limit, catalog_truncated):
        return _inconclusive("COUNTERPARTY_ROWS_TRUNCATED")
    fields = valid["output_fields"]
    ref_f, code_f, name_f = (fields[k] for k in OUTPUT_FIELDS)
    seen: set[str] = set()
    by_key: dict[str, list[dict[str, str]]] = {}
    for row in catalog_rows:
        if not isinstance(row, dict) or any(f not in row for f in (ref_f, code_f, name_f)):
            return _inconclusive("COUNTERPARTY_FACT_INVALID")
        ref, code, name = row[ref_f], row[code_f], row[name_f]
        if not all(isinstance(v, str) for v in (ref, code, name)) or not _utf8_safe(ref, code, name):
            return _inconclusive("COUNTERPARTY_FACT_INVALID")
        canonical = _canonical_guid(ref)
        if canonical is None or canonical in seen:
            return _inconclusive("COUNTERPARTY_FACT_INVALID")
        seen.add(canonical)
        if canonical not in activity:
            continue
        key = normalize_name(name)
        if key:
            by_key.setdefault(key, []).append(
                {"counterparty_id": ref, "code": code, "name": name}
            )
    groups = [
        {
            "group_id": group_id(key),
            "match_key": key,
            "match_basis": "NORMALIZED_NAME",
            "members": sorted(members, key=lambda m: str(UUID(m["counterparty_id"]))),
        }
        for key, members in sorted(by_key.items())
        if len(members) >= 2
    ]
    if groups:
        return _result("FINDING", "DUPLICATE_CANDIDATES_FOUND", groups=groups)
    return _result("PASS", "NO_DUPLICATE_CANDIDATES")
