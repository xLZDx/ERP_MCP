"""S9 E2 / TC132: alert state machine, hysteresis, NO_DATA, visible delivery failure, per-tenant isolation."""
import ast
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.phase2.alert_rules import (
    AlertDeliveryOutcome,
    AlertEngine,
    AlertEvent,
    AlertRule,
    AlertState,
    AlertStatus,
    EventType,
    FakeAlertSink,
    RuleKind,
)
from business_ai_gateway.phase2.ops_types import (
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"
POISON = FakeAlertSink.POISON
T0 = datetime(2026, 3, 1, tzinfo=UTC)


class EvilDecimal(Decimal):
    pass


class EvilInt(int):
    pass


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class ManualClock:
    def __init__(self):
        self.t = T0

    def now(self):
        return self.t

    def adv(self, seconds):
        self.t += timedelta(seconds=seconds)


class SpyPorts:
    def __init__(self):
        self.log = []
        self.owner = FakeOwnership()
        self.ent = FakeEntitlements()

    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id))
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, kind))
        return self.owner.owns(tenant_id, company_id, kind, ref)


S1 = OpsScope("t1", "c1", "a1")
S2 = OpsScope("t2", "c2", "a2")


class Env:
    def __init__(self, **kwargs):
        self.ports = SpyPorts()
        for t, c, a, s in (("t1", "c1", "a1", "SRC-1"), ("t2", "c2", "a2", "SRC-2")):
            self.ports.ent.grant(t, a, c)
            self.ports.owner.add(t, c, "source_id", s)
        self.clock = ManualClock()
        self.engine = AlertEngine(self.ports, self.ports, FakeCorrelationSource(), self.clock, **kwargs)
        self.sink = FakeAlertSink()

    def rule(self, kind=RuleKind.CURSOR_LAG, scope=S1, subject="SRC-1", threshold=10, for_d=0, recover=2, rec_d=0,
             no_data=60):
        r = AlertRule(kind, threshold, for_d, recover, rec_d, no_data)
        assert self.engine.set_rule(scope, subject, r) is None
        return r

    def obs(self, value, kind=RuleKind.CURSOR_LAG, scope=S1, subject="SRC-1", adv=0):
        self.clock.adv(adv)
        return self.engine.observe(scope, subject, kind, value)

    def state(self, kind=RuleKind.CURSOR_LAG, scope=S1, subject="SRC-1"):
        return self.engine.status(scope, subject, kind).state

    def types(self, scope=S1):
        return [(e.event_type, e.reason) for e in self.engine.events(scope)]


# ---- every rule kind: one firing and one recovery ---------------------------------------------------

KIND_CASES = [
    (RuleKind.AUDIT_UNAVAILABLE, 1, 0, 1, 0),
    (RuleKind.CURSOR_LAG, 100, 10, 500, 5),
    (RuleKind.OUTBOX_LAG, 60, 10, 120, 0),
    (RuleKind.FAILURE_RATIO, Decimal("0.5"), Decimal("0.2"), Decimal("0.9"), Decimal("0.1")),
    (RuleKind.UNAUDITED_EFFECTS, 1, 0, 3, 0),
    (RuleKind.RESTORE_VERIFICATION_FAILED, 1, 0, 1, 0),
]


@pytest.mark.parametrize("kind,threshold,recover,high,low", KIND_CASES)
def test_every_rule_kind_fires_once_and_recovers_once(kind, threshold, recover, high, low):
    env = Env()
    env.rule(kind, threshold=threshold, for_d=30, recover=recover, rec_d=20)
    assert env.obs(high, kind) is None and env.state(kind) is AlertState.PENDING
    assert env.types() == []
    env.obs(high, kind, adv=30)
    assert env.state(kind) is AlertState.FIRING and env.types() == [(EventType.FIRED, OpsReason.ALERT_FIRED)]
    env.obs(low, kind, adv=5)
    assert env.state(kind) is AlertState.RECOVERING
    env.obs(low, kind, adv=20)
    assert env.state(kind) is AlertState.OK
    assert env.types() == [(EventType.FIRED, OpsReason.ALERT_FIRED), (EventType.RECOVERED, OpsReason.ALERT_RECOVERED)]


