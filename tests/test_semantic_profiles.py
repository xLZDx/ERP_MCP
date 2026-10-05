from uuid import UUID

import pytest

from business_ai_gateway.compatibility import CapabilityUnsupported
from business_ai_gateway.semantic import (
    ACCOUNT_TURNOVERS_CONCEPT,
    ACCOUNT_TURNOVERS_FIELDS,
    ACCOUNT_TURNOVERS_METHOD,
    APROVODKA_SHA,
    CONFIGURATION_PRESETS,
    SemanticMappingUnconfirmed,
    SemanticProfileStale,
    SemanticProfileUnavailable,
    build_account_turnovers_arguments,
    build_company_filter,
    find_configuration_preset,
    normalize_account_turnovers,
    normalize_document_rows,
    require_profile_capabilities,
    require_usable_semantic_profile,
    validate_account_turnovers_mapping,
    validate_document_mapping,
    validate_native_reconciliation_evidence,
)
from scripts.semantic_profiles import (
    _validate_mapping_evidence,
)
from scripts.semantic_profiles import (
    parser as semantic_admin_parser,
)

SOURCE_ID = "base-bp-001"
COMPANY_ID = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
METADATA_FINGERPRINT = "sha256:test-current"


def test_preset_catalog_is_pinned_and_advisory_only():
    assert {preset.preset_id for preset in CONFIGURATION_PRESETS} == {
        "bp30",
        "erp2",
        "ut11",
        "zup31",
    }
    assert all(preset.upstream_sha == APROVODKA_SHA for preset in CONFIGURATION_PRESETS)
    assert all(preset.status == "CANDIDATE_ONLY" for preset in CONFIGURATION_PRESETS)
    prefix_by_kind = {
        "catalog": "Catalog_",
        "document": "Document_",
        "accumulation_register": "AccumulationRegister_",
        "information_register": "InformationRegister_",
        "accounting_register": "AccountingRegister_",
        "calculation_register": "CalculationRegister_",
        "chart_of_accounts": "ChartOfAccounts_",
    }
    for preset in CONFIGURATION_PRESETS:
        names = [candidate.entity_set for candidate in preset.candidates]
        assert names and len(names) == len(set(names))
        assert all(candidate.status == "CANDIDATE_ONLY" for candidate in preset.candidates)
        for candidate in preset.candidates:
            assert candidate.entity_set.startswith(prefix_by_kind[candidate.kind])
            assert candidate.upstream_confidence in {"verified", "common"}
    keys = [
        key.casefold()
        for preset in CONFIGURATION_PRESETS
        for key in (preset.preset_id, *preset.aliases)
    ]
    assert len(keys) == len(set(keys))
    assert find_configuration_preset("  БУХГАЛТЕРИЯ ").preset_id == "bp30"
    assert find_configuration_preset("missing") is None


def test_validated_semantic_profile_requires_exact_source_company_schema_and_evidence():
    evidence = {
        "native_reconciliation_cases": [
            {
                "case_id": f"case-{i}",
                "status": "PASS",
                "native_report_ref": f"reports/{i}",
            }
            for i in range(10)
        ]
    }
    profile = {
        "source_id": SOURCE_ID,
        "company_id": COMPANY_ID,
        "status": "VALIDATED",
        "metadata_fingerprint": METADATA_FINGERPRINT,
        "validation_evidence": evidence,
    }
    require_usable_semantic_profile(
        profile,
        source_id=SOURCE_ID,
        company_id=COMPANY_ID,
        metadata_fingerprint=METADATA_FINGERPRINT,
        drift_status="STABLE",
    )

    for scope in (
        {"source_id": "other-base", "company_id": COMPANY_ID},
        {"source_id": SOURCE_ID, "company_id": None},
    ):
        with pytest.raises(SemanticProfileUnavailable):
            require_usable_semantic_profile(
                {**profile, **scope},
                source_id=SOURCE_ID,
                company_id=COMPANY_ID,
                metadata_fingerprint=METADATA_FINGERPRINT,
                drift_status="STABLE",
            )


