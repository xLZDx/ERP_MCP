"""R2-US-039..041 (S8/E4): offline G5 rehearsal through the WorkbenchSession facade. NOT a UAT.

TC115+116+117 chain, TC118+119 chain, TC120 two companies, TC121+122+123 through the facade with the
fake dispatcher call log, composed-component failure -> INTERNAL_REFUSED, no partial disclosure after a
revoke, determinism and concurrency. Real RunLedger / AttestationStore / matrix / E1-E3 functions run
over fakes; the facade must add no decision of its own, which the call-log tests assert.
"""
from __future__ import annotations

import ast
import itertools
import re
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import workbench_session as ws
from business_ai_gateway.phase2.comparison_snapshot import RunLedger, SideRead, SnapshotStore
from business_ai_gateway.phase2.evidence_attestation import (
    AttestationDecision,
    AttestationRequest,
    AttestationStore,
    Signer,
    SignerKind,
)
from business_ai_gateway.phase2.fakes import FakeClock
from business_ai_gateway.phase2.jobs_api import (
    ApiContext,
    ApiDecision,
    CsrfGuard,
    FakeCapturePolicy,
    FakeEventSink,
    FakeJobDispatcher,
    FakeScopeEpochs,
    IdempotencyStore,
    JobKind,
    JobRequest,
    RefusalLog,
    RerunRequest,
    SessionRecord,
    fake_csrf_token,
)
from business_ai_gateway.phase2.safe_errors import FakeCorrelationSource, RenderedError
from business_ai_gateway.phase2.side_effect_boundary import default_registry
from business_ai_gateway.phase2.timeline_view import (
    Applicability,
    ApplicabilityPolicy,
    ApplicabilityReason,
    EntryKind,
    RunBinding,
    TimelineSubject,
    TimelineView,
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
from business_ai_gateway.phase2.workbench_review import CardsResult, DiscrepancyCard, ReviewLog
from business_ai_gateway.phase2.workbench_session import WorkbenchSession
from business_ai_gateway.phase2.workbench_types import (
    AnnotationKind,
    FakeEntitlements,
    FakeOwnership,
    OwnerDirectory,
    ReasonCode,
    SafeError,
    ViewerScope,
)

R = ReasonCode
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
KEY = "tb:818HA:521.1:2026-08"
KEY_B = "tb:SECRET-B:999.9:2026-08"
REV, POL_VER, POL_DIG = f"{1:064x}", "pol-v1", f"{2:064x}"
DIGEST = "a" * 64
POISON = "Traceback secret://vault/key-7 SELECT * FROM tenants provider-said-no ForeignSourceName"
CORR = re.compile(r"[A-Za-z0-9._:-]{1,64}")
FAIL_N = {"closing_credit": Decimal("0.1"), "turnover_debit": Decimal("100.00")}
FAIL_G = {"closing_credit": Decimal("0.3"), "turnover_debit": Decimal("100.5")}


def h(n: int) -> str:
    return f"{n:064x}"


class Calls:
    """Call log of the composed E1-E3 functions (the facade must reach each decision through one of them)."""

    NAMES = ("build_cards", "verify_original", "request_override", "check_rerun", "commit_rerun", "build_timeline",
             "render_guard", "build_coverage_panel", "build_scoped_diff", "build_scoped_evidence",
             "render_guard_coverage", "decide_enqueue", "decide_rerun", "read_job", "read_result")

    def __init__(self, monkeypatch):
        self.log: list[str] = []
        for name in self.NAMES:
            real = getattr(ws, name)
            monkeypatch.setattr(ws, name, self._wrap(name, real))

    def _wrap(self, name, real):
        def spy(*a, **kw):
            self.log.append(name)
            return real(*a, **kw)
        return spy

    def take(self) -> list[str]:
        out, self.log = self.log, []
        return out


class Env:
    """Tenant t1, companies A and B, one fake clock shared by every store. Same script => same bytes."""

    def __init__(self, scopes_cls=FakeScopeEpochs):
        self.clk = FakeClock(T0 + timedelta(days=10))
        self.store = SnapshotStore(self.clk.now)
        self.ledger = RunLedger(self.store)
        self.review_log = ReviewLog(self.clk.now)
        self._ids = itertools.count(1)
        self.att = AttestationStore(self.clk.now, accountants={"t1": {"acc1"}},
                                    id_source=lambda: f"att-{next(self._ids)}")
        self.scopes = scopes_cls({("t1", "A"): 5, ("t1", "B"): 5})
        self.ownership, self.entitlements = FakeOwnership(), FakeEntitlements()
        self.capture, self.events = FakeCapturePolicy(), FakeEventSink()
        for company in ("A", "B"):
            self.entitlements.grant("t1", "alice", company)
        for ref in ("src1", "SRC-1", "SRC-2"):
            self.ownership.add("t1", "A", "source_id", ref)
        self.ownership.add("t1", "A", "comparison_key", KEY)
        self.dispatcher = FakeJobDispatcher()
        self.idem = IdempotencyStore(64, 3600)
        self.refusals = RefusalLog()
        self.corr = FakeCorrelationSource()
        self.ctx = ApiContext(
            csrf=CsrfGuard(fake_csrf_token), scopes=self.scopes, registry=default_registry(),
            refusals=self.refusals, idempotency=self.idem, dispatcher=self.dispatcher, clock=self.clk,
            correlation=self.corr, ownership=self.ownership, entitlements=self.entitlements,
            capture_policy=self.capture, events=self.events)
        self.owners = OwnerDirectory((("t1", "A", "src1", "owner-a"),))
        self.values: dict[str, tuple[dict, dict]] = {}
        self.reader_calls = 0
        self.reader_error: Exception | None = None
        self.bindings: list[RunBinding] = []
        self.keys_company = {KEY: "A"}
        self.policy = ApplicabilityPolicy(3600, REV, False)
        self.matrix = self.make_matrix("A")
        self.evidence_rows = self.make_evidence(("A",))
        self.raise_in: str | None = None
        self.viewer = ViewerScope("t1", "A", 5)
        self.session = SessionRecord("S1", "t1", "alice", T0 + timedelta(days=12), DIGEST)
        self.ws = WorkbenchSession(
            ledger=self.ledger, store=self.store, review_log=self.review_log, owners=self.owners,
            attestations=self.att, ctx=self.ctx, reader=self.reader, subjects=self._subjects,
            feeds=lambda: (), matrix=lambda: self._maybe_raise("matrix") or self.matrix,
            policy=lambda: self.policy, evidence=lambda: self.evidence_rows)

    # ---- providers
    def _maybe_raise(self, where):
        if self.raise_in == where:
            raise RuntimeError(POISON)

    def _subjects(self):
        self._maybe_raise("subjects")
        subs = []
        for key, company in self.keys_company.items():
            binds = tuple(self.bindings) if company == "A" else ()
            subs.append(TimelineSubject("t1", company, key, binds))
        return tuple(subs)

    def reader(self, tenant, snapshot_id):
        self.reader_calls += 1
        if self.reader_error is not None:
            raise self.reader_error
        s = self.store.get(tenant, snapshot_id)
        n, g = self.values[snapshot_id]
        return (SideRead("native", s.snapshot_id, s.digest, dict(n)),
                SideRead("gateway", s.snapshot_id, s.digest, dict(g)))

    # ---- fixtures
    @staticmethod
    def make_matrix(*companies):
        claims, ev, links = [], [], []
        for c in companies:
            scope = ClaimScope("t1", c)
            claims.append(Claim("cl-" + c, scope, "purchases", "validate"))
            ev.append(Evidence("ev-" + c, scope, "src-" + c, h(7), EvidenceVerdict.PASS))
            links.append(Link("cl-" + c, "ev-" + c))
        return build_matrix(tuple(claims), tuple(ev), tuple(links))

    @staticmethod
    def make_evidence(companies):
        claims, ev, links = [], [], []
        for c in companies:
            scope = ClaimScope("t1", c)
            claims.append(Claim("cl-" + c, scope, "purchases", "validate"))
            ev.append(Evidence("ev-" + c, scope, "src-" + c, h(7), EvidenceVerdict.PASS))
            links.append(Link("cl-" + c, "ev-" + c))
        return tuple(claims), tuple(ev), tuple(links)

    def snapshot(self, native, gateway):
        s = self.store.create("t1", {"values": {"native": native, "gateway": gateway}}, known_at=T0)
        self.ownership.add("t1", "A", "snapshot_id", s.snapshot_id)
        self.values[s.snapshot_id] = (native, gateway)
        return s

    def first_run(self, native=None, gateway=None, key=KEY):
        n = dict(FAIL_N if native is None else native)
        g = dict(FAIL_G if gateway is None else gateway)
        s = self.snapshot(n, g)
        pair = self.reader("t1", s.snapshot_id)
        company = self.keys_company.get(key, "A")
        self.ownership.add("t1", company, "comparison_key", key)
        run = self.ledger.run("t1", key, *pair, snapshot_id=s.snapshot_id)
        self.ownership.add("t1", company, "run_id", run.run_id)
        return s, run

    def attest(self, rev=REV):
        res = self.att.sign(AttestationRequest("t1", rev, POL_VER, POL_DIG, "prop", "req",
                                               AttestationDecision.PASS), Signer(SignerKind.HUMAN, "acc1"))
        assert res.signed
        return res.attestation.attestation_id

    def bind(self, run, att_id):
        self.bindings.append(RunBinding(run.run_id, att_id, REV, POL_VER, POL_DIG))

    def token(self, session=None):
        return fake_csrf_token(session or self.session)

    def rerun_request(self, prev, snapshot_id, key="idem-key-0001", epoch=5):
        return RerunRequest(ViewerScope("t1", "A", epoch), "alice", KEY, prev, snapshot_id, key)

    def own_runs(self, key=KEY):
        for v in self.ledger.list_runs("t1", key):
            self.ownership.add("t1", "A", "run_id", v.record.run_id)

    def rerun(self, prev, snapshot_id, key="idem-key-0001", token=None):
        out = self.ws.rerun(self.rerun_request(prev, snapshot_id, key), self.session,
                            self.token() if token is None else token)
        self.own_runs()  # the ownership service learns the runs a rerun created
        return out

    def job_request(self, operation="read_document", key="idem-key-1001", epoch=5, company="A"):
        return JobRequest(ViewerScope("t1", company, epoch), "alice", JobKind.RESCAN, operation,
                          (("source_id", "SRC-1"),), key)

    def statuses(self, key=KEY):
        self.own_runs(key)
        return [(v.record.run_id, v.status) for v in self.ledger.list_runs("t1", key)]

    def no_side_effects(self):
        assert self.dispatcher.calls == () and self.idem.record_count() == 0


@pytest.fixture
def env():
    return Env()


@pytest.fixture
def calls(monkeypatch):
    return Calls(monkeypatch)


def entry(view, ref):
    found = [e for e in view.entries if e.ref_id == ref]
    assert len(found) == 1
    return found[0]


# ============================================================ TC115 + TC116 + TC117 chain
def test_tc115_116_117_chain_over_one_ledger(env, calls):
    s1, run1 = env.first_run()
    cards_result = env.ws.cards(env.session, env.viewer, KEY, source_id="src1")
    assert calls.take() == ["build_cards"]
    assert type(cards_result) is CardsResult and cards_result.run_state == "FAIL"
    assert cards_result.run_id == run1.run_id
    cards = cards_result.cards
    assert [c.measure for c in cards] == list(run1.differences) and len(cards) == 2
    by = {c.measure: c for c in cards}
    assert by["closing_credit"].delta == Decimal("0.2") and by["turnover_debit"].delta == Decimal("0.50")
    assert all(c.owner_id == "owner-a" and c.run_status == "CURRENT" for c in cards)
    assert all(c.row_detail is R.ROW_DETAIL_UNAVAILABLE and c.fragment.snapshot_digest == s1.digest
               for c in cards)
    assert all(env.ws.verify_original(env.session, env.viewer, c) is R.ORIGINAL_INTACT for c in cards)
    assert calls.take() == ["verify_original"] * 2

    # annotate: notes, assignment, acknowledgement never touch the numbers
    for kind, text, kw in ((AnnotationKind.NOTE, "check 0.30 vs 0.10 please", {}),
                           (AnnotationKind.ASSIGNED, "", {"assignee": "owner-a"}),
                           (AnnotationKind.ACKNOWLEDGED, "", {})):
        assert not isinstance(env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, kind, text, **kw), SafeError)
    assert calls.take() == []  # annotations are the ReviewLog's own method, not a decision function
    assert env.ws.cards(env.session, env.viewer, KEY, source_id="src1") == cards_result
    calls.take()
    override = env.ws.override(run1.run_id, closing_credit=Decimal("0.3"))
    assert isinstance(override, SafeError) and override.reason_code is R.ORIGINAL_NUMBERS_IMMUTABLE
    assert calls.take() == ["request_override"]

    # new evidence -> rerun through the API (CSRF + idempotency) -> NEW run
    s2 = env.snapshot({"closing_credit": Decimal("0.3"), "turnover_debit": Decimal("100.5")},
                      {"closing_credit": Decimal("0.3"), "turnover_debit": Decimal("100.5")})
    decision = env.rerun(run1.run_id, s2.snapshot_id)
    assert calls.take() == ["decide_rerun", "check_rerun", "commit_rerun"]
    assert type(decision) is ApiDecision and decision.allowed and decision.http_class == 202
    assert decision.ticket.kind is JobKind.RERUN
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1
    states = env.statuses()
    assert [st for _, st in states] == ["SUPERSEDED", "CURRENT"]
    run2_id = states[1][0]
    assert env.ledger.get("t1", run2_id).supersedes == run1.run_id

    # old run: SUPERSEDED, numbers and digests unchanged, still verifiable
    old = env.ws.cards(env.session, env.viewer, KEY, source_id="src1", run_id=run1.run_id).cards
    assert all(c.run_status == "SUPERSEDED" for c in old)
    assert [(c.measure, c.native, c.gateway, c.original_digest) for c in old] == \
        [(c.measure, c.native, c.gateway, c.original_digest) for c in cards]
    assert all(env.ws.verify_original(env.session, env.viewer, c) is R.ORIGINAL_INTACT for c in cards)
    # the new run is PASS: no discrepancy cards, and the rerun is annotated on the old run
    passed = env.ws.cards(env.session, env.viewer, KEY, source_id="src1")
    assert (passed.run_state, passed.cards, passed.run_id) == ("PASS", (), run2_id)
    notes = env.ws.annotations(env.session, env.viewer, run1.run_id)
    assert notes[-1].kind is AnnotationKind.RERUN_REQUESTED and notes[-1].related_run_id == run2_id


