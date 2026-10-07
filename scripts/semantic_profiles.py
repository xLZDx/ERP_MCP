"""Operator-only lifecycle for source/company-scoped semantic profiles."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import asyncpg

from business_ai_gateway.analytics_balance import (
    ANALYTICS_BALANCE_CONCEPT,
    validate_analytics_balance_mapping,
)
from business_ai_gateway.compatibility import CapabilityUnsupported
from business_ai_gateway.duplicate_counterparties import (
    DUPLICATE_CONCEPT,
    validate_duplicate_mapping,
)
from business_ai_gateway.evidence_basis import (
    BASIS_MACHINE,
    MACHINE_EVIDENCE_CLASS,
    check_machine_evidence_structure,
)
from business_ai_gateway.semantic import (
    ACCOUNTING_POSTING_ROWS_CONCEPT,
    BANK_BALANCE_CONCEPT,
    CASH_MOVEMENTS_CONCEPT,
    INVENTORY_BALANCE_CONCEPT,
    INVENTORY_MOVEMENTS_CONCEPT,
    PAYABLE_BALANCE_CONCEPT,
    PRESETS_BY_ID,
    RECEIVABLE_BALANCE_CONCEPT,
    canonical_fingerprint,
    capability_evidence_fingerprint,
    find_configuration_preset,
    require_profile_capabilities,
    validate_account_turnovers_mapping,
    validate_accounting_posting_rows_mapping,
    validate_bank_balance_mapping,
    validate_cash_movements_mapping,
    validate_document_mapping,
    validate_inventory_balance_mapping,
    validate_inventory_movements_mapping,
    validate_native_reconciliation_evidence,
    validate_settlement_balance_mapping,
)
from business_ai_gateway.settings import Settings
from business_ai_gateway.settlement_collector import (
    OPEN_ITEMS_CONCEPTS,
    validate_open_items_mapping,
)

try:  # run as ``python scripts/semantic_profiles.py`` (scripts/ on sys.path) or imported as ``scripts.*``
    from real1c import machine_reconciliation
except ImportError:  # pragma: no cover - import layout depends on the caller
    from scripts.real1c import machine_reconciliation

CONCEPTS = (
    "account.balance_and_turnovers",
    "receivable.open_items",
    "payable.open_items",
    DUPLICATE_CONCEPT,
    "receivable",
    "payable",
    "sales",
    "purchases",
    "cash",
    "inventory",
    INVENTORY_BALANCE_CONCEPT,
    INVENTORY_MOVEMENTS_CONCEPT,
    ACCOUNTING_POSTING_ROWS_CONCEPT,
    CASH_MOVEMENTS_CONCEPT,
    BANK_BALANCE_CONCEPT,
    RECEIVABLE_BALANCE_CONCEPT,
    PAYABLE_BALANCE_CONCEPT,
    ANALYTICS_BALANCE_CONCEPT,
    "vat",
)


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _read_object(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if file_path.stat().st_size > 256_000:
        raise ValueError("semantic profile input file exceeds 256 KB")
    value = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _validate_mapping_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    if set(evidence) - {"evidence_refs", "notes"}:
        raise ValueError("mapping evidence may contain only evidence_refs and notes")
    refs = evidence.get("evidence_refs", [])
    if not isinstance(refs, list) or any(
        not isinstance(ref, str) or not ref.strip() or len(ref) > 2048 for ref in refs
    ):
        raise ValueError("mapping evidence_refs must be non-empty controlled references")
    notes = evidence.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 2048:
        raise ValueError("mapping evidence notes must be text of at most 2048 characters")
    return {"evidence_refs": refs, "notes": notes}


def _profile_fingerprint(profile: Any, mappings: list[Any]) -> str:
    return canonical_fingerprint(
        {
            "source_id": profile["source_id"],
            "company_id": str(profile["company_id"]) if profile["company_id"] else None,
            "preset_id": profile["preset_id"],
            "profile_name": profile["profile_name"],
            "profile_version": profile["profile_version"],
            "metadata_fingerprint": profile["metadata_fingerprint"],
            "capability_fingerprint": profile["capability_fingerprint"],
            "preset_repository": profile["preset_repository"],
            "preset_upstream_sha": profile["preset_upstream_sha"],
            "profile_json": _json_value(profile["profile_json"]),
            "mappings": [
                {
                    "canonical_concept": row["canonical_concept"],
                    "mapping_json": _json_value(row["mapping_json"]),
                    "evidence_json": _json_value(row["evidence_json"]),
                    "mapping_status": row["mapping_status"],
                    "confidence": row["confidence"],
                }
                for row in mappings
            ],
            "validation_evidence_json": _json_value(profile["validation_evidence_json"]),
        }
    )


async def _record_event(
    conn: asyncpg.Connection,
    *,
    profile_id: uuid.UUID,
    actor: str,
    action: str,
    details: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO bag.semantic_profile_events(event_id, profile_id, actor, action, details_json)
        VALUES($1,$2,$3,$4,$5::jsonb)
        """,
        uuid.uuid4(),
        profile_id,
        actor,
        action,
        json.dumps(details, ensure_ascii=False),
    )


