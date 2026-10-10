"""S9 E1 background interference (TC129): exact ratio, budget plan with guaranteed background minimum,
capture/writer caps, per-tenant sub-share over the reused PhysicalBackendBudget. Refusal rows first."""
# ruff: noqa: SIM117  (nested reservations are deliberate: the nesting order is the scenario)
import dataclasses
import threading
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.backend_budget import (
    BackendCapacityError,
    BackendId,
    PhysicalBackendBudget,
)
from business_ai_gateway.phase2.capacity_interference import (
    DEFAULT_INTERFERENCE_TARGET,
    TARGET_LABEL,
    BudgetPlan,
    BudgetPolicy,
    DemandItem,
    InterferenceResult,
    SubShareDenied,
    TenantSubShare,
    WorkClass,
    interference,
    make_policy,
    plan_budget,
)
from business_ai_gateway.phase2.capacity_model import (
    R1_LIMITS,
    LimitLayer,
    MeasurementRef,
    PercentileValue,
    percentile,
)
from business_ai_gateway.phase2.ops_types import (
    Basis,
    FakeCorrelationSource,
    OpsReason,
    OpsRefusal,
)


class EvilInt(int):
    def __eq__(self, other):
        return True

    __hash__ = int.__hash__


class EvilDecimal(Decimal):
    pass


def ids():
    return FakeCorrelationSource()


# ============================================================ interference ratio

def test_default_target_is_the_proposed_twenty_percent_and_labelled():
    assert DEFAULT_INTERFERENCE_TARGET == Decimal("0.20")
    assert TARGET_LABEL == "proposed target, not a measured guarantee"
    result = interference(100, 110)
    assert result.target == Decimal("0.20") and result.target_label == TARGET_LABEL


def test_ratio_below_equal_and_above_target_are_exact():
    below, equal, above = interference(100, 119), interference(100, 120), interference(100, 121)
    assert (below.reason, equal.reason, above.reason) == (
        OpsReason.WITHIN_TARGET, OpsReason.WITHIN_TARGET, OpsReason.EXCEEDS_TARGET)
    assert (below.ratio, equal.ratio, above.ratio) == (Decimal("0.190000"), Decimal("0.200000"), Decimal("0.210000"))


def test_verdict_uses_the_exact_comparison_not_the_rounded_ratio():
    # 1_000_001 vs 5_000_000: diff 1/5_000_000 above 20% would round to 0.200000 but is exactly above target
    result = interference(5_000_000, 6_000_001)
    assert result.ratio == Decimal("0.200000") and result.reason is OpsReason.EXCEEDS_TARGET
    assert interference(5_000_000, 6_000_000).reason is OpsReason.WITHIN_TARGET


def test_faster_under_load_is_within_target_with_negative_ratio():
    result = interference(200, 100)
    assert result.reason is OpsReason.WITHIN_TARGET and result.ratio == Decimal("-0.500000")
    assert interference(100, 0).ratio == Decimal("-1.000000")


def test_custom_target_is_honoured():
    assert interference(100, 150, Decimal("0.5")).reason is OpsReason.WITHIN_TARGET
    assert interference(100, 151, Decimal("0.5")).reason is OpsReason.EXCEEDS_TARGET
    assert interference(100, 100, Decimal(0)).reason is OpsReason.WITHIN_TARGET
    assert interference(100, 101, Decimal(0)).reason is OpsReason.EXCEEDS_TARGET


@pytest.mark.parametrize("baseline", [0, None, -1, True, 1.5, "100", EvilInt(100), 2**80, 3_600_000_001, [1], object()])
def test_baseline_zero_missing_or_hostile_is_baseline_invalid(baseline):
    result = interference(baseline, 100)
    assert result.reason is OpsReason.BASELINE_INVALID and result.ratio is None


@pytest.mark.parametrize("loaded", [None, -1, True, 1.5, "100", EvilInt(100), 2**80, [1], object()])
def test_hostile_loaded_value_is_input_invalid_not_within_target(loaded):
    result = interference(100, loaded)
    assert result.reason is OpsReason.INPUT_INVALID and result.ratio is None


@pytest.mark.parametrize("target", [None, 0.2, "0.2", 1, Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"),
                                    Decimal(101), EvilDecimal("0.2"), True])
