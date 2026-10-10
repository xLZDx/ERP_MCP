"""S8 review fix batch G1: company boundary, epoch authority, original-number binding, quotas, rerun split."""
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from business_ai_gateway.phase2 import workbench_review as wr
from business_ai_gateway.phase2.comparison_snapshot import RunLedger, SideRead, SnapshotStore
from business_ai_gateway.phase2.reconciliation import Comparison, ComparisonState, Difference
from business_ai_gateway.phase2.workbench_review import (
    AnnotationEntry,
    CardsResult,
    DiscrepancyCard,
    RerunOutcome,
    RerunPlan,
    ReviewLog,
    build_cards,
    check_rerun,
    commit_rerun,
    request_override,
    request_rerun,
    verify_original,
)
from business_ai_gateway.phase2.workbench_types import (
    AnnotationKind,
    FakeOwnership,
    OwnerDirectory,
    ReasonCode,
    SafeError,
    ViewerScope,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
KEY_A, KEY_B = "key-A", "key-B"


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class Clock:
    def __call__(self):
        return T0 + timedelta(days=10)


def vals(**kw):
    return {k: Decimal(v) for k, v in kw.items()}


class Env:
    """One tenant t1, two companies: cA owns KEY_A, cB owns KEY_B."""

    def __init__(self):
        self.store = SnapshotStore(Clock())
        self.ledger = RunLedger(self.store)
        self.log = ReviewLog(lambda: T0 + timedelta(days=11))
        self.own = FakeOwnership()
        self.epoch = 1
        self.ep = lambda: self.epoch
        self.va, self.vb = ViewerScope("t1", "cA", 1), ViewerScope("t1", "cB", 1)
        self.owners = OwnerDirectory((("t1", "cA", "srcA", "owner-a"), ("t1", "cB", "srcB", "owner-b")))
        self.runs = {}
        self.reader_calls = 0
        self.run_for("cA", KEY_A, "srcA")
        self.run_for("cB", KEY_B, "srcB")

    def kw(self, **extra):
        base = {"ownership": self.own, "current_epoch": self.ep}
        base.update(extra)
        return base

    def snap(self, company, n, g, known_at=T0):
        s = self.store.create("t1", {"values": {"native": n, "gateway": g}}, known_at=known_at)
        self.own.add("t1", company, "snapshot_id", s.snapshot_id)
        return s

    def run_for(self, company, key, src, n=None, g=None):
        n = n or vals(m="1", k="5")
        g = g or vals(m="2", k="5")
        self.own.add("t1", company, "comparison_key", key)
        self.own.add("t1", company, "source_id", src)
        s = self.snap(company, n, g)
        run = self.ledger.run("t1", key, SideRead("native", s.snapshot_id, s.digest, n),
                              SideRead("gateway", s.snapshot_id, s.digest, g), snapshot_id=s.snapshot_id)
        self.own.add("t1", company, "run_id", run.run_id)
        self.runs[key] = run
        return run

    def reader(self, tenant, snapshot_id):
        self.reader_calls += 1
        s = self.store.get(tenant, snapshot_id)
        doc = json.loads(s.canonical)["values"]
        n = {k: Decimal(v["$dec"]) for k, v in doc["native"].items()}
        g = {k: Decimal(v["$dec"]) for k, v in doc["gateway"].items()}
        return (SideRead("native", s.snapshot_id, s.digest, n), SideRead("gateway", s.snapshot_id, s.digest, g))

    def cards(self, viewer, key, src, **kw):
        return build_cards(self.ledger, "t1", key, self.owners, viewer, source_id=src, **self.kw(**kw))

    def rerun_args(self, viewer, key, run_id, snap_id):
        return (self.ledger, self.store, self.log, viewer, "t1", key, run_id, snap_id)


@pytest.fixture
def e():
    return Env()


def refusal(res, code):
    assert isinstance(res, SafeError), res
    assert res.reason_code is code


# ---- 1. company boundary -----------------------------------------------------------------------------

def test_b_cannot_read_annotate_or_rerun_a_and_unknown_is_identical(e):
    run_a = e.runs[KEY_A]
    snap_new = e.snap("cB", vals(m="2", k="5"), vals(m="2", k="5"), T0 + timedelta(days=1))
    before_runs = len(e.ledger.list_runs("t1", KEY_A))
    foreign, unknown = [], []
    # cards
    foreign.append(e.cards(e.vb, KEY_A, "srcB"))
    unknown.append(e.cards(e.vb, "no-such-key", "srcB"))
    # annotate
    foreign.append(e.log.add(e.ledger, e.vb, "t1", run_a.run_id, AnnotationKind.NOTE, "x", actor_id="bob", **e.kw()))
    unknown.append(e.log.add(e.ledger, e.vb, "t1", "run-999999", AnnotationKind.NOTE, "x", actor_id="bob", **e.kw()))
    # annotations
    foreign.append(e.log.entries(e.vb, "t1", run_a.run_id, **e.kw()))
    unknown.append(e.log.entries(e.vb, "t1", "run-999999", **e.kw()))
    # rerun
    foreign.append(request_rerun(*e.rerun_args(e.vb, KEY_A, run_a.run_id, snap_new.snapshot_id), e.reader,
                                 actor_id="bob", **e.kw()))
    unknown.append(request_rerun(*e.rerun_args(e.vb, "no-such-key", "run-999999", snap_new.snapshot_id), e.reader,
                                 actor_id="bob", **e.kw()))
    # verify (a card of A shown to B)
    card_a = e.cards(e.va, KEY_A, "srcA").cards[0]
    assert verify_original(card_a, e.ledger, e.vb, **e.kw()) is ReasonCode.NOT_IN_SCOPE
    forged_unknown = dataclasses.replace(card_a, run_id="run-999999", comparison_key="no-such-key")
    assert verify_original(forged_unknown, e.ledger, e.vb, **e.kw()) is ReasonCode.NOT_IN_SCOPE
    for f, u in zip(foreign, unknown, strict=True):
        assert f == u and isinstance(f, SafeError) and f.reason_code is ReasonCode.NOT_IN_SCOPE
    assert len(e.ledger.list_runs("t1", KEY_A)) == before_runs and e.reader_calls == 0
    assert e.log.entries(e.va, "t1", run_a.run_id, **e.kw()) == ()
    # B still works on its own key
    mine = e.cards(e.vb, KEY_B, "srcB")
    assert isinstance(mine, CardsResult) and mine.run_state == "FAIL" and mine.cards[0].owner_id == "owner-b"
    run_b = e.runs[KEY_B]
    assert isinstance(e.log.add(e.ledger, e.vb, "t1", run_b.run_id, AnnotationKind.NOTE, "ok", actor_id="bob",
                                **e.kw()), AnnotationEntry)
    out = request_rerun(*e.rerun_args(e.vb, KEY_B, run_b.run_id, snap_new.snapshot_id), e.reader,
                        actor_id="bob", **e.kw())
    assert isinstance(out, RerunOutcome)


def test_foreign_source_and_foreign_snapshot_are_refused_before_ledger_read(e):
    e.own.add("t1", "cB", "comparison_key", KEY_A)  # B owns the key but not A's source
    refusal(e.cards(e.vb, KEY_A, "srcA"), ReasonCode.NOT_IN_SCOPE)
    snap_a = e.snap("cA", vals(m="3"), vals(m="3"), T0 + timedelta(days=1))
    refusal(request_rerun(*e.rerun_args(e.vb, KEY_B, e.runs[KEY_B].run_id, snap_a.snapshot_id), e.reader,
                          actor_id="bob", **e.kw()), ReasonCode.NOT_IN_SCOPE)


def test_ownership_port_failure_is_dependency_failed_not_in_scope(e):
    class Boom:
        def owns(self, *a):
            raise RuntimeError("POISON")

    res = e.cards(e.va, KEY_A, "srcA", ownership=Boom())
    refusal(res, ReasonCode.DEPENDENCY_FAILED)
    assert "POISON" not in repr(res)
    for bad in (None, 5, "x", object()):
        refusal(e.cards(e.va, KEY_A, "srcA", ownership=bad), ReasonCode.INPUT_INVALID)


def test_cards_distinguish_no_run_pass_inconclusive_fail(e):
    e.own.add("t1", "cA", "comparison_key", "empty")
    none = e.cards(e.va, "empty", "srcA")
    assert (none.run_state, none.run_id, none.cards) == ("NO_RUN", None, ())
    fail = e.cards(e.va, KEY_A, "srcA")
    assert fail.run_state == "FAIL" and len(fail.cards) == 1 and fail.run_id == e.runs[KEY_A].run_id
    e.run_for("cA", "passk", "srcA", vals(m="1"), vals(m="1"))
    ok = e.cards(e.va, "passk", "srcA")
    assert ok.run_state == "PASS" and ok.cards == ()
    s = e.snap("cA", vals(m="1"), vals(m="1"))
    e.own.add("t1", "cA", "comparison_key", "incon")
    e.ledger.run("t1", "incon", SideRead("native", s.snapshot_id, s.digest, vals(m="1")),
                 SideRead("gateway", s.snapshot_id, "0" * 64, vals(m="1")), snapshot_id=s.snapshot_id)
    inc = e.cards(e.va, "incon", "srcA")
    assert inc.run_state == "INCONCLUSIVE" and inc.cards == ()
    assert len({none.run_state, fail.run_state, ok.run_state, inc.run_state}) == 4


# ---- 2. epoch authority -------------------------------------------------------------------------------

def test_epoch_authority_is_required_everywhere(e):
    run = e.runs[KEY_A]
    snap_new = e.snap("cA", vals(m="2"), vals(m="2"), T0 + timedelta(days=1))
    with pytest.raises(TypeError):
        build_cards(e.ledger, "t1", KEY_A, e.owners, e.va, source_id="srcA", ownership=e.own)
    with pytest.raises(TypeError):
        e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "x", actor_id="a", ownership=e.own)
    with pytest.raises(TypeError):
        e.log.entries(e.va, "t1", run.run_id, ownership=e.own)
    with pytest.raises(TypeError):
        request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), e.reader, actor_id="a",
                      ownership=e.own)
    with pytest.raises(TypeError):
        verify_original(None, e.ledger, e.va, ownership=e.own)
    for bad in (None, 1, "1", object()):
        refusal(e.cards(e.va, KEY_A, "srcA", current_epoch=bad), ReasonCode.INPUT_INVALID)
    refusal(e.cards(e.va, KEY_A, "srcA", current_epoch=lambda: 2), ReasonCode.SCOPE_EPOCH_STALE)
    refusal(e.cards(e.va, KEY_A, "srcA", current_epoch=lambda: (_ for _ in ()).throw(RuntimeError())),
            ReasonCode.DEPENDENCY_FAILED)


