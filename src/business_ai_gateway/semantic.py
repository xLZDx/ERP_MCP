from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .compatibility import CapabilityUnsupported

APROVODKA_REPOSITORY = "https://github.com/theYahia/WWmcp"
APROVODKA_SHA = "7b62c90e1fe74324605dc28d76f195200bb97252"
ACCOUNT_TURNOVERS_CONCEPT = "account.balance_and_turnovers"
ACCOUNT_TURNOVERS_METHOD = "balanceAndTurnovers"
INVENTORY_BALANCE_CONCEPT = "inventory.balance"
INVENTORY_BALANCE_METHOD = "Balance"
BANK_BALANCE_CONCEPT = "bank.balance"
RECEIVABLE_BALANCE_CONCEPT = "receivable.balance"
PAYABLE_BALANCE_CONCEPT = "payable.balance"
INVENTORY_MOVEMENTS_CONCEPT = "inventory.movements"
_ENTITY_SET_PATTERN = re.compile(r"^AccountingRegister_[\w\u0080-\uffff]+$", re.UNICODE)
_PROPERTY_PATTERN = re.compile(r"^[\w\u0080-\uffff]+$", re.UNICODE)
ACCOUNT_TURNOVERS_FIELDS = (
    "account",
    "opening_debit",
    "opening_credit",
    "debit_turnover",
    "credit_turnover",
    "closing_debit",
    "closing_credit",
)
DOCUMENT_CONCEPT_FIELDS = {
    "sales": (
        "document_ref",
        "document_number",
        "date",
        "counterparty",
        "amount",
        "currency",
        "posted",
    ),
    "purchases": (
        "document_ref",
        "document_number",
        "date",
        "counterparty",
        "amount",
        "currency",
        "posted",
    ),
}
INVENTORY_BALANCE_FIELDS = ("item_ref", "warehouse_ref", "quantity")
BANK_BALANCE_FIELDS = ("bank_account_ref", "currency_ref", "amount")
SETTLEMENT_BALANCE_FIELDS = ("counterparty_ref", "contract_ref", "amount")
INVENTORY_MOVEMENT_FIELDS = (
    "period",
    "item_ref",
    "warehouse_ref",
    "quantity",
    "record_type",
    "recorder_ref",
)


@dataclass(frozen=True, slots=True)
class PresetEntityCandidate:
    entity_set: str
    kind: str
    upstream_confidence: str
    status: str = "CANDIDATE_ONLY"


@dataclass(frozen=True, slots=True)
class ConfigurationPreset:
    """An upstream-derived discovery hint, never a source-validated mapping."""

    preset_id: str
    name: str
    aliases: tuple[str, ...]
    upstream_path: str
    upstream_repository: str = APROVODKA_REPOSITORY
    upstream_sha: str = APROVODKA_SHA
    status: str = "CANDIDATE_ONLY"
    candidates: tuple[PresetEntityCandidate, ...] = ()


