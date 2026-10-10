"""S9 E2 / TC131: at-least-once delivery, digest de-dup, quarantine, fence, backoff, per-tenant bounds."""
import ast
import hashlib
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from business_ai_gateway.phase2.delivery_replay import (
    Claim,
    DeliveryEvent,
    DeliveryOutcome,
    DeliveryStatus,
    FakeDeliverySink,
    RecordStatus,
    RegisterOutcome,
    ReplayPlanner,
    SinkKind,
    SinkResponse,
    _with,
    deliver_pending,
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
POISON = FakeDeliverySink.POISON
T0 = datetime(2026, 3, 1, tzinfo=UTC)
S1 = OpsScope("t1", "c1", "a1")
S2 = OpsScope("t2", "c2", "a2")
S1B = OpsScope("t1", "c1b", "a1b")  # a second company of tenant t1


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


def dg(name):
    return hashlib.sha256(name.encode()).hexdigest()


def ev(seq, conn="CON-1", eid=None, digest=None):
    eid = eid or f"EVT-{conn}-{seq}"
    return DeliveryEvent(conn, seq, eid, digest or dg(eid))


class _Switch:
    """The sink BOUND to the planner: forwards to env.sink (or a per-call override used by fault tests)."""

    def __init__(self, env):
        self.env = env
        self.override = None

    def publish(self, *args):
        return (self.override or self.env.sink).publish(*args)


class Env:
    def __init__(self, sink=None, **kwargs):
        self.ports = SpyPorts()
        for t, c, a, s in (("t1", "c1", "a1", "SRC-1"), ("t2", "c2", "a2", "SRC-2"),
                           ("t1", "c1b", "a1b", "SRC-1B"), ("t1", "c1", "a1", "SRC-1X")):
            self.ports.ent.grant(t, a, c)
            self.ports.owner.add(t, c, "source_id", s)
        self.clock = ManualClock()
        self.sink = sink or FakeDeliverySink()
        self.switch = _Switch(self)
        self.planner = ReplayPlanner(self.ports, self.ports, FakeCorrelationSource(), self.clock,
                                     sinks={"t1": self.switch, "t2": self.switch}, **kwargs)

    def reg(self, events, scope=S1, source="SRC-1"):
        return self.planner.register(scope, source, events)

    def run(self, worker="W1", scope=S1, source="SRC-1", conn="CON-1", claim=None, sink="DEFAULT"):
        self.switch.override = None if sink == "DEFAULT" else sink
        try:
            return self.planner.deliver_pending(scope, worker, source, conn, claim)
        finally:
            self.switch.override = None

    def drain(self, workers=("W1",), conn="CON-1", scope=S1, source="SRC-1", limit=60):
        outs = []
        for i in range(limit):
            out = self.run(workers[i % len(workers)], scope, source, conn)
            outs.append(out)
            if out.status in (DeliveryStatus.COMPLETE, DeliveryStatus.FAILED_FINAL):
                break
            self.clock.adv(10)
        return outs

    def published(self, tenant="t1", conn="CON-1"):
        return [p[3] for p in self.sink.published if p[0] == tenant and p[2] == conn]


# ---- registration, replay, conflict -----------------------------------------------------------------

def test_register_replay_with_same_digest_publishes_nothing_more():
    env = Env()
    out = env.reg([ev(1), ev(2)])
    assert type(out) is RegisterOutcome and (out.accepted, out.replayed, out.conflicts) == (2, 0, 0)
    assert env.drain()[-1].status is DeliveryStatus.COMPLETE and len(env.sink.published) == 2
    again = env.reg([ev(1), ev(2)])
    assert (again.accepted, again.replayed, again.reason) == (0, 2, None)
    done = env.run()
    assert done.status is DeliveryStatus.COMPLETE and done.delivered_count == 0
    assert len(env.sink.published) == 2 and len(env.sink.calls) == 2


def test_same_id_with_other_digest_is_quarantined_and_never_overwrites():
    env = Env()
    env.reg([ev(1, eid="EVT-A")])
    out = env.reg([ev(1, eid="EVT-A", digest=dg("tampered"))])
    assert out.conflicts == 1 and out.accepted == 0 and out.reason is OpsReason.EVENT_DIGEST_CONFLICT
    assert env.planner.quarantine_count(S1) == 1
    env.drain()
    assert env.sink.published == [("t1", "SRC-1", "CON-1", "EVT-A", dg("EVT-A"))]  # the ORIGINAL digest
    env.reg([ev(1, eid="EVT-A", digest=dg("tampered"))])  # replaying the conflict again is still refused
    assert env.sink.published[0][4] == dg("EVT-A") and env.planner.quarantine_count(S1) == 1
    assert env.planner.quarantine_count(S2) == 0


def test_same_event_id_on_another_connection_is_a_different_event():
    env = Env()
    out = env.reg([ev(1, "CON-1", eid="EVT-X"), ev(1, "CON-2", eid="EVT-X")])
    assert out.accepted == 2 and out.conflicts == 0


# ---- scripted faults: 429, network, duplicate ack ---------------------------------------------------

def test_429_network_failure_lost_ack_then_success_publishes_each_event_exactly_once_in_order():
    env = Env(base_delay=1, max_attempts=10)
    env.sink.script("t1", [SinkKind.RATE_LIMITED, SinkKind.NETWORK_FAILURE, "LOST_ACK"], retry_after=5)
    env.reg([ev(i) for i in range(1, 6)])
    outs = env.drain(("W1", "W2"))
    assert outs[-1].status is DeliveryStatus.COMPLETE
    assert env.published() == [f"EVT-CON-1-{i}" for i in range(1, 6)]  # none lost, none twice, in order
    assert sum(o.duplicate_ack_count for o in outs) == 1  # the lost ack came back as a duplicate ack
    assert [r.status for r in env.planner.records(S1, "SRC-1", "CON-1")] == [RecordStatus.DELIVERED] * 5
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 5


def test_retry_after_is_honored_on_the_clock_and_bounded():
    env = Env(base_delay=1, max_delay=300)
    env.sink.script("t1", [SinkKind.RATE_LIMITED], retry_after=40)
    env.reg([ev(1)])
    first = env.run()
    assert first.status is DeliveryStatus.WAITING and first.reason is OpsReason.RATE_LIMITED
    assert first.next_retry_at == T0 + timedelta(seconds=40) and first.delivered_count == 0
    calls = len(env.sink.calls)
    env.clock.adv(39)
    assert env.run().status is DeliveryStatus.WAITING and len(env.sink.calls) == calls  # not even asked
    env.clock.adv(1)
    assert env.run().status is DeliveryStatus.COMPLETE and env.published() == ["EVT-CON-1-1"]


class _FixedSink:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def publish(self, *args):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_retry_after_larger_than_the_cap_is_clamped():
    env = Env(max_delay=300)
    env.reg([ev(1)])
    out = env.run(sink=_FixedSink(SinkResponse(SinkKind.RATE_LIMITED, 3600)))
    assert out.next_retry_at == T0 + timedelta(seconds=300)


@pytest.mark.parametrize("response", [
    SinkResponse("DELIVERED", 0), None, "DELIVERED", object(), object.__new__(SinkResponse), RuntimeError(POISON),
])
def test_malformed_or_hostile_sink_answers_are_a_network_failure_not_a_delivery(response):
    env = Env()
    env.reg([ev(1)])
    out = env.run(sink=_FixedSink(response))
    assert out.status is DeliveryStatus.WAITING and out.delivered_count == 0
    assert out.reason in (OpsReason.NETWORK_FAILURE,) and POISON not in repr(out)
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 0
    assert env.planner.records(S1, "SRC-1", "CON-1")[0].status is RecordStatus.PENDING


def test_backoff_grows_exponentially_through_scheduler_backoff_delay():
    env = Env(base_delay=8, max_delay=3600, max_attempts=10, jitter_source=lambda: 0.0)
    env.sink.script("t1", [SinkKind.NETWORK_FAILURE] * 3)
    env.reg([ev(1)])
    delays = []
    for _ in range(3):
        out = env.run()
        delays.append((out.next_retry_at - env.clock.t).total_seconds())
        env.clock.t = out.next_retry_at
    assert delays == [4.0, 8.0, 16.0]


def test_attempts_exhaust_to_explicit_final_failure_and_the_connection_is_parked():
    env = Env(max_attempts=3, base_delay=1)
    env.sink.script("t1", [SinkKind.NETWORK_FAILURE] * 3)
    env.reg([ev(1), ev(2)])
    outs = env.drain()
    assert outs[-1].status is DeliveryStatus.FAILED_FINAL and outs[-1].reason is OpsReason.DELIVERY_FAILED_FINAL
    calls = len(env.sink.calls)
    again = env.run()
    assert again.status is DeliveryStatus.FAILED_FINAL and len(env.sink.calls) == calls  # no infinite retry
    recs = env.planner.records(S1, "SRC-1", "CON-1")
    assert [r.status for r in recs] == [RecordStatus.FAILED, RecordStatus.PENDING] and recs[0].attempts == 3
    assert env.sink.published == [] and env.planner.cursor(S1, "SRC-1", "CON-1") == 0  # order never skipped


def test_cursor_never_advances_past_an_undelivered_event():
    env = Env(max_attempts=5)
    env.sink.script("t1", [None, SinkKind.RATE_LIMITED])  # first healthy, second rate limited
    env.reg([ev(1), ev(2), ev(3)])
    out = env.run()
    assert out.status is DeliveryStatus.WAITING and out.cursor_seq == 1 and out.delivered_count == 1
    assert env.published() == ["EVT-CON-1-1"] and env.planner.cursor(S1, "SRC-1", "CON-1") == 1
    assert env.planner.records(S1, "SRC-1", "CON-1")[2].status is RecordStatus.PENDING


def test_a_gap_in_registered_sequence_numbers_does_not_block_the_cursor_over_registered_events():
    env = Env()
    env.reg([ev(1), ev(5)])
    env.drain()
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 5


# ---- claims and the fence ---------------------------------------------------------------------------

def test_a_live_claim_of_another_worker_blocks_delivery_without_a_sink_call():
    env = Env(lease_seconds=60)
    env.reg([ev(1)])
    claim = env.planner.claim(S1, "W1", "SRC-1", "CON-1")
    assert type(claim) is Claim and claim.generation == 1
    held = env.run("W2")
    assert held.status is DeliveryStatus.CLAIM_HELD and held.reason is OpsReason.DUPLICATE_SUPPRESSED
    assert env.sink.calls == []
    env.clock.adv(61)  # lease expired: W2 may take over with a newer fence
    assert env.run("W2").status is DeliveryStatus.COMPLETE


def test_stale_claim_cannot_publish_or_mark():
    env = Env(lease_seconds=60)
    env.reg([ev(1), ev(2)])
    old = env.planner.claim(S1, "W1", "SRC-1", "CON-1")
    env.clock.adv(61)
    assert env.run("W2").status is DeliveryStatus.COMPLETE
    published = list(env.sink.published)
    calls = len(env.sink.calls)
    stale = env.run("W1", claim=old)
    assert stale.status is DeliveryStatus.COMPLETE or stale.status is DeliveryStatus.STALE
    env2 = Env(lease_seconds=60)
    env2.reg([ev(1)])
    old2 = env2.planner.claim(S1, "W1", "SRC-1", "CON-1")
    env2.clock.adv(61)
    newer = env2.planner.claim(S1, "W2", "SRC-1", "CON-1")
    assert newer.generation == old2.generation + 1
    out = env2.run("W1", claim=old2)
    assert out.status is DeliveryStatus.STALE and out.reason is OpsReason.STALE_CLAIM
    assert env2.sink.calls == [] and env2.planner.records(S1, "SRC-1", "CON-1")[0].status is RecordStatus.PENDING
    assert env.sink.published == published and len(env.sink.calls) == calls


def test_a_worker_that_goes_stale_mid_publish_cannot_mark_and_the_sink_sees_one_publication():
    state = {"inside": False}
    env = Env()

    def hook(tenant, source, connection, event_id):
        if state["inside"]:
            return
        state["inside"] = True
        env.clock.adv(61)  # W1's lease runs out while its publish is in flight
        assert env.run("W2").status is DeliveryStatus.COMPLETE

    env.sink = FakeDeliverySink(on_publish=hook)
    env.reg([ev(1)])
    out = env.run("W1")
    assert out.status is DeliveryStatus.STALE and out.reason is OpsReason.STALE_CLAIM
    assert env.published() == ["EVT-CON-1-1"] and len(env.sink.published) == 1
    rec = env.planner.records(S1, "SRC-1", "CON-1")[0]
    assert rec.status is RecordStatus.DELIVERED and env.planner.cursor(S1, "SRC-1", "CON-1") == 1


def test_forged_or_foreign_claim_objects_are_refused():
    env = Env()
    env.reg([ev(1)])
    for bad in (object.__new__(Claim), "claim", 5, object()):
        assert env.run(claim=bad).status is DeliveryStatus.REFUSED
    forged = Claim("W9", 99)  # well-formed but never issued: the fence rejects it
    assert env.run("W9", claim=forged).status is DeliveryStatus.STALE
    assert env.sink.calls == []


def test_concurrent_threads_publish_every_event_exactly_once_in_order():
    env = Env()
    events = [ev(i, "CON-1") for i in range(1, 21)] + [ev(i, "CON-2") for i in range(1, 21)]
    env.reg(events)

    def work(name):
        for _ in range(300):
            for conn in ("CON-1", "CON-2"):
                env.run(name, conn=conn)

    threads = [threading.Thread(target=work, args=(f"W{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for conn in ("CON-1", "CON-2"):
        env.drain(conn=conn)
    assert len(env.sink.published) == 40 and len({p[:4] for p in env.sink.published}) == 40
    for conn in ("CON-1", "CON-2"):
        assert env.published(conn=conn) == [f"EVT-{conn}-{i}" for i in range(1, 21)]  # per-connection order
        assert env.planner.cursor(S1, "SRC-1", conn) == 20


# ---- per tenant -------------------------------------------------------------------------------------

def test_tenant_a_429_storm_does_not_delay_tenant_b():
    env = Env(max_attempts=50)
    env.sink.script("t1", [SinkKind.RATE_LIMITED] * 30, retry_after=200)
    env.reg([ev(1)], S1, "SRC-1")
    env.reg([ev(1)], S2, "SRC-2")
    a = env.run("W1", S1, "SRC-1")
    b = env.run("W1", S2, "SRC-2")
    assert a.status is DeliveryStatus.WAITING and b.status is DeliveryStatus.COMPLETE
    assert env.published("t2") == ["EVT-CON-1-1"] and env.published("t1") == []
    assert env.planner.cursor(S2, "SRC-2", "CON-1") == 1 and env.planner.cursor(S1, "SRC-1", "CON-1") == 0


def test_dedup_store_is_bounded_per_tenant_with_explicit_refusal_and_no_eviction():
    env = Env(per_tenant_cap=2)
    out = env.reg([ev(1), ev(2), ev(3)])
    assert (out.accepted, out.quota_refused, out.reason) == (2, 1, OpsReason.QUOTA_EXCEEDED)
    assert "t2" not in repr(out)
    b = env.reg([ev(1), ev(2)], S2, "SRC-2")  # tenant 2 has its own full budget
    assert (b.accepted, b.quota_refused, b.reason) == (2, 0, None)
    env.drain()
    assert env.published() == ["EVT-CON-1-1", "EVT-CON-1-2"]  # undelivered records were never evicted
    late = env.reg([ev(3)])
    assert late.quota_refused == 1  # delivered records keep their dedup slot too


def test_foreign_and_unknown_source_are_identical_for_every_operation():
    foreign, unknown = Env(), Env()
    for env in (foreign, unknown):
        env.reg([ev(1)])
        env.ports.log.clear()
    probes = []
    for env, source in ((foreign, "SRC-2"), (unknown, "SRC-NOPE")):  # SRC-2 belongs to tenant 2
        outs = (env.planner.register(S1, source, [ev(1)]), env.planner.claim(S1, "W1", source, "CON-1"),
                env.planner.cursor(S1, source, "CON-1"), env.planner.records(S1, source, "CON-1"),
                env.run(source=source))
        probes.append(outs)
    for f, u in zip(*probes, strict=True):
        fr = f.reason if type(f) is OpsRefusal else (f.status, f.reason)
        ur = u.reason if type(u) is OpsRefusal else (u.status, u.reason)
        assert fr == ur and (OpsReason.NOT_FOUND in (fr, fr[1] if isinstance(fr, tuple) else fr))
    assert foreign.ports.log == unknown.ports.log
    assert foreign.sink.calls == [] and unknown.sink.calls == []


def test_unentitled_actor_gets_nothing_and_no_ownership_question_is_asked():
    env = Env()
    env.reg([ev(1)])
    env.ports.log.clear()
    stranger = OpsScope("t1", "c1", "stranger")
    out = env.run(scope=stranger)
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.NOT_ENTITLED
    assert [c[0] for c in env.ports.log] == ["entitled"] and env.sink.calls == []


# ---- hostile input ----------------------------------------------------------------------------------

def test_hostile_events_and_arguments_never_raise_and_change_nothing():
    env = Env()
    class MyList(list):
        pass

    bad_batches = [None, 5, "x", [None], [object()], [object.__new__(DeliveryEvent)], MyList([ev(1)]),
                   [ev(i) for i in range(1, 1002)], {"a": 1}]
    for batch in bad_batches:
        out = env.reg(batch)
        assert type(out) is OpsRefusal and out.reason is OpsReason.INPUT_INVALID, batch
    for bad in (None, 5, b"x", EvilStr("SRC-1"), "", "x" * 10_000, "a\x00b", object()):
        assert type(env.planner.register(S1, bad, [ev(1)])) is OpsRefusal
        assert type(env.planner.register(bad, "SRC-1", [ev(1)])) is OpsRefusal
        assert type(env.planner.cursor(S1, bad, "CON-1")) is OpsRefusal
        assert type(env.planner.cursor(S1, "SRC-1", bad)) is OpsRefusal
        assert type(env.planner.records(S1, "SRC-1", bad)) is OpsRefusal
        assert type(env.planner.claim(S1, bad, "SRC-1", "CON-1")) is OpsRefusal
        assert env.run(worker=bad).status is DeliveryStatus.REFUSED
        assert env.run(conn=bad).status is DeliveryStatus.REFUSED
    assert env.run(scope=object.__new__(OpsScope)).status is DeliveryStatus.REFUSED
    assert env.planner.records(S1, "SRC-1", "CON-1") == () and env.sink.calls == []


@pytest.mark.parametrize("args", [
    ("CON-1", 0, "E", dg("E")), ("CON-1", -1, "E", dg("E")), ("CON-1", True, "E", dg("E")),
    ("CON-1", 1.0, "E", dg("E")), ("CON-1", 1, "", dg("E")), ("CON-1", 1, "E", "abc"), ("CON-1", 1, "E", "A" * 64),
    ("CON-1", 1, EvilStr("E"), dg("E")), ("", 1, "E", dg("E")), (None, 1, "E", dg("E")),
    ("CON-1", 1, "E\x00", dg("E")), ("CON-1", 1, "x" * 500, dg("E")),
])
def test_delivery_event_construction_refuses_malformed_fields(args):
    with pytest.raises(ValueError):
        DeliveryEvent(*args)


def test_planner_construction_refuses_bad_config():
    p = SpyPorts()
    base = (p, p, FakeCorrelationSource(), ManualClock())
    for kwargs in ({"per_tenant_cap": 0}, {"max_attempts": 0}, {"max_attempts": True}, {"base_delay": 0},
                   {"max_delay": 0}, {"base_delay": 10, "max_delay": 5}, {"lease_seconds": 0},
                   {"jitter_source": 5}, {"per_tenant_cap": 1.5}):
        with pytest.raises(ValueError):
            ReplayPlanner(*base, **kwargs)
    with pytest.raises(ValueError):
        ReplayPlanner(p, p, FakeCorrelationSource(), object())


def test_unusable_clock_refuses_and_publishes_nothing():
    env = Env()
    env.reg([ev(1)])

    class Naive:
        def now(self):
            return datetime(2026, 1, 1)  # noqa: DTZ001

    env.planner._clock = Naive()
    out = env.run()
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.DEPENDENCY_FAILED
    assert env.sink.calls == []


def test_outcome_values_validate_and_carry_no_verdict():
    corr = "CORR-000001"
    assert DeliveryOutcome(DeliveryStatus.COMPLETE, None, 1, 0, 3, None, corr).authority == "EVALUATION_ONLY"
    for args in ((DeliveryStatus.COMPLETE, OpsReason.NOT_FOUND, 0, 0, 0, None, corr),
                 (DeliveryStatus.STALE, None, 0, 0, 0, None, corr),
                 (DeliveryStatus.FAILED_FINAL, OpsReason.RATE_LIMITED, 0, 0, 0, None, corr),
                 ("COMPLETE", None, 0, 0, 0, None, corr), (DeliveryStatus.COMPLETE, None, True, 0, 0, None, corr),
                 (DeliveryStatus.COMPLETE, None, 0, 0, 0, datetime(2026, 1, 1), corr),  # noqa: DTZ001
                 (DeliveryStatus.COMPLETE, None, 0, 0, 0, None, "")):
        with pytest.raises(ValueError):
            DeliveryOutcome(*args)
    with pytest.raises(ValueError):
        RegisterOutcome(0, 0, 1, 0, None, corr)
    assert not {"passed", "verdict", "delivered_ok"} & set(DeliveryOutcome.__dataclass_fields__)
    assert repr(ev(1)) == "DeliveryEvent(<redacted>)" and repr(Claim("W1", 1)) == "Claim(<redacted>)"


def test_module_function_requires_an_exact_planner():
    env = Env()
    env.reg([ev(1)])
    assert type(deliver_pending(object(), S1, "W1", "SRC-1", "CON-1")) is OpsRefusal
    assert deliver_pending(env.planner, S1, "W1", "SRC-1", "CON-1").status is DeliveryStatus.COMPLETE


def test_sink_exception_text_never_reaches_any_output():
    env = Env()
    env.sink.script("t1", ["RAISE"])
    env.reg([ev(1)])
    out = env.run()
    assert out.reason is OpsReason.NETWORK_FAILURE
    blob = repr(out) + repr(env.planner.records(S1, "SRC-1", "CON-1")) + repr(env.planner)
    assert POISON not in blob and "ConnectionError" not in blob


# ---- S9 review fix batch ----------------------------------------------------------------------------

def test_two_sources_with_the_same_connection_id_stay_fully_separate():  # B1
    env = Env()
    a = env.reg([ev(1, eid="EVT-SAME"), ev(2, eid="EVT-A2")], S1, "SRC-1")
    x = env.reg([ev(1, eid="EVT-SAME", digest=dg("other-content")), ev(2, eid="EVT-X2")], S1, "SRC-1X")  # same company
    b = env.reg([ev(1, eid="EVT-SAME", digest=dg("third-content")), ev(2, eid="EVT-B2")], S1B, "SRC-1B")  # other company
    for out in (a, x, b):
        assert (out.accepted, out.replayed, out.conflicts, out.reason) == (2, 0, 0, None)
    assert env.planner.quarantine_count(S1) == 0
    assert [r.event_id for r in env.planner.records(S1, "SRC-1", "CON-1")] == ["EVT-SAME", "EVT-A2"]
    assert [r.event_id for r in env.planner.records(S1, "SRC-1X", "CON-1")] == ["EVT-SAME", "EVT-X2"]
    assert [r.event_id for r in env.planner.records(S1B, "SRC-1B", "CON-1")] == ["EVT-SAME", "EVT-B2"]
    out = env.run(scope=S1B, source="SRC-1B")  # only B is delivered
    assert out.status is DeliveryStatus.COMPLETE and out.delivered_count == 2 and out.cursor_seq == 2
    assert {p[1] for p in env.sink.published} == {"SRC-1B"}
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 0 and env.planner.cursor(S1, "SRC-1X", "CON-1") == 0
    assert all(r.status is RecordStatus.PENDING for r in env.planner.records(S1, "SRC-1", "CON-1"))
    assert env.run(source="SRC-1X").delivered_count == 2 and env.planner.cursor(S1, "SRC-1", "CON-1") == 0
    assert env.run(source="SRC-1").delivered_count == 2
    by_source = {(p[1], p[3]): p[4] for p in env.sink.published}
    assert by_source[("SRC-1", "EVT-SAME")] == dg("EVT-SAME")
    assert by_source[("SRC-1X", "EVT-SAME")] == dg("other-content")
    assert by_source[("SRC-1B", "EVT-SAME")] == dg("third-content") and len(env.sink.published) == 6


def test_the_sink_cannot_be_chosen_by_the_caller():  # B2
    import inspect

    assert "sink" not in inspect.signature(ReplayPlanner.deliver_pending).parameters
    assert "sink" not in inspect.signature(deliver_pending).parameters
    swallow = _FixedSink(SinkResponse(SinkKind.DELIVERED))
    env = Env()
    env.reg([ev(1)])
    out = env.planner.deliver_pending(S1, "W1", "SRC-1", "CON-1", swallow)  # lands in the claim slot
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.INPUT_INVALID
    assert swallow.calls == 0 and env.sink.calls == []
    assert env.planner.records(S1, "SRC-1", "CON-1")[0].status is RecordStatus.PENDING


def test_a_tenant_without_a_bound_sink_publishes_nothing_and_binding_is_validated():  # B2
    env = Env()
    env.ports.ent.grant("t3", "a3", "c3")
    env.ports.owner.add("t3", "c3", "source_id", "SRC-3")
    s3 = OpsScope("t3", "c3", "a3")
    assert env.planner.register(s3, "SRC-3", [ev(1)]).accepted == 1
    out = env.planner.deliver_pending(s3, "W1", "SRC-3", "CON-1")
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.DEPENDENCY_FAILED
    p = SpyPorts()
    for bad in ([], {"t1": object()}, {"": env.sink}, {EvilStr("t1"): env.sink}, {"t1": None}):
        with pytest.raises(ValueError):
            ReplayPlanner(p, p, FakeCorrelationSource(), ManualClock(), sinks=bad)
    sinks = {"t1": env.sink}
    planner = ReplayPlanner(env.ports, env.ports, FakeCorrelationSource(), env.clock, sinks=sinks)
    sinks["t1"] = _FixedSink(SinkResponse(SinkKind.DELIVERED))  # later edits of the caller's dict change nothing
    planner.register(S1, "SRC-1", [ev(1)])
    assert planner.deliver_pending(S1, "W1", "SRC-1", "CON-1").delivered_count == 1
    assert len(env.sink.published) == 1


def test_a_record_write_is_a_compare_and_set_on_the_snapshot_that_was_read():  # B3
    env = Env()
    env.reg([ev(1)])
    claim = env.planner.claim(S1, "W1", "SRC-1", "CON-1")
    key = env.planner._rec_key("c1", "SRC-1", "CON-1", "EVT-CON-1-1")
    ckey = env.planner._conn_key("c1", "SRC-1", "CON-1")
    snapshot = env.planner._conn_recs("t1", "c1", "SRC-1", "CON-1")[0][1]
    delivered = _with(snapshot, RecordStatus.DELIVERED, 1, None)
    rolled_back = _with(snapshot, RecordStatus.PENDING, 1, T0 + timedelta(seconds=5))
    assert env.planner._mark("t1", ckey, claim, key, delivered, snapshot) == "ok"
    assert env.planner._mark("t1", ckey, claim, key, rolled_back, snapshot) == "conflict"  # same Claim, stale read
    rec = env.planner.records(S1, "SRC-1", "CON-1")[0]
    assert rec.status is RecordStatus.DELIVERED and rec.attempts == 1  # not rolled back, attempts not under-counted


def test_a_lost_compare_and_set_mid_call_reports_a_retryable_refusal_with_the_real_counts():  # B3 + B6
    env = Env()
    env.reg([ev(1), ev(2), ev(3)])
    claim = env.planner.claim(S1, "W1", "SRC-1", "CON-1")
    key3 = env.planner._rec_key("c1", "SRC-1", "CON-1", "EVT-CON-1-3")
    ckey = env.planner._conn_key("c1", "SRC-1", "CON-1")

    def rival(tenant, source, connection, event_id):
        if event_id == "EVT-CON-1-3":  # a second user of the same Claim finishes event 3 first
            snap = env.planner._conn_recs("t1", "c1", "SRC-1", "CON-1")[2][1]
            assert env.planner._mark("t1", ckey, claim, key3, _with(snap, RecordStatus.DELIVERED, 1, None),
                                     snap) == "ok"

    env.sink = FakeDeliverySink(on_publish=rival)
    out = env.run(claim=claim)
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.INTERNAL_REFUSED
    assert out.delivered_count == 2 and out.cursor_seq == 3  # the real count and the real cursor
    assert [r.status for r in env.planner.records(S1, "SRC-1", "CON-1")] == [RecordStatus.DELIVERED] * 3
    assert [r.attempts for r in env.planner.records(S1, "SRC-1", "CON-1")] == [1, 1, 1]


def test_lock_contention_keeps_real_counts_and_reports_the_unreleased_lease():  # B6
    env = Env()
    env.reg([ev(1), ev(2)])
    ckey = env.planner._conn_key("c1", "SRC-1", "CON-1")

    fired = []

    def hold_lock(tenant, source, connection, event_id):
        if event_id == "EVT-CON-1-2" and not fired:
            fired.append(1)
            assert env.planner._locks.try_acquire("t1", ckey)  # contention starts after event 1 was marked

    env.sink = FakeDeliverySink(on_publish=hold_lock)
    out = env.run()
    env.planner._locks.release("t1", ckey)
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.INTERNAL_REFUSED
    assert out.delivered_count == 1 and out.cursor_seq == 1 and out.lease_released is False
    again = env.run()  # the same worker may re-claim; the sink answers the re-publish with a duplicate ack
    assert again.status is DeliveryStatus.COMPLETE and again.lease_released is True and again.cursor_seq == 2
    assert [p[3] for p in env.sink.published] == ["EVT-CON-1-1", "EVT-CON-1-2"]


def test_register_accepts_only_a_seq_above_the_highest_registered_one():  # B4
    env = Env()
    env.reg([ev(5)])
    env.drain()
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 5
    for late in (ev(4, eid="EVT-LATE"), ev(5, eid="EVT-OTHER-5")):
        out = env.reg([late])
        assert (out.accepted, out.sequence_refused, out.reason) == (0, 1, OpsReason.INPUT_INVALID)
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 5 and len(env.planner.records(S1, "SRC-1", "CON-1")) == 1
    mixed = env.reg([ev(3, eid="EVT-3"), ev(6, eid="EVT-6"), ev(5)])  # 5 is a replay, 6 is new, 3 is late
    assert (mixed.accepted, mixed.replayed, mixed.sequence_refused) == (1, 1, 1)
    assert env.planner.cursor(S1, "SRC-1", "CON-1") == 5  # 6 is pending: the cursor did not move backwards
    other = env.reg([ev(1, "CON-2")])  # another connection has its own high-water mark
    assert other.accepted == 1


def test_unknown_connection_is_not_found_and_creates_no_state():  # B4
    env = Env()
    assert env.planner.claim(S1, "W1", "SRC-1", "CON-NOPE").reason is OpsReason.NOT_FOUND
    out = env.run(conn="CON-NOPE")
    assert out.status is DeliveryStatus.REFUSED and out.reason is OpsReason.NOT_FOUND and env.sink.calls == []
    assert env.planner._claims.count("t1") == 0
    env.reg([ev(1, "CON-NOPE")])
    assert env.planner.claim(S1, "W1", "SRC-1", "CON-NOPE").generation == 1  # no phantom claim row existed


def test_a_429_stays_a_429_with_the_retry_after_clamped_to_the_maximum():  # B5
    env = Env(max_delay=7200)
    env.reg([ev(1)])
    huge = env.run(sink=_FixedSink(SinkResponse(SinkKind.RATE_LIMITED, 10**9)))
    assert huge.status is DeliveryStatus.WAITING and huge.reason is OpsReason.RATE_LIMITED
    assert huge.next_retry_at == T0 + timedelta(seconds=3600)  # clamped to the 3600 s maximum, not retried at once
    env.clock.adv(3600)
    just_over = env.run(sink=_FixedSink(SinkResponse(SinkKind.RATE_LIMITED, 3601)))
    assert just_over.reason is OpsReason.RATE_LIMITED and just_over.next_retry_at == env.clock.t + timedelta(seconds=3600)


@pytest.mark.parametrize("garbage", [-1, True, "7", None, 1.5, 10**30])
def test_a_garbage_retry_after_on_a_429_waits_the_maximum_backoff_never_zero(garbage):  # B5
    env = Env(max_delay=300)
    env.reg([ev(1)])
    out = env.run(sink=_FixedSink(SinkResponse(SinkKind.RATE_LIMITED, garbage)))
    assert out.status is DeliveryStatus.WAITING and out.reason is OpsReason.RATE_LIMITED
    assert out.next_retry_at == T0 + timedelta(seconds=300)


@pytest.mark.parametrize("kind", [SinkKind.DELIVERED, SinkKind.DUPLICATE_ACK])
def test_a_delivered_answer_with_a_garbage_retry_after_is_still_delivered(kind):  # B5
    env = Env()
    env.reg([ev(1)])
    out = env.run(sink=_FixedSink(SinkResponse(kind, "garbage")))
    assert out.status is DeliveryStatus.COMPLETE and out.cursor_seq == 1
    assert (out.delivered_count, out.duplicate_ack_count) == ((1, 0) if kind is SinkKind.DELIVERED else (0, 1))


def test_unhashable_or_forged_reasons_raise_value_error_not_type_error():  # A4
    corr = "CORR-000001"
    for reason in (["x"], {"a": 1}, EvilStr("STALE_CLAIM")):
        with pytest.raises(ValueError):
            DeliveryOutcome(DeliveryStatus.STALE, reason, 0, 0, 0, None, corr)
    with pytest.raises(ValueError):
        DeliveryOutcome(DeliveryStatus.COMPLETE, None, 0, 0, 0, None, corr, lease_released=1)
    with pytest.raises(ValueError):
        RegisterOutcome(0, 0, 0, 0, None, corr, sequence_refused=1)  # a refused seq needs its reason


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
    tree = ast.parse((_SRC / "delivery_replay.py").read_text(encoding="utf-8"))
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
    bad = ast.parse("import socket\nx.delete()\n")
    assert any(isinstance(n, ast.Import) and n.names[0].name in _FORBIDDEN_ROOTS for n in ast.walk(bad))
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in _FORBIDDEN_CALLS for n in ast.walk(bad))