def test_rerun_replay_creates_no_second_run_and_no_second_dispatch(env, calls):
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    first = env.rerun(run1.run_id, s2.snapshot_id)
    calls.take()
    again = env.rerun(run1.run_id, s2.snapshot_id)
    assert calls.take() == ["decide_rerun"]  # replay never reaches the rerun fence
    assert again.reason_code is R.REPLAYED and again.http_class == 200 and again.ticket == first.ticket
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1 and len(env.statuses()) == 2
    env.ownership.add("t1", "A", "snapshot_id", "other-snapshot")
    changed = env.rerun(run1.run_id, "other-snapshot")
    assert changed.reason_code is R.IDEMPOTENCY_CONFLICT and changed.http_class == 409
    assert len(env.dispatcher.calls) == 1 and len(env.statuses()) == 2


def test_rerun_fence_refusals_map_one_to_one_and_leave_no_trace(env, calls):
    s1, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))

    same = env.rerun(run1.run_id, s1.snapshot_id)  # not new evidence
    assert (same.reason_code, same.http_class) == (R.NO_NEW_EVIDENCE, 409)
    env.ownership.add("t1", "A", "run_id", "run-does-not-exist")  # owned but absent: a fence verdict
    env.ownership.add("t1", "A", "snapshot_id", "snap-does-not-exist")
    unknown = env.rerun("run-does-not-exist", s2.snapshot_id, key="idem-key-0002")
    assert (unknown.reason_code, unknown.http_class) == (R.RERUN_TARGET_UNKNOWN, 404)
    missing_snap = env.rerun(run1.run_id, "snap-does-not-exist", key="idem-key-0003")
    assert (missing_snap.reason_code, missing_snap.http_class) == (R.NOT_FOUND, 404)
    env.no_side_effects()
    assert len(env.statuses()) == 1 and not any(isinstance(d, SafeError) for d in (same, unknown))
    assert [d.next_action for d in (same, unknown)] and all(CORR.fullmatch(d.correlation_id)
                                                           for d in (same, unknown, missing_snap))

    ok = env.rerun(run1.run_id, s2.snapshot_id, key="idem-key-0004")
    assert ok.http_class == 202
    stale = env.rerun(run1.run_id, s2.snapshot_id, key="idem-key-0005")  # head already moved
    assert (stale.reason_code, stale.http_class) == (R.RERUN_TARGET_STALE, 409)
    assert len(env.dispatcher.calls) == 1 and env.idem.record_count() == 1 and len(env.statuses()) == 2


