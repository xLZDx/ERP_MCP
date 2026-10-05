from uuid import UUID

import pytest

from business_ai_gateway.compatibility import CapabilityUnsupported
from business_ai_gateway.semantic import (
    APROVODKA_SHA,
    CONFIGURATION_PRESETS,
    SemanticProfileStale,
    SemanticProfileUnavailable,
    find_configuration_preset,
    require_profile_capabilities,
    require_usable_semantic_profile,
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


def test_old_or_cross_source_register_evidence_cannot_authorize_semantic_mapping():
    with pytest.raises(CapabilityUnsupported):
        require_profile_capabilities(
            [{"entity_set": "AccountingRegister_Хозрасчетный", "method": "drCrTurnovers"}],
            {"source_id": "other-base", "metadata_fingerprint": METADATA_FINGERPRINT, "registers": []},
            source_id=SOURCE_ID,
            metadata_fingerprint=METADATA_FINGERPRINT,
        )


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
