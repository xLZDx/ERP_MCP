"""Sprint S4B / E2 / R2-US-015: impact-closure tests for the model dependency graph.

TC043: an operation that uses a changed dependency is blocked.
TC044: unknown graph / unknown dependency is a conservative deny, never 'no impact'.
TC045: remove + recreate of an object is NOT a rename (no inherited identity).

Complements (does not duplicate) tests/phase2/test_model_graph.py.
"""
from __future__ import annotations

import itertools

import pytest

from business_ai_gateway.phase2.model_graph import Dependency, DependencyGraph
from business_ai_gateway.phase2.structural_diff import ChangeKind, ObjectChange, ObservedDiff

T, S = "tenant-1", "source-1"


def diff(*objects, unattributed=False, changed=True, tenant=T, source=S):
    return ObservedDiff(
        tenant_id=tenant, source_id=source,
        canonicalizer_version="edmx-structural-v2",
        previous_raw_sha256="a" * 64, observed_raw_sha256="b" * 64,
        previous_structural_sha256="a" * 64,
        observed_structural_sha256=("b" if changed else "a") * 64,
        changes=tuple(ObjectChange(o, k, "a" * 64, "b" * 64) for o, k in objects),
        unattributed_structural_change=unattributed,
    )


def dep(op, obj, tenant=T, source=S):
    return Dependency(tenant, source, op, obj, "v1")


def build(deps, ops, edges=(), complete=True, tenant=T, source=S):
    return DependencyGraph(tenant, source, deps, known_operations=ops,
                           complete=complete, object_edges=edges)


def chain_graph(edges=None):
    """op_a uses A; A depends on B; B depends on C (edge = (dependent, upstream))."""
    edges = (("A", "B"), ("B", "C")) if edges is None else edges
    return build([dep("op_a", "A"), dep("op_x", "X")], ["op_a", "op_x"], edges)


ALL = frozenset({"op_a", "op_x"})


# ---------------- TC043: affected operation is blocked ----------------

def test_tc043_transitive_two_hops_blocks_root_operation():
    r = chain_graph().affected(diff(("C", ChangeKind.MODIFIED)))
    assert r.blocked_operations == {"op_a"}
    assert r.unaffected_operations == {"op_x"}
    assert r.reason == "SCOPED_IMPACT" and r.unknown_impact is False


def test_tc043_sensitivity_without_edge_chain_is_broken_operation_not_blocked():
    # Opposite graph: B->C edge missing, so C is unknown to the graph (fail closed),
    # while with the edge present the impact is precisely scoped.
    broken = chain_graph(edges=(("A", "B"),))
    r = broken.affected(diff(("C", ChangeKind.MODIFIED)))
    assert r.reason == "UNMAPPED_MODIFICATION"  # not a silent 'no impact'
    full = chain_graph().affected(diff(("C", ChangeKind.MODIFIED)))
    assert full.reason == "SCOPED_IMPACT" and full.blocked_operations == {"op_a"}


def test_tc043_edge_direction_upstream_change_blocks_dependent_not_reverse():
    # Changing the dependent (A) must not propagate down to its upstreams' operations.
    g2 = build([dep("op_a", "A"), dep("op_c", "C")], ["op_a", "op_c"], (("A", "B"), ("B", "C")))
    r = g2.affected(diff(("A", ChangeKind.MODIFIED)))
    assert r.blocked_operations == {"op_a"}
    assert r.unaffected_operations == {"op_c"}
    # And the upstream change does reach the dependent chain.
    r2 = g2.affected(diff(("C", ChangeKind.MODIFIED)))
    assert r2.blocked_operations == {"op_a", "op_c"}


def test_tc043_middle_node_change_blocks_only_downstream_dependents():
    g = build([dep("op_a", "A"), dep("op_b", "B"), dep("op_c", "C")],
              ["op_a", "op_b", "op_c"], (("A", "B"), ("B", "C")))
    r = g.affected(diff(("B", ChangeKind.MODIFIED)))
    assert r.blocked_operations == {"op_a", "op_b"}
    assert r.unaffected_operations == {"op_c"}


