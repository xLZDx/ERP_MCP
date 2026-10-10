"""S9 E3 (R2-US-045, TC133): typed step classification, rehearsal planning, shadow comparison."""
import dataclasses
import itertools

import pytest

from business_ai_gateway.phase2.ops_types import (
    AUTHORITY,
    FakeCorrelationSource,
    OpsReason,
    OpsRefusal,
    is_valid_refusal,
)
from business_ai_gateway.phase2.release_migration import (
    R1_OBJECT_CLASSES,
    MigrationStep,
    MigrationUnit,
    ObjectClass,
    Phase,
    RehearsalAction,
    RehearsalPlan,
    SchemaName,
    ShadowObservation,
    ShadowResult,
    StepClass,
    StepKind,
    classify_step,
    compare_shadow,
    is_operation_id,
    plan_rehearsal,
)

IDS = FakeCorrelationSource()
D1, D2, D3 = "a" * 64, "b" * 64, "c" * 64


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


def step(kind, phase=Phase.EXPAND, schema=SchemaName.LIVING, oc=ObjectClass.TABLE):
    return MigrationStep(phase, kind, schema, oc)


def add(version, requires=(), kinds=1):
    return MigrationUnit(version, tuple(requires),
                         tuple(step(StepKind.CREATE_TABLE) for _ in range(kinds)))


def refused(result, reason):
    assert type(result) is OpsRefusal and is_valid_refusal(result)
    assert result.reason is reason


DESTRUCTIVE_KINDS = [StepKind.DROP_TABLE, StepKind.DROP_COLUMN, StepKind.DROP_INDEX,
                     StepKind.DROP_FUNCTION, StepKind.DROP_TRIGGER, StepKind.DROP_POLICY,
                     StepKind.DROP_SCHEMA, StepKind.DROP_ROLE, StepKind.TRUNCATE,
                     StepKind.ALTER_TYPE, StepKind.RENAME, StepKind.REVOKE, StepKind.DELETE_ROWS,
                     StepKind.UPDATE_ROWS, StepKind.NARROW_CONSTRAINT]


# ---- classification -------------------------------------------------------------------------------

def test_step_class_values_are_ops_reason_codes():
    for cls in StepClass:
        assert cls.as_reason() is OpsReason(cls.value)


@pytest.mark.parametrize("kind,oc", [
    (StepKind.CREATE_SCHEMA, ObjectClass.SCHEMA), (StepKind.CREATE_TABLE, ObjectClass.TABLE),
    (StepKind.CREATE_INDEX, ObjectClass.INDEX), (StepKind.ADD_NULLABLE_COLUMN, ObjectClass.COLUMN),
    (StepKind.ADD_DEFAULTED_COLUMN, ObjectClass.COLUMN), (StepKind.ADD_FUNCTION, ObjectClass.FUNCTION),
    (StepKind.REPLACE_FUNCTION, ObjectClass.FUNCTION), (StepKind.ADD_TRIGGER, ObjectClass.TRIGGER),
    (StepKind.REPLACE_TRIGGER, ObjectClass.TRIGGER), (StepKind.ADD_POLICY, ObjectClass.POLICY),
    (StepKind.REPLACE_POLICY, ObjectClass.POLICY), (StepKind.ENABLE_RLS, ObjectClass.TABLE),
    (StepKind.ADD_ROLE, ObjectClass.ROLE), (StepKind.GRANT, ObjectClass.PRIVILEGE),
    (StepKind.HARDEN_PRIVILEGES, ObjectClass.PRIVILEGE), (StepKind.SET_OWNER, ObjectClass.TABLE),
    (StepKind.SET_OWNER, ObjectClass.FUNCTION), (StepKind.HARDEN_FUNCTION, ObjectClass.FUNCTION),
    (StepKind.INSERT_ROWS, ObjectClass.ROW_DATA),
])
def test_additive_kinds_in_expand_and_shadow(kind, oc):
    for phase in (Phase.EXPAND, Phase.SHADOW):
        assert classify_step(step(kind, phase, oc=oc)) is StepClass.ADDITIVE
    for phase in (Phase.SWITCH, Phase.CONTRACT):  # an additive kind outside expand/shadow is unknown
        assert classify_step(step(kind, phase, oc=oc)) is StepClass.UNCLASSIFIED


