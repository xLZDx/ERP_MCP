from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from business_ai_gateway.dad_rules import (
    ReconciliationRule,
    SemanticObservation,
    evaluate_reconciliation,
)
from business_ai_gateway.external_evidence import EvidenceClass, EvidenceFact
from tests.test_external_evidence import parse, scope


def fixture(evidence_class=EvidenceClass.BANK_STATEMENT):
    from business_ai_gateway.external_evidence import EvidenceParserProfile

    profile = EvidenceParserProfile("fixture", "v1", evidence_class, scope())
    document = parse(b"key,date,currency,amount\nprivate-business-key,2026-01-12,MDL,12.340000\n", candidate=profile)
    rule = ReconciliationRule("DAD-FIXTURE", "FIXTURE-PACK", "v1", scope(), evidence_class,
                              "cash.movements", date(2026, 1, 1), date(2026, 2, 1))
    observation = SemanticObservation(scope(), "cash.movements", document.facts, True, True, "c" * 64, "L1")
    return rule, document, observation


def evaluate(rule, document, observation, **overrides):
    args = {"validated_rules": frozenset({rule.fingerprint()}), "external": (document,),
            "validated_evidence_profiles": frozenset({document.profile_fingerprint}),
            "observation": observation, "validated_semantic_scopes": frozenset({rule.scope.fingerprint()})}
    args.update(overrides)
    return evaluate_reconciliation(rule, **args)


@pytest.mark.parametrize("evidence_class", [EvidenceClass.Z_REPORT, EvidenceClass.TERMINAL_REPORT, EvidenceClass.BANK_STATEMENT])
def test_confirmed_scoped_normalized_comparison_passes_without_native_level_upgrade(evidence_class):
    rule, document, observation = fixture(evidence_class)
    result = evaluate(rule, document, observation)
    assert result["status"] == "PASS" and result["evidence_level"] == "L1"
    assert result["human_review_required"] is True and result["native_approval_inferred"] is False
    assert "private-business-key" not in str(result) and "synthetic-company" not in str(result)


@pytest.mark.parametrize("mutation,status", [("rule", "INCONCLUSIVE"), ("external", "EVIDENCE_REQUIRED"),
    ("profile", "INCONCLUSIVE"), ("semantic_registry", "CAPABILITY_UNSUPPORTED"),
    ("semantic_flag", "CAPABILITY_UNSUPPORTED"), ("missing_observation", "INCONCLUSIVE"),
    ("truncated", "INCONCLUSIVE"), ("cross_company", "INCONCLUSIVE"), ("same_plane", "INCONCLUSIVE")])
def test_missing_unconfirmed_or_cross_scope_evidence_never_guesses_pass(mutation, status):
    rule, document, observation = fixture()
    overrides = {}
    if mutation == "rule":
        overrides["validated_rules"] = frozenset()
    elif mutation == "external":
        overrides["external"] = ()
    elif mutation == "profile":
        overrides["validated_evidence_profiles"] = frozenset()
    elif mutation == "semantic_registry":
        overrides["validated_semantic_scopes"] = frozenset()
    elif mutation == "semantic_flag":
        observation = replace(observation, semantic_profile_confirmed=False)
    elif mutation == "missing_observation":
        observation = None
    elif mutation == "truncated":
        observation = replace(observation, complete=False)
    elif mutation == "cross_company":
        observation = replace(observation, scope=replace(scope(), company_id="other"))
    else:
        observation = replace(observation, artifact_sha256=document.document_sha256)
    assert evaluate(rule, document, observation, **overrides)["status"] == status


@pytest.mark.parametrize("mutation,reason", [("amount", "AMOUNT_MISMATCH"), ("date", "BUSINESS_DATE_MISMATCH"),
                                           ("missing", "SEMANTIC_ITEM_MISSING"), ("extra", "EXTERNAL_ITEM_MISSING")])
def test_mismatches_enumerate_minimized_findings(mutation, reason):
    rule, document, observation = fixture()
    fact = observation.facts[0]
    facts = (replace(fact, amount=Decimal("12.35")),) if mutation == "amount" else (
        (replace(fact, business_date=date(2026, 1, 13)),) if mutation == "date" else () if mutation == "missing"
        else (*observation.facts, replace(fact, key="private-extra-key")))
    result = evaluate(rule, document, replace(observation, facts=facts))
    assert result["status"] == "FINDING" and result["findings"][0]["reason"] == reason
    assert "private" not in str(result) and "12.35" not in str(result)