class Bumping:
    """Epoch authority that moves after ``n`` reads (the scope changes while the call is running)."""

    def __init__(self, n):
        self.n, self.calls = n, 0

    def __call__(self):
        self.calls += 1
        return 1 if self.calls <= self.n else 2


def test_epoch_moving_during_read_returns_no_data(e):
    run = e.runs[KEY_A]
    refusal(e.cards(e.va, KEY_A, "srcA", current_epoch=Bumping(1)), ReasonCode.SCOPE_EPOCH_STALE)
    assert isinstance(e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "n", actor_id="a",
                                **e.kw()), AnnotationEntry)
    refusal(e.log.entries(e.va, "t1", run.run_id, **e.kw(current_epoch=Bumping(1))), ReasonCode.SCOPE_EPOCH_STALE)
    refusal(e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "m", actor_id="a",
                      **e.kw(current_epoch=Bumping(1))), ReasonCode.SCOPE_EPOCH_STALE)
    assert len(e.log.entries(e.va, "t1", run.run_id, **e.kw())) == 1  # the stale add wrote nothing
    card = e.cards(e.va, KEY_A, "srcA").cards[0]
    assert verify_original(card, e.ledger, e.va, **e.kw(current_epoch=Bumping(1))) is ReasonCode.SCOPE_EPOCH_STALE


