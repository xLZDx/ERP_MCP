"""R2-US-031 / TC091-TC093: explicit account-based AP strategy, absent register, balance-only."""
import ast
import contextlib
import dataclasses
from datetime import UTC, date, datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import ap_account_strategy as mod
from business_ai_gateway.phase2.ap_account_strategy import (
    AgingBucket,
    AgingState,
    ApViewState,
    InputName,
    LedgerInputs,
    Reason,
    SourceDescription,
    Strategy,
    StrategyState,
    compute_aging,
    make_balance_view,
    qualify_strategy,
)
from business_ai_gateway.phase2.ap_account_strategy import OpenItem as _OpenItem

LEDGER = "ledger_accounting_register"
SETTLE = "settlements_register"
P_FROM, P_UNTIL = date(2026, 1, 1), date(2027, 1, 1)
TENANT, SOURCE = "TENANT-A", "SRC-1"


def OpenItem(doc_ref, document_date, due_date, amount, currency="", company="",
             tenant_id=TENANT, source_id=SOURCE):
    """Fixture builder: rows default to the fixture tenant/source (tests override it explicitly)."""
    return _OpenItem(doc_ref, document_date, due_date, amount, currency, company, tenant_id, source_id)


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
        tenant_id=TENANT, source_id=SOURCE,
    )
    base.update(kw)
    return SourceDescription(**base)


def inputs(**kw) -> LedgerInputs:
    base: dict = dict(  # noqa: C408
        register="Хозрасчетный", account_codes=("60.01",), analytics_keys=("Контрагент", "Договор"),
        company="MOLDRETAIL", currency="MDL", period_from=P_FROM, period_until=P_UNTIL,
        tenant_id=TENANT, source_id=SOURCE,
    )
    base.update(kw)
    return LedgerInputs(**base)


def qualified():
    return qualify_strategy(LEDGER, inputs(), source())


def item(ref, doc, due, amount) -> OpenItem:
    return OpenItem(ref, doc, due, Decimal(amount), currency="MDL", company="MOLDRETAIL")


def _total(rows):
    with contextlib.suppress(Exception):  # hostile rows: the aging itself must refuse them
        if all(type(r.amount) is Decimal and r.amount.is_finite() for r in rows):
            with localcontext(Context(prec=100)):
                return sum((r.amount for r in rows), Decimal(0))
    return Decimal(0)


_UNSET = object()


def age(rows, as_of=_UNSET, strat=None, total="auto"):
    """compute_aging with the (mandatory) declared total defaulting to the exact row sum."""
    return compute_aging(strat if strat is not None else qualified(), rows,
                         ASOF if as_of is _UNSET else as_of, _total(rows) if total == "auto" else total)


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


def test_tc092_absent_builds_no_balance_and_no_aging_and_digest_is_stable_and_distinct():
    absent = qualify_strategy(SETTLE, inputs(register="РегистрРасчетов"), source())
    again = qualify_strategy(SETTLE, inputs(register="РегистрРасчетов"), source())
    assert absent.digest == again.digest
    assert absent.digest != qualified().digest
    view = make_balance_view(absent, Decimal(1000))
    assert view.state is ApViewState.ABSENT
    assert view.balance is None
    assert view.aging_state is AgingState.NOT_AVAILABLE
    aging = age((item("D1", date(2026, 1, 1), date(2026, 2, 1), "10"),), date(2026, 3, 1), strat=absent)
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
    for src in (source(accounting_registers=(), settlements_registers=()),
                SourceDescription(tenant_id=TENANT, source_id=SOURCE)):
        r = qualify_strategy(SETTLE, inputs(register="X"), src)
        assert r.state is StrategyState.ABSENT
    # a description that names no tenant/source is not ABSENT for anybody: it is not in scope at all
    r = qualify_strategy(SETTLE, inputs(register="X"), SourceDescription())
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_NOT_IN_SOURCE


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
    r = age(rows, as_of, total=Decimal("1501.50"))
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
    r = age((item("D", date(2025, 1, 1), due, "7"),), as_of)
    assert r.state is AgingState.AVAILABLE
    assert dict(r.buckets)[bucket] == Decimal(7)
    assert sum(1 for _, v in r.buckets if v) == 1