def test_hostile_target_is_refused(target):
    result = interference(100, 100, target)
    assert result.reason is OpsReason.INPUT_INVALID and result.target is None


def test_config_limits_are_not_capacity_numbers():
    pool = R1_LIMITS[LimitLayer.R1_POOL]
    assert interference(pool, 100).reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY
    assert interference(100, pool).reason is OpsReason.CONFIG_LIMIT_NOT_CAPACITY


def test_percentile_values_are_accepted_and_insufficient_ones_are_not_numbers():
    base = percentile(list(range(1000, 1020)), 95)
    loaded = percentile(list(range(1000, 1020)), 95)
    assert interference(base, loaded).reason is OpsReason.WITHIN_TARGET
    short = percentile([1, 2, 3], 95)
    assert interference(short, loaded).reason is OpsReason.BASELINE_INVALID
    assert interference(base, short).reason is OpsReason.INSUFFICIENT_SAMPLES
    forged = object.__new__(PercentileValue)
    assert interference(forged, 100).reason is OpsReason.BASELINE_INVALID
    assert interference(100, forged).reason is OpsReason.INPUT_INVALID


def test_result_is_scripted_by_default_digest_bound_and_has_no_proven_field():
    result = interference(100, 130)
    assert result.basis is Basis.SCRIPTED_OFFLINE_FIXTURE and result.authority == "EVALUATION_ONLY"
    assert not [f.name for f in dataclasses.fields(InterferenceResult) if "proven" in f.name or "passed" in f.name]
    assert result == interference(100, 130) and result.digest != interference(100, 131).digest
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.reason = OpsReason.WITHIN_TARGET  # type: ignore[misc]
    with pytest.raises(ValueError, match="INTERFERENCE_RESULT_INVALID"):
        dataclasses.replace(result, authority="OTHER")
    assert "130" not in repr(result)


def test_operator_reference_changes_only_the_label_and_malformed_reference_is_refused():
    ref = MeasurementRef("RUN-1", "c" * 64)
    assert interference(100, 110, measurement_ref=ref).basis is Basis.OPERATOR_REFERENCE
    for bad in ("RUN-1", object(), 5):
        assert interference(100, 110, measurement_ref=bad).reason is OpsReason.BASIS_NOT_REAL_MEASUREMENT


# ============================================================ policy

@pytest.mark.parametrize("minimum", [0, -1, -100])
def test_a_policy_that_lets_background_starve_is_refused(minimum):
    result = make_policy(min_background_slots=minimum, tenant_share_slots=2, ids=ids())
    assert type(result) is OpsRefusal and result.reason is OpsReason.BACKGROUND_STARVED


@pytest.mark.parametrize("bad", [True, 1.0, "1", None, EvilInt(1), 2**40])
def test_hostile_policy_values_are_input_invalid(bad):
    assert make_policy(min_background_slots=bad, tenant_share_slots=2, ids=ids()).reason is OpsReason.INPUT_INVALID
    assert make_policy(min_background_slots=1, tenant_share_slots=bad, ids=ids()).reason is OpsReason.INPUT_INVALID
    assert make_policy(min_background_slots=1, tenant_share_slots=2, capture_per_backend=bad,
                       ids=ids()).reason is OpsReason.INPUT_INVALID
    assert make_policy(min_background_slots=1, tenant_share_slots=2, writer_per_source=bad,
                       ids=ids()).reason is OpsReason.INPUT_INVALID
    with pytest.raises(ValueError, match="BUDGET_POLICY_INVALID"):
        BudgetPolicy(bad, 2)


def test_conservative_defaults_are_capture_one_per_backend_and_writer_one_per_source():
    policy = BudgetPolicy(min_background_slots=1, tenant_share_slots=4)
    assert (policy.capture_per_backend, policy.writer_per_source) == (1, 1)
    assert type(make_policy(min_background_slots=1, tenant_share_slots=4, ids=ids())) is BudgetPolicy


# ============================================================ plan_budget

def item(tenant="t1", backend="db-1", source="s1", work=WorkClass.INTERACTIVE, count=1):
    return DemandItem(tenant, backend, source, work, count)


def budget(per=4, total=8):
    return PhysicalBackendBudget(per_backend_limit=per, total_limit=total)


