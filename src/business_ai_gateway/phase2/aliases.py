"""Phase 2 supplier alias resolver (R2-US-014): pure in-memory, no I/O, no wall clock.

Rules
- Every entity and alias lives in exactly one scope (tenant_id + company_id). Resolution never
  crosses a scope: the same display name in two companies/tenants is two entities.
- RESOLVED needs an EXACT namespaced reference match (compared after trimming only, case-sensitive,
  never fuzzy) inside the queried scope and exactly one matching entity.
- Two or more candidates -> AMBIGUOUS: the candidate ids are returned and ONE resolution-queue item
  is created (repeated resolves reuse it). The resolver never picks and never merges.
- Display-name similarity (NFKC + casefold + trim) can only fill ``suggestions`` / make a queue
  item; it never produces RESOLVED.
- ``resolve_ambiguity`` is the only way a human decision is recorded. It needs a non-blank HUMAN
  approver, is idempotent for the same choice, refuses a conflicting second choice, and only
  records who/when (injected clock). It does not merge entities or touch aliases.
- Result codes are fixed constants; caller-supplied text is never echoed into them.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

__all__ = [
    "ActorKind", "AliasOutcome", "AliasRecord", "AliasResolver", "AliasScope", "Approver",
    "Decision", "DecisionResult", "QueueItem", "Reference", "ResolutionResult", "ResolveQuery",
    "SupplierEntity", "normalize_name",
]


class AliasOutcome(StrEnum):
    RESOLVED = "RESOLVED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    REJECTED_INPUT = "REJECTED_INPUT"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    DECIDED = "DECIDED"
    REJECTED_APPROVER = "REJECTED_APPROVER"
    REJECTED_CHOICE = "REJECTED_CHOICE"
    REJECTED_CONFLICT = "REJECTED_CONFLICT"
    UNKNOWN_ITEM = "UNKNOWN_ITEM"
    OK = "OK"


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    AUTOMATION = "AUTOMATION"


def normalize_name(value: object) -> str:
    """NFKC + casefold + trim for display names; '' means unusable."""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _trim(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True, slots=True)
class AliasScope:
    tenant_id: str
    company_id: str

    def valid(self) -> bool:
        return (isinstance(self.tenant_id, str) and isinstance(self.company_id, str)
                and bool(self.tenant_id.strip()) and bool(self.company_id.strip()))

    def key(self) -> tuple[str, str]:
        return (self.tenant_id.strip(), self.company_id.strip())


@dataclass(frozen=True, slots=True)
class Reference:
    """Namespaced external reference (e.g. namespace 'tax_id' / 'erp_code'); compared exactly."""
    namespace: str
    value: str

    def valid(self) -> bool:
        return bool(_trim(self.namespace)) and bool(_trim(self.value))

    def key(self) -> tuple[str, str]:
        return (_trim(self.namespace), _trim(self.value))


@dataclass(frozen=True, slots=True)
class SupplierEntity:
    entity_id: str
    scope: AliasScope
    canonical_name: str
    references: tuple[Reference, ...] = ()


@dataclass(frozen=True, slots=True)
class AliasRecord:
    """Extra alias of an entity: a display-name alias and/or a reference, with provenance."""
    entity_id: str
    scope: AliasScope
    provenance: str
    alias_text: str = ""
    reference: Reference | None = None


@dataclass(frozen=True, slots=True)
class ResolveQuery:
    reference: Reference | None = None
    name: str = ""


@dataclass(frozen=True, slots=True)
class Approver:
    identity: str
    kind: ActorKind


@dataclass(frozen=True, slots=True)
class Decision:
    chosen_entity_id: str
    approver: str
    reason: str
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class QueueItem:
    item_id: str
    scope: AliasScope
    candidate_ids: tuple[str, ...]
    suggestions: tuple[str, ...]
    decision: Decision | None = None


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    outcome: AliasOutcome
    entity_id: str | None = None
    candidate_ids: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    queue_item_id: str | None = None
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in (AliasOutcome.RESOLVED, AliasOutcome.OK)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    outcome: AliasOutcome
    decision: Decision | None = None
    replay: bool = False
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is AliasOutcome.DECIDED


@dataclass(slots=True)
class AliasResolver:
    clock: Callable[[], datetime]
    _entities: dict[str, SupplierEntity] = field(default_factory=dict)
    _aliases: list[AliasRecord] = field(default_factory=list)
    _queue: dict[str, QueueItem] = field(default_factory=dict)

    # -- registration -------------------------------------------------------------------------
    def add_entity(self, entity: SupplierEntity) -> ResolutionResult:
        if not isinstance(entity.scope, AliasScope) or not entity.scope.valid():
            return ResolutionResult(AliasOutcome.SCOPE_VIOLATION, code="SCOPE_INVALID")
        if (not _trim(entity.entity_id) or not normalize_name(entity.canonical_name)
                or not all(isinstance(r, Reference) and r.valid() for r in entity.references)):
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ENTITY_INVALID")
        if entity.entity_id in self._entities:
            return ResolutionResult(AliasOutcome.REJECTED_DUPLICATE, code="ENTITY_EXISTS")
        self._entities[entity.entity_id] = entity
        return ResolutionResult(AliasOutcome.OK, entity_id=entity.entity_id)

    def add_alias(self, alias: AliasRecord) -> ResolutionResult:
        if not isinstance(alias.scope, AliasScope) or not alias.scope.valid():
            return ResolutionResult(AliasOutcome.SCOPE_VIOLATION, code="SCOPE_INVALID")
        ent = self._entities.get(alias.entity_id)
        if ent is None:
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ENTITY_UNKNOWN")
        if ent.scope.key() != alias.scope.key():
            return ResolutionResult(AliasOutcome.SCOPE_VIOLATION, code="ALIAS_SCOPE_MISMATCH")
        has_text = bool(normalize_name(alias.alias_text))
        has_ref = alias.reference is not None and alias.reference.valid()
        if (not has_text and not has_ref) or not _trim(alias.provenance) or (
                alias.reference is not None and not alias.reference.valid()):
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ALIAS_INVALID")
        self._aliases.append(alias)
        return ResolutionResult(AliasOutcome.OK, entity_id=alias.entity_id)

    # -- resolution ---------------------------------------------------------------------------
    def resolve(self, scope: AliasScope, query: ResolveQuery) -> ResolutionResult:
        if not isinstance(scope, AliasScope) or not scope.valid():
            return ResolutionResult(AliasOutcome.SCOPE_VIOLATION, code="SCOPE_INVALID")
        skey = scope.key()
        in_scope = [e for e in self._entities.values() if e.scope.key() == skey]
        ref = query.reference
        if ref is not None and not ref.valid():
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="REFERENCE_INVALID")
        ref_hits: set[str] = set()
        if ref is not None:
            rk = ref.key()
            for e in in_scope:
                if any(r.key() == rk for r in e.references):
                    ref_hits.add(e.entity_id)
            for a in self._aliases:
                if a.scope.key() == skey and a.reference is not None and a.reference.key() == rk:
                    ref_hits.add(a.entity_id)
        name_hits = self._name_hits(skey, in_scope, query.name)
        if len(ref_hits) == 1:
            return ResolutionResult(AliasOutcome.RESOLVED, entity_id=next(iter(ref_hits)))
        if len(ref_hits) >= 2:
            return self._ambiguous(scope, ref_hits, name_hits)
        # no reference match: names alone can only suggest, never resolve
        if len(name_hits) >= 2:
            return self._ambiguous(scope, name_hits, name_hits)
        return ResolutionResult(AliasOutcome.NOT_FOUND, suggestions=tuple(sorted(name_hits)),
                                code="NO_EXACT_REFERENCE")

    def _name_hits(self, skey: tuple[str, str], in_scope: list[SupplierEntity],
                   name: str) -> set[str]:
        n = normalize_name(name)
        if not n:
            return set()
        hits = {e.entity_id for e in in_scope if normalize_name(e.canonical_name) == n}
        for a in self._aliases:
            if a.scope.key() == skey and normalize_name(a.alias_text) == n:
                hits.add(a.entity_id)
        return hits

    def _ambiguous(self, scope: AliasScope, candidates: set[str],
                   suggestions: set[str]) -> ResolutionResult:
        cands = tuple(sorted(candidates))
        digest = hashlib.sha256(
            "\x1f".join([*scope.key(), *cands]).encode("utf-8")).hexdigest()[:24]
        item_id = f"RQ-{digest}"
        if item_id not in self._queue:
            self._queue[item_id] = QueueItem(item_id, scope, cands,
                                             tuple(sorted(suggestions - candidates)))
        return ResolutionResult(AliasOutcome.AMBIGUOUS, candidate_ids=cands, queue_item_id=item_id,
                                code="AMBIGUOUS_CANDIDATES")

    # -- queue / human decision ---------------------------------------------------------------
    def queue_items(self) -> tuple[QueueItem, ...]:
        return tuple(self._queue.values())

    def resolve_ambiguity(self, item_id: str, chosen_entity_id: str, approver: Approver,
                          reason: str) -> DecisionResult:
        item = self._queue.get(item_id) if isinstance(item_id, str) else None
        if item is None:
            return DecisionResult(AliasOutcome.UNKNOWN_ITEM, code="ITEM_UNKNOWN")
        if (not isinstance(approver, Approver) or approver.kind is not ActorKind.HUMAN
                or not normalize_name(approver.identity)):
            return DecisionResult(AliasOutcome.REJECTED_APPROVER, code="APPROVER_NOT_HUMAN")
        if not _trim(reason):
            return DecisionResult(AliasOutcome.REJECTED_INPUT, code="REASON_REQUIRED")
        if chosen_entity_id not in item.candidate_ids:
            return DecisionResult(AliasOutcome.REJECTED_CHOICE, code="CHOICE_NOT_CANDIDATE")
        if item.decision is not None:
            if item.decision.chosen_entity_id == chosen_entity_id:
                return DecisionResult(AliasOutcome.DECIDED, item.decision, replay=True)
            return DecisionResult(AliasOutcome.REJECTED_CONFLICT, code="DECISION_CONFLICT")
        decision = Decision(chosen_entity_id, approver.identity.strip(), reason.strip(),
                            self.clock())
        self._queue[item_id] = QueueItem(item.item_id, item.scope, item.candidate_ids,
                                         item.suggestions, decision)
        return DecisionResult(AliasOutcome.DECIDED, decision)