@pytest.mark.parametrize("missing_doc", [True, False])
def test_tc093_one_missing_date_refuses_the_whole_aging(missing_doc):
    rows = (
        item("D1", date(2026, 1, 1), date(2026, 2, 1), "10"),
        OpenItem("D2", None if missing_doc else date(2026, 1, 1), date(2026, 2, 1) if missing_doc else None,
                 Decimal(20), "MDL", "MOLDRETAIL"),
    )
    r = age(rows, date(2026, 6, 1))
    assert r.state is AgingState.NOT_AVAILABLE
    assert r.reason is Reason.DATE_MISSING
    assert r.buckets == () and r.open_total is None  # no partial aging for the good row


def test_tc093_aging_requires_qualified_strategy():
    rows = (item("D1", date(2026, 1, 1), date(2026, 2, 1), "10"),)
    bad = qualify_strategy("nope", inputs(), source())
    r = age(rows, date(2026, 6, 1), strat=bad)
    assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.STRATEGY_NOT_QUALIFIED)
    assert compute_aging("qualified", rows, date(2026, 6, 1), Decimal(10)).reason         is Reason.STRATEGY_NOT_QUALIFIED


# ------------------------------------------------------------------ aging policy, hostile input

D0, DUE, ASOF = date(2026, 1, 1), date(2026, 2, 1), date(2026, 6, 1)


@pytest.mark.parametrize(("rows", "reason"), [
    ((), Reason.ITEMS_EMPTY),
    ([item("D", D0, DUE, "1")], Reason.ITEMS_INVALID),
    (("raw",), Reason.ITEMS_INVALID),
    ((item("D", D0, DUE, "1"), item(" d ", D0, DUE, "2")), Reason.DUPLICATE_ITEM),
    ((item("D", D0, DUE, "1"), item("Ｄ", D0, DUE, "2")), Reason.DUPLICATE_ITEM),  # fullwidth D
    ((item("", D0, DUE, "1"),), Reason.ITEM_REF_INVALID),
    ((OpenItem(5, D0, DUE, Decimal(1), "MDL", "MOLDRETAIL"),), Reason.ITEM_REF_INVALID),
    ((item("a\u200bb", D0, DUE, "1"),), Reason.ITEM_REF_INVALID),
    ((item("D", D0, DUE, "-0.01"),), Reason.NEGATIVE_AMOUNT),
    ((OpenItem("D", D0, DUE, 1.5, "MDL", "MOLDRETAIL"),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, 10, "MDL", "MOLDRETAIL"),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, True, "MDL", "MOLDRETAIL"),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, Decimal("NaN"), "MDL", "MOLDRETAIL"),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, Decimal("Infinity"), "MDL", "MOLDRETAIL"),), Reason.AMOUNT_INVALID),
    ((OpenItem("D", D0, DUE, Decimal("1E+999"), "MDL", "MOLDRETAIL"),), Reason.AMOUNT_INVALID),
    ((item("D", DUE, D0, "1"),), Reason.DATE_ORDER_INVALID),                    # due before document
    ((item("D", date(2026, 7, 1), date(2026, 8, 1), "1"),), Reason.DATE_ORDER_INVALID),  # after as_of
    ((OpenItem("D", "2026-01-01", DUE, Decimal(1), "MDL", "MOLDRETAIL"),), Reason.DATE_INVALID),
])
def test_aging_refusals_have_fixed_codes(rows, reason):
    r = age(rows, ASOF)
    assert r.state is AgingState.NOT_AVAILABLE
    assert r.reason is reason
    assert r.buckets == ()


def test_timezone_naive_and_aware_datetimes_are_refused_not_coerced():
    naive = datetime(2026, 1, 1, 0, 0)  # noqa: DTZ001 - naive on purpose
    aware = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    for bad in (naive, aware):
        assert age((OpenItem("D", bad, DUE, Decimal(1), "MDL", "MOLDRETAIL"),), ASOF).reason \
            is Reason.DATE_INVALID
        assert age((OpenItem("D", D0, bad, Decimal(1), "MDL", "MOLDRETAIL"),), ASOF).reason \
            is Reason.DATE_INVALID
        assert age((item("D", D0, DUE, "1"),), bad).reason is Reason.DATE_INVALID
        assert qualify_strategy(LEDGER, inputs(period_from=bad), source()).reason is Reason.INPUT_INVALID
        assert qualify_strategy(LEDGER, inputs(), source(covered_from=bad)).reason is Reason.INPUT_INVALID


@pytest.mark.parametrize("as_of", [None, "2026-06-01", 20260601])
def test_as_of_must_be_a_plain_date(as_of):
    r = age((item("D", D0, DUE, "1"),), as_of)
    assert r.reason is Reason.DATE_INVALID and r.as_of is None