def test_rule_kinds_are_exactly_the_tdd_list():
    assert {k.value for k in RuleKind} == {"AUDIT_UNAVAILABLE", "CURSOR_LAG", "OUTBOX_LAG", "FAILURE_RATIO",
                                           "UNAUDITED_EFFECTS", "RESTORE_VERIFICATION_FAILED"}


# ---- single fire, hysteresis, flapping --------------------------------------------------------------

def test_threshold_is_inclusive_and_short_breach_never_fires():
    env = Env()
    env.rule(for_d=30)
    env.obs(9, adv=0)
    assert env.state() is AlertState.OK
    env.obs(10)
    assert env.state() is AlertState.PENDING
    env.obs(3, adv=29)  # back inside the band before for_duration: PENDING drops, nothing fired
    assert env.state() is AlertState.OK and env.types() == []
    env.obs(10, adv=1)
    env.obs(10, adv=29)
    assert env.state() is AlertState.PENDING  # a new PENDING started at the second breach


def test_continued_breach_creates_a_single_fired_event():
    env = Env()
    env.rule(for_d=0)
    for _ in range(25):
        env.obs(50, adv=1)
    assert env.types() == [(EventType.FIRED, OpsReason.ALERT_FIRED)] and env.state() is AlertState.FIRING


def test_flapping_inside_hysteresis_creates_no_second_event():
    env = Env()
    env.rule(for_d=0, recover=2, rec_d=30)
    env.obs(50)
    for _ in range(6):
        env.obs(1, adv=10)    # clear: RECOVERING (shorter than recover_duration)
        env.obs(5, adv=1)     # inside the band: back to FIRING, no recovery
        env.obs(50, adv=1)    # above the threshold again
    assert env.types() == [(EventType.FIRED, OpsReason.ALERT_FIRED)] and env.state() is AlertState.FIRING


def test_band_value_does_not_recover_and_recovery_needs_continuous_clear():
    env = Env()
    env.rule(for_d=0, recover=2, rec_d=30)
    env.obs(50)
    env.obs(5, adv=100)  # band only: still firing, no recovery
    assert env.state() is AlertState.FIRING
    env.obs(1, adv=1)
    env.obs(1, adv=30)
    assert env.state() is AlertState.OK and len(env.types()) == 2


def test_new_episode_after_recovery_gives_a_second_pair_with_distinct_ids():
    env = Env()
    env.rule()
    env.obs(50)
    env.obs(0, adv=1)
    env.obs(50, adv=1)
    env.obs(0, adv=1)
    events = env.engine.events(S1)
    assert [e.event_type for e in events] == [EventType.FIRED, EventType.RECOVERED] * 2
    assert len({e.event_id for e in events}) == 4 and [e.episode for e in events] == [1, 1, 2, 2]


# ---- NO_DATA ----------------------------------------------------------------------------------------

def test_silence_fires_no_data_once_and_a_clear_stream_recovers_it():
    env = Env()
    env.rule(no_data=60)
    env.obs(1)
    env.clock.adv(59)
    assert env.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG) is None and env.state() is AlertState.OK
    env.clock.adv(2)
    env.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG)
    assert env.state() is AlertState.FIRING and env.types() == [(EventType.FIRED, OpsReason.NO_DATA)]
    assert env.engine.status(S1, "SRC-1", RuleKind.CURSOR_LAG).no_data_active is True
    env.clock.adv(500)
    env.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG)  # still silent: no second event
    assert len(env.types()) == 1
    env.obs(1, adv=1)
    assert env.state() is AlertState.OK
    assert env.types()[-1] == (EventType.RECOVERED, OpsReason.ALERT_RECOVERED)
    assert env.engine.status(S1, "SRC-1", RuleKind.CURSOR_LAG).no_data_active is False


def test_a_rule_that_never_saw_a_sample_fires_no_data_too():
    env = Env()
    env.rule(no_data=60)
    env.clock.adv(61)
    env.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG)
    assert env.types() == [(EventType.FIRED, OpsReason.NO_DATA)]


