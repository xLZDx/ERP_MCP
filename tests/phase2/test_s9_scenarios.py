"""S9 E5 end-to-end offline scenarios (R2-US-043..046, TC127..138) over the REAL S9 modules with fakes only.

One chain per tenant, run stage by stage:

  capacity report (E1) -> interference verdict + budget plan (E1) -> audit-gated effect with a sink outage and
  recovery (E2) -> delivery storm with 429 / network faults and two workers (E2) -> alert fired on delivery lag
  and recovered (E2) -> expand rehearsal + shadow compare + rollback decisions with a revoked grant (E3) ->
  restore manifest + simulated defects (E4) -> export with masking / formula safety (E4) -> hold, retention and
  a deletion PLAN that is never executed (E4) -> G6-pre readiness checklist (E5).

The chain below contains NO decision rule of its own: every verdict is produced by exactly one S9 module
function, and the tests recompute it by calling that function directly. Every number here is a scripted
fixture value (``SCRIPTED_OFFLINE_FIXTURE``); nothing proves capacity, restore, alert delivery or a gate.
"""
import copy
import dataclasses
import hashlib
import json
import re
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest

from business_ai_gateway.phase2.alert_rules import (
    AlertDeliveryOutcome,
    AlertEngine,
    AlertRule,
    AlertState,
    EventType,
    FakeAlertSink,
    RuleKind,
)
from business_ai_gateway.phase2.audit_gate import (
    AuditGate,
    AuditPhase,
    FakeAuditSink,
    GateOutcome,
    GateStatus,
    SinkMode,
)
from business_ai_gateway.phase2.backend_budget import PhysicalBackendBudget
from business_ai_gateway.phase2.capacity_interference import (
    DemandItem,
    WorkClass,
    interference,
    make_policy,
    plan_budget,
)
from business_ai_gateway.phase2.capacity_model import (
    ActiveClientCount,
    BackendCount,
    CacheState,
    CapacityReport,
    CapacityStore,
    ConfiguredLimit,
    DiscoveryState,
    GridCell,
    LimitLayer,
    OutcomeClass,
    ReportPolicy,
    RequestSample,
    SessionCount,
    SourceCount,
    WorkloadClass,
    build_report,
    make_cell,
    percentile,
    read_report,
)
from business_ai_gateway.phase2.delivery_replay import (
    DeliveryEvent,
    DeliveryOutcome,
    DeliveryStatus,
    FakeDeliverySink,
    RecordStatus,
    RegisterOutcome,
    ReplayPlanner,
    SinkKind,
)
from business_ai_gateway.phase2.evidence_attestation import (
    AttestationDecision,
    AttestationRequest,
    AttestationStore,
    Signer,
    SignerKind,
)
from business_ai_gateway.phase2.export_safety import (
    ExportColumnPolicy,
    ExportPolicy,
    ExportRequest,
    ExportResult,
    build_export,
)
from business_ai_gateway.phase2.g6_pre_readiness import (
    OperatorEvidenceRef,
    ReadinessReport,
    SlotKind,
    SlotStatus,
    build_readiness,
)
from business_ai_gateway.phase2.ops_types import (
    Basis,
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOperatorAuthority,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
)
from business_ai_gateway.phase2.release_migration import (
    MigrationStep,
    MigrationUnit,
    ObjectClass,
    Phase,
    RehearsalPlan,
    SchemaName,
    ShadowObservation,
    ShadowResult,
    StepKind,
    classify_step,
    compare_shadow,
    plan_rehearsal,
)
from business_ai_gateway.phase2.release_rollback import (
    ACTION_ROLLBACK,
    BlockCause,
    FakeGrantRegistry,
    GrantId,
    GrantRecord,
    ReleaseState,
    RollbackDecision,
    RollbackPlan,
    SwitchSnapshot,
    decide_rollback,
)
from business_ai_gateway.phase2.restore_verify import (
    LIVING_TABLES,
    CheckName,
    RestoreManifest,
    RestoreReport,
    build_manifest,
    verify_restore,
)
from business_ai_gateway.phase2.retention_hold import (
    ACTION_APPROVE_DELETION,
    ACTION_RELEASE_HOLD,
    ACTION_SET_POLICY,
    ApprovalRequest,
    DeletionDecision,
    DeletionRequest,
    Hold,
    HoldLevel,
    HoldReason,
    HoldReleaseReceipt,
    ReleaseRequest,
    RetentionLedger,
    RetentionPolicy,
    decide_deletion,
)
from business_ai_gateway.phase2.side_effect_boundary import default_registry

TA, TB = "q7alpha", "q7beta"  # unique tenant markers: every id of a tenant carries its marker
T_BASE = datetime(2026, 6, 1, tzinfo=UTC)
ATT_NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)  # the attestation store keeps its own fixed clock
HEAD = "abcdef1234567"
DAY = 86_400
P1, D2 = "c" * 64, "b" * 64


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ======================================================================================== fakes and world

class StepClock:
    """Injected clock: reads never advance it; ``advance``/``to`` only move it FORWARD (monotone)."""

    def __init__(self, start):
        self._t = start

    def now(self):
        return self._t

    def __call__(self):
        return self._t

    def advance(self, seconds):
        self._t += timedelta(seconds=seconds)

    def to(self, moment):
        self._t = max(self._t, moment)


class Tenant:
    """All identifiers of one tenant. ``foreign_tag`` names the OTHER tenant whose ids are fed in as hostile input."""

    def __init__(self, tag, foreign_tag):
        self.tag, self.foreign_tag = tag, foreign_tag
        self.tenant, self.company, self.actor = f"tenant-{tag}", f"company-{tag}", f"actor-{tag}"
        self.approver, self.operator = f"approver-{tag}", f"operator-{tag}"
        self.scope = OpsScope(self.tenant, self.company, self.actor)
        self.approver_scope = OpsScope(self.tenant, self.company, self.approver)
        self.source, self.conn, self.export_id = f"SRC-{tag}-1", f"CN-{tag}-1", f"EXP-{tag}-1"
        self.runs = (f"RUN-{tag}-1", f"RUN-{tag}-2")
        self.req1, self.req2 = f"REQ-{tag}-1", f"REQ-{tag}-2"
        self.workers = (f"worker-{tag}-1", f"worker-{tag}-2")
        self.foreign_tenant, self.foreign_company = f"tenant-{foreign_tag}", f"company-{foreign_tag}"
        self.foreign_source = f"SRC-{foreign_tag}-1"


class World:
    """One shared set of S9 components (shared on purpose: tenant isolation must come from the modules)."""

    def __init__(self, *tenants):
        self.tenants = tenants
        self.clock = StepClock(T_BASE)
        self.log = []                     # every entitlement / ownership port call, in order
        self.broken = set()               # port names that raise
        self.owner, self.ent = FakeOwnership(), FakeEntitlements()
        self.authority = FakeOperatorAuthority()
        self.ids = FakeCorrelationSource()
        self.audit_log, self.alert_log, self.hold_audits = [], [], []
        self.hold_audit_answer = True
        for t in tenants:
            self.ent.grant(t.tenant, t.actor, t.company)
            self.ent.grant(t.tenant, t.approver, t.company)
            for kind, ref in (("source_id", t.source), ("report_id", t.export_id),
                              ("run_id", t.runs[0]), ("run_id", t.runs[1])):
                self.owner.add(t.tenant, t.company, kind, ref)
            self.authority.allow(t.operator, ACTION_ROLLBACK)
            self.authority.allow(t.actor, ACTION_SET_POLICY)
            self.authority.allow(t.approver, ACTION_APPROVE_DELETION)
            self.authority.allow(t.approver, ACTION_RELEASE_HOLD)
        self.store = CapacityStore(10, FakeCorrelationSource("RPT"), self._register_owner, self.ids)
        self.audit_sinks = {t.tenant: FakeAuditSink(self.clock, log=self.audit_log, name=f"audit-{t.tag}")
                            for t in tenants}
        self.alert_sinks = {t.tenant: FakeAlertSink(log=self.alert_log) for t in tenants}
        self.gate = AuditGate(default_registry(), dict(self.audit_sinks), self, self, self.ids, self.clock)
        self.delivery_sink = FakeDeliverySink()
        self.planner = ReplayPlanner(self, self, self.ids, self.clock, max_attempts=8, base_delay=1,
                                     max_delay=300, lease_seconds=60,
                                     sinks={t.tenant: self.delivery_sink for t in tenants})
        self.alerts = AlertEngine(self, self, self.ids, self.clock,
                                  sinks={t.tenant: self.alert_sinks[t.tenant] for t in tenants})
        self.ledger = RetentionLedger(self.ids, self, self, self.authority, self.clock, self._hold_audit, 100)

    def _register_owner(self, tenant_id, company_id, kind, ref):
        self.owner.add(tenant_id, company_id, kind, ref)  # the fake returns None; the store needs exactly True
        return True

    # --- ports (the S9 modules call these structurally; every call is logged) ------------------------
    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id, actor_id))
        if "entitlement" in self.broken:
            raise RuntimeError("POISON-ENTITLEMENT-DOWN")
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, kind, ref))
        if "ownership" in self.broken:
            raise RuntimeError("POISON-OWNERSHIP-DOWN")
        return self.owner.owns(tenant_id, company_id, kind, ref)

    def _hold_audit(self, record):
        self.hold_audits.append(record)
        if isinstance(self.hold_audit_answer, Exception):
            raise self.hold_audit_answer
        return self.hold_audit_answer

    def segment(self, fn):
        """The port calls made by ``fn()`` only, plus its result."""
        start = len(self.log)
        result = fn()
        return self.log[start:], result


