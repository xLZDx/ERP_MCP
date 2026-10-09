"""Phase 2 taxonomy / LDM candidate store (R2-US-013, REQ08).

Pure in-memory logic: no I/O, no wall clock, no raw exception text in results. Concepts and typed
edges are created ONLY as ``CANDIDATE`` and are always bound to a scope (tenant + company/source).
Every state change appends an immutable version; an older version and its links are never rewritten.

Guard order for ``accept`` (first failure wins, nothing is written before all pass): scope ->
edge lookup -> approver kind (HUMAN, or RULE with a policy_ref; LLM/AUTOMATION never) -> approver
identity usable -> independence from the proposer and EVERY previous proposer -> evidence_ref
non-blank -> status is CANDIDATE -> expected_previous_version (CAS).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum

from .promotion import normalize_identity

__all__ = [
    "Actor", "Concept", "EdgeKind", "EdgeVersion", "ProducerKind", "Status", "TaxOutcome",
    "TaxResult", "TaxScope", "TaxonomyStore",
]


class ProducerKind(StrEnum):
    HUMAN = "HUMAN"
    RULE = "RULE"
    LLM = "LLM"
    AUTOMATION = "AUTOMATION"


class EdgeKind(StrEnum):
    IS_A = "IS_A"
    PART_OF = "PART_OF"
    REFERENCES = "REFERENCES"
    DEPENDS_ON = "DEPENDS_ON"


class Status(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class TaxOutcome(StrEnum):
    OK = "OK"
    REJECTED_INPUT = "REJECTED_INPUT"
    REJECTED_SCOPE = "REJECTED_SCOPE"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE = "DUPLICATE"
    REJECTED_ACTOR_KIND = "REJECTED_ACTOR_KIND"
    REJECTED_SELF_APPROVAL = "REJECTED_SELF_APPROVAL"
    REJECTED_EVIDENCE = "REJECTED_EVIDENCE"
    REJECTED_CAS = "REJECTED_CAS"
    REJECTED_STATE = "REJECTED_STATE"


@dataclass(frozen=True, slots=True)
class TaxScope:
    tenant_id: str
    company_id: str


@dataclass(frozen=True, slots=True)
class Actor:
    kind: ProducerKind
    actor_id: str
    policy_ref: str = ""  # required for a RULE approver


@dataclass(frozen=True, slots=True)
class Concept:
    concept_id: str
    scope: TaxScope
    name: str
    producer: Actor
    confidence: float
    status: Status = Status.CANDIDATE


@dataclass(frozen=True, slots=True)
class EdgeVersion:
    edge_id: str
    version: int
    scope: TaxScope
    kind: EdgeKind
    source_id: str
    target_id: str
    definition: str
    producer: Actor
    confidence: float
    status: Status
    proposers: tuple[str, ...]  # normalized identities of every proposer so far
    decided_by: str = ""
    evidence_ref: str = ""


@dataclass(frozen=True, slots=True)
class TaxResult:
    outcome: TaxOutcome
    code: str = ""
    edge: EdgeVersion | None = None
    concept: Concept | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is TaxOutcome.OK


def _bad(outcome: TaxOutcome, code: str) -> TaxResult:
    return TaxResult(outcome, code)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _scope_ok(scope: object) -> bool:
    return (isinstance(scope, TaxScope) and _text(scope.tenant_id) and _text(scope.company_id))


def _scope_key(scope: TaxScope) -> tuple[str, str]:
    return (normalize_identity(scope.tenant_id), normalize_identity(scope.company_id))


def _confidence_ok(value: object) -> bool:
    return (type(value) is float or type(value) is int) and 0.0 <= value <= 1.0


def _actor_ok(actor: object) -> bool:
    return (isinstance(actor, Actor) and isinstance(actor.kind, ProducerKind)
            and bool(normalize_identity(actor.actor_id)))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


class TaxonomyStore:
    def __init__(self) -> None:
        self._concepts: dict[str, Concept] = {}
        self._edges: dict[str, list[EdgeVersion]] = {}

    # ------------------------------------------------------------------ proposals
    def propose_concept(self, scope: TaxScope, name: str, producer: Actor,
                        confidence: float) -> TaxResult:
        if not _scope_ok(scope):
            return _bad(TaxOutcome.REJECTED_SCOPE, "SCOPE_REQUIRED")
        if not _text(name) or not _actor_ok(producer) or not _confidence_ok(confidence):
            return _bad(TaxOutcome.REJECTED_INPUT, "INVALID_CONCEPT")
        cid = _stable_id("c", *_scope_key(scope), normalize_identity(name))
        if cid in self._concepts:
            return TaxResult(TaxOutcome.DUPLICATE, "CONCEPT_EXISTS", concept=self._concepts[cid])
        concept = Concept(cid, scope, name.strip(), producer, float(confidence))
        self._concepts[cid] = concept
        return TaxResult(TaxOutcome.OK, concept=concept)

    def get_concept(self, scope: TaxScope, concept_id: str) -> Concept | None:
        c = self._concepts.get(concept_id)
        if c is None or not _scope_ok(scope) or _scope_key(c.scope) != _scope_key(scope):
            return None
        return c

    def propose_edge(self, scope: TaxScope, kind: EdgeKind, source_id: str, target_id: str,
                     definition: str, producer: Actor, confidence: float) -> TaxResult:
        if not _scope_ok(scope):
            return _bad(TaxOutcome.REJECTED_SCOPE, "SCOPE_REQUIRED")
        if (not isinstance(kind, EdgeKind) or not _text(source_id) or not _text(target_id)
                or not _text(definition) or not _actor_ok(producer)
                or not _confidence_ok(confidence)):
            return _bad(TaxOutcome.REJECTED_INPUT, "INVALID_EDGE")
        if self.get_concept(scope, source_id) is None or self.get_concept(scope, target_id) is None:
            return _bad(TaxOutcome.REJECTED_SCOPE, "CONCEPT_NOT_IN_SCOPE")
        eid = _stable_id("e", *_scope_key(scope), kind.value, source_id, target_id)
        who = normalize_identity(producer.actor_id)
        versions = self._edges.get(eid)
        if versions is None:
            ev = EdgeVersion(eid, 1, scope, kind, source_id, target_id, definition.strip(),
                             producer, float(confidence), Status.CANDIDATE, (who,))
            self._edges[eid] = [ev]
            return TaxResult(TaxOutcome.OK, edge=ev)
        head = versions[-1]
        if head.status is not Status.REJECTED:
            return TaxResult(TaxOutcome.DUPLICATE, "EDGE_EXISTS", edge=head)
        # a rejected edge needs a NEW proposal: new version, back to CANDIDATE, proposers accumulate
        ev = EdgeVersion(eid, head.version + 1, scope, kind, source_id, target_id,
                         definition.strip(), producer, float(confidence), Status.CANDIDATE,
                         head.proposers if who in head.proposers else head.proposers + (who,))
        versions.append(ev)
        return TaxResult(TaxOutcome.OK, edge=ev)

    # ------------------------------------------------------------------ decisions
    def _head(self, scope: TaxScope, edge_id: str) -> EdgeVersion | TaxResult:
        if not _scope_ok(scope):
            return _bad(TaxOutcome.REJECTED_SCOPE, "SCOPE_REQUIRED")
        versions = self._edges.get(edge_id)
        if not versions or _scope_key(versions[0].scope) != _scope_key(scope):
            return _bad(TaxOutcome.NOT_FOUND, "EDGE_NOT_FOUND")
        return versions[-1]

    def accept(self, scope: TaxScope, edge_id: str, approver: Actor, evidence_ref: str,
               expected_previous_version: int) -> TaxResult:
        head = self._head(scope, edge_id)
        if isinstance(head, TaxResult):
            return head
        if not _actor_ok(approver):
            return _bad(TaxOutcome.REJECTED_INPUT, "INVALID_APPROVER")
        if approver.kind not in (ProducerKind.HUMAN, ProducerKind.RULE):
            return _bad(TaxOutcome.REJECTED_ACTOR_KIND, "ACTOR_CANNOT_ACCEPT")
        if approver.kind is ProducerKind.RULE and not _text(approver.policy_ref):
            return _bad(TaxOutcome.REJECTED_ACTOR_KIND, "RULE_POLICY_REQUIRED")
        if normalize_identity(approver.actor_id) in head.proposers:
            return _bad(TaxOutcome.REJECTED_SELF_APPROVAL, "APPROVER_NOT_INDEPENDENT")
        if not _text(evidence_ref):
            return _bad(TaxOutcome.REJECTED_EVIDENCE, "EVIDENCE_REQUIRED")
        if head.status is not Status.CANDIDATE:
            return _bad(TaxOutcome.REJECTED_STATE, "NOT_A_CANDIDATE")
        if type(expected_previous_version) is not int or expected_previous_version != head.version:
            return _bad(TaxOutcome.REJECTED_CAS, "STALE_VERSION")
        new = replace(head, version=head.version + 1, status=Status.ACCEPTED,
                      decided_by=normalize_identity(approver.actor_id),
                      evidence_ref=evidence_ref.strip())
        self._edges[edge_id].append(new)
        return TaxResult(TaxOutcome.OK, edge=new)

    def reject(self, scope: TaxScope, edge_id: str, rejecter: Actor, evidence_ref: str,
               expected_previous_version: int) -> TaxResult:
        head = self._head(scope, edge_id)
        if isinstance(head, TaxResult):
            return head
        if not _actor_ok(rejecter):
            return _bad(TaxOutcome.REJECTED_INPUT, "INVALID_APPROVER")
        if rejecter.kind not in (ProducerKind.HUMAN, ProducerKind.RULE):
            return _bad(TaxOutcome.REJECTED_ACTOR_KIND, "ACTOR_CANNOT_REJECT")
        if rejecter.kind is ProducerKind.RULE and not _text(rejecter.policy_ref):
            return _bad(TaxOutcome.REJECTED_ACTOR_KIND, "RULE_POLICY_REQUIRED")
        if not _text(evidence_ref):
            return _bad(TaxOutcome.REJECTED_EVIDENCE, "EVIDENCE_REQUIRED")
        if head.status is not Status.CANDIDATE:
            return _bad(TaxOutcome.REJECTED_STATE, "NOT_A_CANDIDATE")
        if type(expected_previous_version) is not int or expected_previous_version != head.version:
            return _bad(TaxOutcome.REJECTED_CAS, "STALE_VERSION")
        new = replace(head, version=head.version + 1, status=Status.REJECTED,
                      decided_by=normalize_identity(rejecter.actor_id),
                      evidence_ref=evidence_ref.strip())
        self._edges[edge_id].append(new)
        return TaxResult(TaxOutcome.OK, edge=new)

    def supersede_semantics(self, scope: TaxScope, edge_id: str, new_definition: str,
                            proposer: Actor, confidence: float,
                            expected_previous_version: int) -> TaxResult:
        """New semantic version (back to CANDIDATE); the old version stays readable, untouched."""
        head = self._head(scope, edge_id)
        if isinstance(head, TaxResult):
            return head
        if not _text(new_definition) or not _actor_ok(proposer) or not _confidence_ok(confidence):
            return _bad(TaxOutcome.REJECTED_INPUT, "INVALID_SUPERSEDE")
        if head.status is Status.REJECTED:
            return _bad(TaxOutcome.REJECTED_STATE, "REJECTED_NEEDS_NEW_PROPOSAL")
        if type(expected_previous_version) is not int or expected_previous_version != head.version:
            return _bad(TaxOutcome.REJECTED_CAS, "STALE_VERSION")
        who = normalize_identity(proposer.actor_id)
        new = replace(head, version=head.version + 1, definition=new_definition.strip(),
                      producer=proposer, confidence=float(confidence), status=Status.CANDIDATE,
                      proposers=head.proposers if who in head.proposers else head.proposers + (who,),
                      decided_by="", evidence_ref="")
        self._edges[edge_id].append(new)
        return TaxResult(TaxOutcome.OK, edge=new)

    # ------------------------------------------------------------------ queries
    def edges_in_scope(self, scope: TaxScope) -> tuple[EdgeVersion, ...]:
        """Current (head) version of every edge in exactly this scope; empty for an invalid scope."""
        if not _scope_ok(scope):
            return ()
        key = _scope_key(scope)
        return tuple(v[-1] for v in self._edges.values() if _scope_key(v[0].scope) == key)

    def versions(self, scope: TaxScope, edge_id: str) -> tuple[EdgeVersion, ...]:
        if not _scope_ok(scope):
            return ()
        vs = self._edges.get(edge_id)
        if not vs or _scope_key(vs[0].scope) != _scope_key(scope):
            return ()
        return tuple(vs)

    def get_version(self, scope: TaxScope, edge_id: str, version: int) -> EdgeVersion | None:
        for v in self.versions(scope, edge_id):
            if v.version == version:
                return v
        return None