def test_decimal_comparison_preserves_micro_difference_at_large_magnitudes():
    rule, document, observation = fixture()
    left = EvidenceFact("private-business-key", date(2026, 1, 12), "MDL", Decimal("9999999999999999999999999999.000001"))
    right = replace(left, amount=Decimal("9999999999999999999999999999.000002"))
    result = evaluate(rule, replace(document, facts=(right,)), replace(observation, facts=(left,)))
    assert result["status"] == "FINDING" and result["findings"][0]["reason"] == "AMOUNT_MISMATCH"


@pytest.mark.parametrize("change", ["version", "effective_period", "tolerance", "human_review"])
def test_rule_applicability_is_versioned_and_invalid_policy_is_rejected(change):
    rule, document, observation = fixture()
    if change == "version":
        updated = replace(rule, pack_version="v2")
        assert evaluate(updated, document, observation, validated_rules=frozenset({rule.fingerprint()}))["status"] == "INCONCLUSIVE"
        return
    updated = replace(rule, effective_until=date(2026, 1, 20)) if change == "effective_period" else (
        replace(rule, absolute_tolerance=Decimal("NaN")) if change == "tolerance" else replace(rule, human_review_required=False))
    with pytest.raises(ValueError, match="DAD_RULE_INVALID"):
        updated.fingerprint()


@pytest.mark.parametrize("mutation", ["duplicate", "nonfinite", "wrong_currency", "out_of_period",
    "invalid_key", "too_precise", "huge", "wrong_concept", "unknown_level", "bad_digest"])
def test_invalid_observation_is_inconclusive_not_business_pass(mutation):
    rule, document, observation = fixture()
    fact = observation.facts[0]
    changes = {"duplicate": {"facts": (fact, fact)},
               "nonfinite": {"facts": (replace(fact, amount=Decimal("NaN")),)},
               "wrong_currency": {"facts": (replace(fact, currency="USD"),)},
               "out_of_period": {"facts": (replace(fact, business_date=date(2026, 2, 1)),)},
               "invalid_key": {"facts": (replace(fact, key="private\x00key"),)},
               "too_precise": {"facts": (replace(fact, amount=Decimal("1.0000001")),)},
               "huge": {"facts": (replace(fact, amount=Decimal("1e1000")),)},
               "wrong_concept": {"semantic_concept": "unconfirmed.concept"},
               "unknown_level": {"evidence_level": "UNKNOWN"}, "bad_digest": {"artifact_sha256": "invalid"}}
    assert evaluate(rule, document, replace(observation, **changes[mutation]))["status"] == "INCONCLUSIVE"


def test_two_external_documents_of_same_class_are_not_silently_netted_or_selected():
    rule, document, observation = fixture()
    assert evaluate(rule, document, observation, external=(document, document))["status"] == "INCONCLUSIVE"


def test_explicit_tolerance_and_pack_fingerprint_change_are_honored():
    rule, document, observation = fixture()
    tolerant = replace(rule, absolute_tolerance=Decimal("0.01"))
    observation = replace(observation, facts=(replace(observation.facts[0], amount=Decimal("12.35")),))
    assert evaluate(tolerant, document, observation)["status"] == "PASS"
    assert evaluate(rule, document, observation)["status"] == "FINDING"
    assert tolerant.fingerprint() != rule.fingerprint()


@pytest.mark.parametrize("level", ["private-token-or-document-text", ["private-secret"], {"private": "payload"}, 1, None])
def test_invalid_evidence_level_is_not_echoed_even_on_early_rule_rejection(level):
    rule, document, observation = fixture()
    observation = replace(observation, evidence_level=level)
    for approved in (frozenset(), frozenset({rule.fingerprint()})):
        result = evaluate(rule, document, observation, validated_rules=approved)
        assert result["status"] == "INCONCLUSIVE" and result["evidence_level"] is None
        assert "private" not in str(result)