def test_no_data_while_pending_fires_and_while_recovering_returns_to_firing_without_event():
    env = Env()
    env.rule(for_d=100, no_data=60)
    env.obs(50)
    env.clock.adv(61)
    env.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG)
    assert env.types() == [(EventType.FIRED, OpsReason.NO_DATA)]
    env2 = Env()
    env2.rule(for_d=0, rec_d=100, no_data=60)
    env2.obs(50)
    env2.obs(0, adv=1)
    assert env2.state() is AlertState.RECOVERING
    env2.clock.adv(61)
    env2.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG)
    assert env2.state() is AlertState.FIRING and len(env2.types()) == 1


# ---- clock regression -------------------------------------------------------------------------------

def test_clock_regression_neither_unfires_nor_double_fires():
    env = Env()
    env.rule(for_d=30, rec_d=30)
    env.obs(50)
    env.obs(50, adv=30)
    assert env.state() is AlertState.FIRING
    env.clock.adv(-3600)  # clock jumps back an hour
    env.obs(50)
    env.obs(1)            # clear sample at a regressed time: RECOVERING starts at the clamped time
    assert env.state() is AlertState.RECOVERING and len(env.types()) == 1
    env.obs(1)
    assert env.state() is AlertState.RECOVERING  # regressed time never completes a recovery early
    env.clock.t = T0 + timedelta(seconds=30 + 31)
    env.obs(1)
    assert env.state() is AlertState.OK and len(env.types()) == 2


def test_clock_regression_does_not_fire_a_pending_alert_early_or_twice():
    env = Env()
    env.rule(for_d=30)
    env.obs(50)
    env.clock.adv(-100)
    env.obs(50)
    assert env.state() is AlertState.PENDING and env.types() == []
    env.clock.t = T0 + timedelta(seconds=31)
    env.obs(50)
    env.clock.adv(-50)
    env.obs(50)
    assert len(env.types()) == 1


def test_unusable_clock_refuses_without_changing_state():
    env = Env()
    env.rule()

    class Naive:
        def now(self):
            return datetime(2026, 1, 1)  # noqa: DTZ001

    env.engine._clock = Naive()
    refusal = env.engine.observe(S1, "SRC-1", RuleKind.CURSOR_LAG, 50)
    assert refusal.reason is OpsReason.DEPENDENCY_FAILED
    env.engine._clock = env.clock
    assert env.state() is AlertState.OK and env.types() == []


# ---- delivery ---------------------------------------------------------------------------------------

def test_failed_delivery_keeps_the_event_undelivered_and_retries():
    env = Env()
    env.rule()
    env.obs(50)
    env.sink.fail_next(1)
    out = env.engine.deliver_events(S1, env.sink)
    assert type(out) is AlertDeliveryOutcome and out.reason is OpsReason.ALERT_DELIVERY_FAILED
    assert out.delivered_count == 0 and out.remaining_count == 1 and POISON not in repr(out)
    assert env.sink.sent == [] and len(env.engine.undelivered(S1)) == 1
    record = env.engine.records(S1)[0]
    assert record.delivered is False and record.attempts == 1
    ok = env.engine.deliver_events(S1, env.sink)
    assert ok.reason is None and ok.delivered_count == 1 and ok.remaining_count == 0
    assert [e.event_type for e in env.sink.sent] == [EventType.FIRED] and env.engine.undelivered(S1) == ()
    again = env.engine.deliver_events(S1, env.sink)
    assert again.delivered_count == 0 and len(env.sink.sent) == 1 and env.sink.attempts == 2


@pytest.mark.parametrize("mode", ["raise", "false", "malformed"])
def test_every_sink_failure_mode_is_a_visible_delivery_failure(mode):
    env = Env()
    env.rule()
    env.obs(50)
    env.sink.fail_next(1, mode)
    out = env.engine.deliver_events(S1, env.sink)
    assert out.reason is OpsReason.ALERT_DELIVERY_FAILED and env.sink.sent == []
    assert env.engine.records(S1)[0].delivered is False