def test_tc043_cycle_terminates_and_blocks_all_members():
    g = build([dep("op_a", "A"), dep("op_b", "B"), dep("op_x", "X")],
              ["op_a", "op_b", "op_x"], (("A", "B"), ("B", "A")))
    r = g.affected(diff(("A", ChangeKind.MODIFIED)))
    assert r.blocked_operations == {"op_a", "op_b"}
    assert r.unaffected_operations == {"op_x"}


def test_tc043_longer_cycle_terminates():
    g = build([dep("op_a", "A"), dep("op_x", "X")], ["op_a", "op_x"],
              (("A", "B"), ("B", "C"), ("C", "A")))
    assert g.affected(diff(("C", ChangeKind.REMOVED))).blocked_operations == {"op_a"}


def test_tc043_diamond_dependency_counted_once():
    # D uses B and C; both depend on A. Change in A reaches D via two paths.
    g = build([dep("op_d", "D"), dep("op_x", "X")], ["op_d", "op_x"],
              (("B", "A"), ("C", "A"), ("D", "B"), ("D", "C")))
    r = g.affected(diff(("A", ChangeKind.MODIFIED)))
    assert r.blocked_operations == {"op_d"}
    assert r.unaffected_operations == {"op_x"}
    assert len(r.blocked_operations) + len(r.unaffected_operations) == 2


def test_tc043_one_operation_on_many_objects_blocked_by_any_one_change():
    g = build([dep("op_a", "A"), dep("op_a", "B"), dep("op_x", "X")], ["op_a", "op_x"])
    for obj in ("A", "B"):
        assert g.affected(diff((obj, ChangeKind.MODIFIED))).blocked_operations == {"op_a"}


def test_tc043_two_changes_union_of_blocked_operations():
    g = build([dep("op_a", "A"), dep("op_b", "B"), dep("op_x", "X")], ["op_a", "op_b", "op_x"])
    r = g.affected(diff(("A", ChangeKind.MODIFIED), ("B", ChangeKind.REMOVED)))
    assert r.blocked_operations == {"op_a", "op_b"} and r.unaffected_operations == {"op_x"}


def test_tc043_added_unknown_alongside_modified_mapped_is_scoped_not_unknown():
    r = chain_graph().affected(diff(("Brand", ChangeKind.ADDED), ("C", ChangeKind.MODIFIED)))
    assert r.blocked_operations == {"op_a"} and r.unknown_impact is False


def test_tc043_result_partitions_known_operations_and_is_scoped():
    r = chain_graph().affected(diff(("C", ChangeKind.MODIFIED)))
    assert r.affected_operations | r.unaffected_operations == ALL
    assert r.affected_operations & r.unaffected_operations == frozenset()
    assert (r.tenant_id, r.source_id) == (T, S)


# ---------------- TC044: unknown => conservative deny ----------------

def test_tc044_operation_without_declared_dependencies_makes_graph_incomplete():
    # op_x has no mapping, so a 'complete' graph cannot be declared.
    with pytest.raises(ValueError, match="INCOMPLETE_DECLARED_GRAPH"):
        build([dep("op_a", "A")], ["op_a", "op_x"], complete=True)


def test_tc044_operation_without_dependencies_is_denied_on_any_change():
    g = build([dep("op_a", "A")], ["op_a", "op_x"], complete=False)
    r = g.affected(diff(("A", ChangeKind.MODIFIED)))
    assert r.unknown_impact is True and r.reason == "UNKNOWN_IMPACT"
    assert r.blocked_operations == {"op_a", "op_x"}
    assert r.unaffected_operations == frozenset()
    # Sensitivity: declaring the missing dependency makes the graph complete and scoped.
    ok = build([dep("op_a", "A"), dep("op_x", "X")], ["op_a", "op_x"], complete=True)
    r2 = ok.affected(diff(("A", ChangeKind.MODIFIED)))
    assert r2.unknown_impact is False and r2.unaffected_operations == {"op_x"}


@pytest.mark.parametrize("kind", [ChangeKind.ADDED, ChangeKind.MODIFIED, ChangeKind.REMOVED])
def test_tc044_incomplete_graph_denies_every_change_kind(kind):
    g = build([dep("op_a", "A")], ["op_a", "op_x"], complete=False)
    r = g.affected(diff(("A", kind)))
    assert r.blocked_operations == {"op_a", "op_x"} and r.unknown_impact


