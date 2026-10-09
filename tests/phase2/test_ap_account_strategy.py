"""R2-US-031 / TC091-TC093: explicit account-based AP strategy, absent register, balance-only."""
import ast
import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import ap_account_strategy as mod
from business_ai_gateway.phase2.ap_account_strategy import (
    AgingBucket,
    AgingState,
    ApViewState,
    InputName,
    LedgerInputs,
    OpenItem,
    Reason,
    SourceDescription,
    Strategy,
    StrategyState,
    compute_aging,
    make_balance_view,
    qualify_strategy,
)

LEDGER = "ledger_accounting_register"
SETTLE = "settlements_register"
P_FROM, P_UNTIL = date(2026, 1, 1), date(2027, 1, 1)


def source(**kw) -> SourceDescription:
    base: dict = dict(  # noqa: C408
        accounting_registers=("Хозрасчетный",),
        settlements_registers=(),
        account_codes=("60.01", "60.02"),
        analytics_keys=("Контрагент", "Договор"),
        companies=("MOLDRETAIL",),
        currencies=("MDL",),
        covered_from=date(2025, 1, 1),
        covered_until=date(2028, 1, 1),
    )
    base.update(kw)
    return SourceDescription(**base)


def inputs(**kw) -> LedgerInputs:
    base: dict = dict(  # noqa: C408
        register="Хозрасчетный", account_codes=("60.01",), analytics_keys=("Контрагент", "Договор"),
        company="MOLDRETAIL", currency="MDL", period_from=P_FROM, period_until=P_UNTIL,
    )
    base.update(kw)
    return LedgerInputs(**base)


def qualified():
    return qualify_strategy(LEDGER, inputs(), source())


def item(ref, doc, due, amount) -> OpenItem:
    return OpenItem(ref, doc, due, Decimal(amount))


# ------------------------------------------------------------------ TC091

def test_tc091_ledger_strategy_qualified_when_every_input_present():
    r = qualified()
    assert r.state is StrategyState.QUALIFIED
    assert r.reason is Reason.ALL_INPUTS_PRESENT
    assert r.strategy is Strategy.LEDGER_ACCOUNTING_REGISTER
    assert r.missing == ()
    assert r.authority == "EVALUATION_ONLY"


@pytest.mark.parametrize(("src_kw", "decl_kw", "missing"), [
    ({"accounting_registers": ("Другой",)}, {}, InputName.REGISTER),
    ({}, {"account_codes": ("60.01", "99.99")}, InputName.ACCOUNT_CODES),
    ({}, {"analytics_keys": ("Контрагент", "Склад")}, InputName.ANALYTICS_KEYS),
    ({"companies": ("OTHER",)}, {}, InputName.COMPANY),
    ({"currencies": ("EUR",)}, {}, InputName.CURRENCY),
    ({"covered_until": date(2026, 6, 1)}, {}, InputName.PERIOD),
    ({"covered_from": date(2026, 3, 1)}, {}, InputName.PERIOD),
    ({"covered_from": None}, {}, InputName.PERIOD),
])
def test_tc091_each_missing_input_unqualifies_with_that_input_named(src_kw, decl_kw, missing):
    r = qualify_strategy(LEDGER, inputs(**decl_kw), source(**src_kw))
    assert r.state is StrategyState.UNQUALIFIED
    assert r.reason is Reason.INPUT_NOT_IN_SOURCE
    assert r.missing == (missing,)
    assert r.digest != qualified().digest


def test_tc091_several_missing_inputs_are_all_listed_sorted():
    r = qualify_strategy(LEDGER, inputs(), source(companies=("X",), currencies=("EUR",)))
    assert r.missing == (InputName.COMPANY, InputName.CURRENCY)


@pytest.mark.parametrize("name", ["", "Ledger_Accounting_Register", " ledger_accounting_register",
                                  "ledger", "ap.account_based", None, 5, b"ledger_accounting_register",
                                  Strategy.LEDGER_ACCOUNTING_REGISTER.value + "\u200b"])
