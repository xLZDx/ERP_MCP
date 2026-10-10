"""S8 E1 R2-US-039: TC115 row/fragment/owner/delta, TC116 originals immutable, TC117 new evidence -> new run.

Hostile-input rows and the "cannot go green / cannot mutate the original" rows come before the happy path.
"""
import ast
import dataclasses
import inspect
import threading
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from business_ai_gateway.phase2 import workbench_review as wr
from business_ai_gateway.phase2.comparison_snapshot import RunLedger, SideRead, SnapshotStore
from business_ai_gateway.phase2.reconciliation import Comparison, ComparisonState, Difference
from business_ai_gateway.phase2.workbench_review import (
    AnnotationEntry,
    DiscrepancyCard,
    FragmentRef,
    RerunOutcome,
    ReviewLog,
    build_cards,
    request_override,
    request_rerun,
    verify_original,
)
from business_ai_gateway.phase2.workbench_types import (
    AUTHORITY,
    AnnotationKind,
    OwnerDirectory,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_safe_error,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
KEY = "tb:818HA:521.1:2026-08"
POISON = "POISON-secret-ref-SELECT-stack"


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilDec(Decimal):
    def __eq__(self, other):
        return True

    __hash__ = Decimal.__hash__


class Clock:
    def __init__(self):
        self.now = T0 + timedelta(days=10)

    def __call__(self):
        return self.now


def values(**kw):
    return {k: Decimal(v) for k, v in kw.items()}


def snap(store, native, gateway, *, tenant="t1", known_at=T0):
    return store.create(tenant, {"values": {"native": native, "gateway": gateway}}, known_at=known_at)


def reads(s, native, gateway):
    return (SideRead("native", s.snapshot_id, s.digest, dict(native)),
            SideRead("gateway", s.snapshot_id, s.digest, dict(gateway)))


_DEFAULT = object()


def _naive():
    return datetime(2026, 1, 1)  # noqa: DTZ001 - naive on purpose


class World:
    """Ledger + store + snapshots; ``reader`` replays the numbers frozen in the snapshot (the offline source)."""

    def __init__(self):
        self.store = SnapshotStore(Clock())
        self.ledger = RunLedger(self.store)
        self.log = ReviewLog(lambda: T0 + timedelta(days=11))
        self.owners = OwnerDirectory((("t1", "c1", "src1", "owner-a"),))
        self.viewer = ViewerScope("t1", "c1", 1)
        self.reader_calls = 0

    def first_run(self, native=None, gateway=None):
        n = native or values(closing_credit="0.1", turnover_debit="100.00")
        g = gateway or values(closing_credit="0.3", turnover_debit="100.5")
        s = snap(self.store, n, g)
        run = self.ledger.run("t1", KEY, *reads(s, n, g), snapshot_id=s.snapshot_id)
        return s, run

    def new_snapshot(self, native, gateway, known_at):
        return snap(self.store, native, gateway, known_at=known_at)

    def reader(self, tenant, snapshot_id):
        self.reader_calls += 1
        s = self.store.get(tenant, snapshot_id)
        import json
        doc = json.loads(s.canonical)["values"]
        n = {k: Decimal(v["$dec"]) for k, v in doc["native"].items()}
        g = {k: Decimal(v["$dec"]) for k, v in doc["gateway"].items()}
        return reads(s, n, g)

    def cards(self, **kw):
        kw.setdefault("source_id", "src1")
        return build_cards(self.ledger, "t1", KEY, self.owners, self.viewer, **kw)

    def rerun(self, prev, new_snapshot_id, reader=_DEFAULT, viewer=_DEFAULT, tenant="t1", **kw):
        viewer = self.viewer if viewer is _DEFAULT else viewer
        reader = self.reader if reader is _DEFAULT else reader
        return request_rerun(self.ledger, self.store, self.log, viewer, tenant, KEY, prev,
                             new_snapshot_id, reader, **kw)


@pytest.fixture
def w():
    return World()


# ===================================================================================================
# 1. hostile input: a fixed refusal, never an exception, never an echo
# ===================================================================================================

HOSTILE = [None, 5, b"x", EvilStr("t1"), "", "   ", "t\x001", "t\u200b1", "x" * 10_000, [POISON], object(),
           Decimal(1), T0, {POISON: 1}]


def _assert_refusal(result, *codes):
    assert isinstance(result, SafeError), result
    assert is_valid_safe_error(result)
    assert result.reason_code in codes
    assert POISON not in repr(result)


@pytest.mark.parametrize("bad", HOSTILE)
def test_build_cards_hostile_scalar_arguments_are_refused(w, bad):
    w.first_run()
    ok = (w.ledger, "t1", KEY, w.owners, w.viewer)
    for idx in (1, 2):
        args = list(ok)
        args[idx] = bad
        _assert_refusal(build_cards(*args, source_id="src1"), ReasonCode.INPUT_INVALID, ReasonCode.NOT_IN_SCOPE)
    _assert_refusal(build_cards(*ok, source_id=bad), ReasonCode.INPUT_INVALID)
    if bad is not None:  # None means "not supplied" for these three optional arguments
        _assert_refusal(build_cards(*ok, source_id="src1", run_id=bad), ReasonCode.INPUT_INVALID,
                        ReasonCode.NOT_IN_SCOPE)
        _assert_refusal(build_cards(*ok, source_id="src1", current_epoch=bad), ReasonCode.INPUT_INVALID,
                        ReasonCode.SCOPE_EPOCH_STALE)  # a stray exact int is a valid-typed but stale epoch
        _assert_refusal(build_cards(*ok, source_id="src1", comparison=bad), ReasonCode.INPUT_INVALID)


@pytest.mark.parametrize("bad", HOSTILE + [object.__new__(ViewerScope), object.__new__(OwnerDirectory),
                                          object.__new__(RunLedger)])
def test_build_cards_hostile_objects_are_refused(w, bad):
    w.first_run()
    _assert_refusal(build_cards(bad, "t1", KEY, w.owners, w.viewer, source_id="src1"), ReasonCode.INPUT_INVALID)
    _assert_refusal(build_cards(w.ledger, "t1", KEY, bad, w.viewer, source_id="src1"), ReasonCode.INPUT_INVALID)
    _assert_refusal(build_cards(w.ledger, "t1", KEY, w.owners, bad, source_id="src1"), ReasonCode.INPUT_INVALID)


def test_build_cards_subclass_viewer_and_directory_refused(w):
    w.first_run()

    class V(ViewerScope):
        pass

    class D(OwnerDirectory):
        pass

    _assert_refusal(build_cards(w.ledger, "t1", KEY, w.owners, V("t1", "c1", 1), source_id="src1"),
                    ReasonCode.INPUT_INVALID)
    _assert_refusal(build_cards(w.ledger, "t1", KEY, D(w.owners.entries), w.viewer, source_id="src1"),
                    ReasonCode.INPUT_INVALID)


def test_build_cards_comparison_hostile_contents_refused(w):
    w.first_run()
    good = Difference(("cp", "ct"), "closing_credit", Decimal(1), Decimal(2))
    bad_diffs = [
        Difference(("cp", "ct"), "closing_credit", EvilDec("1"), Decimal(2)),
        Difference(("cp", "ct"), "closing_credit", Decimal("NaN"), Decimal(2)),
        Difference(("cp", "ct"), "closing_credit", 1.5, Decimal(2)),
        Difference(("cp", "ct"), EvilStr("m"), Decimal(1), Decimal(2)),
        Difference(("cp", "ct"), "", Decimal(1), Decimal(2)),
        Difference(("cp",), "m", Decimal(1), Decimal(2)),
        Difference(("cp", None), "m", Decimal(1), Decimal(2)),
        Difference(("cp", "ct\x00"), "m", Decimal(1), Decimal(2)),
        "not a difference",
    ]
    for bad in bad_diffs:
        comp = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (good, bad))
        _assert_refusal(w.cards(comparison=comp), ReasonCode.INPUT_INVALID)
    forged = object.__new__(Comparison)
    _assert_refusal(w.cards(comparison=forged), ReasonCode.INPUT_INVALID)
    # a comparison with differences for a run that did not FAIL is inconsistent and refused
    w2 = World()
    s = w2.new_snapshot(values(closing_credit="1"), values(closing_credit="1"), T0)
    w2.ledger.run("t1", KEY, *reads(s, values(closing_credit="1"), values(closing_credit="1")),
                  snapshot_id=s.snapshot_id)
    comp = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (good,))
    _assert_refusal(w2.cards(comparison=comp), ReasonCode.INPUT_INVALID)