def test_reader_that_bumps_the_epoch_creates_no_run(e):
    run = e.runs[KEY_A]
    snap_new = e.snap("cA", vals(m="2", k="5"), vals(m="2", k="5"), T0 + timedelta(days=1))

    def bumping_reader(tenant, snapshot_id):
        e.epoch = 2
        return e.reader(tenant, snapshot_id)

    res = request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), bumping_reader,
                        actor_id="a", **e.kw())
    refusal(res, ReasonCode.SCOPE_EPOCH_STALE)
    assert len(e.ledger.list_runs("t1", KEY_A)) == 1
    e.epoch = 1
    assert e.log.entries(e.va, "t1", run.run_id, **e.kw()) == ()


# ---- 3. comparison binding ------------------------------------------------------------------------------

def test_fabricated_comparison_numbers_never_give_original_intact(e):
    fabricated = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference(("r", "c"), "m", Decimal(1), Decimal(1000000)),))
    res = e.cards(e.va, KEY_A, "srcA", comparison=fabricated)
    assert res.cards[0].basis == wr.BASIS_COMPARISON
    assert verify_original(res.cards[0], e.ledger, e.va, **e.kw()) is ReasonCode.ORIGINAL_UNVERIFIABLE
    totals_fab = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference(None, "m", Decimal(1), Decimal(1000000)),))
    card = e.cards(e.va, KEY_A, "srcA", comparison=totals_fab).cards[0]
    assert verify_original(card, e.ledger, e.va, **e.kw()) is ReasonCode.ORIGINAL_UNVERIFIABLE
    honest = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference(None, "m", Decimal(1), Decimal(2)),))
    card = e.cards(e.va, KEY_A, "srcA", comparison=honest).cards[0]
    assert verify_original(card, e.ledger, e.va, **e.kw()) is ReasonCode.ORIGINAL_INTACT  # recomputed