def test_tc091_unknown_strategy_is_unqualified_without_number_or_echo(name):
    r = qualify_strategy(name, inputs(), source())
    assert r.state is StrategyState.UNQUALIFIED
    assert r.reason is Reason.UNKNOWN_STRATEGY
    assert r.strategy is None
    assert r.missing == ()
    view = make_balance_view(r, Decimal(100))
    assert view.balance is None and view.state is ApViewState.UNQUALIFIED


def test_tc091_str_enum_member_name_is_accepted_as_its_exact_value():
    assert qualify_strategy(Strategy.LEDGER_ACCOUNTING_REGISTER, inputs(), source()).state \
        is StrategyState.QUALIFIED


@pytest.mark.parametrize("decl_kw", [
    {"register": ""}, {"account_codes": ()}, {"analytics_keys": ()}, {"company": " "},
    {"currency": ""}, {"period_from": None}, {"period_until": None},
    {"period_from": P_UNTIL, "period_until": P_FROM}, {"period_from": P_FROM, "period_until": P_FROM},
])
def test_tc091_undeclared_input_is_refused_not_defaulted(decl_kw):
    r = qualify_strategy(LEDGER, inputs(**decl_kw), source())
    assert r.state is StrategyState.UNQUALIFIED
    assert r.reason is Reason.INPUT_NOT_DECLARED
    assert len(r.missing) >= 1


def test_tc091_matching_is_normalised_but_confusable_lookalikes_do_not_qualify():
    r = qualify_strategy(LEDGER, inputs(company=" moldretail ", currency="mdl"), source())
    assert r.state is StrategyState.QUALIFIED
    # Latin 'C' inside a Cyrillic word is a mixed-script identity: invalid, not a match
    bad = qualify_strategy(LEDGER, inputs(register="Хозрасчетныи\u200b"), source())
    assert bad.state is StrategyState.UNQUALIFIED
    assert bad.reason is Reason.INPUT_NOT_DECLARED


def test_tc091_digest_stable_order_independent_and_input_sensitive():
    a = qualify_strategy(LEDGER, inputs(account_codes=("60.01", "60.02")), source())
    b = qualify_strategy(LEDGER, inputs(account_codes=("60.02", "60.01", "60.01")), source())
    assert a.digest == b.digest
    assert len(a.digest) == 64
    assert a.digest != qualified().digest
    other_period = qualify_strategy(LEDGER, inputs(period_until=date(2026, 12, 31)), source())
    assert other_period.state is StrategyState.QUALIFIED
    assert other_period.digest != qualified().digest


def test_tc091_ledger_does_not_fall_back_to_settlements():
    r = qualify_strategy(LEDGER, inputs(register="Расчеты"), source(settlements_registers=("Расчеты",)))
    assert r.state is StrategyState.UNQUALIFIED
    assert r.strategy is Strategy.LEDGER_ACCOUNTING_REGISTER
    assert r.missing == (InputName.REGISTER,)


# ------------------------------------------------------------------ TC092

def test_tc092_absent_settlements_register_is_first_class_result():
    r = qualify_strategy(SETTLE, inputs(register="РегистрРасчетов"), source())
    assert r.state is StrategyState.ABSENT
    assert r.reason is Reason.REGISTER_NOT_IN_SOURCE
    assert r.strategy is Strategy.SETTLEMENTS_REGISTER
    assert r.missing == (InputName.REGISTER,)
    # no fallback: the source does have a usable ledger register, still ABSENT
    assert qualify_strategy(LEDGER, inputs(), source()).state is StrategyState.QUALIFIED


def test_tc092_absent_builds_no_balance_and_no_aging_and_digest_is_stable_and_distinct():
    absent = qualify_strategy(SETTLE, inputs(register="РегистрРасчетов"), source())
    again = qualify_strategy(SETTLE, inputs(register="РегистрРасчетов"), source())
    assert absent.digest == again.digest
    assert absent.digest != qualified().digest
    view = make_balance_view(absent, Decimal(1000))
    assert view.state is ApViewState.ABSENT
    assert view.balance is None
    assert view.aging_state is AgingState.NOT_AVAILABLE
    aging = compute_aging(absent, (item("D1", date(2026, 1, 1), date(2026, 2, 1), "10"),), date(2026, 3, 1))
    assert aging.state is AgingState.NOT_AVAILABLE
    assert aging.reason is Reason.STRATEGY_NOT_QUALIFIED
    assert aging.open_total is None and aging.buckets == ()


