"""Deterministic disposition rules for the real 1C 818HA lane.

PASS can only be produced by class RR with ``oracle_match is True``, no truncation
and no error. There is no default-to-PASS path anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

PASS = "PASS"
FINDING = "FINDING"
INCONCLUSIVE = "INCONCLUSIVE"
EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
SEMANTIC_PROFILE_UNVALIDATED = "SEMANTIC_PROFILE_UNVALIDATED"
REFUSED_WRITE = "REFUSED-WRITE"
ERROR = "ERROR"

DISPOSITIONS = (
    PASS,
    FINDING,
    INCONCLUSIVE,
    EVIDENCE_REQUIRED,
    CAPABILITY_UNSUPPORTED,
    SEMANTIC_PROFILE_UNVALIDATED,
    REFUSED_WRITE,
    ERROR,
)
CATALOGUE_CLASSES = ("RR", "NP", "UG", "EV", "WD")


@dataclass(frozen=True)
class Observed:
    error: str | None = None
    profile_gate_refusal: bool | None = None
    data_returned: bool | None = None
    write_refused: bool | None = None
    write_effect_detected: bool | None = None
    capability_absent_confirmed: bool | None = None
    evidence_required_observed: bool | None = None
    oracle_match: bool | None = None
    truncated: bool = False
    evidence_classes: tuple[str, ...] = ()


def decide(catalogue_class: str, observed: Observed) -> tuple[str, str]:
    """Return ``(disposition, reason_code)`` for a catalogue class and observation."""
    if catalogue_class not in CATALOGUE_CLASSES:
        raise ValueError(f"unknown catalogue class: {catalogue_class!r}")
    o = observed
    if o.error:
        return ERROR, "error"
    if catalogue_class == "WD":
        if o.write_effect_detected is True:
            return FINDING, "write_effect_detected"
        if o.write_refused is True:
            return REFUSED_WRITE, "write_refused"
        return INCONCLUSIVE, "write_outcome_not_observed"
    if catalogue_class == "UG":
        if o.capability_absent_confirmed is True:
            return CAPABILITY_UNSUPPORTED, "capability_absent_confirmed"
        if o.capability_absent_confirmed is False:
            return FINDING, "capability_present_but_catalogued_unsupported"
        return INCONCLUSIVE, "capability_not_confirmed"
    if catalogue_class == "EV":
        if o.evidence_required_observed is True:
            return EVIDENCE_REQUIRED, "evidence_required_observed"
        if o.data_returned is True:
            return FINDING, "data_without_evidence"
        return INCONCLUSIVE, "evidence_gate_not_observed"
    if catalogue_class == "NP":
        if o.profile_gate_refusal is True:
            return SEMANTIC_PROFILE_UNVALIDATED, "profile_gate_refusal"
        if o.data_returned is True:
            return FINDING, "profile_bypass"
        return INCONCLUSIVE, "profile_gate_not_observed"
    # RR
    if o.profile_gate_refusal is True:
        return SEMANTIC_PROFILE_UNVALIDATED, "profile_gate_refusal"
    if o.truncated:
        return INCONCLUSIVE, "truncated"
    if o.oracle_match is True:
        return PASS, "oracle_match"
    if o.oracle_match is False:
        return FINDING, "oracle_mismatch"
    return INCONCLUSIVE, "oracle_not_compared"