def test_comparison_must_match_the_runs_measure_set_exactly(e):
    for measures in (("other",), ("m", "other"), ("k",)):
        comp = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", tuple(
            Difference(None, m, Decimal(1), Decimal(2)) for m in measures))
        refusal(e.cards(e.va, KEY_A, "srcA", comparison=comp), ReasonCode.INPUT_INVALID)
    dup = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference(("r", "c"), "m", Decimal(1), Decimal(2)), Difference(("r", "c"), "m", Decimal(1), Decimal(3))))
    refusal(e.cards(e.va, KEY_A, "srcA", comparison=dup), ReasonCode.INPUT_INVALID)


@pytest.mark.parametrize("field,value", [
    ("owner_id", "someone-else"), ("run_status", "SUPERSEDED"), ("row_detail", None), ("basis", "COMPARISON"),
    ("owner_note", ReasonCode.OWNER_UNASSIGNED),
])
def test_card_digest_covers_owner_status_row_detail_basis(e, field, value):
    card = e.cards(e.va, KEY_A, "srcA").cards[0]
    forged = dataclasses.replace(card, **{field: value})
    assert verify_original(forged, e.ledger, e.va, **e.kw()) is ReasonCode.ORIGINAL_TAMPERED


# ---- 4. quotas ---------------------------------------------------------------------------------------------

