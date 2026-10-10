"""R2-US-040 (S8/E2) timeline view: TC118 known/effective labels, TC119 historical != live green,
TC120 (timeline part) scope, plus the S6b hostile-input lesson rows.

Offline and in-memory: real RunLedger / AttestationStore / EventLedger / MatrixResult over a fake clock.
Rows that guard "cannot be green" and hostile input come before the happy path on purpose.
"""
from __future__ import annotations

import ast
import itertools
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import timeline_view as tv
from business_ai_gateway.phase2.comparison_snapshot import (
    RunLedger,
    SideRead,
    SnapshotStore,
    _projection,
)
from business_ai_gateway.phase2.evidence_attestation import (
    AttestationDecision,
    AttestationRequest,
    AttestationStore,
    Signer,
    SignerKind,
)
from business_ai_gateway.phase2.temporal import EventKind, EventLedger, ModelEvent
from business_ai_gateway.phase2.timeline_view import (
    EFFECTIVE_AT_LABEL,
    EFFECTIVE_UNKNOWN_LABEL,
    HISTORICAL_LABEL,
    KNOWN_AT_LABEL,
    Applicability,
    ApplicabilityPolicy,
    ApplicabilityReason,
    EffectiveTimeLabel,
    EntryKind,
    EventFeed,
    KnownTimeLabel,
    RunBinding,
    ScopeAuthority,
    TimelineEntry,
    TimelineSubject,
    TimelineView,
    build_timeline,
    is_green,
    render_guard,
)
from business_ai_gateway.phase2.validation_coverage import (
    Claim,
    ClaimScope,
    Evidence,
    EvidenceVerdict,
    Link,
    build_matrix,
)
from business_ai_gateway.phase2.workbench_types import ReasonCode, SafeError, ViewerScope

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
KEY = "tb:818HA:521.1:2026-08"
REV, POL_VER, POL_DIG = f"{1:064x}", "pol-v1", f"{2:064x}"
CC = {"closing_credit": Decimal(24)}


def h(n: int) -> str:
    return f"{n:064x}"


class LyingStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class LyingDT(datetime):
    def __eq__(self, other):
        return True

    def __lt__(self, other):
        return True

    __hash__ = datetime.__hash__


class LyingInt(int):
    def __eq__(self, other):
        return True

    __hash__ = int.__hash__


class Env:
    """One tenant t1 / company A, plus company B for scope rows. The clock only moves when told."""

    def __init__(self):
        self.now = T0 + timedelta(days=10)
        self.store = SnapshotStore(self.clock)
        self.ledger = RunLedger(self.store)
        self._ids = itertools.count(1)
        self.att = AttestationStore(self.clock, accountants={"t1": {"acc1"}},
                                    id_source=lambda: f"att-{next(self._ids)}")
        self.epochs = {("t1", "A"): 5, ("t1", "B"): 5}
        self.authority = ScopeAuthority(lambda t, c: self.epochs.get((t, c)))
        self.viewer = ViewerScope("t1", "A", 5)
        self.policy = ApplicabilityPolicy(3600, REV, False)
        self.matrix = self.make_matrix()
        self.bindings: list[RunBinding] = []
        self.extra_subjects: tuple[TimelineSubject, ...] = ()
        self.feeds: tuple[EventFeed, ...] = ()

    def clock(self) -> datetime:
        return self.now

    # ---- fixtures
    @staticmethod
    def make_matrix(company="A", with_evidence=True):
        scope = ClaimScope("t1", company)
        claims = (Claim("cl-" + company, scope, "purchases", "validate"),)
        ev = (Evidence("ev-" + company, scope, "src-" + company, h(7), EvidenceVerdict.PASS),)
        links = (Link("cl-" + company, "ev-" + company),) if with_evidence else ()
        return build_matrix(claims, ev if with_evidence else (), links)

    def snap(self, native=None, gateway=None, **extra):
        n = dict(CC) if native is None else native
        g = dict(n) if gateway is None else gateway
        payload = {"account": "521.1", "values": {"native": n, "gateway": g}, **extra}
        return self.store.create("t1", payload, known_at=T0)

    def go(self, snap, *, key=KEY, observed=None, **kw):
        def read(side):
            vals = _projection(snap, side) or dict(CC)
            return SideRead(side, snap.snapshot_id, observed or snap.digest, vals)
        return self.ledger.run("t1", key, read("native"), read("gateway"),
                               snapshot_id=snap.snapshot_id, **kw)

    def attest(self, rev=REV):
        res = self.att.sign(AttestationRequest("t1", rev, POL_VER, POL_DIG, "prop", "req",
                                               AttestationDecision.PASS), Signer(SignerKind.HUMAN, "acc1"))
        assert res.signed
        return res.attestation.attestation_id

    def bind(self, run, att_id, rev=REV):
        b = RunBinding(run.run_id, att_id, rev, POL_VER, POL_DIG)
        self.bindings.append(b)
        return b

    def live_run(self):
        run = self.go(self.snap())
        self.bind(run, self.attest())
        return run

    def subject(self, company="A", key=KEY, bindings=None):
        return TimelineSubject("t1", company, key, tuple(self.bindings if bindings is None else bindings))

    def build(self, **over):
        args = {"viewer": self.viewer, "authority": self.authority, "ledger": self.ledger,
                "attestations": self.att, "subjects": (self.subject(),) + self.extra_subjects,
                "feeds": self.feeds, "matrix": self.matrix, "policy": self.policy, "clock": self.clock}
        args.update(over)
        return build_timeline(**args)