def test_tc092_settlements_register_present_in_source_qualifies():
    r = qualify_strategy(SETTLE, inputs(register="Расчеты", account_codes=(), analytics_keys=()),
                         source(settlements_registers=("Расчеты",)))
    assert r.state is StrategyState.QUALIFIED
    assert r.digest != qualified().digest


def test_tc092_settlements_register_listed_only_as_accounting_register_is_absent():
    r = qualify_strategy(SETTLE, inputs(register="Хозрасчетный"), source())
    assert r.state is StrategyState.ABSENT


def test_tc092_absent_is_not_an_exception_for_empty_or_hostile_source():
    for src in (source(accounting_registers=(), settlements_registers=()), SourceDescription()):
        r = qualify_strategy(SETTLE, inputs(register="X"), src)
        assert r.state is StrategyState.ABSENT


# ------------------------------------------------------------------ TC093

def test_tc093_balance_only_has_no_aging():
    view = make_balance_view(qualified(), Decimal("1234.56"))
    assert view.state is ApViewState.BALANCE_ONLY
    assert view.balance == Decimal("1234.56")
    assert view.aging_state is AgingState.NOT_AVAILABLE
    assert view.aging_reason is Reason.BALANCE_ONLY_NO_ITEMS
    assert not any(hasattr(view, a) for a in ("buckets", "aging"))
    assert view.digest != make_balance_view(qualified(), Decimal("1234.57")).digest
    assert view.digest == make_balance_view(qualified(), Decimal("1234.560")).digest


@pytest.mark.parametrize("bad", [1234.5, 5, "12", None, True, Decimal("NaN"), Decimal("Infinity"),
                                 Decimal("1E+40"), Decimal("1E-20")])
def test_tc093_balance_must_be_a_finite_bounded_decimal(bad):
    view = make_balance_view(qualified(), bad)
    assert view.state is ApViewState.INPUT_INVALID
    assert view.reason is Reason.BALANCE_INVALID
    assert view.balance is None


def test_tc093_negative_balance_is_allowed_as_a_label_only():
    # a closing balance may be a debit position; it is only labelled BALANCE_ONLY, no aging
    view = make_balance_view(qualified(), Decimal(-10))
    assert view.state is ApViewState.BALANCE_ONLY and view.balance == Decimal(-10)


def test_tc093_aging_buckets_sum_to_open_total():
    as_of = date(2026, 6, 30)
    rows = (
        item("D1", date(2026, 5, 1), date(2026, 7, 15), "100.10"),   # not due -> CURRENT
        item("D2", date(2026, 5, 1), date(2026, 6, 20), "200.20"),   # 10 days
        item("D3", date(2026, 3, 1), date(2026, 5, 15), "300.30"),   # 46 days
        item("D4", date(2026, 2, 1), date(2026, 4, 20), "400.40"),   # 71 days
        item("D5", date(2025, 11, 1), date(2026, 1, 1), "500.50"),   # 180 days
    )
    r = compute_aging(qualified(), rows, as_of, Decimal("1501.50"))
    assert r.state is AgingState.AVAILABLE and r.reason is Reason.AGING_COMPUTED
    assert dict(r.buckets) == {
        AgingBucket.CURRENT: Decimal("100.10"), AgingBucket.D1_30: Decimal("200.20"),
        AgingBucket.D31_60: Decimal("300.30"), AgingBucket.D61_90: Decimal("400.40"),
        AgingBucket.D91_PLUS: Decimal("500.50"),
    }
    assert [b for b, _ in r.buckets] == list(AgingBucket)
    assert sum((v for _, v in r.buckets), Decimal(0)) == r.open_total == Decimal("1501.50")
    assert r.authority == "EVALUATION_ONLY"