def test_switch_and_contract_kinds_only_in_their_own_phase():
    flag = ObjectClass.FEATURE_FLAG
    assert classify_step(step(StepKind.FEATURE_FLAG, Phase.SWITCH, oc=flag)) is StepClass.SWITCH_ONLY
    assert classify_step(step(StepKind.ROUTE_SWITCH, Phase.SWITCH, oc=ObjectClass.ROUTE)) \
        is StepClass.SWITCH_ONLY
    assert classify_step(step(StepKind.RETIRE_FEATURE_FLAG, Phase.CONTRACT, oc=flag)) \
        is StepClass.CONTRACT
    assert classify_step(step(StepKind.RETIRE_ROUTE, Phase.CONTRACT, oc=ObjectClass.ROUTE)) \
        is StepClass.CONTRACT
    for phase in (Phase.EXPAND, Phase.SHADOW, Phase.CONTRACT):
        assert classify_step(step(StepKind.FEATURE_FLAG, phase, oc=flag)) is StepClass.UNCLASSIFIED
    for phase in (Phase.EXPAND, Phase.SHADOW, Phase.SWITCH):
        assert classify_step(step(StepKind.RETIRE_FEATURE_FLAG, phase, oc=flag)) \
            is StepClass.UNCLASSIFIED


def test_additive_kind_on_a_wrong_object_class_is_unclassified():
    assert classify_step(step(StepKind.CREATE_TABLE, oc=ObjectClass.ROW_DATA)) is StepClass.UNCLASSIFIED
    assert classify_step(step(StepKind.INSERT_ROWS, oc=ObjectClass.TABLE)) is StepClass.UNCLASSIFIED
    assert classify_step(step(StepKind.FEATURE_FLAG, Phase.SWITCH, oc=ObjectClass.ROUTE)) \
        is StepClass.UNCLASSIFIED


def test_every_destructive_kind_is_destructive_in_every_phase_and_object_class():
    non_r1 = [c for c in ObjectClass if c not in R1_OBJECT_CLASSES]
    for kind, phase, oc in itertools.product(DESTRUCTIVE_KINDS, Phase, non_r1):
        assert classify_step(step(kind, phase, oc=oc)) is StepClass.DESTRUCTIVE


def test_planted_drop_table_is_destructive_and_never_additive():
    planted = step(StepKind.DROP_TABLE, Phase.EXPAND)  # disguised as an expand step
    assert classify_step(planted) is StepClass.DESTRUCTIVE
    assert StepKind.DROP_RELATION is StepKind.DROP_TABLE  # an alias is the very same member
    assert classify_step(step(StepKind.DROP_RELATION, Phase.EXPAND)) is StepClass.DESTRUCTIVE


def test_nothing_in_the_whole_type_space_turns_a_destructive_or_r1_step_additive():
    for phase, kind, schema, oc in itertools.product(Phase, StepKind, SchemaName, ObjectClass):
        result = classify_step(MigrationStep(phase, kind, schema, oc))
        if schema is SchemaName.R1 or oc in R1_OBJECT_CLASSES:
            assert result is StepClass.UNCLASSIFIED
        elif kind in DESTRUCTIVE_KINDS:
            assert result is StepClass.DESTRUCTIVE
        else:
            assert result in (StepClass.ADDITIVE, StepClass.SWITCH_ONLY, StepClass.CONTRACT,
                              StepClass.UNCLASSIFIED)


