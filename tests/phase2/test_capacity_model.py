"""S9 E1 capacity model: TC127 four axes + grid, TC128 refusals are not throughput, exact percentiles,
ownership-before-read, per-tenant quota, no "proven" field. Hostile and refusal rows first."""
import dataclasses
import threading
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.capacity_model import (
    MATRIX_ACTIVE_CLIENTS,
    MATRIX_SESSIONS,
    MATRIX_SOURCES,
    OPERATOR_REFERENCE_ACTION,
    R1_LIMITS,
    ActiveClientCount,
    BackendCount,
    CacheState,
    CapacityReport,
    CapacityStore,
    ConfiguredLimit,
    DiscoveryState,
    GridCell,
    LimitLayer,
    MeasurementRef,
    OutcomeClass,
    PercentileValue,
    ReportPolicy,
    RequestSample,
    SessionCount,
    SourceCount,
    WorkloadClass,
    build_report,
    is_valid_cell,
    is_valid_report,
    is_valid_sample,
    make_cell,
    make_sample,
    percentile,
    read_report,
    summarize,
    throughput,
)
from business_ai_gateway.phase2.fakes import FakeClock
from business_ai_gateway.phase2.ops_types import (
    AUTHORITY,
    Basis,
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOperatorAuthority,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
)


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilInt(int):
    def __eq__(self, other):
        return True

    __hash__ = int.__hash__


class EvilDecimal(Decimal):
    pass


OK, PR = OutcomeClass.BUSINESS_OK, OutcomeClass.PROFILE_REFUSED
HOSTILE_INT = [None, True, False, 0, -1, EvilInt(5), 5.0, "5", Decimal(5), 2**80, [5], object()]
HOSTILE_LATENCY = [None, True, False, -1, EvilInt(5), 5.0, "5", Decimal(5), 2**80, 3_600_000_001, [5], object()]


def ids():
    return FakeCorrelationSource()


def cell(sources=30, clients=5, sessions=1000, backends=1, cache=CacheState.WARM,
         disc=DiscoveryState.OFF, work=WorkloadClass.METADATA):
    result = make_cell(SourceCount(sources), ActiveClientCount(clients), SessionCount(sessions),
                       BackendCount(backends), cache, disc, work, ids())
    assert type(result) is GridCell, result
    return result


def s(outcome, latency):
    return RequestSample(outcome, latency)


class Env:
    """Ports with one shared call log, a store, and a clock."""

    def __init__(self, cap=3):
        self.log: list[tuple] = []
        self.owner, self.ent = FakeOwnership(), FakeEntitlements()
        self.ent.grant("t1", "a1", "c1")
        self.ent.grant("t2", "b1", "c9")
        self.store = CapacityStore(cap, FakeCorrelationSource("RPT"), self.register, FakeCorrelationSource())
        self.clock = FakeClock()
        self.auth = FakeOperatorAuthority()

    def register(self, tenant_id, company_id, kind, ref):
        """Owner registration that CONFIRMS: FakeOwnership.add is silent on overflow, so ask owns() afterwards."""
        self.owner.add(tenant_id, company_id, kind, ref)
        return self.owner.owns(tenant_id, company_id, kind, ref)

    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id, actor_id, company_id))
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, company_id, kind, ref))
        return self.owner.owns(tenant_id, company_id, kind, ref)

    def build(self, scope, samples, grid=None, policy=None, **kw):
        kw.setdefault("operator_authority", self.auth)
        return build_report(scope, self, self, self.store, grid or cell(), samples,
                            policy or ReportPolicy(window_us=10_000_000), self.clock, **kw)

    def read(self, scope, report_id):
        return read_report(scope, report_id, self, self, self.store)


A1 = OpsScope("t1", "c1", "a1")
B1 = OpsScope("t2", "c9", "b1")
GOOD_SAMPLES = [s(OK, 1000 * (i + 1)) for i in range(100)]


# ======================================================================== TC127: four axes

@pytest.mark.parametrize("cls", [SessionCount, ActiveClientCount, SourceCount, BackendCount])
@pytest.mark.parametrize("bad", HOSTILE_INT)
def test_axis_types_reject_hostile_values(cls, bad):
    with pytest.raises(ValueError, match="AXIS_INVALID"):
        cls(bad)


def test_axis_limits_and_no_implicit_conversion():
    assert SessionCount(1000).value == 1000 and BackendCount(64).value == 64
    with pytest.raises(ValueError, match="AXIS_INVALID"):
        BackendCount(65)
    with pytest.raises(ValueError, match="AXIS_INVALID"):
        SessionCount(1_000_001)
    with pytest.raises(TypeError):
        int(SessionCount(5))  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        SessionCount(5) + 1  # type: ignore[operator]
    with pytest.raises(TypeError):
        SessionCount(5) < SessionCount(6)  # type: ignore[operator]  # noqa: B015


def test_four_axis_types_are_distinct_and_never_equal_even_with_the_same_number():
    axes = [SessionCount(5), ActiveClientCount(5), SourceCount(5), BackendCount(5)]
    assert len({type(a) for a in axes}) == 4
    for i, a in enumerate(axes):
        for j, b in enumerate(axes):
            assert (a == b) is (i == j)
    assert len({hash(a) for a in axes}) >= 1 and len(set(axes)) == 4


def _all_axes():
    return {"sources": SourceCount(30), "clients": ActiveClientCount(5), "sessions": SessionCount(1000),
            "backends": BackendCount(2)}


_AXIS_NAMES = ["sources", "clients", "sessions", "backends"]


@pytest.mark.parametrize(("slot", "wrong"), [(a, b) for a in _AXIS_NAMES for b in _AXIS_NAMES if a != b])
def test_each_axis_type_in_another_axis_place_is_refused(slot, wrong):
    axes = _all_axes()
    axes[slot] = axes[wrong]
    result = make_cell(axes["sources"], axes["clients"], axes["sessions"], axes["backends"],
                       CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, ids())
    assert type(result) is OpsRefusal and result.reason is OpsReason.INPUT_INVALID
    with pytest.raises(ValueError, match="GRID_CELL_INVALID"):
        GridCell(axes["sources"], axes["clients"], axes["sessions"], axes["backends"],
                 CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA)