CONFIGURATION_PRESETS = (
    ConfigurationPreset(
        "bp30",
        "1С:Бухгалтерия предприятия 3.0",
        ("бп", "бп3", "бухгалтерия", "accounting"),
        "servers/aprovodka/src/presets/bp30.ts",
        candidates=(
            PresetEntityCandidate("AccountingRegister_Хозрасчетный", "accounting_register", "verified"),
            PresetEntityCandidate("ChartOfAccounts_Хозрасчетный", "chart_of_accounts", "common"),
            PresetEntityCandidate("Catalog_Организации", "catalog", "verified"),
            PresetEntityCandidate("Catalog_Контрагенты", "catalog", "verified"),
            PresetEntityCandidate("Catalog_ДоговорыКонтрагентов", "catalog", "verified"),
            PresetEntityCandidate("Catalog_Номенклатура", "catalog", "verified"),
            PresetEntityCandidate("Catalog_Склады", "catalog", "common"),
            PresetEntityCandidate("Document_ПоступлениеТоваровУслуг", "document", "verified"),
            PresetEntityCandidate("Document_РеализацияТоваровУслуг", "document", "verified"),
            PresetEntityCandidate("InformationRegister_КурсыВалют", "information_register", "common"),
        ),
    ),
    ConfigurationPreset(
        "ut11",
        "1С:Управление торговлей 11",
        ("ут", "торговля", "trade"),
        "servers/aprovodka/src/presets/ut11.ts",
        candidates=(
            PresetEntityCandidate("AccumulationRegister_ТоварыНаСкладах", "accumulation_register", "verified"),
            PresetEntityCandidate("InformationRegister_РаспределениеЗапасов", "information_register", "verified"),
            PresetEntityCandidate("AccumulationRegister_ТоварыОрганизаций", "accumulation_register", "common"),
            PresetEntityCandidate("AccumulationRegister_РасчетыСКлиентами", "accumulation_register", "common"),
            PresetEntityCandidate("AccumulationRegister_РасчетыСПоставщиками", "accumulation_register", "common"),
            PresetEntityCandidate("AccumulationRegister_ДенежныеСредстваБезналичные", "accumulation_register", "common"),
            PresetEntityCandidate("Catalog_Партнеры", "catalog", "common"),
            PresetEntityCandidate("Catalog_Контрагенты", "catalog", "verified"),
            PresetEntityCandidate("Catalog_Номенклатура", "catalog", "verified"),
            PresetEntityCandidate("Catalog_Организации", "catalog", "verified"),
            PresetEntityCandidate("Document_РеализацияТоваровУслуг", "document", "verified"),
            PresetEntityCandidate("InformationRegister_ЦеныНоменклатуры", "information_register", "common"),
        ),
    ),
    ConfigurationPreset(
        "zup31",
        "1С:Зарплата и управление персоналом 3.1",
        ("зуп", "зарплата", "payroll"),
        "servers/aprovodka/src/presets/zup31.ts",
        candidates=(
            PresetEntityCandidate("Catalog_ФизическиеЛица", "catalog", "common"),
            PresetEntityCandidate("Catalog_Сотрудники", "catalog", "common"),
            PresetEntityCandidate("Catalog_Организации", "catalog", "common"),
            PresetEntityCandidate("Document_ПриемНаРаботу", "document", "common"),
            PresetEntityCandidate("Document_КадровыйПеревод", "document", "common"),
            PresetEntityCandidate("Document_НачислениеЗарплатыИВзносов", "document", "common"),
            PresetEntityCandidate("CalculationRegister_Начисления", "calculation_register", "common"),
            PresetEntityCandidate("CalculationRegister_Удержания", "calculation_register", "common"),
            PresetEntityCandidate("InformationRegister_КадроваяИсторияСотрудников", "information_register", "common"),
        ),
    ),
    ConfigurationPreset(
        "erp2",
        "1С:ERP Управление предприятием 2",
        ("erp", "ерп", "1c:erp"),
        "servers/aprovodka/src/presets/erp2.ts",
        candidates=(
            PresetEntityCandidate("AccumulationRegister_ТоварыНаСкладах", "accumulation_register", "verified"),
            PresetEntityCandidate("InformationRegister_РаспределениеЗапасов", "information_register", "verified"),
            PresetEntityCandidate("AccountingRegister_Хозрасчетный", "accounting_register", "common"),
            PresetEntityCandidate("ChartOfAccounts_Хозрасчетный", "chart_of_accounts", "common"),
            PresetEntityCandidate("Document_ЗаказНаПроизводство2_2", "document", "common"),
            PresetEntityCandidate("Document_ЭтапПроизводства2_2", "document", "common"),
            PresetEntityCandidate("Catalog_РесурсныеСпецификации", "catalog", "common"),
            PresetEntityCandidate("AccumulationRegister_ЗатратыНаВыпуск", "accumulation_register", "common"),
            PresetEntityCandidate("AccumulationRegister_ДенежныеСредстваБезналичные", "accumulation_register", "common"),
        ),
    ),
)

PRESETS_BY_ID = {preset.preset_id: preset for preset in CONFIGURATION_PRESETS}


def canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_native_reconciliation_evidence(evidence: Any) -> list[dict[str, str]]:
    cases = evidence.get("native_reconciliation_cases") if isinstance(evidence, dict) else None
    if not isinstance(cases, list) or len(cases) < 10:
        raise ValueError("at least ten native reconciliation cases are required")
    normalized: list[dict[str, str]] = []
    for case in cases:
        if not isinstance(case, dict) or case.get("status") != "PASS":
            raise ValueError("every native reconciliation case must have status PASS")
        case_id = case.get("case_id")
        report_ref = case.get("native_report_ref")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("every reconciliation case requires a non-empty case_id")
        if not isinstance(report_ref, str) or not report_ref.strip():
            raise ValueError("every reconciliation case requires a native_report_ref")
        normalized.append({"case_id": case_id, "native_report_ref": report_ref})
    case_ids = [case["case_id"] for case in normalized]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("native reconciliation case IDs must be unique")
    return normalized