# ======================================================================================== the chain

def scripted_samples(scale):
    ok = [RequestSample(OutcomeClass.BUSINESS_OK, scale * (i + 1)) for i in range(100)]
    return ok + [RequestSample(OutcomeClass.PROFILE_REFUSED, 50) for _ in range(10)]


def step(kind, object_class, phase=Phase.EXPAND):
    return MigrationStep(phase, kind, SchemaName.LIVING, object_class)


ADDITIVE_STEPS = (step(StepKind.CREATE_TABLE, ObjectClass.TABLE), step(StepKind.CREATE_INDEX, ObjectClass.INDEX))
SWITCH_STEPS = (step(StepKind.ROUTE_SWITCH, ObjectClass.ROUTE, Phase.SWITCH),
               step(StepKind.FEATURE_FLAG, ObjectClass.FEATURE_FLAG, Phase.SWITCH))
DESTRUCTIVE_STEP = step(StepKind.DROP_TABLE, ObjectClass.TABLE)
OWNED_DEFECT_NAMES = ("COUNT", "DIGEST", "FK", "SEQUENCE", "HEAD", "ATTESTATION", "SCOPE", "INCOMPLETE")


def restore_rows(t, att_id):
    base = {"tenant_id": t.tenant, "source_id": t.source}
    o1, o2, r1, r2 = UUID(int=21), UUID(int=22), UUID(int=11), UUID(int=12)
    return {
        "tenants": [{"tenant_id": t.tenant}],
        "sources": [{**base, "company_id": t.company, "scope_epoch": 0, "status": "ACTIVE"}],
        "observations": [
            {**base, "observation_id": o1, "object_id": f"obj-{t.tag}", "revision_id": r1, "kind": "OBSERVED",
             "digest": "a" * 64, "supersedes": None, "provenance": {"k": ["v", 1, None]}},
            {**base, "observation_id": o2, "object_id": f"obj-{t.tag}", "revision_id": r2, "kind": "OBSERVED",
             "digest": D2, "supersedes": o1, "provenance": {}}],
        "accepted_heads": [{**base, "model_key": "m1", "revision_id": r2, "version": 2},
                           {**base, "model_key": "m2", "revision_id": None, "version": 0}],
        "acceptance_events": [
            {**base, "acceptance_id": UUID(int=31), "model_key": "m1", "from_version": 0, "to_version": 1,
             "accepted_revision": r1},
            {**base, "acceptance_id": UUID(int=32), "model_key": "m1", "from_version": 1, "to_version": 2,
             "accepted_revision": r2}],
        "jobs": [{**base, "job_id": UUID(int=41), "state": "PENDING", "fence": 0}],
        "cursors": [{**base, "connection_id": "cn1", "cursor_value": "x", "version": 0}],
        "outbox": [{**base, "connection_id": "cn1", "event_id": f"e{i}", "seq": i, "status": "PENDING"}
                   for i in (1, 2, 3)],
        "role_scope": [{"role_name": "living_worker", **base, "company_id": None}],
        "trusted_reviewers": [{"role_name": "living_promoter", **base, "active": True,
                               "expires_at": ATT_NOW + timedelta(days=30)}],
        "attestations": [{**base, "attestation_id": att_id, "revision_id": r2, "policy_version": "v1",
                          "policy_digest": P1, "expires_at": ATT_NOW + timedelta(days=30), "revoked_at": None}],
    }


def _pop_job(rows):
    rows["jobs"].pop()


def _flip_cursor(rows):
    rows["cursors"][0]["cursor_value"] = "y"


def _orphan_supersedes(rows):
    rows["observations"][1]["supersedes"] = UUID(int=99)


def _outbox_hole(rows):
    rows["outbox"].pop(1)


def _head_version(rows):
    rows["accepted_heads"][0]["version"] = 3


def _attestation_policy(rows):
    rows["attestations"][0]["policy_digest"] = "d" * 64


def _make_foreign_row(foreign_tenant):
    def mutate(rows):
        rows["jobs"][0]["tenant_id"] = foreign_tenant
    return mutate


def _drop_outbox_table(rows):
    rows.pop("outbox")