def test_zero_amount_row_is_allowed_and_same_day_due_is_valid():
    r = age((item("D", D0, D0, "0"), item("E", D0, ASOF, "5")), ASOF)
    assert r.state is AgingState.AVAILABLE
    assert r.open_total == Decimal(5)


def test_declared_total_must_equal_row_sum_exactly():
    rows = (item("D", D0, DUE, "10.00"), item("E", D0, DUE, "0.01"))
    assert age(rows, total=Decimal("10.01")).state is AgingState.AVAILABLE
    off = age(rows, total=Decimal("10.02"))
    assert (off.state, off.reason) == (AgingState.NOT_AVAILABLE, Reason.TOTAL_MISMATCH)
    assert age(rows, total=10.01).reason is Reason.AMOUNT_INVALID


def test_exactness_no_float_rounding_on_many_small_amounts():
    rows = tuple(item(f"D{i}", D0, DUE, "0.1") for i in range(1000))
    r = age(rows, ASOF)
    assert r.open_total == Decimal("100.0")
    assert all(isinstance(v, Decimal) for _, v in r.buckets)


def test_wide_amounts_sum_exactly_without_rounding():
    big = Decimal("9" * 30)
    rows = tuple(OpenItem(f"D{i}", D0, DUE, big, "MDL", "MOLDRETAIL") for i in range(3))
    r = age(rows)
    assert r.state is AgingState.AVAILABLE and r.open_total == Decimal(3 * 10**30 - 3)
    wide = Decimal("1." + "1" * 8)
    one = age((OpenItem("D", D0, DUE, wide, "MDL", "MOLDRETAIL"),))
    assert one.state is AgingState.AVAILABLE and one.open_total == wide


def test_too_many_items_refused():
    rows = (item("D", D0, DUE, "1"),) * (mod.MAX_ITEMS + 1)
    assert age(rows, ASOF).reason is Reason.TOO_MANY_ITEMS


def test_aging_digest_deterministic_order_independent_and_input_sensitive():
    a, b = item("A", D0, DUE, "1"), item("B", D0, DUE, "2")
    base = age((a, b), ASOF)
    assert base.digest == age((b, a), ASOF).digest
    assert base.digest != age((a, item("B", D0, DUE, "3")), ASOF).digest
    assert base.digest != age((a, b), date(2026, 6, 2)).digest
    assert base.digest != age((a, item("B", D0, date(2026, 2, 2), "2")), ASOF).digest
    refused = age((), ASOF)
    assert refused.digest != base.digest
    assert refused.digest == age((), ASOF).digest


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
    assert age(hostile, ASOF).state is AgingState.NOT_AVAILABLE
    assert age((hostile,), ASOF).state is AgingState.NOT_AVAILABLE


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
    assert secret not in repr(age((item(secret, D0, DUE, "-1"),), ASOF))