def entry(view, ref):
    found = [e for e in view.entries if e.ref_id == ref]
    assert len(found) == 1
    return found[0]


@pytest.fixture
def env():
    return Env()


def event(eid="ev1", rec=None, obs=None, eff=None, kind=EventKind.OBSERVED, obj="o1", rev="r1"):
    rec = rec or T0
    return ModelEvent(eid, "t1", "s1", obj, rev, kind, rec, obs or rec, eff,
                      h(5) if kind is EventKind.OBSERVED else None)


def feed_with(*events, company="A"):
    led = EventLedger("t1", "s1")
    for e in events:
        led.append(e)
    return EventFeed("t1", company, led)


# ===================================================== TC119: "cannot be green" rows come first
def _paused(e, run):
    e.policy = ApplicabilityPolicy(3600, REV, True)


def _revoked(e, run):
    assert e.att.revoke(e.bindings[0].attestation_id, "t1", Signer(SignerKind.HUMAN, "acc1")).revoked


def _superseded(e, run):
    e.go(e.snap(v=2), rerun_of=run.run_id)


def _new_revision(e, run):
    e.policy = ApplicabilityPolicy(3600, h(9), False)


def _stale(e, run):
    e.now += timedelta(seconds=3601)


def _incomplete(e, run):
    e.matrix = build_matrix((Claim("c1", ClaimScope("t1", "A"), "purchases", "validate"),
                             Claim("c2", ClaimScope("t1", "A"), "sales", "validate")),
                            (Evidence("e1", ClaimScope("t1", "A"), "s1", h(7), EvidenceVerdict.PASS),),
                            (Link("c1", "e1"),))
    assert not e.matrix.accepted


def _refused(e, run):
    e.matrix = build_matrix((), (), ())
    assert not e.matrix.accepted


def _other_company_only_matrix(e, run):
    e.matrix = e.make_matrix("B")  # complete, but covers only company B


def _no_binding(e, run):
    e.bindings.clear()


def _no_attestation_id(e, run):
    e.bindings[0] = RunBinding(run.run_id, None, REV, POL_VER, POL_DIG)


def _unknown_attestation_id(e, run):
    e.bindings[0] = RunBinding(run.run_id, "att-does-not-exist", REV, POL_VER, POL_DIG)


def _wrong_policy_digest(e, run):
    e.bindings[0] = RunBinding(run.run_id, e.bindings[0].attestation_id, REV, POL_VER, h(99))


def _source_status_unknown(e, run):
    e.policy = ApplicabilityPolicy(3600, REV, None)


def _revision_unknown(e, run):
    e.policy = ApplicabilityPolicy(3600, None, False)


def _matrix_garbage(e, run):
    e.matrix = object()


def _matrix_none(e, run):
    e.matrix = None


def _clock_before_record(e, run):
    e.now = run.recorded_at - timedelta(seconds=1)