def test_draft_or_unacknowledged_or_changed_metadata_profile_is_denied():
    evidence = {
        "native_reconciliation_cases": [
            {
                "case_id": f"case-{i}",
                "status": "PASS",
                "native_report_ref": f"reports/{i}",
            }
            for i in range(10)
        ]
    }
    profile = {
        "source_id": SOURCE_ID,
        "company_id": COMPANY_ID,
        "status": "NEEDS_VALIDATION",
        "metadata_fingerprint": METADATA_FINGERPRINT,
        "validation_evidence": {},
    }
    args = {
        "source_id": SOURCE_ID,
        "company_id": COMPANY_ID,
        "metadata_fingerprint": METADATA_FINGERPRINT,
        "drift_status": "STABLE",
    }
    with pytest.raises(SemanticProfileUnavailable):
        require_usable_semantic_profile(profile, **args)

    profile["status"] = "VALIDATED"
    profile["validation_evidence"] = evidence
    with pytest.raises(SemanticProfileStale):
        require_usable_semantic_profile(
            profile,
            **{**args, "metadata_fingerprint": "sha256:new-schema"},
        )
    with pytest.raises(SemanticProfileStale):
        require_usable_semantic_profile(profile, **{**args, "drift_status": "DRIFTED"})

    duplicated = [*evidence["native_reconciliation_cases"]]
    duplicated[-1] = {**duplicated[-1], "case_id": duplicated[0]["case_id"]}
    profile["validation_evidence"] = {"native_reconciliation_cases": duplicated}
    with pytest.raises(SemanticProfileUnavailable):
        require_usable_semantic_profile(profile, **args)


def test_semantic_mapping_cannot_claim_an_unconfirmed_register_operation():
    capabilities = {
        "source_id": SOURCE_ID,
        "metadata_fingerprint": METADATA_FINGERPRINT,
        "registers": [
            {
                "entity_set": "AccountingRegister_Хозрасчетный",
                "methods": {
                    "drCrTurnovers": {
                        "available": False,
                        "evidence": {"kind": "metadata-function-import-absent"},
                    }
                },
            }
        ],
    }
    with pytest.raises(CapabilityUnsupported) as unsupported:
        require_profile_capabilities(
            [{"entity_set": "AccountingRegister_Хозрасчетный", "method": "drCrTurnovers"}],
            capabilities,
            source_id=SOURCE_ID,
            metadata_fingerprint=METADATA_FINGERPRINT,
        )
    assert unsupported.value.code == "CAPABILITY_UNSUPPORTED"
    capabilities["registers"][0]["methods"]["drCrTurnovers"].update(
        {
            "available": True,
            "evidence": {"kind": "metadata-get-function-import", "metadata_fingerprint": METADATA_FINGERPRINT},
        }
    )
    require_profile_capabilities(
        [{"entity_set": "AccountingRegister_Хозрасчетный", "method": "drCrTurnovers"}],
        capabilities,
        source_id=SOURCE_ID,
        metadata_fingerprint=METADATA_FINGERPRINT,
    )


def test_account_turnovers_mapping_is_explicit_and_company_scoped():
    mapping = {
        "entity_set": "AccountingRegister_Хозрасчетный",
        "method": ACCOUNT_TURNOVERS_METHOD,
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "output_fields": dict(
            zip(
                ACCOUNT_TURNOVERS_FIELDS,
                ("Счет_Key", "НачальныйДт", "НачальныйКт", "ОборотДт", "ОборотКт", "КонечныйДт", "КонечныйКт"),
                strict=True,
            )
        ),
    }
    assert ACCOUNT_TURNOVERS_CONCEPT == "account.balance_and_turnovers"
    assert validate_account_turnovers_mapping(mapping) == (
        "AccountingRegister_Хозрасчетный",
        "balanceAndTurnovers",
    )
    entity_set, method, arguments = build_account_turnovers_arguments(
        mapping,
        company_external_ref="f3727523-9689-4b73-973e-9754360fd0a0",
        start_period="2026-01-01T00:00:00Z",
        end_period="2026-01-31T23:59:59Z",
    )
    assert entity_set == "AccountingRegister_Хозрасчетный"
    assert method == "balanceAndTurnovers"
    assert arguments == {
        "Period": {
            "from": "2026-01-01T00:00:00+00:00",
            "to": "2026-01-31T23:59:59+00:00",
        },
        "Condition": "Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'",
    }
    assert normalize_account_turnovers(
        [
            {
                "Счет_Key": "acc-1",
                "НачальныйДт": 1,
                "НачальныйКт": 2,
                "ОборотДт": 3,
                "ОборотКт": 4,
                "КонечныйДт": 5,
                "КонечныйКт": 6,
            }
        ],
        mapping,
    ) == [
        {
            "account": "acc-1",
            "opening_debit": 1,
            "opening_credit": 2,
            "debit_turnover": 3,
            "credit_turnover": 4,
            "closing_debit": 5,
            "closing_credit": 6,
        }
    ]
    string_scope = {**mapping, "company_scope": {"field": "Организация_Code", "value_type": "string"}}
    _, _, string_arguments = build_account_turnovers_arguments(
        string_scope,
        company_external_ref="O'Brien",
        start_period="2026-01-01T00:00:00+03:00",
        end_period="2026-01-31T23:59:59+03:00",
    )
    assert string_arguments["Condition"] == "Организация_Code eq 'O''Brien'"


