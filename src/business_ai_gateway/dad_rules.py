"""Versioned internal DAD evidence-comparison rules; no transport/query or native format inference."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from .external_evidence import (
    EvidenceClass,
    EvidenceFact,
    EvidenceRejected,
    EvidenceScope,
    ExternalEvidence,
    require_evidence,
)


@dataclass(frozen=True, slots=True)
class ReconciliationRule:
    rule_id: str
    pack_id: str
    pack_version: str
    scope: EvidenceScope
    evidence_class: EvidenceClass
    semantic_concept: str
    effective_from: date
    effective_until: date
    absolute_tolerance: Decimal = Decimal(0)
    human_review_required: bool = True

    def fingerprint(self) -> str:
        self.scope.validate()
        if (any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
                for value in (self.rule_id, self.pack_id, self.pack_version, self.semantic_concept))
                or not isinstance(self.evidence_class, EvidenceClass)
                or type(self.effective_from) is not date or type(self.effective_until) is not date
                or not self.effective_from <= self.scope.period_start < self.scope.period_end <= self.effective_until
                or not isinstance(self.absolute_tolerance, Decimal) or not self.absolute_tolerance.is_finite()
                or self.absolute_tolerance < 0 or self.absolute_tolerance > Decimal(1)
                or self.absolute_tolerance.as_tuple().exponent < -6
                or self.human_review_required is not True):
            raise ValueError("DAD_RULE_INVALID")
        fields = {"rule": self.rule_id, "pack": self.pack_id, "version": self.pack_version,
                  "scope": self.scope.fingerprint(), "class": self.evidence_class.value,
                  "semantic_concept": self.semantic_concept, "effective_from": str(self.effective_from),
                  "effective_until": str(self.effective_until), "tolerance": str(self.absolute_tolerance),
                  "human_review_required": True}
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SemanticObservation:
    scope: EvidenceScope
    semantic_concept: str
    facts: tuple[EvidenceFact, ...]
    complete: bool
    semantic_profile_confirmed: bool
    artifact_sha256: str
    evidence_level: str  # preserved, never elevated by this evaluator


def _valid_facts(facts, scope):
    if not isinstance(facts, tuple) or len(facts) > 2000:
        return False
    seen = set()
    for fact in facts:
        if (not isinstance(fact, EvidenceFact) or not isinstance(fact.key, str) or not fact.key
                or len(fact.key) > 128 or any(ord(character) < 32 or ord(character) == 127 for character in fact.key)
                or fact.key in seen or type(fact.business_date) is not date
                or not scope.period_start <= fact.business_date < scope.period_end
                or fact.currency != scope.currency or not isinstance(fact.amount, Decimal)
                or not fact.amount.is_finite() or fact.amount.copy_abs() >= Decimal("1e28")
                or fact.amount.as_tuple().exponent < -6):
            return False
        seen.add(fact.key)
    return True


def evaluate_reconciliation(
    rule: ReconciliationRule, *, validated_rules: frozenset[str],
    external: tuple[ExternalEvidence, ...], validated_evidence_profiles: frozenset[str],
    observation: SemanticObservation | None, validated_semantic_scopes: frozenset[str],
) -> dict:
    """Trusted internal inputs only. Not exposed as an AI-authored query or public upload tool."""
    fingerprint = rule.fingerprint()
    level = observation.evidence_level if observation is not None else None
    safe_level = level if type(level) is str and level in {"L1", "L2-A", "L2-B", "L3"} else None
    result = {"rule_id": rule.rule_id, "pack_id": rule.pack_id, "pack_version": rule.pack_version,
              "rule_fingerprint": fingerprint, "scope_fingerprint": rule.scope.fingerprint(),
              "status": "INCONCLUSIVE", "reason": "RULE_UNCONFIRMED", "findings": [],
              "human_review_required": True, "native_approval_inferred": False,
              "evidence_level": safe_level}
    if fingerprint not in validated_rules:
        return result
    try:
        require_evidence(frozenset({rule.evidence_class}), external, scope=rule.scope,
                         validated_profiles=validated_evidence_profiles)
    except EvidenceRejected as failure:
        result.update(status="EVIDENCE_REQUIRED" if str(failure) == "EVIDENCE_REQUIRED" else "INCONCLUSIVE",
                      reason=str(failure))
        return result
    if observation is None:
        result.update(reason="SEMANTIC_OBSERVATION_REQUIRED")
        return result
    if (observation.semantic_profile_confirmed is not True
            or rule.scope.fingerprint() not in validated_semantic_scopes):
        result.update(status="CAPABILITY_UNSUPPORTED", reason="SEMANTIC_PROFILE_UNCONFIRMED")
        return result
    if (observation.scope != rule.scope or observation.semantic_concept != rule.semantic_concept
            or observation.complete is not True or safe_level is None
            or not isinstance(observation.artifact_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", observation.artifact_sha256)
            or not _valid_facts(observation.facts, rule.scope)):
        result.update(reason="SEMANTIC_OBSERVATION_INCOMPLETE_OR_SCOPE_MISMATCH")
        return result
    documents = [item for item in external if item.evidence_class == rule.evidence_class]
    if len(documents) != 1 or not _valid_facts(documents[0].facts, rule.scope):
        result.update(reason="EXTERNAL_EVIDENCE_AMBIGUOUS_OR_INVALID")
        return result
    document = documents[0]
    if document.document_sha256 == observation.artifact_sha256:
        result.update(reason="OBSERVATION_PLANES_NOT_INDEPENDENT")
        return result
    actual = {fact.key: fact for fact in observation.facts}
    evidence = {fact.key: fact for fact in document.facts}
    for key in sorted(set(actual) | set(evidence)):
        left, right = actual.get(key), evidence.get(key)
        reason = "SEMANTIC_ITEM_MISSING" if left is None else "EXTERNAL_ITEM_MISSING" if right is None else None
        if left is not None and right is not None:
            if left.business_date != right.business_date:
                reason = "BUSINESS_DATE_MISMATCH"
            else:
                with localcontext() as context:
                    context.prec = 80  # retain exact micro-unit differences near 28-digit boundaries
                    if abs(left.amount - right.amount) > rule.absolute_tolerance:
                        reason = "AMOUNT_MISMATCH"
        if reason:
            result["findings"].append({"key_sha256": hashlib.sha256(key.encode()).hexdigest(), "reason": reason})
    result.update(status="FINDING" if result["findings"] else "PASS", reason="VALIDATED_NORMALIZED_COMPARISON",
                  semantic_artifact_sha256=observation.artifact_sha256,
                  external_artifact_sha256=document.document_sha256)
    return result