NOT_GREEN_ROWS = [
    ("superseded", _superseded, Applicability.HISTORICAL_PASS, ApplicabilityReason.SUPERSEDED_BY_RUN),
    ("new_revision", _new_revision, Applicability.HISTORICAL_PASS, ApplicabilityReason.REVISION_CHANGED),
    ("revoked", _revoked, Applicability.REVOKED, ApplicabilityReason.ATTESTATION_REVOKED),
    ("stale", _stale, Applicability.HISTORICAL_PASS, ApplicabilityReason.STALE),
    ("paused", _paused, Applicability.HISTORICAL_PASS, ApplicabilityReason.SOURCE_PAUSED),
    ("coverage_incomplete", _incomplete, Applicability.NOT_COVERED, ApplicabilityReason.NOT_COVERED),
    ("coverage_refused", _refused, Applicability.NOT_COVERED, ApplicabilityReason.NOT_COVERED),
    ("coverage_other_company", _other_company_only_matrix, Applicability.NOT_COVERED,
     ApplicabilityReason.NOT_COVERED),
    ("no_binding", _no_binding, Applicability.UNATTESTED, ApplicabilityReason.ATTESTATION_MISSING),
    ("no_attestation_id", _no_attestation_id, Applicability.UNATTESTED,
     ApplicabilityReason.ATTESTATION_MISSING),
    ("unknown_attestation_id", _unknown_attestation_id, Applicability.UNATTESTED,
     ApplicabilityReason.ATTESTATION_NOT_CURRENT),
    ("wrong_policy_digest", _wrong_policy_digest, Applicability.UNATTESTED,
     ApplicabilityReason.ATTESTATION_NOT_CURRENT),
    ("source_status_unknown", _source_status_unknown, Applicability.UNKNOWN,
     ApplicabilityReason.INPUT_UNKNOWN),
    ("revision_unknown", _revision_unknown, Applicability.UNKNOWN, ApplicabilityReason.INPUT_UNKNOWN),
    ("matrix_garbage", _matrix_garbage, Applicability.UNKNOWN, ApplicabilityReason.INPUT_UNKNOWN),
    ("matrix_none", _matrix_none, Applicability.UNKNOWN, ApplicabilityReason.INPUT_UNKNOWN),
    ("clock_before_record", _clock_before_record, Applicability.UNKNOWN, ApplicabilityReason.INPUT_UNKNOWN),
]


@pytest.mark.parametrize(("name", "mutate", "applic", "reason"), NOT_GREEN_ROWS,
                         ids=[r[0] for r in NOT_GREEN_ROWS])
def test_tc119_every_non_live_input_gives_named_non_green_value_with_reason(env, name, mutate, applic, reason):
    run = env.live_run()
    assert is_green(entry(env.build(), run.run_id))  # baseline: the same setup IS live without the defect
    mutate(env, run)
    view = env.build()
    assert type(view) is TimelineView
    e = entry(view, run.run_id)
    assert e.applicability is applic and e.reason is reason
    assert is_green(e) is False
    assert not any(is_green(x) for x in view.entries if x.applicability is not Applicability.LIVE_CURRENT)
    if applic is Applicability.HISTORICAL_PASS:
        assert e.label_text == HISTORICAL_LABEL == "historical, not current"


def test_tc119_superseded_run_keeps_numbers_and_new_run_is_the_live_one(env):
    first = env.live_run()
    second = env.go(env.snap(v=2), rerun_of=first.run_id)
    env.bind(second, env.attest())
    view = env.build()
    assert entry(view, first.run_id).applicability is Applicability.HISTORICAL_PASS
    assert is_green(entry(view, second.run_id))


@pytest.mark.parametrize("state", ["FAIL", "INCONCLUSIVE"])
def test_tc119_non_pass_run_is_named_and_never_green(env, state):
    if state == "FAIL":
        run = env.go(env.snap({"a": Decimal(1)}, {"a": Decimal(2)}))
        want = Applicability.FAIL
    else:
        run = env.go(env.snap(), observed=h(404))
        want = Applicability.INCONCLUSIVE
    env.bind(run, env.attest())
    e = entry(env.build(), run.run_id)
    assert e.applicability is want and not is_green(e)


def test_tc119_inconclusive_rerun_does_not_hide_current_but_is_not_green_itself(env):
    first = env.live_run()
    inc = env.go(env.snap(v=3), observed=h(404), rerun_of=first.run_id)
    env.bind(inc, env.attest())
    view = env.build()
    assert is_green(entry(view, first.run_id))  # ledger rule: CURRENT stays the last decisive run
    assert entry(view, inc.run_id).applicability is Applicability.INCONCLUSIVE


def test_tc119_freshness_boundary_exact_window_is_fresh_one_second_more_is_stale(env):
    run = env.live_run()
    env.now += timedelta(seconds=3600)
    assert is_green(entry(env.build(), run.run_id))
    env.now += timedelta(seconds=1)
    assert entry(env.build(), run.run_id).reason is ApplicabilityReason.STALE