def test_after_a_rerun_the_next_rerun_must_target_the_new_head(env):
    _, run1 = env.first_run()
    s2 = env.snapshot({"closing_credit": Decimal(1)}, {"closing_credit": Decimal(1)})
    assert env.rerun(run1.run_id, s2.snapshot_id).http_class == 202
    head = env.statuses()[-1][0]
    s3 = env.snapshot({"closing_credit": Decimal(2)}, {"closing_credit": Decimal(2)})
    stale = env.rerun(run1.run_id, s3.snapshot_id, key="idem-key-0002")
    assert stale.reason_code is R.RERUN_TARGET_STALE
    nxt = env.rerun(head, s3.snapshot_id, key="idem-key-0003")
    assert nxt.http_class == 202 and len(env.statuses()) == 3


# ============================================================ TC118 + TC119 chain
def test_tc118_119_chain_history_revoke_and_clock(env, calls):
    _, run1 = env.first_run(FAIL_N, FAIL_N)  # PASS run, attested
    att1 = env.attest()
    env.bind(run1, att1)
    view = env.ws.timeline(env.session, env.viewer)
    assert type(view) is TimelineView and calls.take() == ["build_timeline", "render_guard"]
    assert is_green(entry(view, run1.run_id)) and entry(view, run1.run_id).applicability is Applicability.LIVE_CURRENT

    # new evidence -> new run through the API; old run becomes HISTORICAL_PASS, new one is not green yet
    s2 = env.snapshot({"closing_credit": Decimal(25)}, {"closing_credit": Decimal(25)})
    assert env.rerun(run1.run_id, s2.snapshot_id).http_class == 202
    run2 = env.statuses()[-1][0]
    view = env.ws.timeline(env.session, env.viewer)
    old, new = entry(view, run1.run_id), entry(view, run2)
    assert (old.applicability, old.reason) == (Applicability.HISTORICAL_PASS, ApplicabilityReason.SUPERSEDED_BY_RUN)
    assert old.label_text == "historical, not current" and not is_green(old)
    assert new.applicability is Applicability.UNATTESTED and not is_green(new)
    assert old.effective.label == "EFFECTIVE_UNKNOWN" and old.known.label == "KNOWN_AT"

    # attest the new run: live only now (attested + covered + fresh)
    att2 = env.attest()
    env.bind(env.ledger.get("t1", run2), att2)
    view = env.ws.timeline(env.session, env.viewer)
    assert is_green(entry(view, run2)) and not is_green(entry(view, run1.run_id))
    assert [e.ref_id for e in view.entries if is_green(e)] == [run2]

    # clock advance beyond the freshness window: history stays, green goes
    env.clk.advance(7200)
    stale = env.ws.timeline(env.session, env.viewer)
    assert (entry(stale, run2).applicability, entry(stale, run2).reason) == \
        (Applicability.HISTORICAL_PASS, ApplicabilityReason.STALE)
    assert not any(is_green(e) for e in stale.entries)

    # revoke the new attestation: REVOKED entry, history kept, applicability removed, no resurrection
    assert env.att.revoke(att2, "t1", Signer(SignerKind.HUMAN, "acc1")).revoked
    env.clk.advance(-3600)  # clock regression must not resurrect it
    after = env.ws.timeline(env.session, env.viewer)
    assert entry(after, run2).applicability is Applicability.REVOKED and not is_green(entry(after, run2))
    revoked_att = entry(after, att2)
    assert revoked_att.kind is EntryKind.ATTESTATION and revoked_att.applicability is Applicability.REVOKED
    assert entry(after, run1.run_id).applicability is Applicability.HISTORICAL_PASS  # history kept
    assert entry(after, att1).applicability is not Applicability.LIVE_CURRENT
    assert not any(is_green(e) for e in after.entries)
    assert len(after.entries) >= len(view.entries)  # nothing disappeared