class SemanticProfileUnavailable(RuntimeError):
    code = "SEMANTIC_PROFILE_UNVALIDATED"


class SemanticProfileStale(SemanticProfileUnavailable):
    code = "SCHEMA_DRIFT"


class SemanticMappingUnconfirmed(SemanticProfileUnavailable):
    code = "SEMANTIC_MAPPING_UNCONFIRMED"


def validate_account_turnovers_mapping(mapping: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(mapping, dict):
        raise SemanticMappingUnconfirmed("account-turnover mapping must be a JSON object")
    register_set = mapping.get("entity_set")
    method = mapping.get("method")
    company_scope = mapping.get("company_scope")
    if (
        set(mapping)
        - {
            "entity_set",
            "method",
            "company_scope",
            "output_fields",
            "required_register_capabilities",
        }
        or
        not isinstance(register_set, str)
        or not _ENTITY_SET_PATTERN.fullmatch(register_set)
        or method != ACCOUNT_TURNOVERS_METHOD
        or not isinstance(company_scope, dict)
        or set(company_scope) != {"field", "value_type"}
        or not isinstance(company_scope.get("field"), str)
        or not _PROPERTY_PATTERN.fullmatch(company_scope["field"])
        or company_scope.get("value_type") not in {"guid", "string"}
        or not isinstance(mapping.get("output_fields"), dict)
        or set(mapping["output_fields"]) != set(ACCOUNT_TURNOVERS_FIELDS)
        or any(
            not isinstance(field, str) or not _PROPERTY_PATTERN.fullmatch(field)
            for field in mapping["output_fields"].values()
        )
        or len(set(mapping["output_fields"].values())) != len(ACCOUNT_TURNOVERS_FIELDS)
    ):
        raise SemanticMappingUnconfirmed("account-turnover mapping is incomplete or unsupported")
    return register_set, method


def normalize_account_turnovers(rows: Any, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Project source-native rows into a profile-defined canonical shape."""
    validate_account_turnovers_mapping(mapping)
    if not isinstance(rows, list):
        raise SemanticMappingUnconfirmed("register response is not a row list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticMappingUnconfirmed("register response contains a non-object row")
        field_map = mapping["output_fields"]
        missing = [source_field for source_field in field_map.values() if source_field not in row]
        if missing:
            raise SemanticMappingUnconfirmed(
                "register response is missing a field required by the validated semantic mapping"
            )
        normalized.append(
            {canonical_field: row[source_field] for canonical_field, source_field in field_map.items()}
        )
    return normalized


def validate_document_mapping(concept: str, mapping: dict[str, Any]) -> None:
    fields = DOCUMENT_CONCEPT_FIELDS.get(concept)
    if not isinstance(mapping, dict) or fields is None:
        raise SemanticMappingUnconfirmed("document mapping concept/object is unsupported")
    company_scope = mapping.get("company_scope")
    output_fields = mapping.get("output_fields")
    if (
        set(mapping) - {"entity_set", "company_scope", "output_fields", "order_by"}
        or not isinstance(mapping.get("entity_set"), str)
        or not mapping["entity_set"].startswith("Document_")
        or not _ENTITY_SET_PATTERN.fullmatch(
            mapping["entity_set"].replace("Document_", "AccountingRegister_", 1)
        )
        or not isinstance(company_scope, dict)
        or set(company_scope) != {"field", "value_type"}
        or not isinstance(company_scope.get("field"), str)
        or not _PROPERTY_PATTERN.fullmatch(company_scope["field"])
        or company_scope.get("value_type") not in {"guid", "string"}
        or not isinstance(output_fields, dict)
        or set(output_fields) != set(fields)
        or any(
            not isinstance(field, str) or not _PROPERTY_PATTERN.fullmatch(field)
            for field in output_fields.values()
        )
        or len(set(output_fields.values())) != len(fields)
        or not isinstance(mapping.get("order_by"), str)
        or not _PROPERTY_PATTERN.fullmatch(mapping["order_by"])
        or mapping["order_by"] != output_fields.get("date")
    ):
        raise SemanticMappingUnconfirmed("document mapping is incomplete or unsupported")


def _validate_accumulation_balance_mapping(
    mapping: dict[str, Any], fields: tuple[str, ...], label: str
) -> tuple[str, str]:
    if not isinstance(mapping, dict):
        raise SemanticMappingUnconfirmed("inventory mapping must be a JSON object")
    register_set = mapping.get("entity_set")
    company_scope = mapping.get("company_scope")
    output_fields = mapping.get("output_fields")
    if (
        set(mapping) - {"entity_set", "method", "company_scope", "output_fields", "required_register_capabilities"}
        or not isinstance(register_set, str)
        or not register_set.startswith("AccumulationRegister_")
        or not _ENTITY_SET_PATTERN.fullmatch(register_set.replace("AccumulationRegister_", "AccountingRegister_", 1))
        or mapping.get("method") != INVENTORY_BALANCE_METHOD
        or not isinstance(company_scope, dict)
        or set(company_scope) != {"field", "value_type"}
        or not isinstance(company_scope.get("field"), str)
        or not _PROPERTY_PATTERN.fullmatch(company_scope["field"])
        or company_scope.get("value_type") not in {"guid", "string"}
        or not isinstance(output_fields, dict)
        or set(output_fields) != set(fields)
        or any(not isinstance(field, str) or not _PROPERTY_PATTERN.fullmatch(field) for field in output_fields.values())
        or len(set(output_fields.values())) != len(fields)
    ):
        raise SemanticMappingUnconfirmed(f"{label} balance mapping is incomplete or unsupported")
    required = mapping.get("required_register_capabilities")
    if required is not None and required != [
        {"entity_set": register_set, "method": INVENTORY_BALANCE_METHOD}
    ]:
        raise SemanticMappingUnconfirmed(f"{label} capability dependency does not match its operation")
    return register_set, INVENTORY_BALANCE_METHOD


def validate_inventory_balance_mapping(mapping: dict[str, Any]) -> tuple[str, str]:
    return _validate_accumulation_balance_mapping(mapping, INVENTORY_BALANCE_FIELDS, "inventory")


def validate_bank_balance_mapping(mapping: dict[str, Any]) -> tuple[str, str]:
    return _validate_accumulation_balance_mapping(mapping, BANK_BALANCE_FIELDS, "bank")


def validate_settlement_balance_mapping(
    concept: str, mapping: dict[str, Any]
) -> tuple[str, str]:
    labels = {
        RECEIVABLE_BALANCE_CONCEPT: "receivable",
        PAYABLE_BALANCE_CONCEPT: "payable",
    }
    label = labels.get(concept)
    if label is None:
        raise SemanticMappingUnconfirmed("settlement balance concept is unsupported")
    return _validate_accumulation_balance_mapping(mapping, SETTLEMENT_BALANCE_FIELDS, label)


def build_inventory_balance_arguments(
    mapping: dict[str, Any], *, company_external_ref: str, period: str
) -> tuple[str, str, dict[str, str]]:
    register_set, method = validate_inventory_balance_mapping(mapping)
    try:
        point = datetime.fromisoformat(period)
    except (TypeError, ValueError) as exc:
        raise ValueError("period must be an ISO-8601 timestamp") from exc
    if point.tzinfo is None:
        raise ValueError("period must include an explicit timezone")
    return register_set, method, {
        "Period": point.isoformat(),
        "Condition": build_company_filter(mapping, company_external_ref),
    }


def build_bank_balance_arguments(
    mapping: dict[str, Any], *, company_external_ref: str, period: str
) -> tuple[str, str, dict[str, str]]:
    register_set, method = validate_bank_balance_mapping(mapping)
    try:
        point = datetime.fromisoformat(period)
    except (TypeError, ValueError) as exc:
        raise ValueError("period must be an ISO-8601 timestamp") from exc
    if point.tzinfo is None:
        raise ValueError("period must include an explicit timezone")
    return register_set, method, {
        "Period": point.isoformat(),
        "Condition": build_company_filter(mapping, company_external_ref),
    }


def build_settlement_balance_arguments(
    concept: str,
    mapping: dict[str, Any],
    *,
    company_external_ref: str,
    period: str,
) -> tuple[str, str, dict[str, str]]:
    register_set, method = validate_settlement_balance_mapping(concept, mapping)
    try:
        point = datetime.fromisoformat(period)
    except (TypeError, ValueError) as exc:
        raise ValueError("period must be an ISO-8601 timestamp") from exc
    if point.tzinfo is None:
        raise ValueError("period must include an explicit timezone")
    return register_set, method, {
        "Period": point.isoformat(),
        "Condition": build_company_filter(mapping, company_external_ref),
    }


def normalize_inventory_balance_rows(rows: Any, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    validate_inventory_balance_mapping(mapping)
    if not isinstance(rows, list):
        raise SemanticMappingUnconfirmed("inventory balance response is not a row list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticMappingUnconfirmed("inventory balance response contains a non-object row")
        field_map = mapping["output_fields"]
        if any(source_field not in row for source_field in field_map.values()):
            raise SemanticMappingUnconfirmed(
                "inventory balance response is missing a mapped field"
            )
        normalized.append(
            {canonical_field: row[source_field] for canonical_field, source_field in field_map.items()}
        )
    return normalized


def normalize_bank_balance_rows(rows: Any, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    validate_bank_balance_mapping(mapping)
    if not isinstance(rows, list):
        raise SemanticMappingUnconfirmed("bank balance response is not a row list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticMappingUnconfirmed("bank balance response contains a non-object row")
        field_map = mapping["output_fields"]
        if any(source_field not in row for source_field in field_map.values()):
            raise SemanticMappingUnconfirmed("bank balance response is missing a mapped field")
        normalized.append(
            {canonical_field: row[source_field] for canonical_field, source_field in field_map.items()}
        )
    return normalized


def normalize_settlement_balance_rows(
    rows: Any, mapping: dict[str, Any], concept: str
) -> list[dict[str, Any]]:
    validate_settlement_balance_mapping(concept, mapping)
    if not isinstance(rows, list):
        raise SemanticMappingUnconfirmed("settlement balance response is not a row list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticMappingUnconfirmed("settlement balance response contains a non-object row")
        field_map = mapping["output_fields"]
        if any(source_field not in row for source_field in field_map.values()):
            raise SemanticMappingUnconfirmed("settlement balance response is missing a mapped field")
        normalized.append(
            {canonical_field: row[source_field] for canonical_field, source_field in field_map.items()}
        )
    return normalized


def build_company_filter(mapping: dict[str, Any], company_external_ref: str) -> str:
    company_scope = mapping.get("company_scope")
    if not isinstance(company_scope, dict):
        raise SemanticMappingUnconfirmed("company scope mapping is absent")
    if company_scope.get("value_type") == "guid":
        try:
            company_ref = str(UUID(company_external_ref))
        except (TypeError, ValueError) as exc:
            raise SemanticMappingUnconfirmed(
                "company reference is not a GUID as required by the validated mapping"
            ) from exc
        literal = f"guid'{company_ref}'"
    elif company_scope.get("value_type") == "string":
        if not company_external_ref or len(company_external_ref) > 256:
            raise SemanticMappingUnconfirmed("company reference is empty or too long")
        literal = "'" + company_external_ref.replace("'", "''") + "'"
    else:
        raise SemanticMappingUnconfirmed("company value type is unsupported")
    field = company_scope.get("field")
    if not isinstance(field, str) or not _PROPERTY_PATTERN.fullmatch(field):
        raise SemanticMappingUnconfirmed("company dimension field is invalid")
    return f"{field} eq {literal}"


def normalize_document_rows(rows: Any, mapping: dict[str, Any], concept: str) -> list[dict[str, Any]]:
    validate_document_mapping(concept, mapping)
    if not isinstance(rows, list):
        raise SemanticMappingUnconfirmed("document response is not a row list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticMappingUnconfirmed("document response contains a non-object row")
        field_map = mapping["output_fields"]
        if any(source_field not in row for source_field in field_map.values()):
            raise SemanticMappingUnconfirmed(
                "document response is missing a field required by the validated semantic mapping"
            )
        normalized.append(
            {canonical_field: row[source_field] for canonical_field, source_field in field_map.items()}
        )
    return normalized


def validate_inventory_movements_mapping(mapping: dict[str, Any]) -> None:
    """Validate an operator-confirmed record-set mapping; presets are never promoted here."""
    if not isinstance(mapping, dict):
        raise SemanticMappingUnconfirmed("inventory movement mapping must be a JSON object")
    allowed = {
        "entity_set",
        "company_scope",
        "output_fields",
        "record_type_values",
        "quantity_encoding",
        "source_timezone",
        "order_by",
        "required_register_capabilities",
    }
    entity_set = mapping.get("entity_set")
    scope = mapping.get("company_scope")
    output_fields = mapping.get("output_fields")
    record_values = mapping.get("record_type_values")
    if (
        set(mapping) - allowed
        or not isinstance(entity_set, str)
        or not entity_set.startswith("AccumulationRegister_")
        or not _ENTITY_SET_PATTERN.fullmatch(
            entity_set.replace("AccumulationRegister_", "AccountingRegister_", 1)
        )
        or not isinstance(scope, dict)
        or set(scope) != {"field", "value_type"}
        or not isinstance(scope.get("field"), str)
        or not _PROPERTY_PATTERN.fullmatch(scope["field"])
        or scope.get("value_type") not in {"guid", "string"}
        or not isinstance(output_fields, dict)
        or set(output_fields) != set(INVENTORY_MOVEMENT_FIELDS)
        or any(not isinstance(field, str) or not _PROPERTY_PATTERN.fullmatch(field)
               for field in output_fields.values())
        or len(set(output_fields.values())) != len(INVENTORY_MOVEMENT_FIELDS)
        or not isinstance(mapping.get("order_by"), str)
        or mapping.get("order_by") != output_fields.get("period")
        or not isinstance(record_values, dict)
        or set(record_values) != {"receipt", "expense"}
        or any(
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
            for values in record_values.values()
        )
        or set(record_values.get("receipt", [])) & set(record_values.get("expense", []))
        or mapping.get("quantity_encoding") != "positive_magnitude_by_record_type"
        or mapping.get("required_register_capabilities", []) != []
    ):
        raise SemanticMappingUnconfirmed("inventory movement mapping is incomplete or unsupported")
    timezone_name = mapping.get("source_timezone")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise SemanticMappingUnconfirmed("source timezone must be confirmed in the semantic profile")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SemanticMappingUnconfirmed("source timezone is not a valid IANA timezone") from exc


def build_inventory_movement_query(
    mapping: dict[str, Any],
    *,
    company_external_ref: str,
    start_period: str,
    end_period: str,
) -> tuple[str, list[str], str]:
    validate_inventory_movements_mapping(mapping)
    try:
        start = datetime.fromisoformat(start_period)
        end = datetime.fromisoformat(end_period)
    except (TypeError, ValueError) as exc:
        raise ValueError("period boundaries must be ISO-8601 timestamps") from exc
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("period boundaries must include a timezone and start < end")
    source_zone = ZoneInfo(mapping["source_timezone"])
    start_local = start.astimezone(source_zone).replace(tzinfo=None).isoformat(timespec="seconds")
    end_local = end.astimezone(source_zone).replace(tzinfo=None).isoformat(timespec="seconds")
    fields = mapping["output_fields"]
    company_filter = build_company_filter(mapping, company_external_ref)
    period_field = fields["period"]
    filter_expr = (
        f"{company_filter} and {period_field} ge datetime'{start_local}' "
        f"and {period_field} lt datetime'{end_local}'"
    )
    return (
        mapping["entity_set"],
        list(fields.values()),
        filter_expr,
    )


def normalize_inventory_movement_rows(rows: Any, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    validate_inventory_movements_mapping(mapping)
    if not isinstance(rows, list):
        raise SemanticMappingUnconfirmed("inventory movement response is not a row list")
    field_map = mapping["output_fields"]
    directions = {
        value: direction
        for direction, values in mapping["record_type_values"].items()
        for value in values
    }
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or any(field not in row for field in field_map.values()):
            raise SemanticMappingUnconfirmed("inventory movement row is missing mapped fields")
        source_type = row[field_map["record_type"]]
        direction = directions.get(source_type) if isinstance(source_type, str) else None
        if direction is None:
            raise SemanticMappingUnconfirmed("register record type is not mapped by this source profile")
        raw_quantity = row[field_map["quantity"]]
        if isinstance(raw_quantity, bool):
            raise SemanticMappingUnconfirmed("movement quantity is not numeric")
        try:
            quantity = Decimal(str(raw_quantity))
        except (InvalidOperation, ValueError) as exc:
            raise SemanticMappingUnconfirmed("movement quantity is not numeric") from exc
        if not quantity.is_finite() or quantity < 0:
            raise SemanticMappingUnconfirmed(
                "movement quantity must be a non-negative magnitude per the confirmed profile"
            )
        delta = quantity if direction == "receipt" else -quantity
        normalized.append(
            {
                "period": row[field_map["period"]],
                "item_ref": row[field_map["item_ref"]],
                "warehouse_ref": row[field_map["warehouse_ref"]],
                "quantity_delta": str(delta),
                "direction": direction,
                "recorder_ref": row[field_map["recorder_ref"]],
            }
        )
    return normalized


def build_account_turnovers_arguments(
    mapping: dict[str, Any],
    *,
    company_external_ref: str,
    start_period: str,
    end_period: str,
) -> tuple[str, str, dict[str, Any]]:
    """Build bounded inputs from an operator-confirmed source/company mapping."""
    register_set, method = validate_account_turnovers_mapping(mapping)
    try:
        start = datetime.fromisoformat(start_period)
        end = datetime.fromisoformat(end_period)
    except (TypeError, ValueError) as exc:
        raise ValueError("period boundaries must be ISO-8601 timestamps") from exc
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise ValueError("period boundaries must include a timezone and start <= end")

    condition = build_company_filter(mapping, company_external_ref)
    return register_set, method, {
        "Period": {"from": start.isoformat(), "to": end.isoformat()},
        "Condition": condition,
    }


class SemanticProfileStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_VALIDATION = "NEEDS_VALIDATION"
    VALIDATED = "VALIDATED"
    STALE = "STALE"
    RETIRED = "RETIRED"


def find_configuration_preset(query: str) -> ConfigurationPreset | None:
    normalized = query.strip().casefold()
    return next(
        (
            preset
            for preset in CONFIGURATION_PRESETS
            if normalized == preset.preset_id.casefold()
            or normalized in {alias.casefold() for alias in preset.aliases}
        ),
        None,
    )


def require_usable_semantic_profile(
    profile: dict[str, Any],
    *,
    source_id: str,
    company_id: UUID | None,
    metadata_fingerprint: str,
    drift_status: str,
) -> None:
    """Fail closed unless a validated profile applies to this exact source scope/schema."""
    if profile.get("status") != SemanticProfileStatus.VALIDATED:
        raise SemanticProfileUnavailable("semantic profile is not validated")
    if profile.get("source_id") != source_id or profile.get("company_id") != company_id:
        raise SemanticProfileUnavailable("semantic profile scope does not match the request")
    if drift_status == "DRIFTED" or profile.get("metadata_fingerprint") != metadata_fingerprint:
        raise SemanticProfileStale("semantic profile does not match the current metadata")
    if drift_status != "STABLE":
        raise SemanticProfileUnavailable("source metadata stability is not acknowledged")
    try:
        validate_native_reconciliation_evidence(profile.get("validation_evidence"))
    except ValueError as exc:
        raise SemanticProfileUnavailable(str(exc)) from exc


def require_profile_capabilities(
    required: list[dict[str, str]],
    register_capabilities: dict[str, Any],
    *,
    source_id: str,
    metadata_fingerprint: str,
) -> None:
    """Require source evidence for every sensitive register operation used by a mapping."""
    if (
        register_capabilities.get("source_id") != source_id
        or register_capabilities.get("metadata_fingerprint") != metadata_fingerprint
    ):
        raise CapabilityUnsupported("register capability evidence is not current for this source")
    raw_registers = register_capabilities.get("registers", [])
    if isinstance(raw_registers, list):
        registers = {
            item.get("entity_set"): item
            for item in raw_registers
            if isinstance(item, dict) and isinstance(item.get("entity_set"), str)
        }
    elif isinstance(raw_registers, dict):
        registers = raw_registers
    else:
        registers = {}
    for item in required:
        register_set = item.get("entity_set", "")
        method = item.get("method", "")
        capability = registers.get(register_set, {}).get("methods", {}).get(method, {})
        evidence = capability.get("evidence", {})
        if (
            capability.get("available") is not True
            or evidence.get("metadata_fingerprint") != metadata_fingerprint
        ):
            raise CapabilityUnsupported(
                f"profile depends on an unconfirmed source capability: {register_set}.{method}"
            )