def test_tc119_check_as_of_valid_historical_never_produces_green(env):
    run = env.live_run()
    att_id = env.bindings[0].attestation_id
    env.now += timedelta(minutes=5)  # revoke strictly after signing so signing time was valid
    env.att.revoke(att_id, "t1", Signer(SignerKind.HUMAN, "acc1"))
    signed = env.att.history("t1")[0].signed_at
    as_of = env.att.check_as_of(att_id, "t1", REV, POL_VER, POL_DIG, signed)
    assert as_of.valid and as_of.code == "VALID_HISTORICAL"  # history still says valid at signing time
    e = entry(env.build(), run.run_id)
    assert e.applicability is Applicability.REVOKED and not is_green(e)


def test_tc119_revoked_attestation_stays_visible_with_its_signing_time(env):
    run = env.live_run()
    att_id = env.bindings[0].attestation_id
    signed = env.att.history("t1")[0].signed_at
    env.att.revoke(att_id, "t1", Signer(SignerKind.HUMAN, "acc1"))
    view = env.build()
    a = entry(view, att_id)
    assert a.kind is EntryKind.ATTESTATION and a.applicability is Applicability.REVOKED
    assert a.known.at == signed and not is_green(a)
    assert entry(view, run.run_id).applicability is Applicability.REVOKED  # history kept, applicability gone


def test_tc119_clock_regression_does_not_resurrect_revoked_attestation(env):
    run = env.live_run()
    env.att.revoke(env.bindings[0].attestation_id, "t1", Signer(SignerKind.HUMAN, "acc1"))
    for back in (timedelta(seconds=1), timedelta(days=30)):
        env.now = env.now - back  # regress, even to before the signature
        e = entry(env.build(), run.run_id)
        assert e.applicability is Applicability.REVOKED and not is_green(e)


def test_tc119_live_current_is_the_only_green_value():
    greens = []
    for applic in Applicability:
        for reason in [None, *ApplicabilityReason]:
            try:
                e = TimelineEntry(EntryKind.RUN, "run-1", KnownTimeLabel(T0), EffectiveTimeLabel.unknown(),
                                  applic, reason, "x", False)
            except ValueError:
                continue  # constructor refuses inconsistent pairs
            if is_green(e):
                greens.append((applic, reason))
    assert greens == [(Applicability.LIVE_CURRENT, None)]
    assert {a.value for a in Applicability} == {
        "LIVE_CURRENT", "HISTORICAL_PASS", "REVOKED", "UNATTESTED", "INCONCLUSIVE", "FAIL",
        "NOT_COVERED", "UNKNOWN"}


def test_tc119_is_green_refuses_forged_and_foreign_objects(env):
    run = env.live_run()
    real = entry(env.build(), run.run_id)
    assert is_green(real)

    class Sub(TimelineEntry):  # exact type only
        pass

    for bad in (None, "LIVE_CURRENT", 1, object(), object.__new__(TimelineEntry), [real], real.applicability):
        assert is_green(bad) is False
    with pytest.raises(FrozenInstanceError):
        real.applicability = Applicability.LIVE_CURRENT  # type: ignore[misc]
    forged = object.__new__(TimelineEntry)
    object.__setattr__(forged, "applicability", Applicability.LIVE_CURRENT)
    assert is_green(forged) is False  # other slots unset -> not green


def test_tc119_entry_constructor_refuses_green_with_a_reason_and_non_green_without_one():
    with pytest.raises(ValueError, match="^TIMELINE_ENTRY_INVALID$"):
        TimelineEntry(EntryKind.RUN, "r", KnownTimeLabel(T0), EffectiveTimeLabel.unknown(),
                      Applicability.LIVE_CURRENT, ApplicabilityReason.STALE, "x", False)
    with pytest.raises(ValueError, match="^TIMELINE_ENTRY_INVALID$"):
        TimelineEntry(EntryKind.RUN, "r", KnownTimeLabel(T0), EffectiveTimeLabel.unknown(),
                      Applicability.HISTORICAL_PASS, None, "x", False)


# ===================================================== hostile input (S6b lesson rows)
HOSTILE = [None, "x", "", 1, 2**200, 1.5, b"b", object(), [], {}, LyingStr("t1"), LyingInt(5),
           LyingDT(2026, 1, 1, tzinfo=UTC), True]