def test_coverage_gap_makes_the_attested_run_not_green(env):
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    env.bind(run1, env.attest())
    assert is_green(entry(env.ws.timeline(env.session, env.viewer), run1.run_id))
    env.matrix = env.make_matrix("B")  # nothing covers company A any more
    view = env.ws.timeline(env.session, env.viewer)
    assert entry(view, run1.run_id).applicability is Applicability.NOT_COVERED
    panel = env.ws.coverage(env.session, env.viewer)
    assert panel.status.value == "INCOMPLETE" and not panel.complete


# ============================================================ TC120 two companies
def test_tc120_two_company_scope_no_leakage(env, calls):
    env.keys_company[KEY_B] = "B"
    _, run_a = env.first_run()
    env.first_run(key=KEY_B)
    env.bind(run_a, env.attest())
    env.matrix = env.make_matrix("A", "B")
    env.evidence_rows = env.make_evidence(("A", "B"))

    views = (env.ws.timeline(env.session, env.viewer), env.ws.diff(env.session, env.viewer), env.ws.coverage(env.session, env.viewer),
             env.ws.evidence(env.session, env.viewer))
    assert all(not isinstance(v, SafeError) and v.hidden_by_scope is True for v in views)
    for v in views:
        text = repr(v)
        assert KEY_B not in text and "cl-B" not in text and "ev-B" not in text and "src-B" not in text
    assert views[1].items and all(i.comparison_key == KEY for i in views[1].items)
    assert [i.evidence_id for i in views[3].items] == ["ev-A"]
    assert all(e.ref_id != "cl-B" for e in views[0].entries)
    names = calls.take()
    assert names == ["build_timeline", "render_guard", "build_scoped_diff", "render_guard_coverage",
                     "build_coverage_panel", "render_guard_coverage", "build_scoped_evidence",
                     "render_guard_coverage"]

    # B sees only its own; A's key never appears
    viewer_b = ViewerScope("t1", "B", 5)
    diff_b = env.ws.diff(env.session, viewer_b)
    assert {i.comparison_key for i in diff_b.items} == {KEY_B} and KEY not in repr(diff_b)
    assert KEY not in repr(env.ws.coverage(env.session, viewer_b)) and "ev-A" not in repr(env.ws.evidence(env.session, viewer_b))