class Chain:
    """The cross-story chain of ONE tenant. Stages are generators that yield between steps so that two tenants can
    be interleaved. ``out`` keeps every raw output (scanned for cross-tenant text); ``facts`` keeps plain counts."""

    def __init__(self, world, tenant):
        self.w, self.t = world, tenant
        self.out, self.facts, self.effect_calls, self.lags = {}, {}, [], []

    def keep(self, name, value):
        self.out[name] = value
        return value

    def run(self):
        for stage in (self.capacity, self.audit, self.delivery, self.alert, self.release, self.restore,
                      self.export, self.retention, self.readiness):
            yield from stage()

    # ---- E1: grid cell report -> interference verdict -> budget plan ---------------------------------
    def capacity(self):
        w, t = self.w, self.t
        cell = self.keep("cell", make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000),
                                           BackendCount(1), CacheState.WARM, DiscoveryState.OFF,
                                           WorkloadClass.METADATA, w.ids))
        policy = ReportPolicy(window_us=10_000_000)
        base = self.keep("report_base", build_report(t.scope, w, w, w.store, cell, scripted_samples(1000),
                                                     policy, w.clock))
        yield
        loaded = self.keep("report_loaded", build_report(t.scope, w, w, w.store, cell, scripted_samples(1100),
                                                         policy, w.clock))
        if not (isinstance(base, CapacityReport) and isinstance(loaded, CapacityReport)):
            return
        yield
        self.keep("interference", interference(base.business[1], loaded.business[1]))
        bpolicy = make_policy(min_background_slots=1, tenant_share_slots=4, ids=w.ids)
        demand = [DemandItem(t.tenant, "DB-1", t.source, WorkClass.INTERACTIVE, 3),
                  DemandItem(t.tenant, "DB-1", t.source, WorkClass.BACKGROUND, 2)]
        self.keep("budget_plan", plan_budget(bpolicy, demand,
                                             PhysicalBackendBudget(per_backend_limit=4, total_limit=8), w.ids))
        self.keep("report_read", read_report(t.scope, base.report_id, w, w, w.store))
        yield

    # ---- E2: audit-gated effect, sink outage, recovery, completion outage + retry ----------------------
    def audit(self):
        w, t = self.w, self.t
        sink = w.audit_sinks[t.tenant]
        refs = (("source_id", t.source),)

        def effect(label):
            return lambda: self.effect_calls.append(label)

        sink.set_mode(SinkMode.DOWN)
        self.keep("audit_down", w.gate.guarded_effect(t.scope, t.req1, "create_document", effect("down"), refs))
        yield
        sink.set_mode(SinkMode.HEALTHY)
        self.keep("audit_ok", w.gate.guarded_effect(t.scope, t.req1, "create_document", effect("req1"), refs))
        yield
        sink.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)
        self.keep("audit_pending", w.gate.guarded_effect(t.scope, t.req2, "create_document", effect("req2"), refs))
        self.keep("unaudited_pending", w.gate.unaudited(t.scope))
        yield
        sink.set_phase_mode(AuditPhase.COMPLETION, None)
        self.keep("audit_retry", w.gate.retry_completion(t.scope, t.req2))
        self.keep("unaudited_after", w.gate.unaudited(t.scope))
        self.keep("audit_records", tuple(sink.records))
        yield

    # ---- E2: delivery storm with two workers ------------------------------------------------------------
    def sink_calls(self):
        return sum(1 for c in self.w.delivery_sink.calls if c[0] == self.t.tenant)

    def lag(self):
        recs = self.w.planner.records(self.t.scope, self.t.source, self.t.conn)
        return sum(1 for r in recs if r.status is not RecordStatus.DELIVERED)

    def delivery(self):
        w, t = self.w, self.t
        p, sink = w.planner, w.delivery_sink
        events = [DeliveryEvent(t.conn, i, f"EV-{t.tag}-{i:02d}", sha(f"EV-{t.tag}-{i:02d}")) for i in range(1, 13)]
        reg = self.keep("register", p.register(t.scope, t.source, events))
        self.keep("register_replay", p.register(t.scope, t.source, events))
        clash = DeliveryEvent(t.conn, 1, events[0].event_id, sha("another payload"))
        self.keep("register_conflict", p.register(t.scope, t.source, [clash]))
        if not isinstance(reg, RegisterOutcome):
            return
        self.lags.append(self.lag())
        sink.script(t.tenant, [SinkKind.RATE_LIMITED, SinkKind.NETWORK_FAILURE, "RAISE", "LOST_ACK",
                               SinkKind.RATE_LIMITED], retry_after=5)
        yield
        c1 = self.keep("claim_w1", p.claim(t.scope, t.workers[0], t.source, t.conn))
        self.keep("claim_contended", p.claim(t.scope, t.workers[1], t.source, t.conn))
        self.keep("held_outcome", p.deliver_pending(t.scope, t.workers[1], t.source, t.conn))
        self.facts["calls_while_held"] = self.sink_calls()
        yield
        w.clock.advance(61)  # the lease of worker 1 runs out
        c2 = self.keep("claim_w2", p.claim(t.scope, t.workers[1], t.source, t.conn))
        self.keep("stale_outcome", p.deliver_pending(t.scope, t.workers[0], t.source, t.conn, claim=c1))
        self.facts["calls_after_stale"] = self.sink_calls()
        yield
        outcomes = []
        for i in range(60):
            worker = t.workers[1] if i % 2 == 0 else t.workers[0]
            out = p.deliver_pending(t.scope, worker, t.source, t.conn, claim=c2 if i == 0 else None)
            outcomes.append(out)
            if not isinstance(out, DeliveryOutcome) or out.status is DeliveryStatus.COMPLETE:
                break
            if out.next_retry_at is not None:
                w.clock.to(out.next_retry_at)
            yield
        self.keep("delivery_outcomes", tuple(outcomes))
        self.keep("cursor", p.cursor(t.scope, t.source, t.conn))
        self.keep("quarantine", p.quarantine_count(t.scope))
        self.lags.append(self.lag())
        yield

    def published(self):
        return [e for e in self.w.delivery_sink.published if e[0] == self.t.tenant]

    # ---- E2: alert on delivery lag, fired once, recovered once -------------------------------------------
    def alert(self):
        w, t = self.w, self.t
        if len(self.lags) < 2:
            return
        high, low = self.lags[0], self.lags[-1]
        sink = w.alert_sinks[t.tenant]
        rule = AlertRule(RuleKind.OUTBOX_LAG, 5, 30, 0, 10)
        self.keep("alert_rule_result", w.alerts.set_rule(t.scope, t.source, rule))
        self.keep("alert_obs_1", w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, high))
        self.keep("alert_pending", w.alerts.status(t.scope, t.source, RuleKind.OUTBOX_LAG))
        yield
        w.clock.advance(30)
        self.keep("alert_obs_2", w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, high))
        self.keep("alert_firing", w.alerts.status(t.scope, t.source, RuleKind.OUTBOX_LAG))
        sink.fail_next(1)
        self.keep("alert_deliver_failed", w.alerts.deliver_events(t.scope))
        self.keep("alert_deliver_fired", w.alerts.deliver_events(t.scope))
        yield
        self.keep("alert_obs_3", w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, low))
        self.keep("alert_recovering", w.alerts.status(t.scope, t.source, RuleKind.OUTBOX_LAG))
        w.clock.advance(10)
        self.keep("alert_obs_4", w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, low))
        self.keep("alert_ok", w.alerts.status(t.scope, t.source, RuleKind.OUTBOX_LAG))
        self.keep("alert_deliver_recovered", w.alerts.deliver_events(t.scope))
        self.keep("alert_deliver_again", w.alerts.deliver_events(t.scope))
        self.keep("alert_obs_5", w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, low))
        self.keep("alert_events", w.alerts.events(t.scope))
        self.keep("alert_sent", tuple(sink.sent))
        yield

    # ---- E3: expand rehearsal, shadow compare, rollback with a revoked grant -------------------------------
    def release(self):
        w, t = self.w, self.t
        unit1 = MigrationUnit("001", (), ADDITIVE_STEPS)
        unit2 = MigrationUnit("002", ("001",), ADDITIVE_STEPS)
        unit3 = MigrationUnit("003", ("002",), (ADDITIVE_STEPS[0], DESTRUCTIVE_STEP))
        self.keep("rehearsal", plan_rehearsal([unit1, unit2], ("001",), w.ids))
        self.keep("rehearsal_destructive", plan_rehearsal([unit2, unit3], ("001",), w.ids))
        ops = [f"OP-{t.tag}-{i}" for i in (1, 2, 3)]
        observed = [ShadowObservation(op, sha(op), sha(op), sha(op)) for op in ops]
        self.keep("shadow", compare_shadow(ops, observed, w.ids))
        yield
        grants = FakeGrantRegistry()  # platform-level API: isolation between tenants is by registry INSTANCE
        g1, g2 = GrantId(f"GR-{t.tag}-1"), GrantId(f"GR-{t.tag}-2")
        expires = datetime(2030, 1, 1, tzinfo=UTC)
        assert grants.issue(GrantRecord(g1, expires)) and grants.issue(GrantRecord(g2, expires))
        snapshot = SwitchSnapshot((g1, g2))
        state = ReleaseState(f"REL-{t.tag}", T_BASE, 3600, 5)
        good = RollbackPlan(f"2026-05-{t.tag}", 5, SWITCH_STEPS)
        bad = RollbackPlan(f"2026-05-{t.tag}", 5, (SWITCH_STEPS[0], DESTRUCTIVE_STEP))
        additive = RollbackPlan(f"2026-05-{t.tag}", 5, ADDITIVE_STEPS)

        def decide(plan, actor=t.operator, clock=w.clock):
            return decide_rollback(actor, plan, state, grants=grants, attestations=object(),
                                   authority=w.authority, clock=clock, ids=w.ids, switch_snapshot=snapshot)

        self.keep("rollback_destructive", decide(bad))
        self.keep("rollback_additive", decide(additive))
        self.keep("rollback_before_revoke", decide(good))
        yield
        self.facts["revoked"] = grants.revoke(g1)
        self.keep("rollback_after_revoke", decide(good))
        self.facts["reissue_g1"] = grants.issue(GrantRecord(g1, expires))
        self.keep("rollback_regressed_clock", decide(good, clock=lambda: T_BASE - timedelta(days=1)))
        self.keep("rollback_unauthorized", decide(good, actor=f"nobody-{t.tag}"))
        self.facts["grant_ids"] = (g1, g2)
        yield

    # ---- E4: manifest of a populated registry, simulated restore defects ---------------------------------------
    def restore(self):
        w, t = self.w, self.t
        att_id = f"att-{t.tag}-1"
        store = AttestationStore(lambda: ATT_NOW, accountants={t.tenant: {"acct"}},
                                 id_source=iter([att_id]).__next__)
        signed = store.sign(AttestationRequest(t.tenant, D2, "v1", P1, "prop", "req", AttestationDecision.PASS),
                            Signer(SignerKind.HUMAN, "acct"))
        att_id = signed.attestation.attestation_id
        rows = restore_rows(t, att_id)
        sources = (t.source,)
        source = self.keep("manifest", build_manifest(t.scope, sources, rows, w, w, w.ids))
        if not isinstance(source, RestoreManifest):
            return
        restored = build_manifest(t.scope, sources, copy.deepcopy(rows), w, w, w.ids)
        self.keep("restore_ok", verify_restore(t.scope, sources, source, restored, w, w, w.ids, store, w.clock))
        yield
        defects = (("COUNT", _pop_job), ("DIGEST", _flip_cursor), ("FK", _orphan_supersedes),
                   ("SEQUENCE", _outbox_hole), ("HEAD", _head_version), ("ATTESTATION", _attestation_policy),
                   ("SCOPE", _make_foreign_row(t.foreign_tenant)), ("INCOMPLETE", _drop_outbox_table))
        for name, mutate in defects:
            broken = copy.deepcopy(rows)
            mutate(broken)
            manifest = build_manifest(t.scope, sources, broken, w, w, w.ids)
            self.keep(f"restore_{name}", verify_restore(t.scope, sources, source, manifest, w, w, w.ids,
                                                        store, w.clock))
            yield

    # ---- E4: export with masking, hashing, formula safety, foreign rows in the input ------------------------------
    def export(self):
        w, t = self.w, self.t
        policy = ExportPolicy.from_mapping({
            "title": ExportColumnPolicy.PUBLIC, "note": ExportColumnPolicy.PUBLIC,
            "amount": ExportColumnPolicy.PUBLIC, "iban": ExportColumnPolicy.HASHED,
            "email": ExportColumnPolicy.MASKED, "secret": ExportColumnPolicy.DENIED})
        own = {"tenant_id": t.tenant, "company_id": t.company}
        rows = [
            {**own, "title": '=HYPERLINK("x")', "note": "ok", "amount": Decimal("12.50"), "iban": f"DE-{t.tag}",
             "email": f"x@{t.tag}.example", "secret": f"s-{t.tag}", "extra": "undeclared"},
            {**own, "title": "+1 555", "note": "password: hunter2", "amount": 7, "iban": f"FR-{t.tag}",
             "email": "y@example.test", "secret": "t", "extra": "u"},
            {"tenant_id": t.foreign_tenant, "company_id": t.foreign_company, "title": f"foreign-{t.foreign_tag}",
             "note": f"n-{t.foreign_tag}", "amount": 1, "iban": f"XX-{t.foreign_tag}", "email": "z", "secret": "q"},
        ]
        self.keep("export", build_export(t.scope, ExportRequest(t.export_id), rows, policy, w, w, w.ids))
        yield

    # ---- E4: hold blocks a deletion decision, release is audited, plan is never executed ---------------------------
    def retention(self):
        w, t = self.w, self.t
        ledger = w.ledger
        self.keep("policy", ledger.add_policy(t.scope, RetentionPolicy("fin", 1, timedelta(days=30))))
        for run in t.runs:
            self.keep(f"object_{run}", ledger.register_object(t.scope, "run_id", run, t.source, "fin"))
        w.clock.advance(31 * DAY)
        yield

        def approve(label):
            """Two phases: the initiator requests, then the named approver confirms under his OWN scope."""
            pending = self.keep(f"approval_request_{label}", ledger.request_approval(
                t.scope, DeletionRequest("run_id", t.runs, "pending"), t.approver, w.clock.now() + timedelta(days=3)))
            if not isinstance(pending, ApprovalRequest):
                return pending
            return self.keep(f"approval_{label}", ledger.confirm_approval(
                t.approver_scope, DeletionRequest("run_id", t.runs, pending.approval_id)))

        def decide(approval):
            approval_id = getattr(approval, "approval_id", "missing")
            return decide_deletion(t.scope, DeletionRequest("run_id", t.runs, approval_id), ledger)

        approval1 = approve("1")
        w.clock.advance(60)
        self.keep("hold", ledger.place_hold(t.scope, HoldLevel.OBJECT, HoldReason.LEGAL, "run_id", t.runs[0]))
        self.keep("decision_blocked", decide(approval1))
        yield
        w.clock.advance(60)
        hold = self.out["hold"]
        if not isinstance(hold, Hold):
            return
        self.keep("release_request", ledger.request_release(t.scope, hold.hold_id, t.approver))
        self.keep("hold_release", ledger.confirm_release(t.approver_scope, hold.hold_id))
        self.keep("decision_stale_approval", decide(approval1))
        yield
        w.clock.advance(60)
        approval2 = approve("2")
        w.clock.advance(60)
        self.keep("decision_plan", decide(approval2))
        yield

    # ---- E5: readiness checklist ---------------------------------------------------------------------------------
    def readiness(self):
        self.keep("readiness", build_readiness(None, HEAD, self.w.ids))
        yield


