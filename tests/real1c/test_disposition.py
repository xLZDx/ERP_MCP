from __future__ import annotations

import itertools

import pytest

from scripts.real1c import disposition as d
from scripts.real1c.disposition import Observed, decide


@pytest.mark.parametrize(
    ("cls", "obs", "expected"),
    [
        (
            "WD",
            Observed(write_effect_detected=True, write_refused=True),
            (d.FINDING, "write_effect_detected"),
        ),
        ("WD", Observed(write_refused=True), (d.REFUSED_WRITE, "write_refused")),
        ("WD", Observed(), (d.INCONCLUSIVE, "write_outcome_not_observed")),
        (
            "UG",
            Observed(capability_absent_confirmed=True),
            (d.CAPABILITY_UNSUPPORTED, "capability_absent_confirmed"),
        ),
        (
            "UG",
            Observed(capability_absent_confirmed=False),
            (d.FINDING, "capability_present_but_catalogued_unsupported"),
        ),
        ("UG", Observed(), (d.INCONCLUSIVE, "capability_not_confirmed")),
        (
            "EV",
            Observed(evidence_required_observed=True, data_returned=True),
            (d.EVIDENCE_REQUIRED, "evidence_required_observed"),
        ),
        ("EV", Observed(data_returned=True), (d.FINDING, "data_without_evidence")),
        ("EV", Observed(), (d.INCONCLUSIVE, "evidence_gate_not_observed")),
        (
            "NP",
            Observed(profile_gate_refusal=True, data_returned=True),
            (d.SEMANTIC_PROFILE_UNVALIDATED, "profile_gate_refusal"),
        ),
        ("NP", Observed(data_returned=True), (d.FINDING, "profile_bypass")),
        ("NP", Observed(), (d.INCONCLUSIVE, "profile_gate_not_observed")),
        (
            "RR",
            Observed(profile_gate_refusal=True, oracle_match=True),
            (d.SEMANTIC_PROFILE_UNVALIDATED, "profile_gate_refusal"),
        ),
        ("RR", Observed(truncated=True, oracle_match=True), (d.INCONCLUSIVE, "truncated")),
        ("RR", Observed(oracle_match=True), (d.PASS, "oracle_match")),
        ("RR", Observed(oracle_match=False), (d.FINDING, "oracle_mismatch")),
        ("RR", Observed(), (d.INCONCLUSIVE, "oracle_not_compared")),
        ("RR", Observed(data_returned=True), (d.INCONCLUSIVE, "oracle_not_compared")),
    ],
)
def test_decide_rules(cls, obs, expected):
    assert decide(cls, obs) == expected


@pytest.mark.parametrize("cls", ["RR", "NP", "UG", "EV", "WD"])
def test_error_takes_precedence(cls):
    obs = Observed(error="boom", oracle_match=True, write_refused=True,
                   capability_absent_confirmed=True, evidence_required_observed=True,
                   profile_gate_refusal=True)  # fmt: skip
    assert decide(cls, obs) == (d.ERROR, "error")


def test_unknown_class_raises():
    with pytest.raises(ValueError):
        decide("XX", Observed(oracle_match=True))


def test_exact_disposition_strings():
    assert d.REFUSED_WRITE == "REFUSED-WRITE"
    assert len(set(d.DISPOSITIONS)) == 8


def test_pass_only_from_rr_with_oracle_match_true_exhaustive():
    tri = (None, True, False)
    for cls in ("RR", "NP", "UG", "EV", "WD"):
        for err, gate, data, wr, we, cap, evr, orc, trunc in itertools.product(
            (None, "e"), tri, tri, tri, tri, tri, tri, tri, (False, True)
        ):
            obs = Observed(error=err, profile_gate_refusal=gate, data_returned=data,
                           write_refused=wr, write_effect_detected=we,
                           capability_absent_confirmed=cap, evidence_required_observed=evr,
                           oracle_match=orc, truncated=trunc)  # fmt: skip
            disp, _ = decide(cls, obs)
            if disp == d.PASS:
                assert (
                    cls == "RR" and orc is True and not trunc and err is None and gate is not True
                )