@pytest.mark.parametrize("plain", [5, "5", 5.0, True, Decimal(5), None])
def test_plain_numbers_are_not_accepted_as_axes(plain):
    for pos in range(4):
        args = [SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1)]
        args[pos] = plain
        result = make_cell(*args, CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, ids())
        assert type(result) is OpsRefusal
        if plain is not None:
            assert result.reason is OpsReason.INPUT_INVALID


def test_sessions_and_active_clients_stay_two_numbers_and_render_separately():
    grid = cell(sources=100, clients=5, sessions=1000, backends=3)
    assert dict(grid.axes()) == {"sources": 100, "active_clients": 5, "sessions": 1000, "backends": 3}
    assert grid.sessions.value == 1000 and grid.active_clients.value == 5
    assert repr(grid) == "GridCell(sources=100, active_clients=5, sessions=1000, backends=3)"


def test_a_sessions_claim_without_the_active_client_dimension_is_refused():
    result = make_cell(SourceCount(30), None, SessionCount(1000), BackendCount(1), CacheState.WARM,
                       DiscoveryState.OFF, WorkloadClass.METADATA, ids())
    assert result.reason is OpsReason.SESSIONS_NOT_ACTIVE_CLIENTS


def test_missing_backend_count_is_refused():
    result = make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000), None, CacheState.WARM,
                       DiscoveryState.OFF, WorkloadClass.METADATA, ids())
    assert result.reason is OpsReason.BACKEND_COUNT_MISSING


def test_sessions_below_active_clients_is_inconsistent_over_the_whole_matrix():
    refused, accepted = [], 0
    for src in MATRIX_SOURCES:
        for sessions in MATRIX_SESSIONS:
            for clients in MATRIX_ACTIVE_CLIENTS:
                result = make_cell(SourceCount(src), ActiveClientCount(clients), SessionCount(sessions),
                                   BackendCount(1), CacheState.COLD, DiscoveryState.ON, WorkloadClass.BALANCES,
                                   ids())
                if type(result) is GridCell:
                    accepted += 1
                    assert sessions >= clients
                else:
                    assert result.reason is OpsReason.GRID_CELL_INCONSISTENT
                    refused.append((sessions, clients))
    assert set(refused) == {(50, 100)} and len(refused) == len(MATRIX_SOURCES)
    assert accepted == len(MATRIX_SOURCES) * (len(MATRIX_SESSIONS) * len(MATRIX_ACTIVE_CLIENTS) - 1)


@pytest.mark.parametrize(("sources", "clients", "sessions"), [(31, 5, 1000), (30, 6, 1000), (30, 5, 999)])
def test_values_outside_the_fixed_matrix_are_refused(sources, clients, sessions):
    result = make_cell(SourceCount(sources), ActiveClientCount(clients), SessionCount(sessions),
                       BackendCount(1), CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, ids())
    assert result.reason is OpsReason.INPUT_INVALID


def test_every_matrix_dimension_value_is_a_real_enum_member():
    for cache in CacheState:
        for disc in DiscoveryState:
            for work in WorkloadClass:
                assert type(cell(cache=cache, disc=disc, work=work)) is GridCell
    assert {c.value for c in CacheState} == {"COLD", "WARM"} and {d.value for d in DiscoveryState} == {"OFF", "ON"}
    assert {w.value for w in WorkloadClass} == {"METADATA", "DOCUMENTS", "BALANCES", "CAPTURE"}
    for bad in ("WARM", EvilStr("WARM"), None, 1):
        result = make_cell(SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1), bad,
                           DiscoveryState.OFF, WorkloadClass.METADATA, ids())
        assert result.reason is OpsReason.INPUT_INVALID


def test_r1_constants_and_config_limits_are_not_accepted_as_another_layer():
    assert {k.value: v.value for k, v in R1_LIMITS.items()} == {
        "R1_SESSIONS": 1000, "R1_POOL": 10, "R1_SIDECAR": 4, "R1_FANOUT_TOTAL": 20, "R1_FANOUT_PER_BACKEND": 2}
    for limit in R1_LIMITS.values():
        for pos in range(4):
            args = [SourceCount(30), ActiveClientCount(5), SessionCount(1000), BackendCount(1)]
            args[pos] = limit
            result = make_cell(*args, CacheState.WARM, DiscoveryState.OFF, WorkloadClass.METADATA, ids())
            assert result.reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
        sample = make_sample(limit, 100, ids())
        assert sample.reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
        assert make_sample(OK, limit, ids()).reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    for layer in (LimitLayer.BUDGET, LimitLayer.MAX_SESSIONS, LimitLayer.POOL_SIZE):
        assert make_cell(ConfiguredLimit(layer, 150), None, None, None, None, None, None,
                         ids()).reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    # a ConfiguredLimit smuggled into the sample list is refused as such, not counted
    env = Env()
    result = env.build(A1, [*GOOD_SAMPLES, R1_LIMITS[LimitLayer.R1_POOL]])
    assert result.reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    assert env.store.count("t1") == 0


def test_configured_limit_itself_is_validated():
    for bad in (("R1_POOL", 10), (LimitLayer.R1_POOL, True), (LimitLayer.R1_POOL, -1), (LimitLayer.R1_POOL, 2**40)):
        with pytest.raises(ValueError, match="CONFIGURED_LIMIT_INVALID"):
            ConfiguredLimit(*bad)


def test_one_source_count_over_several_backends_and_one_backend_shared_by_sources_are_distinct_cells():
    many_sources_one_backend = cell(sources=150, backends=1)
    few_sources_many_backends = cell(sources=30, backends=8)
    assert many_sources_one_backend != few_sources_many_backends
    assert dict(many_sources_one_backend.axes())["backends"] == 1
    assert dict(few_sources_many_backends.axes())["sources"] == 30
    assert cell(sources=30, backends=1) != cell(sources=30, backends=2)