def drain(gen):
    for _ in gen:
        pass


def run_interleaved(chains):
    live = [c.run() for c in chains]
    while live:
        for gen in list(live):
            try:
                next(gen)
            except StopIteration:
                live.remove(gen)


def solo(tag=TA, foreign=TB):
    t = Tenant(tag, foreign)
    w = World(t)
    chain = Chain(w, t)
    drain(chain.run())
    return w, t, chain


# ======================================================================================== scanners

_DIGEST_ATTRS = ("digest", "plan_digest", "report_digest", "export_digest", "manifest_digest", "source_digest",
                 "restored_digest", "policy_digest", "object_digest", "event_id")


def digests_of(out):
    found = {}
    for name, obj in out.items():
        items = list(enumerate(obj)) if isinstance(obj, (tuple, list)) else [("", obj)]
        for index, item in items:
            for attr in _DIGEST_ATTRS:
                value = getattr(item, attr, None)
                if type(value) is str and re.fullmatch(r"[0-9a-f]{32,64}", value):
                    found[f"{name}[{index}].{attr}"] = value
    return found


def _walk(obj, acc, seen, depth=0):
    if depth > 10 or id(obj) in seen:
        return
    seen.add(id(obj))
    if obj is None or isinstance(obj, (bool, int, float, str, Decimal, UUID, datetime, date, timedelta, bytes)):
        acc.append(str(obj))
        return
    if isinstance(obj, Enum):
        acc.append(str(obj.value))
        return
    acc.append(repr(obj))
    if isinstance(obj, dict):
        for key, value in obj.items():
            _walk(key, acc, seen, depth + 1)
            _walk(value, acc, seen, depth + 1)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            _walk(item, acc, seen, depth + 1)
    elif dataclasses.is_dataclass(obj):
        for f in dataclasses.fields(obj):
            try:
                value = getattr(obj, f.name)
            except AttributeError:
                continue
            _walk(value, acc, seen, depth + 1)


def visible_text(obj):
    """Everything an observer could read from an output: repr plus every (nested) dataclass field value."""
    acc = []
    _walk(obj, acc, set())
    return "\n".join(acc).lower()


def leaks(objs, marker):
    return [name for name, obj in objs.items() if marker in visible_text(obj)]


def is_refusal(out):
    return refusal_reason(out) is not None


def refusal_reason(out):
    if isinstance(out, OpsRefusal):
        return out.reason
    if isinstance(out, (GateOutcome, DeliveryOutcome)) and out.status.value == "REFUSED":
        return out.reason
    if isinstance(out, RollbackDecision) and not out.allowed:
        return out.reason
    return None


# ======================================================================================== E1 scenario

def test_capacity_grid_cell_report_then_interference_verdict_and_budget_plan():
    w, t, chain = solo()
    base, loaded = chain.out["report_base"], chain.out["report_loaded"]
    assert isinstance(base, CapacityReport) and isinstance(loaded, CapacityReport)
    # the four axes stay separate and the report is stamped as a scripted fixture, never as proof
    assert isinstance(chain.out["cell"], GridCell)
    assert chain.out["cell"].axes() == (("sources", 30), ("active_clients", 5), ("sessions", 1000), ("backends", 1))
    assert base.basis is Basis.SCRIPTED_OFFLINE_FIXTURE and base.authority == "EVALUATION_ONLY"
    assert not {"proven", "capacity_proven", "passed", "verdict"} & {f.name for f in dataclasses.fields(base)}
    # refusals are not throughput: 100 business reads over 10 s, 10 refused requests counted apart
    assert base.throughput_per_s == 10 and base.refusal_fraction == Decimal("0.090909")
    assert dict(base.counts)["BUSINESS_OK"] == 100 and dict(base.counts)["PROFILE_REFUSED"] == 10
    assert base.flags == ()
    # every number comes from the module function itself
    assert base.business[1] == percentile([1000 * (i + 1) for i in range(100)], 95)
    assert base.business[1].value == 95_000 and loaded.business[1].value == 104_500
    verdict = chain.out["interference"]
    assert verdict == interference(95_000, 104_500)
    assert verdict.reason is OpsReason.WITHIN_TARGET and verdict.ratio == Decimal("0.1")
    assert verdict.basis is Basis.SCRIPTED_OFFLINE_FIXTURE
    plan = chain.out["budget_plan"]
    assert (plan.interactive_granted, plan.background_granted) == (3, 1)  # background keeps its guaranteed minimum
    assert [(a.granted, a.deferred, a.reason) for a in plan.allocations] == [
        (3, 0, None), (1, 1, OpsReason.TENANT_SHARE_EXCEEDED)]
    assert chain.out["report_read"] == base and w.store.count(t.tenant) == 2


def test_capacity_verdicts_never_turn_green_on_bad_inputs():
    w, t, _ = solo()
    store, policy = w.store, ReportPolicy(window_us=10_000_000)
    cell = make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1),
                     CacheState.COLD, DiscoveryState.ON, WorkloadClass.BALANCES, w.ids)
    heavy = build_report(t.scope, w, w, store, cell, scripted_samples(1500), policy, w.clock)
    exceeded = interference(95_000, heavy.business[1])
    assert exceeded.reason is OpsReason.EXCEEDS_TARGET and exceeded == interference(95_000, 142_500)
    few = build_report(t.scope, w, w, store, cell, scripted_samples(1000)[:5], policy, w.clock)
    assert OpsReason.INSUFFICIENT_SAMPLES in few.flags and few.business[1].value is None
    assert interference(few.business[1], 100_000).reason is OpsReason.BASELINE_INVALID
    assert interference(95_000, few.business[1]).reason is OpsReason.INSUFFICIENT_SAMPLES
    # a configured limit is a limit, never capacity
    refused = make_cell(ConfiguredLimit(LimitLayer.R1_POOL, 10), ActiveClientCount(5), SessionCount(1000),
                        BackendCount(1), CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, w.ids)
    assert isinstance(refused, OpsRefusal) and refused.reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    assert interference(ConfiguredLimit(LimitLayer.R1_POOL, 10), 5).reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY


def test_capacity_report_calls_entitlement_first_and_foreign_report_ids_read_as_unknown():
    a, b = Tenant(TA, TB), Tenant(TB, TA)
    w = World(a, b)
    cell = make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1),
                     CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, w.ids)
    seg, report = w.segment(lambda: build_report(a.scope, w, w, w.store, cell, scripted_samples(1000),
                                                 ReportPolicy(window_us=10_000_000), w.clock))
    assert seg == [("entitled", a.tenant, a.actor)] and isinstance(report, CapacityReport)
    foreign_seg, foreign = w.segment(lambda: read_report(b.scope, report.report_id, w, w, w.store))
    unknown_seg, unknown = w.segment(lambda: read_report(b.scope, "RPT-999999", w, w, w.store))
    assert isinstance(foreign, OpsRefusal) and foreign.reason is OpsReason.NOT_FOUND
    assert (foreign.reason, foreign.next_action) == (unknown.reason, unknown.next_action)
    assert [e[:2] for e in foreign_seg] == [e[:2] for e in unknown_seg] == [("entitled", b.tenant),
                                                                              ("owns", b.tenant)]