@pytest.mark.parametrize(("days_past_due", "bucket"), [
    (-1, AgingBucket.CURRENT), (0, AgingBucket.CURRENT), (1, AgingBucket.D1_30),
    (30, AgingBucket.D1_30), (31, AgingBucket.D31_60), (60, AgingBucket.D31_60),
    (61, AgingBucket.D61_90), (90, AgingBucket.D61_90), (91, AgingBucket.D91_PLUS),
    (400, AgingBucket.D91_PLUS),
])
def test_tc093_bucket_boundary_days(days_past_due, bucket):
    as_of = date(2026, 12, 31)
    due = date.fromordinal(as_of.toordinal() - days_past_due)
    r = compute_aging(qualified(), (item("D", date(2025, 1, 1), due, "7"),), as_of)
    assert r.state is AgingState.AVAILABLE
    assert dict(r.buckets)[bucket] == Decimal(7)
    assert sum(1 for _, v in r.buckets if v) == 1


@pytest.mark.parametrize("missing_doc", [True, False])
def test_tc093_one_missing_date_refuses_the_whole_aging(missing_doc):
    rows = (
        item("D1", date(2026, 1, 1), date(2026, 2, 1), "10"),
        OpenItem("D2", None if missing_doc else date(2026, 1, 1), date(2026, 2, 1) if missing_doc else None,
                 Decimal(20)),
    )
    r = compute_aging(qualified(), rows, date(2026, 6, 1))
    assert r.state is AgingState.NOT_AVAILABLE
    assert r.reason is Reason.DATE_MISSING
    assert r.buckets == () and r.open_total is None  # no partial aging for the good row


def test_tc093_aging_requires_qualified_strategy():
    rows = (item("D1", date(2026, 1, 1), date(2026, 2, 1), "10"),)
    bad = qualify_strategy("nope", inputs(), source())
    r = compute_aging(bad, rows, date(2026, 6, 1))
    assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.STRATEGY_NOT_QUALIFIED)
    assert compute_aging("qualified", rows, date(2026, 6, 1)).reason is Reason.STRATEGY_NOT_QUALIFIED


# ------------------------------------------------------------------ aging policy, hostile input

D0, DUE, ASOF = date(2026, 1, 1), date(2026, 2, 1), date(2026, 6, 1)


@pytest.mark.parametrize(("rows", "reason"), [
    ((), Reason.ITEMS_EMPTY),
    ([item("D", D0, DUE, "1")], Reason.ITEMS_INVALID),
    (("raw",), Reason.ITEMS_INVALID),
    ((item("D", D0, DUE, "1"), item(" d ", D0, DUE, "2")), Reason.DUPLICATE_ITEM),
    ((item("D", D0, DUE, "1"), item("Ｄ", D0, DUE, "2")), Reason.DUPLICATE_ITEM),  # fullwidth D
    ((item("", D0, DUE, "1"),), Reason.ITEM_REF_INVALID),
    ((OpenItem(5, D0, DUE, Decimal(1)),), Reason.ITEM_REF_INVALID),
    ((item("a\u200bb", D0, DUE, "1"),), Reason.ITEM_REF_INVALID),
    ((item("D", D0, DUE, "-0.01"),), Reason.NEGATIVE_AMOUNT),
    ((OpenItem("D", D0, DUE, 1.5),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, 10),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, True),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, Decimal("NaN")),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, Decimal("Infinity")),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, Decimal("1E+999")),), Reason.AMOUNT_INVALID),
    ((item("D", DUE, D0, "1"),), Reason.DATE_ORDER_INVALID),                    # due before document
    ((item("D", date(2026, 7, 1), date(2026, 8, 1), "1"),), Reason.DATE_ORDER_INVALID),  # after as_of
    ((OpenItem("D", "2026-01-01", DUE, Decimal(1)),), Reason.DATE_INVALID),
])
def test_aging_refusals_have_fixed_codes(rows, reason):
    r = compute_aging(qualified(), rows, ASOF)
    assert r.state is AgingState.NOT_AVAILABLE
    assert r.reason is reason
    assert r.buckets == ()


