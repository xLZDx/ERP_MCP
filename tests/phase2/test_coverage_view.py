"""R2-US-040 (S8/E2) coverage panel and scoped diff/evidence: TC120 foreign rows absent (ids, names,
counts), opaque HIDDEN_BY_SCOPE flag only, SCOPE_EPOCH_STALE, re-check before disclosure, repr without
foreign identifiers; TC118/TC119 coverage-panel part; S6b hostile-input lesson rows.

Hostile and "must not leak" rows come before the happy path.
"""
from __future__ import annotations

import ast
import itertools
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import coverage_view as cv
from business_ai_gateway.phase2.comparison_snapshot import (
    RunLedger,
    SideRead,
    SnapshotStore,
    _projection,
)
from business_ai_gateway.phase2.coverage_view import (
    CoveragePanel,
    EvidenceItem,
    ScopedDiffView,
    ScopedEvidenceView,
    build_coverage_panel,
    build_scoped_diff,
    build_scoped_evidence,
    render_guard_coverage,
)
from business_ai_gateway.phase2.timeline_view import ScopeAuthority, TimelineSubject
from business_ai_gateway.phase2.validation_coverage import (
    Claim,
    ClaimScope,
    CoverageCode,
    CoverageStatus,
    Evidence,
    EvidenceVerdict,
    Link,
    build_matrix,
)
from business_ai_gateway.phase2.workbench_types import ReasonCode, SafeError, ViewerScope

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
A, B = ClaimScope("t1", "A"), ClaimScope("t1", "B")
PASS, FAIL = EvidenceVerdict.PASS, EvidenceVerdict.FAIL


def h(n: int) -> str:
    return f"{n:064x}"


class LyingStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class LyingInt(int):
    def __eq__(self, other):
        return True

    __hash__ = int.__hash__


class World:
    """Company A is the viewer; company B holds rows that must never be disclosed."""

    def __init__(self):
        self.claims = (
            Claim("cA-covered", A, "purchases", "validate"),
            Claim("cA-open", A, "sales", "validate"),
            Claim("SECRET-cB-covered", B, "purchases", "validate"),
            Claim("SECRET-cB-open", B, "sales", "validate"),
        )
        self.evidence = (
            Evidence("eA1", A, "srcA", h(1), PASS),
            Evidence("SECRET-eB1", B, "SECRET-source-B", h(2), PASS),
        )
        self.links = (Link("cA-covered", "eA1"), Link("SECRET-cB-covered", "SECRET-eB1"))
        self.matrix = build_matrix(self.claims, self.evidence, self.links)
        self.epochs = {("t1", "A"): 5, ("t1", "B"): 5}
        self.authority = ScopeAuthority(lambda t, c: self.epochs.get((t, c)))
        self.viewer = ViewerScope("t1", "A", 5)


@pytest.fixture
def w():
    return World()


def blob(view) -> str:
    return repr(view) + repr(getattr(view, "digest", ""))


# ===================================================== TC120: nothing foreign, ever
def test_tc120_panel_drops_foreign_rows_ids_names_and_counts(w):
    panel = build_coverage_panel(w.viewer, w.authority, w.matrix)
    assert type(panel) is CoveragePanel
    assert [c.claim_id for c in panel.covered] == ["cA-covered"]
    assert panel.uncovered == ("cA-open",)
    assert panel.hidden_by_scope is True
    assert "SECRET" not in blob(panel) and "srcB" not in blob(panel).lower()
    assert not hasattr(panel, "hidden_count") and not hasattr(panel, "total")


def test_tc120_panel_state_is_computed_from_in_scope_rows_only(w):
    # the global matrix is INCOMPLETE (both companies have an open claim); viewer A has no open claim
    claims = (Claim("cA", A, "purchases", "validate"), Claim("SECRET-cB-open", B, "sales", "validate"))
    matrix = build_matrix(claims, (Evidence("eA", A, "s", h(1), PASS),), (Link("cA", "eA"),))
    assert matrix.status is CoverageStatus.INCOMPLETE
    panel = build_coverage_panel(w.viewer, w.authority, matrix)
    assert panel.status is CoverageStatus.COMPLETE and panel.code is CoverageCode.OK
    assert panel.uncovered == () and panel.hidden_by_scope is True
    assert "SECRET" not in blob(panel)