def test_tenant_quota_does_not_block_another_tenant(e):
    log = ReviewLog(lambda: T0, max_per_run=100, max_per_tenant=3, max_total=10)
    run_a = e.runs[KEY_A]
    for _ in range(3):
        assert isinstance(log.add(e.ledger, e.va, "t1", run_a.run_id, AnnotationKind.ACKNOWLEDGED, actor_id="a",
                                  **e.kw()), AnnotationEntry)
    refusal(log.add(e.ledger, e.va, "t1", run_a.run_id, AnnotationKind.ACKNOWLEDGED, actor_id="a", **e.kw()),
            ReasonCode.RATE_LIMITED)
    # a second tenant on the same log still annotates and reruns
    s2 = e.store.create("t2", {"values": {"native": vals(m="1"), "gateway": vals(m="2")}}, known_at=T0)
    r2 = e.ledger.run("t2", "k2", SideRead("native", s2.snapshot_id, s2.digest, vals(m="1")),
                      SideRead("gateway", s2.snapshot_id, s2.digest, vals(m="2")), snapshot_id=s2.snapshot_id)
    for kind, ref in (("comparison_key", "k2"), ("run_id", r2.run_id)):
        e.own.add("t2", "cX", kind, ref)
    vt2 = ViewerScope("t2", "cX", 1)
    entry = log.add(e.ledger, vt2, "t2", r2.run_id, AnnotationKind.NOTE, "hi", actor_id="z", **e.kw())
    assert isinstance(entry, AnnotationEntry) and entry.seq == 1  # per-tenant sequence, no cross-tenant count
    s3 = e.store.create("t2", {"values": {"native": vals(m="2"), "gateway": vals(m="2")}}, known_at=T0)
    e.own.add("t2", "cX", "snapshot_id", s3.snapshot_id)
    out = request_rerun(e.ledger, e.store, log, vt2, "t2", "k2", r2.run_id, s3.snapshot_id, e.reader,
                        actor_id="z", **e.kw())
    assert isinstance(out, RerunOutcome), out


def test_run_quota_and_rerun_rate_limited_is_distinct(e):
    log = ReviewLog(lambda: T0, max_per_run=1)
    run = e.runs[KEY_A]
    e.log = log
    assert isinstance(log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "x", actor_id="a", **e.kw()),
                      AnnotationEntry)
    snap_new = e.snap("cA", vals(m="2"), vals(m="2"), T0 + timedelta(days=1))
    res = request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), e.reader, actor_id="a",
                        **e.kw())
    refusal(res, ReasonCode.RATE_LIMITED)
    assert len(e.ledger.list_runs("t1", KEY_A)) == 1 and e.reader_calls == 0
    for bad in (0, -1, True, None, "5"):
        with pytest.raises(ValueError, match="REVIEW_LOG_INVALID"):
            ReviewLog(max_per_run=bad)


# ---- 5. rerun split and distinct codes ------------------------------------------------------------------

def test_check_rerun_is_pure_and_commit_creates_the_run(e):
    run = e.runs[KEY_A]
    snap_new = e.snap("cA", vals(m="2", k="5"), vals(m="2", k="5"), T0 + timedelta(days=1))
    plan = check_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), **e.kw())
    assert isinstance(plan, RerunPlan)
    assert len(e.ledger.list_runs("t1", KEY_A)) == 1 and e.reader_calls == 0
    assert e.log.entries(e.va, "t1", run.run_id, **e.kw()) == ()
    out = commit_rerun(e.ledger, e.store, e.log, e.va, plan, e.reader, actor_id="alice", **e.kw())
    assert isinstance(out, RerunOutcome) and out.previous_run_id == run.run_id and out.annotated is True
    entry = e.log.entries(e.va, "t1", run.run_id, **e.kw())[0]
    assert entry.kind is AnnotationKind.RERUN_REQUESTED and entry.actor_id == "alice"
    assert entry.related_run_id == out.new_run_id
    # the plan is stale now: a second commit is refused, no second run
    refusal(commit_rerun(e.ledger, e.store, e.log, e.va, plan, e.reader, actor_id="alice", **e.kw()),
            ReasonCode.RERUN_TARGET_STALE)
    assert len(e.ledger.list_runs("t1", KEY_A)) == 2