def test_forged_cell_is_not_valid():
    assert not is_valid_cell(object.__new__(GridCell))
    forged = object.__new__(GridCell)
    for name, value in (("sources", SourceCount(30)), ("active_clients", ActiveClientCount(5)),
                        ("sessions", SessionCount(1000)), ("backends", 7), ("cache_state", CacheState.WARM),
                        ("discovery", DiscoveryState.ON), ("workload", WorkloadClass.METADATA)):
        object.__setattr__(forged, name, value)
    assert not is_valid_cell(forged)
    for junk in (None, 1, "x", object()):
        assert not is_valid_cell(junk)


# ===================================================================== samples and outcome classes

def test_outcome_class_is_closed():
    assert [c.value for c in OutcomeClass] == [
        "BUSINESS_OK", "BUSINESS_ERROR", "TIMEOUT", "PROFILE_REFUSED", "ACL_REFUSED", "BUDGET_REFUSED",
        "AUTH_REFUSED"]


@pytest.mark.parametrize("bad", ["business_ok", "BUSINESS_OK ", " BUSINESS_OK", "OK", "", "SUCCESS",
                                 EvilStr("BUSINESS_OK"), None, 1, b"BUSINESS_OK", "BUSINESS_OK\x00"])
def test_unknown_outcome_is_refused_and_never_counted_as_ok(bad):
    result = make_sample(bad, 100, ids())
    assert type(result) is OpsRefusal
    assert result.reason is OpsReason.INPUT_INVALID
    env = Env()
    assert env.build(A1, [*GOOD_SAMPLES, bad]).reason is OpsReason.INPUT_INVALID


def test_make_sample_accepts_exact_member_and_exact_string_only():
    assert make_sample("BUSINESS_OK", 5, ids()) == s(OK, 5)
    assert make_sample(OK, 5, ids()) == s(OK, 5)
    assert make_sample(OK, 5, ids(), basis="OPERATOR_REFERENCE").reason is OpsReason.INPUT_INVALID


@pytest.mark.parametrize("bad", HOSTILE_LATENCY)
def test_hostile_latency_is_refused(bad):
    assert make_sample(OK, bad, ids()).reason is OpsReason.INPUT_INVALID
    with pytest.raises(ValueError, match="SAMPLE_INVALID"):
        RequestSample(OK, bad)


def test_latency_bounds_are_exact():
    assert make_sample(OK, 0, ids()) == s(OK, 0)
    assert make_sample(OK, 3_600_000_000, ids()).latency_us == 3_600_000_000


def test_forged_and_malformed_samples_are_invalid():
    assert not is_valid_sample(object.__new__(RequestSample))
    for junk in (None, ("BUSINESS_OK", 5), "x", {"outcome": OK}, object()):
        assert not is_valid_sample(junk)
    with pytest.raises(ValueError, match="SAMPLE_INVALID"):
        RequestSample("BUSINESS_OK", 5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="SAMPLE_INVALID"):
        RequestSample(OK, 5, "SCRIPTED_OFFLINE_FIXTURE")  # type: ignore[arg-type]
    assert "100" not in repr(s(OK, 100))


# ======================================================================== exact percentiles

def test_nearest_rank_known_vectors_p50_p95_p99():
    values = list(range(1, 101))  # 1..100: rank == value
    assert (percentile(values, 50).value, percentile(values, 95).value, percentile(values, 99).value) == (50, 95, 99)
    shuffled = [37, 5, 99, 1, 100] + [v for v in values if v not in (37, 5, 99, 1, 100)][::-1]
    assert (percentile(shuffled, 50).value, percentile(shuffled, 95).value, percentile(shuffled, 99).value) == (50, 95, 99)
    values200 = list(range(1, 201))
    assert percentile(values200, 50).value == 100 and percentile(values200, 95).value == 190
    assert percentile(values200, 99).value == 198
    assert percentile(tuple(values), 99).n == 100


def test_nearest_rank_odd_even_ties_and_single_sample():
    assert percentile([10], 50).value == 10 and percentile([10], 50).n == 1
    assert percentile([30, 10], 50).value == 10  # rank ceil(0.5*2) = 1
    assert percentile([10, 20, 30], 50).value == 20  # rank 2
    assert percentile([5, 5, 5, 5], 50).value == 5  # ties
    twenty = [100] * 19 + [999]
    assert percentile(twenty, 95).value == 100  # rank 19 of 20
    assert percentile(twenty + [999], 95).value == 999  # rank ceil(0.95*21) = 20 of 21 sorted
    assert percentile([0, 0], 50).value == 0  # zero is a real latency


def test_percentile_minimum_samples_give_insufficient_not_a_number():
    p99_short = percentile(list(range(99)), 99)
    assert p99_short.value is None and p99_short.reason is OpsReason.INSUFFICIENT_SAMPLES and p99_short.n == 99
    assert percentile(list(range(19)), 95).reason is OpsReason.INSUFFICIENT_SAMPLES
    assert percentile(list(range(20)), 95).value == 18
    assert percentile([], 50).reason is OpsReason.INSUFFICIENT_SAMPLES
    assert percentile([7], 95).value is None and percentile([7], 99).value is None


@pytest.mark.parametrize("p", [0, 100, 51, -1, True, 95.0, "95", None, EvilInt(95), 2**70])
def test_percentile_unsupported_p_is_input_invalid(p):
    result = percentile([1, 2, 3], p)
    assert result.reason is OpsReason.INPUT_INVALID and result.value is None


@pytest.mark.parametrize("bad", [None, "123", {1, 2}, object(), [1, 2.0], [1, True], [1, -1], [1, 2**80],
                                 [1, EvilInt(2)], [1, "2"], [1, None], [3_600_000_001], [Decimal(1)]])