# ======================================================================================== E2 scenarios

def test_audit_gate_sink_outage_blocks_the_effect_and_recovery_completes_it_without_rerun():
    w, t, chain = solo()
    sink = w.audit_sinks[t.tenant]
    down = chain.out["audit_down"]
    assert down.status is GateStatus.REFUSED and down.reason is OpsReason.AUDIT_UNAVAILABLE
    assert down.effect_invoked is False
    ok = chain.out["audit_ok"]
    assert ok.status is GateStatus.COMPLETED and ok.effect_invoked is True and ok.reason is None
    assert 0 < ok.intent_sequence < ok.completion_sequence
    pending = chain.out["audit_pending"]
    assert pending.status is GateStatus.COMPLETION_PENDING and pending.reason is OpsReason.AUDIT_COMPLETION_PENDING
    assert pending.effect_invoked is True and chain.out["unaudited_pending"].pending_count == 1
    retry = chain.out["audit_retry"]
    assert retry.status is GateStatus.COMPLETED and chain.out["unaudited_after"].pending_count == 0
    assert chain.out["unaudited_after"].entries[0].reconciled is True
    # call logs: the effect ran once per request (never for the outage, never again on retry) and the sink saw
    # the intent of the outage attempt, nothing else, before recovery
    assert chain.effect_calls == ["req1", "req2"]
    assert [(r.request_id, r.phase) for r in sink.records] == [
        (t.req1, AuditPhase.INTENT), (t.req1, AuditPhase.COMPLETION),
        (t.req2, AuditPhase.INTENT), (t.req2, AuditPhase.COMPLETION)]
    assert sink.write_attempts[0] is AuditPhase.INTENT
    assert POISON_FREE(chain.out)


def POISON_FREE(out):
    text = "\n".join(visible_text(v) for v in out.values())
    return all(p.lower() not in text for p in (FakeAuditSink.POISON, FakeDeliverySink.POISON,
                                                FakeAlertSink.POISON, "POISON-"))


def test_delivery_storm_with_429_network_faults_and_two_workers_publishes_each_event_exactly_once():
    w, t, chain = solo()
    reg = chain.out["register"]
    assert (reg.accepted, reg.replayed, reg.conflicts) == (12, 0, 0)
    assert chain.out["register_replay"].replayed == 12 and chain.out["register_replay"].accepted == 0
    clash = chain.out["register_conflict"]
    assert clash.conflicts == 1 and clash.reason is OpsReason.EVENT_DIGEST_CONFLICT
    assert chain.out["quarantine"] == 1
    # worker 2 is refused while worker 1 holds the lease; worker 1's stale claim publishes nothing
    assert chain.out["claim_contended"].reason is OpsReason.DUPLICATE_SUPPRESSED
    assert chain.out["held_outcome"].status is DeliveryStatus.CLAIM_HELD
    assert chain.facts["calls_while_held"] == 0
    assert chain.out["stale_outcome"].status is DeliveryStatus.STALE
    assert chain.out["stale_outcome"].reason is OpsReason.STALE_CLAIM and chain.facts["calls_after_stale"] == 0
    outcomes = chain.out["delivery_outcomes"]
    assert outcomes[-1].status is DeliveryStatus.COMPLETE and outcomes[-1].cursor_seq == 12
    waits = [o.reason for o in outcomes if o.status is DeliveryStatus.WAITING]
    assert waits == [OpsReason.RATE_LIMITED, OpsReason.NETWORK_FAILURE, OpsReason.NETWORK_FAILURE,
                     OpsReason.NETWORK_FAILURE, OpsReason.RATE_LIMITED]  # 429, network, raise, lost ack, 429
    assert {o.status for o in outcomes} == {DeliveryStatus.WAITING, DeliveryStatus.COMPLETE}
    # exactly once: twelve distinct events, each stored once, in sequence order; the lost ack is a duplicate ACK
    published = chain.published()
    assert [e[3] for e in published] == [f"EV-{t.tag}-{i:02d}" for i in range(1, 13)]
    assert sum(o.delivered_count for o in outcomes) + sum(o.duplicate_ack_count for o in outcomes) == 12
    assert sum(o.duplicate_ack_count for o in outcomes) == 1
    assert chain.out["cursor"] == 12 and chain.lags == [12, 0]
    assert all(r.status is RecordStatus.DELIVERED for r in w.planner.records(t.scope, t.source, t.conn))
    assert POISON_FREE(chain.out)


def test_alert_fires_once_on_delivery_lag_and_recovers_once_with_visible_delivery_failure():
    w, t, chain = solo()
    assert chain.out["alert_rule_result"] is None and chain.out["alert_obs_1"] is None
    assert chain.out["alert_pending"].state is AlertState.PENDING
    assert chain.out["alert_firing"].state is AlertState.FIRING and chain.out["alert_firing"].episode == 1
    failed = chain.out["alert_deliver_failed"]
    assert isinstance(failed, AlertDeliveryOutcome) and failed.reason is OpsReason.ALERT_DELIVERY_FAILED
    assert (failed.delivered_count, failed.remaining_count) == (0, 1)
    assert chain.out["alert_deliver_fired"].delivered_count == 1
    assert chain.out["alert_recovering"].state is AlertState.RECOVERING
    assert chain.out["alert_ok"].state is AlertState.OK
    assert chain.out["alert_deliver_recovered"].delivered_count == 1
    assert chain.out["alert_deliver_again"].delivered_count == 0 and chain.out["alert_deliver_again"].reason is None
    events = chain.out["alert_events"]
    assert [(e.event_type, e.reason) for e in events] == [(EventType.FIRED, OpsReason.ALERT_FIRED),
                                                           (EventType.RECOVERED, OpsReason.ALERT_RECOVERED)]
    # a later clear sample adds no event; the sink saw each event once, in order, after one failed attempt
    assert [e.event_id for e in chain.out["alert_sent"]] == [e.event_id for e in events]
    assert w.alert_sinks[t.tenant].attempts == 3
    # the samples that drove the alert are the lag of the real delivery storm
    assert chain.lags == [12, 0]


# ======================================================================================== E3 scenario

def test_release_expand_shadow_and_rollback_denied_for_destructive_allowed_as_plan_with_revoked_grant_revoked():
    w, t, chain = solo()
    rehearsal = chain.out["rehearsal"]
    assert isinstance(rehearsal, RehearsalPlan) and rehearsal.executed is False
    assert [(a.version, a.apply) for a in rehearsal.actions] == [("001", False), ("002", True)]
    refused = chain.out["rehearsal_destructive"]
    assert isinstance(refused, OpsRefusal) and refused.reason is OpsReason.DESTRUCTIVE
    assert classify_step(DESTRUCTIVE_STEP).as_reason() is OpsReason.DESTRUCTIVE  # the module decides, not the chain
    shadow = chain.out["shadow"]
    assert isinstance(shadow, ShadowResult) and shadow.reason is OpsReason.R1_UNCHANGED
    assert shadow.promotion_permitted is False
    ops = [f"OP-{t.tag}-{i}" for i in (1, 2, 3)]
    assert compare_shadow(ops, [ShadowObservation(o, sha("a"), sha("b"), sha("b")) for o in ops], w.ids).reason \
        is OpsReason.R1_REGRESSION
    assert compare_shadow(ops, [ShadowObservation(o, sha("a"), sha("a"), sha("b")) for o in ops], w.ids).reason \
        is OpsReason.SHADOW_DIVERGENCE
    assert compare_shadow(ops, [ShadowObservation(ops[0], sha("a"), sha("a"), sha("a"))], w.ids).reason \
        is OpsReason.SHADOW_INCOMPLETE
    # rollback: a destructive plan is denied, a clean plan is only a decision (executed is always False)
    denied = chain.out["rollback_destructive"]
    assert denied.allowed is False and denied.reason is OpsReason.ROLLBACK_DESTRUCTIVE_DENIED
    assert denied.plan_digest is None and denied.executed is False and denied.effective_grants == ()
    additive = chain.out["rollback_additive"]  # a rollback plan may only flip switches: adding rights is refused too
    assert additive.allowed is False and additive.reason is OpsReason.ROLLBACK_DESTRUCTIVE_DENIED
    g1, g2 = chain.facts["grant_ids"]
    first = chain.out["rollback_before_revoke"]
    assert first.allowed is True and first.executed is False and first.effective_grants == (g1, g2)
    # a revoked grant stays revoked: after revocation, after a re-issue attempt and under a regressed clock
    assert chain.facts["revoked"] is True and chain.facts["reissue_g1"] is False
    for name in ("rollback_after_revoke", "rollback_regressed_clock"):
        after = chain.out[name]
        assert after.allowed is True and after.executed is False
        assert after.effective_grants == (g2,)
        assert [(b.grant_id, b.cause, b.reason) for b in after.blocked] == [
            (g1, BlockCause.REVOKED, OpsReason.RESURRECTION_BLOCKED)]
    assert first.plan_digest != chain.out["rollback_after_revoke"].plan_digest
    unauthorized = chain.out["rollback_unauthorized"]
    assert unauthorized.allowed is False and unauthorized.reason is OpsReason.NOT_AUTHORIZED
    assert unauthorized.effective_grants == () and unauthorized.blocked == ()