def test_tc120_panel_without_foreign_rows_has_flag_false(w):
    matrix = build_matrix(w.claims[:2], w.evidence[:1], w.links[:1])
    assert build_coverage_panel(w.viewer, w.authority, matrix).hidden_by_scope is False


def test_tc120_hidden_flag_does_not_depend_on_how_many_foreign_rows_exist(w):
    def panel_with(n):
        claims = (Claim("cA", A, "purchases", "validate"),) + tuple(
            Claim(f"SECRET-{i}", B, f"cap{i}", "validate") for i in range(n))
        ev = (Evidence("eA", A, "s", h(1), PASS),) + tuple(
            Evidence(f"SECRET-e{i}", B, f"src{i}", h(100 + i), PASS) for i in range(n))
        links = (Link("cA", "eA"),) + tuple(Link(f"SECRET-{i}", f"SECRET-e{i}") for i in range(n))
        return build_coverage_panel(w.viewer, w.authority, build_matrix(claims, ev, links))

    one, many = panel_with(1), panel_with(7)
    assert one.hidden_by_scope is many.hidden_by_scope is True
    assert one.digest == many.digest


def test_tc120_stale_epoch_gives_safe_error_for_every_builder(w):
    w.epochs[("t1", "A")] = 9
    outs = [
        build_coverage_panel(w.viewer, w.authority, w.matrix),
        build_scoped_evidence(w.viewer, w.authority, w.claims, w.evidence, w.links),
        build_scoped_diff(w.viewer, w.authority, RunLedger(SnapshotStore()), ()),
    ]
    for out in outs:
        assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


@pytest.mark.parametrize("lookup", [lambda t, c: None, lambda t, c: True, lambda t, c: LyingInt(5),
                                    lambda t, c: 5.0, lambda t, c: 1 / 0])
def test_tc120_unusable_epoch_is_stale_never_disclosure(w, lookup):
    out = build_coverage_panel(w.viewer, ScopeAuthority(lookup), w.matrix)
    assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


def test_tc120_revoke_between_build_and_render_is_rechecked(w):
    views = [
        build_coverage_panel(w.viewer, w.authority, w.matrix),
        build_scoped_evidence(w.viewer, w.authority, w.claims, w.evidence, w.links),
        build_scoped_diff(w.viewer, w.authority, RunLedger(SnapshotStore()), ()),
    ]
    for v in views:
        assert render_guard_coverage(v, w.authority) is v
    w.epochs[("t1", "A")] = 6
    for v in views:
        out = render_guard_coverage(v, w.authority)
        assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


def test_tc120_epoch_flip_during_build_is_caught_by_final_recheck(w):
    calls = itertools.count()
    auth = ScopeAuthority(lambda t, c: 5 if next(calls) == 0 else 6)
    out = build_coverage_panel(w.viewer, auth, w.matrix)
    assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


def test_tc120_render_guard_refuses_forged_foreign_and_unknown_views(w):
    panel = build_coverage_panel(w.viewer, w.authority, w.matrix)
    for bad in (None, "p", 1, object(), object.__new__(CoveragePanel), object.__new__(ScopedDiffView),
                object.__new__(ScopedEvidenceView), [panel]):
        assert type(render_guard_coverage(bad, w.authority)) is SafeError
    assert type(render_guard_coverage(panel, object())) is SafeError
    assert type(render_guard_coverage(panel, object.__new__(ScopeAuthority))) is SafeError


# ---- scoped evidence
def test_tc120_evidence_view_has_only_in_scope_evidence_and_no_source_names(w):
    view = build_scoped_evidence(w.viewer, w.authority, w.claims, w.evidence, w.links)
    assert type(view) is ScopedEvidenceView
    assert [(i.evidence_id, i.verdict, i.claim_ids) for i in view.items] == [("eA1", PASS, ("cA-covered",))]
    assert view.hidden_by_scope is True
    text = blob(view)
    assert "SECRET" not in text and "srcA" not in text  # not even in-scope source refs are exposed
    assert not hasattr(view.items[0], "source_ref") and view.items[0].digest == h(1)