def plan(demand, per=4, total=8, minimum=1, share=100, **kw):
    policy = BudgetPolicy(min_background_slots=minimum, tenant_share_slots=share, **kw)
    result = plan_budget(policy, demand, budget(per, total), ids())
    assert type(result) is BudgetPlan, result
    return result


def granted(result):
    return [a.granted for a in result.allocations]


I, B, C, W = WorkClass.INTERACTIVE, WorkClass.BACKGROUND, WorkClass.CAPTURE, WorkClass.WRITER


def test_interactive_pressure_never_takes_the_guaranteed_background_minimum():
    result = plan([item(count=100), item(tenant="t2", source="s2", work=B, count=2)])
    assert granted(result) == [3, 1]  # 4 slots: 1 guaranteed to background, interactive gets the other 3
    assert result.allocations[0].reason is OpsReason.BACKEND_BUDGET_EXCEEDED and result.allocations[0].deferred == 97
    assert result.allocations[1].granted >= result.min_background_slots == 1
    assert result.allocations[1].reason is OpsReason.BACKEND_BUDGET_EXCEEDED and result.allocations[1].deferred == 1


def test_background_minimum_is_honoured_for_every_interactive_load_and_order():
    for interactive in (1, 3, 4, 5, 50, 10_000):
        for first_interactive in (True, False):
            demand = [item(count=interactive), item(source="s2", work=B, count=1)]
            result = plan(demand if first_interactive else demand[::-1])
            bg_index = 1 if first_interactive else 0
            assert result.allocations[bg_index].granted == 1, (interactive, first_interactive)


def test_minimum_larger_than_one_and_unused_guarantee_goes_to_interactive():
    result = plan([item(count=10), item(source="s2", work=B, count=5)], per=6, minimum=2)
    assert granted(result) == [4, 2]
    only_interactive = plan([item(count=10)], per=6, minimum=2)
    assert granted(only_interactive) == [6]  # no background demand: nothing is withheld


def test_background_takes_what_interactive_leaves():
    result = plan([item(count=1), item(source="s2", work=B, count=10)])
    assert granted(result) == [1, 3] and result.interactive_granted == 1 and result.background_granted == 3


def test_a_budget_that_cannot_keep_a_slot_for_interactive_is_refused_not_silently_planned():
    policy = BudgetPolicy(min_background_slots=4, tenant_share_slots=4)
    assert plan_budget(policy, [item()], budget(4, 8), ids()).reason is OpsReason.BACKEND_BUDGET_EXCEEDED
    assert plan_budget(BudgetPolicy(1, 4), [item()], budget(1, 1), ids()).reason is OpsReason.BACKEND_BUDGET_EXCEEDED


def test_capture_is_one_per_backend_and_writer_is_one_per_source():
    result = plan([item(tenant="t1", work=C), item(tenant="t2", work=C), item(tenant="t3", backend="db-2", work=C)])
    assert granted(result) == [1, 0, 1]
    assert result.allocations[1].reason is OpsReason.BACKEND_BUDGET_EXCEEDED
    result = plan([item(source="s1", work=W), item(source="s1", backend="db-2", work=W), item(source="s2", work=W)])
    assert granted(result) == [1, 0, 1]
    assert result.allocations[1].reason is OpsReason.BACKEND_BUDGET_EXCEEDED
    wide = plan([item(work=C, count=5)], capture_per_backend=2)
    assert granted(wide) == [2] and wide.allocations[0].deferred == 3


def test_tenant_at_its_share_cannot_take_other_tenants_slots():
    result = plan([item(tenant="A", count=10), item(tenant="B", source="s2", count=6)], per=10, total=20, share=4)
    assert granted(result) == [4, 4]  # B is capped by the same share, not starved by A
    assert result.allocations[0].reason is OpsReason.TENANT_SHARE_EXCEEDED
    assert result.allocations[0].deferred == 6
    other = plan([item(tenant="A", count=10), item(tenant="B", source="s2", count=3)], per=10, total=20, share=4)
    assert granted(other) == [4, 3] and other.allocations[1].reason is None


def test_tenant_share_is_per_backend():
    result = plan([item(tenant="A", backend="db-1", count=9), item(tenant="A", backend="db-2", count=9)],
                  per=10, total=20, share=4)
    assert granted(result) == [4, 4]


