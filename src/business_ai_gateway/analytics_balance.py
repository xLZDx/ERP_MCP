"""Balance by analytics (ADR-0008): mapping, canonical rows, route selection, COM binding.

Route selection is decided before execution, only from persisted capability evidence. There is NO
runtime fallback: an error from the selected OData route is never retried over COM.

Configuration fingerprint (documented choice): ``sha256(platform_version + ":" + adapter_profile)``
derived from ``OneCCapabilities``; a missing platform version is "not derivable" and fails closed.
Company references compare exactly, except GUIDs which compare in normalised form.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

from .compatibility import CapabilityUnsupported
from .evidence_store import _read_bounded, _safe_location
from .semantic import (
    _ENTITY_SET_PATTERN,
    _PROPERTY_PATTERN,
    SemanticMappingUnconfirmed,
    build_company_filter,
)

ANALYTICS_BALANCE_CONCEPT = "account.balance_by_analytics"
ANALYTICS_BALANCE_METHOD = "balance"
MAX_ACCOUNTS = 16
MAX_SLOTS = 3
ANALYTICS_ROLES = frozenset(
    {"counterparty", "contract", "item", "warehouse", "cash_desk", "employee", "bank_account", "other"}
)
ABSENT_EVIDENCE_KIND = "metadata-function-import-absent-or-not-read-only"
MAX_BINDINGS_FILE_BYTES = 128_000
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
AS_OF_MIN_YEAR = 1990
AS_OF_MAX_YEAR = 2100
# The bridge runs one code-owned template on this register and company dimension only (ADR-0008 section 7).
COM_FIXED_ENTITY_SET = "AccountingRegister_Хозрасчетный"
COM_FIXED_COMPANY_FIELD = "Организация_Key"

_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_CODE = re.compile(r"[0-9A-Za-z._\-\u0080-￿]{1,32}\Z")
_TYPE = re.compile(r"[A-Za-z]+\.[\w\u0080-￿]+\Z", re.UNICODE)
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}\Z")
_MAPPING_KEYS = {
    "entity_set", "method", "company_scope", "accounts", "account_field", "analytics",
    "amount_fields", "currency_field", "required_register_capabilities",
}


class AnalyticsBalanceError(RuntimeError):
    """Fail-closed error with a stable machine code."""

    code = "SOURCE_RESPONSE_INVALID"

    def __init__(self, code: str | None = None):
        code = code or self.code
        super().__init__(code)
        self.code = code


class AnalyticsBalanceDenied(AnalyticsBalanceError):
    """Route/binding refusal decided before any data call."""

    code = "ANALYTICS_ROUTE_DENIED"


class RouteUnknown(AnalyticsBalanceDenied):
    code = "ROUTE_CAPABILITY_UNKNOWN"


class ComBindingInvalid(AnalyticsBalanceDenied):
    code = "COM_BINDING_INVALID"


class ComRouteUnsupported(CapabilityUnsupported):
    """CAPABILITY_UNSUPPORTED for a proven-absent OData method without a usable binding."""

    def __init__(self, reason: str):
        super().__init__("CAPABILITY_UNSUPPORTED")
        self.reason = reason


# ---------------------------------------------------------------- mapping

def _bad(message: str):
    raise SemanticMappingUnconfirmed(f"analytics balance mapping: {message}")


def _prop(value: Any) -> bool:
    return isinstance(value, str) and bool(_PROPERTY_PATTERN.fullmatch(value))


def validate_analytics_balance_mapping(mapping: Any) -> tuple[str, str]:
    if not isinstance(mapping, dict) or set(mapping) - _MAPPING_KEYS:
        _bad("must be an object with known keys only")
    register_set = mapping.get("entity_set")
    if not isinstance(register_set, str) or not _ENTITY_SET_PATTERN.fullmatch(register_set):
        _bad("entity_set must be an AccountingRegister_* name")
    if mapping.get("method") != ANALYTICS_BALANCE_METHOD:
        _bad("method must be balance")
    scope = mapping.get("company_scope")
    if (
        not isinstance(scope, dict) or set(scope) != {"field", "value_type"}
        or not _prop(scope.get("field")) or scope.get("value_type") not in {"guid", "string"}
    ):
        _bad("company_scope is invalid")
    accounts = mapping.get("accounts")
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= MAX_ACCOUNTS:
        _bad("accounts must contain 1..16 entries")
    keys, codes = set(), set()
    for item in accounts:
        if (
            not isinstance(item, dict) or set(item) != {"code", "account_key"}
            or not isinstance(item["code"], str) or not _CODE.fullmatch(item["code"])
            or not isinstance(item["account_key"], str) or not _GUID.fullmatch(item["account_key"])
        ):
            _bad("account entry is invalid")
        keys.add(item["account_key"].lower())
        codes.add(item["code"])
    if len(keys) != len(accounts) or len(codes) != len(accounts):
        _bad("account keys and codes must be unique")
    fields = [mapping.get("account_field")]
    if not _prop(fields[0]):
        _bad("account_field is invalid")
    slots = mapping.get("analytics")
    if not isinstance(slots, list) or not 1 <= len(slots) <= MAX_SLOTS:
        _bad("analytics must contain 1..3 slots")
    seen_slots = set()
    for slot in slots:
        if (
            not isinstance(slot, dict)
            or not {"slot", "role", "ref_field", "type_field"} <= set(slot)
            or set(slot) - {"slot", "role", "ref_field", "type_field", "expected_type"}
            or type(slot["slot"]) is not int or not 1 <= slot["slot"] <= MAX_SLOTS
            or slot["slot"] in seen_slots
            or slot["role"] not in ANALYTICS_ROLES
            or not _prop(slot["ref_field"]) or not _prop(slot["type_field"])
            or ("expected_type" in slot
                and (not isinstance(slot["expected_type"], str)
                     or not _TYPE.fullmatch(slot["expected_type"])))
        ):
            _bad("analytics slot is invalid")
        seen_slots.add(slot["slot"])
        fields += [slot["ref_field"], slot["type_field"]]
    amounts = mapping.get("amount_fields")
    if not isinstance(amounts, dict) or set(amounts) != {"debit", "credit"}:
        _bad("amount_fields must be exactly debit/credit")
    if not _prop(amounts["debit"]) or not _prop(amounts["credit"]):
        _bad("amount field is invalid")
    fields += [amounts["debit"], amounts["credit"], scope["field"]]
    currency = mapping.get("currency_field", "__missing__")
    if currency is not None:
        if not _prop(currency):
            _bad("currency_field must be a property or null")
        fields.append(currency)
    if len(set(fields)) != len(fields):
        _bad("projected fields must be distinct")
    if mapping.get("required_register_capabilities") != [
        {"entity_set": register_set, "method": ANALYTICS_BALANCE_METHOD}
    ]:
        _bad("capability dependency is missing or mismatched")
    return register_set, ANALYTICS_BALANCE_METHOD


def build_analytics_balance_arguments(
    mapping: dict[str, Any], *, company_external_ref: str, as_of: str
) -> tuple[str, str, dict[str, str]]:
    register_set, method = validate_analytics_balance_mapping(mapping)
    try:
        point = datetime.fromisoformat(as_of)
    except (TypeError, ValueError) as exc:
        raise ValueError("as_of must be an ISO-8601 timestamp") from exc
    if point.tzinfo is None or point.utcoffset() is None:
        raise ValueError("as_of must include an explicit timezone")
    if not AS_OF_MIN_YEAR <= point.year <= AS_OF_MAX_YEAR:
        raise ValueError("as_of is outside the supported range")
    field = mapping["account_field"]
    condition = " or ".join(
        f"{field} eq guid'{UUID(item['account_key'])!s}'" for item in mapping["accounts"]
    )
    return (
        register_set,
        method,
        {
            "Period": point.isoformat(),
            "Condition": build_company_filter(mapping, company_external_ref),
            "AccountCondition": condition,
        },
    )


# ---------------------------------------------------------------- canonical rows

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_AMOUNT_CONTEXT_DIGITS = 60


def _decimal(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    text = str(value)
    if not _NUMBER.fullmatch(text):  # rejects "1_000", "NaN", "Infinity", whitespace and hex forms
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID") from None
    if not number.is_finite() or number.adjusted() >= _AMOUNT_CONTEXT_DIGITS:
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    if number == 0:
        return "0"
    text = format(number, "f")  # exact, no context rounding
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _guid_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _GUID.fullmatch(value):
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    value = value.lower()
    return None if value == ZERO_GUID else value


def normalize_type(value: Any) -> str:
    """``StandardODATA.Catalog_X`` / ``Catalog_X`` / ``Catalog.X`` -> ``Catalog.X``."""
    if not isinstance(value, str):
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    text = value.removeprefix("StandardODATA.")
    if "." not in text and "_" in text:
        text = text.replace("_", ".", 1)
    if not _TYPE.fullmatch(text):
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    return text


def _slot_entry(slot: dict, ref: Any, type_: Any) -> dict[str, Any]:
    ref = _guid_or_none(ref)
    if ref is None:
        return {"slot": slot["slot"], "role": slot["role"], "ref": None, "type": None}
    kind = normalize_type(type_)
    expected = slot.get("expected_type")
    if expected is not None and kind != expected:
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    return {"slot": slot["slot"], "role": slot["role"], "ref": ref, "type": kind}


def _account_lookup(mapping: dict) -> dict[str, str]:
    return {item["account_key"].lower(): item["code"] for item in mapping["accounts"]}


def _same_company(left: Any, right: str, value_type: str) -> bool:
    if value_type == "guid":
        try:
            return UUID(str(left)) == UUID(right)
        except ValueError:
            return False
    return left == right


def normalize_odata_balance_rows(
    rows: Any, mapping: dict[str, Any], *, company_external_ref: str
) -> list[dict[str, Any]]:
    validate_analytics_balance_mapping(mapping)
    if not isinstance(rows, list):
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    accounts = _account_lookup(mapping)
    slots = sorted(mapping["analytics"], key=lambda item: item["slot"])
    scope = mapping["company_scope"]
    currency_field = mapping.get("currency_field")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
        needed = [mapping["account_field"], scope["field"], *mapping["amount_fields"].values()]
        for slot in slots:
            needed += [slot["ref_field"], slot["type_field"]]
        if currency_field:
            needed.append(currency_field)
        if any(name not in row for name in needed):
            raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
        if not _same_company(row[scope["field"]], company_external_ref, scope["value_type"]):
            raise AnalyticsBalanceError("COMPANY_SCOPE_MISMATCH")
        key = _guid_or_none(row[mapping["account_field"]])
        if key is None or key not in accounts:
            raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
        out.append(
            {
                "account": accounts[key],
                "account_key": key,
                "analytics": [
                    _slot_entry(slot, row[slot["ref_field"]], row[slot["type_field"]])
                    for slot in slots
                ],
                "balance_debit": _decimal(row[mapping["amount_fields"]["debit"]]),
                "balance_credit": _decimal(row[mapping["amount_fields"]["credit"]]),
                "currency_ref": _guid_or_none(row[currency_field]) if currency_field else None,
            }
        )
    return out


def normalize_com_balance_rows(
    response_rows: Any, mapping: dict[str, Any], *, company_external_ref: str
) -> list[dict[str, Any]]:
    validate_analytics_balance_mapping(mapping)
    if not isinstance(response_rows, (list, tuple)):
        raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
    accounts = _account_lookup(mapping)
    slots = sorted(mapping["analytics"], key=lambda item: item["slot"])
    out = []
    for row in response_rows:
        if (
            not isinstance(row, dict)
            or not {"account_key", "company_ref", "analytics", "debit", "credit", "currency_ref"} <= set(row)
            or not isinstance(row["analytics"], list) or len(row["analytics"]) != MAX_SLOTS
            or any(not isinstance(item, dict) or not {"ref", "type"} <= set(item)
                   for item in row["analytics"])
        ):
            raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
        if not _same_company(row["company_ref"], company_external_ref, "guid"):
            raise AnalyticsBalanceError("COMPANY_SCOPE_MISMATCH")
        key = _guid_or_none(row["account_key"])
        if key is None or key not in accounts:
            raise AnalyticsBalanceError("SOURCE_RESPONSE_INVALID")
        out.append(
            {
                "account": accounts[key],
                "account_key": key,
                "analytics": [
                    _slot_entry(
                        slot,
                        row["analytics"][slot["slot"] - 1]["ref"],
                        row["analytics"][slot["slot"] - 1]["type"],
                    )
                    for slot in slots
                ],
                "balance_debit": _decimal(row["debit"]),
                "balance_credit": _decimal(row["credit"]),
                "currency_ref": (
                    _guid_or_none(row["currency_ref"]) if mapping.get("currency_field") else None
                ),
            }
        )
    return out


# ---------------------------------------------------------------- binding

@dataclass(frozen=True, slots=True)
class ComBinding:
    source_id: str
    binding_id: str
    version: int
    clone_identity: str
    configuration_fingerprint: str
    metadata_fingerprint: str
    source_base_url_sha256: str
    credential_identity: str
    allowed_company_refs: tuple[str, ...]
    status: str
    approved_at: datetime


_BINDING_FIELDS = set(ComBinding.__dataclass_fields__)
_STATUSES = {"APPROVED", "REVOKED"}


def configuration_fingerprint(capabilities: Any) -> str:
    version = getattr(capabilities, "platform_version", None)
    profile = getattr(capabilities, "adapter_profile", None)
    if not isinstance(version, str) or not version or profile is None:
        raise ComBindingInvalid("COM_BINDING_CONFIGURATION_UNKNOWN")
    value = getattr(profile, "value", profile)
    return hashlib.sha256(f"{version}:{value}".encode()).hexdigest()


def _same_ref(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return UUID(left) == UUID(right)
    except (ValueError, AttributeError, TypeError):
        return False


def validate_binding(
    binding: ComBinding, *, source: Any, capabilities: Any, company_external_ref: str
) -> None:
    if not isinstance(binding, ComBinding) or binding.source_id != source.id:
        raise ComBindingInvalid("COM_BINDING_SOURCE_MISMATCH")
    if binding.status != "APPROVED":
        raise ComBindingInvalid("COM_BINDING_NOT_APPROVED")
    if binding.source_base_url_sha256 != hashlib.sha256(source.base_url.encode()).hexdigest():
        raise ComBindingInvalid("COM_BINDING_BASE_URL_CHANGED")
    credential = getattr(source, "username_secret_ref", None)
    if not credential or binding.credential_identity != credential:
        raise ComBindingInvalid("COM_BINDING_CREDENTIAL_CHANGED")
    current = getattr(capabilities, "metadata_fingerprint", None)
    if not current or binding.metadata_fingerprint != current:
        raise ComBindingInvalid("COM_BINDING_METADATA_CHANGED")
    if binding.configuration_fingerprint != configuration_fingerprint(capabilities):
        raise ComBindingInvalid("COM_BINDING_CONFIGURATION_CHANGED")
    if not any(_same_ref(ref, company_external_ref) for ref in binding.allowed_company_refs):
        raise ComBindingInvalid("COM_COMPANY_NOT_ALLOWED")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ComBindingInvalid("COM_BINDINGS_INVALID")
        result[key] = value
    return result


def _binding(record: Any) -> ComBinding:
    bad = ComBindingInvalid("COM_BINDINGS_INVALID")
    if type(record) is not dict or set(record) != _BINDING_FIELDS:
        raise bad
    text = ("source_id", "binding_id", "clone_identity", "credential_identity")
    if (
        any(type(record[k]) is not str or not record[k] or len(record[k]) > 256 for k in text)
        or not _ID.fullmatch(record["binding_id"])
        or type(record["version"]) is not int or record["version"] < 1
        or any(type(record[k]) is not str or not _SHA.fullmatch(record[k]) for k in (
            "configuration_fingerprint", "metadata_fingerprint", "source_base_url_sha256"))
        or record["status"] not in _STATUSES
        or type(record["allowed_company_refs"]) is not list
        or not 1 <= len(record["allowed_company_refs"]) <= 64
        or any(type(r) is not str or not r or len(r) > 256 for r in record["allowed_company_refs"])
        or len(set(record["allowed_company_refs"])) != len(record["allowed_company_refs"])
        or type(record["approved_at"]) is not str
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["approved_at"])
    ):
        raise bad
    try:
        approved = datetime.fromisoformat(record["approved_at"]).astimezone(UTC)
    except ValueError:
        raise bad from None
    values = dict(record)
    values["allowed_company_refs"] = tuple(record["allowed_company_refs"])
    values["approved_at"] = approved
    return ComBinding(**values)


def load_com_bindings(path: Path, expected_sha256: str) -> tuple[ComBinding, ...]:
    if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
        raise ComBindingInvalid("COM_BINDINGS_INVALID")
    try:
        _safe_location(path)
        data = _read_bounded(path, MAX_BINDINGS_FILE_BYTES)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ComBindingInvalid("COM_BINDINGS_STALE")
        decoded = json.loads(data, object_pairs_hook=_unique)
        if (
            type(decoded) is not dict or set(decoded) != {"schema_version", "bindings"}
            or type(decoded["schema_version"]) is not int or decoded["schema_version"] != 1
            or type(decoded["bindings"]) is not list or not 1 <= len(decoded["bindings"]) <= 256
        ):
            raise ComBindingInvalid("COM_BINDINGS_INVALID")
        bindings = tuple(_binding(item) for item in decoded["bindings"])
    except ComBindingInvalid:
        raise
    except Exception:  # noqa: BLE001 - never leak file/parse details
        raise ComBindingInvalid("COM_BINDINGS_INVALID") from None
    if (
        len({b.source_id for b in bindings}) != len(bindings)
        or len({b.binding_id for b in bindings}) != len(bindings)
    ):
        raise ComBindingInvalid("COM_BINDINGS_INVALID")
    return bindings


def find_binding(bindings: tuple[ComBinding, ...], source_id: str) -> ComBinding | None:
    found = [b for b in bindings if b.source_id == source_id]
    if len(found) > 1:
        raise ComBindingInvalid("COM_BINDING_AMBIGUOUS")
    return found[0] if found else None


# ---------------------------------------------------------------- route selection

@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: str
    reason: str
    binding: ComBinding | None = None


def classify_odata_capability(
    register_capabilities: Any, *, source_id: str, metadata_fingerprint: str | None, entity_set: str
) -> str:
    profile = register_capabilities
    if (
        not isinstance(profile, dict) or not metadata_fingerprint
        or profile.get("evidence_source") != "live-metadata"
        or profile.get("source_id") != source_id
        or profile.get("metadata_fingerprint") != metadata_fingerprint
        or profile.get("status") is not None
    ):
        return "UNKNOWN"
    registers = profile.get("registers")
    if isinstance(registers, dict):
        entry = registers.get(entity_set)
    elif isinstance(registers, list):
        entry = next(
            (r for r in registers if isinstance(r, dict) and r.get("entity_set") == entity_set), None
        )
    else:
        entry = None
    methods = entry.get("methods") if isinstance(entry, dict) else None
    method = methods.get(ANALYTICS_BALANCE_METHOD) if isinstance(methods, dict) else None
    evidence = method.get("evidence") if isinstance(method, dict) else None
    if not isinstance(evidence, dict) or evidence.get("metadata_fingerprint") != metadata_fingerprint:
        return "UNKNOWN"
    if method.get("available") is True:
        return "AVAILABLE"
    if method.get("available") is False and evidence.get("kind") == ABSENT_EVIDENCE_KIND:
        return "UNSUPPORTED"
    return "UNKNOWN"


def select_route(
    capabilities: Any,
    mapping: dict[str, Any],
    bindings: tuple[ComBinding, ...] | Callable[[], tuple[ComBinding, ...]],
    *,
    source: Any,
    company_external_ref: str,
) -> RouteDecision:
    register_set, _ = validate_analytics_balance_mapping(mapping)
    state = classify_odata_capability(
        getattr(capabilities, "register_capabilities", None),
        source_id=source.id,
        metadata_fingerprint=getattr(capabilities, "metadata_fingerprint", None),
        entity_set=register_set,
    )
    if state == "AVAILABLE":
        return RouteDecision("odata", "capability_available")  # bindings are never consulted
    if state == "UNKNOWN":
        raise RouteUnknown()
    try:
        resolved = bindings() if callable(bindings) else bindings
        binding = find_binding(tuple(resolved or ()), source.id)
        if binding is None:
            raise ComRouteUnsupported("no_binding")
        validate_binding(
            binding, source=source, capabilities=capabilities,
            company_external_ref=company_external_ref,
        )
    except ComBindingInvalid as exc:
        if exc.code == "COM_COMPANY_NOT_ALLOWED":
            raise
        raise ComRouteUnsupported(exc.code.lower()) from None
    if (
        register_set != COM_FIXED_ENTITY_SET
        or mapping["company_scope"]["field"] != COM_FIXED_COMPANY_FIELD
    ):
        raise ComRouteUnsupported("com_mapping_not_served_by_bridge")
    return RouteDecision("com", "capability_unsupported_binding_approved", binding)