# ======================================================================================== E4 scenarios

def test_restore_manifest_of_a_populated_registry_and_each_simulated_defect_has_its_own_code():
    _w, _t, chain = solo()
    manifest = chain.out["manifest"]
    assert isinstance(manifest, RestoreManifest) and [tb.name for tb in manifest.tables] == list(LIVING_TABLES)
    ok = chain.out["restore_ok"]
    assert isinstance(ok, RestoreReport) and ok.verified is True and ok.codes == ()
    assert [c.name for c in ok.checks] == list(CheckName) and all(c.ran and c.passed for c in ok.checks)
    expected = {"COUNT": OpsReason.RESTORE_COUNT_MISMATCH, "DIGEST": OpsReason.RESTORE_DIGEST_MISMATCH,
                "FK": OpsReason.RESTORE_FK_ORPHAN, "SEQUENCE": OpsReason.RESTORE_SEQUENCE_GAP,
                "HEAD": OpsReason.RESTORE_HEAD_MISMATCH, "ATTESTATION": OpsReason.RESTORE_ATTESTATION_STALE,
                "SCOPE": OpsReason.RESTORE_SCOPE_FOREIGN, "INCOMPLETE": OpsReason.RESTORE_INCOMPLETE}
    assert tuple(expected) == OWNED_DEFECT_NAMES
    for name, code in expected.items():
        report = chain.out[f"restore_{name}"]
        assert isinstance(report, RestoreReport) and report.verified is False, name
        assert code in report.codes, (name, report.codes)
        assert report.report_digest != ok.report_digest
    # an incomplete restore runs no other check; a defect never turns into a partial pass
    incomplete = chain.out["restore_INCOMPLETE"]
    assert [c.ran for c in incomplete.checks] == [True] + [False] * 7
    # the report names fixed tables and codes only: no foreign tenant id and no value of the defect
    assert TB not in visible_text(chain.out["restore_SCOPE"])


def test_export_masks_hashes_denies_neutralizes_formulas_and_drops_foreign_rows_without_trace():
    _w, _t, chain = solo()
    result = chain.out["export"]
    assert isinstance(result, ExportResult)
    assert result.header == ("amount", "email", "iban", "note", "title")  # secret DENIED, extra undeclared
    first, second = result.rows
    assert first[0] == "12.50" and first[1] == "[MASKED]" and first[3] == "ok"
    assert first[2].startswith("h:") and len(first[2]) == 18 and first[2] != second[2]
    assert first[4] == "'=HYPERLINK(\"x\")" and second[4] == "'+1 555"  # formula-capable text is neutralized
    assert second[3] == "[DENIED]" and second[0] == "7"  # credential-shaped text is denied, numbers are exempt
    assert (result.neutralized_cells, result.denied_values, result.unclassified_columns) == (2, 1, 1)
    assert result.hidden_by_scope is True and len(result.rows) == 2
    assert result.findings == (OpsReason.COLUMN_UNCLASSIFIED, OpsReason.CELL_NEUTRALIZED,
                               OpsReason.VALUE_DENIED, OpsReason.HIDDEN_BY_SCOPE)
    assert TB not in visible_text(result) and "hunter2" not in visible_text(result)
    assert result.authority == "EVALUATION_ONLY"


def test_hold_blocks_deletion_release_is_audited_and_the_final_decision_is_a_plan_never_executed():
    w, t, chain = solo()
    blocked = chain.out["decision_blocked"]
    assert isinstance(blocked, OpsRefusal) and blocked.reason is OpsReason.HOLD_ACTIVE
    release = chain.out["hold_release"]
    assert isinstance(release, HoldReleaseReceipt) and len(w.hold_audits) == 1
    assert (w.hold_audits[0].action, w.hold_audits[0].requester, w.hold_audits[0].approver) == (
        "HOLD_RELEASED", t.actor, t.approver)
    assert isinstance(chain.out["release_request"], ReleaseRequest)
    stale = chain.out["decision_stale_approval"]  # an approval older than a (even released) hold stays void
    assert isinstance(stale, OpsRefusal) and stale.reason is OpsReason.APPROVAL_MISSING
    plan = chain.out["decision_plan"]
    assert isinstance(plan, DeletionDecision) and plan.executed is False
    assert plan.reason is OpsReason.DELETION_ALLOWED_PLAN and plan.approval_id == chain.out["approval_2"].approval_id
    assert plan.plan_digest != plan.object_digest
    assert not hasattr(chain.w.ledger, "delete") and not hasattr(chain.w.ledger, "execute")


# ======================================================================================== E5 readiness

def test_readiness_states_every_slot_not_run_after_a_fully_green_chain():
    w, _t, chain = solo()
    report = chain.out["readiness"]
    assert isinstance(report, ReadinessReport) and report.head == HEAD
    assert [s.status for s in report.slots] == [SlotStatus.NOT_RUN] * 6
    assert report.not_run == tuple(SlotKind) and len(report.not_run) == 6
    for kind in SlotKind:
        assert kind.value in report.statement
    assert "NOT PASSED" in report.statement and all(s.evidence_digest is None for s in report.slots)
    assert not {"passed", "g6_pre_passed", "proven", "verdict", "ok"} & {f.name for f in dataclasses.fields(report)}
    assert not any(hasattr(report, name) for name in ("passed", "g6_pre_passed", "is_passed"))
    # the green outputs of the whole chain are not evidence: nothing but an OperatorEvidenceRef can move a slot
    green = [v for v in chain.out.values() if not isinstance(v, (str, int))]
    assert green, "the chain produced no outputs"
    fed = build_readiness(green, HEAD, w.ids)
    assert isinstance(fed, ReadinessReport) and fed.not_run == tuple(SlotKind)
    assert fed.report_digest == report.report_digest


def test_readiness_marks_only_the_slot_with_a_matching_operator_evidence_ref_as_unverified():
    ref = OperatorEvidenceRef(SlotKind.REPEATABLE_RESTORE_REHEARSAL, "OPS-REF-1", sha("artifact"), "staging", HEAD)
    wrong_head = OperatorEvidenceRef(SlotKind.MIGRATION_REHEARSAL_ON_COPY, "OPS-REF-2", sha("x"), "staging",
                                     "fedcba7654321")
    report = build_readiness([ref, wrong_head], HEAD)
    status = {s.slot: s.status for s in report.slots}
    assert status[SlotKind.REPEATABLE_RESTORE_REHEARSAL] is SlotStatus.EVIDENCE_RECEIVED_UNVERIFIED
    assert [k for k, v in status.items() if v is SlotStatus.NOT_RUN] == [
        k for k in SlotKind if k is not SlotKind.REPEATABLE_RESTORE_REHEARSAL]
    assert SlotKind.REPEATABLE_RESTORE_REHEARSAL not in report.not_run
    assert SlotKind.MIGRATION_REHEARSAL_ON_COPY in report.not_run  # evidence for another head does not count
    assert "NOT PASSED" in report.statement and build_readiness([ref], HEAD) == build_readiness([ref, ref], HEAD)
    bad_head = build_readiness([ref], "not a head!", FakeCorrelationSource())
    assert isinstance(bad_head, OpsRefusal) and bad_head.reason is OpsReason.INPUT_INVALID


# ======================================================================================== chain-wide properties

def test_the_chain_adds_no_decision_rule_every_result_equals_the_direct_module_call():
    w, t, chain = solo()
    out = chain.out
    # E1
    assert out["interference"] == interference(out["report_base"].business[1].value,
                                               out["report_loaded"].business[1].value)
    assert out["report_loaded"].business == tuple(
        percentile([1100 * (i + 1) for i in range(100)], p) for p in (50, 95, 99))
    # E3
    assert out["shadow"] == compare_shadow(
        [f"OP-{t.tag}-{i}" for i in (1, 2, 3)],
        [ShadowObservation(f"OP-{t.tag}-{i}", sha(f"OP-{t.tag}-{i}"), sha(f"OP-{t.tag}-{i}"),
                           sha(f"OP-{t.tag}-{i}")) for i in (1, 2, 3)], w.ids)
    assert out["rehearsal"] == plan_rehearsal(
        [MigrationUnit("001", (), ADDITIVE_STEPS), MigrationUnit("002", ("001",), ADDITIVE_STEPS)], ("001",), w.ids)
    # E5: the readiness result is a pure function of (evidence, head)
    assert out["readiness"] == build_readiness(None, HEAD, w.ids)
    # call logs: every gated call opened with the entitlement check of the acting tenant, and no port was ever
    # asked about any identifier of the OTHER tenant even though its ids were fed in as hostile input
    kinds = {e[0] for e in w.log}
    assert kinds == {"entitled", "owns"} and w.log[0][0] == "entitled"
    assert all(e[1] == t.tenant for e in w.log)
    assert not [e for e in w.log if TB in " ".join(map(str, e[2:])).lower()]
    # the ledger and planner took no decision from the chain: every refusal carries a fixed OpsReason code
    for name in ("decision_blocked", "decision_stale_approval", "rehearsal_destructive"):
        assert is_refusal(out[name]) and type(out[name].reason) is OpsReason


