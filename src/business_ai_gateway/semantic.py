from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from .compatibility import CapabilityUnsupported

APROVODKA_REPOSITORY = "https://github.com/theYahia/WWmcp"
APROVODKA_SHA = "7b62c90e1fe74324605dc28d76f195200bb97252"


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