def test_percentile_hostile_values_are_refused_without_raising(bad):
    assert percentile(bad, 50).reason is OpsReason.INPUT_INVALID


def test_percentile_recursive_and_oversize_inputs_do_not_raise():
    loop: list = []
    loop.append(loop)
    assert percentile(loop, 50).reason is OpsReason.INPUT_INVALID
    assert percentile([1] * 100_001, 50).reason is OpsReason.INPUT_INVALID

    class Liar(list):
        def __iter__(self):
            raise RuntimeError("POISON")

    assert percentile(Liar([1, 2]), 50).reason is OpsReason.INPUT_INVALID


def test_percentile_value_validates_itself():
    with pytest.raises(ValueError, match="PERCENTILE_INVALID"):
        PercentileValue(50, 1, 5, OpsReason.INSUFFICIENT_SAMPLES)
    with pytest.raises(ValueError, match="PERCENTILE_INVALID"):
        PercentileValue(50, 1, None, None)


def test_throughput_is_an_exact_decimal_rate():
    assert throughput(100, 10_000_000) == Decimal("10.000000")
    assert throughput(0, 1) == Decimal("0.000000")
    assert throughput(1, 3_000_000) == Decimal("0.333333")
    assert throughput(2, 3_000_000) == Decimal("0.666667")
    assert type(throughput(5, 1_000_000)) is Decimal
    for bad_count, bad_window in [(True, 1), (-1, 1), (1.0, 1), (1, 0), (1, True), (1, 1.0), (1, -5),
                                  (EvilInt(1), 1), (1, EvilInt(1)), (None, 1), (1, 2**80), (100_001, 1)]:
        assert throughput(bad_count, bad_window) is None


# ======================================================================== TC128: refusals

def test_1000_instant_refusals_plus_100_slow_ok_gives_throughput_and_p95_of_the_100_only():
    env = Env()
    samples = [s(PR, 50) for _ in range(1000)] + [s(OK, 200_000 + i) for i in range(100)]
    report = env.build(A1, samples)
    assert type(report) is CapacityReport
    assert report.throughput_per_s == Decimal("10.000000")  # 100 OK / 10 s, refusals add nothing
    assert report.business[1].value == 200_094 and report.business[1].n == 100  # p95 of the 100 slow OK only
    assert report.business[0].value == 200_049
    assert dict(report.counts)["PROFILE_REFUSED"] == 1000 and dict(report.counts)["BUSINESS_OK"] == 100
    assert report.refusal_latency[0].value == 50 and report.refusal_latency[0].n == 1000
    assert OpsReason.REFUSALS_DOMINATE in report.flags and OpsReason.UNRELIABLE_REFUSALS in report.flags
    assert report.refusal_fraction == Decimal("0.909091")


def _lcg(seed):
    state = seed
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) % 2**64
        yield state >> 33


def test_adding_refusals_never_changes_business_throughput_or_business_percentiles():
    for seed in range(1, 9):
        gen = _lcg(seed)
        base = [s(OK, 1 + next(gen) % 900_000) for _ in range(150)]
        base += [s(OutcomeClass.BUSINESS_ERROR, 1 + next(gen) % 900_000) for _ in range(10)]
        env = Env(cap=50)
        reference = env.build(A1, base)
        assert type(reference) is CapacityReport
        extra = []
        for step in range(1, 7):
            extra += [s(list(OutcomeClass)[3 + next(gen) % 4], next(gen) % 5000) for _ in range(step * 40)]
            mixed = base + extra
            for i in range(len(mixed) - 1, 0, -1):  # deterministic interleave of the refusals into the sequence
                j = next(gen) % (i + 1)
                mixed[i], mixed[j] = mixed[j], mixed[i]
            report = env.build(A1, mixed)
            assert report.throughput_per_s == reference.throughput_per_s
            assert report.business == reference.business
            assert dict(report.counts)["BUSINESS_OK"] == 150 and dict(report.counts)["BUSINESS_ERROR"] == 10
            assert report.total_samples == len(base) + len(extra)


def test_acl_and_other_refusals_are_counted_separately_with_their_own_counter():
    samples = ([s(OK, 1000)] * 10 + [s(OutcomeClass.ACL_REFUSED, 10)] * 3 + [s(OutcomeClass.BUDGET_REFUSED, 20)] * 2
               + [s(OutcomeClass.AUTH_REFUSED, 30)] + [s(PR, 40)] * 4 + [s(OutcomeClass.TIMEOUT, 9_000_000)]
               + [s(OutcomeClass.BUSINESS_ERROR, 5000)] * 2)
    summary = summarize(samples, ids())
    assert [(k, v) for k, v in summary.counts] == [
        ("BUSINESS_OK", 10), ("BUSINESS_ERROR", 2), ("TIMEOUT", 1), ("PROFILE_REFUSED", 4),
        ("ACL_REFUSED", 3), ("BUDGET_REFUSED", 2), ("AUTH_REFUSED", 1)]
    assert summary.business_ok == 10 and summary.refused == 10 and summary.total == 23
    assert summary.count_of(OutcomeClass.ACL_REFUSED) == 3
    # timeouts and business errors are neither throughput nor refusals; refusal latency never mixes into business
    assert summary.business[0].value == 1000 and summary.business[0].n == 10
    assert summary.refusal_latency[0].n == 10 and summary.refusal_latency[0].value == 20


def test_refusals_dominate_boundary_uses_the_declared_bound_exactly():
    env = Env(cap=10)
    policy = ReportPolicy(window_us=10_000_000, refusal_bound=Decimal("0.5"))
    at_bound = [s(OK, 10)] * 50 + [s(PR, 1)] * 50
    over_bound = [s(OK, 10)] * 49 + [s(PR, 1)] * 51
    assert OpsReason.REFUSALS_DOMINATE not in env.build(A1, at_bound, policy=policy).flags
    over = env.build(A1, over_bound, policy=policy)
    assert OpsReason.REFUSALS_DOMINATE in over.flags and OpsReason.UNRELIABLE_REFUSALS in over.flags
    strict = ReportPolicy(window_us=10_000_000, refusal_bound=Decimal(0))
    assert OpsReason.REFUSALS_DOMINATE in env.build(A1, [s(OK, 1), s(PR, 1)], policy=strict).flags
    assert OpsReason.REFUSALS_DOMINATE not in env.build(A1, [s(OK, 1)], policy=strict).flags