def test_tc120_cross_company_link_is_not_rendered_even_as_an_id(w):
    # an A claim linked to B's evidence (and the reverse) must not surface either id
    claims = (Claim("cA", A, "purchases", "validate"), Claim("SECRET-cB", B, "purchases", "validate"))
    evidence = (Evidence("eA", A, "s", h(1), PASS), Evidence("SECRET-eB", B, "s", h(2), PASS))
    links = (Link("cA", "eA"), Link("cA", "SECRET-eB"), Link("SECRET-cB", "eA"), Link("SECRET-cB", "SECRET-eB"))
    view = build_scoped_evidence(w.viewer, w.authority, claims, evidence, links)
    assert type(view) is SafeError or "SECRET" not in blob(view)
    if type(view) is ScopedEvidenceView:
        assert [i.evidence_id for i in view.items] == ["eA"]
        assert view.items[0].claim_ids == ("cA",)
        assert view.hidden_by_scope is True


def test_tc120_non_pass_evidence_is_shown_with_its_verdict_in_scope(w):
    evidence = (Evidence("eA1", A, "srcA", h(1), FAIL),)
    view = build_scoped_evidence(w.viewer, w.authority, w.claims[:1], evidence, (Link("cA-covered", "eA1"),))
    assert view.items[0].verdict is FAIL and view.hidden_by_scope is False


# ---- scoped diff
class DiffWorld:
    def __init__(self):
        self.now = T0 + timedelta(days=10)
        self.store = SnapshotStore(lambda: self.now)
        self.ledger = RunLedger(self.store)
        self.epochs = {("t1", "A"): 5, ("t1", "B"): 5, ("t2", "A"): 5}
        self.authority = ScopeAuthority(lambda t, c: self.epochs.get((t, c)))
        self.viewer = ViewerScope("t1", "A", 5)

    def fail_run(self, key, native, gateway, tenant="t1", **kw):
        snap = self.store.create(tenant, {"values": {"native": native, "gateway": gateway}, "k": key},
                                 known_at=T0)

        def read(side):
            return SideRead(side, snap.snapshot_id, snap.digest, _projection(snap, side))
        return self.ledger.run(tenant, key, read("native"), read("gateway"), snapshot_id=snap.snapshot_id, **kw)


def test_tc120_diff_view_has_only_in_scope_runs_exact_numbers_and_no_foreign_keys():
    d = DiffWorld()
    run = d.fail_run("KEY-A", {"debit": Decimal("0.10"), "credit": Decimal(5)},
                     {"debit": Decimal("0.30"), "credit": Decimal(5)})
    d.fail_run("SECRET-KEY-B", {"x": Decimal(1)}, {"x": Decimal(2)})
    d.fail_run("SECRET-KEY-OTHER-TENANT", {"x": Decimal(1)}, {"x": Decimal(2)}, tenant="t2")
    subs = (TimelineSubject("t1", "A", "KEY-A", ()), TimelineSubject("t1", "B", "SECRET-KEY-B", ()),
            TimelineSubject("t2", "A", "SECRET-KEY-OTHER-TENANT", ()))
    view = build_scoped_diff(d.viewer, d.authority, d.ledger, subs)
    assert type(view) is ScopedDiffView
    assert [(i.run_id, i.measure, i.native, i.gateway, i.run_status) for i in view.items] == [
        (run.run_id, "debit", Decimal("0.10"), Decimal("0.30"), "CURRENT")]
    assert all(type(i.native) is Decimal and type(i.gateway) is Decimal for i in view.items)
    assert view.hidden_by_scope is True and "SECRET" not in blob(view)


def test_tc120_diff_view_lists_superseded_run_differences_with_status():
    d = DiffWorld()
    first = d.fail_run("KEY-A", {"m": Decimal(1)}, {"m": Decimal(2)})
    second = d.fail_run("KEY-A", {"m": Decimal(2)}, {"m": Decimal(4)}, rerun_of=first.run_id)
    view = build_scoped_diff(d.viewer, d.authority, d.ledger, (TimelineSubject("t1", "A", "KEY-A", ()),))
    assert {(i.run_id, i.run_status) for i in view.items} == {
        (first.run_id, "SUPERSEDED"), (second.run_id, "CURRENT")}
    assert view.hidden_by_scope is False