def test_commit_rejects_forged_or_foreign_plans(e):
    run = e.runs[KEY_A]
    snap_new = e.snap("cA", vals(m="2"), vals(m="2"), T0 + timedelta(days=1))
    plan = check_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), **e.kw())
    for bad in (None, 5, object(), object.__new__(RerunPlan)):
        refusal(commit_rerun(e.ledger, e.store, e.log, e.va, bad, e.reader, actor_id="a", **e.kw()),
                ReasonCode.INPUT_INVALID)
    refusal(commit_rerun(e.ledger, e.store, e.log, e.vb, plan, e.reader, actor_id="b", **e.kw()),
            ReasonCode.NOT_IN_SCOPE)
    forged = dataclasses.replace(plan, snapshot_digest="0" * 64)
    refusal(commit_rerun(e.ledger, e.store, e.log, e.va, forged, e.reader, actor_id="a", **e.kw()),
            ReasonCode.RERUN_TARGET_STALE)
    assert len(e.ledger.list_runs("t1", KEY_A)) == 1 and e.reader_calls == 0


def test_rerun_outcomes_are_distinguishable(e):
    run = e.runs[KEY_A]
    snap_new = e.snap("cA", vals(m="2"), vals(m="2"), T0 + timedelta(days=1))
    a = request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id),
                      lambda t, s: (_ for _ in ()).throw(RuntimeError("POISON")), actor_id="a", **e.kw())
    refusal(a, ReasonCode.DEPENDENCY_FAILED)
    b = request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), lambda t, s: "junk",
                      actor_id="a", **e.kw())
    refusal(b, ReasonCode.DEPENDENCY_FAILED)
    e.own.add("t1", "cA", "snapshot_id", "snap-gone")
    refusal(request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, "snap-gone"), e.reader, actor_id="a", **e.kw()),
            ReasonCode.NOT_FOUND)
    refusal(request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), e.reader, actor_id="a",
                          **e.kw(current_epoch=lambda: 9)), ReasonCode.SCOPE_EPOCH_STALE)
    e.log = ReviewLog(lambda: (_ for _ in ()).throw(RuntimeError()))
    refusal(request_rerun(*e.rerun_args(e.va, KEY_A, run.run_id, snap_new.snapshot_id), e.reader, actor_id="a",
                          **e.kw()), ReasonCode.INTERNAL_REFUSED)
    assert len(e.ledger.list_runs("t1", KEY_A)) == 1


# ---- 6. ledger failure is not tampering ---------------------------------------------------------------------

def test_ledger_exception_is_not_tampered(e):
    card = e.cards(e.va, KEY_A, "srcA").cards[0]

    ledger = e.ledger
    real_get = RunLedger.get
    calls = {"n": 0}

    def flaky(self, tenant, run_id):
        calls["n"] += 1
        if calls["n"] > 1:  # the probe passes, the real read fails
            raise RuntimeError("POISON")
        return real_get(self, tenant, run_id)

    RunLedger.get = flaky  # type: ignore[method-assign]
    try:
        res = verify_original(card, ledger, e.va, **e.kw())
    finally:
        RunLedger.get = real_get  # type: ignore[method-assign]
    assert res is ReasonCode.INTERNAL_REFUSED
    assert verify_original(card, ledger, e.va, **e.kw()) is ReasonCode.ORIGINAL_INTACT


# ---- 7. exact-type conventions --------------------------------------------------------------------------------

