
import pytest

from business_ai_gateway.phase2.model_graph import Dependency, DependencyGraph
from business_ai_gateway.phase2.structural_diff import ChangeKind, ObjectChange, ObservedDiff


def diff(*objects, unattributed=False, changed=True):
    return ObservedDiff(
        canonicalizer_version="edmx-structural-v1",
        previous_raw_sha256="a" * 64,
        observed_raw_sha256="b" * 64,
        previous_structural_sha256="a" * 64,
        observed_structural_sha256=("b" if changed else "a") * 64,
        changes=tuple(ObjectChange(obj, kind, "a" * 64, "b" * 64) for obj, kind in objects),
        unattributed_structural_change=unattributed,
    )


def graph(complete=True, edges=()):
    return DependencyGraph(
        "tenant-1", "source-1",
        (Dependency("tenant-1", "source-1", "purchase_documents", "Purchase", "v1"),
         Dependency("tenant-1", "source-1", "payable_balance", "Accounting", "v1")),
        known_operations=("purchase_documents", "payable_balance"),
        complete=complete,
        object_edges=edges,
    )


def test_addition_is_nonimpacting_with_complete_graph():
    result = graph().affected(diff(("NewUnrelatedObject", ChangeKind.ADDED)))
    assert result.affected_operations == frozenset()
    assert result.unaffected_operations == {"purchase_documents", "payable_balance"}
    assert result.unknown_impact is False


def test_modified_object_blocks_only_dependent_tool():
    result = graph().affected(diff(("Purchase", ChangeKind.MODIFIED)))
    assert result.blocked_operations == {"purchase_documents"}
    assert result.unaffected_operations == {"payable_balance"}


def test_renamed_object_is_removed_and_added():
    result = graph().affected(diff(("Purchase", ChangeKind.REMOVED),
                                   ("PurchasesNew", ChangeKind.ADDED)))
    assert result.blocked_operations == {"purchase_documents"}


def test_transitive_dependency_closure():
    result = graph(edges=(("Purchase", "Currency"),)).affected(
        diff(("Currency", ChangeKind.MODIFIED)))
    assert result.blocked_operations == {"purchase_documents"}


def test_unmapped_existing_object_fails_closed():
    result = graph().affected(diff(("Unmapped", ChangeKind.MODIFIED)))
    assert result.unknown_impact is True
    assert result.blocked_operations == {"purchase_documents", "payable_balance"}


def test_unattributed_change_fails_closed():
    result = graph().affected(diff(unattributed=True))
    assert result.unknown_impact and result.blocked_operations == {
        "purchase_documents", "payable_balance"
    }


def test_incomplete_graph_blocks_all_changes():
    result = graph(complete=False).affected(diff(("NewObject", ChangeKind.ADDED)))
    assert result.unknown_impact and len(result.blocked_operations) == 2


def test_no_change_does_not_block_when_graph_incomplete():
    result = graph(complete=False).affected(diff(changed=False))
    assert not result.affected_operations and not result.unknown_impact


def test_cross_source_dependency_is_rejected():
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        DependencyGraph("tenant-1", "source-1",
                        [Dependency("other-tenant", "source-1", "purchase_documents", "Purchase", "v1")],
                        known_operations=["purchase_documents"], complete=True)


def test_declared_complete_graph_must_cover_all_tools():
    with pytest.raises(ValueError, match="INCOMPLETE_DECLARED_GRAPH"):
        DependencyGraph("tenant-1", "source-1",
                        [Dependency("tenant-1", "source-1", "purchase_documents", "Purchase", "v1")],
                        known_operations=["purchase_documents", "payable_balance"], complete=True)


def test_graph_rejects_cycle_self_edge():
    with pytest.raises(ValueError, match="INVALID_OBJECT_EDGE"):
        graph(edges=(("Purchase", "Purchase"),))


def test_dependency_edges_do_not_approve_model():
    result = graph().affected(diff(("Purchase", ChangeKind.MODIFIED)))
    assert result.affected_operations == {"purchase_documents"}
    assert not hasattr(result, "approved_model")