def test_diff_view_ledger_that_raises_never_leaks_poison():
    d = DiffWorld()

    class Boom(RunLedger):
        def list_runs(self, *a):
            raise RuntimeError("POISON-FOREIGN stack secret=abc")

    out = build_scoped_diff(d.viewer, d.authority, Boom(d.store), (TimelineSubject("t1", "A", "K", ()),))
    assert type(out) is SafeError and "POISON" not in repr(out)


# ===================================================== hostile input (S6b lesson rows)
HOSTILE = [None, "x", "", 1, 2**200, 1.5, b"b", object(), [], {}, LyingStr("t1"), LyingInt(5), True]
_REC: list = []
_REC.append(_REC)
HOSTILE.append(_REC)


@pytest.mark.parametrize("bad", HOSTILE, ids=lambda v: type(v).__name__ + str(id(v) % 89))
@pytest.mark.parametrize("arg", ["viewer", "authority", "matrix"])
def test_hostile_panel_arguments_are_refused_never_raise(w, arg, bad):
    args = {"viewer": w.viewer, "authority": w.authority, "matrix": w.matrix}
    args[arg] = bad
    out = build_coverage_panel(**args)
    assert type(out) is SafeError and out.authority == "EVALUATION_ONLY"


@pytest.mark.parametrize("bad", HOSTILE, ids=lambda v: type(v).__name__ + str(id(v) % 89))
@pytest.mark.parametrize("arg", ["viewer", "authority", "claims", "evidence", "links"])
def test_hostile_evidence_arguments_are_refused_never_raise(w, arg, bad):
    args = {"viewer": w.viewer, "authority": w.authority, "claims": w.claims, "evidence": w.evidence,
            "links": w.links}
    args[arg] = bad
    assert type(build_scoped_evidence(**args)) is SafeError


@pytest.mark.parametrize("bad", HOSTILE, ids=lambda v: type(v).__name__ + str(id(v) % 89))
@pytest.mark.parametrize("arg", ["viewer", "authority", "ledger", "subjects"])
def test_hostile_diff_arguments_are_refused_never_raise(arg, bad):
    d = DiffWorld()
    args = {"viewer": d.viewer, "authority": d.authority, "ledger": d.ledger, "subjects": ()}
    args[arg] = bad
    assert type(build_scoped_diff(**args)) is SafeError


def test_hostile_elements_inside_tuples_are_refused_not_skipped(w):
    for bad in (None, "x", object(), object.__new__(Claim)):
        assert type(build_scoped_evidence(w.viewer, w.authority, w.claims + (bad,), w.evidence, w.links)) is SafeError
        assert type(build_scoped_evidence(w.viewer, w.authority, w.claims, w.evidence + (bad,), w.links)) is SafeError
        assert type(build_scoped_evidence(w.viewer, w.authority, w.claims, w.evidence, w.links + (bad,))) is SafeError
    forged_row_matrix = w.matrix.__class__(w.matrix.status, w.matrix.code, (object(),), (), w.matrix.digest)
    assert type(build_coverage_panel(w.viewer, w.authority, forged_row_matrix)) is SafeError
    lying_status = w.matrix.__class__("COMPLETE", w.matrix.code, w.matrix.rows, (), "d")  # type: ignore[arg-type]
    assert type(build_coverage_panel(w.viewer, w.authority, lying_status)) is SafeError
    assert type(build_coverage_panel(w.viewer, w.authority, object.__new__(w.matrix.__class__))) is SafeError


def test_hostile_forged_viewer_authority_and_subjects_are_refused(w):
    d = DiffWorld()
    assert type(build_coverage_panel(object.__new__(ViewerScope), w.authority, w.matrix)) is SafeError
    assert type(build_coverage_panel(w.viewer, object.__new__(ScopeAuthority), w.matrix)) is SafeError
    out = build_scoped_diff(d.viewer, d.authority, d.ledger, (object.__new__(TimelineSubject),))
    assert type(out) is SafeError