@pytest.mark.parametrize("bad", [None, 5, "x", object(), object.__new__(DiscrepancyCard), [], {}])
def test_verify_original_hostile_card_is_tampered_never_raises(w, bad):
    w.first_run()
    assert verify_original(bad, w.ledger) is ReasonCode.ORIGINAL_TAMPERED


@pytest.mark.parametrize("bad", [None, 5, "x", object(), object.__new__(RunLedger)])
def test_verify_original_hostile_ledger_is_tampered_never_raises(w, bad):
    w.first_run()
    card = w.cards()[0]
    assert verify_original(card, bad) is ReasonCode.ORIGINAL_TAMPERED


def test_forged_card_with_evil_values_is_tampered(w):
    w.first_run()
    card = w.cards()[0]
    forged = object.__new__(DiscrepancyCard)
    for f in dataclasses.fields(DiscrepancyCard):
        object.__setattr__(forged, f.name, getattr(card, f.name))
    assert verify_original(forged, w.ledger) is ReasonCode.ORIGINAL_INTACT  # a faithful forgery has no effect
    object.__setattr__(forged, "native", EvilDec("0.1"))  # lying __eq__ cannot pass
    assert verify_original(forged, w.ledger) is ReasonCode.ORIGINAL_TAMPERED
    object.__setattr__(forged, "native", card.native)
    object.__setattr__(forged, "tenant_id", EvilStr("t1"))
    assert verify_original(forged, w.ledger) is ReasonCode.ORIGINAL_TAMPERED


def test_foreign_tenant_and_stale_epoch_are_refused(w):
    w.first_run()
    other = ViewerScope("t2", "c1", 1)
    _assert_refusal(build_cards(w.ledger, "t1", KEY, w.owners, other, source_id="src1"), ReasonCode.NOT_IN_SCOPE)
    _assert_refusal(w.cards(current_epoch=2), ReasonCode.SCOPE_EPOCH_STALE)
    _assert_refusal(w.cards(current_epoch=True), ReasonCode.INPUT_INVALID)
    assert isinstance(w.cards(current_epoch=1), tuple)
    # a run id that is not this tenant's reads exactly like an unknown run (no existence leak)
    _assert_refusal(w.cards(run_id="run-999999"), ReasonCode.NOT_IN_SCOPE)