def test_account_turnovers_mapping_refuses_guessed_entity_or_unscoped_call():
    base = {
        "entity_set": "AccountingRegister_Хозрасчетный",
        "method": "balanceAndTurnovers",
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "output_fields": dict(zip(ACCOUNT_TURNOVERS_FIELDS, ACCOUNT_TURNOVERS_FIELDS, strict=True)),
    }
    for mapping in (
        {**base, "entity_set": "AccountingRegister_Хозрасчетный/DrCrTurnovers"},
        {**base, "method": "drCrTurnovers"},
        {**base, "company_scope": {"field": "Организация_Key) or true", "value_type": "guid"}},
    ):
        with pytest.raises(SemanticMappingUnconfirmed):
            validate_account_turnovers_mapping(mapping)
    with pytest.raises(SemanticMappingUnconfirmed):
        build_account_turnovers_arguments(
            base,
            company_external_ref="not-a-guid",
            start_period="2026-01-01T00:00:00Z",
            end_period="2026-01-31T23:59:59Z",
        )
    with pytest.raises(ValueError, match="start <= end"):
        build_account_turnovers_arguments(
            base,
            company_external_ref="f3727523-9689-4b73-973e-9754360fd0a0",
            start_period="2026-02-01T00:00:00Z",
            end_period="2026-01-01T00:00:00Z",
        )
    with pytest.raises(SemanticMappingUnconfirmed, match="missing a field"):
        normalize_account_turnovers(
            [{"Account": "a"}],
            {
                **base,
                "output_fields": dict(
                    zip(
                        ACCOUNT_TURNOVERS_FIELDS,
                        (f"Field{i}" for i in range(7)),
                        strict=True,
                    )
                ),
            },
        )


def test_semantic_cli_exposes_operator_mapping_confirmation():
    args = semantic_admin_parser().parse_args(
        [
            "confirm-mapping",
            "--profile-id",
            "f3727523-9689-4b73-973e-9754360fd0a0",
            "--concept",
            "account.balance_and_turnovers",
            "--evidence-file",
            "mapping-review.json",
            "--actor",
            "operator",
        ]
    )
    assert args.command == "confirm-mapping"


def test_sales_and_purchase_document_maps_are_company_scoped_and_profile_projected():
    fields = {
        "document_ref": "Ref_Key",
        "document_number": "Number",
        "date": "Date",
        "counterparty": "Контрагент_Key",
        "amount": "СуммаДокумента",
        "currency": "ВалютаДокумента_Key",
        "posted": "Posted",
    }
    for concept in ("sales", "purchases"):
        mapping = {
            "entity_set": "Document_РеализацияТоваровУслуг",
            "company_scope": {"field": "Организация_Key", "value_type": "guid"},
            "output_fields": fields,
            "order_by": "Date",
        }
        validate_document_mapping(concept, mapping)
        assert build_company_filter(
            mapping, "f3727523-9689-4b73-973e-9754360fd0a0"
        ) == "Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'"
        assert normalize_document_rows(
            [
                {
                    "Ref_Key": "doc-1",
                    "Number": "0001",
                    "Date": "2026-01-01T00:00:00",
                    "Контрагент_Key": "party-1",
                    "СуммаДокумента": "125.50",
                    "ВалютаДокумента_Key": "currency-1",
                    "Posted": True,
                }
            ],
            mapping,
            concept,
        )[0]["amount"] == "125.50"


