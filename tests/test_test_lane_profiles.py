from __future__ import annotations

import hashlib
import json
import uuid

import pytest

from business_ai_gateway.fixture_profiles import (
    TEST_LANE_PROFILE_KIND,
    TEST_LANE_WARNING,
    SyntheticFixtureProfiles,
    profile_provenance,
)
from business_ai_gateway.registry import Registry
from business_ai_gateway.settings import Settings
from scripts import test_lane_profiles as gen

SHA = "a" * 64


def _lane(**kw):
    return Settings(_env_file=None, **kw)


def test_committed_file_matches_generator_and_every_mapping_passes_the_shared_validators():
    raw = gen.FIXTURE_PATH.read_bytes()
    assert raw == gen.render(), "re-pin: python scripts/test_lane_profiles.py --write"
    provider = SyntheticFixtureProfiles(
        gen.FIXTURE_PATH, hashlib.sha256(raw).hexdigest(), environment="test"
    )
    company = uuid.UUID(gen.COMPANY_ID)
    concepts = json.loads(raw)["sources"][gen.SOURCE_ID]["companies"][gen.COMPANY_ID]["concepts"]
    assert set(concepts) == {
        "account.balance_and_turnovers",
        "accounting.posting_rows",
        "sales",
        "purchases",
        "counterparty.duplicate_candidates",
    }
    for concept in concepts:
        mapping = provider.lookup(gen.SOURCE_ID, company, concept)
        Registry.check_concept_mapping(concept, mapping)
        fingerprint = provider.profile_fingerprint(
            gen.SOURCE_ID, company, concept, mapping, prefix="test-lane-unreconciled:"
        )
        assert fingerprint.startswith("test-lane-unreconciled:")


def test_provenance_is_never_native_or_machine():
    out = profile_provenance({"profile_kind": TEST_LANE_PROFILE_KIND})
    assert out["profile_kind"] == "TEST_LANE_UNRECONCILED"
    assert out["evidence_level"] == "L1"
    assert out["native_reconciliation"] == "NOT_RUN"
    assert TEST_LANE_WARNING in out["warnings"]


def test_settings_accept_complete_test_lane_configuration():
    s = _lane(
        environment="test",
        test_lane_profiles_file="C:/x/profiles.json",
        test_lane_profiles_sha256=SHA,
        test_lane_unreconciled_sources="onec-818ha-reference",
    )
    assert s.test_lane_unreconciled_source_items == ("onec-818ha-reference",)


@pytest.mark.parametrize("environment", ["production", "staging", "development"])
def test_settings_deny_test_lane_outside_test_environment(environment):
    with pytest.raises(ValueError):
        _lane(
            environment=environment,
            test_lane_profiles_file="C:/x/profiles.json",
            test_lane_profiles_sha256=SHA,
            test_lane_unreconciled_sources="onec-818ha-reference",
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"test_lane_unreconciled_sources": "src"},
        {"test_lane_profiles_file": "C:/x/p.json", "test_lane_profiles_sha256": SHA},
        {
            "test_lane_profiles_file": "relative/p.json",
            "test_lane_profiles_sha256": SHA,
            "test_lane_unreconciled_sources": "src",
        },
        {
            "test_lane_profiles_file": "C:/x/p.json",
            "test_lane_profiles_sha256": SHA,
            "test_lane_unreconciled_sources": "Bad Id",
        },
    ],
)
def test_settings_reject_incomplete_or_invalid_test_lane_configuration(extra):
    with pytest.raises(ValueError):
        _lane(environment="test", **extra)


def test_registry_denies_test_lane_in_production():
    with pytest.raises(ValueError, match="TEST_LANE_PROFILES_FORBIDDEN_IN_PRODUCTION"):
        Registry(None, production=True, test_lane_sources=("onec-818ha-reference",))


def test_provider_refuses_a_non_test_environment_and_a_wrong_hash():
    with pytest.raises(RuntimeError, match="FORBIDDEN_ENVIRONMENT"):
        SyntheticFixtureProfiles(gen.FIXTURE_PATH, SHA, environment="production")
    with pytest.raises(RuntimeError, match="HASH_MISMATCH"):
        SyntheticFixtureProfiles(gen.FIXTURE_PATH, SHA, environment="test")
