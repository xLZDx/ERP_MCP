"""Phase 2 supplier alias resolver (R2-US-014): pure in-memory, no I/O, no wall clock.

Rules
- Every entity and alias lives in exactly one scope (tenant_id + company_id). Resolution never
  crosses a scope: the same display name in two companies/tenants is two entities. Entities are
  keyed by (scope, entity_id), so the same entity_id may exist in several scopes and registering
  one never reveals whether another scope uses it.
- Scope parts are normalised exactly like the taxonomy module (NFKC + casefold + strip); any
  control / format / separator / blank-glyph character makes an identity invalid (see ``_identity``).
- RESOLVED needs an EXACT namespaced reference match (compared after trimming only, case-sensitive,
  never fuzzy) inside the queried scope and exactly one matching entity.
- Two or more candidates -> AMBIGUOUS: the candidate ids are returned and ONE resolution-queue item
  is created (repeated resolves reuse it). The resolver never picks and never merges.
- Display-name similarity (NFKC + casefold + trim) can only fill ``suggestions`` / make a queue
  item; it never produces RESOLVED.
- The queue is scope-bound: ``queue_items(scope)`` lists only that scope and
  ``resolve_ambiguity(scope, item_id, ...)`` treats another scope's item exactly like an unknown one.
  It is the only way a human decision is recorded: non-blank HUMAN approver, idempotent for the
  same choice (the replay does NOT reveal the first approver), conflicting second choice refused,
  only records who/when (injected clock). It does not merge entities or touch aliases.
- Result codes are fixed constants; caller-supplied text is never echoed into them.
- RESIDUAL RISK: the approver kind is caller-asserted; there is no authenticated principal binding.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ._identity import clean_identity, exact_text, is_empty_1c_ref, scope_key, stable_key

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
    """NFKC + casefold + trim for display names; '' means unusable (incl. invisible chars)."""
    return clean_identity(value)


@dataclass(frozen=True, slots=True)
class AliasScope:
    tenant_id: str
    company_id: str

    def valid(self) -> bool:
        return self.key() is not None

    def key(self) -> tuple[str, str] | None:
        return scope_key(self.tenant_id, self.company_id)


def _skey(scope: object) -> tuple[str, str] | None:
    if type(scope) is not AliasScope:
        return None
    try:
        return scope.key()
    except Exception:  # noqa: BLE001 - unset slots / hostile attribute access: treat as invalid scope
        return None


@dataclass(frozen=True, slots=True)
class Reference:
    """Namespaced external reference (e.g. namespace 'tax_id' / 'erp_code'); compared exactly."""
    namespace: str
    value: str

    def valid(self) -> bool:
        return (bool(exact_text(self.namespace)) and bool(exact_text(self.value))
                and not is_empty_1c_ref(exact_text(self.value)))

    def key(self) -> tuple[str, str]:
        return (exact_text(self.namespace), exact_text(self.value))


def _ref_ok(ref: object) -> bool:
    try:
        return type(ref) is Reference and ref.valid()
    except Exception:  # noqa: BLE001 - hostile/partially built object
        return False


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


def _scope_bad() -> ResolutionResult:
    return ResolutionResult(AliasOutcome.SCOPE_VIOLATION, code="SCOPE_INVALID")


@dataclass(slots=True)
class AliasResolver:
    clock: Callable[[], datetime]
    _entities: dict[tuple[tuple[str, str], str], SupplierEntity] = field(default_factory=dict)
    _aliases: list[AliasRecord] = field(default_factory=list)
    _queue: dict[str, QueueItem] = field(default_factory=dict)

    # -- registration -------------------------------------------------------------------------
    def add_entity(self, entity: SupplierEntity) -> ResolutionResult:
        if type(entity) is not SupplierEntity:
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ENTITY_INVALID")
        skey = _skey(entity.scope)
        if skey is None:
            return _scope_bad()
        try:
            entity_id, name, refs = entity.entity_id, entity.canonical_name, entity.references
        except AttributeError:
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ENTITY_INVALID")
        if (type(entity_id) is not str or not exact_text(entity_id) or is_empty_1c_ref(entity_id)
                or not normalize_name(name)
                or not isinstance(refs, (tuple, list))
                or not all(_ref_ok(r) for r in tuple(refs))):
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ENTITY_INVALID")
        key = (skey, entity_id)
        if key in self._entities:
            return ResolutionResult(AliasOutcome.REJECTED_DUPLICATE, code="ENTITY_EXISTS")
        self._entities[key] = SupplierEntity(entity_id, entity.scope, name, tuple(refs))
        return ResolutionResult(AliasOutcome.OK, entity_id=entity_id)

    def add_alias(self, alias: AliasRecord) -> ResolutionResult:
        if type(alias) is not AliasRecord:
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ALIAS_INVALID")
        skey = _skey(alias.scope)
        if skey is None:
            return _scope_bad()
        try:
            entity_id, alias_text = alias.entity_id, alias.alias_text
            reference, provenance = alias.reference, alias.provenance
        except AttributeError:
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ALIAS_INVALID")
        if type(entity_id) is not str or (skey, entity_id) not in self._entities:
            # also covers an entity that exists only in another scope: no cross-scope oracle
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ENTITY_UNKNOWN")
        has_text = bool(normalize_name(alias_text))
        has_ref = _ref_ok(reference)
        if (not has_text and not has_ref) or not exact_text(provenance) or (
                reference is not None and not has_ref):
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="ALIAS_INVALID")
        self._aliases.append(alias)
        return ResolutionResult(AliasOutcome.OK, entity_id=alias.entity_id)

    # -- resolution ---------------------------------------------------------------------------
    def resolve(self, scope: AliasScope, query: ResolveQuery) -> ResolutionResult:
        skey = _skey(scope)
        if skey is None:
            return _scope_bad()
        if type(query) is not ResolveQuery:
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="QUERY_INVALID")
        in_scope = [e for (k, _), e in self._entities.items() if k == skey]
        ref = query.reference
        if ref is not None and not _ref_ok(ref):
            return ResolutionResult(AliasOutcome.REJECTED_INPUT, code="REFERENCE_INVALID")
        ref_hits: set[str] = set()
        if ref is not None:
            rk = ref.key()
            for e in in_scope:
                if any(r.key() == rk for r in e.references):
                    ref_hits.add(e.entity_id)
            for a in self._aliases:
                if _skey(a.scope) == skey and a.reference is not None and a.reference.key() == rk:
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
                   name: object) -> set[str]:
        n = normalize_name(name)
        if not n:
            return set()
        hits = {e.entity_id for e in in_scope if normalize_name(e.canonical_name) == n}
        for a in self._aliases:
            if _skey(a.scope) == skey and normalize_name(a.alias_text) == n:
                hits.add(a.entity_id)
        return hits

    def _ambiguous(self, scope: AliasScope, candidates: set[str],
                   suggestions: set[str]) -> ResolutionResult:
        cands = tuple(sorted(candidates))
        skey = scope.key()
        digest = hashlib.sha256(stable_key(*skey, *cands).encode("utf-8")).hexdigest()[:24]
        item_id = f"RQ-{digest}"
        if item_id not in self._queue:
            self._queue[item_id] = QueueItem(item_id, scope, cands,
                                             tuple(sorted(suggestions - candidates)))
        return ResolutionResult(AliasOutcome.AMBIGUOUS, candidate_ids=cands, queue_item_id=item_id,
                                code="AMBIGUOUS_CANDIDATES")

    # -- queue / human decision ---------------------------------------------------------------
    def queue_items(self, scope: AliasScope) -> tuple[QueueItem, ...]:
        """Queue items of exactly this scope; empty for an invalid scope."""
        skey = _skey(scope)
        if skey is None:
            return ()
        return tuple(i for i in self._queue.values() if _skey(i.scope) == skey)

    def resolve_ambiguity(self, scope: AliasScope, item_id: str, chosen_entity_id: str,
                          approver: Approver, reason: str) -> DecisionResult:
        skey = _skey(scope)
        if skey is None:
            return DecisionResult(AliasOutcome.SCOPE_VIOLATION, code="SCOPE_INVALID")
        item = self._queue.get(item_id) if type(item_id) is str else None
        if item is None or _skey(item.scope) != skey:
            # another scope's item is indistinguishable from a missing one
            return DecisionResult(AliasOutcome.UNKNOWN_ITEM, code="ITEM_UNKNOWN")
        if (type(approver) is not Approver or approver.kind is not ActorKind.HUMAN
                or not normalize_name(approver.identity)):
            return DecisionResult(AliasOutcome.REJECTED_APPROVER, code="APPROVER_NOT_HUMAN")
        why = exact_text(reason)
        if not why:
            return DecisionResult(AliasOutcome.REJECTED_INPUT, code="REASON_REQUIRED")
        if type(chosen_entity_id) is not str or not any(
                type(c) is str and str.__eq__(c, chosen_entity_id) is True for c in item.candidate_ids):
            return DecisionResult(AliasOutcome.REJECTED_CHOICE, code="CHOICE_NOT_CANDIDATE")
        if item.decision is not None:
            if item.decision.chosen_entity_id == chosen_entity_id:
                first = item.decision
                masked = Decision(first.chosen_entity_id, "", "", first.decided_at)
                return DecisionResult(AliasOutcome.DECIDED, masked, replay=True)
            return DecisionResult(AliasOutcome.REJECTED_CONFLICT, code="DECISION_CONFLICT")
        decision = Decision(chosen_entity_id, exact_text(approver.identity), why, self.clock())
        self._queue[item.item_id] = QueueItem(item.item_id, item.scope, item.candidate_ids,
                                              item.suggestions, decision)
        return DecisionResult(AliasOutcome.DECIDED, decision)