_REC: list = []
_REC.append(_REC)
HOSTILE.append(_REC)
ARGS = ["viewer", "authority", "ledger", "attestations", "subjects", "feeds", "matrix", "policy", "clock"]


@pytest.mark.parametrize("arg", ARGS)
@pytest.mark.parametrize("bad", HOSTILE, ids=lambda v: type(v).__name__ + str(id(v) % 97))
def test_hostile_argument_never_raises_and_never_goes_green(env, arg, bad):
    env.live_run()
    out = env.build(**{arg: bad})
    assert type(out) in (SafeError, TimelineView)
    if type(out) is TimelineView:
        assert not any(is_green(e) for e in out.entries)
        assert arg == "matrix"  # only a broken matrix may still yield a (non-green) view
    else:
        assert out.authority == "EVALUATION_ONLY"


def test_hostile_forged_object_new_instances_are_refused_without_raising(env):
    env.live_run()
    for arg, cls in [("viewer", ViewerScope), ("authority", ScopeAuthority), ("policy", ApplicabilityPolicy)]:
        out = env.build(**{arg: object.__new__(cls)})
        assert type(out) is SafeError
    forged_subject = object.__new__(TimelineSubject)
    assert type(env.build(subjects=(forged_subject,))) is SafeError
    forged_binding_subject = TimelineSubject("t1", "A", KEY, ())
    object.__setattr__(forged_binding_subject, "bindings", (object.__new__(RunBinding),))
    out = env.build(subjects=(forged_binding_subject,))
    assert type(out) is SafeError or not any(is_green(e) for e in out.entries)
    assert type(env.build(feeds=(object.__new__(EventFeed),))) is SafeError


@pytest.mark.parametrize("clock", [
    lambda: datetime(2026, 9, 11, 12, 0),  # noqa: DTZ001                     # naive
    lambda: LyingDT(2026, 9, 11, 12, 0, tzinfo=UTC),            # datetime subclass with lying __eq__/__lt__
    lambda: "2026-09-11T12:00:00Z",
    lambda: None,
    lambda: (_ for _ in ()).throw(RuntimeError("POISON-CLOCK-SECRET")),
    lambda: datetime.max.replace(tzinfo=timezone(timedelta(hours=-5))),  # astimezone overflows
], ids=["naive", "lying_subclass", "str", "none", "raises", "overflow"])
def test_hostile_clock_is_a_fixed_refusal_and_poison_never_leaks(env, clock):
    env.live_run()
    out = env.build(clock=clock)
    assert type(out) is SafeError
    assert "POISON" not in repr(out)


def test_non_utc_aware_clock_is_flattened_to_the_same_instant(env):
    run = env.live_run()
    plus3 = timezone(timedelta(hours=3))
    view = env.build(clock=lambda: env.now.astimezone(plus3))
    assert type(view) is TimelineView and is_green(entry(view, run.run_id))
    assert view.generated_at == env.now and view.generated_at.utcoffset() == timedelta(0)


def test_hostile_text_is_refused_by_constructors_with_fixed_code_and_no_echo():
    for bad in ("", "a\x00b", "x" * 5000, "zero\u200bwidth", LyingStr("t1"), None, 5):
        with pytest.raises(ValueError, match="^TIMELINE_SUBJECT_INVALID$"):
            TimelineSubject(bad, "A", KEY, ())
        with pytest.raises(ValueError, match="^TIMELINE_SUBJECT_INVALID$"):
            TimelineSubject("t1", "A", bad, ())
    with pytest.raises(ValueError, match="^TIMELINE_SUBJECT_INVALID$"):
        TimelineSubject("t1", "A", KEY, [object()])  # type: ignore[arg-type]
    for bad_digest in ("", "g" * 64, "A" * 64, h(1)[:-1], LyingStr(h(1))):
        with pytest.raises(ValueError, match="^RUN_BINDING_INVALID$"):
            RunBinding("run-000001", "att-1", bad_digest, POL_VER, POL_DIG)
    for bad in (True, LyingInt(5), -1, 2**64, 1.5, None):
        with pytest.raises(ValueError, match="^APPLICABILITY_POLICY_INVALID$"):
            ApplicabilityPolicy(bad, REV, False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="^APPLICABILITY_POLICY_INVALID$"):
        ApplicabilityPolicy(3600, REV, "no")  # type: ignore[arg-type]