def test_delivery_order_is_preserved_and_stops_at_the_first_failure():
    env = Env()
    env.rule()
    env.obs(50)
    env.obs(0, adv=1)
    env.sink.fail_next(1)
    out = env.engine.deliver_events(S1, env.sink)
    assert out.remaining_count == 2 and env.sink.sent == []  # RECOVERED was not sent ahead of FIRED
    out = env.engine.deliver_events(S1, env.sink)
    assert [e.event_type for e in env.sink.sent] == [EventType.FIRED, EventType.RECOVERED] and out.reason is None


def test_hostile_sink_and_scope_for_delivery():
    env = Env()
    env.rule()
    env.obs(50)
    for bad in (None, 5, object(), "sink"):
        assert env.engine.deliver_events(S1, bad).reason is OpsReason.INPUT_INVALID
    for bad in (None, 5, object(), EvilStr("t1"), object.__new__(OpsScope)):
        assert type(env.engine.deliver_events(bad, env.sink)) is OpsRefusal
    stranger = OpsScope("t1", "c1", "stranger")
    assert env.engine.deliver_events(stranger, env.sink).reason is OpsReason.NOT_ENTITLED
    assert env.sink.attempts == 0


def test_concurrent_delivery_sends_each_event_exactly_once():
    env = Env()
    env.rule()
    env.obs(50)
    env.obs(0, adv=1)

    def work():
        for _ in range(20):
            env.engine.deliver_events(S1, env.sink)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [e.event_type for e in env.sink.sent] == [EventType.FIRED, EventType.RECOVERED]
    assert env.engine.undelivered(S1) == ()


def test_concurrent_observation_fires_once():
    env = Env()
    env.rule(for_d=0)

    def work():
        for _ in range(30):
            env.engine.observe(S1, "SRC-1", RuleKind.CURSOR_LAG, 50)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert env.types() == [(EventType.FIRED, OpsReason.ALERT_FIRED)] and env.state() is AlertState.FIRING


# ---- per tenant -------------------------------------------------------------------------------------

def test_tenants_have_isolated_state_events_and_delivery():
    env = Env()
    env.rule(scope=S1, subject="SRC-1")
    env.rule(scope=S2, subject="SRC-2")
    env.obs(50, scope=S1, subject="SRC-1")
    assert env.state(scope=S2, subject="SRC-2") is AlertState.OK and env.types(S2) == []
    env.obs(0, scope=S2, subject="SRC-2", adv=1)  # tenant 2 samples cannot resolve tenant 1's alert
    assert env.state() is AlertState.FIRING
    env.obs(50, scope=S2, subject="SRC-2", adv=1)
    assert len(env.types(S1)) == 1 and len(env.types(S2)) == 1
    sink2 = FakeAlertSink()
    env.engine.deliver_events(S2, sink2)
    assert len(sink2.sent) == 1 and sink2.sent[0].tenant_id == "t2" and len(env.engine.undelivered(S1)) == 1
    assert "t1" not in repr(env.engine.events(S2)) and "t2" not in repr(env.engine.events(S1))


def test_one_tenants_failing_sink_does_not_stop_the_other_tenant():
    env = Env()
    env.rule(scope=S1, subject="SRC-1")
    env.rule(scope=S2, subject="SRC-2")
    env.obs(50, scope=S1, subject="SRC-1")
    env.obs(50, scope=S2, subject="SRC-2")
    bad, good = FakeAlertSink(), FakeAlertSink()
    bad.fail_next(5)
    assert env.engine.deliver_events(S1, bad).reason is OpsReason.ALERT_DELIVERY_FAILED
    assert env.engine.deliver_events(S2, good).reason is None and len(good.sent) == 1


def test_foreign_and_unknown_subject_are_identical_and_touch_no_state():
    foreign, unknown = Env(), Env()
    foreign.rule()
    unknown.rule()
    foreign.ports.log.clear()
    unknown.ports.log.clear()
    f = foreign.engine.observe(S1, "SRC-2", RuleKind.CURSOR_LAG, 50)  # SRC-2 belongs to tenant 2
    u = unknown.engine.observe(S1, "SRC-NOPE", RuleKind.CURSOR_LAG, 50)
    assert f.reason is u.reason is OpsReason.NOT_FOUND and foreign.ports.log == unknown.ports.log
    assert [c[0] for c in foreign.ports.log] == ["entitled", "owns"]
    assert foreign.types() == [] and foreign.state() is AlertState.OK