def test_foreign_tenant_run_is_not_disclosed(w):
    s = w.new_snapshot(values(a="1"), values(a="2"), T0)
    s2 = w.store.create("t2", {"values": {"native": values(a="1"), "gateway": values(a="2")}}, known_at=T0)
    run2 = w.ledger.run("t2", KEY, *reads(s2, values(a="1"), values(a="2")), snapshot_id=s2.snapshot_id)
    w.ledger.run("t1", KEY, *reads(s, values(a="1"), values(a="2")), snapshot_id=s.snapshot_id)
    res = w.cards(run_id=run2.run_id)
    _assert_refusal(res, ReasonCode.NOT_IN_SCOPE)


# ---- ReviewLog hostile ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [None, 5, b"n", EvilStr("note"), "", "   ", "n\x00", "n\u200b", "x" * 5_000,
                                  [POISON], object()])
def test_annotation_hostile_text_refused_and_log_unchanged(w, text):
    _, run = w.first_run()
    res = w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, text)
    _assert_refusal(res, ReasonCode.ANNOTATION_INVALID)
    assert w.log.entries(w.viewer, "t1", run.run_id) == ()


def test_recursive_annotation_text_refused(w):
    _, run = w.first_run()
    rec = []
    rec.append(rec)
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, rec),
                    ReasonCode.ANNOTATION_INVALID)


@pytest.mark.parametrize("kind", [None, 5, "BOGUS", "note", EvilStr("NOTE"), object()])
def test_annotation_unknown_kind_refused(w, kind):
    _, run = w.first_run()
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", run.run_id, kind, "x"), ReasonCode.ANNOTATION_INVALID)


@pytest.mark.parametrize("kind", ["ADJUSTMENT", "OVERRIDE", "ADJUST", "CORRECTION", "SET_NUMBERS"])
def test_annotation_adjustment_kinds_are_original_numbers_immutable(w, kind):
    _, run = w.first_run()
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", run.run_id, kind, "closing_credit=0"),
                    ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)
    assert w.log.entries(w.viewer, "t1", run.run_id) == ()


def test_rerun_requested_kind_cannot_be_forged_through_add(w):
    _, run = w.first_run()
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.RERUN_REQUESTED, "x"),
                    ReasonCode.ANNOTATION_INVALID)


@pytest.mark.parametrize("assignee", [None, 5, "", EvilStr("o"), "o\x00", "x" * 5_000])
def test_assigned_requires_valid_assignee(w, assignee):
    _, run = w.first_run()
    res = w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.ASSIGNED, assignee=assignee)
    _assert_refusal(res, ReasonCode.ANNOTATION_INVALID)


def test_assignee_on_non_assigned_kind_refused(w):
    _, run = w.first_run()
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x", assignee="o"),
                    ReasonCode.ANNOTATION_INVALID)


def test_annotation_scope_and_run_checks(w):
    _, run = w.first_run()
    other = ViewerScope("t2", "c1", 1)
    _assert_refusal(w.log.add(w.ledger, other, "t1", run.run_id, AnnotationKind.NOTE, "x"), ReasonCode.NOT_IN_SCOPE)
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", "run-999999", AnnotationKind.NOTE, "x"),
                    ReasonCode.NOT_IN_SCOPE)
    _assert_refusal(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x", current_epoch=9),
                    ReasonCode.SCOPE_EPOCH_STALE)
    _assert_refusal(w.log.add(object.__new__(RunLedger), w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x"),
                    ReasonCode.INPUT_INVALID)
    _assert_refusal(w.log.add(w.ledger, object.__new__(ViewerScope), "t1", run.run_id, AnnotationKind.NOTE, "x"),
                    ReasonCode.INPUT_INVALID)
    _assert_refusal(w.log.entries(other, "t1", run.run_id), ReasonCode.NOT_IN_SCOPE)
    _assert_refusal(w.log.entries(object.__new__(ViewerScope), "t1", run.run_id), ReasonCode.INPUT_INVALID)
    assert w.log.entries(w.viewer, "t1", run.run_id) == ()


@pytest.mark.parametrize("clock", [lambda: _naive(), lambda: "now", lambda: None, lambda: 5,
                                   lambda: (_ for _ in ()).throw(RuntimeError(POISON)), 7])
def test_hostile_clock_gives_internal_refused_not_an_exception(w, clock):
    _, run = w.first_run()
    log = ReviewLog(clock)
    res = log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x")
    _assert_refusal(res, ReasonCode.INTERNAL_REFUSED)
    assert log.entries(w.viewer, "t1", run.run_id) == ()


def test_datetime_subclass_clock_refused_and_non_utc_clock_flattened(w):
    _, run = w.first_run()

    class Sub(datetime):
        pass

    log = ReviewLog(lambda: Sub(2026, 9, 1, tzinfo=UTC))
    _assert_refusal(log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x"),
                    ReasonCode.INTERNAL_REFUSED)
    plus3 = timezone(timedelta(hours=3))
    log2 = ReviewLog(lambda: datetime(2026, 9, 1, 15, 0, tzinfo=plus3))
    entry = log2.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x")
    assert isinstance(entry, AnnotationEntry)
    assert entry.recorded_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert entry.recorded_at.utcoffset() == timedelta(0)


def test_review_log_capacity_is_bounded(w):
    _, run = w.first_run()
    log = ReviewLog(lambda: T0)
    last = None
    for _ in range(wr.MAX_LOG_ENTRIES + 5):
        last = log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.ACKNOWLEDGED)
        if isinstance(last, SafeError):
            break
    _assert_refusal(last, ReasonCode.RATE_LIMITED)
    assert len(log.entries(w.viewer, "t1", run.run_id)) == wr.MAX_LOG_ENTRIES


