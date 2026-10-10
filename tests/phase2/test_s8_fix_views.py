"""S8 review fix batch, stream G3: timeline_view / coverage_view scope, identity, digest, time and provider rows.

Each test pins one defect class found in the S8 review (tenant-wide attestation disclosure, casefold scope
mismatch, foreign-data-dependent errors, untested EMPTY_MATRIX, unverified digests, clock strictness,
ignored newer GAP/SOURCE_UNAVAILABLE/REVOKED events, provider faults reported as caller faults, lying str
authority/basis). Offline and in-memory: real RunLedger / AttestationStore / EventLedger / MatrixResult.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from functools import partial

import pytest

from business_ai_gateway.phase2 import timeline_view as tv
from business_ai_gateway.phase2.comparison_snapshot import (
    RunLedger,
    SideRead,
    SnapshotStore,
    _projection,
)
from business_ai_gateway.phase2.coverage_view import (
    CoveragePanel,
    ScopedDiffView,
    ScopedEvidenceView,
    build_coverage_panel,
    build_scoped_diff,
    build_scoped_evidence,
    render_guard_coverage,
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
    Applicability,
    ApplicabilityPolicy,
    ApplicabilityReason,
    EffectiveTimeLabel,
    EntryKind,
    EventFeed,
    KnownTimeLabel,
    RunBinding,
    ScopeAuthority,
    TimelineSubject,
    TimelineView,
    build_timeline,
    is_green,
    render_guard,
)
from business_ai_gateway.phase2.validation_coverage import (
    Claim,
    ClaimScope,
    CoverageCode,
    CoverageStatus,
    Evidence,
    EvidenceVerdict,
    Link,
    MatrixResult,
    MatrixRow,
    _matrix_digest,
    build_matrix,
)
from business_ai_gateway.phase2.workbench_types import ReasonCode, SafeError, ViewerScope


class _AllOwned:
    """Permissive OwnershipPort: these tests pin scope/view behavior, not ownership (see test_s8_gpt_fix_views)."""

    def owns(self, tenant_id, company_id, kind, ref):
        return True


_ALL_OWNED = _AllOwned()
build_coverage_panel = partial(build_coverage_panel, ownership=_ALL_OWNED)
build_scoped_diff = partial(build_scoped_diff, ownership=_ALL_OWNED)
build_scoped_evidence = partial(build_scoped_evidence, ownership=_ALL_OWNED)


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
REV, POL_VER, POL_DIG = f"{1:064x}", "pol-v1", f"{2:064x}"
PASS = EvidenceVerdict.PASS
HUMAN = SignerKind.HUMAN
A, B, T2A = ClaimScope("t1", "A"), ClaimScope("t1", "B"), ClaimScope("t2", "A")


def h(n: int) -> str:
    return f"{n:064x}"


class LyingStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class ZeroZone(tzinfo):
    """A zero-offset zone that is not the UTC singleton."""

    def utcoffset(self, dt):
        return timedelta(0)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "ZERO"


class LyingDT(datetime):
    def __eq__(self, other):
        return True

    __hash__ = datetime.__hash__


class W:
    """Tenant t1 (companies A and B) plus tenant t2; the clock only moves when told."""

    def __init__(self, att_ids=("att-A", "att-B", "att-ORPHAN", "att-T2")):
        self.now = T0 + timedelta(days=10)
        self.store = SnapshotStore(self.clock)
        self.ledger = RunLedger(self.store)
        ids = iter(att_ids)
        self.att = AttestationStore(self.clock, accountants={"t1": {"acc1"}, "t2": {"acc2"}},
                                    id_source=lambda: next(ids))
        self.epochs = {("t1", "A"): 5, ("t1", "B"): 5, ("Acme", "x"): 5, ("t2", "A"): 5}
        self.authority = ScopeAuthority(lambda t, c: self.epochs.get((t, c)))
        self.viewer = ViewerScope("t1", "A", 5)
        self.policy = ApplicabilityPolicy(3600, REV, False)
        self.matrix = self.matrix_for("A")

    def clock(self) -> datetime:
        return self.now

    @staticmethod
    def matrix_for(company, tenant="t1"):
        scope = ClaimScope(tenant, company)
        return build_matrix((Claim("cl-" + company, scope, "purchases", "validate"),),
                            (Evidence("ev-" + company, scope, "src-" + company, h(7), PASS),),
                            (Link("cl-" + company, "ev-" + company),))

    def run(self, key, tag="a"):
        snap = self.store.create("t1", {"account": "521.1", "tag": tag,
                                        "values": {"native": {"m": Decimal(24)}, "gateway": {"m": Decimal(24)}}},
                                 known_at=T0)

        def read(side):
            return SideRead(side, snap.snapshot_id, snap.digest, _projection(snap, side))
        return self.ledger.run("t1", key, read("native"), read("gateway"), snapshot_id=snap.snapshot_id)

    def attest(self, tenant="t1", signer="acc1"):
        res = self.att.sign(AttestationRequest(tenant, REV, POL_VER, POL_DIG, "prop", "req",
                                               AttestationDecision.PASS), Signer(HUMAN, signer))
        assert res.signed
        return res.attestation.attestation_id

    @staticmethod
    def bind(run, att_id):
        return RunBinding(run.run_id, att_id, REV, POL_VER, POL_DIG)

    def timeline(self, subjects, **over):
        args = {"viewer": self.viewer, "authority": self.authority, "ledger": self.ledger,
                "attestations": self.att, "subjects": subjects, "feeds": (), "matrix": self.matrix,
                "policy": self.policy, "clock": self.clock, "ownership": _ALL_OWNED}
        args.update(over)
        return build_timeline(**args)


@pytest.fixture
def w():
    return W()


def live(w):
    """One live run of company A; returns (run, subjects)."""
    run = w.run("KEY-A")
    return run, (TimelineSubject("t1", "A", "KEY-A", (w.bind(run, w.attest()),)),)


def event(eid, rec, kind=EventKind.OBSERVED, obj="o1"):
    return ModelEvent(eid, "t1", "s1", obj, "r1", kind, rec, rec, None,
                      h(5) if kind is EventKind.OBSERVED else None)


def feed_of(*events, company="A", tenant="t1"):
    led = EventLedger("t1", "s1")
    for e in events:
        led.append(e)
    return EventFeed(tenant, company, led)


# ===================================================== 1: attestations only via the viewer's own runs
def test_timeline_emits_only_attestations_bound_to_the_viewers_own_runs(w):
    ra, rb = w.run("KEY-A", "a"), w.run("KEY-B", "b")
    a, b = w.attest(), w.attest()
    w.attest()  # orphan: signed for tenant t1, bound to nobody
    w.attest("t2", "acc2")  # other tenant, same store
    subs = (TimelineSubject("t1", "A", "KEY-A", (w.bind(ra, a),)),
            TimelineSubject("t1", "B", "KEY-B", (w.bind(rb, b),)))
    view = w.timeline(subs)
    assert type(view) is TimelineView
    assert {e.ref_id for e in view.entries if e.kind is EntryKind.ATTESTATION} == {"att-A"}
    for foreign in ("att-B", "att-ORPHAN", "att-T2", rb.run_id, "KEY-B"):
        assert foreign not in repr(view)
    assert view.hidden_by_scope is True  # company B of the same tenant: only the opaque flag
    assert w.att.revoke(b, "t1", Signer(HUMAN, "acc1")).revoked  # revoking a foreign attestation ...
    again = w.timeline(subs)
    assert again.entries == view.entries and again.digest == view.digest  # ... changes nothing for A


def test_timeline_attestation_not_yet_signed_at_the_injected_clock_is_not_shown(w):
    run = w.run("KEY-A")
    w.now += timedelta(hours=1)
    att_id = w.attest()
    w.now -= timedelta(hours=1)  # clock reads earlier than the signature
    view = w.timeline((TimelineSubject("t1", "A", "KEY-A", (w.bind(run, att_id),)),))
    assert type(view) is TimelineView and att_id not in {e.ref_id for e in view.entries}
    assert not any(is_green(e) for e in view.entries)


# ===================================================== 2: one exact identity rule before any read
@pytest.mark.parametrize("scope", [("ACME", "X"), ("Acme", "X"), ("ACME", "x")])
def test_casefold_variant_subject_is_foreign_and_the_ledger_is_never_read(scope):
    w = W()
    w.viewer = ViewerScope("Acme", "x", 5)
    spy_calls = []
    real = RunLedger.list_runs

    def spy(self, *a):
        spy_calls.append(a)
        return real(self, *a)

    RunLedger.list_runs = spy  # type: ignore[method-assign]
    try:
        view = w.timeline((TimelineSubject(scope[0], scope[1], "K", ()),),
                          feeds=(feed_of(event("e1", T0), tenant=scope[0], company=scope[1]),))
        assert type(view) is TimelineView
        # M03: only another company of the EXACT tenant leaves the opaque flag; a tenant variant leaves no trace
        assert view.hidden_by_scope is (scope[0] == "Acme") and view.entries == ()
        assert spy_calls == []
        w.timeline((TimelineSubject("Acme", "x", "K", ()),))
        assert spy_calls == [("Acme", "K")]  # positive control: the exact scope IS read
    finally:
        RunLedger.list_runs = real  # type: ignore[method-assign]


def test_other_tenant_subject_is_dropped_without_even_the_opaque_flag(w):
    view = w.timeline((TimelineSubject("t2", "A", "K", ()),), feeds=(feed_of(event("e1", T0), tenant="t2"),))
    assert type(view) is TimelineView and view.entries == () and view.hidden_by_scope is False


def test_foreign_malformed_subject_does_not_break_the_viewers_timeline(w):
    run, subs = live(w)
    base = w.timeline(subs)
    junk = TimelineSubject("t1", "B", "K", ())
    object.__setattr__(junk, "comparison_key", "bad\x00key")
    object.__setattr__(junk, "bindings", (object.__new__(RunBinding),))
    out = w.timeline(subs + (junk,))
    assert type(out) is TimelineView and out.entries == base.entries and out.hidden_by_scope is True
    assert run.run_id in {e.ref_id for e in out.entries}


# ===================================================== 3: foreign data cannot change what the viewer sees
def test_refused_matrix_panel_shows_one_fixed_code_whatever_the_foreign_reason(w):
    empty = build_matrix((), (), ())
    dup = build_matrix((Claim("c", A, "purchases", "validate"), Claim("c", B, "sales", "validate")), (), ())
    assert empty.code is not dup.code and empty.status is dup.status is CoverageStatus.REFUSED
    p1, p2 = (build_coverage_panel(w.viewer, w.authority, m) for m in (empty, dup))
    assert p1.status is p2.status is CoverageStatus.REFUSED
    assert p1.code is p2.code is CoverageCode.CLAIM_INVALID and p1.digest == p2.digest
    assert p1.hidden_by_scope is False and p1.covered == () and p1.complete is False


def _evidence_args(extra_scope=B):
    claims = (Claim("cA", A, "purchases", "validate"),)
    ev = (Evidence("eA", A, "sA", h(1), PASS),)
    links = (Link("cA", "eA"),)
    junk_claims = (Claim("cX", extra_scope, "p", "validate"), Claim("cX", extra_scope, "q", "validate"),
                   Claim("bad\x00id", extra_scope, "z", "validate"))
    junk_ev = (Evidence("eX", extra_scope, "s", h(9), PASS), Evidence("eX2", extra_scope, "s2", "nothex", PASS),
               Evidence("eX", extra_scope, "s3", h(8), PASS))
    junk_links = (Link("ghost", "ghost2"), Link("cX", "nope"), Link("cX", "eX"), Link("cA", "eX"),
                  Link("cX", "eA"), Link("cA", "eX"))
    return (claims, ev, links), (claims + junk_claims, ev + junk_ev, links + junk_links)


@pytest.mark.parametrize(("scope", "flag"), [(B, True), (T2A, False)])
def test_foreign_duplicate_dangling_and_malformed_rows_do_not_change_the_evidence_view(w, scope, flag):
    base_args, junk_args = _evidence_args(scope)
    base = build_scoped_evidence(w.viewer, w.authority, *base_args)
    out = build_scoped_evidence(w.viewer, w.authority, *junk_args)
    assert type(base) is ScopedEvidenceView and type(out) is ScopedEvidenceView
    assert out.items == base.items and [i.evidence_id for i in out.items] == ["eA"]
    assert out.items[0].claim_ids == ("cA",)
    assert base.hidden_by_scope is False and out.hidden_by_scope is flag  # other tenant: no flag
    assert "eX" not in repr(out) and "cX" not in repr(out)


def test_lying_str_scope_is_not_the_viewers_scope(w):
    claims = (Claim("cL", ClaimScope(LyingStr("t1"), LyingStr("A")), "p", "validate"),)
    out = build_scoped_evidence(w.viewer, w.authority, claims, (), ())
    assert type(out) is ScopedEvidenceView and out.items == ()


def _matrix_with(rows, base):
    return MatrixResult(base.status, base.code, rows, base.uncovered, tv.matrix_digest(rows), base.non_pass)


def test_matrix_digest_helper_equals_the_validation_coverage_digest(w):
    assert tv.matrix_digest(w.matrix.rows) == w.matrix.digest == _matrix_digest(w.matrix.rows)


def test_panel_ignores_a_malformed_foreign_row_but_refuses_a_malformed_own_row(w):
    base = build_coverage_panel(w.viewer, w.authority, w.matrix)
    bad_foreign = MatrixRow("cB", "cap", "op", ("e1", "e2"), ("t1", "b"), (h(1),), (), ())
    out = build_coverage_panel(w.viewer, w.authority, _matrix_with(w.matrix.rows + (bad_foreign,), w.matrix))
    assert type(out) is CoveragePanel and out.hidden_by_scope is True
    assert (out.status, out.code, out.covered, out.uncovered) == (base.status, base.code, base.covered,
                                                                  base.uncovered)
    own = w.matrix.rows[0]
    for broken in (replace(own, evidence_digests=()), replace(own, evidence_sources=own.evidence_sources * 2),
                   replace(own, evidence_ids=own.evidence_ids * 2)):
        got = build_coverage_panel(w.viewer, w.authority, _matrix_with((broken,), w.matrix))
        assert type(got) is SafeError and got.reason_code is ReasonCode.INPUT_INVALID


def test_tampered_foreign_row_still_fails_the_integrity_check(w):
    rows = w.matrix.rows + (MatrixRow("cB", "cap", "op", ("e1",), ("t1", "b"), (h(1),), ("s",), ()),)
    forged = MatrixResult(w.matrix.status, w.matrix.code, rows, (), w.matrix.digest, ())
    assert type(build_coverage_panel(w.viewer, w.authority, forged)) is SafeError


def test_other_tenant_matrix_rows_do_not_set_the_hidden_flag(w):
    panel = build_coverage_panel(w.viewer, w.authority, w.matrix_for("A", "t2"))
    assert panel.hidden_by_scope is False and panel.code is CoverageCode.EMPTY_MATRIX


# ===================================================== 4: company with zero rows
def test_company_with_zero_rows_is_incomplete_empty_matrix_never_complete(w):
    panel = build_coverage_panel(w.viewer, w.authority, w.matrix_for("B"))
    assert panel.status is CoverageStatus.INCOMPLETE and panel.code is CoverageCode.EMPTY_MATRIX
    assert panel.complete is False and panel.hidden_by_scope is True
    assert panel.covered == () and panel.uncovered == () and panel.non_pass == ()


# ===================================================== 5: digests verified, lengths, shared helpers
def test_render_guard_rejects_tampered_views(w):
    run, subs = live(w)
    view = w.timeline(subs)
    assert render_guard(view, w.authority) is view
    shortened = w.timeline(subs)
    object.__setattr__(shortened, "entries", shortened.entries[:-1])
    assert type(render_guard(shortened, w.authority)) is SafeError
    flipped = w.timeline(subs)
    revoked_like = next(e for e in flipped.entries if e.kind is EntryKind.ATTESTATION)
    object.__setattr__(revoked_like, "applicability", Applicability.LIVE_CURRENT)
    object.__setattr__(revoked_like, "reason", None)
    assert type(render_guard(flipped, w.authority)) is SafeError
    def fresh_panel():
        return build_coverage_panel(w.viewer, w.authority, w.matrix)

    def fresh_ev():
        return build_scoped_evidence(w.viewer, w.authority, *_evidence_args()[0])

    for make, attr, value in ((fresh_panel, "uncovered", ("fake",)), (fresh_ev, "items", ()),
                              (fresh_panel, "status", CoverageStatus.INCOMPLETE)):
        v = make()
        assert render_guard_coverage(v, w.authority) is v
        object.__setattr__(v, attr, value)
        assert type(render_guard_coverage(v, w.authority)) is SafeError
    assert run.run_id


def test_constructors_refuse_a_digest_that_does_not_match_the_content(w):
    run, subs = live(w)
    view = w.timeline(subs)
    with pytest.raises(ValueError, match="^TIMELINE_VIEW_INVALID$"):
        replace(view, digest=h(3))
    with pytest.raises(ValueError, match="^COVERAGE_PANEL_INVALID$"):
        replace(build_coverage_panel(w.viewer, w.authority, w.matrix), digest=h(3))
    with pytest.raises(ValueError, match="^SCOPED_EVIDENCE_INVALID$"):
        replace(build_scoped_evidence(w.viewer, w.authority, *_evidence_args()[0]), digest=h(3))
    assert run.run_id


def test_shared_helpers_are_public_and_one_refuse_class_is_used():
    from business_ai_gateway.phase2 import coverage_view as cv
    for name in ("Refuse", "check_epoch", "guard", "provider", "text_ok", "digest_ok", "matrix_digest",
                 "scope_relation", "scoped_matrix"):
        assert name in tv.__all__ and hasattr(tv, name)
    assert not hasattr(cv, "_Refuse") and not hasattr(cv, "_guard")
    assert cv.Refuse is tv.Refuse


# ===================================================== 6: time strictness
def test_time_labels_require_exactly_utc_not_just_a_zero_offset():
    zero = datetime(2026, 1, 1, tzinfo=ZeroZone())
    with pytest.raises(ValueError, match="^TIME_LABEL_INVALID$"):
        KnownTimeLabel(zero)
    with pytest.raises(ValueError, match="^TIME_LABEL_INVALID$"):
        EffectiveTimeLabel.at_time(zero)
    assert KnownTimeLabel(datetime(2026, 1, 1, tzinfo=UTC)).at.tzinfo is UTC


def test_provider_record_with_a_subclassed_timestamp_is_refused_not_trusted(w, monkeypatch):
    _run, subs = live(w)
    real = RunLedger.list_runs

    def lying(self, *a):
        views = real(self, *a)
        rec = replace(views[0].record, recorded_at=LyingDT(2026, 9, 11, 12, 0, tzinfo=UTC))
        return (replace(views[0], record=rec),)

    monkeypatch.setattr(RunLedger, "list_runs", lying)
    out = w.timeline(subs)
    assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED


# ===================================================== 7: newer GAP / SOURCE_UNAVAILABLE / REVOKED events
@pytest.mark.parametrize(("kind", "applic", "reason"), [
    (EventKind.GAP, Applicability.UNKNOWN, ApplicabilityReason.HISTORY_GAP),
    (EventKind.SOURCE_UNAVAILABLE, Applicability.UNKNOWN, ApplicabilityReason.HISTORY_GAP),
    (EventKind.ATTESTATION_REVOKED, Applicability.REVOKED, ApplicabilityReason.ATTESTATION_REVOKED),
])
def test_a_newer_blocking_event_of_the_company_leaves_no_run_live_current(w, kind, applic, reason):
    run, subs = live(w)
    w.now += timedelta(hours=1)
    assert is_green(next(e for e in w.timeline(subs).entries if e.ref_id == run.run_id))
    newer = event("blk", run.recorded_at + timedelta(seconds=60), kind)
    view = w.timeline(subs, feeds=(feed_of(newer),))
    got = next(e for e in view.entries if e.ref_id == run.run_id)
    assert got.applicability is applic and got.reason is reason and not is_green(got)


@pytest.mark.parametrize("kind", [EventKind.GAP, EventKind.SOURCE_UNAVAILABLE, EventKind.ATTESTATION_REVOKED])
def test_events_that_are_older_future_foreign_or_observations_do_not_block(w, kind):
    run, subs = live(w)
    w.now += timedelta(hours=1)
    cases = {
        "older": feed_of(event("e", run.recorded_at - timedelta(seconds=1), kind)),
        "future": feed_of(event("e", w.now + timedelta(seconds=1), kind)),
        "foreign_company": feed_of(event("e", run.recorded_at + timedelta(seconds=60), kind), company="B"),
        "observation": feed_of(event("e", run.recorded_at + timedelta(seconds=60))),
    }
    for name, feed in cases.items():
        view = w.timeline(subs, feeds=(feed,))
        assert is_green(next(e for e in view.entries if e.ref_id == run.run_id)), name


# ===================================================== 8: provider faults are not the viewer's fault
def test_provider_malformed_output_is_internal_refused_not_input_invalid(w, monkeypatch):
    run, subs = live(w)
    real_list, real_hist = RunLedger.list_runs, AttestationStore.history
    monkeypatch.setattr(RunLedger, "list_runs", lambda self, *a: list(real_list(self, *a)))
    out = w.timeline(subs)
    assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED
    monkeypatch.setattr(RunLedger, "list_runs", real_list)
    monkeypatch.setattr(AttestationStore, "history", lambda self, *a, **k: [1])
    out = w.timeline(subs)
    assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED
    monkeypatch.setattr(AttestationStore, "history", real_hist)

    def boom(self, *a):
        raise RuntimeError("POISON-FOREIGN-SOURCE secret=abc")

    monkeypatch.setattr(RunLedger, "list_runs", boom)
    out = w.timeline(subs)
    assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED
    assert "POISON" not in repr(out) and run.run_id
    d = build_scoped_diff(w.viewer, w.authority, w.ledger, subs)
    assert type(d) is SafeError and d.reason_code is ReasonCode.INTERNAL_REFUSED


@pytest.mark.parametrize("clock", [lambda: (_ for _ in ()).throw(RuntimeError("X")), lambda: "now", lambda: None])
def test_a_clock_that_fails_or_lies_is_a_provider_fault(w, clock):
    run, subs = live(w)
    out = w.timeline(subs, clock=clock)
    assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED and run.run_id


def test_a_clock_that_is_not_callable_is_a_caller_fault(w):
    out = w.timeline((), clock=5)
    assert type(out) is SafeError and out.reason_code is ReasonCode.INPUT_INVALID


# ===================================================== 9: lying str authority/basis
def test_lying_str_authority_and_basis_are_refused_by_every_view_constructor(w):
    run, subs = live(w)
    views = [w.timeline(subs), build_coverage_panel(w.viewer, w.authority, w.matrix),
             build_scoped_evidence(w.viewer, w.authority, *_evidence_args()[0]),
             build_scoped_diff(w.viewer, w.authority, w.ledger, subs)]
    assert {type(v) for v in views} == {TimelineView, CoveragePanel, ScopedEvidenceView, ScopedDiffView}
    for v in views:
        for attr in ("authority", "basis"):
            with pytest.raises(ValueError, match="_INVALID$"):
                replace(v, **{attr: LyingStr("x")})
    assert run.run_id


def test_a_lying_str_tenant_in_a_view_constructor_is_refused(w):
    run, subs = live(w)
    with pytest.raises(ValueError, match="^TIMELINE_VIEW_INVALID$"):
        replace(w.timeline(subs), tenant_id=LyingStr("t1"))
    assert run.run_id


# ===================================================== scoped diff uses the same exact rule
def test_diff_casefold_variant_subject_is_foreign_and_never_read():
    w = W()
    w.viewer = ViewerScope("Acme", "x", 5)
    out = build_scoped_diff(w.viewer, w.authority, w.ledger, (TimelineSubject("ACME", "X", "K", ()),))
    assert type(out) is ScopedDiffView and out.items == () and out.hidden_by_scope is False  # M03: tenant variant


def test_utc_exact_helper_rejects_zero_offset_non_utc_zones():
    assert tv.utc_exact(datetime(2026, 1, 1, tzinfo=UTC))
    assert not tv.utc_exact(datetime(2026, 1, 1, tzinfo=ZeroZone()))
    assert not tv.utc_exact(LyingDT(2026, 1, 1, tzinfo=UTC))