def test_unentitled_actor_learns_nothing():
    env = Env()
    env.rule()
    env.ports.log.clear()
    out = env.engine.observe(OpsScope("t1", "c1", "stranger"), "SRC-1", RuleKind.CURSOR_LAG, 50)
    assert out.reason is OpsReason.NOT_ENTITLED and [c[0] for c in env.ports.log] == ["entitled"]


def test_rule_and_event_quotas_are_per_tenant_and_never_evict():
    env = Env(rules_per_tenant=1, events_per_tenant=1)
    env.rule(scope=S1, subject="SRC-1")
    second = env.engine.set_rule(S1, "SRC-1", AlertRule(RuleKind.OUTBOX_LAG, 10, 0, 2, 0))
    assert second.reason is OpsReason.QUOTA_EXCEEDED
    dup = env.engine.set_rule(S1, "SRC-1", AlertRule(RuleKind.CURSOR_LAG, 99, 0, 2, 0))
    assert dup.reason is OpsReason.QUOTA_EXCEEDED or dup.reason is OpsReason.DUPLICATE_SUPPRESSED
    env.rule(scope=S2, subject="SRC-2")  # tenant 2 unaffected
    env.obs(50)
    refused = env.obs(0, adv=1)  # RECOVERED has no room: refused, state unchanged, FIRED not evicted
    assert refused.reason is OpsReason.QUOTA_EXCEEDED and env.state() is AlertState.FIRING
    assert len(env.types()) == 1
    env.obs(50, scope=S2, subject="SRC-2")
    assert len(env.types(S2)) == 1


def test_reregistering_a_rule_is_duplicate_suppressed_and_keeps_the_original():
    env = Env()
    env.rule(threshold=10)
    again = env.engine.set_rule(S1, "SRC-1", AlertRule(RuleKind.CURSOR_LAG, 1000, 0, 2, 0))
    assert again.reason is OpsReason.DUPLICATE_SUPPRESSED
    env.obs(10)
    assert env.state() is AlertState.FIRING


def test_unknown_rule_is_not_found():
    env = Env()
    assert env.obs(5).reason is OpsReason.NOT_FOUND
    assert env.engine.status(S1, "SRC-1", RuleKind.CURSOR_LAG).reason is OpsReason.NOT_FOUND
    assert env.engine.tick(S1, "SRC-1", RuleKind.CURSOR_LAG).reason is OpsReason.NOT_FOUND


# ---- construction and hostile input -----------------------------------------------------------------

@pytest.mark.parametrize("args", [
    (RuleKind.CURSOR_LAG, Decimal("NaN"), 0, 1, 0), (RuleKind.CURSOR_LAG, Decimal("Infinity"), 0, 1, 0),
    (RuleKind.CURSOR_LAG, -5, 0, 1, 0), (RuleKind.CURSOR_LAG, 0, 0, 0, 0), (RuleKind.CURSOR_LAG, 10, 0, 10, 0),
    (RuleKind.CURSOR_LAG, 10, 0, 11, 0), (RuleKind.CURSOR_LAG, 10, 0, -1, 0),
    (RuleKind.CURSOR_LAG, 10, 0, Decimal("NaN"), 0), (RuleKind.CURSOR_LAG, True, 0, 0, 0),
    (RuleKind.CURSOR_LAG, 10.0, 0, 1, 0), (RuleKind.CURSOR_LAG, "10", 0, 1, 0), (RuleKind.CURSOR_LAG, None, 0, 1, 0),
    (RuleKind.CURSOR_LAG, EvilDecimal("10"), 0, 1, 0), (RuleKind.CURSOR_LAG, EvilInt(10), 0, 1, 0),
    (RuleKind.CURSOR_LAG, 10, -1, 1, 0), (RuleKind.CURSOR_LAG, 10, True, 1, 0), (RuleKind.CURSOR_LAG, 10, 0, 1, -1),
    (RuleKind.CURSOR_LAG, 10, 10**12, 1, 0), (RuleKind.CURSOR_LAG, 10, 0, 1, 10**12),
    (RuleKind.FAILURE_RATIO, Decimal("1.5"), 0, 0, 0), ("CURSOR_LAG", 10, 0, 1, 0), (None, 10, 0, 1, 0),
    (RuleKind.CURSOR_LAG, Decimal("1E+500"), 0, 1, 0),
])
def test_invalid_thresholds_are_refused_at_construction(args):
    with pytest.raises(ValueError):
        AlertRule(*args)