def test_timezone_naive_and_aware_datetimes_are_refused_not_coerced():
    naive = datetime(2026, 1, 1, 0, 0)  # noqa: DTZ001 - naive on purpose
    aware = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    for bad in (naive, aware):
        assert compute_aging(qualified(), (OpenItem("D", bad, DUE, Decimal(1)),), ASOF).reason \
            is Reason.DATE_INVALID
        assert compute_aging(qualified(), (OpenItem("D", D0, bad, Decimal(1)),), ASOF).reason \
            is Reason.DATE_INVALID
        assert compute_aging(qualified(), (item("D", D0, DUE, "1"),), bad).reason is Reason.DATE_INVALID
        assert qualify_strategy(LEDGER, inputs(period_from=bad), source()).reason is Reason.INPUT_INVALID
        assert qualify_strategy(LEDGER, inputs(), source(covered_from=bad)).reason is Reason.INPUT_INVALID


@pytest.mark.parametrize("as_of", [None, "2026-06-01", 20260601])
def test_as_of_must_be_a_plain_date(as_of):
    r = compute_aging(qualified(), (item("D", D0, DUE, "1"),), as_of)
    assert r.reason is Reason.DATE_INVALID and r.as_of is None


def test_zero_amount_row_is_allowed_and_same_day_due_is_valid():
    r = compute_aging(qualified(), (item("D", D0, D0, "0"), item("E", D0, ASOF, "5")), ASOF)
    assert r.state is AgingState.AVAILABLE
    assert r.open_total == Decimal(5)


def test_declared_total_must_equal_row_sum_exactly():
    rows = (item("D", D0, DUE, "10.00"), item("E", D0, DUE, "0.01"))
    assert compute_aging(qualified(), rows, ASOF, Decimal("10.01")).state is AgingState.AVAILABLE
    off = compute_aging(qualified(), rows, ASOF, Decimal("10.02"))
    assert (off.state, off.reason) == (AgingState.NOT_AVAILABLE, Reason.TOTAL_MISMATCH)
    assert compute_aging(qualified(), rows, ASOF, 10.01).reason is Reason.AMOUNT_INVALID


def test_exactness_no_float_rounding_on_many_small_amounts():
    rows = tuple(item(f"D{i}", D0, DUE, "0.1") for i in range(1000))
    r = compute_aging(qualified(), rows, ASOF)
    assert r.open_total == Decimal("100.0")
    assert all(isinstance(v, Decimal) for _, v in r.buckets)


def test_precision_overflow_is_a_refusal_not_an_exception():
    big = Decimal("9" * 30)
    rows = tuple(OpenItem(f"D{i}", D0, DUE, big) for i in range(3))
    r = compute_aging(qualified(), rows, ASOF)
    assert r.state is AgingState.AVAILABLE  # 30 digits sum fits the 60-digit exact context
    wide = Decimal("1." + "1" * 8)
    assert compute_aging(qualified(), (OpenItem("D", D0, DUE, wide),), ASOF).state is AgingState.AVAILABLE


def test_too_many_items_refused():
    rows = (item("D", D0, DUE, "1"),) * (mod.MAX_ITEMS + 1)
    assert compute_aging(qualified(), rows, ASOF).reason is Reason.TOO_MANY_ITEMS


def test_aging_digest_deterministic_order_independent_and_input_sensitive():
    a, b = item("A", D0, DUE, "1"), item("B", D0, DUE, "2")
    base = compute_aging(qualified(), (a, b), ASOF)
    assert base.digest == compute_aging(qualified(), (b, a), ASOF).digest
    assert base.digest != compute_aging(qualified(), (a, item("B", D0, DUE, "3")), ASOF).digest
    assert base.digest != compute_aging(qualified(), (a, b), date(2026, 6, 2)).digest
    assert base.digest != compute_aging(qualified(), (a, item("B", D0, date(2026, 2, 2), "2")), ASOF).digest
    refused = compute_aging(qualified(), (), ASOF)
    assert refused.digest != base.digest
    assert refused.digest == compute_aging(qualified(), (), ASOF).digest


