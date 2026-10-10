"""S9 E2 / TC130: audit gate fails closed before the effect; completion failure is a visible obligation."""
import ast
import threading
from datetime import datetime
from pathlib import Path

import pytest

from business_ai_gateway.phase2.audit_gate import (
    AuditAck,
    AuditGate,
    AuditPhase,
    AuditRecord,
    FakeAuditSink,
    GateOutcome,
    GateStatus,
    SinkMode,
    UnauditedReport,
    _RecordOutcome,
    guarded_effect,
    is_valid_gate_outcome,
)
from business_ai_gateway.phase2.fakes import FakeClock
from business_ai_gateway.phase2.ops_types import (
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
)
from business_ai_gateway.phase2.side_effect_boundary import default_registry

_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"
POISON = FakeAuditSink.POISON


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilInt(int):
    pass


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
REFS1 = (("source_id", "SRC-1"),)
REFS2 = (("source_id", "SRC-2"),)


def _ports():
    p = SpyPorts()
    p.ent.grant("t1", "a1", "c1")
    p.ent.grant("t2", "a2", "c2")
    p.owner.add("t1", "c1", "source_id", "SRC-1")
    p.owner.add("t2", "c2", "source_id", "SRC-2")
    return p


class Env:
    def __init__(self, cap=1000, timeout=5):
        self.log = []
        self.clock = FakeClock()
        self.ports = _ports()
        self.sink1 = FakeAuditSink(self.clock, log=self.log, name="audit-t1")
        self.sink2 = FakeAuditSink(self.clock, log=self.log, name="audit-t2")
        self.gate = AuditGate(default_registry(), {"t1": self.sink1, "t2": self.sink2}, self.ports, self.ports,
                              FakeCorrelationSource(), self.clock, timeout_seconds=timeout, unaudited_cap=cap)
        self.calls = []

    def effect(self, tag="e"):
        def run():
            self.log.append(("effect", tag))
            self.calls.append(tag)
        return run

    def write(self, scope=S1, request_id="REQ-1", op="create_document", refs=REFS1, effect=None):
        return self.gate.guarded_effect(scope, request_id, op, effect or self.effect(request_id), refs)


# ---- TC130: sink unavailable in every flavour => effect never invoked -------------------------------

class _OtherDigestSink:
    def write(self, record):
        return AuditAck(1, True, "0" * 64)


class _TruthyDurableSink:
    def write(self, record):
        return AuditAck(1, 1, record.digest)  # durable is 1, not True


class _BoolSeqSink:
    def write(self, record):
        return AuditAck(True, True, record.digest)


class _EvilSeqSink:
    def write(self, record):
        return AuditAck(EvilInt(5), True, record.digest)


class _ForgedAckSink:
    def write(self, record):
        return object.__new__(AuditAck)  # attributes never set


class _NoneSink:
    def write(self, record):
        return None


def _env_with_sink(sink):
    env = Env()
    env.gate = AuditGate(default_registry(), {"t1": sink}, env.ports, env.ports, FakeCorrelationSource(),
                         env.clock)
    return env


@pytest.mark.parametrize("mode", [SinkMode.DOWN, SinkMode.SLOW, SinkMode.MALFORMED, SinkMode.NON_DURABLE])
def test_sink_failure_modes_never_invoke_the_effect(mode):
    env = Env()
    env.sink1.set_mode(mode)
    out = env.write()
    assert env.calls == []
    assert out.status is GateStatus.REFUSED and out.reason is OpsReason.AUDIT_UNAVAILABLE
    assert out.effect_invoked is False and out.intent_sequence == 0
    assert POISON not in repr(out) and "ConnectionError" not in repr(out)


@pytest.mark.parametrize("sink", [_OtherDigestSink(), _TruthyDurableSink(), _BoolSeqSink(), _EvilSeqSink(),
                                  _ForgedAckSink(), _NoneSink()])
def test_malformed_or_unbound_acks_never_invoke_the_effect(sink):
    env = _env_with_sink(sink)
    out = env.write()
    assert env.calls == [] and out.reason is OpsReason.AUDIT_UNAVAILABLE


def test_slow_sink_that_did_store_does_not_create_a_second_intent_on_retry():
    env = Env()
    env.sink1.set_mode(SinkMode.SLOW)
    assert env.write().reason is OpsReason.AUDIT_UNAVAILABLE and env.calls == []
    assert len(env.sink1.records) == 1  # stored late, but the effect did not run
    env.sink1.set_mode(SinkMode.HEALTHY)
    assert env.write().status is GateStatus.COMPLETED
    phases = [r.phase for r in env.sink1.records]
    assert phases.count(AuditPhase.INTENT) == 1 and phases.count(AuditPhase.COMPLETION) == 1