def test_document_map_restricts_entity_kind_and_rejects_unreviewed_filter():
    mapping = {
        "entity_set": "Document_РеализацияТоваровУслуг",
        "company_scope": {"field": "Организация_Key", "value_type": "string"},
        "output_fields": {
            "document_ref": "Ref_Key",
            "document_number": "Number",
            "date": "Date",
            "counterparty": "Контрагент_Key",
            "amount": "СуммаДокумента",
            "currency": "ВалютаДокумента_Key",
            "posted": "Posted",
        },
        "order_by": "Date",
    }
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_document_mapping(
            "sales", {**mapping, "entity_set": "Catalog_Номенклатура"}
        )
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_document_mapping("sales", {**mapping, "filter": "true"})


def test_old_or_cross_source_register_evidence_cannot_authorize_semantic_mapping():
    with pytest.raises(CapabilityUnsupported):
        require_profile_capabilities(
            [{"entity_set": "AccountingRegister_Хозрасчетный", "method": "drCrTurnovers"}],
            {"source_id": "other-base", "metadata_fingerprint": METADATA_FINGERPRINT, "registers": []},
            source_id=SOURCE_ID,
            metadata_fingerprint=METADATA_FINGERPRINT,
        )


def test_native_evidence_and_operator_cli_require_reconciliation_and_actor():
    cases = [
        {"case_id": f"case-{i}", "status": "PASS", "native_report_ref": f"reports/{i}"}
        for i in range(10)
    ]
    assert len(validate_native_reconciliation_evidence({"native_reconciliation_cases": cases})) == 10
    with pytest.raises(ValueError, match="status PASS"):
        validate_native_reconciliation_evidence(
            {"native_reconciliation_cases": [*cases[:-1], {**cases[-1], "status": "FAIL"}]}
        )
    with pytest.raises(ValueError, match="unique"):
        validate_native_reconciliation_evidence(
            {"native_reconciliation_cases": [*cases[:-1], {**cases[-1], "case_id": "case-0"}]}
        )
    parsed = semantic_admin_parser().parse_args(
        [
            "create",
            "--source-id",
            SOURCE_ID,
            "--preset-id",
            "bp30",
            "--profile-name",
            "draft",
            "--actor",
            "operator-1",
        ]
    )
    assert parsed.command == "create"
    assert parsed.actor == "operator-1"
    assert _validate_mapping_evidence(
        {"evidence_refs": ["controlled://mapping-source/1"], "notes": "Reviewed"}
    )["evidence_refs"] == ["controlled://mapping-source/1"]
    with pytest.raises(ValueError, match="only evidence_refs and notes"):
        _validate_mapping_evidence({"rows": [{"amount": 42}]})


def test_semantic_profile_migration_persists_versioned_pinned_preset_and_requires_reconciliation():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sql = (root / "db/migrations/006_semantic_profiles.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS bag.semantic_profiles" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.semantic_mappings" in sql
    assert "native_reconciliation_cases" in sql
    assert "jsonb_array_length" in sql
    assert "native_reconciliation_evidence_valid" in sql
    assert "preset_upstream_sha text NOT NULL" in sql
    assert "GRANT SELECT ON bag.semantic_profiles, bag.semantic_mappings TO business_ai_app" in sql
    assert "SECURITY DEFINER" in sql
    assert "source_capabilities_invalidate_semantic_profiles" in sql
    assert "VALUES (6)" in sql

    events = (root / "db/migrations/007_semantic_profile_events.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS bag.semantic_profile_events" in events
    assert "BEFORE UPDATE OR DELETE" in events
    assert "GRANT SELECT, INSERT ON bag.semantic_profile_events TO business_ai_admin" in events
    assert "VALUES (7)" in events