@pytest.mark.parametrize("d", [
    diff(("C", ChangeKind.MODIFIED)),
    diff(("Zzz", ChangeKind.REMOVED)),
    diff(unattributed=True),
    diff(changed=False),
])
def test_tc044_blocked_and_unaffected_partition_exactly_the_known_operations(d):
    # A caller allows only ops in unaffected_operations; blocked | unaffected must be exactly the
    # known inventory (disjoint), so an undeclared operation can never be reported as unaffected.
    r = chain_graph().affected(d)
    assert r.blocked_operations | r.unaffected_operations == ALL
    assert r.blocked_operations & r.unaffected_operations == frozenset()
    assert "never_declared_op" not in r.unaffected_operations


def _gate_allows(graph, observed, operation):
    """Caller contract: allow only when affected() returned and the op is explicitly unaffected.

    Any exception (scope mismatch, untrusted diff) is a DENY, never 'no impact'.
    """
    try:
        return operation in graph.affected(observed).unaffected_operations
    except ValueError:
        return False


def test_tc044_scope_mismatch_raises_and_gate_treats_it_as_deny():
    g = chain_graph()
    foreign = diff(changed=False, tenant="tenant-2")  # would be 'no impact' if scope were ignored
    with pytest.raises(ValueError, match="DIFF_SCOPE_MISMATCH"):
        g.affected(foreign)
    assert _gate_allows(g, foreign, "op_x") is False
    assert _gate_allows(g, diff(changed=False), "op_x") is True  # positive control, same scope
    assert _gate_allows(g, diff(changed=False), "never_declared_op") is False


@pytest.mark.parametrize("kind", [ChangeKind.MODIFIED, ChangeKind.REMOVED])
def test_tc044_changed_object_absent_from_graph_denies_everything(kind):
    r = chain_graph().affected(diff(("Ghost", kind)))
    assert r.unknown_impact is True and r.reason == "UNMAPPED_MODIFICATION"
    assert r.blocked_operations == ALL and r.unaffected_operations == frozenset()


def test_tc044_one_unmapped_change_among_mapped_ones_denies_all():
    r = chain_graph().affected(diff(("C", ChangeKind.MODIFIED), ("Ghost", ChangeKind.MODIFIED)))
    assert r.unknown_impact and r.blocked_operations == ALL


def test_tc044_sensitivity_registering_ghost_turns_deny_into_scoped():
    g = build([dep("op_a", "A"), dep("op_x", "X"), dep("op_x", "Ghost")], ["op_a", "op_x"])
    r = g.affected(diff(("Ghost", ChangeKind.MODIFIED)))
    assert r.unknown_impact is False and r.blocked_operations == {"op_x"}


def test_tc044_object_known_only_via_edge_is_not_unmapped():
    # C appears only as an edge endpoint; it is covered by the graph.
    r = chain_graph().affected(diff(("C", ChangeKind.REMOVED)))
    assert r.unknown_impact is False


def test_tc044_unattributed_change_with_listed_changes_still_denies():
    r = chain_graph().affected(diff(("C", ChangeKind.MODIFIED), unattributed=True))
    assert r.unknown_impact and r.blocked_operations == ALL


def test_tc044_untrusted_diff_is_rejected():
    d = diff(("C", ChangeKind.MODIFIED))
    object.__setattr__(d, "trust_level", "VALIDATED")
    with pytest.raises(ValueError, match="UNTRUSTED_OR_INVALID_DIFF"):
        chain_graph().affected(d)


def test_tc044_non_diff_input_is_rejected():
    with pytest.raises(ValueError, match="UNTRUSTED_OR_INVALID_DIFF"):
        chain_graph().affected({"changes": []})  # type: ignore[arg-type]