def test_empty_samples_are_not_a_pass_they_are_insufficient():
    report = Env().build(A1, [])
    assert report.throughput_per_s == Decimal("0.000000") and report.refusal_fraction == Decimal("0.000000")
    assert all(pv.reason is OpsReason.INSUFFICIENT_SAMPLES for pv in report.business)
    assert OpsReason.INSUFFICIENT_SAMPLES in report.flags


@pytest.mark.parametrize("bad", [None, "samples", 5, {"a": 1}, {1, 2}, object(), (1, 2, 3), [None], [object()],
                                 [("BUSINESS_OK", 5)], [OK]])
def test_hostile_sample_containers_are_refused_before_ports_are_asked(bad):
    env = Env()
    result = env.build(A1, bad)
    assert type(result) is OpsRefusal and result.reason is OpsReason.INPUT_INVALID
    assert env.log == []


def test_list_subclass_and_oversize_sample_inputs_are_refused():
    env = Env()

    class L(list):
        pass

    assert env.build(A1, L(GOOD_SAMPLES)).reason is OpsReason.INPUT_INVALID
    assert env.build(A1, [s(OK, 1)] * 100_001).reason is OpsReason.INPUT_INVALID
    loop: list = []
    loop.append(loop)
    assert env.build(A1, loop).reason is OpsReason.INPUT_INVALID
    assert env.log == []


def test_samples_are_snapshotted_once_so_a_mutating_caller_cannot_change_the_report():
    env = Env()
    samples = [s(OK, 100)] * 30

    class MutatingClock:
        def now(self):
            samples.clear()
            samples.extend([s(PR, 1)] * 500)
            return datetime(2026, 1, 1, tzinfo=UTC)

    report = build_report(A1, env, env, env.store, cell(), samples, ReportPolicy(window_us=1_000_000),
                          MutatingClock())
    assert dict(report.counts)["BUSINESS_OK"] == 30 and dict(report.counts)["PROFILE_REFUSED"] == 0
    assert report.total_samples == 30


@pytest.mark.parametrize("bad", [(0, Decimal("0.5")), (True, Decimal("0.5")), (10, Decimal("NaN")),
                                 (10, Decimal("Infinity")), (10, Decimal("-0.1")), (10, Decimal("1.01")),
                                 (10, EvilDecimal("0.5")), (10, 0.5), (EvilInt(10), Decimal("0.5")),
                                 (2**80, Decimal("0.5")), (10, None)])
def test_report_policy_rejects_hostile_values(bad):
    with pytest.raises(ValueError, match="REPORT_POLICY_INVALID"):
        ReportPolicy(*bad)


def test_forged_policy_and_other_bad_arguments_are_refused_without_raising():
    env = Env()
    forged_policy = object.__new__(ReportPolicy)
    forged_cell = object.__new__(GridCell)
    for kwargs in ({"policy": forged_policy}, {"grid": forged_cell}):
        result = env.build(A1, GOOD_SAMPLES, **kwargs) if "policy" in kwargs else build_report(
            A1, env, env, env.store, forged_cell, GOOD_SAMPLES, ReportPolicy(window_us=10), env.clock)
        assert result.reason is OpsReason.INPUT_INVALID
    for scope in (None, object.__new__(OpsScope), "t1", object()):
        assert build_report(scope, env, env, env.store, cell(), GOOD_SAMPLES, ReportPolicy(window_us=10),
                            env.clock).reason is OpsReason.INPUT_INVALID
    assert build_report(A1, env, env, None, cell(), GOOD_SAMPLES, ReportPolicy(window_us=10),
                        env.clock).reason is OpsReason.INPUT_INVALID
    assert build_report(A1, env, env, env.store, cell(), GOOD_SAMPLES, ReportPolicy(window_us=10),
                        object()).reason is OpsReason.INPUT_INVALID
    assert env.log == [] and env.store.count("t1") == 0


class _BadClock:
    def __init__(self, value):
        self._value = value

    def now(self):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


@pytest.mark.parametrize("value", [RuntimeError("POISON-clock"), None, "2026-01-01", datetime(2026, 1, 1)])  # noqa: DTZ001 - naive on purpose
def test_unusable_clock_fails_closed_and_stores_nothing(value):
    env = Env()
    result = build_report(A1, env, env, env.store, cell(), GOOD_SAMPLES, ReportPolicy(window_us=10),
                          _BadClock(value))
    assert result.reason is OpsReason.DEPENDENCY_FAILED and "POISON" not in repr(result)
    assert env.store.count("t1") == 0


# ======================================================================== basis and "proven"

def test_report_has_no_field_that_can_express_capacity_proven_or_a_pass():
    names = {f.name for f in dataclasses.fields(CapacityReport)}
    for name in names:
        low = name.lower()
        assert not any(w in low for w in ("proven", "proof", "passed", "verdict", "capacity_ok", "approved")), name
    assert "proven" not in {m.value.lower() for m in Basis}
    report = Env().build(A1, GOOD_SAMPLES)
    assert report.authority == AUTHORITY == "EVALUATION_ONLY"
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.basis = Basis.OPERATOR_REFERENCE  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):  # slots: no such attribute can be attached
        report.capacity_proven = True  # type: ignore[attr-defined]
    assert not hasattr(report, "capacity_proven")