def test_r1_schema_or_r1_object_class_is_unclassified_even_for_additive_or_destructive_kinds():
    assert classify_step(step(StepKind.CREATE_TABLE, schema=SchemaName.R1)) is StepClass.UNCLASSIFIED
    assert classify_step(step(StepKind.DROP_TABLE, schema=SchemaName.R1)) is StepClass.UNCLASSIFIED
    for oc in R1_OBJECT_CLASSES:
        for kind in (StepKind.CREATE_TABLE, StepKind.DROP_TABLE, StepKind.GRANT, StepKind.REVOKE):
            assert classify_step(step(kind, oc=oc)) is StepClass.UNCLASSIFIED


def test_unknown_kind_string_and_non_enum_fields_are_unclassified():
    assert classify_step(MigrationStep(Phase.EXPAND, "DROP_EVERYTHING", SchemaName.LIVING,
                                       ObjectClass.TABLE)) is StepClass.UNCLASSIFIED
    assert classify_step(MigrationStep(Phase.EXPAND, "CREATE_TABLE", SchemaName.LIVING,
                                       ObjectClass.TABLE)) is StepClass.UNCLASSIFIED  # str, not the enum
    assert classify_step(MigrationStep(Phase.EXPAND, EvilStr("CREATE_TABLE"), SchemaName.LIVING,
                                       ObjectClass.TABLE)) is StepClass.UNCLASSIFIED
    assert classify_step(MigrationStep("EXPAND", StepKind.CREATE_TABLE, SchemaName.LIVING,
                                       ObjectClass.TABLE)) is StepClass.UNCLASSIFIED
    assert classify_step(MigrationStep(Phase.EXPAND, StepKind.CREATE_TABLE, "LIVING",
                                       ObjectClass.TABLE)) is StepClass.UNCLASSIFIED
    assert classify_step(MigrationStep(Phase.EXPAND, StepKind.CREATE_TABLE, SchemaName.LIVING,
                                       "TABLE")) is StepClass.UNCLASSIFIED
    assert classify_step(MigrationStep(None, None, None, None)) is StepClass.UNCLASSIFIED


def test_classify_step_is_total_on_hostile_objects():
    forged = object.__new__(MigrationStep)  # slots never set
    recursive = []
    recursive.append(recursive)
    for junk in (None, 5, "CREATE_TABLE", b"x", object(), forged, recursive, [step(StepKind.GRANT)],
                 {"kind": "GRANT"}, EvilStr("ADDITIVE")):
        assert classify_step(junk) is StepClass.UNCLASSIFIED


def test_a_step_subclass_cannot_lie_about_its_class():
    @dataclasses.dataclass(frozen=True)
    class Sub(MigrationStep):
        pass

    assert classify_step(Sub(Phase.EXPAND, StepKind.CREATE_TABLE, SchemaName.LIVING,
                             ObjectClass.TABLE)) is StepClass.UNCLASSIFIED


def test_classification_result_is_the_exact_enum_and_repr_has_no_field_text():
    out = classify_step(step(StepKind.CREATE_TABLE))
    assert type(out) is StepClass
    assert "CREATE_TABLE" not in repr(step(StepKind.CREATE_TABLE))


# ---- rehearsal planning ---------------------------------------------------------------------------

def real_units():
    return [add("001"), add("002", ["001"]), add("003", ["001", "002"])]


def test_rehearsal_orders_the_real_set_and_applies_everything_on_a_fresh_database():
    plan = plan_rehearsal(real_units(), [], IDS)
    assert type(plan) is RehearsalPlan
    assert [(a.version, a.apply) for a in plan.actions] == [("001", True), ("002", True), ("003", True)]
    assert plan.executed is False and plan.authority == AUTHORITY
    assert len(plan.digest) == 64