def test_lying_eq_strings_are_refused_everywhere(e):
    card = e.cards(e.va, KEY_A, "srcA").cards[0]
    for field in ("run_status", "basis", "tenant_id", "run_id", "measure", "owner_id", "authority"):
        forged = object.__new__(DiscrepancyCard)
        for f in dataclasses.fields(DiscrepancyCard):
            object.__setattr__(forged, f.name, getattr(card, f.name))
        object.__setattr__(forged, field, EvilStr("x"))
        assert verify_original(forged, e.ledger, e.va, **e.kw()) is ReasonCode.ORIGINAL_TAMPERED, field
    with pytest.raises(ValueError, match="CARD_INVALID"):
        dataclasses.replace(card, run_status=EvilStr("NOPE"))
    with pytest.raises(ValueError, match="CARD_INVALID"):
        dataclasses.replace(card, basis=EvilStr("NOPE"))
    with pytest.raises(ValueError, match="CARD_INVALID"):
        dataclasses.replace(card, row_detail=EvilStr("x"))
    with pytest.raises(ValueError, match="CARD_INVALID"):
        dataclasses.replace(card, authority=EvilStr("x"))
    refusal(e.cards(e.va, EvilStr(KEY_A), "srcA"), ReasonCode.INPUT_INVALID)
    refusal(e.cards(e.va, KEY_A, EvilStr("srcA")), ReasonCode.INPUT_INVALID)
    refusal(request_override(EvilStr("x")), ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)


# ---- 8. decimals --------------------------------------------------------------------------------------------------

def test_card_refuses_non_finite_and_huge_decimals(e):
    card = e.cards(e.va, KEY_A, "srcA").cards[0]
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("1E+500")):
        for field in ("native", "gateway", "delta"):
            with pytest.raises(ValueError, match="CARD_INVALID"):
                dataclasses.replace(card, **{field: bad})


def test_comparison_value_with_huge_exponent_is_input_invalid(e):
    for bad in (Decimal("1E+500"), Decimal("1E-500"), Decimal("NaN")):
        comp = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
            Difference(None, "m", bad, Decimal(2)),))
        refusal(e.cards(e.va, KEY_A, "srcA", comparison=comp), ReasonCode.INPUT_INVALID)


# ---- 9. repr hygiene --------------------------------------------------------------------------------------------------

def test_reprs_show_no_field_values(e):
    run = e.runs[KEY_A]
    card = e.cards(e.va, KEY_A, "srcA").cards[0]
    entry = e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "SECRET-NOTE", actor_id="alice-actor",
                      **e.kw())
    result = e.cards(e.va, KEY_A, "srcA")
    for obj in (card, entry, e.owners, result, card.fragment):
        text = repr(obj)
        for needle in ("SECRET-NOTE", "alice-actor", "owner-a", "srcA", "Decimal", "key-A", card.original_digest):
            assert needle not in text, (type(obj).__name__, needle)


# ---- 10. never raises ---------------------------------------------------------------------------------------------------

def test_directory_from_mapping_and_review_log_hostile_keys_never_raise(e):
    class Key:
        def __lt__(self, other):
            raise RuntimeError("POISON")

    with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID"):
        OwnerDirectory.from_mapping({("t", "c", "s"): "o", ("t", "c", "s2"): Key()})
    for bad in (None, 1, EvilStr("t1"), object(), "", b"x"):
        assert isinstance(e.log.entries(e.va, bad, bad, **e.kw()), SafeError)
        assert isinstance(e.log.add(e.ledger, e.va, bad, bad, bad, bad, actor_id=bad, **e.kw()), SafeError)


# ---- 11. actor ------------------------------------------------------------------------------------------------------------

def test_annotation_records_actor_and_requires_exact_text(e):
    run = e.runs[KEY_A]
    entry = e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "x", actor_id="alice", **e.kw())
    assert entry.actor_id == "alice"
    for bad in (None, "", 5, EvilStr("a"), "a\x00"):
        refusal(e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "x", actor_id=bad, **e.kw()),
                ReasonCode.INPUT_INVALID)
    with pytest.raises(TypeError):
        e.log.add(e.ledger, e.va, "t1", run.run_id, AnnotationKind.NOTE, "x", **e.kw())