def test_identical_inputs_with_injected_clock_and_ids_give_byte_identical_digests():
    runs = [digests_of(solo()[2].out) for _ in range(2)]
    first, second = (json.dumps(r, sort_keys=True).encode() for r in runs)
    assert first == second and len(runs[0]) >= 25
    for key in ("report_base[].digest", "interference[].digest", "budget_plan[].digest", "rehearsal[].digest",
                "shadow[].digest", "manifest[].manifest_digest", "restore_ok[].report_digest",
                "export[].export_digest", "decision_plan[].plan_digest", "readiness[].report_digest",
                "rollback_before_revoke[].plan_digest"):
        assert key in runs[0], key
    # the digests are bound to the inputs: another tenant tag changes every tenant-bound one
    other = digests_of(solo(TB, TA)[2].out)
    assert other["manifest[].manifest_digest"] != runs[0]["manifest[].manifest_digest"]
    assert other["readiness[].report_digest"] == runs[0]["readiness[].report_digest"]  # tenant-free by design


def test_two_tenants_interleaved_have_zero_cross_visibility_and_the_same_decisions_as_alone():
    def interleaved():
        a, b = Tenant(TA, TB), Tenant(TB, TA)
        w = World(a, b)
        ca, cb = Chain(w, a), Chain(w, b)
        run_interleaved([ca, cb])
        return w, ca, cb

    w, ca, cb = interleaved()
    # positive control: the scanner does find an id that really is in the output, and a planted foreign one
    assert not leaks({"x": ca.out["report_base"]}, "zzz-not-there")
    assert leaks({"restore_ok": ca.out["manifest"]}, TA)
    assert leaks({"planted": _Planted(f"x {TB}")}, TB)
    # zero cross-visibility: every output and repr of A for B's markers and vice versa
    assert leaks(ca.out, TB) == [] and leaks(cb.out, TA) == []
    assert not [k for k, v in ca.out.items() if TA not in visible_text(v) and k in OWN_MARKER_KEYS]
    # the tenants' own sinks and the shared sink hold only their own data
    for c, other in ((ca, TB), (cb, TA)):
        sink = w.audit_sinks[c.t.tenant]
        assert leaks({"audit": tuple(sink.records), "alerts": tuple(w.alert_sinks[c.t.tenant].sent),
                      "published": tuple(c.published())}, other) == []
    for entry in w.delivery_sink.published:
        assert (TA in " ".join(entry).lower()) != (TB in " ".join(entry).lower())  # exactly one tenant per event
    # the shared components keep per-tenant counts
    assert w.store.count(ca.t.tenant) == w.store.count(cb.t.tenant) == 2
    assert len(w.alerts.events(ca.t.scope)) == len(w.alerts.events(cb.t.scope)) == 2
    assert w.gate.unaudited(ca.t.scope).pending_count == 0 == w.gate.unaudited(cb.t.scope).pending_count
    # decisions of an interleaved tenant equal the decisions of the same tenant running alone
    alone_a = solo(TA, TB)[2]
    for name in ("interference", "shadow", "rehearsal"):
        assert ca.out[name] == alone_a.out[name], name
    for name in ("audit_down", "audit_ok", "audit_pending", "audit_retry"):
        assert (ca.out[name].status, ca.out[name].reason) == (alone_a.out[name].status, alone_a.out[name].reason)
    assert [o.status for o in ca.out["delivery_outcomes"]][-1] is DeliveryStatus.COMPLETE
    assert ca.out["decision_plan"].executed is False and cb.out["decision_plan"].executed is False
    assert ca.out["restore_ok"].verified and cb.out["restore_ok"].verified
    # the interleaving itself is deterministic: a second run reproduces every digest of both tenants
    _w2, ca2, cb2 = interleaved()
    assert digests_of(ca.out) == digests_of(ca2.out) and digests_of(cb.out) == digests_of(cb2.out)
    assert digests_of(ca.out) != digests_of(cb.out)


OWN_MARKER_KEYS = ("manifest",)


class _Planted:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return self.text


def test_foreign_references_read_exactly_like_unknown_ones_across_every_module():
    a, b = Tenant(TA, TB), Tenant(TB, TA)
    w = World(a, b)
    run_interleaved([Chain(w, a), Chain(w, b)])
    sink = w.delivery_sink

    def probes(src, run, export_id, conn):
        req = DeletionRequest("run_id", (run,), "x")
        return {
            "gate": lambda: w.gate.guarded_effect(a.scope, "REQ-X", "create_document", lambda: None,
                                                  (("source_id", src),)),
            "register": lambda: w.planner.register(a.scope, src, []),
            "records": lambda: w.planner.records(a.scope, src, conn),
            "deliver": lambda: w.planner.deliver_pending(a.scope, a.workers[0], src, conn),
            "alert": lambda: w.alerts.status(a.scope, src, RuleKind.OUTBOX_LAG),
            "manifest": lambda: build_manifest(a.scope, (src,), {}, w, w, w.ids),
            "export": lambda: build_export(a.scope, ExportRequest(export_id), [], ExportPolicy(()), w, w, w.ids),
            "deletion": lambda: decide_deletion(a.scope, req, w.ledger),
        }

    foreign = probes(b.source, b.runs[0], b.export_id, b.conn)
    unknown = probes("SRC-nope", "RUN-nope", "EXP-nope", "CN-nope")
    before = len(sink.calls)
    for name, call in foreign.items():
        f_seg, f_out = w.segment(call)
        u_seg, u_out = w.segment(unknown[name])
        assert refusal_reason(f_out) is not None, name
        assert refusal_reason(f_out) is refusal_reason(u_out), name
        assert [e[:2] for e in f_seg] == [e[:2] for e in u_seg], name  # same port-call pattern
        assert f_seg[0][0] == "entitled", name
        assert TB not in visible_text(f_out), name
    assert refusal_reason(foreign["deletion"]()) is OpsReason.OBJECT_NOT_OWNED
    assert len(sink.calls) == before  # not one publish for a foreign connection
    # rollback is platform-level: another tenant's registry instance is simply a different object
    assert not hasattr(w, "grants")


# ======================================================================================== induced failures

def _ports_table(w, t):
    """Every gated entry point, with whether it asks the ownership port at all."""
    cell = make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1),
                     CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, w.ids)
    ev = DeliveryEvent(t.conn, 1, f"EV-{t.tag}-01", sha("e"))
    refs = (("source_id", t.source),)
    return {
        "report": (False, lambda: build_report(t.scope, w, w, w.store, cell, scripted_samples(1000),
                                               ReportPolicy(window_us=10), w.clock)),
        "gate": (True, lambda: w.gate.guarded_effect(t.scope, t.req1, "create_document", lambda: None, refs)),
        "register": (True, lambda: w.planner.register(t.scope, t.source, [ev])),
        "deliver": (True, lambda: w.planner.deliver_pending(t.scope, t.workers[0], t.source, t.conn)),
        "alert": (True, lambda: w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, 1)),
        "manifest": (True, lambda: build_manifest(t.scope, (t.source,), {}, w, w, w.ids)),
        "export": (True, lambda: build_export(t.scope, ExportRequest(t.export_id), [], ExportPolicy(()),
                                              w, w, w.ids)),
        "retention": (True, lambda: decide_deletion(t.scope, DeletionRequest("run_id", t.runs, "a"), w.ledger)),
    }


@pytest.mark.parametrize("port", ["entitlement", "ownership"])
def test_a_failing_port_gives_a_fixed_dependency_refusal_and_no_effect_anywhere(port):
    t = Tenant(TA, TB)
    w = World(t)
    effects = []
    w.broken.add(port)
    table = _ports_table(w, t)
    for name, (uses_ownership, call) in table.items():
        if port == "ownership" and not uses_ownership:
            continue
        out = call()
        assert refusal_reason(out) is OpsReason.DEPENDENCY_FAILED, (name, out)
        text = visible_text(out)
        assert "poison" not in text, name
    # the failure happened BEFORE any effect: no sink was touched, nothing was stored
    assert w.delivery_sink.calls == [] and w.audit_sinks[t.tenant].write_attempts == []
    assert w.store.count(t.tenant) == 0 and effects == []
    assert w.alerts.records(OpsScope("x", "y", "z")) is not None  # the engine itself still answers


def test_a_chain_with_every_port_down_never_returns_a_partial_or_green_result():
    t = Tenant(TA, TB)
    w = World(t)
    w.broken.update({"entitlement", "ownership"})
    chain = Chain(w, t)
    drain(chain.run())
    assert chain.effect_calls == []
    for name, value in chain.out.items():
        if name in ("readiness", "cell", "rehearsal", "rehearsal_destructive", "shadow") or \
                name.startswith(("rollback", "audit_records")):
            continue  # tenant-free components: they have no port to lose
        reason = refusal_reason(value)
        assert reason is OpsReason.DEPENDENCY_FAILED or isinstance(value, (OpsRefusal, GateOutcome,
                                                                          DeliveryOutcome, tuple)), (name, value)
        assert not isinstance(value, (CapacityReport, RegisterOutcome, RestoreManifest, RestoreReport,
                                      ExportResult, DeletionDecision)), name
    assert w.delivery_sink.calls == [] and w.delivery_sink.published == []
    assert chain.out["readiness"].not_run == tuple(SlotKind)  # the checklist itself is unaffected: still NOT_RUN
    assert not [k for k in chain.out if k in ("decision_plan", "restore_ok", "export") and
                not is_refusal(chain.out[k])]
    # platform-level rollback decisions do not depend on tenant ports, yet stay plans: executed is False
    assert all(v.executed is False for k, v in chain.out.items() if k.startswith("rollback"))