def test_rehearsal_reapply_of_applied_versions_is_an_idempotent_noop():
    plan = plan_rehearsal(real_units(), ["001", "002", "003"], IDS)
    assert [a.apply for a in plan.actions] == [False, False, False]
    plan2 = plan_rehearsal(real_units(), ("001",), IDS)
    assert [a.apply for a in plan2.actions] == [False, True, True]
    twice = plan_rehearsal([add("001"), add("001")], [], IDS)  # same version twice in one plan
    assert [a.apply for a in twice.actions] == [True, False]


def test_rehearsal_missing_requires_is_refused():
    refused(plan_rehearsal([add("002", ["001"])], [], IDS), OpsReason.REHEARSAL_REQUIRES_UNMET)
    refused(plan_rehearsal([add("001"), add("003", ["002"])], [], IDS),
            OpsReason.REHEARSAL_REQUIRES_UNMET)


def test_rehearsal_gap_is_refused_even_when_requires_is_empty():
    refused(plan_rehearsal([add("001"), add("003", [])], [], IDS), OpsReason.REHEARSAL_REQUIRES_UNMET)
    refused(plan_rehearsal([add("003", ["001"])], ["001"], IDS), OpsReason.REHEARSAL_REQUIRES_UNMET)


def test_rehearsal_order_matters_like_record_migration():
    refused(plan_rehearsal([add("002", ["001"]), add("001")], [], IDS),
            OpsReason.REHEARSAL_REQUIRES_UNMET)


def test_rehearsal_refuses_a_non_additive_unit_with_the_class_code():
    bad = MigrationUnit("001", (), (step(StepKind.CREATE_TABLE), step(StepKind.DROP_TABLE)))
    refused(plan_rehearsal([bad], [], IDS), OpsReason.DESTRUCTIVE)
    r1 = MigrationUnit("001", (), (step(StepKind.CREATE_TABLE, schema=SchemaName.R1),))
    refused(plan_rehearsal([r1], [], IDS), OpsReason.UNCLASSIFIED)
    sw = MigrationUnit("001", (), (step(StepKind.FEATURE_FLAG, Phase.SWITCH,
                                        oc=ObjectClass.FEATURE_FLAG),))
    refused(plan_rehearsal([sw], [], IDS), OpsReason.SWITCH_ONLY)
    ct = MigrationUnit("001", (), (step(StepKind.RETIRE_ROUTE, Phase.CONTRACT, oc=ObjectClass.ROUTE),))
    refused(plan_rehearsal([ct], [], IDS), OpsReason.CONTRACT)
    both = MigrationUnit("001", (), (step(StepKind.RETIRE_ROUTE, Phase.CONTRACT, oc=ObjectClass.ROUTE),
                                     step(StepKind.TRUNCATE)))
    refused(plan_rehearsal([both], [], IDS), OpsReason.DESTRUCTIVE)  # the worst class wins


def test_rehearsal_does_not_judge_steps_of_an_already_recorded_version():
    # record_migration returns false for it: the body never runs, so its steps are not rehearsed
    unit = MigrationUnit("001", (), (step(StepKind.DROP_TABLE),))
    plan = plan_rehearsal([unit], ["001"], IDS)
    assert type(plan) is RehearsalPlan and plan.actions[0].apply is False


def test_rehearsal_a_hostile_unit_cannot_ride_behind_an_applied_version():
    refused(plan_rehearsal([add("001"), "not a unit"], ["001"], IDS), OpsReason.INPUT_INVALID)