def test_bad_clock_fails_closed():
    class NaiveClock:
        def now(self):
            return datetime(2026, 1, 1)  # noqa: DTZ001

    class RaisingClock:
        def now(self):
            raise RuntimeError(POISON)

    for clock in (NaiveClock(), RaisingClock()):
        env = Env()
        env.gate = AuditGate(default_registry(), {"t1": env.sink1}, env.ports, env.ports, FakeCorrelationSource(),
                             clock)
        out = env.write()
        assert env.calls == [] and out.reason is OpsReason.AUDIT_UNAVAILABLE and POISON not in repr(out)


def test_missing_sink_binding_is_unavailable_not_pass_through():
    env = Env()
    env.ports.ent.grant("t3", "a3", "c3")
    env.ports.owner.add("t3", "c3", "source_id", "SRC-3")
    out = env.write(OpsScope("t3", "c3", "a3"), refs=(("source_id", "SRC-3"),))
    assert out.reason is OpsReason.AUDIT_UNAVAILABLE and env.calls == []


def test_recovery_proceeds_with_exactly_one_intent_and_one_completion():
    env = Env()
    env.sink1.set_mode(SinkMode.DOWN)
    assert env.write().reason is OpsReason.AUDIT_UNAVAILABLE and env.calls == []
    assert env.sink1.records == []
    env.sink1.set_mode(SinkMode.HEALTHY)
    out = env.write()
    assert out.status is GateStatus.COMPLETED and out.reason is None and env.calls == ["REQ-1"]
    assert [r.phase for r in env.sink1.records] == [AuditPhase.INTENT, AuditPhase.COMPLETION]
    assert out.intent_sequence >= 1 and out.completion_sequence > out.intent_sequence


def test_call_order_is_intent_then_effect_then_completion():
    env = Env()
    env.write()
    assert env.log == [("audit-t1", "INTENT"), ("effect", "REQ-1"), ("audit-t1", "COMPLETION")]


# ---- completion failure => visible obligation, effect never retried ---------------------------------

def test_completion_failure_is_pending_obligation_and_effect_is_not_retried():
    env = Env()
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)
    out = env.write()
    assert out.status is GateStatus.COMPLETION_PENDING and out.reason is OpsReason.AUDIT_COMPLETION_PENDING
    assert out.effect_invoked is True and out.completion_sequence == 0 and env.calls == ["REQ-1"]
    report = env.gate.unaudited(S1)
    assert type(report) is UnauditedReport and report.pending_count == 1
    assert report.entries[0].request_id == "REQ-1" and report.entries[0].reconciled is False
    assert POISON not in repr(report) and "REQ-1" not in repr(report.entries[0])
    still = env.gate.retry_completion(S1, "REQ-1")  # sink still down: still pending, effect untouched
    assert still.status is GateStatus.COMPLETION_PENDING and env.calls == ["REQ-1"]
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, None)
    done = env.gate.retry_completion(S1, "REQ-1")
    assert done.status is GateStatus.COMPLETED and env.calls == ["REQ-1"]
    assert env.gate.unaudited(S1).pending_count == 0
    assert [r.phase for r in env.sink1.records] == [AuditPhase.INTENT, AuditPhase.COMPLETION]
    again = env.gate.retry_completion(S1, "REQ-1")
    assert again.status is GateStatus.COMPLETED and len(env.sink1.records) == 2


def test_retry_completion_unknown_request_and_foreign_scope():
    env = Env()
    assert env.gate.retry_completion(S1, "REQ-NOPE").reason is OpsReason.NOT_FOUND
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)
    env.write()
    foreign = env.gate.retry_completion(S2, "REQ-1")  # tenant 2 cannot see tenant 1's obligation
    assert foreign.reason is OpsReason.NOT_FOUND
    assert env.gate.unaudited(S2).entries == ()


def test_effect_raising_is_audited_as_effect_failed_never_success():
    env = Env()

    def boom():
        env.log.append(("effect", "boom"))
        raise RuntimeError(POISON)

    out = env.gate.guarded_effect(S1, "REQ-9", "post_document", boom, REFS1)
    assert out.status is GateStatus.EFFECT_FAILED and out.reason is OpsReason.EFFECT_FAILED
    assert out.completion_sequence >= 1 and POISON not in repr(out)
    assert [r.outcome.value for r in env.sink1.records] == ["PENDING", "EFFECT_FAILED"]
    assert env.log == [("audit-t1", "INTENT"), ("effect", "boom"), ("audit-t1", "COMPLETION")]


