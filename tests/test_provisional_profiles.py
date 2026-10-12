"""Provisional (UNVALIDATED_INDEPENDENT_RECONCILIATION) profiles for a real, not yet natively validated source."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from business_ai_gateway import registry as registry_module
from business_ai_gateway.fixture_profiles import (
    PROVISIONAL_PROFILE_KIND,
    ProvisionalProfiles,
    profile_provenance,
)
from business_ai_gateway.registry import Registry
from business_ai_gateway.semantic import SemanticProfileStale, SemanticProfileUnavailable
from business_ai_gateway.settings import Settings
from tests.sc_stack import ORG_ONE, ORG_TWO, fixture_document, write_fixture_file

SOURCE = "onec-818ha-reference"
CONCEPT = "cash.movements"
BASIS = {
    "basis": "independent reconstruction from AccountingRegister_Хозрасчетный_RecordType postings",
    "native_reconciliation": "NOT_RUN",
}


def provisional_document(company_id: uuid.UUID) -> dict:
    document = fixture_document(SOURCE, {ORG_ONE: company_id, ORG_TWO: uuid.uuid4()})
    document["reconciliation"] = BASIS
    return document


@pytest.fixture
def company_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def provider(tmp_path, company_id) -> ProvisionalProfiles:
    path = tmp_path / "provisional.json"
    sha = write_fixture_file(path, provisional_document(company_id))
    return ProvisionalProfiles(path, sha, environment="test")


def source_row(provider, *, tags=("real-reference", "read-only"), drift="STABLE", enabled=True, fingerprint=None):
    return {
        "tags": list(tags), "enabled": enabled, "drift_status": drift,
        "current_metadata_fingerprint": fingerprint or provider.pinned_metadata_fingerprint(SOURCE),
        "register_capabilities_json": json.dumps({}),
    }


def make_registry(provider, *, source=None, shadowed=False, production=False):
    pool = MagicMock()
    # 1st fetchrow: no VALIDATED row; 2nd: the source/capability row.
    pool.fetchrow = AsyncMock(side_effect=[None, source])
    pool.fetchval = AsyncMock(return_value=shadowed)
    db = MagicMock()
    db.require_pool.return_value = pool
    registry = Registry(db, production=False, provisional_profiles=provider)
    registry.production = production
    return registry


@pytest.fixture(autouse=True)
def _skip_capability_evidence(monkeypatch):
    # Capability evidence is exercised by its own tests; this module judges provenance and guards.
    monkeypatch.setattr(registry_module, "require_profile_capabilities", lambda *a, **k: None)


# ------------------------------------------------------------------ guards


def test_settings_guards(tmp_path):
    path, sha = str(tmp_path / "p.json"), "a" * 64
    with pytest.raises(ValueError, match="FORBIDDEN_IN_PRODUCTION"):
        Settings(_env_file=None, environment="production", provisional_profiles_file=path,
                 provisional_profiles_sha256=sha)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        Settings(_env_file=None, environment="test", provisional_profiles_file=path)
    with pytest.raises(ValueError, match="REQUIRE_TEST_ENVIRONMENT"):
        Settings(_env_file=None, environment="development", provisional_profiles_file=path,
                 provisional_profiles_sha256=sha)
    with pytest.raises(ValueError, match="SETTINGS_INVALID"):
        Settings(_env_file=None, environment="test", provisional_profiles_file="relative.json",
                 provisional_profiles_sha256=sha)
    assert Settings(_env_file=None, environment="test", provisional_profiles_file=path,
                    provisional_profiles_sha256=sha).provisional_profiles_file == path


def test_provider_refuses_production_bad_hash_and_missing_basis(tmp_path, company_id):
    path = tmp_path / "p.json"
    sha = write_fixture_file(path, provisional_document(company_id))
    for env in ("production", "development"):
        with pytest.raises(RuntimeError, match="PROVISIONAL.*FORBIDDEN_ENVIRONMENT"):
            ProvisionalProfiles(path, sha, environment=env)
    with pytest.raises(RuntimeError, match="PROVISIONAL.*HASH_MISMATCH"):
        ProvisionalProfiles(path, "0" * 64, environment="test")
    no_basis = provisional_document(company_id)
    del no_basis["reconciliation"]
    other = tmp_path / "nobasis.json"
    with pytest.raises(RuntimeError, match="RECONCILIATION_BASIS_REQUIRED"):
        ProvisionalProfiles(other, write_fixture_file(other, no_basis), environment="test")


def test_registry_refuses_provisional_provider_in_production(provider):
    with pytest.raises(ValueError, match="PROVISIONAL_PROFILES_FORBIDDEN_IN_PRODUCTION"):
        Registry(MagicMock(), production=True, provisional_profiles=provider)


def test_fingerprint_is_distinct_from_the_synthetic_one(provider, company_id):
    mapping = provider.lookup(SOURCE, company_id, CONCEPT)
    fingerprint = provider.profile_fingerprint(SOURCE, company_id, CONCEPT, mapping)

    assert fingerprint.startswith("provisional:")


# ------------------------------------------------------------------ registry behaviour


@pytest.mark.asyncio
async def test_real_reference_source_gets_a_labelled_provisional_profile(provider, company_id):
    registry = make_registry(provider, source=source_row(provider))

    profile = await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)

    assert profile["profile_kind"] == PROVISIONAL_PROFILE_KIND
    assert profile["audit_detail_code"] == "UNVALIDATED_INDEPENDENT_RECONCILIATION_PROFILE"
    assert profile["profile_fingerprint"].startswith("provisional:")
    assert profile["reconciliation_basis"] == BASIS


@pytest.mark.asyncio
async def test_provisional_provenance_never_claims_native_validation(provider, company_id):
    registry = make_registry(provider, source=source_row(provider))
    profile = await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)

    provenance = profile_provenance(profile)

    assert provenance["validation_status"] == "UNVALIDATED_INDEPENDENT_RECONCILIATION"
    assert provenance["native_reconciliation"] == "NOT_RUN"
    assert provenance["evidence_level"] == "L2_PROVISIONAL"
    assert provenance["profile_kind"] != "VALIDATED_NATIVE"
    assert "UNVALIDATED_INDEPENDENT_RECONCILIATION_NOT_NATIVE_VALIDATED" in provenance["warnings"]
    assert provenance["reconciliation_basis"] == BASIS


def test_unknown_provenance_is_still_refused():
    with pytest.raises(ValueError, match="PROFILE_PROVENANCE_UNKNOWN"):
        profile_provenance({"profile_kind": "SOMETHING_ELSE"})


@pytest.mark.asyncio
@pytest.mark.parametrize("tags", [("synthetic-fixture",), ("read-only",), ()])
async def test_source_without_real_reference_tag_is_refused(provider, company_id, tags):
    registry = make_registry(provider, source=source_row(provider, tags=tags))

    with pytest.raises(SemanticProfileUnavailable, match="no validated"):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)


@pytest.mark.asyncio
async def test_disabled_source_is_refused(provider, company_id):
    registry = make_registry(provider, source=source_row(provider, enabled=False))

    with pytest.raises(SemanticProfileUnavailable):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)


@pytest.mark.asyncio
async def test_a_db_profile_of_any_live_status_shadows_the_provisional_one(provider, company_id):
    registry = make_registry(provider, source=source_row(provider), shadowed=True)

    with pytest.raises(SemanticProfileUnavailable):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)


@pytest.mark.asyncio
async def test_metadata_drift_makes_the_provisional_profile_stale(provider, company_id):
    drifted = source_row(provider, fingerprint="f" * 64)
    registry = make_registry(provider, source=drifted)

    with pytest.raises(SemanticProfileStale):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)


@pytest.mark.asyncio
async def test_unacknowledged_drift_status_is_stale(provider, company_id):
    registry = make_registry(provider, source=source_row(provider, drift="DRIFTED"))

    with pytest.raises(SemanticProfileStale):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)


@pytest.mark.asyncio
async def test_other_company_or_unlisted_concept_or_source_is_refused(provider, company_id):
    for source_id, company, concept in (
        (SOURCE, uuid.uuid4(), CONCEPT),          # company not in the file
        (SOURCE, company_id, "no.such.concept"),   # concept not in the file
        ("some-other-source", company_id, CONCEPT),  # source not listed
    ):
        registry = make_registry(provider, source=source_row(provider))
        with pytest.raises(SemanticProfileUnavailable):
            await registry.require_semantic_mapping(source_id, company, concept)


@pytest.mark.asyncio
async def test_production_registry_never_consults_the_provisional_provider(provider, company_id):
    spy = MagicMock(wraps=provider)
    registry = make_registry(spy, source=source_row(provider), production=True)

    with pytest.raises(SemanticProfileUnavailable):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)

    assert spy.method_calls == []


@pytest.mark.asyncio
async def test_without_a_provider_the_original_refusal_is_unchanged(company_id):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)
    db = MagicMock()
    db.require_pool.return_value = pool
    registry = Registry(db, production=False)

    with pytest.raises(SemanticProfileUnavailable, match=f"no validated {CONCEPT} profile"):
        await registry.require_semantic_mapping(SOURCE, company_id, CONCEPT)


# ------------------------------------------------------------------ the committed real-source profile


def test_committed_real_source_profile_loads_and_passes_the_runtime_validator():
    import hashlib
    from pathlib import Path

    from business_ai_gateway.analytics_balance import validate_analytics_balance_mapping

    path = Path(__file__).resolve().parents[1] / "testbed" / "real1c" / "provisional_profiles_818ha.json"
    provider = ProvisionalProfiles(path, hashlib.sha256(path.read_bytes()).hexdigest(), environment="test")
    company = uuid.UUID("3e31afc5-351f-4f36-8074-99129fa3d911")

    mapping = provider.lookup(SOURCE, company, "account.balance_by_analytics")

    assert validate_analytics_balance_mapping(mapping) == ("AccountingRegister_Хозрасчетный", "balance")
    assert [item["code"] for item in mapping["accounts"]] == ["521.1"]
    assert mapping["amount_fields"] == {"debit": "СуммаSplittedBalanceDr", "credit": "СуммаSplittedBalanceCr"}
    assert provider.reconciliation["native_reconciliation"] == "NOT_RUN"
    with pytest.raises(SemanticProfileUnavailable):  # nothing else is granted
        provider.lookup(SOURCE, company, "payable.balance")