# ------------------------------------------------------------------ hostile types

class _Boom:
    def __getattribute__(self, name):
        if name.startswith("__"):
            return object.__getattribute__(self, name)
        raise RuntimeError("boom")


@pytest.mark.parametrize("hostile", [None, 0, "x", b"x", [], {}, object(), _Boom(), float("nan")],
                         ids=lambda v: type(v).__name__)
def test_hostile_arguments_never_raise(hostile):
    assert qualify_strategy(hostile, hostile, hostile).state is StrategyState.UNQUALIFIED
    assert qualify_strategy(LEDGER, hostile, hostile).state is StrategyState.UNQUALIFIED
    assert qualify_strategy(LEDGER, inputs(), hostile).reason is Reason.INPUT_INVALID
    assert qualify_strategy(LEDGER, hostile, source()).reason is Reason.INPUT_INVALID
    assert make_balance_view(hostile, Decimal(1)).state is ApViewState.INPUT_INVALID
    assert make_balance_view(qualified(), hostile).balance is None
    assert compute_aging(hostile, hostile, hostile).state is AgingState.NOT_AVAILABLE
    assert compute_aging(qualified(), hostile, ASOF).state is AgingState.NOT_AVAILABLE
    assert compute_aging(qualified(), (hostile,), ASOF).state is AgingState.NOT_AVAILABLE


@pytest.mark.parametrize("field", ["accounting_registers", "account_codes", "analytics_keys",
                                   "companies", "currencies"])
@pytest.mark.parametrize("bad", ["Хозрасчетный", ["Хозрасчетный"], (5,), (None,), ("",), ("a" * 300,)])
def test_hostile_source_lists_are_input_invalid(field, bad):
    r = qualify_strategy(LEDGER, inputs(), source(**{field: bad}))
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_INVALID


@pytest.mark.parametrize("field", ["account_codes", "analytics_keys"])
@pytest.mark.parametrize("bad", ["60.01", ["60.01"], (5,), ("\u200b",)])
def test_hostile_declared_lists_are_input_invalid(field, bad):
    r = qualify_strategy(LEDGER, inputs(**{field: bad}), source())
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_INVALID


def test_refusal_never_echoes_caller_text():
    secret = "SECRET-NAME-123"
    results = [
        qualify_strategy(secret, inputs(), source()),
        qualify_strategy(LEDGER, inputs(company=secret), source()),
        qualify_strategy(LEDGER, inputs(register=secret), source()),
    ]
    for r in results:
        blob = repr(r)
        assert secret not in blob and secret.lower() not in blob
    view = make_balance_view(qualify_strategy(secret, inputs(), source()), Decimal(1))
    assert secret not in repr(view)
    assert secret not in repr(compute_aging(qualified(), (item(secret, D0, DUE, "-1"),), ASOF))


def test_results_are_frozen_slotted_dataclasses():
    for obj in (qualified(), make_balance_view(qualified(), Decimal(1)),
                compute_aging(qualified(), (item("D", D0, DUE, "1"),), ASOF), source(), inputs(),
                item("D", D0, DUE, "1")):
        assert dataclasses.is_dataclass(obj)
        assert not hasattr(obj, "__dict__")
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, dataclasses.fields(obj)[0].name, None)


# ------------------------------------------------------------------ boundaries

def test_module_has_no_write_network_file_db_imports_and_no_validation_coverage():
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add(("." * node.level) + (node.module or ""))
    assert roots <= {"__future__", "hashlib", "dataclasses", "datetime", "decimal", "enum", "._identity"}
    assert not any("validation_coverage" in r for r in roots)
    assert "float(" not in Path(mod.__file__).read_text(encoding="utf-8")


def test_validation_coverage_still_refuses_ap_account_based():
    from business_ai_gateway.phase2.validation_coverage import RESERVED_CAPABILITIES
    assert "ap.account_based" in RESERVED_CAPABILITIES
    assert not hasattr(mod, "capability_enabled")