def test_tc044_graph_construction_rejects_bad_inventory_and_scope():
    with pytest.raises(ValueError, match="INVALID_OPERATION_INVENTORY"):
        build([], [], complete=False)
    with pytest.raises(ValueError, match="INVALID_OPERATION_INVENTORY"):
        build([], ["op_a", ""], complete=False)
    with pytest.raises(ValueError, match="INVALID_GRAPH_SCOPE"):
        build([dep("op_a", "A")], ["op_a"], tenant="")
    with pytest.raises(ValueError, match="DEPENDENCY_SCOPE_MISMATCH"):
        build([dep("undeclared_op", "A")], ["op_a"], complete=False)
    with pytest.raises(ValueError, match="DEPENDENCY_SCOPE_MISMATCH"):
        build([Dependency(T, S, "op_a", "", "v1")], ["op_a"], complete=False)
    with pytest.raises(ValueError, match="DEPENDENCY_SCOPE_MISMATCH"):
        build([Dependency(T, S, "op_a", "A", "")], ["op_a"], complete=False)
    with pytest.raises(ValueError, match="INVALID_OBJECT_EDGE"):
        build([dep("op_a", "A")], ["op_a"], edges=(("A", ""),))


# ---------------- TC045: remove + recreate is not a rename ----------------

def purchase_graph():
    return build([dep("purchase_documents", "Purchase"), dep("payable_balance", "Accounting")],
                 ["purchase_documents", "payable_balance"])


def test_tc045_removed_old_identity_blocks_its_dependents_even_if_recreated_under_new_name():
    r = purchase_graph().affected(diff(("Purchase", ChangeKind.REMOVED),
                                       ("PurchaseV2", ChangeKind.ADDED)))
    assert r.blocked_operations == {"purchase_documents"}
    assert r.unaffected_operations == {"payable_balance"}


def test_tc045_recreated_object_does_not_inherit_links():
    g = purchase_graph()
    # The recreated object, once it exists, is unknown to the graph: modifying it
    # is an unmapped change (deny), never 'no impact' and never purchase_documents only.
    r = g.affected(diff(("PurchaseV2", ChangeKind.MODIFIED)))
    assert r.reason == "UNMAPPED_MODIFICATION" and r.unknown_impact
    assert r.blocked_operations == {"purchase_documents", "payable_balance"}
    # Adding it does not block the old identity's operation.
    added = g.affected(diff(("PurchaseV2", ChangeKind.ADDED)))
    assert added.blocked_operations == frozenset() and not added.unknown_impact
    # Sensitivity: an explicit new mapping is what grants the link.
    g2 = build([dep("purchase_documents", "Purchase"), dep("purchase_documents", "PurchaseV2"),
                dep("payable_balance", "Accounting")], ["purchase_documents", "payable_balance"])
    assert g2.affected(diff(("PurchaseV2", ChangeKind.MODIFIED))).blocked_operations == {
        "purchase_documents"}


def test_tc045_same_name_remove_and_add_in_one_diff_blocks_dependents():
    r = purchase_graph().affected(diff(("Purchase", ChangeKind.REMOVED),
                                       ("Purchase", ChangeKind.ADDED)))
    assert r.blocked_operations == {"purchase_documents"}
    assert r.unaffected_operations == {"payable_balance"}


def test_tc045_recreated_same_name_added_alone_still_blocks_prior_dependents():
    # An ADDED object whose name matches an existing mapping must not be treated as new/harmless.
    r = purchase_graph().affected(diff(("Purchase", ChangeKind.ADDED)))
    assert r.blocked_operations == {"purchase_documents"}


def test_tc045_removed_upstream_blocks_transitive_dependents_while_recreation_adds_nothing():
    g = chain_graph()
    r = g.affected(diff(("C", ChangeKind.REMOVED), ("C2", ChangeKind.ADDED)))
    assert r.blocked_operations == {"op_a"}
    assert r.unaffected_operations == {"op_x"}


def test_tc045_remove_without_recreate_vs_rename_pair_same_blocking():
    g = purchase_graph()
    removed = g.affected(diff(("Purchase", ChangeKind.REMOVED)))
    renamed = g.affected(diff(("Purchase", ChangeKind.REMOVED), ("Purchases", ChangeKind.ADDED)))
    assert removed.blocked_operations == renamed.blocked_operations == {"purchase_documents"}


# ---------------- scope isolation ----------------

def test_scope_company_b_graph_rejects_company_a_diff():
    gb = build([dep("op_a", "A", tenant="tenant-2")], ["op_a"], tenant="tenant-2")
    with pytest.raises(ValueError, match="DIFF_SCOPE_MISMATCH"):
        gb.affected(diff(("A", ChangeKind.MODIFIED), tenant=T))