# ---- override requests -------------------------------------------------------------------------

def test_override_request_always_refused_original_numbers_immutable(w):
    w.first_run()
    for args, kwargs in [((), {}), (("t1", KEY, Decimal(0)), {}), ((), {"native": Decimal(1), "state": "PASS"}),
                         ((None, object()), {"verdict": "VALIDATED"}), ((EvilStr("x"),), {POISON: POISON})]:
        res = request_override(*args, **kwargs)
        _assert_refusal(res, ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)


def test_no_public_function_takes_numbers_verdicts_or_states():
    banned = {"native", "gateway", "native_values", "gateway_values", "delta", "state", "verdict", "status",
              "values", "amount", "number", "numbers", "validated", "differences", "command", "query", "sql",
              "raw", "channel"}
    for name in ("build_cards", "verify_original", "request_rerun"):
        params = set(inspect.signature(getattr(wr, name)).parameters)
        assert not params & banned, (name, params & banned)
    for method in (ReviewLog.add, ReviewLog.entries):
        assert not set(inspect.signature(method).parameters) & banned
    tree = ast.parse(inspect.getsource(wr))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in {"AnnotationEntry", "ReviewLog", "RerunOutcome"}:
            fields = {n.target.id for n in node.body if isinstance(n, ast.AnnAssign)}
            assert not fields & {"native", "gateway", "delta", "state", "verdict"}, node.name


# ===================================================================================================
# 2. TC116: original numbers cannot be changed (cannot go green by editing)
# ===================================================================================================

def test_types_are_frozen_slotted(w):
    w.first_run()
    card = w.cards()[0]
    for attr, val in (("native", Decimal(9)), ("delta", Decimal(0)), ("original_digest", "0" * 64),
                      ("owner_id", "evil")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(card, attr, val)
    assert not hasattr(card, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        card.extra = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.fragment.measure = "x"
    assert isinstance(card.fragment, FragmentRef)
    assert card.authority == AUTHORITY


@pytest.mark.parametrize("field,value", [
    ("native", Decimal("0.2")), ("gateway", Decimal("0.3000001")), ("delta", Decimal(0)),
    ("measure", "turnover_debit"), ("run_id", "run-000002"), ("original_digest", "f" * 64),
    ("card_digest", "f" * 64), ("tenant_id", "t2"),
    ("fragment", FragmentRef("0" * 64, None, "closing_credit")),
])
def test_forged_card_is_original_tampered(w, field, value):
    w.first_run()
    card = next(c for c in w.cards() if c.measure == "closing_credit")
    assert verify_original(card, w.ledger) is ReasonCode.ORIGINAL_INTACT
    forged = dataclasses.replace(card, **{field: value})
    assert verify_original(forged, w.ledger) is ReasonCode.ORIGINAL_TAMPERED


def test_forged_card_with_recomputed_card_digest_still_fails_against_ledger(w):
    w.first_run()
    card = next(c for c in w.cards() if c.measure == "closing_credit")
    fake_native = Decimal("0.2")
    forged = dataclasses.replace(card, native=fake_native, delta=card.gateway - fake_native)
    forged = dataclasses.replace(forged, card_digest=wr._card_digest(forged))  # attacker recomputes own digest
    assert verify_original(forged, w.ledger) is ReasonCode.ORIGINAL_TAMPERED


def test_card_for_unknown_run_is_tampered(w):
    w.first_run()
    card = w.cards()[0]
    assert verify_original(card, RunLedger(SnapshotStore(Clock()))) is ReasonCode.ORIGINAL_TAMPERED


def test_notes_assignment_acknowledgement_never_change_numbers(w):
    _, run = w.first_run()
    before = w.cards()
    ledger_before = w.ledger.get("t1", run.run_id)
    assert isinstance(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE,
                                "please set closing_credit to 0.30 and ignore 100.5 delta of 999"), AnnotationEntry)
    assert isinstance(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.ASSIGNED,
                                assignee="owner-b"), AnnotationEntry)
    assert isinstance(w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.ACKNOWLEDGED), AnnotationEntry)
    after = w.cards()
    assert after == before
    assert [c.original_digest for c in after] == [c.original_digest for c in before]
    assert w.ledger.get("t1", run.run_id) == ledger_before
    assert all(verify_original(c, w.ledger) is ReasonCode.ORIGINAL_INTACT for c in after)
    assert [e.kind for e in w.log.entries(w.viewer, "t1", run.run_id)] == [
        AnnotationKind.NOTE, AnnotationKind.ASSIGNED, AnnotationKind.ACKNOWLEDGED]


def test_annotation_text_is_stored_verbatim_and_never_parsed(w):
    _, run = w.first_run()
    entry = w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "Note 100.50 / долг")
    assert entry.text == "Note 100.50 / долг"
    assert entry.authority == AUTHORITY
    assert entry.seq == 1 and entry.related_run_id is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.text = "x"