def test_alias_backend_ids_share_one_counter_in_the_plan():
    result = plan([item(backend="DB-1", count=3), item(backend=" db-1 ", count=3), item(backend="db-1.", count=3)])
    assert granted(result) == [3, 1, 0]
    assert plan([item(backend="db-1", count=3), item(backend="db-2", count=3)]).allocations[1].granted == 3


def test_total_limit_bounds_the_sum_over_backends():
    result = plan([item(backend="db-1", count=4), item(backend="db-2", count=4)], per=4, total=5)
    assert granted(result) == [4, 1]


def test_plan_is_deterministic_digest_bound_stamped_and_text_free():
    demand = [item(tenant="POISON-tenant", source="POISON-source", count=2), item(work=B, count=1)]
    first, second = plan(demand), plan(demand)
    assert first == second and first.digest == second.digest and len(first.digest) == 64
    assert first.digest != plan([item(tenant="other", source="POISON-source", count=2), item(work=B)]).digest
    assert first.basis is Basis.SCRIPTED_OFFLINE_FIXTURE and first.authority == "EVALUATION_ONLY"
    text = repr(first) + str(first.allocations) + repr(demand[0])
    assert "POISON" not in text
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.digest = "x"  # type: ignore[misc]


def test_plan_reads_the_budget_but_never_reserves_from_it():
    shared = budget(4, 8)
    plan_budget(BudgetPolicy(1, 4), [item(count=3)], shared, ids())
    assert shared.active_total == 0


@pytest.mark.parametrize("bad", [None, "x", 5, [None], [object()], [("t1", "db-1")], {"a": 1}, (item(), None)])
def test_hostile_demand_is_refused_not_raised(bad):
    result = plan_budget(BudgetPolicy(1, 4), bad, budget(), ids())
    assert type(result) is OpsRefusal and result.reason is OpsReason.INPUT_INVALID


def test_oversize_subclassed_forged_and_recursive_demand_is_refused():
    policy = BudgetPolicy(1, 4)

    class L(list):
        pass

    assert plan_budget(policy, [item()] * 1025, budget(), ids()).reason is OpsReason.INPUT_INVALID
    assert plan_budget(policy, L([item()]), budget(), ids()).reason is OpsReason.INPUT_INVALID
    assert plan_budget(policy, [object.__new__(DemandItem)], budget(), ids()).reason is OpsReason.INPUT_INVALID
    loop: list = []
    loop.append(loop)
    assert plan_budget(policy, loop, budget(), ids()).reason is OpsReason.INPUT_INVALID
    for bad_backend in ("", "bad backend!", "x" * 300, "db\x001", "Ünï"):
        try:
            demand = [item(backend=bad_backend)]
        except ValueError:
            continue
        assert plan_budget(policy, demand, budget(), ids()).reason is OpsReason.INPUT_INVALID


@pytest.mark.parametrize("args", [(None, "db-1", "s", I, 1), ("", "db-1", "s", I, 1), ("t", 5, "s", I, 1),
                                  ("t", "db-1", "t\u200b", I, 1), ("t", "db-1", "s", "INTERACTIVE", 1),
                                  ("t", "db-1", "s", I, 0), ("t", "db-1", "s", I, True), ("t", "db-1", "s", I, 10_001),
                                  ("t", "db-1", "s", I, EvilInt(1))])
def test_demand_item_rejects_hostile_fields(args):
    with pytest.raises(ValueError, match="DEMAND_ITEM_INVALID"):
        DemandItem(*args)


def test_bad_policy_or_budget_objects_are_refused():
    assert plan_budget(object.__new__(BudgetPolicy), [item()], budget(), ids()).reason is OpsReason.INPUT_INVALID
    assert plan_budget(BudgetPolicy(1, 4), [item()], object(), ids()).reason is OpsReason.INPUT_INVALID
    assert plan_budget(None, [item()], budget(), ids()).reason is OpsReason.INPUT_INVALID


# ============================================================ runtime: shared budget + sub-share

def bid(raw="db-1"):
    return BackendId.normalize(raw)


def test_alias_backend_ids_share_one_counter_in_the_reused_budget():
    shared = PhysicalBackendBudget(per_backend_limit=1, total_limit=5)
    with shared.reserve(trusted_backend_id=BackendId.normalize("DB-1")):
        with pytest.raises(BackendCapacityError, match="BACKEND_CAPACITY_EXCEEDED"):
            with shared.reserve(trusted_backend_id=BackendId.normalize(" db-1 ")):
                pass
        with shared.reserve(trusted_backend_id=bid("db-2")):
            assert shared.active_total == 2
    assert shared.active_total == 0