def test_stale_scope_epoch_gives_safe_error_and_no_view_everywhere(env):
    env.first_run()
    env.scopes.bump("t1", "A")
    for result in (env.ws.timeline(env.session, env.viewer), env.ws.diff(env.session, env.viewer), env.ws.coverage(env.session, env.viewer),
                   env.ws.evidence(env.session, env.viewer), env.ws.cards(env.session, env.viewer, KEY, source_id="src1"),
                   env.ws.annotate(env.session, env.viewer, env.token(), "run-1", AnnotationKind.NOTE, "x"),
                   env.ws.annotations(env.session, env.viewer, "run-1")):
        assert type(result) is SafeError and result.reason_code is R.SCOPE_EPOCH_STALE
        assert CORR.fullmatch(result.correlation_id) and result.correlation_id != "CORR-UNASSIGNED"
    stale_rerun = env.rerun("run-1", "SN-2")
    assert stale_rerun.reason_code is R.SCOPE_EPOCH_STALE and stale_rerun.http_class == 403
    env.no_side_effects()


# ============================================================ TC121 + TC122 + TC123 via the facade
def test_tc122_csrf_and_idempotency_through_the_facade(env, calls):
    other = SessionRecord("S2", "t1", "alice", T0 + timedelta(days=12), DIGEST)
    expired = SessionRecord("S3", "t1", "alice", T0 + timedelta(days=1), DIGEST)
    cases = (
        (env.session, "", R.CSRF_REJECTED, 403), (env.session, "FAKE-bad", R.CSRF_REJECTED, 403),
        (env.session, fake_csrf_token(other), R.CSRF_REJECTED, 403),
        (expired, fake_csrf_token(expired), R.SESSION_INVALID, 401),
    )
    for session, token, code, http in cases:
        d = env.ws.enqueue(env.job_request(), session, token)
        assert (d.allowed, d.reason_code, d.http_class) == (False, code, http)
    assert calls.take() == ["decide_enqueue"] * len(cases)
    env.no_side_effects()

    ok = env.ws.enqueue(env.job_request(), env.session, env.token())
    assert (ok.allowed, ok.http_class) == (True, 202) and len(env.dispatcher.calls) == 1
    replay = env.ws.enqueue(env.job_request(), env.session, env.token())
    assert replay.reason_code is R.REPLAYED and len(env.dispatcher.calls) == 1
    other_params = JobRequest(ViewerScope("t1", "A", 5), "alice", JobKind.RESCAN, "read_document",
                              (("source_id", "SRC-2"),), "idem-key-1001")
    conflict = env.ws.enqueue(other_params, env.session, env.token())
    assert (conflict.reason_code, conflict.http_class) == (R.IDEMPOTENCY_CONFLICT, 409)
    missing = env.ws.enqueue(env.job_request(key=None), env.session, env.token())
    assert (missing.reason_code, missing.http_class) == (R.IDEMPOTENCY_KEY_REQUIRED, 400)
    stale = env.ws.enqueue(env.job_request(epoch=4), env.session, env.token())
    assert stale.reason_code is R.SCOPE_EPOCH_STALE
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1


