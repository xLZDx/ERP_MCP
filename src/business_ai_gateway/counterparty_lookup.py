"""Read-only counterparty lookup and reference-name resolution over a validated catalog profile.

Mapping (``counterparty.lookup``), owned by the semantic profile, never by the caller::

    {"entity_set": "Catalog_<Name>",
     "output_fields": {"ref": "Ref_Key", "code": "Code", "name": "Description",
                       "deleted": "DeletionMark", "folder": "IsFolder"},
     "max_results": 20,
     "required_register_capabilities": []}

The caller supplies only a bounded search text. Everything that reaches the 1C filter is either a
profile property name (validated against a strict pattern) or a quote-escaped, length-bounded literal.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from .semantic import SemanticMappingUnconfirmed

COUNTERPARTY_LOOKUP_CONCEPT = "counterparty.lookup"
LOOKUP_FIELDS = ("ref", "code", "name", "deleted", "folder")
MIN_QUERY = 2
MAX_QUERY = 64
MAX_RESULTS_CEILING = 50
MAX_REFS_PER_REQUEST = 30  # keeps the OR-filter well inside URL limits

_CATALOG = re.compile(r"Catalog_[0-9A-Za-z_\u0080-￿]{1,120}\Z")
_PROPERTY = re.compile(r"[0-9A-Za-z_\u0080-￿]{1,120}\Z")
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")


def validate_counterparty_lookup_mapping(mapping: Any) -> str:
    def bad(message: str):
        raise SemanticMappingUnconfirmed(f"counterparty lookup mapping: {message}")

    if not isinstance(mapping, dict) or set(mapping) - {
        "entity_set", "output_fields", "max_results", "required_register_capabilities"
    }:
        bad("must be an object with known keys only")
    entity_set = mapping.get("entity_set")
    if not isinstance(entity_set, str) or not _CATALOG.fullmatch(entity_set):
        bad("entity_set must be a Catalog_* name")
    fields = mapping.get("output_fields")
    if (
        not isinstance(fields, dict) or set(fields) != set(LOOKUP_FIELDS)
        or any(not isinstance(value, str) or not _PROPERTY.fullmatch(value) for value in fields.values())
        or len(set(fields.values())) != len(LOOKUP_FIELDS)
    ):
        bad("output_fields must map exactly ref/code/name/deleted/folder to distinct properties")
    limit = mapping.get("max_results")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS_CEILING:
        bad(f"max_results must be an integer 1..{MAX_RESULTS_CEILING}")
    if mapping.get("required_register_capabilities", []) != []:
        bad("a catalog lookup cannot claim register capabilities")
    return entity_set


def normalize_search_text(text: Any) -> str:
    """Validate and normalise the caller's text. Raises ValueError (a safe INVALID_ARGUMENT)."""
    if not isinstance(text, str):
        raise ValueError("query must be a string")  # noqa: TRY004 - callers map ValueError to INVALID_ARGUMENT
    cleaned = " ".join(text.split())
    if not MIN_QUERY <= len(cleaned) <= MAX_QUERY:
        raise ValueError(f"query must be {MIN_QUERY}..{MAX_QUERY} characters")
    if any(unicodedata.category(ch).startswith("C") for ch in cleaned):
        raise ValueError("query contains control characters")
    return cleaned


def _literal(value: str) -> str:
    return value.replace("'", "''")


def build_lookup_query(mapping: dict[str, Any], query: str) -> tuple[str, list[str], str, int]:
    """Return (entity_set, select, filter_expr, row_limit) for a bounded partial-name search."""
    entity_set = validate_counterparty_lookup_mapping(mapping)
    fields = mapping["output_fields"]
    text = normalize_search_text(query)
    select = [fields[name] for name in LOOKUP_FIELDS]
    # substringof is case-insensitive on the real 1C publication (verified live 2026-10-07);
    # tolower() is NOT supported there, so case folding is never pushed down.
    filter_expr = f"substringof('{_literal(text)}', {fields['name']})"
    return entity_set, select, filter_expr, mapping["max_results"] + 1  # +1 detects truncation


def build_refs_filter(mapping: dict[str, Any], refs: list[str]) -> str:
    validate_counterparty_lookup_mapping(mapping)
    clean = []
    for ref in refs:
        if not isinstance(ref, str) or not _GUID.fullmatch(ref):
            raise ValueError("reference must be a GUID")
        clean.append(str(uuid.UUID(ref)))
    if not 1 <= len(clean) <= MAX_REFS_PER_REQUEST:
        raise ValueError(f"1..{MAX_REFS_PER_REQUEST} references per request")
    ref_field = mapping["output_fields"]["ref"]
    return " or ".join(f"{ref_field} eq guid'{ref}'" for ref in clean)


def _fold(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _row(raw: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    fields = mapping["output_fields"]
    if any(fields[name] not in raw for name in LOOKUP_FIELDS):
        raise SemanticMappingUnconfirmed("catalog response is missing a field required by the profile")
    ref = raw[fields["ref"]]
    if not isinstance(ref, str) or not _GUID.fullmatch(ref):
        raise SemanticMappingUnconfirmed("catalog response carries a malformed reference")
    return {
        "ref": ref.lower(),
        "code": raw[fields["code"]],
        "name": raw[fields["name"]],
        "deleted": bool(raw[fields["deleted"]]),
        "folder": bool(raw[fields["folder"]]),
    }


def evaluate_lookup(raw_rows: Any, mapping: dict[str, Any], query: str) -> dict[str, Any]:
    """Classify catalog rows: EXACT / AMBIGUOUS / PARTIAL / NOT_FOUND. Groups are never returned as matches."""
    validate_counterparty_lookup_mapping(mapping)
    needle = _fold(normalize_search_text(query))
    if not isinstance(raw_rows, list):
        raise SemanticMappingUnconfirmed("catalog response is not a row list")
    limit = mapping["max_results"]
    rows = [_row(item, mapping) for item in raw_rows if isinstance(item, dict)]
    if len(rows) != len(raw_rows):
        raise SemanticMappingUnconfirmed("catalog response contains a non-object row")
    truncated = len(rows) > limit
    candidates = [row for row in rows[:limit] if not row["folder"]]
    # a search hit on 1C's side is substring-based; re-check locally so the status is deterministic
    candidates = [row for row in candidates if needle in _fold(row["name"]) or needle in _fold(row["code"])]
    exact = [row for row in candidates if _fold(row["name"]) == needle or _fold(row["code"]) == needle]
    live_exact = [row for row in exact if not row["deleted"]]
    if len(exact) == 1:
        status = "EXACT"
    elif len(live_exact) == 1:
        status = "EXACT"
        exact = live_exact
    elif len(exact) > 1:
        status = "AMBIGUOUS"
    elif len(candidates) == 1:
        status = "PARTIAL"
    elif candidates:
        status = "AMBIGUOUS"
    else:
        status = "NOT_FOUND"
    matches = exact if status == "EXACT" else candidates
    return {
        "status": status,
        "match_count": len(matches),
        "matches": matches,
        "truncated": truncated,
    }


def index_names(raw_rows: Any, mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """ref -> {code, name, deleted} for name resolution; unknown/extra rows are ignored."""
    validate_counterparty_lookup_mapping(mapping)
    if not isinstance(raw_rows, list):
        raise SemanticMappingUnconfirmed("catalog response is not a row list")
    out: dict[str, dict[str, Any]] = {}
    for item in raw_rows:
        if isinstance(item, dict):
            row = _row(item, mapping)
            out[row["ref"]] = {"code": row["code"], "name": row["name"], "deleted": row["deleted"]}
    return out
