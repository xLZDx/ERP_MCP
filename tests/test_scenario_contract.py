import json

import pytest

from scripts.validate_scenarios import SCENARIO_PATH, SEED_PATH, validate_scenario_suite


def test_accounting_scenario_pack_is_deterministic_and_does_not_claim_native_evidence():
    count, fingerprint = validate_scenario_suite()
    assert count == 10
    assert fingerprint.startswith("sha256:")
    assert validate_scenario_suite() == (count, fingerprint)


def test_scenario_pack_rejects_broken_invariant_and_claimed_native_reconciliation(tmp_path):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed["scenario_fixtures"]["account-turnover"]["closing_debit"] = 999
    seed_copy = tmp_path / "seed.json"
    seed_copy.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(ValueError, match="does not reconcile"):
        validate_scenario_suite(seed_copy, SCENARIO_PATH)

    scenarios = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    scenarios["scenarios"][0]["native_reconciliation"] = {
        "status": "PASS",
        "report_ref": "synthetic-is-not-native",
    }
    scenarios_copy = tmp_path / "scenarios.json"
    scenarios_copy.write_text(json.dumps(scenarios), encoding="utf-8")
    with pytest.raises(ValueError, match="must not claim native"):
        validate_scenario_suite(SEED_PATH, scenarios_copy)