@pytest.mark.parametrize("mode", [SinkMode.DOWN, SinkMode.SLOW, SinkMode.MALFORMED, SinkMode.NON_DURABLE])
def test_every_audit_sink_failure_mode_refuses_before_the_effect(mode):
    t = Tenant(TA, TB)
    w = World(t)
    w.audit_sinks[t.tenant].set_mode(mode)
    calls = []
    out = w.gate.guarded_effect(t.scope, t.req1, "create_document", lambda: calls.append(1),
                                (("source_id", t.source),))
    assert out.status is GateStatus.REFUSED and out.reason is OpsReason.AUDIT_UNAVAILABLE
    assert calls == [] and out.effect_invoked is False
    assert FakeAuditSink.POISON not in visible_text(out)


@pytest.mark.parametrize("answer", [False, None, "yes", RuntimeError("POISON-AUDIT-FN")])
def test_a_failed_hold_release_audit_keeps_the_hold_and_the_deletion_blocked(answer):
    t = Tenant(TA, TB)
    w = World(t)
    chain = Chain(w, t)
    gen = chain.retention()
    next(gen)  # policy + objects, clock +31 days
    next(gen)  # approval, hold, blocked decision
    w.hold_audit_answer = answer
    hold = chain.out["hold"]
    w.clock.advance(60)
    assert isinstance(w.ledger.request_release(t.scope, hold.hold_id, t.approver), ReleaseRequest)
    release = w.ledger.confirm_release(t.approver_scope, hold.hold_id)
    assert isinstance(release, OpsRefusal) and release.reason is OpsReason.AUDIT_UNAVAILABLE
    again = decide_deletion(t.scope, DeletionRequest("run_id", t.runs, chain.out["approval_1"].approval_id), w.ledger)
    assert isinstance(again, OpsRefusal) and again.reason is OpsReason.HOLD_ACTIVE
    assert "poison" not in visible_text(release).lower()


def test_failing_attestation_port_authority_grants_and_clock_are_fixed_refusals_not_results():
    t = Tenant(TA, TB)
    w = World(t)  # fresh clock: the attestation row is still unexpired, so the port really is asked
    rows = restore_rows(t, "att-x")
    manifest = build_manifest(t.scope, (t.source,), rows, w, w, w.ids)

    class Raises:
        def __getattr__(self, name):
            raise RuntimeError("POISON-COMPONENT")

    class Garbled:
        def check_current(self, *args):
            return object()

    def verify(attestations, clock):
        return verify_restore(t.scope, (t.source,), manifest, manifest, w, w, w.ids, attestations, clock)

    def boom():
        raise RuntimeError("POISON-CLOCK")

    for att, clock in ((Raises(), w.clock), (Garbled(), w.clock), (None, boom)):
        out = verify(att, clock)
        assert isinstance(out, OpsRefusal) and out.reason is OpsReason.DEPENDENCY_FAILED
    plan = RollbackPlan("2026-05", 5, SWITCH_STEPS)
    state = ReleaseState("REL-1", T_BASE, 3600, 5)
    registry = FakeGrantRegistry()
    for kwargs in ({"authority": Raises()}, {"grants": Raises()}, {"clock": boom}):
        args = {"grants": registry, "attestations": object(), "authority": w.authority, "clock": w.clock,
                "ids": w.ids} | kwargs
        decision = decide_rollback(t.operator, plan, state, **args)
        assert decision.allowed is False and decision.reason is OpsReason.DEPENDENCY_FAILED
        assert decision.plan_digest is None and decision.executed is False
    # an unusable ledger clock cannot produce a deletion plan either
    w2 = World(t)
    broken_ledger = RetentionLedger(w2.ids, w2, w2, w2.authority, boom, w2._hold_audit, 10)
    assert broken_ledger.add_policy(t.scope, RetentionPolicy("fin", 1, timedelta(days=1))).__class__ is RetentionPolicy
    reg = broken_ledger.register_object(t.scope, "run_id", t.runs[0], t.source, "fin")
    assert isinstance(reg, OpsRefusal) and reg.reason is OpsReason.DEPENDENCY_FAILED


def test_a_failing_report_owner_registration_stores_nothing_and_a_failing_sinks_never_complete_delivery():
    t = Tenant(TA, TB)
    w = World(t)

    def refuse_owner(*args):
        raise RuntimeError("POISON-OWNER-REGISTRY")

    store = CapacityStore(10, FakeCorrelationSource("RPT"), refuse_owner, w.ids)
    cell = make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1),
                     CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, w.ids)
    out = build_report(t.scope, w, w, store, cell, scripted_samples(1000), ReportPolicy(window_us=10_000_000), w.clock)
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.DEPENDENCY_FAILED and store.count(t.tenant) == 0
    # a delivery sink that always raises or answers garbage never completes and never advances the cursor
    events = [DeliveryEvent(t.conn, i, f"EV-{t.tag}-{i}", sha(str(i))) for i in (1, 2)]
    assert isinstance(w.planner.register(t.scope, t.source, events), RegisterOutcome)
    w.delivery_sink.script(t.tenant, ["RAISE", "MALFORMED"])
    for _ in range(2):
        out = w.planner.deliver_pending(t.scope, t.workers[0], t.source, t.conn)
        assert out.status is DeliveryStatus.WAITING and out.reason is OpsReason.NETWORK_FAILURE
        w.clock.to(out.next_retry_at)
    assert w.planner.cursor(t.scope, t.source, t.conn) == 0 and w.delivery_sink.published == []
    # an alert sink that fails in every flavour leaves the event undelivered and says so
    assert w.alerts.set_rule(t.scope, t.source, AlertRule(RuleKind.OUTBOX_LAG, 5, 0, 0, 0)) is None
    assert w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, 9) is None
    sink = w.alert_sinks[t.tenant]
    for mode in ("raise", "false", "malformed"):
        sink.fail_next(1, mode)
        outcome = w.alerts.deliver_events(t.scope)
        assert outcome.reason is OpsReason.ALERT_DELIVERY_FAILED and outcome.remaining_count == 1
    assert len(w.alerts.undelivered(t.scope)) == 1 and sink.sent == []


# ======================================================================================== concurrency

@pytest.mark.parametrize("round_no", range(5))
def test_two_threads_running_delivery_and_alert_publish_once_and_alert_once(round_no):
    t = Tenant(TA, TB)
    w = World(t)
    count = 20
    events = [DeliveryEvent(t.conn, i, f"EV-{t.tag}-{i:02d}", sha(f"{round_no}-{i}")) for i in range(1, count + 1)]
    assert isinstance(w.planner.register(t.scope, t.source, events), RegisterOutcome)
    assert w.alerts.set_rule(t.scope, t.source, AlertRule(RuleKind.OUTBOX_LAG, 5, 0, 0, 0)) is None
    sink = w.alert_sinks[t.tenant]
    barrier = threading.Barrier(2)
    outcomes, alert_results, errors = [], [], []

    def worker(name):
        try:
            barrier.wait(timeout=10)
            for _ in range(2000):
                outcomes.append(w.planner.deliver_pending(t.scope, name, t.source, t.conn))
                if w.planner.cursor(t.scope, t.source, t.conn) == count:
                    break
            for _ in range(200):  # a contended observation is refused and changed nothing: retry it
                if w.alerts.observe(t.scope, t.source, RuleKind.OUTBOX_LAG, 9) is None:
                    break
            for _ in range(200):
                result = w.alerts.deliver_events(t.scope)
                alert_results.append(result)
                if not isinstance(result, OpsRefusal) and result.remaining_count == 0:
                    break
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(name,)) for name in t.workers]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert errors == [] and not any(th.is_alive() for th in threads)
    # no duplicate publication: every event reached the sink exactly once, in order, and no worker was told "duplicate"
    assert [e[3] for e in w.delivery_sink.published] == [e.event_id for e in events]
    assert len(w.delivery_sink.calls) == count
    delivered = [o for o in outcomes if isinstance(o, DeliveryOutcome)]
    assert sum(o.delivered_count for o in delivered) == count and sum(o.duplicate_ack_count for o in delivered) == 0
    assert w.planner.cursor(t.scope, t.source, t.conn) == count
    # no double alert: one FIRED event, delivered once, to a sink that stored it once
    recorded = w.alerts.events(t.scope)
    assert [(e.event_type, e.reason) for e in recorded] == [(EventType.FIRED, OpsReason.ALERT_FIRED)]
    assert len(sink.sent) == 1 and sink.sent[0].event_id == recorded[0].event_id
    assert sum(r.delivered_count for r in alert_results if isinstance(r, AlertDeliveryOutcome)) == 1
    assert w.alerts.status(t.scope, t.source, RuleKind.OUTBOX_LAG).episode == 1
    assert w.alerts.undelivered(t.scope) == ()