def test_mutating_source_inputs_or_returned_tuples_does_not_change_ledger(w):
    n = values(closing_credit="0.1")
    g = values(closing_credit="0.3")
    s = w.new_snapshot(n, g, T0)
    nr, gr = reads(s, n, g)
    run = w.ledger.run("t1", KEY, nr, gr, snapshot_id=s.snapshot_id)
    first = w.cards()
    nr.values["closing_credit"] = Decimal(999)  # caller edits its own input after the run
    gr.values["closing_credit"] = Decimal(-1)
    assert w.cards() == first
    assert first[0].native == Decimal("0.1") and first[0].gateway == Decimal("0.3")
    assert w.ledger.get("t1", run.run_id).native_values == (("closing_credit", Decimal("0.1")),)
    log_entries = w.log.entries(w.viewer, "t1", run.run_id)
    assert isinstance(log_entries, tuple)
    with pytest.raises(TypeError):
        log_entries[0] = None  # type: ignore[index]


def test_card_digest_is_deterministic_and_changes_with_numbers(w):
    w.first_run()
    a, b = w.cards(), w.cards()
    assert a == b and [c.card_digest for c in a] == [c.card_digest for c in b]
    assert len({c.card_digest for c in a}) == len(a)
    w2 = World()
    w2.first_run(values(closing_credit="0.1", turnover_debit="100.00"),
                 values(closing_credit="0.31", turnover_debit="100.5"))
    c1 = next(c for c in a if c.measure == "closing_credit")
    c2 = next(c for c in w2.cards() if c.measure == "closing_credit")
    assert c1.original_digest != c2.original_digest and c1.card_digest != c2.card_digest


# ===================================================================================================
# 3. TC115: row / fragment / owner / delta
# ===================================================================================================

def test_fail_run_with_two_measures_yields_two_cards_with_owner_fragment_delta(w):
    s, run = w.first_run()
    cards = w.cards()
    assert isinstance(cards, tuple) and [c.measure for c in cards] == ["closing_credit", "turnover_debit"]
    cc, td = cards
    assert (cc.native, cc.gateway, cc.delta) == (Decimal("0.1"), Decimal("0.3"), Decimal("0.2"))
    assert (td.native, td.gateway, td.delta) == (Decimal(100), Decimal("100.5"), Decimal("0.5"))
    for c in cards:
        assert type(c.native) is Decimal and type(c.delta) is Decimal
        assert c.owner_id == "owner-a" and c.owner_note is None
        assert c.run_id == run.run_id and c.run_status == "CURRENT" and c.tenant_id == "t1"
        assert c.comparison_key == KEY and c.authority == AUTHORITY
        assert c.fragment == FragmentRef(s.digest, None, c.measure)
        assert c.fragment.snapshot_digest == run.snapshot_digest
        assert c.basis == wr.BASIS_RUN_LEDGER
        assert verify_original(c, w.ledger) is ReasonCode.ORIGINAL_INTACT


def test_key_only_run_is_honest_about_missing_row_detail(w):
    w.first_run()
    for c in w.cards():
        assert c.row_key is None
        assert c.row_detail is ReasonCode.ROW_DETAIL_UNAVAILABLE


def test_unmapped_owner_is_visible_never_guessed(w):
    w.first_run()
    for src, owners in (("other-src", w.owners), ("src1", OwnerDirectory(())),
                        ("src1", OwnerDirectory((("t1", "c2", "src1", "owner-z"),)))):
        cards = build_cards(w.ledger, "t1", KEY, owners, w.viewer, source_id=src)
        assert all(c.owner_id is None and c.owner_note is ReasonCode.OWNER_UNASSIGNED for c in cards)


def test_delta_is_exact_decimal_sign_and_not_float(w):
    native = values(a="0.3", b="5", c="-1.5")
    gateway = {"a": Decimal("0.1") + Decimal("0.2") + Decimal("0.0000000000000001"), "b": Decimal(3),
               "c": Decimal("-1.25")}
    s = w.new_snapshot(native, gateway, T0)
    w.ledger.run("t1", KEY, *reads(s, native, gateway), snapshot_id=s.snapshot_id)
    by = {c.measure: c for c in w.cards()}
    assert by["a"].delta == Decimal("1E-16") and by["a"].delta > 0
    assert by["b"].delta == Decimal(-2)  # gateway - native, negative
    assert by["c"].delta == Decimal("0.25")
    assert 0.1 + 0.2 != 0.3 and by["a"].delta != 0  # the float world would have lost this
    assert all(type(c.delta) is Decimal for c in by.values())


def test_delta_precision_overflow_gives_fixed_reason_and_no_card(w):
    native = {"big": Decimal("1E+100")}
    gateway = {"big": Decimal("1E-100")}
    s = w.new_snapshot(native, gateway, T0)
    w.ledger.run("t1", KEY, *reads(s, native, gateway), snapshot_id=s.snapshot_id)
    res = w.cards()
    _assert_refusal(res, ReasonCode.DELTA_PRECISION_EXCEEDED)


def test_one_sided_measure_has_no_delta_and_no_invented_zero(w):
    native = values(a="1")
    gateway = values(a="1", extra="2")
    s = w.new_snapshot(native, gateway, T0)
    w.ledger.run("t1", KEY, *reads(s, native, gateway), snapshot_id=s.snapshot_id)
    (card,) = w.cards()
    assert card.measure == "extra" and card.native is None and card.gateway == Decimal(2) and card.delta is None
    assert verify_original(card, w.ledger) is ReasonCode.ORIGINAL_INTACT