def test_results_are_frozen_slotted_dataclasses():
    for obj in (qualified(), make_balance_view(qualified(), Decimal(1)),
                age((item("D", D0, DUE, "1"),), ASOF), source(), inputs(),
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


def test_validation_coverage_never_enables_ap_account_based_from_a_strategy_result():
    from business_ai_gateway.phase2.validation_coverage import (
        RESERVED_CAPABILITIES,
        capability_enabled,
    )
    assert "ap.account_based" in RESERVED_CAPABILITIES
    for result in (qualified(), make_balance_view(qualified(), Decimal(1))):
        assert capability_enabled(result, object(), "ap.account_based") is False
    assert not hasattr(mod, "capability_enabled")


# ------------------------------------------------------------------ S6b review fixes

class _Liar(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


def test_str_subclass_with_lying_eq_is_not_a_strategy_name():
    r = qualify_strategy(_Liar("whatever"), inputs(), source())
    assert r.reason is Reason.UNKNOWN_STRATEGY and r.strategy is None


def test_qualified_result_carries_normalised_declared_inputs():
    r = qualify_strategy(LEDGER, inputs(company=" moldretail ", currency="mdl",
                                        account_codes=("60.02", "60.01")), source())
    assert (r.register, r.company, r.currency) == ("хозрасчетный", "moldretail", "mdl")
    assert r.account_codes == ("60.01", "60.02") and r.analytics_keys == ("договор", "контрагент")
    assert (r.period_from, r.period_until) == (P_FROM, P_UNTIL)
    refused = qualify_strategy(LEDGER, inputs(company="other"), source())
    assert refused.company == "" and refused.period_from is None  # refusals carry no caller text


def test_qualified_digest_covers_the_source_description():
    base = qualified().digest
    assert qualify_strategy(LEDGER, inputs(), source(currencies=("MDL", "EUR"))).digest != base
    assert qualify_strategy(LEDGER, inputs(), source(covered_until=date(2029, 1, 1))).digest != base
    assert qualify_strategy(LEDGER, inputs(), source(account_codes=("60.01", "60.02", "60.03"))).digest != base


def test_mixed_script_company_and_register_are_refused_not_matched():
    mixed_company = "\u041cOLDRETAIL"  # Cyrillic EM + Latin OLDRETAIL
    r = qualify_strategy(LEDGER, inputs(company=mixed_company), source())
    assert r.reason is Reason.INPUT_NOT_DECLARED and r.missing == (InputName.COMPANY,)
    mixed_register = "\u0425ozraschet"  # Cyrillic Kha + Latin
    r = qualify_strategy(LEDGER, inputs(register=mixed_register), source(accounting_registers=(mixed_register,)))
    assert r.reason is Reason.INPUT_INVALID  # the source entry itself is mixed-script
    r = qualify_strategy(LEDGER, inputs(register=mixed_register), source())
    assert r.reason is Reason.INPUT_NOT_DECLARED and r.missing == (InputName.REGISTER,)
    r = qualify_strategy(LEDGER, inputs(), source(companies=(mixed_company,)))
    assert r.reason is Reason.INPUT_INVALID


@pytest.mark.parametrize(("field", "value"), [
    ("companies", ("MoldRetail", "MOLDRETAIL")),
    ("currencies", ("MDL", "mdl")),
    ("accounting_registers", ("Хозрасчетный", "ХОЗРАСЧЕТНЫЙ")),
])
def test_case_colliding_source_entries_are_refused(field, value):
    assert qualify_strategy(LEDGER, inputs(), source(**{field: value})).reason is Reason.INPUT_INVALID


def test_exact_duplicate_source_entries_are_harmless():
    ok = qualify_strategy(LEDGER, inputs(), source(companies=("MOLDRETAIL", "MOLDRETAIL")))
    assert ok.state is StrategyState.QUALIFIED


@pytest.mark.parametrize(("src_kw", "missing"), [
    ({"covered_until": P_UNTIL}, None),                          # period_until == covered_until
    ({"covered_until": date(2026, 12, 31)}, InputName.PERIOD),   # covered one day short
    ({"covered_from": P_FROM}, None),                            # period_from == covered_from
    ({"covered_from": date(2026, 1, 2)}, InputName.PERIOD),      # covered starts one day late
])
def test_period_boundary_equality(src_kw, missing):
    r = qualify_strategy(LEDGER, inputs(), source(**src_kw))
    if missing is None:
        assert r.state is StrategyState.QUALIFIED
    else:
        assert r.state is StrategyState.UNQUALIFIED and r.missing == (missing,)


def test_settlements_register_present_but_company_currency_period_missing_is_unqualified():
    src = source(settlements_registers=("Расчеты",), companies=(), currencies=(),
                 covered_from=None, covered_until=None)
    r = qualify_strategy(SETTLE, inputs(register="Расчеты"), src)
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_NOT_IN_SOURCE
    assert r.missing == (InputName.COMPANY, InputName.CURRENCY, InputName.PERIOD)


def test_settlements_strategy_validates_only_the_fields_it_uses():
    src = source(settlements_registers=("Расчеты",), account_codes=("", 5), analytics_keys="bad")
    decl = inputs(register="Расчеты", account_codes="bad", analytics_keys=(None,))
    r = qualify_strategy(SETTLE, decl, src)
    assert r.state is StrategyState.QUALIFIED
    assert r.account_codes == () and r.analytics_keys == ()
    # the ledger strategy does use them
    assert qualify_strategy(LEDGER, decl, source()).reason is Reason.INPUT_INVALID


def test_malformed_settlements_description_is_input_invalid_not_absent():
    assert qualify_strategy(SETTLE, inputs(register="X"), source(settlements_registers="X")).reason \
        is Reason.INPUT_INVALID
    assert qualify_strategy(SETTLE, inputs(register="X"), source(companies=("",))).reason \
        is Reason.INPUT_INVALID


def test_balance_digest_is_exact_beyond_28_significant_digits():
    a = Decimal("1" * 30 + "." + "1" * 8)          # 38 significant digits, the allowed maximum
    b = Decimal("1" * 30 + "." + "1" * 7 + "2")
    va, vb = make_balance_view(qualified(), a), make_balance_view(qualified(), b)
    assert va.state is ApViewState.BALANCE_ONLY and vb.state is ApViewState.BALANCE_ONLY
    assert va.digest != vb.digest
    assert mod._dec_text(a) == "1" * 30 + "." + "1" * 8


def test_balance_view_carries_the_strategy_company_and_currency():
    v = make_balance_view(qualify_strategy(LEDGER, inputs(company="MoldRetail", currency="Mdl"), source()),
                          Decimal(5))
    assert (v.company, v.currency) == ("moldretail", "mdl")
    eur = qualify_strategy(LEDGER, inputs(currency="EUR"), source(currencies=("MDL", "EUR")))
    mdl = qualify_strategy(LEDGER, inputs(), source(currencies=("MDL", "EUR")))
    assert make_balance_view(eur, Decimal(5)).currency == "eur"
    assert make_balance_view(eur, Decimal(5)).digest != make_balance_view(mdl, Decimal(5)).digest


def test_hand_built_qualified_result_without_bound_inputs_is_refused():
    bare = dataclasses.replace(qualified(), company="", currency="")
    assert make_balance_view(bare, Decimal(1)).state is ApViewState.UNQUALIFIED
    assert age((item("D", D0, DUE, "1"),), strat=bare).reason is Reason.STRATEGY_NOT_QUALIFIED
    no_period = dataclasses.replace(qualified(), period_until=None)
    assert age((item("D", D0, DUE, "1"),), strat=no_period).reason is Reason.STRATEGY_NOT_QUALIFIED


@pytest.mark.parametrize(("company", "currency"), [
    ("OTHER", "MDL"), ("MOLDRETAIL", "EUR"), ("", "MDL"), ("MOLDRETAIL", ""), (None, "MDL"),
])
def test_open_item_company_and_currency_must_match_the_strategy(company, currency):
    row = OpenItem("D", D0, DUE, Decimal(1), currency, company)
    r = age((item("A", D0, DUE, "1"), row), total=Decimal(2))
    assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.ITEM_SCOPE_MISMATCH)
    assert r.buckets == ()


def test_open_item_scope_is_compared_after_normalisation():
    row = OpenItem("D", D0, DUE, Decimal(1), " mdl ", "MoldRetail")
    assert age((row,)).state is AgingState.AVAILABLE


@pytest.mark.parametrize(("as_of", "ok"), [
    (P_FROM, True), (date(2026, 12, 31), True), (P_UNTIL, False), (date(2027, 6, 1), False),
    (date(2025, 12, 31), False),
])
def test_as_of_must_lie_in_the_half_open_strategy_period(as_of, ok):
    r = age((OpenItem("D", P_FROM, P_FROM, Decimal(1), "MDL", "MOLDRETAIL"),), as_of)
    if ok:
        assert r.state is AgingState.AVAILABLE
    else:
        assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.AS_OF_OUT_OF_PERIOD)