def test_effect_raising_and_completion_failing_is_pending_not_success():
    env = Env()
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)

    def boom():
        raise RuntimeError(POISON)

    out = env.gate.guarded_effect(S1, "REQ-9", "create_document", boom, REFS1)
    assert out.status is GateStatus.COMPLETION_PENDING
    report = env.gate.unaudited(S1)
    assert report.entries[0].effect_failed is True


# ---- reads and classification -----------------------------------------------------------------------

def test_classified_read_passes_without_the_gate_even_when_sink_is_down():
    env = Env()
    env.sink1.set_mode(SinkMode.DOWN)
    out = env.write(op="read_document")
    assert out.status is GateStatus.READ_PASSED and env.calls == ["REQ-1"]
    assert env.sink1.write_attempts == []


def test_read_that_raises_reports_effect_failed_without_audit():
    env = Env()

    def boom():
        raise RuntimeError(POISON)

    out = env.gate.guarded_effect(S1, "REQ-1", "read_document", boom, REFS1)
    assert out.status is GateStatus.EFFECT_FAILED and env.sink1.write_attempts == [] and POISON not in repr(out)


def test_unclassified_and_invalid_operations_are_refused_without_effect_or_sink():
    env = Env()
    assert env.write(op="launch_missiles").reason is OpsReason.UNCLASSIFIED
    for bad in ("", "  ", "CREATE document!", "create_document\x00", None, 5, EvilStr("read_document"), ["x"],
                "x" * 10_000):
        out = env.write(op=bad)
        assert out.status is GateStatus.REFUSED and out.reason is OpsReason.INPUT_INVALID, bad
    assert env.calls == [] and env.sink1.write_attempts == []


# ---- ownership first, foreign == unknown ------------------------------------------------------------

def test_foreign_and_unknown_refs_are_identical_and_nothing_is_written():
    foreign, unknown = Env(), Env()
    f = foreign.write(refs=REFS2)  # SRC-2 belongs to tenant 2
    u = unknown.write(refs=(("source_id", "SRC-NOPE"),))
    assert f.reason is u.reason is OpsReason.NOT_FOUND and f.status is u.status is GateStatus.REFUSED
    assert foreign.ports.log == unknown.ports.log
    for env in (foreign, unknown):
        assert env.calls == [] and env.sink1.write_attempts == [] and env.sink2.write_attempts == []


def test_unentitled_actor_is_refused_before_any_ownership_question():
    env = Env()
    out = env.write(OpsScope("t1", "c1", "stranger"))
    assert out.reason is OpsReason.NOT_ENTITLED
    assert [c[0] for c in env.ports.log] == ["entitled"] and env.calls == []


def test_hostile_inputs_never_raise_and_never_invoke_the_effect():
    env = Env()
    hostile = [None, 5, b"x", EvilStr("t1"), "", [None], object(), "x" * 10_000, float("nan")]
    for bad in hostile:
        assert env.gate.guarded_effect(bad, "REQ-1", "create_document", env.effect(), REFS1).status \
            is GateStatus.REFUSED
        assert env.gate.guarded_effect(S1, bad, "create_document", env.effect(), REFS1).status is GateStatus.REFUSED
        assert env.gate.guarded_effect(S1, "REQ-1", "create_document", bad, REFS1).status is GateStatus.REFUSED
        assert env.gate.guarded_effect(S1, "REQ-1", "create_document", env.effect(), bad).status \
            is GateStatus.REFUSED
        assert type(env.gate.unaudited(bad)) is OpsRefusal
        assert env.gate.retry_completion(bad, "REQ-1").status is GateStatus.REFUSED
    forged = object.__new__(OpsScope)
    assert env.gate.guarded_effect(forged, "REQ-1", "create_document", env.effect(), REFS1).status \
        is GateStatus.REFUSED
    assert env.calls == []


def test_port_that_raises_is_dependency_failed_and_effect_not_invoked():
    env = Env()

    class Boom:
        def entitled(self, *a):
            raise RuntimeError(POISON)

        def owns(self, *a):
            raise RuntimeError(POISON)

    env.gate = AuditGate(default_registry(), {"t1": env.sink1}, Boom(), Boom(), FakeCorrelationSource(),
                         env.clock)
    out = env.write()
    assert out.reason is OpsReason.DEPENDENCY_FAILED and env.calls == [] and POISON not in repr(out)