@pytest.mark.parametrize("units", [
    None, 5, "001", b"001", [], (), {}, object(), [None], ["001"], [{"version": "001"}],
    [object.__new__(MigrationUnit)], [MigrationUnit("1", (), (step(StepKind.GRANT),))],
    [MigrationUnit("0001", (), (step(StepKind.GRANT),))],
    [MigrationUnit(EvilStr("001"), (), (step(StepKind.GRANT),))],
    [MigrationUnit(None, (), (step(StepKind.GRANT),))],
    [MigrationUnit("001", "001", (step(StepKind.GRANT),))],
    [MigrationUnit("001", [None], (step(StepKind.GRANT),))],
    [MigrationUnit("001", (EvilStr("x"),), (step(StepKind.GRANT),))],
    [MigrationUnit("001", (), ())],
    [MigrationUnit("001", (), None)],
    [MigrationUnit("001", (), "steps")],
    [MigrationUnit("001", ("001",) * 17, (step(StepKind.GRANT),))],
    [MigrationUnit("001", (), (step(StepKind.GRANT),) * 513)],
    [add("001")] * 65,
])
def test_rehearsal_hostile_units_are_input_invalid(units):
    refused(plan_rehearsal(units, [], IDS), OpsReason.INPUT_INVALID)


@pytest.mark.parametrize("applied", [
    None, 5, "001", b"", {"001": 1}, [None], ["1"], [EvilStr("001")], ["001\x00"], [["001"]],
    ["001"] * 65, [True],
])
def test_rehearsal_hostile_applied_versions_are_input_invalid(applied):
    refused(plan_rehearsal([add("001")], applied, IDS), OpsReason.INPUT_INVALID)


def test_rehearsal_recursive_containers_do_not_crash():
    rec = []
    rec.append(rec)
    refused(plan_rehearsal(rec, [], IDS), OpsReason.INPUT_INVALID)
    refused(plan_rehearsal([add("001")], rec, IDS), OpsReason.INPUT_INVALID)


def test_rehearsal_tuple_and_list_subclasses_are_refused():
    class T(tuple):
        pass

    refused(plan_rehearsal(T([add("001")]), [], IDS), OpsReason.INPUT_INVALID)
    refused(plan_rehearsal([add("001")], T(), IDS), OpsReason.INPUT_INVALID)


def test_rehearsal_snapshot_is_taken_once_a_later_mutation_changes_nothing():
    units = [add("001")]
    plan = plan_rehearsal(units, [], IDS)
    units.append(add("003"))
    assert [a.version for a in plan.actions] == ["001"]


def test_rehearsal_digest_is_derived_and_not_a_constructor_argument():
    plan = plan_rehearsal(real_units(), [], IDS)
    with pytest.raises(TypeError):
        RehearsalPlan(plan.actions, digest="0" * 64)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RehearsalPlan(plan.actions, authority="PROVEN")  # type: ignore[call-arg]
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.digest = "x"  # type: ignore[misc]
    other = plan_rehearsal(real_units(), ["001"], IDS)
    assert other.digest != plan.digest
    assert plan_rehearsal(real_units(), [], IDS).digest == plan.digest


def test_rehearsal_constructors_reject_bad_content():
    with pytest.raises(ValueError):
        RehearsalPlan(())
    with pytest.raises(ValueError):
        RehearsalPlan(("001",))  # type: ignore[arg-type]
    for bad in (("1", True, 1), ("001", 1, 1), ("001", True, True), ("001", True, -1)):
        with pytest.raises(ValueError):
            RehearsalAction(*bad)  # type: ignore[arg-type]


def test_rehearsal_refusal_never_echoes_input_and_uses_the_injected_id():
    secret = "SECRET-VERSION-TEXT"
    out = plan_rehearsal([MigrationUnit(secret, (), (step(StepKind.GRANT),))], [], IDS)
    assert type(out) is OpsRefusal and secret not in repr(out) and out.correlation_id.startswith("CORR-")


def test_rehearsal_a_failing_id_source_still_refuses_without_raising():
    class Boom:
        def next_id(self):
            raise RuntimeError("boom")

    out = plan_rehearsal(None, [], Boom())
    refused(out, OpsReason.INPUT_INVALID)


# ---- shadow comparison ----------------------------------------------------------------------------

def obs(op, before=D1, after=D1, shadow=D1):
    return ShadowObservation(op, before, after, shadow)