def test_declared_total_is_mandatory_for_an_available_aging():
    rows = (item("D", D0, DUE, "10"),)
    r = compute_aging(qualified(), rows, ASOF)
    assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.DECLARED_TOTAL_REQUIRED)
    assert r.buckets == () and r.open_total is None
    assert compute_aging(qualified(), rows, ASOF, None).reason is Reason.DECLARED_TOTAL_REQUIRED
    assert compute_aging(qualified(), rows, ASOF, Decimal(10)).state is AgingState.AVAILABLE


def test_several_instalments_of_one_document_are_allowed_same_due_date_is_a_duplicate():
    inst = (item("INV-1", D0, date(2026, 3, 1), "10"), item("INV-1", D0, date(2026, 4, 1), "20"))
    r = age(inst)
    assert r.state is AgingState.AVAILABLE and r.open_total == Decimal(30)
    dup = age((item("INV-1", D0, DUE, "10"), item(" inv-1 ", D0, DUE, "20")))
    assert dup.reason is Reason.DUPLICATE_ITEM


def test_aging_digest_is_bound_to_the_strategy():
    rows = (item("D", D0, DUE, "1"),)
    other = qualify_strategy(LEDGER, inputs(), source(currencies=("MDL", "EUR")))
    assert age(rows).digest != age(rows, strat=other).digest