def test_default_basis_is_scripted_and_operator_labelled_samples_without_a_reference_are_downgraded():
    env = Env()
    assert env.build(A1, GOOD_SAMPLES).basis is Basis.SCRIPTED_OFFLINE_FIXTURE
    labelled = [RequestSample(OK, 100, Basis.OPERATOR_REFERENCE)] * 30
    downgraded = env.build(A1, labelled)
    assert downgraded.basis is Basis.SCRIPTED_OFFLINE_FIXTURE and downgraded.measurement_ref_digest is None


def test_operator_reference_needs_a_well_formed_ref_and_operator_samples_and_still_has_no_proven_field():
    env = Env()
    env.auth.allow("a1", OPERATOR_REFERENCE_ACTION)
    ref = MeasurementRef("RUN-2026-10-10", "a" * 64)
    operator = [RequestSample(OK, 100 + i, Basis.OPERATOR_REFERENCE) for i in range(30)]
    report = env.build(A1, operator, measurement_ref=ref)
    assert report.basis is Basis.OPERATOR_REFERENCE and report.measurement_ref_digest == "a" * 64
    # a reference over scripted samples cannot upgrade them
    assert env.build(A1, GOOD_SAMPLES, measurement_ref=ref).reason is OpsReason.BASIS_NOT_REAL_MEASUREMENT
    assert env.build(A1, [], measurement_ref=ref).reason is OpsReason.BASIS_NOT_REAL_MEASUREMENT
    for bad in ("RUN-1", ("RUN", "a" * 64), object(), EvilStr("x"), 5):
        assert env.build(A1, operator, measurement_ref=bad).reason is OpsReason.BASIS_NOT_REAL_MEASUREMENT
    for args in (("", "a" * 64), ("RUN", "A" * 64), ("RUN", "a" * 63), ("RUN\x00", "a" * 64), (EvilStr("R"), "a" * 64),
                 ("RUN", EvilStr("a" * 64)), (None, None)):
        with pytest.raises(ValueError, match="MEASUREMENT_REF_INVALID"):
            MeasurementRef(*args)
    assert "RUN-2026" not in repr(ref)


# ================================================== ownership/entitlement before any read, tenants

def test_unentitled_actor_is_refused_first_and_nothing_is_stored():
    env = Env()
    result = env.build(OpsScope("t1", "c1", "stranger"), GOOD_SAMPLES)
    assert result.reason is OpsReason.NOT_ENTITLED
    assert [c[0] for c in env.log] == ["entitled"] and env.store.count("t1") == 0


def test_build_registers_the_owner_and_read_returns_the_same_report():
    env = Env()
    report = env.build(A1, GOOD_SAMPLES)
    assert env.owner.owns("t1", "c1", "report_id", report.report_id)
    assert env.read(A1, report.report_id) == report
    assert [c[0] for c in env.log][-2:] == ["entitled", "owns"]  # entitlement strictly before ownership


def test_foreign_and_unknown_report_ids_give_the_identical_refusal_and_port_calls():
    foreign_env, unknown_env = Env(), Env()
    foreign_report = foreign_env.build(B1, GOOD_SAMPLES)
    foreign_env.log.clear()
    unknown_env.build(B1, GOOD_SAMPLES)
    unknown_env.log.clear()
    foreign = foreign_env.read(A1, foreign_report.report_id)
    unknown = unknown_env.read(A1, "RPT-999999")
    assert type(foreign) is OpsRefusal and foreign.reason is OpsReason.NOT_FOUND
    assert (foreign.reason, foreign.next_action, foreign.authority) == (unknown.reason, unknown.next_action, unknown.authority)
    assert dataclasses.astuple(foreign)[:2] == dataclasses.astuple(unknown)[:2]
    assert [(c[0], c[3] if c[0] == "owns" else None) for c in foreign_env.log] == \
        [(c[0], c[3] if c[0] == "owns" else None) for c in unknown_env.log]
    assert len(foreign_env.log) == len(unknown_env.log) == 2


def test_a_report_of_another_company_in_the_same_tenant_is_not_found_not_forbidden():
    env = Env()
    env.ent.grant("t1", "a2", "c2")
    report = env.build(A1, GOOD_SAMPLES)
    result = env.read(OpsScope("t1", "c2", "a2"), report.report_id)
    assert result.reason is OpsReason.NOT_FOUND


@pytest.mark.parametrize("bad", [None, "", 5, EvilStr("RPT-000001"), "R\x00", "x" * 10_000, ["a"], object()])
def test_read_with_hostile_report_id_is_refused_before_any_port_call(bad):
    env = Env()
    result = env.read(A1, bad)
    assert result.reason is OpsReason.INPUT_INVALID and env.log == []


def test_ownership_without_a_stored_report_is_not_found():
    env = Env()
    env.owner.add("t1", "c1", "report_id", "RPT-777")
    assert env.read(A1, "RPT-777").reason is OpsReason.NOT_FOUND


def test_tenant_a_full_quota_leaves_tenant_b_untouched_and_the_refusal_mentions_nothing_of_b():
    env = Env(cap=2)
    b_report = env.build(B1, GOOD_SAMPLES)
    assert type(env.build(A1, GOOD_SAMPLES)) is CapacityReport and type(env.build(A1, GOOD_SAMPLES)) is CapacityReport
    refusal = env.build(A1, GOOD_SAMPLES)
    assert type(refusal) is OpsRefusal and refusal.reason is OpsReason.QUOTA_EXCEEDED
    text = repr(refusal) + str(dataclasses.asdict(refusal))
    assert "t2" not in text and "c9" not in text and b_report.report_id not in text
    assert env.store.count("t1") == 2 and env.store.count("t2") == 1
    assert env.read(B1, b_report.report_id) == b_report  # B's record is intact and still readable
    assert type(env.build(B1, GOOD_SAMPLES)) is CapacityReport  # B still has its own room
    assert env.build(B1, GOOD_SAMPLES).reason is OpsReason.QUOTA_EXCEEDED  # and its own cap