def test_pass_and_inconclusive_runs_have_no_cards(w):
    n = values(a="1")
    s = w.new_snapshot(n, n, T0)
    w.ledger.run("t1", KEY, *reads(s, n, n), snapshot_id=s.snapshot_id)
    assert w.cards() == ()
    w2 = World()
    s2 = w2.new_snapshot(n, n, T0)
    nr, _ = reads(s2, n, n)
    gr2 = SideRead("gateway", s2.snapshot_id, "0" * 64, dict(n))  # observed digest differs -> INCONCLUSIVE
    w2.ledger.run("t1", KEY, nr, gr2, snapshot_id=s2.snapshot_id)
    assert w2.cards() == ()
    assert build_cards(w2.ledger, "t1", "no-such-key", w2.owners, w2.viewer, source_id="src1") == ()


def test_row_level_cards_through_the_explicit_comparison_adapter(w):
    s, run = w.first_run()
    comp = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference(None, "closing_credit", Decimal("10.10"), Decimal("10.30")),
        Difference(("cp-1", "ct-1"), "turnover_debit", Decimal("0.10"), Decimal("0.30")),
        Difference(("cp-2", "ct-2"), "ROW_MISSING", None, None),
    ))
    cards = w.cards(comparison=comp)
    assert isinstance(cards, tuple) and len(cards) == 3
    totals, row, missing = cards
    assert totals.row_key is None and totals.row_detail is None and totals.delta == Decimal("0.20")
    assert row.row_key == ("cp-1", "ct-1") and row.row_detail is None
    assert row.fragment == FragmentRef(s.digest, ("cp-1", "ct-1"), "turnover_debit")
    assert (row.native, row.gateway, row.delta) == (Decimal("0.10"), Decimal("0.30"), Decimal("0.20"))
    assert missing.native is None and missing.delta is None and missing.measure == "ROW_MISSING"
    for c in cards:
        assert c.basis == wr.BASIS_COMPARISON and c.run_id == run.run_id
        assert c.owner_id == "owner-a"
        assert verify_original(c, w.ledger) is ReasonCode.ORIGINAL_INTACT
    forged = dataclasses.replace(row, gateway=Decimal("0.31"))
    assert verify_original(forged, w.ledger) is ReasonCode.ORIGINAL_TAMPERED
    # a FAIL run cannot be "explained" by a comparison without differences: refused, not silently empty
    _assert_refusal(w.cards(comparison=Comparison(ComparisonState.MATCH, "ALL_SIX_AND_ROWS_EQUAL", "p", ())),
                    ReasonCode.INPUT_INVALID)


def test_guid_ids_canonicalised_and_text_preserved_exactly(w):
    guid_up = "{3F2504E0-4F89-11D3-9A0C-0305E82C3301}"
    comp = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference((guid_up, "Contract № 5 A"), "closing_credit", Decimal(1), Decimal(2)),))
    w.first_run()
    (card,) = w.cards(comparison=comp)
    assert card.row_key == ("3f2504e0-4f89-11d3-9a0c-0305e82c3301", "Contract № 5 A")
    comp2 = Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", "p", (
        Difference(("Case-Sensitive-Ref", "ct"), "closing_credit", Decimal(1), Decimal(2)),))
    (card2,) = w.cards(comparison=comp2)
    assert card2.row_key == ("Case-Sensitive-Ref", "ct")


def test_run_id_selects_a_specific_run_and_status_labels(w):
    _, run1 = w.first_run()
    n = values(closing_credit="0.3", turnover_debit="100.5")
    s2 = w.new_snapshot(n, n, T0 + timedelta(days=1))
    out = w.rerun(run1.run_id, s2.snapshot_id)
    assert isinstance(out, RerunOutcome)
    old = w.cards(run_id=run1.run_id)
    assert [c.run_status for c in old] == ["SUPERSEDED", "SUPERSEDED"]
    assert w.cards() == ()  # current run is PASS: nothing to discuss


# ===================================================================================================
# 4. TC117: new evidence -> new run
# ===================================================================================================

def test_rerun_hostile_arguments_refused_and_no_run_created(w):
    _, run = w.first_run()
    s2 = w.new_snapshot(values(a="1"), values(a="1"), T0 + timedelta(days=1))
    base = {"prev": run.run_id, "new_snapshot_id": s2.snapshot_id}
    for bad in HOSTILE:
        for key in ("prev", "new_snapshot_id"):
            kw = dict(base)
            kw[key] = bad
            res = w.rerun(kw["prev"], kw["new_snapshot_id"])
            _assert_refusal(res, ReasonCode.INPUT_INVALID, ReasonCode.RERUN_TARGET_UNKNOWN, ReasonCode.NOT_IN_SCOPE)
        _assert_refusal(w.rerun(run.run_id, s2.snapshot_id, tenant=bad), ReasonCode.INPUT_INVALID,
                        ReasonCode.NOT_IN_SCOPE)
    for bad in (None, 5, "x", object(), object.__new__(ViewerScope)):
        _assert_refusal(w.rerun(run.run_id, s2.snapshot_id, viewer=bad), ReasonCode.INPUT_INVALID)
    for bad in (None, 5, "x", object()):
        _assert_refusal(w.rerun(run.run_id, s2.snapshot_id, reader=bad), ReasonCode.INPUT_INVALID)
    for args in ((None, w.store, w.log), (w.ledger, None, w.log), (w.ledger, w.store, None),
                 (object.__new__(RunLedger), w.store, w.log)):
        _assert_refusal(request_rerun(*args, w.viewer, "t1", KEY, run.run_id, s2.snapshot_id, w.reader),
                        ReasonCode.INPUT_INVALID)
    _assert_refusal(request_rerun(w.ledger, w.store, w.log, w.viewer, "t1", bad_key := 5, run.run_id,
                                  s2.snapshot_id, w.reader), ReasonCode.INPUT_INVALID)
    assert bad_key == 5
    assert len(w.ledger.list_runs("t1", KEY)) == 1
    assert w.reader_calls == 0