def test_tc123_refusal_is_not_bypassed_by_respelling_through_the_facade(env):
    first = env.ws.enqueue(env.job_request("post_document"), env.session, env.token())
    assert (first.allowed, first.reason_code, first.http_class) == (False, R.OPERATION_DENIED, 403)
    for spelling in ("POST_DOCUMENT", " post_document ", "Post_Document"):
        d = env.ws.enqueue(env.job_request(spelling, key="idem-key-2002"), env.session, env.token())
        assert (d.allowed, d.reason_code) == (False, R.OPERATION_DENIED)
    for spelling in ("post\u200b_document", "unknown_operation_xyz", ""):
        d = env.ws.enqueue(env.job_request(spelling, key="idem-key-2003"), env.session, env.token())
        assert d.allowed is False and d.reason_code in (R.OPERATION_UNCLASSIFIED, R.OPERATION_DENIED)
    env.no_side_effects()
    assert ("t1", "A", "post_document", R.OPERATION_DENIED) in env.refusals.entries()


def test_tc121_every_refusal_is_a_safe_shape_with_a_correlation_id_and_no_poison(env):
    bad_inputs = (None, POISON, 5, object(), env.job_request(), RuntimeError(POISON))
    decisions = [env.ws.enqueue(x, y, z) for x in bad_inputs for y in (None, POISON) for z in (None, POISON)]
    decisions += [env.ws.rerun(x, None, POISON) for x in bad_inputs]
    decisions += [env.ws.read_job(x, None, POISON) for x in bad_inputs]
    for d in decisions:
        assert type(d) is ApiDecision and d.allowed is False and d.reason_code is not None
        assert CORR.fullmatch(d.correlation_id) and POISON not in repr(d)
        rendered = env.ws.render_error(d.safe_error())
        assert type(rendered) is RenderedError and POISON not in repr(rendered)
    env.no_side_effects()


def test_read_job_and_result_through_the_facade_are_scoped(env, calls):
    d = env.ws.enqueue(env.job_request(), env.session, env.token())
    job_id = d.ticket.job_id
    calls.take()
    got = env.ws.read_job(env.viewer, env.session, job_id)
    assert got.allowed and got.job.job_id == job_id and calls.take() == ["read_job"]
    pending = env.ws.read_result(env.viewer, env.session, job_id)  # own job, not finished: its fixed state
    assert (pending.allowed, pending.http_class, pending.job.state.value, pending.job.result_digest) ==         (True, 202, "QUEUED", None)
    env.dispatcher.complete(job_id, h(5))
    assert env.ws.read_result(env.viewer, env.session, job_id).job.result_digest == h(5)
    foreign = env.ws.read_job(ViewerScope("t1", "B", 5), env.session, job_id)
    missing = env.ws.read_job(ViewerScope("t1", "B", 5), env.session, "JOB-999999")
    assert foreign.reason_code is missing.reason_code is R.NOT_FOUND and foreign.http_class == 404


# ============================================================ composed-component failure
@pytest.mark.parametrize(("where", "failing", "unaffected"), [
    ("subjects", ("timeline", "diff"), ("coverage",)),
    ("matrix", ("timeline", "coverage"), ("diff",)),
])
def test_provider_failure_is_internal_refused_never_a_partial_view(env, where, failing, unaffected):
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    env.bind(run1, env.attest())
    assert is_green(entry(env.ws.timeline(env.session, env.viewer), run1.run_id))
    env.raise_in = where
    for name in failing:
        result = getattr(env.ws, name)(env.session, env.viewer)
        assert type(result) is SafeError, name
        assert result.reason_code is R.INTERNAL_REFUSED and CORR.fullmatch(result.correlation_id)
        assert POISON not in repr(result)
    for name in unaffected:  # a view that does not use the failing provider is unaffected
        assert type(getattr(env.ws, name)(env.session, env.viewer)) is not SafeError


