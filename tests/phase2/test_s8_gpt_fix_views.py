"""S8 GPT-PM gate remediation, stream K3: timeline_view / coverage_view findings M02, M03, M10, M11.

M02 ledger-backed views need independently verified company ownership of every comparison key and of every
RunRecord the provider returns; M03 a casefold/NFKC tenant variant is another tenant (no trace, never SIBLING);
M10 a blocking event at the SAME timestamp as a PASS run is not green; M11 conflicting own-company subjects of
one comparison key fail closed and never make green depend on order. Offline and in-memory.
"""
from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.comparison_snapshot import (
    RunLedger,
    RunView,
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
    ApplicabilityPolicy,
    EntryKind,
    EventFeed,
    RunBinding,
    ScopeAuthority,
    TimelineSubject,
    TimelineView,
    build_timeline,
    is_green,
)
from business_ai_gateway.phase2.validation_coverage import (
    Claim,
    ClaimScope,
    Evidence,
    EvidenceVerdict,
    Link,
    build_matrix,
)
from business_ai_gateway.phase2.workbench_types import (
    FakeOwnership,
    ReasonCode,
    SafeError,
    ViewerScope,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
REV, POL_VER, POL_DIG = f"{1:064x}", "pol-v1", f"{2:064x}"
SECRET_NATIVE, SECRET_GATEWAY = Decimal("9876.54"), Decimal("1234.56")


def h(n: int) -> str:
    return f"{n:064x}"


class W:
    def __init__(self):
        self.now = T0 + timedelta(days=10)
        self.store = SnapshotStore(self.clock)
        self.ledger = RunLedger(self.store)
        ids = (f"att-{i}" for i in itertools.count())
        self.att = AttestationStore(self.clock, accountants={"t1": {"acc1"}, "t2": {"acc2"}},
                                    id_source=lambda: next(ids))
        self.epochs = {("t1", "A"): 5, ("t1", "B"): 5, ("Tenant-A", "A"): 5, ("Tenant-A", "B"): 5}
        self.authority = ScopeAuthority(lambda t, c: self.epochs.get((t, c)))
        self.viewer = ViewerScope("t1", "A", 5)
        self.policy = ApplicabilityPolicy(3600, REV, False)
        scope = ClaimScope("t1", "A")
        self.matrix = build_matrix((Claim("cl-A", scope, "purchases", "validate"),),
                                   (Evidence("ev-A", scope, "src-A", h(7), EvidenceVerdict.PASS),),
                                   (Link("cl-A", "ev-A"),))
        self.own = FakeOwnership()
        self.own.add("t1", "A", "comparison_key", "KEY-A")
        self.own.add("t1", "B", "comparison_key", "KEY-B")

    def clock(self):
        return self.now

    def run(self, key, native=Decimal(24), gateway=Decimal(24), tenant="t1"):
        snap = self.store.create(tenant, {"account": "521.1", "values": {"native": {"m": native},
                                                                         "gateway": {"m": gateway}}},
                                 known_at=T0)

        def read(side):
            return SideRead(side, snap.snapshot_id, snap.digest, _projection(snap, side))
        return self.ledger.run(tenant, key, read("native"), read("gateway"), snapshot_id=snap.snapshot_id)

    def attest(self):
        res = self.att.sign(AttestationRequest("t1", REV, POL_VER, POL_DIG, "prop", "req",
                                               AttestationDecision.PASS), Signer(SignerKind.HUMAN, "acc1"))
        assert res.signed
        return res.attestation.attestation_id

    @staticmethod
    def bind(run, att_id):
        return RunBinding(run.run_id, att_id, REV, POL_VER, POL_DIG)

    def timeline(self, subjects, **over):
        args = {"viewer": self.viewer, "authority": self.authority, "ledger": self.ledger,
                "attestations": self.att, "subjects": subjects, "feeds": (), "matrix": self.matrix,
                "policy": self.policy, "clock": self.clock, "ownership": self.own}
        args.update(over)
        return build_timeline(**args)

    def diff(self, subjects, **over):
        args = {"viewer": self.viewer, "authority": self.authority, "ledger": self.ledger,
                "subjects": subjects, "ownership": self.own}
        args.update(over)
        return build_scoped_diff(**args)


def gap_feed(at, kind=EventKind.GAP, eid="g1"):
    led = EventLedger("t1", "s1")
    led.append(ModelEvent(eid, "t1", "s1", "o1", "r1", kind, at, at, None, None))
    return EventFeed("t1", "A", led)


# ============================================================ M02 ownership
def test_m02_mislabeled_subject_does_not_disclose_foreign_run_ids_or_sums_in_diff():
    w = W()
    foreign = w.run("KEY-B", SECRET_NATIVE, SECRET_GATEWAY)
    out = w.diff((TimelineSubject("t1", "A", "KEY-B", ()),))  # company A claims B's key
    assert type(out) is ScopedDiffView and out.items == () and out.hidden_by_scope is False
    unknown = w.diff((TimelineSubject("t1", "A", "KEY-NOBODY", ()),))
    assert out.items == unknown.items and out.hidden_by_scope == unknown.hidden_by_scope
    text = repr(out)
    for secret in (foreign.run_id, "9876.54", "1234.56"):
        assert secret not in text
    # positive control: the really owned key IS shown
    w.run("KEY-A", SECRET_NATIVE, SECRET_GATEWAY)
    own = w.diff((TimelineSubject("t1", "A", "KEY-A", ()),))
    assert type(own) is ScopedDiffView and len(own.items) == 1 and own.items[0].native == SECRET_NATIVE


def test_m02_mislabeled_subject_leaves_no_run_entry_in_timeline_and_ledger_is_not_read(monkeypatch):
    w = W()
    foreign = w.run("KEY-B")
    calls = []
    real = RunLedger.list_runs
    monkeypatch.setattr(RunLedger, "list_runs", lambda self, *a: (calls.append(a), real(self, *a))[1])
    view = w.timeline((TimelineSubject("t1", "A", "KEY-B", (w.bind(foreign, w.attest()),)),))
    assert type(view) is TimelineView and view.entries == ()
    assert calls == []  # ownership is verified BEFORE the ledger is read
    assert foreign.run_id not in repr(view) and "att-" not in repr(view)


def test_m02_ownership_is_verified_for_every_key_before_any_ledger_read(monkeypatch):
    w = W()
    w.run("KEY-A")
    calls = []
    real = RunLedger.list_runs
    monkeypatch.setattr(RunLedger, "list_runs", lambda self, *a: (calls.append(a), real(self, *a))[1])
    subs = (TimelineSubject("t1", "A", "KEY-A", ()), TimelineSubject("t1", "A", "KEY-B", ()))
    assert type(w.diff(subs)) is ScopedDiffView
    assert calls == [("t1", "KEY-A")]  # the mislabeled key is never read


@pytest.mark.parametrize("kind", ["wrong_key", "wrong_tenant"])
def test_m02_provider_returning_a_foreign_record_discloses_nothing_in_diff_and_timeline(monkeypatch, kind):
    w = W()
    w.run("KEY-A")
    if kind == "wrong_key":
        foreign = w.run("KEY-B", SECRET_NATIVE, SECRET_GATEWAY)
    else:
        foreign = w.run("KEY-A", SECRET_NATIVE, SECRET_GATEWAY, tenant="t2")
    foreign_view = RunView(foreign, "CURRENT", None)
    monkeypatch.setattr(RunLedger, "list_runs", lambda self, *a: (foreign_view,))
    subs = (TimelineSubject("t1", "A", "KEY-A", ()),)
    for out in (w.diff(subs), w.timeline(subs)):
        assert type(out) is SafeError and out.reason_code is ReasonCode.INTERNAL_REFUSED
        for secret in (foreign.run_id, "9876.54", "1234.56"):
            assert secret not in repr(out)


def test_m02_ownership_is_required_and_hostile_ports_fail_closed():
    w = W()
    w.run("KEY-A", SECRET_NATIVE, SECRET_GATEWAY)
    subs = (TimelineSubject("t1", "A", "KEY-A", ()),)
    with pytest.raises(TypeError):
        build_scoped_diff(w.viewer, w.authority, w.ledger, subs)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        build_timeline(w.viewer, w.authority, w.ledger, w.att, subs, (), w.matrix, w.policy, w.clock)  # type: ignore[call-arg]

    class Boom:
        def owns(self, *a):
            raise RuntimeError("POISON")

    class Yes:
        def owns(self, *a):
            return "yes"  # not exactly True

    for port in (Boom(), Yes()):
        out = w.diff(subs, ownership=port)
        assert type(out) is ScopedDiffView and out.items == () and "POISON" not in repr(out)
        view = w.timeline(subs, ownership=port)
        assert type(view) is TimelineView and view.entries == ()
    for bad in (None, object(), 5):
        assert type(w.diff(subs, ownership=bad)) is SafeError
        assert type(w.timeline(subs, ownership=bad)) is SafeError


def test_m02_panel_and_evidence_require_a_valid_ownership_port():
    w = W()
    ev = (Claim("cA", ClaimScope("t1", "A"), "p", "validate"),)
    assert type(build_coverage_panel(w.viewer, w.authority, w.matrix, ownership=w.own)) is CoveragePanel
    assert type(build_scoped_evidence(w.viewer, w.authority, ev, (), (), ownership=w.own)) is ScopedEvidenceView
    with pytest.raises(TypeError):
        build_coverage_panel(w.viewer, w.authority, w.matrix)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        build_scoped_evidence(w.viewer, w.authority, ev, (), ())  # type: ignore[call-arg]
    assert type(build_coverage_panel(w.viewer, w.authority, w.matrix, ownership=object())) is SafeError
    assert type(build_scoped_evidence(w.viewer, w.authority, ev, (), (), ownership=None)) is SafeError


# ============================================================ M03 tenant variants
@pytest.mark.parametrize("variant", ["TENANT-A", "tenant-a", "Ｔenant-A"])
def test_m03_tenant_case_and_nfkc_variants_leave_no_trace(variant):
    w = W()
    w.viewer = ViewerScope("Tenant-A", "A", 5)
    w.own.add("Tenant-A", "A", "comparison_key", "KEY-A")
    base = w.timeline((), feeds=())
    assert type(base) is TimelineView and base.hidden_by_scope is False
    led = EventLedger("t1", "s1")
    led.append(ModelEvent("e1", "t1", "s1", "o1", "r1", EventKind.OBSERVED, T0, T0, None, h(5)))
    for company in ("A", "B"):
        subs = (TimelineSubject(variant, company, "KEY-A", ()),)
        out = w.timeline(subs, feeds=(EventFeed(variant, company, led),))
        assert type(out) is TimelineView
        assert out.hidden_by_scope is False and out.entries == base.entries and out.digest == base.digest
        d = w.diff(subs)
        assert type(d) is ScopedDiffView and d.hidden_by_scope is False
    # control: another company of the EXACT tenant is still the opaque sibling flag
    sib = w.timeline((TimelineSubject("Tenant-A", "B", "KEY-A", ()),))
    assert sib.hidden_by_scope is True


# ============================================================ M10 same-timestamp blockers
@pytest.mark.parametrize("kind", [EventKind.GAP, EventKind.SOURCE_UNAVAILABLE, EventKind.ATTESTATION_REVOKED])
def test_m10_blocking_event_at_the_same_timestamp_as_a_pass_run_is_not_green(kind):
    w = W()
    run = w.run("KEY-A")
    subs = (TimelineSubject("t1", "A", "KEY-A", (w.bind(run, w.attest()),)),)
    w.now += timedelta(hours=1)
    green = next(e for e in w.timeline(subs).entries if e.ref_id == run.run_id)
    assert is_green(green)  # control: without the event the run is green
    out = w.timeline(subs, feeds=(gap_feed(run.recorded_at, kind),))
    got = next(e for e in out.entries if e.kind is EntryKind.RUN and e.ref_id == run.run_id)
    assert not is_green(got)
    older = w.timeline(subs, feeds=(gap_feed(run.recorded_at - timedelta(seconds=1), kind),))
    assert is_green(next(e for e in older.entries if e.ref_id == run.run_id))  # strictly older still ok


# ============================================================ M11 conflicting duplicates
def test_m11_conflicting_own_subjects_fail_closed_and_order_never_changes_the_result():
    w = W()
    run = w.run("KEY-A")
    attested = TimelineSubject("t1", "A", "KEY-A", (w.bind(run, w.attest()),))
    unattested = TimelineSubject("t1", "A", "KEY-A", (w.bind(run, None),))
    results = [w.timeline(p) for p in ((attested, unattested), (unattested, attested))]
    for r in results:
        if type(r) is TimelineView:
            assert not any(is_green(e) for e in r.entries)
        else:
            assert type(r) is SafeError
    assert results[0] == results[1]
    d1, d2 = w.diff((attested, unattested)), w.diff((unattested, attested))
    assert d1 == d2


def test_m11_identical_duplicates_are_deduplicated_and_still_green():
    w = W()
    run = w.run("KEY-A")
    sub = TimelineSubject("t1", "A", "KEY-A", (w.bind(run, w.attest()),))
    twin = TimelineSubject("t1", "A", "KEY-A", sub.bindings)
    single, double = w.timeline((sub,)), w.timeline((sub, twin))
    assert type(double) is TimelineView and double.entries == single.entries
    assert any(is_green(e) for e in double.entries)