# ------------------------------------------------------------------ GPT-PM round fixes (M04, M07, M08, M09)

ZERO_REFS = ["00000000-0000-0000-0000-000000000000", "{00000000-0000-0000-0000-000000000000}",
             "0" * 32, " (00000000-0000-0000-0000-000000000000) "]


@pytest.mark.parametrize("ref", ZERO_REFS)
def test_m04_empty_1c_document_reference_refuses_the_whole_aging(ref):
    r = age((item("D1", D0, DUE, "5"), item(ref, D0, DUE, "10")), ASOF)
    assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.DOC_REF_EMPTY_1C)
    assert r.buckets == () and r.open_total is None


def test_m04_a_real_guid_document_reference_is_accepted():
    r = age((item("3f2504e0-4f89-11d3-9a0c-0305e82c3301", D0, DUE, "10"),), ASOF)
    assert r.state is AgingState.AVAILABLE


@pytest.mark.parametrize("field", ["company", "register"])
def test_m04_empty_1c_reference_is_not_a_declared_identity(field):
    zero = ZERO_REFS[0]
    kw = {field: zero}
    src = source(companies=(zero,)) if field == "company" else source(accounting_registers=(zero,))
    r = qualify_strategy(LEDGER, inputs(**kw), src)
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_INVALID


@pytest.mark.parametrize("field", ["tenant_id", "source_id"])
def test_m04_empty_1c_reference_is_not_a_tenant_or_source(field):
    zero = ZERO_REFS[0]
    r = qualify_strategy(LEDGER, inputs(**{field: zero}), source(**{field: zero}))
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_INVALID


def test_m07_comma_in_declared_or_source_elements_does_not_collide_digests():
    a = qualify_strategy(LEDGER, inputs(account_codes=("a,b", "c")),
                         source(account_codes=("a,b", "c")))
    b = qualify_strategy(LEDGER, inputs(account_codes=("a", "b,c")),
                         source(account_codes=("a", "b,c")))
    assert a.state is b.state is StrategyState.QUALIFIED
    assert a.digest != b.digest
    k1 = qualify_strategy(LEDGER, inputs(analytics_keys=("x,y", "z")), source(analytics_keys=("x,y", "z")))
    k2 = qualify_strategy(LEDGER, inputs(analytics_keys=("x", "y,z")), source(analytics_keys=("x", "y,z")))
    assert k1.digest != k2.digest
    # source-only ambiguity: the same declared inputs against differently-split source lists
    s1 = qualify_strategy(LEDGER, inputs(), source(account_codes=("60.01", "x,y")))
    s2 = qualify_strategy(LEDGER, inputs(), source(account_codes=("60.01", "x", "y")))
    assert s1.digest != s2.digest
    c1 = qualify_strategy(LEDGER, inputs(), source(companies=("MOLDRETAIL", "a,b")))
    c2 = qualify_strategy(LEDGER, inputs(), source(companies=("MOLDRETAIL", "a", "b")))
    assert c1.digest != c2.digest
    # downstream digests follow
    assert make_balance_view(a, Decimal(1)).digest != make_balance_view(b, Decimal(1)).digest
    rows = (item("D", D0, DUE, "1"),)
    assert age(rows, strat=a).digest != age(rows, strat=b).digest


def test_m07_digest_is_sensitive_to_every_declared_and_source_input():
    base = qualified().digest
    variants = [
        qualify_strategy(LEDGER, inputs(register="Другой"), source(accounting_registers=("Хозрасчетный", "Другой"))),
        qualify_strategy(LEDGER, inputs(account_codes=("60.01", "60.02")), source()),
        qualify_strategy(LEDGER, inputs(analytics_keys=("Контрагент",)), source()),
        qualify_strategy(LEDGER, inputs(company="OTHER"), source(companies=("MOLDRETAIL", "OTHER"))),
        qualify_strategy(LEDGER, inputs(currency="EUR"), source(currencies=("MDL", "EUR"))),
        qualify_strategy(LEDGER, inputs(period_from=date(2026, 2, 1)), source()),
        qualify_strategy(LEDGER, inputs(period_until=date(2026, 12, 1)), source()),
        qualify_strategy(LEDGER, inputs(), source(accounting_registers=("Хозрасчетный", "Z"))),
        qualify_strategy(LEDGER, inputs(), source(account_codes=("60.01", "60.02", "60.03"))),
        qualify_strategy(LEDGER, inputs(), source(analytics_keys=("Контрагент", "Договор", "Склад"))),
        qualify_strategy(LEDGER, inputs(), source(companies=("MOLDRETAIL", "OTHER"))),
        qualify_strategy(LEDGER, inputs(), source(currencies=("MDL", "EUR"))),
        qualify_strategy(LEDGER, inputs(), source(covered_from=date(2025, 6, 1))),
        qualify_strategy(LEDGER, inputs(), source(covered_until=date(2029, 1, 1))),
        qualify_strategy(LEDGER, inputs(tenant_id="TENANT-B"), source(tenant_id="TENANT-B")),
        qualify_strategy(LEDGER, inputs(source_id="SRC-2"), source(source_id="SRC-2")),
    ]
    assert all(v.state is StrategyState.QUALIFIED for v in variants)
    digests = [v.digest for v in variants]
    assert base not in digests and len(set(digests)) == len(digests)