def test_quota_is_checked_after_ownership_and_before_compute():
    env = Env(cap=1)
    env.build(A1, GOOD_SAMPLES)
    env.log.clear()
    result = env.build(A1, GOOD_SAMPLES)
    assert result.reason is OpsReason.QUOTA_EXCEEDED
    assert [c[0] for c in env.log] == ["entitled"]  # no ownership refs for a build; quota after entitlement
    assert env.build(OpsScope("t1", "c1", "stranger"), GOOD_SAMPLES).reason is OpsReason.NOT_ENTITLED  # not an oracle


def test_owner_registration_failure_fails_closed_and_releases_the_slot():
    env = Env(cap=1)

    def broken(*args):
        raise RuntimeError("POISON-register")

    env.store = CapacityStore(1, FakeCorrelationSource("RPT"), broken, FakeCorrelationSource())
    result = env.build(A1, GOOD_SAMPLES)
    assert result.reason is OpsReason.DEPENDENCY_FAILED and "POISON" not in repr(result)
    assert env.store.count("t1") == 0


def test_store_constructor_rejects_bad_arguments():
    for cap in (0, True, "3", None):
        with pytest.raises(ValueError):
            CapacityStore(cap, FakeCorrelationSource(), lambda *a: None, FakeCorrelationSource())
    with pytest.raises(ValueError, match="CAPACITY_STORE_INVALID"):
        CapacityStore(1, FakeCorrelationSource(), None, FakeCorrelationSource())