@pytest.mark.parametrize("no_data", [0, -1, True, 1.5, None, 10**12])
def test_invalid_no_data_window_refused(no_data):
    with pytest.raises(ValueError):
        AlertRule(RuleKind.CURSOR_LAG, 10, 0, 1, 0, no_data)


def test_rule_normalises_numbers_to_decimal_and_is_frozen():
    rule = AlertRule(RuleKind.CURSOR_LAG, 10, 0, 1, 0)
    assert type(rule.threshold) is Decimal and rule.threshold == 10
    with pytest.raises(AttributeError):
        rule.threshold = Decimal(1)  # type: ignore[misc]


def test_engine_construction_refuses_bad_config():
    p = SpyPorts()
    for kwargs in ({"rules_per_tenant": 0}, {"events_per_tenant": True}, {"rules_per_tenant": 1.5}):
        with pytest.raises(ValueError):
            AlertEngine(p, p, FakeCorrelationSource(), ManualClock(), **kwargs)
    with pytest.raises(ValueError):
        AlertEngine(p, p, FakeCorrelationSource(), object())


@pytest.mark.parametrize("bad", [None, True, False, -1, 1.0, "5", Decimal("NaN"), Decimal("Infinity"),
                                 Decimal(-1), EvilInt(5), EvilDecimal("5"), 2**70, object(), [5]])
def test_hostile_sample_values_are_refused_and_change_nothing(bad):
    env = Env()
    env.rule(for_d=0)
    refusal = env.engine.observe(S1, "SRC-1", RuleKind.CURSOR_LAG, bad)
    assert type(refusal) is OpsRefusal and refusal.reason is OpsReason.INPUT_INVALID
    assert env.state() is AlertState.OK and env.types() == []


def test_hostile_scope_subject_kind_never_raise():
    env = Env()
    env.rule()
    for bad in (None, 5, b"x", EvilStr("SRC-1"), "", "x" * 10_000, "a\x00b", object()):
        assert type(env.engine.observe(S1, bad, RuleKind.CURSOR_LAG, 5)) is OpsRefusal
        assert type(env.engine.observe(bad, "SRC-1", RuleKind.CURSOR_LAG, 5)) is OpsRefusal
        assert type(env.engine.observe(S1, "SRC-1", bad, 5)) is OpsRefusal
        assert type(env.engine.tick(S1, bad, RuleKind.CURSOR_LAG)) is OpsRefusal
        assert type(env.engine.status(S1, bad, RuleKind.CURSOR_LAG)) is OpsRefusal
        assert type(env.engine.set_rule(S1, bad, AlertRule(RuleKind.OUTBOX_LAG, 5, 0, 1, 0))) is OpsRefusal
        assert type(env.engine.set_rule(S1, "SRC-1", bad)) is OpsRefusal
        assert type(env.engine.records(bad)) is OpsRefusal
    forged_rule = object.__new__(AlertRule)
    assert env.engine.set_rule(S1, "SRC-1", forged_rule).reason is OpsReason.INPUT_INVALID
    assert env.engine.observe(object.__new__(OpsScope), "SRC-1", RuleKind.CURSOR_LAG, 5).reason \
        is OpsReason.INPUT_INVALID
    assert env.state() is AlertState.OK


def test_mutating_the_callers_rule_inputs_after_registration_changes_nothing():
    env = Env()
    rule = AlertRule(RuleKind.CURSOR_LAG, 10, 0, 2, 0)
    assert env.engine.set_rule(S1, "SRC-1", rule) is None
    object.__setattr__(rule, "threshold", Decimal(10_000))  # forced mutation of the caller's copy
    env.obs(10)
    assert env.state() is AlertState.FIRING


