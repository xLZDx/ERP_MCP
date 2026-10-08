"""Phase 2: immutable, company-scoped model-dependency impact analysis.

The graph is input from *accepted* review data, not from a model suggestion.
Unknown/incomplete dependency coverage must fail closed. No source or DB calls.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .structural_diff import ObservedDiff


@dataclass(frozen=True, slots=True)
class Dependency:
    tenant_id: str
    source_id: str
    operation_id: str
    object_id: str
    mapping_version: str


@dataclass(frozen=True, slots=True)
class ImpactResult:
    tenant_id: str
    source_id: str
    affected_operations: frozenset[str]
    unaffected_operations: frozenset[str]
    unknown_impact: bool
    reason: str

    @property
    def blocked_operations(self) -> frozenset[str]:
        return self.affected_operations


class DependencyGraph:
    """Approved edge projections for a single exact tenant/source scope."""

    def __init__(
        self,
        tenant_id: str,
        source_id: str,
        dependencies: Iterable[Dependency],
        *,
        known_operations: Iterable[str],
        complete: bool,
        object_edges: Iterable[tuple[str, str]] = (),
    ) -> None:
        if not tenant_id or not source_id:
            raise ValueError("INVALID_GRAPH_SCOPE")
        self.tenant_id, self.source_id = tenant_id, source_id
        self.complete = complete
        self.known_operations = frozenset(known_operations)
        if not self.known_operations or any(not op for op in self.known_operations):
            raise ValueError("INVALID_OPERATION_INVENTORY")
        records = tuple(dependencies)
        for d in records:
            if (d.tenant_id != tenant_id or d.source_id != source_id
                    or d.operation_id not in self.known_operations
                    or not d.object_id or not d.mapping_version):
                raise ValueError("DEPENDENCY_SCOPE_MISMATCH")
        self._by_object: dict[str, set[str]] = {}
        mapped = set()
        for dep in records:
            mapped.add(dep.operation_id)
            self._by_object.setdefault(dep.object_id, set()).add(dep.operation_id)
        # 'complete' must be backed by at least one exact mapping for every operation.
        if complete and mapped != self.known_operations:
            raise ValueError("INCOMPLETE_DECLARED_GRAPH")
        self._upstream_by_dependent: dict[str, set[str]] = {}
        for dependent, upstream in object_edges:
            if not dependent or not upstream or dependent == upstream:
                raise ValueError("INVALID_OBJECT_EDGE")
            self._upstream_by_dependent.setdefault(upstream, set()).add(dependent)

    def affected(self, change: ObservedDiff) -> ImpactResult:
        if not isinstance(change, ObservedDiff) or change.trust_level != "OBSERVED_ONLY":
            raise ValueError("UNTRUSTED_OR_INVALID_DIFF")
        if not change.has_changes:
            return ImpactResult(self.tenant_id, self.source_id, frozenset(),
                                self.known_operations, False, "NO_STRUCTURAL_CHANGE")
        if not self.complete or change.unattributed_structural_change:
            return ImpactResult(self.tenant_id, self.source_id, self.known_operations,
                                frozenset(), True, "UNKNOWN_IMPACT")
        seen: set[str] = set()
        todo = [item.qualified_name for item in change.changes]
        while todo:
            obj = todo.pop()
            if obj in seen:
                continue
            seen.add(obj)
            todo.extend(self._upstream_by_dependent.get(obj, ()))
        known_objects = set(self._by_object) | set(self._upstream_by_dependent)
        for dependents in self._upstream_by_dependent.values():
            known_objects.update(dependents)
        # A removed/modified object with no existing graph coverage is not proven harmless.
        if any(item.kind != "ADDED" and item.qualified_name not in known_objects
               for item in change.changes):
            return ImpactResult(self.tenant_id, self.source_id, self.known_operations,
                                frozenset(), True, "UNMAPPED_MODIFICATION")
        affected = frozenset(
            operation for obj in seen for operation in self._by_object.get(obj, ())
        )
        return ImpactResult(self.tenant_id, self.source_id, affected,
                            self.known_operations - affected, False, "SCOPED_IMPACT")