def test_component_exception_in_the_ledger_is_internal_refused_and_never_green(env, monkeypatch):
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    env.bind(run1, env.attest())

    def boom(self, *a, **k):
        raise RuntimeError(POISON)

    monkeypatch.setattr(RunLedger, "list_runs", boom)
    for result in (env.ws.timeline(env.session, env.viewer), env.ws.diff(env.session, env.viewer)):
        assert type(result) is SafeError and result.reason_code is R.INTERNAL_REFUSED
        assert POISON not in repr(result)
        assert not isinstance(result, TimelineView)


def test_facade_converts_a_raising_component_function_into_internal_refused(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError(POISON)

    for name, call in (("build_timeline", lambda: env.ws.timeline(env.session, env.viewer)),
                       ("build_cards", lambda: env.ws.cards(env.session, env.viewer, KEY, source_id="src1")),
                       ("decide_rerun", lambda: env.rerun("run-1", "SN-2")),
                       ("decide_enqueue", lambda: env.ws.enqueue(env.job_request(), env.session, env.token())),
                       ("build_scoped_diff", lambda: env.ws.diff(env.session, env.viewer)),
                       ("read_job", lambda: env.ws.read_job(env.viewer, env.session, "JOB-000001"))):
        monkeypatch.setattr(ws, name, boom)
        result = call()
        assert type(result) is SafeError and result.reason_code is R.INTERNAL_REFUSED, name
        assert CORR.fullmatch(result.correlation_id) and result.correlation_id != "CORR-UNASSIGNED"
        assert POISON not in repr(result)


def test_reader_failure_during_rerun_is_internal_refused_with_no_run_and_no_record(env):
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    env.reader_error = RuntimeError(POISON)
    d = env.rerun(run1.run_id, s2.snapshot_id)
    assert (d.allowed, d.reason_code, d.http_class) == (False, R.DEPENDENCY_FAILED, 429)
    assert POISON not in repr(d)
    env.no_side_effects()
    assert len(env.statuses()) == 1 and env.statuses()[0][1] == "CURRENT"
    env.reader_error = None  # a retry with the same key is a clean first attempt, not a conflict
    assert env.rerun(run1.run_id, s2.snapshot_id).http_class == 202


def test_broken_correlation_source_degrades_to_the_fixed_default_id(env):
    class Broken:
        def next_id(self):
            raise RuntimeError(POISON)

    env.ctx = ApiContext(csrf=env.ctx.csrf, scopes=env.scopes, registry=env.ctx.registry,
                         refusals=env.refusals, idempotency=env.idem, dispatcher=env.dispatcher,
                         clock=env.clk, correlation=Broken(), ownership=env.ownership,
                         entitlements=env.entitlements, capture_policy=env.capture)
    facade = WorkbenchSession(
        ledger=env.ledger, store=env.store, review_log=env.review_log, owners=env.owners,
        attestations=env.att, ctx=env.ctx, reader=env.reader, subjects=env._subjects, feeds=lambda: (),
        matrix=lambda: env.matrix, policy=lambda: env.policy, evidence=lambda: env.evidence_rows)
    env.scopes.bump("t1", "A")
    result = facade.timeline(env.session, env.viewer)
    assert type(result) is SafeError and result.reason_code is R.SCOPE_EPOCH_STALE
    assert result.correlation_id == "CORR-UNASSIGNED" and POISON not in repr(result)


# ============================================================ no partial disclosure after a revoke
class EpochBumpAfter(FakeScopeEpochs):
    """After ``arm(n)``, the n-th later epoch read bumps the epoch (a revoke between build and disclosure)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.left: int | None = None

    def arm(self, reads):
        self.left = reads

    def current_epoch(self, tenant_id, company_id):
        value = super().current_epoch(tenant_id, company_id)
        if self.left is not None:
            self.left -= 1
            if self.left == 0:
                self.bump(tenant_id, company_id)
        return value


@pytest.mark.parametrize("reads", [1, 2])
def test_revoke_during_the_timeline_flow_never_discloses_a_view(reads):
    env = Env(EpochBumpAfter)
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    env.bind(run1, env.attest())
    env.scopes.arm(reads)  # timeline reads the epoch 3 times: build check, pre-disclosure re-check, render_guard
    result = env.ws.timeline(env.session, env.viewer)
    assert type(result) is SafeError and result.reason_code is R.SCOPE_EPOCH_STALE
    assert not isinstance(result, TimelineView)
    assert type(env.ws.timeline(env.session, env.viewer)) is SafeError  # the old viewer scope stays refused
    assert type(env.ws.diff(env.session, env.viewer)) is SafeError


def test_revoke_after_the_last_check_is_refused_on_the_next_read():
    env = Env(EpochBumpAfter)
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    env.bind(run1, env.attest())
    env.scopes.arm(3)  # lands after render_guard's read: that view was verified fresh when disclosed
    assert type(env.ws.timeline(env.session, env.viewer)) is TimelineView
    assert env.ws.timeline(env.session, env.viewer).reason_code is R.SCOPE_EPOCH_STALE


def test_attestation_revoked_between_two_reads_is_visible_in_the_second_view(env):
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    att = env.attest()
    env.bind(run1, att)
    first = env.ws.timeline(env.session, env.viewer)
    assert is_green(entry(first, run1.run_id))
    assert env.att.revoke(att, "t1", Signer(SignerKind.HUMAN, "acc1")).revoked
    second = env.ws.timeline(env.session, env.viewer)
    assert not any(is_green(e) for e in second.entries)
    assert entry(second, run1.run_id).applicability is Applicability.REVOKED


# ============================================================ determinism
def _script(env: Env):
    _, run1 = env.first_run()
    env.bind(run1, env.attest())
    out = [repr(env.ws.cards(env.session, env.viewer, KEY, source_id="src1")), repr(env.ws.timeline(env.session, env.viewer))]
    s2 = env.snapshot({"closing_credit": Decimal(7)}, {"closing_credit": Decimal(7)})
    out.append(repr(env.rerun(run1.run_id, s2.snapshot_id)))
    out.append(repr(env.ws.timeline(env.session, env.viewer)))
    out.append(repr(env.ws.diff(env.session, env.viewer)))
    out.append(repr(env.ws.coverage(env.session, env.viewer)))
    out.append(repr(env.ws.evidence(env.session, env.viewer)))
    return out, env.ws.timeline(env.session, env.viewer).digest


def test_same_inputs_and_injected_clock_and_ids_give_byte_identical_views():
    a, digest_a = _script(Env())
    b, digest_b = _script(Env())
    assert a == b and digest_a == digest_b
    assert re.fullmatch(r"[0-9a-f]{64}", digest_a)
    c = Env()
    c.clk.advance(1)  # a different injected clock must change the digest
    assert _script(c)[1] != digest_a


# ============================================================ concurrency
def _race(env, first, second):
    barrier = threading.Barrier(2)
    out: list[ApiDecision] = []
    lock = threading.Lock()

    def work(req):
        barrier.wait()
        d = env.ws.rerun(req, env.session, env.token())
        with lock:
            out.append(d)

    threads = [threading.Thread(target=work, args=(r,)) for r in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_two_parallel_reruns_of_one_head_with_different_keys_make_exactly_one_new_run(env):
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    out = _race(env, env.rerun_request(run1.run_id, s2.snapshot_id, "idem-key-0001"),
                env.rerun_request(run1.run_id, s2.snapshot_id, "idem-key-0002"))
    assert sorted(d.http_class for d in out) == [202, 409]
    loser = next(d for d in out if not d.allowed)
    assert loser.reason_code is R.RERUN_TARGET_STALE
    assert len(env.statuses()) == 2 and len(env.dispatcher.calls) == 1 and env.reader_calls == 2
    assert env.idem.record_count() == 1


def test_two_parallel_identical_reruns_make_exactly_one_new_run_and_one_replay(env):
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    req = env.rerun_request(run1.run_id, s2.snapshot_id, "idem-key-0001")
    out = _race(env, req, req)
    assert sorted(d.http_class for d in out) == [200, 202]
    assert next(d for d in out if d.allowed and d.http_class == 200).reason_code is R.REPLAYED
    assert len(env.statuses()) == 2 and len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1


# ============================================================ facade adds no rule of its own
def test_facade_exposes_only_pass_through_methods_over_typed_ids():
    public = {n for n in dir(WorkbenchSession) if not n.startswith("_")}
    assert public == {"cards", "verify_original", "annotate", "annotations", "override", "rerun",
                      "enqueue", "read_job", "read_result", "render_error", "timeline", "coverage",
                      "diff", "evidence"}
    forbidden = {"command", "query", "sql", "raw", "channel", "verdict", "state", "status", "numbers"}
    tree = ast.parse(Path(ws.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("__"):
            args = node.args
            names = {a.arg for a in (*args.args, *args.kwonlyargs, *args.posonlyargs)}
            assert not names & forbidden, node.name


def test_module_imports_only_stdlib_and_phase2_siblings():
    tree = ast.parse(Path(ws.__file__).read_text(encoding="utf-8"))
    banned = {"os", "pathlib", "socket", "subprocess", "httpx", "requests", "sqlite3", "asyncio"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & banned
        if isinstance(node, ast.ImportFrom):
            assert node.level == 1 or (node.module or "") in {"__future__", "collections", "collections.abc",
                                                              "datetime", "typing"}
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "eval", "exec"}
    assert ws.AUTHORITY == "EVALUATION_ONLY"
    assert repr(Env().ws) == "WorkbenchSession()"


def test_cards_are_derived_values_the_facade_cannot_edit(env):
    env.first_run()
    result = env.ws.cards(env.session, env.viewer, KEY, source_id="src1")
    assert type(result) is CardsResult and result.run_state == "FAIL"
    cards = result.cards
    assert all(type(c) is DiscrepancyCard and c.authority == "EVALUATION_ONLY" for c in cards)
    with pytest.raises(AttributeError):
        cards[0].native = Decimal(1)  # type: ignore[misc]
