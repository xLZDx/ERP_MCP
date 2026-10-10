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


class Env:
    def __init__(self, sink=None, **kwargs):
        self.ports = SpyPorts()
        for t, c, a, s in (("t1", "c1", "a1", "SRC-1"), ("t2", "c2", "a2", "SRC-2")):
            self.ports.ent.grant(t, a, c)
            self.ports.owner.add(t, c, "source_id", s)
        self.clock = ManualClock()
        self.sink = sink or FakeDeliverySink()
        self.planner = ReplayPlanner(self.ports, self.ports, FakeCorrelationSource(), self.clock, **kwargs)

    def reg(self, events, scope=S1, source="SRC-1"):
        return self.planner.register(scope, source, events)

    def run(self, worker="W1", scope=S1, source="SRC-1", conn="CON-1", claim=None, sink="DEFAULT"):
        return self.planner.deliver_pending(scope, worker, source, conn, self.sink if sink == "DEFAULT" else sink, claim)

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
    SinkResponse(SinkKind.RATE_LIMITED, 10**9), SinkResponse(SinkKind.RATE_LIMITED, -1),
    SinkResponse(SinkKind.RATE_LIMITED, True), SinkResponse("DELIVERED", 0), None, "DELIVERED", object(),
    object.__new__(SinkResponse), RuntimeError(POISON),
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
    for bad in (None, 5, object(), "sink"):
        assert env.run(sink=bad).status is DeliveryStatus.REFUSED
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
    assert type(deliver_pending(object(), S1, "W1", "SRC-1", "CON-1", env.sink)) is OpsRefusal
    assert deliver_pending(env.planner, S1, "W1", "SRC-1", "CON-1", env.sink).status is DeliveryStatus.COMPLETE


def test_sink_exception_text_never_reaches_any_output():
    env = Env()
    env.sink.script("t1", ["RAISE"])
    env.reg([ev(1)])
    out = env.run()
    assert out.reason is OpsReason.NETWORK_FAILURE
    blob = repr(out) + repr(env.planner.records(S1, "SRC-1", "CON-1")) + repr(env.planner)
    assert POISON not in blob and "ConnectionError" not in blob


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
