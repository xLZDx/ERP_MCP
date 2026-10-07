import pytest

from testbed.ferma_onec.reconcile import Observation, reconcile


def observation(plane, **changes):
    values = {"plane": plane, "test_level": "L1", "scenario_id": "fixture", "run_id": "run",
              "source_id": "synthetic", "company_id": "A", "period": "2026-01",
              "currency": "MDL", "metadata_fingerprint": "a" * 64,
              "profile_fingerprint": "b" * 64, "origin_ref": f"fixture-{plane}",
              "measurements": {"receivable": "100.00"}}
    return Observation.model_validate({**values, **changes})


def test_independent_three_plane_comparison_preserves_discrepancy():
    policy = {"receivable": "0.01"}
    native, actual, oracle = (observation(plane) for plane in ("native", "erp_mcp", "ferma"))
    result = reconcile(native, actual, oracle, tolerances=policy)
    assert result["status"] == "PASS" and result["test_level"] == "L1"
    assert result["production_approval"] is False
    wrong = observation("erp_mcp", measurements={"receivable": "101.00"})
    assert reconcile(native, wrong, oracle, tolerances=policy)["status"] == "FINDING"
    assert oracle.measurements == {"receivable": "100.00"}


@pytest.mark.parametrize("change", [
    {"company_id": "B"}, {"period": "2026-02"}, {"currency": "EUR"},
    {"test_level": "L2-A"}, {"metadata_fingerprint": "c" * 64},
    {"origin_ref": "fixture-native"}, {"truncated": True},
    {"measurements": {"other": "100.00"}},
])
def test_mismatched_or_incomplete_observations_never_pass(change):
    assert reconcile(observation("native"), observation("erp_mcp", **change),
                     tolerances={"receivable": "0.01"})["status"] == "INCONCLUSIVE"


def test_missing_native_report_is_evidence_required():
    assert reconcile(None, observation("erp_mcp"), tolerances={})["status"] == "EVIDENCE_REQUIRED"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "x", "1" * 100])
def test_invalid_decimal_observations_are_rejected(amount):
    with pytest.raises(ValueError):
        observation("native", measurements={"receivable": amount})