def test_rerun_new_snapshot_creates_run_n_plus_1_old_run_unchanged(w):
    _, run1 = w.first_run()
    cards_before = w.cards()
    n = values(closing_credit="0.3", turnover_debit="100.5")
    s2 = w.new_snapshot(n, n, T0 + timedelta(days=1))  # backdated correction: evidence known later
    out = w.rerun(run1.run_id, s2.snapshot_id)
    assert isinstance(out, RerunOutcome)
    assert (out.previous_run_id, out.new_run_id, out.new_run_state) == (run1.run_id, "run-000002", "PASS")
    assert out.current_run_id == "run-000002" and out.authority == AUTHORITY and out.annotated is True
    new = w.ledger.get("t1", out.new_run_id)
    assert new.supersedes == run1.run_id and new.snapshot_id == s2.snapshot_id
    views = w.ledger.list_runs("t1", KEY)
    assert [v.status for v in views] == ["SUPERSEDED", "CURRENT"]
    assert views[0].record == run1 and views[0].record.native_values == run1.native_values  # untouched
    old_cards = w.cards(run_id=run1.run_id)
    assert [(c.native, c.gateway, c.delta, c.original_digest) for c in old_cards] == [
        (c.native, c.gateway, c.delta, c.original_digest) for c in cards_before]
    assert all(c.run_status == "SUPERSEDED" for c in old_cards)
    assert all(verify_original(c, w.ledger) is ReasonCode.ORIGINAL_INTACT for c in cards_before + old_cards)
    log = w.log.entries(w.viewer, "t1", run1.run_id)
    assert [e.kind for e in log] == [AnnotationKind.RERUN_REQUESTED] and log[0].related_run_id == out.new_run_id
    assert w.reader_calls == 1


def test_rerun_same_snapshot_id_or_same_digest_is_no_new_evidence(w):
    s1, run1 = w.first_run()
    _assert_refusal(w.rerun(run1.run_id, s1.snapshot_id), ReasonCode.NO_NEW_EVIDENCE)
    # same content frozen at a different known-at gets a different id but the same digest
    n = values(closing_credit="0.1", turnover_debit="100.00")
    g = values(closing_credit="0.3", turnover_debit="100.5")
    same_digest = w.new_snapshot(n, g, T0 + timedelta(hours=1))
    assert same_digest.snapshot_id != s1.snapshot_id and same_digest.digest == s1.digest
    _assert_refusal(w.rerun(run1.run_id, same_digest.snapshot_id), ReasonCode.NO_NEW_EVIDENCE)
    assert len(w.ledger.list_runs("t1", KEY)) == 1 and w.reader_calls == 0
    assert w.log.entries(w.viewer, "t1", run1.run_id) == ()


def test_rerun_of_superseded_or_non_head_run_is_stale(w):
    _, run1 = w.first_run()
    n2 = values(closing_credit="0.2", turnover_debit="100.5")
    s2 = w.new_snapshot(n2, n2, T0 + timedelta(days=1))
    out = w.rerun(run1.run_id, s2.snapshot_id)
    assert isinstance(out, RerunOutcome)
    n3 = values(closing_credit="0.5", turnover_debit="100.5")
    s3 = w.new_snapshot(n3, n3, T0 + timedelta(days=2))
    _assert_refusal(w.rerun(run1.run_id, s3.snapshot_id), ReasonCode.RERUN_TARGET_STALE)
    assert len(w.ledger.list_runs("t1", KEY)) == 2
    assert w.log.entries(w.viewer, "t1", run1.run_id)[-1].related_run_id == out.new_run_id
    assert len(w.log.entries(w.viewer, "t1", run1.run_id)) == 1  # refused attempt wrote nothing


def test_rerun_unknown_run_unknown_snapshot_and_wrong_key(w):
    _, run1 = w.first_run()
    s2 = w.new_snapshot(values(a="1"), values(a="1"), T0 + timedelta(days=1))
    _assert_refusal(w.rerun("run-999999", s2.snapshot_id), ReasonCode.RERUN_TARGET_UNKNOWN)
    _assert_refusal(w.rerun(run1.run_id, "snap-doesnotexist"), ReasonCode.INPUT_INVALID)
    res = request_rerun(w.ledger, w.store, w.log, w.viewer, "t1", "other-key", run1.run_id, s2.snapshot_id,
                        w.reader)
    _assert_refusal(res, ReasonCode.RERUN_TARGET_UNKNOWN)
    assert len(w.ledger.list_runs("t1", KEY)) == 1