def test_scope_same_object_name_in_two_tenants_is_independent():
    ga = build([dep("op_a", "Shared", tenant="tenant-A")], ["op_a"], tenant="tenant-A")
    gb = build([dep("op_b", "Shared", tenant="tenant-B"), dep("op_c", "Other", tenant="tenant-B")],
               ["op_b", "op_c"], tenant="tenant-B")
    ra = ga.affected(diff(("Shared", ChangeKind.MODIFIED), tenant="tenant-A"))
    assert ra.blocked_operations == {"op_a"} and ra.tenant_id == "tenant-A"
    # Company A's change leaves B's graph/results untouched (B sees only its own diffs).
    rb_nochange = gb.affected(diff(changed=False, tenant="tenant-B"))
    assert rb_nochange.blocked_operations == frozenset()
    assert rb_nochange.unaffected_operations == {"op_b", "op_c"}
    rb = gb.affected(diff(("Shared", ChangeKind.MODIFIED), tenant="tenant-B"))
    assert rb.blocked_operations == {"op_b"} and rb.unaffected_operations == {"op_c"}


def test_scope_cross_tenant_dependency_record_rejected_even_when_op_names_match():
    with pytest.raises(ValueError, match="DEPENDENCY_SCOPE_MISMATCH"):
        build([dep("op_a", "A", tenant="tenant-2")], ["op_a"])
    with pytest.raises(ValueError, match="DEPENDENCY_SCOPE_MISMATCH"):
        build([dep("op_a", "A", source="source-2")], ["op_a"])


def test_scope_same_tenant_other_source_is_isolated():
    g1 = build([dep("op_a", "A")], ["op_a"])
    with pytest.raises(ValueError, match="DIFF_SCOPE_MISMATCH"):
        g1.affected(diff(("A", ChangeKind.MODIFIED), source="source-2"))


# ---------------- determinism / idempotence ----------------

def test_determinism_repeated_calls_equal_and_do_not_mutate_graph():
    g = chain_graph()
    d = diff(("C", ChangeKind.MODIFIED))
    first = g.affected(d)
    for _ in range(5):
        assert g.affected(d) == first
    assert sorted(first.blocked_operations) == ["op_a"]
    # A later unrelated query is not polluted by earlier ones.
    assert g.affected(diff(("X", ChangeKind.MODIFIED))).blocked_operations == {"op_x"}


def test_determinism_input_order_of_edges_deps_and_changes_does_not_matter():
    deps = [dep("op_a", "A"), dep("op_b", "B"), dep("op_x", "X")]
    edges = [("A", "B"), ("B", "C"), ("C", "D")]
    changes = [("D", ChangeKind.MODIFIED), ("X", ChangeKind.REMOVED)]
    results = set()
    for dp, ed, ch in itertools.product(itertools.permutations(deps),
                                        itertools.permutations(edges),
                                        itertools.permutations(changes)):
        r = build(list(dp), ["op_x", "op_b", "op_a"], tuple(ed)).affected(diff(*ch))
        results.add((tuple(sorted(r.blocked_operations)), tuple(sorted(r.unaffected_operations)),
                     r.unknown_impact, r.reason))
    assert results == {(("op_a", "op_b", "op_x"), (), False, "SCOPED_IMPACT")}


def test_determinism_duplicate_edges_and_dependencies_are_idempotent():
    once = build([dep("op_a", "A"), dep("op_x", "X")], ["op_a", "op_x"], (("A", "B"),))
    twice = build([dep("op_a", "A"), dep("op_a", "A"), dep("op_x", "X")], ["op_a", "op_x"],
                  (("A", "B"), ("A", "B")))
    d = diff(("B", ChangeKind.MODIFIED))
    assert once.affected(d) == twice.affected(d)


def test_no_change_diff_blocks_nothing_and_everything_is_unaffected():
    r = chain_graph().affected(diff(changed=False))
    assert r.blocked_operations == frozenset() and r.unaffected_operations == ALL
    assert r.reason == "NO_STRUCTURAL_CHANGE" and r.unknown_impact is False