class _LyingNe(str):
    def __ne__(self, other):
        return False

    __eq__ = str.__eq__
    __hash__ = str.__hash__


def test_m08_str_subclass_cannot_hide_a_case_collision():
    r = qualify_strategy(LEDGER, inputs(), source(companies=(_LyingNe("MoldRetail"), _LyingNe("MOLDRETAIL"))))
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_INVALID


@pytest.mark.parametrize("field", ["accounting_registers", "account_codes", "analytics_keys",
                                   "companies", "currencies"])
def test_m08_source_list_elements_must_be_exactly_str(field):
    plain = getattr(source(), field)
    r = qualify_strategy(LEDGER, inputs(), source(**{field: (_LyingNe(plain[0]),) + plain[1:]}))
    assert r.reason is Reason.INPUT_INVALID


def test_m08_declared_inputs_must_be_exactly_str():
    assert qualify_strategy(LEDGER, inputs(account_codes=(_LyingNe("60.01"),)), source()).reason \
        is Reason.INPUT_INVALID
    assert qualify_strategy(LEDGER, inputs(analytics_keys=(_LyingNe("Контрагент"),)), source()).reason \
        is Reason.INPUT_INVALID
    for field in ("register", "company", "currency", "tenant_id", "source_id"):
        r = qualify_strategy(LEDGER, inputs(**{field: _LyingNe(getattr(inputs(), field))}), source())
        assert r.reason is Reason.INPUT_INVALID, field


class _TupleSub(tuple):
    pass


def test_m08_containers_must_be_exact_tuples():
    assert qualify_strategy(LEDGER, inputs(), source(companies=_TupleSub(("MOLDRETAIL",)))).reason \
        is Reason.INPUT_INVALID
    rows = _TupleSub((item("D", D0, DUE, "1"),))
    assert age(rows, ASOF).reason is Reason.ITEMS_INVALID


def test_m08_open_item_text_must_be_exactly_str():
    for kw in ({"company": _LyingNe("MOLDRETAIL")}, {"currency": _LyingNe("MDL")},
               {"tenant_id": _LyingNe(TENANT)}, {"source_id": _LyingNe(SOURCE)}):
        base = dict(company="MOLDRETAIL", currency="MDL", tenant_id=TENANT, source_id=SOURCE)  # noqa: C408
        base.update(kw)
        row = OpenItem("D", D0, DUE, Decimal(1), **base)
        assert age((row,)).reason is Reason.ITEM_SCOPE_MISMATCH, kw
    row = OpenItem(_LyingNe("D"), D0, DUE, Decimal(1), "MDL", "MOLDRETAIL", TENANT, SOURCE)
    assert age((row,)).reason is Reason.ITEM_REF_INVALID


def test_m08_hand_built_result_with_str_subclass_fields_is_refused():
    for field in ("company", "currency", "tenant_id", "source_id"):
        bad = dataclasses.replace(qualified(), **{field: _LyingNe(getattr(qualified(), field))})
        assert make_balance_view(bad, Decimal(1)).state is ApViewState.UNQUALIFIED, field
        assert age((item("D", D0, DUE, "1"),), strat=bad).reason is Reason.STRATEGY_NOT_QUALIFIED, field


def test_m09_tenant_and_source_must_be_declared():
    for kw in ({"tenant_id": ""}, {"source_id": " "}):
        r = qualify_strategy(LEDGER, inputs(**kw), source())
        assert r.reason is Reason.INPUT_NOT_DECLARED
        assert r.missing == ((InputName("TENANT"),) if "tenant_id" in kw else (InputName("SOURCE"),))