async def create_profile(args: argparse.Namespace, conn: asyncpg.Connection) -> uuid.UUID:
    preset = find_configuration_preset(args.preset_id)
    if preset is None or preset.preset_id not in PRESETS_BY_ID:
        raise ValueError("unknown Aprovodka preset ID")
    capability_row = await conn.fetchrow(
        """
        SELECT metadata_fingerprint, metadata_supported, drift_status,
               register_capabilities_json
        FROM bag.source_capabilities WHERE source_id=$1
        """,
        args.source_id,
    )
    if capability_row is None or not capability_row["metadata_supported"]:
        raise ValueError("source has no successful live metadata capability record")
    if capability_row["drift_status"] != "STABLE":
        raise ValueError("source metadata must be acknowledged STABLE before profile creation")
    if args.company_id:
        company_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM bag.companies WHERE source_id=$1 AND company_id=$2)",
            args.source_id,
            uuid.UUID(args.company_id),
        )
        if not company_exists:
            raise ValueError("company does not belong to the selected source")

    operator_definition = _read_object(args.profile_file) if args.profile_file else {}
    definition = {
        "preset_source": {
            "repository": preset.upstream_repository,
            "sha": preset.upstream_sha,
            "path": preset.upstream_path,
            "status": preset.status,
        },
        "candidate_entities": [asdict(candidate) for candidate in preset.candidates],
        "operator_definition": operator_definition,
    }
    capability_profile = _json_value(capability_row["register_capabilities_json"])
    if not isinstance(capability_profile, dict):
        raise TypeError("stored register capability profile is invalid")
    capability_fingerprint = capability_evidence_fingerprint(capability_profile)
    profile_id = uuid.uuid4()
    company_id = uuid.UUID(args.company_id) if args.company_id else None
    version = await conn.fetchval(
        """
        SELECT coalesce(max(profile_version),0)+1
        FROM bag.semantic_profiles
        WHERE source_id=$1 AND company_id IS NOT DISTINCT FROM $2::uuid AND preset_id=$3
        """,
        args.source_id,
        company_id,
        preset.preset_id,
    )
    fields = {
        "source_id": args.source_id,
        "company_id": str(company_id) if company_id else None,
        "preset_id": preset.preset_id,
        "profile_name": args.profile_name,
        "profile_version": version,
        "metadata_fingerprint": capability_row["metadata_fingerprint"],
        "capability_fingerprint": capability_fingerprint,
        "preset_repository": preset.upstream_repository,
        "preset_upstream_sha": preset.upstream_sha,
        "profile_json": definition,
        "validation_evidence_json": {},
    }
    profile_fingerprint = _profile_fingerprint(fields, [])
    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO bag.semantic_profiles(
                profile_id, source_id, company_id, preset_id, profile_name, profile_version,
                status, metadata_fingerprint, capability_fingerprint, profile_fingerprint,
                preset_repository, preset_upstream_sha, profile_json, created_by
            ) VALUES($1,$2,$3,$4,$5,$6,'DRAFT',$7,$8,$9,$10,$11,$12::jsonb,$13)
            """,
            profile_id,
            args.source_id,
            company_id,
            preset.preset_id,
            args.profile_name,
            version,
            capability_row["metadata_fingerprint"],
            capability_fingerprint,
            profile_fingerprint,
            preset.upstream_repository,
            preset.upstream_sha,
            json.dumps(definition, ensure_ascii=False),
            args.actor,
        )
        await _record_event(
            conn,
            profile_id=profile_id,
            actor=args.actor,
            action="CREATED",
            details={"preset_id": preset.preset_id, "profile_fingerprint": profile_fingerprint},
        )
    return profile_id


async def add_mapping(args: argparse.Namespace, conn: asyncpg.Connection) -> None:
    profile_id = uuid.UUID(args.profile_id)
    profile = await conn.fetchrow(
        "SELECT profile_id, status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
    )
    if profile is None or profile["status"] not in {"DRAFT", "NEEDS_VALIDATION"}:
        raise ValueError("mappings can be added only to a draft profile")
    mapping = _read_object(args.mapping_file)
    if args.concept == "account.balance_and_turnovers":
        validate_account_turnovers_mapping(mapping)
        required = mapping.get("required_register_capabilities")
        expected = [{"entity_set": mapping["entity_set"], "method": mapping["method"]}]
        if required is not None and required != expected:
            raise ValueError("account-turnover capability dependency must match the exact mapping")
        mapping["required_register_capabilities"] = expected
    elif args.concept in {"sales", "purchases"}:
        validate_document_mapping(args.concept, mapping)
    elif args.concept == INVENTORY_BALANCE_CONCEPT:
        entity_set, method = validate_inventory_balance_mapping(mapping)
        required = mapping.get("required_register_capabilities")
        expected = [{"entity_set": entity_set, "method": method}]
        if required is not None and required != expected:
            raise ValueError("inventory capability dependency must match the exact mapping")
        mapping["required_register_capabilities"] = expected
    elif args.concept == INVENTORY_MOVEMENTS_CONCEPT:
        validate_inventory_movements_mapping(mapping)
        if mapping.get("required_register_capabilities", []) != []:
            raise ValueError("movement record-set mapping cannot claim virtual-table methods")
    elif args.concept == ACCOUNTING_POSTING_ROWS_CONCEPT:
        validate_accounting_posting_rows_mapping(mapping)
        if mapping.get("required_register_capabilities", []) != []:
            raise ValueError(
                "accounting posting record-set mapping cannot claim virtual-table methods"
            )
    elif args.concept == CASH_MOVEMENTS_CONCEPT:
        validate_cash_movements_mapping(mapping)
        if mapping.get("required_register_capabilities", []) != []:
            raise ValueError("cash movement record-set mapping cannot claim virtual-table methods")
    elif args.concept in OPEN_ITEMS_CONCEPTS:
        validate_open_items_mapping(args.concept, mapping)
    elif args.concept == DUPLICATE_CONCEPT:
        validate_duplicate_mapping(mapping)
    elif args.concept == BANK_BALANCE_CONCEPT:
        entity_set, method = validate_bank_balance_mapping(mapping)
        required = mapping.get("required_register_capabilities")
        expected = [{"entity_set": entity_set, "method": method}]
        if required is not None and required != expected:
            raise ValueError("bank capability dependency must match the exact mapping")
        mapping["required_register_capabilities"] = expected
    elif args.concept in {RECEIVABLE_BALANCE_CONCEPT, PAYABLE_BALANCE_CONCEPT}:
        entity_set, method = validate_settlement_balance_mapping(args.concept, mapping)
        required = mapping.get("required_register_capabilities")
        expected = [{"entity_set": entity_set, "method": method}]
        if required is not None and required != expected:
            raise ValueError("settlement capability dependency must match the exact mapping")
        mapping["required_register_capabilities"] = expected
    elif args.concept == ANALYTICS_BALANCE_CONCEPT:
        if isinstance(mapping, dict) and "required_register_capabilities" not in mapping:
            mapping["required_register_capabilities"] = [
                {"entity_set": mapping.get("entity_set"), "method": mapping.get("method")}
            ]
        validate_analytics_balance_mapping(mapping)
    evidence = _read_object(args.evidence_file) if args.evidence_file else {}
    evidence = _validate_mapping_evidence(evidence)
    if "required_register_capabilities" in mapping:
        required = mapping["required_register_capabilities"]
        if not isinstance(required, list) or any(
            not isinstance(item, dict)
            or set(item) != {"entity_set", "method"}
            or not all(isinstance(item[key], str) and item[key] for key in item)
            for item in required
        ):
            raise ValueError("required_register_capabilities must contain entity_set/method pairs")

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO bag.semantic_mappings(
                mapping_id, profile_id, canonical_concept, mapping_json, evidence_json,
                mapping_status, confidence
            ) VALUES($1,$2,$3,$4::jsonb,$5::jsonb,'CANDIDATE','LOW')
            """,
            uuid.uuid4(),
            profile_id,
            args.concept,
            json.dumps(mapping, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
        )
        await conn.execute(
            "UPDATE bag.semantic_profiles SET status='NEEDS_VALIDATION' WHERE profile_id=$1",
            profile_id,
        )
        profile_full = await conn.fetchrow(
            "SELECT * FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        )
        mappings = await conn.fetch(
            "SELECT * FROM bag.semantic_mappings WHERE profile_id=$1 ORDER BY canonical_concept",
            profile_id,
        )
        profile_fingerprint = _profile_fingerprint(profile_full, mappings)
        await conn.execute(
            "UPDATE bag.semantic_profiles SET profile_fingerprint=$2 WHERE profile_id=$1",
            profile_id,
            profile_fingerprint,
        )
        await _record_event(
            conn,
            profile_id=profile_id,
            actor=args.actor,
            action="MAPPING_ADDED",
            details={
                "canonical_concept": args.concept,
                "mapping_fingerprint": canonical_fingerprint(mapping),
            },
        )


async def confirm_mapping(args: argparse.Namespace, conn: asyncpg.Connection) -> None:
    profile_id = uuid.UUID(args.profile_id)
    evidence = _validate_mapping_evidence(_read_object(args.evidence_file))
    if not evidence["evidence_refs"]:
        raise ValueError("mapping confirmation requires at least one controlled evidence reference")
    async with conn.transaction():
        profile = await conn.fetchrow(
            "SELECT * FROM bag.semantic_profiles WHERE profile_id=$1 FOR UPDATE", profile_id
        )
        if profile is None or profile["status"] not in {"DRAFT", "NEEDS_VALIDATION"}:
            raise ValueError("mappings can be confirmed only before profile validation")
        mapping_row = await conn.fetchrow(
            """
            SELECT * FROM bag.semantic_mappings
            WHERE profile_id=$1 AND canonical_concept=$2 FOR UPDATE
            """,
            profile_id,
            args.concept,
        )
        if mapping_row is None or mapping_row["mapping_status"] != "CANDIDATE":
            raise ValueError("candidate mapping not found or is no longer confirmable")
        mapping = _json_value(mapping_row["mapping_json"])
        if args.concept == "account.balance_and_turnovers":
            entity_set, method = validate_account_turnovers_mapping(mapping)
            required = mapping.get("required_register_capabilities")
            if required != [{"entity_set": entity_set, "method": method}]:
                raise ValueError("mapping capability dependency does not match its operation")
        elif args.concept in {"sales", "purchases"}:
            validate_document_mapping(args.concept, mapping)
        elif args.concept == INVENTORY_BALANCE_CONCEPT:
            entity_set, method = validate_inventory_balance_mapping(mapping)
            if mapping.get("required_register_capabilities") != [
                {"entity_set": entity_set, "method": method}
            ]:
                raise ValueError("inventory capability dependency does not match its operation")
        elif args.concept == INVENTORY_MOVEMENTS_CONCEPT:
            validate_inventory_movements_mapping(mapping)
            if mapping.get("required_register_capabilities", []) != []:
                raise ValueError("movement record-set mapping cannot claim virtual-table methods")
        elif args.concept == ACCOUNTING_POSTING_ROWS_CONCEPT:
            validate_accounting_posting_rows_mapping(mapping)
            if mapping.get("required_register_capabilities", []) != []:
                raise ValueError(
                    "accounting posting record-set mapping cannot claim virtual-table methods"
                )
        elif args.concept == CASH_MOVEMENTS_CONCEPT:
            validate_cash_movements_mapping(mapping)
            if mapping.get("required_register_capabilities", []) != []:
                raise ValueError(
                    "cash movement record-set mapping cannot claim virtual-table methods"
                )
        elif args.concept == BANK_BALANCE_CONCEPT:
            entity_set, method = validate_bank_balance_mapping(mapping)
            if mapping.get("required_register_capabilities") != [
                {"entity_set": entity_set, "method": method}
            ]:
                raise ValueError("bank capability dependency does not match its operation")
        elif args.concept in {RECEIVABLE_BALANCE_CONCEPT, PAYABLE_BALANCE_CONCEPT}:
            entity_set, method = validate_settlement_balance_mapping(args.concept, mapping)
            if mapping.get("required_register_capabilities") != [
                {"entity_set": entity_set, "method": method}
            ]:
                raise ValueError("settlement capability dependency does not match its operation")
        elif args.concept == ANALYTICS_BALANCE_CONCEPT:
            validate_analytics_balance_mapping(mapping)
        previous_evidence = _json_value(mapping_row["evidence_json"])
        combined_evidence = {
            "evidence_refs": list(
                dict.fromkeys(
                    [*previous_evidence.get("evidence_refs", []), *evidence["evidence_refs"]]
                )
            ),
            "notes": evidence["notes"] or previous_evidence.get("notes", ""),
        }
        await conn.execute(
            """
            UPDATE bag.semantic_mappings
            SET mapping_status='CONFIRMED', confidence='HIGH', evidence_json=$3::jsonb
            WHERE mapping_id=$1 AND profile_id=$2
            """,
            mapping_row["mapping_id"],
            profile_id,
            json.dumps(combined_evidence, ensure_ascii=False),
        )
        mappings = await conn.fetch(
            "SELECT * FROM bag.semantic_mappings WHERE profile_id=$1 ORDER BY canonical_concept",
            profile_id,
        )
        profile_fingerprint = _profile_fingerprint(profile, mappings)
        await conn.execute(
            "UPDATE bag.semantic_profiles SET profile_fingerprint=$2 WHERE profile_id=$1",
            profile_id,
            profile_fingerprint,
        )
        await _record_event(
            conn,
            profile_id=profile_id,
            actor=args.actor,
            action="MAPPING_CONFIRMED",
            details={
                "mapping_id": str(mapping_row["mapping_id"]),
                "canonical_concept": args.concept,
                "evidence_fingerprint": canonical_fingerprint(evidence),
                "profile_fingerprint": profile_fingerprint,
            },
        )


def _is_machine_manifest(evidence: dict[str, Any]) -> bool:
    cases = evidence.get("native_reconciliation_cases")
    return "machine_scope" in evidence or "evidence_basis" in evidence or (
        isinstance(cases, list)
        and any(isinstance(c, dict) and c.get("evidence_class") == MACHINE_EVIDENCE_CLASS for c in cases)
    )


def _machine_validation_evidence(
    evidence_input: dict[str, Any],
    *,
    args: argparse.Namespace,
    profile: Any,
    mappings: list[Any],
    capability_fingerprint: str,
) -> dict[str, Any]:
    """CLI-only path for labelled machine two-source evidence; every precondition is re-proved here."""
    settings = Settings()
    if settings.environment != "test":
        raise ValueError("machine two-source validation is test-environment only")
    if profile["source_id"] not in settings.machine_reconciled_source_items:
        raise ValueError("source is not in BAG_MACHINE_RECONCILED_SOURCES")
    if profile["company_id"] is None:
        raise ValueError("machine two-source validation needs a company-specific profile")
    if len(mappings) != 1 or mappings[0]["canonical_concept"] != ANALYTICS_BALANCE_CONCEPT:
        raise ValueError("a machine-reconciled profile carries exactly one analytics-balance mapping")
    mapping = _json_value(mappings[0]["mapping_json"])
    codes = sorted(a.get("code") for a in mapping.get("accounts", []) if isinstance(a, dict))
    if codes != ["521.1"]:
        raise ValueError("machine two-source validation is limited to account 521.1")
    if not args.artifacts_root or not args.plans_dir:
        raise ValueError("--artifacts-root and --plans-dir are required for machine evidence")
    allowed_keys = {"native_reconciliation_cases", "evidence_basis", "machine_scope"}
    if set(evidence_input) - allowed_keys:
        raise ValueError("machine evidence manifest has unexpected fields")
    check_machine_evidence_structure(
        evidence_input,
        source_id=profile["source_id"],
        company_id=str(profile["company_id"]),
        concept=ANALYTICS_BALANCE_CONCEPT,
        mapping=mapping,
        metadata_fingerprint=profile["metadata_fingerprint"],
        capability_fingerprint=capability_fingerprint,
    )
    machine_reconciliation.verify_all(
        evidence_input,
        artifacts_root=Path(args.artifacts_root),
        plans_dir=Path(args.plans_dir),
        scope_sha256=evidence_input["machine_scope"]["authorization_scope_sha256"],
    )
    validate_native_reconciliation_evidence(evidence_input, allow_machine=True)
    return {
        # The full verified case records are stored (class, run records, authority): the normalized
        # case_id/ref pair alone would lose the class and read back as native evidence.
        "native_reconciliation_cases": [
            {**case, "status": "PASS"} for case in evidence_input["native_reconciliation_cases"]
        ],
        "evidence_basis": BASIS_MACHINE,
        "machine_scope": evidence_input["machine_scope"],
        "evidence_manifest_fingerprint": canonical_fingerprint(evidence_input),
    }


async def validate_profile(args: argparse.Namespace, conn: asyncpg.Connection) -> None:
    profile_id = uuid.UUID(args.profile_id)
    evidence_input = _read_object(args.evidence_file)
    machine = _is_machine_manifest(evidence_input)
    validation_evidence = None
    if not machine:
        cases = validate_native_reconciliation_evidence(evidence_input)
        validation_evidence = {
            "native_reconciliation_cases": [{**case, "status": "PASS"} for case in cases],
            "evidence_manifest_fingerprint": canonical_fingerprint(evidence_input),
        }
    async with conn.transaction():
        profile = await conn.fetchrow(
            """
            SELECT * FROM bag.semantic_profiles WHERE profile_id=$1 FOR UPDATE
            """,
            profile_id,
        )
        if profile is None or profile["status"] not in {"DRAFT", "NEEDS_VALIDATION"}:
            raise ValueError("only a draft profile can be validated")
        capability_row = await conn.fetchrow(
            """
            SELECT metadata_fingerprint, drift_status, register_capabilities_json
            FROM bag.source_capabilities WHERE source_id=$1
            """,
            profile["source_id"],
        )
        if capability_row is None or capability_row["drift_status"] != "STABLE":
            raise ValueError("source capabilities are absent or metadata drift is unacknowledged")
        if capability_row["metadata_fingerprint"] != profile["metadata_fingerprint"]:
            raise ValueError("profile metadata fingerprint is stale")
        capability_profile = _json_value(capability_row["register_capabilities_json"])
        if capability_evidence_fingerprint(capability_profile) != profile["capability_fingerprint"]:
            raise ValueError("profile capability fingerprint is stale")

        mappings = await conn.fetch(
            "SELECT * FROM bag.semantic_mappings WHERE profile_id=$1 ORDER BY canonical_concept",
            profile_id,
        )
        for mapping_row in mappings:
            if mapping_row["mapping_status"] != "CONFIRMED" or mapping_row["confidence"] != "HIGH":
                raise ValueError(
                    f"mapping {mapping_row['canonical_concept']} must be explicitly confirmed before validation"
                )
            mapping = _json_value(mapping_row["mapping_json"])
            required = mapping.get("required_register_capabilities", [])
            if not isinstance(required, list):
                raise TypeError("mapping required_register_capabilities must be a list")
            if mapping_row["canonical_concept"] == ANALYTICS_BALANCE_CONCEPT:
                validate_analytics_balance_mapping(mapping)
                continue  # OData availability is judged per request by route selection (ADR-0008)
            require_profile_capabilities(
                required,
                capability_profile,
                source_id=profile["source_id"],
                metadata_fingerprint=profile["metadata_fingerprint"],
            )

        if machine:
            validation_evidence = _machine_validation_evidence(
                evidence_input,
                args=args,
                profile=profile,
                mappings=mappings,
                capability_fingerprint=profile["capability_fingerprint"],
            )
            cases = validation_evidence["native_reconciliation_cases"]
        profile = dict(profile)
        profile["validation_evidence_json"] = validation_evidence
        profile_fingerprint = _profile_fingerprint(profile, mappings)
        updated = await conn.fetchrow(
            """
            UPDATE bag.semantic_profiles
            SET status='VALIDATED', validated_by=$2, validated_at=now(),
                validation_evidence_json=$3::jsonb, profile_fingerprint=$4
            WHERE profile_id=$1 AND status IN ('DRAFT','NEEDS_VALIDATION')
            RETURNING profile_id
            """,
            profile_id,
            args.actor,
            json.dumps(validation_evidence, ensure_ascii=False),
            profile_fingerprint,
        )
        if updated is None:
            raise ValueError("profile lifecycle changed during validation")
        await _record_event(
            conn,
            profile_id=profile_id,
            actor=args.actor,
            action="VALIDATED",
            details={
                "profile_fingerprint": profile_fingerprint,
                "metadata_fingerprint": profile["metadata_fingerprint"],
                "capability_fingerprint": profile["capability_fingerprint"],
                "case_count": len(cases),
            },
        )


async def retire_profile(args: argparse.Namespace, conn: asyncpg.Connection) -> None:
    profile_id = uuid.UUID(args.profile_id)
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            UPDATE bag.semantic_profiles
            SET status='RETIRED', retired_at=now()
            WHERE profile_id=$1 AND status <> 'RETIRED'
            RETURNING profile_id, profile_fingerprint
            """,
            profile_id,
        )
        if row is None:
            raise ValueError("semantic profile not found or already retired")
        await _record_event(
            conn,
            profile_id=profile_id,
            actor=args.actor,
            action="RETIRED",
            details={"profile_fingerprint": row["profile_fingerprint"]},
        )


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    dsn = settings.admin_database_url
    if settings.environment == "production" and not dsn:
        raise RuntimeError(
            "production semantic profile administration requires BAG_ADMIN_DATABASE_URL"
        )
    conn = await asyncpg.connect(dsn or settings.database_url)
    try:
        if args.command == "create":
            print(await create_profile(args, conn))
        elif args.command == "add-mapping":
            await add_mapping(args, conn)
        elif args.command == "confirm-mapping":
            await confirm_mapping(args, conn)
        elif args.command == "validate":
            await validate_profile(args, conn)
        elif args.command == "retire":
            await retire_profile(args, conn)
    except CapabilityUnsupported as exc:
        raise RuntimeError(f"{exc.code}: {exc}") from exc
    finally:
        await conn.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--source-id", required=True)
    create.add_argument("--company-id")
    create.add_argument("--preset-id", choices=sorted(PRESETS_BY_ID), required=True)
    create.add_argument("--profile-name", required=True)
    create.add_argument("--profile-file")
    create.add_argument("--actor", required=True)

    mapping = commands.add_parser("add-mapping")
    mapping.add_argument("--profile-id", required=True)
    mapping.add_argument("--concept", choices=CONCEPTS, required=True)
    mapping.add_argument("--mapping-file", required=True)
    mapping.add_argument("--evidence-file")
    mapping.add_argument("--actor", required=True)

    confirm = commands.add_parser("confirm-mapping")
    confirm.add_argument("--profile-id", required=True)
    confirm.add_argument("--concept", choices=CONCEPTS, required=True)
    confirm.add_argument("--evidence-file", required=True)
    confirm.add_argument("--actor", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--profile-id", required=True)
    validate.add_argument("--evidence-file", required=True)
    validate.add_argument("--actor", required=True)
    validate.add_argument("--artifacts-root", help="private root of machine-artifact: references")
    validate.add_argument("--plans-dir", help="Rosetta plans directory (machine evidence authority check)")

    retire = commands.add_parser("retire")
    retire.add_argument("--profile-id", required=True)
    retire.add_argument("--actor", required=True)
    return root


if __name__ == "__main__":
    asyncio.run(_run(parser().parse_args()))