def test_poison_text_in_claims_and_evidence_never_reaches_a_refusal(w):
    bad = Claim("POISON-secret-ref\x00", A, "purchases", "validate")
    out = build_scoped_evidence(w.viewer, w.authority, (bad,), w.evidence, w.links)
    assert type(out) is SafeError and "POISON" not in repr(out)
    out = build_scoped_evidence(w.viewer, w.authority, w.claims, (Evidence("e", A, "POISON-src", "nothex",
                                                                           PASS),), w.links)
    assert type(out) is SafeError and "POISON" not in repr(out)


def test_correlation_id_is_injected_and_validated(w):
    w.epochs[("t1", "A")] = 9
    assert build_coverage_panel(w.viewer, w.authority, w.matrix, correlation_id="CORR-7").correlation_id == "CORR-7"
    assert build_coverage_panel(w.viewer, w.authority, w.matrix, correlation_id="a b").correlation_id == "CORR-UNASSIGNED"


# ===================================================== TC118/TC119 coverage panel content
def test_panel_lists_covered_uncovered_and_non_pass_with_fixed_codes(w):
    claims = (Claim("cA-ok", A, "purchases", "validate"), Claim("cA-open", A, "sales", "validate"),
              Claim("cA-bad", A, "stock", "validate"))
    evidence = (Evidence("e1", A, "s1", h(1), PASS), Evidence("e2", A, "s2", h(2), FAIL))
    matrix = build_matrix(claims, evidence, (Link("cA-ok", "e1"), Link("cA-bad", "e2")))
    panel = build_coverage_panel(w.viewer, w.authority, matrix)
    assert panel.status is CoverageStatus.INCOMPLETE and type(panel.code) is CoverageCode
    assert [c.claim_id for c in panel.covered] == ["cA-ok"]
    assert set(panel.uncovered) == {"cA-open", "cA-bad"} and panel.non_pass == ("cA-bad",)
    assert panel.complete is False


def test_panel_complete_only_when_every_in_scope_claim_is_covered(w):
    matrix = build_matrix(w.claims[:1], w.evidence[:1], w.links[:1])
    panel = build_coverage_panel(w.viewer, w.authority, matrix)
    assert panel.complete is True and panel.status is CoverageStatus.COMPLETE


def test_panel_refused_matrix_is_shown_refused_with_no_rows(w):
    panel = build_coverage_panel(w.viewer, w.authority, build_matrix((), (), ()))
    assert panel.status is CoverageStatus.REFUSED and panel.complete is False
    assert panel.covered == () and panel.uncovered == ()


def test_views_are_deterministic_frozen_and_evaluation_only(w):
    a = build_coverage_panel(w.viewer, w.authority, w.matrix)
    b = build_coverage_panel(w.viewer, w.authority, w.matrix)
    assert a == b and a.digest == b.digest and len(a.digest) == 64
    ev = build_scoped_evidence(w.viewer, w.authority, w.claims, w.evidence, w.links)
    for v, attr in ((a, "authority"), (ev, "authority"), (a.covered[0], "claim_id"), (ev.items[0], "digest")):
        assert not hasattr(v, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(v, attr, "x")
    assert a.authority == ev.authority == "EVALUATION_ONLY"
    assert "offline" in a.basis.lower() and "not a gate" in a.basis.lower()
    assert EvidenceItem.__slots__


def test_constructors_refuse_inconsistent_values_with_fixed_codes():
    with pytest.raises(ValueError, match="^EVIDENCE_ITEM_INVALID$"):
        EvidenceItem("e", "PASS", h(1), ())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="^EVIDENCE_ITEM_INVALID$"):
        EvidenceItem("e", PASS, "not-a-digest", ())


# ===================================================== module boundary (static)
def test_module_imports_only_stdlib_and_sibling_phase2_and_never_opens_a_capability():
    src = Path(cv.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = {"__future__", "collections", "dataclasses", "datetime", "enum", "typing", "decimal"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {a.name.split(".")[0] for a in node.names} <= allowed
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert (node.module or "").split(".")[0] in allowed
        elif isinstance(node, ast.Name):
            assert node.id not in {"open", "capability_enabled", "operation_covered"}
    assert "capability_enabled" not in src and "operation_covered" not in src