def test_value_types_validate_and_redact():
    now = T0
    event = AlertEvent("e" * 32, "t1", "SRC-1", RuleKind.CURSOR_LAG, EventType.FIRED, OpsReason.ALERT_FIRED, 1, now)
    assert repr(event) == "AlertEvent(<redacted>)" and event.authority == "EVALUATION_ONLY"
    bad_args = [
        ("e", "t1", "SRC-1", RuleKind.CURSOR_LAG, EventType.FIRED, OpsReason.ALERT_RECOVERED, 1, now),
        ("e", "t1", "SRC-1", RuleKind.CURSOR_LAG, EventType.RECOVERED, OpsReason.ALERT_FIRED, 1, now),
        ("e", "t1", "SRC-1", RuleKind.CURSOR_LAG, EventType.FIRED, OpsReason.ALERT_FIRED, 0, now),
        ("e", "t1", "SRC-1", RuleKind.CURSOR_LAG, EventType.FIRED, OpsReason.ALERT_FIRED, 1, datetime(2026, 1, 1)),  # noqa: DTZ001
        ("", "t1", "SRC-1", RuleKind.CURSOR_LAG, EventType.FIRED, OpsReason.ALERT_FIRED, 1, now),
    ]
    for args in bad_args:
        with pytest.raises(ValueError):
            AlertEvent(*args)
    with pytest.raises(ValueError):
        AlertDeliveryOutcome(0, 0, OpsReason.ALERT_DELIVERY_FAILED, "CORR-000001")
    with pytest.raises(ValueError):
        AlertDeliveryOutcome(0, 1, None, "CORR-000001")
    assert AlertStatus(AlertState.OK, 0, False).authority == "EVALUATION_ONLY"
    assert not {"passed", "verdict", "sent"} & set(AlertDeliveryOutcome.__dataclass_fields__)
    assert repr(Env().engine) == "AlertEngine(<redacted>)"


def test_event_ids_are_deterministic_and_stable_for_sink_dedup():
    ids = []
    for _ in range(2):
        env = Env()
        env.rule()
        env.obs(50)
        ids.append([e.event_id for e in env.engine.events(S1)])
    assert ids[0] == ids[1] and len(ids[0][0]) == 32


# ---- import boundary --------------------------------------------------------------------------------

_FORBIDDEN_ROOTS = {
    "httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket", "ssl", "subprocess", "sqlite3",
    "psycopg", "psycopg2", "asyncpg", "sqlalchemy", "os", "pathlib", "random", "secrets", "time", "shutil",
    "tempfile", "io", "ctypes", "asyncio", "multiprocessing", "concurrent", "fastapi", "flask", "starlette",
    "threading", "contextvars",
}
_FORBIDDEN_CALLS = {"delete", "remove", "unlink", "rmtree", "truncate", "drop", "open", "eval", "exec", "compile"}


def test_module_imports_nothing_forbidden_and_has_no_delete_calls():
    import sys
    path = _SRC / "alert_rules.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    seen = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            level = 0 if isinstance(node, ast.Import) else node.level
            for module in names:
                seen += 1
                root = module.split(".")[0]
                assert root not in _FORBIDDEN_ROOTS, module
                assert not any(s in module.lower() for s in ("drive_http", "onec", "pdcc", "release1", "release_1"))
                if level:
                    assert level == 1, module
                elif root == "business_ai_gateway":
                    assert module.startswith("business_ai_gateway.phase2")
                else:
                    assert root in sys.stdlib_module_names, module
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            assert name not in _FORBIDDEN_CALLS, (name, node.lineno)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"environ", "getenv", "sleep", "utcnow"}, node.lineno
    assert seen


def test_boundary_scan_is_not_vacuous():
    bad = ast.parse("import threading\nx.unlink()\n")
    assert any(isinstance(n, ast.Import) and n.names[0].name in _FORBIDDEN_ROOTS for n in ast.walk(bad))
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in _FORBIDDEN_CALLS for n in ast.walk(bad))