@pytest.mark.parametrize(("src_kw", "missing"), [
    ({"tenant_id": "TENANT-B"}, "TENANT"), ({"tenant_id": ""}, "TENANT"),
    ({"source_id": "SRC-2"}, "SOURCE"), ({"source_id": ""}, "SOURCE"),
])
def test_m09_source_of_another_tenant_or_source_does_not_qualify(src_kw, missing):
    r = qualify_strategy(LEDGER, inputs(), source(**src_kw))
    assert r.state is StrategyState.UNQUALIFIED and r.reason is Reason.INPUT_NOT_IN_SOURCE
    assert r.missing == (getattr(InputName, missing),)
    assert r.tenant_id == "" and r.source_id == ""


def test_m09_settlements_strategy_is_tenant_and_source_bound_too():
    ok = qualify_strategy(SETTLE, inputs(register="Расчеты"), source(settlements_registers=("Расчеты",)))
    assert ok.state is StrategyState.QUALIFIED and (ok.tenant_id, ok.source_id) == ("tenant-a", "src-1")
    other = qualify_strategy(SETTLE, inputs(register="Расчеты", tenant_id="TENANT-B"),
                             source(settlements_registers=("Расчеты",)))
    assert other.state is StrategyState.UNQUALIFIED and other.missing == (InputName("TENANT"),)


def test_m09_qualified_result_carries_normalised_tenant_and_source():
    r = qualify_strategy(LEDGER, inputs(tenant_id=" Tenant-A ", source_id="src-1"), source())
    assert (r.tenant_id, r.source_id) == ("tenant-a", "src-1")


@pytest.mark.parametrize("kw", [{"tenant_id": "TENANT-B"}, {"source_id": "SRC-2"},
                                {"tenant_id": ""}, {"source_id": ""}, {"tenant_id": None}])
def test_m09_open_items_of_another_tenant_or_source_are_refused(kw):
    base = dict(currency="MDL", company="MOLDRETAIL", tenant_id=TENANT, source_id=SOURCE)  # noqa: C408
    base.update(kw)
    row = OpenItem("D", D0, DUE, Decimal(1), **base)
    r = age((item("A", D0, DUE, "1"), row), total=Decimal(2))
    assert (r.state, r.reason) == (AgingState.NOT_AVAILABLE, Reason.ITEM_SCOPE_MISMATCH)


def test_m09_strategy_of_one_tenant_cannot_age_items_of_another_tenant_with_same_company():
    strat_b = qualify_strategy(LEDGER, inputs(tenant_id="TENANT-B"), source(tenant_id="TENANT-B"))
    assert strat_b.state is StrategyState.QUALIFIED
    rows_a = (item("D", D0, DUE, "1"),)
    assert age(rows_a, strat=strat_b).reason is Reason.ITEM_SCOPE_MISMATCH


def test_m09_balance_and_aging_carry_and_bind_tenant_and_source():
    strat_b = qualify_strategy(LEDGER, inputs(tenant_id="TENANT-B"), source(tenant_id="TENANT-B"))
    strat_s = qualify_strategy(LEDGER, inputs(source_id="SRC-2"), source(source_id="SRC-2"))
    va, vb = make_balance_view(qualified(), Decimal(5)), make_balance_view(strat_b, Decimal(5))
    assert (va.tenant_id, va.source_id) == ("tenant-a", "src-1")
    assert (vb.tenant_id, vb.source_id) == ("tenant-b", "src-1")
    assert va.digest != vb.digest != make_balance_view(strat_s, Decimal(5)).digest
    ra = age((item("D", D0, DUE, "1"),))
    rb = age((OpenItem("D", D0, DUE, Decimal(1), "MDL", "MOLDRETAIL", "TENANT-B", SOURCE),), strat=strat_b)
    assert (ra.tenant_id, ra.source_id) == ("tenant-a", "src-1")
    assert (rb.tenant_id, rb.source_id) == ("tenant-b", "src-1")
    assert ra.digest != rb.digest


def test_m09_hand_built_result_without_tenant_or_source_is_refused():
    for field in ("tenant_id", "source_id"):
        bare = dataclasses.replace(qualified(), **{field: ""})
        assert make_balance_view(bare, Decimal(1)).state is ApViewState.UNQUALIFIED
        assert age((item("D", D0, DUE, "1"),), strat=bare).reason is Reason.STRATEGY_NOT_QUALIFIED