def test_guid_shaped_ids_are_preserved_exactly_other_text_untouched(env):
    guid = "{ABCDEF01-2345-6789-ABCD-EF0123456789}"
    sub = TimelineSubject("t1", "A", guid, ())
    assert sub.comparison_key == guid  # the view layer never rewrites caller text
    assert TimelineSubject("t1", "A", "Cafe-Key/1", ()).comparison_key == "Cafe-Key/1"


def test_poison_in_a_ledger_that_raises_is_not_leaked(env, monkeypatch):
    env.live_run()

    def boom(self, *a):
        raise RuntimeError("POISON-FOREIGN-SOURCE stacktrace secret=abc")

    monkeypatch.setattr(RunLedger, "list_runs", boom)
    out = env.build()
    assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED
    assert "POISON" not in repr(out) and "secret" not in repr(out)


# ===================================================== TC120: scope in the timeline builder
def test_tc120_foreign_company_rows_are_dropped_with_only_an_opaque_flag(env):
    run = env.live_run()
    foreign = env.go(env.snap(v="B"), key="FOREIGN-KEY-B")
    env.extra_subjects = (TimelineSubject("t1", "B", "FOREIGN-KEY-B",
                                          (RunBinding(foreign.run_id, None, REV, POL_VER, POL_DIG),)),)
    env.feeds = (feed_with(event("FOREIGN-EVENT-B"), company="B"), feed_with(event("ev-a")))
    view = env.build()
    assert type(view) is TimelineView
    refs = {e.ref_id for e in view.entries}
    assert run.run_id in refs and "ev-a" in refs
    assert foreign.run_id not in refs and "FOREIGN-EVENT-B" not in refs
    assert view.hidden_by_scope is True
    text = repr(view) + repr(view.entries) + view.digest
    for needle in ("FOREIGN", foreign.run_id, "company B", "'B'"):
        assert needle not in text
    assert not hasattr(view, "hidden_count") and not hasattr(view, "foreign")


def test_tc120_no_foreign_rows_means_flag_false(env):
    env.live_run()
    assert env.build().hidden_by_scope is False


def test_tc120_hidden_flag_is_identical_for_one_or_many_foreign_rows(env):
    env.live_run()
    one = TimelineSubject("t1", "B", "K1", ())
    many = tuple(TimelineSubject("t1", "B", f"K{i}", ()) for i in range(5))
    env.extra_subjects = (one,)
    a = env.build()
    env.extra_subjects = many
    b = env.build()
    assert a.hidden_by_scope is b.hidden_by_scope is True
    assert a.digest == b.digest  # nothing about the number of foreign rows is observable


def test_tc120_stale_scope_epoch_gives_safe_error_and_no_entries(env):
    env.live_run()
    env.epochs[("t1", "A")] = 6
    out = env.build()
    assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE
    assert not hasattr(out, "entries")


@pytest.mark.parametrize("lookup", [lambda t, c: None, lambda t, c: True, lambda t, c: LyingInt(5),
                                    lambda t, c: "5", lambda t, c: 1 / 0])
def test_tc120_unusable_epoch_lookup_is_stale_never_disclosure(env, lookup):
    env.live_run()
    out = env.build(authority=ScopeAuthority(lookup))
    assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


def test_tc120_revoke_between_build_and_render_is_rechecked_before_disclosure(env):
    env.live_run()
    view = env.build()
    assert render_guard(view, env.authority) is view
    env.epochs[("t1", "A")] = 6  # access revoked after the view was built
    out = render_guard(view, env.authority)
    assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


def test_tc120_epoch_changing_during_build_is_caught_by_the_final_recheck(env):
    env.live_run()
    calls = itertools.count()

    def lookup(t, c):
        return 5 if next(calls) == 0 else 6  # valid on entry, revoked by the time of disclosure

    out = env.build(authority=ScopeAuthority(lookup))
    assert type(out) is SafeError and out.reason_code is ReasonCode.SCOPE_EPOCH_STALE


def test_tc120_render_guard_refuses_forged_and_foreign_views(env):
    env.live_run()
    view = env.build()
    for bad in (None, "v", object(), object.__new__(TimelineView), [view]):
        assert type(render_guard(bad, env.authority)) is SafeError
    assert type(render_guard(view, object())) is SafeError
    other = ViewerScope("t1", "B", 5)
    other_view = env.build(viewer=other, subjects=(TimelineSubject("t1", "B", "x", ()),))
    assert type(other_view) is TimelineView and other_view.company_id == "B"