def test_concurrent_builds_never_exceed_the_tenant_quota():
    env = Env(cap=4)
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(12)
    scopes = [A1] * 8 + [B1] * 4

    def worker(scope):
        barrier.wait()
        result = env.build(scope, GOOD_SAMPLES)
        with lock:
            results.append((scope.tenant_id, result))

    threads = [threading.Thread(target=worker, args=(scope,)) for scope in scopes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert env.store.count("t1") == 4 and env.store.count("t2") == 4
    ok_a = [r for t, r in results if t == "t1" and type(r) is CapacityReport]
    assert len(ok_a) == 4 and len({r.report_id for r in ok_a}) == 4
    assert all(r.reason is OpsReason.QUOTA_EXCEEDED for t, r in results if type(r) is OpsRefusal)
    assert sum(type(r) is CapacityReport for t, r in results if t == "t2") == 4


# ======================================================================== digest, determinism, repr

def test_report_digest_is_stable_across_identical_runs_and_changes_with_content():
    first = Env().build(A1, GOOD_SAMPLES)
    second = Env().build(A1, GOOD_SAMPLES)
    assert first == second and first.digest == second.digest and len(first.digest) == 64
    other = Env().build(A1, GOOD_SAMPLES[:98] + [s(OK, 999_999), GOOD_SAMPLES[99]])  # moves p99
    assert other.business[2].value != first.business[2].value and other.digest != first.digest
    assert is_valid_report(first)


def test_a_tampered_or_forged_report_is_invalid():
    report = Env().build(A1, GOOD_SAMPLES)
    with pytest.raises(ValueError, match="CAPACITY_REPORT_INVALID"):
        dataclasses.replace(report, throughput_per_s=Decimal(999))
    with pytest.raises(ValueError, match="CAPACITY_REPORT_INVALID"):
        dataclasses.replace(report, flags=(OpsReason.WITHIN_TARGET,))
    with pytest.raises(ValueError, match="CAPACITY_REPORT_INVALID"):
        dataclasses.replace(report, basis=Basis.OPERATOR_REFERENCE)
    with pytest.raises(ValueError, match="CAPACITY_REPORT_INVALID"):
        dataclasses.replace(report, authority="SOMETHING_ELSE")
    assert not is_valid_report(object.__new__(CapacityReport))
    for junk in (None, 1, "x", object()):
        assert not is_valid_report(junk)
    forged = object.__new__(CapacityReport)
    for f in dataclasses.fields(CapacityReport):
        object.__setattr__(forged, f.name, getattr(report, f.name))
    object.__setattr__(forged, "throughput_per_s", Decimal(1))
    assert not is_valid_report(forged)


def test_repr_and_refusals_of_every_output_contain_no_input_text():
    env = Env()
    scope = OpsScope("POISON-tenant", "POISON-company", "POISON-actor")
    env.ent.grant("POISON-tenant", "POISON-actor", "POISON-company")
    report = env.build(scope, GOOD_SAMPLES)
    summary = summarize(GOOD_SAMPLES, ids())
    outputs = [report, summary, percentile([1, 2, 3], 50), cell(), s(OK, 7), ReportPolicy(window_us=77_777),
               MeasurementRef("POISON-ref", "b" * 64), env.store, scope,
               env.build(OpsScope("POISON-tenant", "POISON-company", "other"), GOOD_SAMPLES),
               env.read(scope, "POISON-report"), make_sample("POISON-outcome", 1, ids())]
    for out in outputs:
        text = repr(out) + str(out)
        assert "POISON" not in text, type(out)
    assert "POISON" not in str(dataclasses.asdict(outputs[-1])) and "POISON" not in repr(report.report_id)


def test_summarize_hostile_and_config_limit_inputs():
    assert summarize(None, ids()).reason is OpsReason.INPUT_INVALID
    assert summarize([R1_LIMITS[LimitLayer.R1_SESSIONS]], ids()).reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    assert summarize([s(OK, 1), None], ids()).reason is OpsReason.INPUT_INVALID
    forged = object.__new__(RequestSample)
    assert summarize([forged], ids()).reason is OpsReason.INPUT_INVALID
    empty = summarize((), ids())
    assert empty.total == 0 and empty.business[0].reason is OpsReason.INSUFFICIENT_SAMPLES


# ============================================================ review fixes (S9 stream 3)

def test_j1_timeouts_dominating_flag_the_report_and_make_throughput_unreliable():
    samples = [s(OK, 1000 + i) for i in range(100)] + [s(OutcomeClass.TIMEOUT, 5_000_000 + i) for i in range(10_000)]
    report = Env().build(A1, samples)
    assert type(report) is CapacityReport
    assert "TIMEOUTS_DOMINATE" in report.failure_flags
    assert OpsReason.UNRELIABLE_REFUSALS in report.flags
    assert dict(report.counts)["TIMEOUT"] == 10_000 and dict(report.counts)["BUSINESS_OK"] == 100
    # timeouts have their OWN percentile set and never leak into the business one
    assert report.timeout_latency[1].value is not None and report.timeout_latency[1].value >= 5_000_000
    assert report.business[1].value < 5_000_000
    assert is_valid_report(report)


def test_j1_business_errors_dominating_are_flagged_separately():
    samples = [s(OK, 1000 + i) for i in range(100)] + [s(OutcomeClass.BUSINESS_ERROR, 10 + i) for i in range(1000)]
    report = Env().build(A1, samples)
    assert "BUSINESS_ERRORS_DOMINATE" in report.failure_flags and "TIMEOUTS_DOMINATE" not in report.failure_flags
    assert OpsReason.UNRELIABLE_REFUSALS in report.flags


def test_j1_a_healthy_mix_has_no_failure_flags_and_the_bound_is_strict():
    ok_only = Env().build(A1, GOOD_SAMPLES)
    assert ok_only.failure_flags == () and OpsReason.UNRELIABLE_REFUSALS not in ok_only.flags
    half = [s(OK, 100 + i) for i in range(50)] + [s(OutcomeClass.TIMEOUT, 900 + i) for i in range(50)]
    assert Env().build(A1, half).failure_flags == ()  # exactly at the 0.5 bound is not "dominating"
    over = [s(OK, 100 + i) for i in range(49)] + [s(OutcomeClass.TIMEOUT, 900 + i) for i in range(51)]
    assert Env().build(A1, over).failure_flags == ("TIMEOUTS_DOMINATE",)


def test_j1_summary_exposes_timeout_percentiles_and_counts():
    summary = summarize([s(OK, 1)] * 5 + [s(OutcomeClass.TIMEOUT, 7_000_000)] * 120, ids())
    assert summary.count_of(OutcomeClass.TIMEOUT) == 120
    assert summary.timeout_latency[2].value == 7_000_000
    few = summarize([s(OutcomeClass.TIMEOUT, 5)] * 3, ids())
    assert few.timeout_latency[1].reason is OpsReason.INSUFFICIENT_SAMPLES


def test_j1_failure_flags_are_digest_bound():
    samples = [s(OK, 1000)] * 10 + [s(OutcomeClass.TIMEOUT, 5)] * 100
    report = Env().build(A1, samples)
    assert is_valid_report(report)
    with pytest.raises(ValueError, match="CAPACITY_REPORT_INVALID"):
        dataclasses.replace(report, failure_flags=())  # digest no longer matches


@pytest.mark.parametrize("answer", [None, False, 0, "yes"])
def test_j2_owner_registration_that_does_not_confirm_rolls_the_report_back(answer):
    env = Env()
    env.store = CapacityStore(3, FakeCorrelationSource("RPT"), lambda *a: answer, FakeCorrelationSource())
    result = env.build(A1, GOOD_SAMPLES)
    assert type(result) is OpsRefusal and result.reason is OpsReason.DEPENDENCY_FAILED
    assert env.store.count("t1") == 0


def test_j2_ownership_overflow_never_leaves_a_stored_but_unreadable_report(monkeypatch):
    import business_ai_gateway.phase2.workbench_types as wt

    env = Env()
    monkeypatch.setattr(wt, "_MAX_PORT_ROWS", 0)  # FakeOwnership.add now silently ignores every write
    result = env.build(A1, GOOD_SAMPLES)
    assert type(result) is OpsRefusal and result.reason is OpsReason.DEPENDENCY_FAILED
    assert env.store.count("t1") == 0  # no quota-consuming report that read_report would answer NOT_FOUND for


def test_j3_operator_reference_needs_an_authorized_actor():
    ref = MeasurementRef("RUN-1", "a" * 64)
    operator = [RequestSample(OK, 100 + i, Basis.OPERATOR_REFERENCE) for i in range(30)]
    env = Env()
    denied = env.build(A1, operator, measurement_ref=ref)
    assert type(denied) is OpsRefusal and denied.reason is OpsReason.NOT_AUTHORIZED and env.store.count("t1") == 0
    env.auth.allow("a1", OPERATOR_REFERENCE_ACTION)
    env.auth.deny("a1", OPERATOR_REFERENCE_ACTION)  # deny wins
    assert env.build(A1, operator, measurement_ref=ref).reason is OpsReason.NOT_AUTHORIZED
    assert env.build(A1, operator, measurement_ref=ref, operator_authority=None).reason is OpsReason.NOT_AUTHORIZED
    assert env.build(A1, operator, measurement_ref=ref, operator_authority=object()).reason is OpsReason.NOT_AUTHORIZED
    ok = Env()
    ok.auth.allow("a1", OPERATOR_REFERENCE_ACTION)
    assert ok.build(A1, operator, measurement_ref=ref).basis is Basis.OPERATOR_REFERENCE
    # an authority entry for another actor/action does not help
    other = Env()
    other.auth.allow("a1", "some.other.action")
    other.auth.allow("zz", OPERATOR_REFERENCE_ACTION)
    assert other.build(A1, operator, measurement_ref=ref).reason is OpsReason.NOT_AUTHORIZED


def test_j3_entitlement_is_still_asked_before_operator_authority_and_scripted_needs_no_authority():
    env = Env()
    ref = MeasurementRef("RUN-1", "a" * 64)
    operator = [RequestSample(OK, 100 + i, Basis.OPERATOR_REFERENCE) for i in range(30)]
    stranger = env.build(OpsScope("t1", "c1", "stranger"), operator, measurement_ref=ref)
    assert stranger.reason is OpsReason.NOT_ENTITLED
    assert env.build(A1, GOOD_SAMPLES, operator_authority=None).basis is Basis.SCRIPTED_OFFLINE_FIXTURE