def test_rerun_foreign_tenant_is_not_in_scope_and_epoch_checked(w):
    _, run1 = w.first_run()
    s2 = w.new_snapshot(values(a="1"), values(a="1"), T0 + timedelta(days=1))
    other = ViewerScope("t2", "c1", 1)
    _assert_refusal(w.rerun(run1.run_id, s2.snapshot_id, viewer=other), ReasonCode.NOT_IN_SCOPE)
    _assert_refusal(w.rerun(run1.run_id, s2.snapshot_id, current_epoch=2), ReasonCode.SCOPE_EPOCH_STALE)
    _assert_refusal(w.rerun(run1.run_id, s2.snapshot_id, current_epoch="1"), ReasonCode.INPUT_INVALID)
    assert len(w.ledger.list_runs("t1", KEY)) == 1 and w.reader_calls == 0


def test_inconclusive_rerun_keeps_earlier_decisive_run_current(w):
    _, run1 = w.first_run()
    s2 = w.new_snapshot(values(closing_credit="0.2"), values(closing_credit="0.2"), T0 + timedelta(days=1))

    def liar(tenant, snapshot_id):  # numbers that are not in the frozen snapshot -> INCONCLUSIVE
        s = w.store.get(tenant, snapshot_id)
        return reads(s, values(closing_credit="7"), values(closing_credit="7"))

    out = w.rerun(run1.run_id, s2.snapshot_id, reader=liar)
    assert isinstance(out, RerunOutcome) and out.new_run_state == "INCONCLUSIVE"
    assert out.current_run_id == run1.run_id
    assert [v.status for v in w.ledger.list_runs("t1", KEY)] == ["CURRENT", "LATEST_ATTEMPT"]
    cards = w.cards()
    assert [c.run_id for c in cards] == [run1.run_id, run1.run_id]
    assert all(c.run_status == "CURRENT" for c in cards)
    assert all(verify_original(c, w.ledger) is ReasonCode.ORIGINAL_INTACT for c in cards)


def test_reader_failure_is_a_fixed_refusal_with_no_echo_and_no_run(w):
    _, run1 = w.first_run()
    s2 = w.new_snapshot(values(a="1"), values(a="1"), T0 + timedelta(days=1))

    def boom(tenant, snapshot_id):
        raise RuntimeError(POISON)

    _assert_refusal(w.rerun(run1.run_id, s2.snapshot_id, reader=boom), ReasonCode.INTERNAL_REFUSED)
    for junk in (None, "x", (1, 2), (object(), object()), ()):
        _assert_refusal(w.rerun(run1.run_id, s2.snapshot_id, reader=lambda t, s, j=junk: j),
                        ReasonCode.INPUT_INVALID)
    assert len(w.ledger.list_runs("t1", KEY)) == 1
    assert w.log.entries(w.viewer, "t1", run1.run_id) == ()


def test_hostile_review_clock_refuses_rerun_before_any_run_is_created(w):
    _, run1 = w.first_run()
    s2 = w.new_snapshot(values(a="1"), values(a="1"), T0 + timedelta(days=1))
    w.log = ReviewLog(lambda: _naive())  # naive
    _assert_refusal(w.rerun(run1.run_id, s2.snapshot_id), ReasonCode.INTERNAL_REFUSED)
    assert len(w.ledger.list_runs("t1", KEY)) == 1 and w.reader_calls == 0


def test_two_parallel_reruns_of_the_same_head_make_exactly_one_new_run(w):
    _, run1 = w.first_run()
    n = values(closing_credit="0.3", turnover_debit="100.5")
    snaps = [w.new_snapshot(n, n, T0 + timedelta(days=d)) for d in (1, 2)]
    barrier = threading.Barrier(2)
    results = []

    def go(snap_id):
        barrier.wait()
        results.append(w.rerun(run1.run_id, snap_id))

    threads = [threading.Thread(target=go, args=(s.snapshot_id,)) for s in snaps]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok = [r for r in results if isinstance(r, RerunOutcome)]
    bad = [r for r in results if isinstance(r, SafeError)]
    assert len(ok) == 1 and len(bad) == 1
    assert bad[0].reason_code is ReasonCode.RERUN_TARGET_STALE
    assert len(w.ledger.list_runs("t1", KEY)) == 2
    assert len(w.log.entries(w.viewer, "t1", run1.run_id)) == 1


# ===================================================================================================
# 5. boundary / honesty
# ===================================================================================================

def test_module_imports_are_stdlib_and_sibling_only():
    tree = ast.parse(inspect.getsource(wr))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(("." * node.level) + (node.module or ""))
    assert not mods & {"httpx", "requests", "socket", "os", "pathlib", "subprocess", "sqlite3"}
    for m in mods:
        assert m.startswith(".") and not m.startswith("..") or m in {
            "__future__", "re", "unicodedata", "threading", "datetime", "decimal", "dataclasses", "collections.abc", "enum",
            "typing", "types"}, m
    src = inspect.getsource(wr)
    assert "open(" not in src and "business_ai_gateway.release" not in src


def test_every_outward_result_is_evaluation_only(w):
    _, run = w.first_run()
    card = w.cards()[0]
    entry = w.log.add(w.ledger, w.viewer, "t1", run.run_id, AnnotationKind.NOTE, "x")
    assert card.authority == entry.authority == AUTHORITY
    assert not any(hasattr(card, n) for n in ("verdict", "validated", "promotable", "approved"))