def test_tc120_other_tenant_attestations_never_appear(env):
    env.live_run()
    other = AttestationStore(env.clock, accountants={"t2": {"acc2"}}, id_source=lambda: "att-t2-FOREIGN")
    other.sign(AttestationRequest("t2", REV, POL_VER, POL_DIG, "p", "r", AttestationDecision.PASS),
               Signer(SignerKind.HUMAN, "acc2"))
    view = env.build(attestations=other)
    assert "FOREIGN" not in repr(view)  # history is tenant-scoped: t2 rows are not t1 rows


# ===================================================== TC118: known / effective labels
def test_tc118_label_constants_are_verbatim():
    assert (KNOWN_AT_LABEL, EFFECTIVE_AT_LABEL, EFFECTIVE_UNKNOWN_LABEL, HISTORICAL_LABEL) == (
        "KNOWN_AT", "EFFECTIVE_AT", "EFFECTIVE_UNKNOWN", "historical, not current")
    assert KnownTimeLabel(T0).label == "KNOWN_AT"
    assert EffectiveTimeLabel.at_time(T0).label == "EFFECTIVE_AT"
    unknown = EffectiveTimeLabel.unknown()
    assert unknown.label == "EFFECTIVE_UNKNOWN" and unknown.at is None
    assert unknown.reason is ReasonCode.EFFECTIVE_UNKNOWN


def test_tc118_two_axes_are_different_types_and_no_single_date_field_exists():
    assert KnownTimeLabel is not EffectiveTimeLabel
    assert KnownTimeLabel(T0) != EffectiveTimeLabel.at_time(T0)
    names = set(TimelineEntry.__slots__)
    assert {"known", "effective"} <= names
    assert not names & {"date", "at", "timestamp", "time", "when"}
    with pytest.raises(ValueError, match="^TIME_LABEL_INVALID$"):
        KnownTimeLabel(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="^TIME_LABEL_INVALID$"):
        EffectiveTimeLabel(T0, EFFECTIVE_UNKNOWN_LABEL, ReasonCode.EFFECTIVE_UNKNOWN)  # lying combination
    with pytest.raises(ValueError, match="^TIME_LABEL_INVALID$"):
        KnownTimeLabel(datetime(2026, 1, 1))  # noqa: DTZ001 - naive on purpose


def test_tc118_event_with_effective_time_shows_both_labels_with_different_values(env):
    rec, obs, eff = T0 + timedelta(days=3), T0 + timedelta(days=2), T0 + timedelta(days=1)
    env.feeds = (feed_with(event("e1", rec, obs, eff)),)
    e = entry(env.build(), "e1")
    assert e.kind is EntryKind.EVENT
    assert e.known.at == rec and e.known.label == "KNOWN_AT"
    assert e.effective.at == eff and e.effective.label == "EFFECTIVE_AT"
    assert e.known.at != e.effective.at


def test_tc118_missing_effective_time_is_unknown_and_never_copies_recorded_or_observed(env):
    rec, obs = T0 + timedelta(days=3), T0 + timedelta(days=2)
    env.feeds = (feed_with(event("e1", rec, obs, None)),)
    view = env.build()
    e = entry(view, "e1")
    assert e.effective.at is None and e.effective.label == "EFFECTIVE_UNKNOWN"
    assert e.effective.reason is ReasonCode.EFFECTIVE_UNKNOWN
    assert e.known.at == rec
    for forbidden in (rec, obs, env.now):
        assert e.effective.at != forbidden


def test_tc118_run_and_attestation_entries_have_unknown_effective_time(env):
    run = env.live_run()
    view = env.build()
    for ref in (run.run_id, env.bindings[0].attestation_id):
        assert entry(view, ref).effective.label == "EFFECTIVE_UNKNOWN"
    assert entry(view, run.run_id).known.at == run.recorded_at  # known axis = ledger recorded_at


def test_tc118_late_correction_sorts_by_known_axis_and_by_effective_axis(env):
    early_known = event("early", T0 + timedelta(days=1), eff=T0 + timedelta(days=5), obj="a", rev="r1")
    late_fix = event("late", T0 + timedelta(days=4), eff=T0 + timedelta(days=2), obj="b", rev="r2")
    no_eff = event("noeff", T0 + timedelta(days=2), obj="c", rev="r3")
    env.feeds = (feed_with(early_known, late_fix, no_eff),)
    view = env.build()
    refs = [e.ref_id for e in view.by_known()]
    assert refs == ["early", "noeff", "late"]
    eff_refs = [e.ref_id for e in view.by_effective()]
    assert eff_refs == ["late", "early", "noeff"]  # unknown effective time last, never guessed in place