def test_module_function_requires_an_exact_gate():
    env = Env()
    assert type(guarded_effect(object(), S1, "REQ-1", "create_document", env.effect(), REFS1)) is OpsRefusal
    assert guarded_effect(env.gate, S1, "REQ-1", "create_document", env.effect(), REFS1).status \
        is GateStatus.COMPLETED


# ---- per tenant -------------------------------------------------------------------------------------

def test_tenant_a_outage_does_not_block_tenant_b():
    env = Env()
    env.sink1.set_mode(SinkMode.DOWN)
    a = env.write(S1, "REQ-A", refs=REFS1)
    b = env.write(S2, "REQ-B", refs=REFS2)
    assert a.reason is OpsReason.AUDIT_UNAVAILABLE and b.status is GateStatus.COMPLETED
    assert env.calls == ["REQ-B"] and env.sink1.records == [] and len(env.sink2.records) == 2
    assert all(r.tenant_id == "t2" for r in env.sink2.records)


def test_unaudited_quota_is_per_tenant_and_refuses_before_the_effect():
    env = Env(cap=1)
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)
    assert env.write(S1, "REQ-1").status is GateStatus.COMPLETION_PENDING
    full = env.write(S1, "REQ-2")
    assert full.reason is OpsReason.QUOTA_EXCEEDED and env.calls == ["REQ-1"]
    assert env.write(S2, "REQ-B", refs=REFS2).status is GateStatus.COMPLETED  # tenant 2 unaffected
    assert env.gate.unaudited(S1).pending_count == 1  # nothing evicted


def test_obligation_overflow_race_is_counted_visibly_not_lost():
    env = Env(cap=1)
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)
    inner = []

    def outer_effect():
        env.calls.append("outer")
        inner.append(env.write(S1, "REQ-INNER"))  # fills the list after the outer pre-check passed

    out = env.gate.guarded_effect(S1, "REQ-OUTER", "create_document", outer_effect, REFS1)
    assert out.status is GateStatus.COMPLETION_PENDING and inner[0].status is GateStatus.COMPLETION_PENDING
    report = env.gate.unaudited(S1)
    assert len(report.entries) == 1 and report.overflow_count == 1 and report.pending_count == 2


def test_concurrent_distinct_requests_each_run_once_with_two_audit_records():
    env = Env()
    outs = []

    def work(i):
        outs.append(env.write(S1, f"REQ-{i}", effect=env.effect(f"REQ-{i}")))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(env.calls) == sorted(f"REQ-{i}" for i in range(16))
    assert all(o.status is GateStatus.COMPLETED for o in outs)
    assert len(env.sink1.records) == 32


# ---- value types and construction -------------------------------------------------------------------

def test_outcome_validation_and_forgery():
    corr = "CORR-000001"
    assert GateOutcome(GateStatus.COMPLETED, None, 1, 2, True, corr).authority == "EVALUATION_ONLY"
    for args in ((GateStatus.COMPLETED, OpsReason.NOT_FOUND, 0, 0, False, corr),
                 (GateStatus.REFUSED, OpsReason.NOT_FOUND, 0, 0, True, corr),
                 (GateStatus.REFUSED, OpsReason.WITHIN_TARGET, 0, 0, False, corr),
                 (GateStatus.COMPLETION_PENDING, None, 0, 0, True, corr),
                 ("COMPLETED", None, 0, 0, True, corr), (GateStatus.COMPLETED, None, True, 0, True, corr),
                 (GateStatus.COMPLETED, None, 0, 0, True, "")):
        with pytest.raises(ValueError):
            GateOutcome(*args)
    assert not is_valid_gate_outcome(object.__new__(GateOutcome)) and not is_valid_gate_outcome(None)
    assert "authority" in {f for f in GateOutcome.__dataclass_fields__}
    assert not {"status_override", "passed", "verdict"} & set(GateOutcome.__dataclass_fields__)


def test_audit_record_validation_and_redaction():
    rec = AuditRecord("t1", "c1", "a1", "REQ-1", "create_document", AuditPhase.INTENT, _RecordOutcome.PENDING)
    assert "REQ-1" not in repr(rec) and len(rec.digest) == 64
    with pytest.raises(ValueError):
        AuditRecord("t1", "c1", "a1", "REQ-1", "Create Document", AuditPhase.INTENT, rec.outcome)
    with pytest.raises(ValueError):
        AuditRecord(EvilStr("t1"), "c1", "a1", "REQ-1", "create_document", AuditPhase.INTENT, rec.outcome)


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": 0}, {"timeout_seconds": True}, {"timeout_seconds": 3601},
                                    {"unaudited_cap": 0}, {"unaudited_cap": 1.5}])