def test_identical_digests_everywhere_is_r1_unchanged():
    res = compare_shadow(["op.a", "op.b"], [obs("op.a"), obs("op.b")], IDS)
    assert type(res) is ShadowResult and res.reason is OpsReason.R1_UNCHANGED
    assert res.regressed == () and res.divergent == () and res.missing == ()
    assert res.authority == AUTHORITY and len(res.digest) == 64


def test_one_changed_r1_digest_is_a_regression_naming_only_the_typed_operation_id():
    res = compare_shadow(["op.a", "op.b"], [obs("op.a"), obs("op.b", before=D1, after=D2, shadow=D2)], IDS)
    assert res.reason is OpsReason.R1_REGRESSION
    assert res.regressed == ("op.b",)
    assert "op.b" not in repr(res)


def test_missing_observation_is_incomplete_never_a_pass():
    res = compare_shadow(["op.a", "op.b"], [obs("op.a")], IDS)
    assert res.reason is OpsReason.SHADOW_INCOMPLETE and res.missing == ("op.b",)
    only = compare_shadow(["op.a"], [], IDS)
    assert only.reason is OpsReason.SHADOW_INCOMPLETE


def test_r2_shadow_differing_from_r1_is_divergence_and_never_a_promotion():
    res = compare_shadow(["op.a"], [obs("op.a", shadow=D3)], IDS)
    assert res.reason is OpsReason.SHADOW_DIVERGENCE and res.divergent == ("op.a",)
    assert res.promotion_permitted is False
    for reason_case in (compare_shadow(["op.a"], [obs("op.a")], IDS),
                        compare_shadow(["op.a"], [], IDS),
                        compare_shadow(["op.a"], [obs("op.a", after=D2)], IDS)):
        assert reason_case.promotion_permitted is False
    assert not any(hasattr(res, name) for name in ("promote", "promoted", "approved", "passed"))


def test_priority_regression_over_incomplete_over_divergence():
    reg_and_missing = compare_shadow(["op.a", "op.b"], [obs("op.a", after=D2)], IDS)
    assert reg_and_missing.reason is OpsReason.R1_REGRESSION and reg_and_missing.missing == ("op.b",)
    inc_and_div = compare_shadow(["op.a", "op.b"], [obs("op.a", shadow=D2)], IDS)
    assert inc_and_div.reason is OpsReason.SHADOW_INCOMPLETE and inc_and_div.divergent == ("op.a",)


def test_an_unexpected_observation_still_counts_for_regressions_but_not_completeness():
    res = compare_shadow(["op.a"], [obs("op.a"), obs("op.extra", after=D2)], IDS)
    assert res.reason is OpsReason.R1_REGRESSION and res.regressed == ("op.extra",)
    ok = compare_shadow(["op.a"], [obs("op.a"), obs("op.extra")], IDS)
    assert ok.reason is OpsReason.R1_UNCHANGED


def test_shadow_result_lists_are_sorted_and_deterministic():
    a = compare_shadow(["z.op", "a.op"], [obs("z.op", after=D2), obs("a.op", after=D2)], IDS)
    b = compare_shadow(["a.op", "z.op"], [obs("a.op", after=D2), obs("z.op", after=D2)], IDS)
    assert a.regressed == ("a.op", "z.op") and a.digest == b.digest


@pytest.mark.parametrize("op", [None, 5, "", " ", "has space", "x" * 65, "1abc", "a\nb", "a\x00b",
                                "drop table; --", "аbc", EvilStr("op.a"), b"op", ["op.a"]])
def test_operation_ids_must_be_typed_fixture_ids(op):
    assert not is_operation_id(op)
    refused(compare_shadow([op], [], IDS), OpsReason.INPUT_INVALID)
    refused(compare_shadow(["op.a"], [ShadowObservation(op, D1, D1, D1)], IDS), OpsReason.INPUT_INVALID)


def test_operation_id_accepts_fixture_style_ids():
    for ok in ("op.a", "OP_1", "r1:read-invoice", "a" * 64):
        assert is_operation_id(ok)