def test_tc118_gap_is_visible_as_a_gap_not_hidden(env):
    env.feeds = (feed_with(event("g1", T0 + timedelta(days=1), kind=EventKind.GAP),
                           event("u1", T0 + timedelta(days=2), kind=EventKind.SOURCE_UNAVAILABLE, obj="o2")),)
    view = env.build()
    for ref in ("g1", "u1"):
        e = entry(view, ref)
        assert e.gap is True and e.applicability is Applicability.UNKNOWN and not is_green(e)
    assert entry(env.build(), "g1").label_text == "gap in history"


def test_tc118_events_recorded_after_now_are_not_yet_known(env):
    env.feeds = (feed_with(event("future", env.now + timedelta(seconds=1))),)
    assert [e for e in env.build().entries if e.ref_id == "future"] == []


def test_active_attestation_row_is_an_evidence_row_never_green(env):
    env.live_run()
    a = entry(env.build(), env.bindings[0].attestation_id)
    assert a.applicability is Applicability.UNKNOWN and a.reason is ApplicabilityReason.EVIDENCE_ROW
    assert not is_green(a)


def test_tc118_observation_event_is_never_green(env):
    env.feeds = (feed_with(event("obs1", T0)),)
    assert not is_green(entry(env.build(), "obs1"))


def test_tc118_revocation_event_is_a_revoked_entry(env):
    env.feeds = (feed_with(event("o1", T0), event("rv", T0 + timedelta(days=1), kind=EventKind.ATTESTATION_REVOKED)),)
    assert entry(env.build(), "rv").applicability is Applicability.REVOKED


# ===================================================== happy path / determinism / honesty
def test_happy_live_current_requires_everything_and_is_green(env):
    run = env.live_run()
    view = env.build()
    e = entry(view, run.run_id)
    assert e.applicability is Applicability.LIVE_CURRENT and e.reason is None and is_green(e)
    assert e.kind is EntryKind.RUN and e.authority == "EVALUATION_ONLY"
    assert view.authority == "EVALUATION_ONLY" and "offline" in view.basis.lower()
    assert view.tenant_id == "t1" and view.company_id == "A" and view.scope_epoch == 5


def test_view_is_deterministic_and_digest_changes_with_content(env):
    env.live_run()
    a, b = env.build(), env.build()
    assert a.digest == b.digest and len(a.digest) == 64 and a == b
    env.now += timedelta(seconds=3601)
    assert env.build().digest != a.digest


def test_view_types_are_frozen_slots(env):
    env.live_run()
    view = env.build()
    for obj, attr in ((view, "tenant_id"), (view.entries[0], "ref_id"), (view.entries[0].known, "label")):
        assert not hasattr(obj, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attr, "x")


def test_correlation_id_is_injected_not_derived_from_input(env):
    env.epochs[("t1", "A")] = 6
    out = env.build(correlation_id="CORR-42")
    assert out.correlation_id == "CORR-42"
    assert env.build(correlation_id="bad id with spaces\n").correlation_id == "CORR-UNASSIGNED"


def test_building_a_view_does_not_mutate_the_ledgers(env):
    run = env.live_run()
    before = (env.ledger.list_runs("t1", KEY), env.att.history("t1"), len(env.att.audit()))
    env.build()
    after = (env.ledger.list_runs("t1", KEY), env.att.history("t1"))
    assert before[:2] == after and env.ledger.get("t1", run.run_id) == run


# ===================================================== module boundary (static)
def test_module_imports_only_stdlib_and_sibling_phase2():
    src = Path(tv.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {"httpx", "requests", "socket", "os", "pathlib", "subprocess", "sqlite3", "asyncpg",
              "psycopg", "open", "business_ai_gateway"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & banned
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 1 or (node.module or "").split(".")[0] not in banned
            if node.level == 0:
                assert (node.module or "").split(".")[0] in {"__future__", "collections", "dataclasses",
                                                              "datetime", "enum", "typing", "decimal", "re"}
        elif isinstance(node, ast.Name) and node.id == "open":
            raise AssertionError("file I/O is forbidden")
    assert "capability_enabled" not in src and "operation_covered" not in src
    assert "check_as_of" not in src  # a historical query is never a gate