def test_gate_construction_refuses_invalid_config(kwargs):
    env = Env()
    with pytest.raises(ValueError):
        AuditGate(default_registry(), {"t1": env.sink1}, env.ports, env.ports, FakeCorrelationSource(), env.clock,
                  **kwargs)


def test_gate_construction_refuses_bad_registry_sinks_and_clock():
    env = Env()
    base = (env.ports, env.ports, FakeCorrelationSource(), env.clock)
    for registry, sinks, clock in ((object(), {"t1": env.sink1}, env.clock), (default_registry(), [], env.clock),
                                   (default_registry(), {"t1": object()}, env.clock),
                                   (default_registry(), {EvilStr("t1"): env.sink1}, env.clock),
                                   (default_registry(), {"t1": env.sink1}, object())):
        with pytest.raises(ValueError):
            AuditGate(registry, sinks, base[0], base[1], base[2], clock)


def test_sink_binding_is_snapshotted_at_construction():
    env = Env()
    sinks = {"t1": env.sink1}
    gate = AuditGate(default_registry(), sinks, env.ports, env.ports, FakeCorrelationSource(), env.clock)
    sinks["t1"] = _NoneSink()
    sinks["t2"] = _NoneSink()
    assert gate.guarded_effect(S1, "REQ-1", "create_document", env.effect(), REFS1).status is GateStatus.COMPLETED
    assert gate.guarded_effect(S2, "REQ-2", "create_document", env.effect(), REFS2).reason \
        is OpsReason.AUDIT_UNAVAILABLE


def test_outputs_are_frozen_and_gate_repr_is_redacted():
    env = Env()
    out = env.write()
    with pytest.raises(AttributeError):
        out.status = GateStatus.REFUSED  # type: ignore[misc]
    assert repr(env.gate) == "AuditGate(<redacted>)"


def test_unaudited_effects_trip_the_alert_rule():
    from business_ai_gateway.phase2.alert_rules import AlertEngine, AlertRule, RuleKind

    env = Env()
    env.sink1.set_phase_mode(AuditPhase.COMPLETION, SinkMode.DOWN)
    env.write()
    ports = env.ports
    engine = AlertEngine(ports, ports, FakeCorrelationSource(), env.clock)
    rule = AlertRule(RuleKind.UNAUDITED_EFFECTS, 1, 0, 0, 0)
    assert engine.set_rule(S1, "SRC-1", rule) is None
    assert engine.observe(S1, "SRC-1", RuleKind.UNAUDITED_EFFECTS, env.gate.unaudited(S1).pending_count) is None
    events = engine.events(S1)
    assert [e.reason for e in events] == [OpsReason.ALERT_FIRED]


# ---- import boundary --------------------------------------------------------------------------------

_FORBIDDEN_ROOTS = {
    "httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket", "ssl", "subprocess", "sqlite3",
    "psycopg", "psycopg2", "asyncpg", "sqlalchemy", "os", "pathlib", "random", "secrets", "time", "shutil",
    "tempfile", "io", "ctypes", "asyncio", "multiprocessing", "concurrent", "fastapi", "flask", "starlette",
    "threading", "contextvars",
}
_FORBIDDEN_CALLS = {"delete", "remove", "unlink", "rmtree", "truncate", "drop", "open", "eval", "exec", "compile"}


def _imports(path):
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append((node.module or "", node.level))
    return out


def test_module_imports_nothing_forbidden_and_has_no_delete_calls():
    import sys
    path = _SRC / "audit_gate.py"
    records = _imports(path)
    assert records
    for module, level in records:
        root = module.split(".")[0]
        assert root not in _FORBIDDEN_ROOTS, module
        assert not any(s in module.lower() for s in ("drive_http", "onec", "pdcc", "release1", "release_1"))
        if level:
            assert level == 1, module
        elif root == "business_ai_gateway":
            assert module.startswith("business_ai_gateway.phase2")
        else:
            assert root in sys.stdlib_module_names, module
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            assert name not in _FORBIDDEN_CALLS, (name, node.lineno)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"environ", "getenv", "sleep", "utcnow", "now_real"}, node.lineno


def test_boundary_scan_is_not_vacuous():
    bad = ast.parse("import socket\nx.remove(1)\n")
    assert any(isinstance(n, ast.Import) and n.names[0].name in _FORBIDDEN_ROOTS for n in ast.walk(bad))
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in _FORBIDDEN_CALLS for n in ast.walk(bad))