@pytest.mark.parametrize("digest", [None, 5, "", "A" * 64, "a" * 63, "a" * 65, "g" * 64, EvilStr("a" * 64),
                                   b"a" * 64, "a" * 64 + "\n"])
def test_observation_digests_must_be_exact_lowercase_sha256(digest):
    for field in range(3):
        row = [D1, D1, D1]
        row[field] = digest
        refused(compare_shadow(["op.a"], [ShadowObservation("op.a", *row)], IDS), OpsReason.INPUT_INVALID)


@pytest.mark.parametrize("expected,observations", [
    (None, []), ([], []), ("op.a", []), (5, []), ([["op.a"]], []), (["op.a", "op.a"], []),
    (["op.a"], None), (["op.a"], "x"), (["op.a"], [None]), (["op.a"], [object.__new__(ShadowObservation)]),
    (["op.a"], [obs("op.a"), obs("op.a")]),  # duplicate observation is ambiguous
    (["op.a"], [{"operation_id": "op.a"}]),
    ([f"op.{i}" for i in range(1001)], []), (["op.a"], [obs("op.a")] * 1001),
])
def test_shadow_hostile_input_is_input_invalid(expected, observations):
    refused(compare_shadow(expected, observations, IDS), OpsReason.INPUT_INVALID)


def test_shadow_recursive_and_subclass_containers_do_not_crash():
    rec = []
    rec.append(rec)
    refused(compare_shadow(rec, [], IDS), OpsReason.INPUT_INVALID)
    refused(compare_shadow(["op.a"], rec, IDS), OpsReason.INPUT_INVALID)

    class L(list):
        pass

    refused(compare_shadow(L(["op.a"]), [], IDS), OpsReason.INPUT_INVALID)
    refused(compare_shadow(["op.a"], L([obs("op.a")]), IDS), OpsReason.INPUT_INVALID)


def test_shadow_set_input_is_accepted_for_expected_operations():
    res = compare_shadow({"op.a", "op.b"}, [obs("op.a"), obs("op.b")], IDS)
    assert res.reason is OpsReason.R1_UNCHANGED


def test_shadow_result_verdict_is_derived_not_caller_supplied():
    for kwargs in ({"reason": OpsReason.R1_UNCHANGED}, {"digest": "0" * 64}, {"authority": "PROVEN"}):
        with pytest.raises(TypeError):
            ShadowResult((), (), (), **kwargs)  # type: ignore[arg-type]
    forced = ShadowResult(("op.a",), (), ())  # even a hand-built result derives its own verdict
    assert forced.reason is OpsReason.R1_REGRESSION
    with pytest.raises(ValueError):
        ShadowResult(("free text",), (), ())
    with pytest.raises(ValueError):
        ShadowResult(["op.a"], (), ())  # type: ignore[arg-type]
    with pytest.raises(dataclasses.FrozenInstanceError):
        forced.reason = OpsReason.R1_UNCHANGED  # type: ignore[misc]


def test_shadow_observation_snapshot_is_taken_once():
    items = [obs("op.a")]
    res = compare_shadow(["op.a"], items, IDS)
    items.append(obs("op.a", after=D2))
    assert res.reason is OpsReason.R1_UNCHANGED


def test_shadow_output_has_no_input_text_beyond_typed_ids():
    res = compare_shadow(["op.a"], [obs("op.a", after=D2)], IDS)
    assert D2 not in repr(res) and D1 not in repr(res)
    assert isinstance(res.reason, OpsReason) and type(res.regressed[0]) is str


def test_nothing_in_this_module_is_a_tenant_or_datetime_dependency():
    # platform level: no step/unit/observation type has a tenant or time field
    for cls in (MigrationStep, MigrationUnit, ShadowObservation, ShadowResult, RehearsalPlan):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not names & {"tenant_id", "company_id", "actor_id", "at", "clock"}