def test_sub_share_limits_per_tenant_and_releases_on_exit_and_on_exception():
    shared = PhysicalBackendBudget(per_backend_limit=5, total_limit=10)
    gate = TenantSubShare(shared, 2)
    with gate.reserve(tenant_id="A", backend_id=bid()):
        with gate.reserve(tenant_id="A", backend_id=bid()):
            with pytest.raises(SubShareDenied) as info:
                with gate.reserve(tenant_id="A", backend_id=bid()):
                    pass
            assert info.value.reason is OpsReason.TENANT_SHARE_EXCEEDED and str(info.value) == "TENANT_SHARE_EXCEEDED"
            with gate.reserve(tenant_id="B", backend_id=bid()):  # B has its own share
                assert shared.active_total == 3
    assert shared.active_total == 0 and gate.active("A", bid()) == 0
    with pytest.raises(RuntimeError, match="BOOM"):
        with gate.reserve(tenant_id="A", backend_id=bid()):
            raise RuntimeError("BOOM")
    assert shared.active_total == 0 and gate.active("A", bid()) == 0


def test_shared_budget_is_the_only_global_limiter_and_denial_returns_the_tenant_slot():
    shared = PhysicalBackendBudget(per_backend_limit=2, total_limit=2)
    gate = TenantSubShare(shared, 5)
    with gate.reserve(tenant_id="A", backend_id=bid()), gate.reserve(tenant_id="B", backend_id=bid()):
        with pytest.raises(SubShareDenied) as info:
            with gate.reserve(tenant_id="C", backend_id=bid()):
                pass
        assert info.value.reason is OpsReason.BACKEND_BUDGET_EXCEEDED
        assert gate.active("C", bid()) == 0  # the tenant slot taken first was handed back
    assert shared.active_total == 0


def test_sub_share_hostile_input_is_denied_with_fixed_reasons():
    gate = TenantSubShare(budget(), 2)
    for tenant in (None, "", 5, "t\x00", "t\u200b"):
        with pytest.raises(SubShareDenied) as info:
            with gate.reserve(tenant_id=tenant, backend_id=bid()):
                pass
        assert info.value.reason is OpsReason.INPUT_INVALID
    for backend in ("db-1", None, object(), object.__new__(BackendId)):
        with pytest.raises(SubShareDenied) as info:
            with gate.reserve(tenant_id="A", backend_id=backend):
                pass
        assert info.value.reason is OpsReason.INPUT_INVALID
    with pytest.raises(ValueError, match="SUB_SHARE_INVALID"):
        TenantSubShare(object(), 2)
    with pytest.raises(ValueError, match="TENANT_LIMIT_INVALID"):
        TenantSubShare(budget(), 0)
    assert "A" not in repr(gate)


def test_two_tenants_never_exceed_their_shares_or_the_shared_limit_under_threads():
    shared = PhysicalBackendBudget(per_backend_limit=5, total_limit=5)
    gate = TenantSubShare(shared, 2)
    attempts = 14
    barrier = threading.Barrier(attempts + 1)
    release = threading.Event()
    results: list[tuple[str, bool]] = []
    lock = threading.Lock()

    def worker(tenant):
        ok = False
        try:
            with gate.reserve(tenant_id=tenant, backend_id=bid()):
                ok = True
                with lock:
                    results.append((tenant, True))
                barrier.wait()
                release.wait(10)
        except SubShareDenied:
            with lock:
                results.append((tenant, False))
            barrier.wait()
        assert ok in (True, False)

    threads = [threading.Thread(target=worker, args=("A" if i % 2 else "B",)) for i in range(attempts)]
    for t in threads:
        t.start()
    barrier.wait()  # every attempt has either reserved or been denied; reservations are still held
    won = [tenant for tenant, ok in results if ok]
    assert shared.active_total == len(won) <= 5
    assert won.count("A") <= 2 and won.count("B") <= 2 and len(won) == 4
    assert gate.active("A", bid()) == won.count("A") and gate.active("B", bid()) == won.count("B")
    release.set()
    for t in threads:
        t.join()
    assert shared.active_total == 0 and gate.active("A", bid()) == 0 and gate.active("B", bid()) == 0
