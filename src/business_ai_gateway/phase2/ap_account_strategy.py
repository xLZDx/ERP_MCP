"""Phase 2: explicit account-based AP strategy for 818HA (R2-US-031, TC091-TC093).

Pure, in-memory, no I/O, no clock, no write path. AP is never computed implicitly: the caller names
a strategy, declares its inputs and supplies a description of what the source actually offers.

Rules
- Two named strategies exist: ``ledger_accounting_register`` (AP derived from an accounting register)
  and ``settlements_register`` (an accumulation register of settlements with counterparties). An
  unknown name is UNQUALIFIED with ``UNKNOWN_STRATEGY``; there is no default and no fallback. The
  name must be exactly a ``str`` or a ``Strategy`` member (a str subclass with a custom ``__eq__`` is
  refused). ``StrategyResult.strategy`` is None for UNKNOWN_STRATEGY and for the catch-all
  INPUT_INVALID raised by an unexpected exception.
- A strategy validates ONLY the fields it uses: the settlements strategy never looks at account codes
  or analytics keys (declared or in the source), so a malformed ledger-only field cannot turn it into
  INPUT_INVALID. Source lists are matched after identity normalisation; a source list in which two
  DIFFERENT raw entries normalise to the same identity (case-colliding, e.g. ``MoldRetail`` and
  ``MOLDRETAIL``) is ambiguous and refused as INPUT_INVALID (exact duplicates are harmless).
- ABSENT is returned only for a WELL-FORMED description that does not list the settlements register.
  A malformed field it uses (wrong type, forbidden characters, collisions) is INPUT_INVALID, never
  ABSENT; a description that lists the register but lacks company/currency/period is UNQUALIFIED
  with INPUT_NOT_IN_SOURCE.
- A QUALIFIED ``StrategyResult`` carries the normalised declared inputs (register, account codes,
  analytics keys, company, currency, period) and its digest also covers the source description
  fields the strategy used, so the same declared inputs against a different source differ.
  Nested sequences are encoded structurally (``stable_key`` per list), so ``("a,b","c")`` and
  ``("a","b,c")`` never share a digest.
- Tenant/source: ``SourceDescription``, ``LedgerInputs`` and ``OpenItem`` carry ``tenant_id`` and
  ``source_id``. They are CALLER-ASSERTED (this module has no way to prove them), but they are mandatory
  (``TENANT``/``SOURCE`` are missing inputs), the declared pair must equal the source description's pair
  (otherwise INPUT_NOT_IN_SOURCE, never ABSENT), a QUALIFIED result/balance/aging carries them and binds
  them into its digest, and every open item must carry the same pair (``ITEM_SCOPE_MISMATCH``).
- Exact types: every text input (declared scalars, list elements, open-item fields) must be exactly
  ``str`` and every container exactly ``tuple``; a subclass (e.g. a lying ``__ne__``) is refused. The 1C
  empty reference (all-zero GUID) is no identity: as a declared/source identity it is INPUT_INVALID and
  as an open-item ``doc_ref`` it refuses the whole aging with ``DOC_REF_EMPTY_1C``.
  ``compute_aging`` and ``make_balance_view`` bind to them: every open item must carry the strategy's
  company and currency (otherwise ``ITEM_SCOPE_MISMATCH``), ``as_of`` must lie in
  ``period_from <= as_of < period_until`` (the same half-open interval as qualification, so a date
  equal to ``period_until`` belongs to the NEXT period; otherwise ``AS_OF_OUT_OF_PERIOD``) and a balance
  view carries the strategy's company and currency.
- The ledger strategy declares register, account codes, analytics keys, company, currency and period.
  It is QUALIFIED only if EVERY declared input is present in the source description (the period must
  lie inside the covered ``[from, until)``). Anything else is UNQUALIFIED with a fixed reason code and
  the list of missing inputs; no number is ever produced from an unqualified strategy.
- A settlements register that the source description does not list is ABSENT: a first-class result
  (never an exception, never a silent switch to the ledger strategy, no balance and no aging).
- A balance (one closing value) is BALANCE_ONLY. It cannot yield aging: aging is NOT_AVAILABLE.
- Aging needs open-item rows and BOTH the document date and the due date on EVERY row. One missing
  date refuses the whole aging (no partial aging, no assumed date). Buckets are measured on days past
  due at ``as_of`` (0 or less is CURRENT; 1-30; 31-60; 61-90; 91+), and they sum EXACTLY to the open
  total (Decimal only, no floats, inexact arithmetic is refused).
- Amount policy: an open-item amount is never negative (zero is allowed). A credit note or prepayment
  must be mapped by the caller (same rule as ``contract_netting``); a negative amount refuses the aging
  with ``NEGATIVE_AMOUNT`` instead of netting against other rows.
- Date policy: only plain ``datetime.date`` values are accepted. ``datetime`` objects (naive or
  timezone-aware) are refused (``DATE_INVALID``): a time part would silently shift the day boundary.
- Result codes are fixed ``StrEnum`` values; caller text is never echoed into them or into digests of
  refusals. Hostile input (wrong types, non-Decimal amounts, forbidden characters, oversize) never
  raises: it yields a refusal code.
- Digests are canonical (sha256 of an ASCII JSON array) and are INTEGRITY only, not authenticity: a
  ``StrategyResult`` is not re-verified against its source description, so a hand-built QUALIFIED
  result is not distinguishable here. The trusted caller must obtain it from ``qualify_strategy``.
- This module does not call ``validation_coverage`` and does not enable ``ap.account_based``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, Inexact, localcontext
from enum import StrEnum

from ._identity import canonical_guid, clean_identity, is_empty_1c_ref, stable_key

__all__ = [
    "AgingBucket", "AgingResult", "AgingState", "ApViewState", "BalanceView", "InputName",
    "LedgerInputs", "OpenItem", "Reason", "SourceDescription", "Strategy", "StrategyResult",
    "StrategyState", "compute_aging", "make_balance_view", "qualify_strategy",
]

MAX_ITEMS = 50_000
MAX_LIST = 10_000
_MAX_ADJUSTED = 30
_MIN_EXPONENT = -8
_EXACT = Context(prec=60, Emin=-999_999, Emax=999_999)
_EXACT.traps[Inexact] = True


class Strategy(StrEnum):
    LEDGER_ACCOUNTING_REGISTER = "ledger_accounting_register"
    SETTLEMENTS_REGISTER = "settlements_register"


class StrategyState(StrEnum):
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    ABSENT = "ABSENT"


class InputName(StrEnum):
    REGISTER = "REGISTER"
    ACCOUNT_CODES = "ACCOUNT_CODES"
    ANALYTICS_KEYS = "ANALYTICS_KEYS"
    COMPANY = "COMPANY"
    CURRENCY = "CURRENCY"
    PERIOD = "PERIOD"
    TENANT = "TENANT"
    SOURCE = "SOURCE"


class Reason(StrEnum):
    ALL_INPUTS_PRESENT = "ALL_INPUTS_PRESENT"
    UNKNOWN_STRATEGY = "UNKNOWN_STRATEGY"
    INPUT_INVALID = "INPUT_INVALID"
    INPUT_NOT_DECLARED = "INPUT_NOT_DECLARED"
    INPUT_NOT_IN_SOURCE = "INPUT_NOT_IN_SOURCE"
    REGISTER_NOT_IN_SOURCE = "REGISTER_NOT_IN_SOURCE"
    STRATEGY_NOT_QUALIFIED = "STRATEGY_NOT_QUALIFIED"
    BALANCE_ONLY_NO_ITEMS = "BALANCE_ONLY_NO_ITEMS"
    BALANCE_INVALID = "BALANCE_INVALID"
    ITEMS_INVALID = "ITEMS_INVALID"
    ITEMS_EMPTY = "ITEMS_EMPTY"
    TOO_MANY_ITEMS = "TOO_MANY_ITEMS"
    ITEM_REF_INVALID = "ITEM_REF_INVALID"
    DOC_REF_EMPTY_1C = "DOC_REF_EMPTY_1C"
    DUPLICATE_ITEM = "DUPLICATE_ITEM"
    DATE_MISSING = "DATE_MISSING"
    DATE_INVALID = "DATE_INVALID"
    DATE_ORDER_INVALID = "DATE_ORDER_INVALID"
    AMOUNT_INVALID = "AMOUNT_INVALID"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    ITEM_SCOPE_MISMATCH = "ITEM_SCOPE_MISMATCH"
    AS_OF_OUT_OF_PERIOD = "AS_OF_OUT_OF_PERIOD"
    DECLARED_TOTAL_REQUIRED = "DECLARED_TOTAL_REQUIRED"
    AGING_COMPUTED = "AGING_COMPUTED"


class ApViewState(StrEnum):
    BALANCE_ONLY = "BALANCE_ONLY"
    UNQUALIFIED = "UNQUALIFIED"
    ABSENT = "ABSENT"
    INPUT_INVALID = "INPUT_INVALID"


class AgingState(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class AgingBucket(StrEnum):
    CURRENT = "CURRENT"
    D1_30 = "D1_30"
    D31_60 = "D31_60"
    D61_90 = "D61_90"
    D91_PLUS = "D91_PLUS"


@dataclass(frozen=True, slots=True)
class SourceDescription:
    """What the source offers (a fixture or a discovery result), never data rows."""

    accounting_registers: tuple[str, ...] = ()
    settlements_registers: tuple[str, ...] = ()
    account_codes: tuple[str, ...] = ()
    analytics_keys: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ()
    covered_from: date | None = None  # inclusive
    covered_until: date | None = None  # exclusive
    tenant_id: str = ""  # caller-asserted tenant / source this description belongs to
    source_id: str = ""


@dataclass(frozen=True, slots=True)
class LedgerInputs:
    """The inputs a strategy declares. The settlements strategy uses only register/company/currency/period."""

    register: str = ""
    account_codes: tuple[str, ...] = ()
    analytics_keys: tuple[str, ...] = ()
    company: str = ""
    currency: str = ""
    period_from: date | None = None  # inclusive
    period_until: date | None = None  # exclusive
    tenant_id: str = ""  # caller-asserted; must equal the source description's tenant / source
    source_id: str = ""


@dataclass(frozen=True, slots=True)
class StrategyResult:
    state: StrategyState
    reason: Reason
    strategy: Strategy | None  # None for UNKNOWN_STRATEGY and for the catch-all INPUT_INVALID
    missing: tuple[InputName, ...]
    digest: str
    authority: str = "EVALUATION_ONLY"
    # normalised declared inputs; filled ONLY when QUALIFIED (refusals never carry caller text)
    register: str = ""
    account_codes: tuple[str, ...] = ()
    analytics_keys: tuple[str, ...] = ()
    company: str = ""
    currency: str = ""
    period_from: date | None = None
    period_until: date | None = None
    tenant_id: str = ""  # normalised; filled ONLY when QUALIFIED
    source_id: str = ""


@dataclass(frozen=True, slots=True)
class BalanceView:
    state: ApViewState
    reason: Reason
    balance: Decimal | None  # set only for BALANCE_ONLY
    aging_state: AgingState  # always NOT_AVAILABLE here
    aging_reason: Reason
    digest: str
    authority: str = "EVALUATION_ONLY"
    company: str = ""  # the strategy's normalised company / currency (BALANCE_ONLY only)
    currency: str = ""
    tenant_id: str = ""
    source_id: str = ""


@dataclass(frozen=True, slots=True)
class OpenItem:
    doc_ref: str
    document_date: date | None
    due_date: date | None
    amount: Decimal
    currency: str = ""  # must equal the qualified strategy's currency / company after normalisation
    company: str = ""
    tenant_id: str = ""  # caller-asserted; must equal the strategy's tenant / source
    source_id: str = ""


@dataclass(frozen=True, slots=True)
class AgingResult:
    state: AgingState
    reason: Reason
    as_of: date | None
    open_total: Decimal | None
    buckets: tuple[tuple[AgingBucket, Decimal], ...]  # empty unless AVAILABLE; all five buckets when set
    digest: str
    authority: str = "EVALUATION_ONLY"
    tenant_id: str = ""  # the strategy's normalised tenant / source (AVAILABLE only)
    source_id: str = ""


# ---------------------------------------------------------------- helpers

def _sha(*parts: str) -> str:
    return hashlib.sha256(stable_key(*parts).encode("ascii")).hexdigest()


def _dec_text(value: Decimal) -> str:
    """Exact canonical text: computed in the exact context, never rounded to the thread precision."""
    if value == 0:
        return "0"
    with localcontext(_EXACT):
        return format(value.normalize(), "f")


def _is_date(value: object) -> bool:
    return type(value) is date


def _empty_ref(value: object) -> bool:
    """The 1C empty reference in ANY spelling: the raw text and its normalised form are both tested."""
    return is_empty_1c_ref(value) or is_empty_1c_ref(clean_identity(value))


def _doc_key(value: object) -> str:
    """One key per document: the canonical GUID when GUID-shaped, else the normalised identity."""
    return canonical_guid(clean_identity(value)) or clean_identity(value)


def _norm_tuple(value: object, *, strict: bool = False) -> tuple[str, ...] | None:
    """Sorted unique normalised identities; None when the container or any element is unusable.

    ``strict`` (source lists) also refuses two DIFFERENT raw entries with the same normal form."""
    if type(value) is not tuple or len(value) > MAX_LIST:  # exact types: a subclass could lie
        return None
    out: dict[str, str] = {}
    for item in value:
        if type(item) is not str or _empty_ref(item):
            return None
        norm = clean_identity(item)
        if not norm:
            return None
        if strict and out.setdefault(norm, item) != item:  # plain stored str on both sides
            return None
        out[norm] = item
    return tuple(sorted(out))


def _ident(value: object) -> str:
    """Normalised identity of an EXACT ``str`` ('' for anything else, incl. str subclasses)."""
    return clean_identity(value) if type(value) is str else ""


def _scalar_ok(value: object) -> bool:
    return type(value) is str and not _empty_ref(value)


def _bound_ok(strategy: StrategyResult) -> bool:
    """A QUALIFIED result must carry plain-str bound scope and plain dates (hand-built ones may not)."""
    for text in (strategy.company, strategy.currency, strategy.tenant_id, strategy.source_id):
        if type(text) is not str or not text or _empty_ref(text):
            return False
    return type(strategy.period_from) is date and type(strategy.period_until) is date


def _amount_ok(value: object) -> bool:
    if type(value) is not Decimal or not value.is_finite():
        return False
    return value.adjusted() <= _MAX_ADJUSTED and value.as_tuple().exponent >= _MIN_EXPONENT  # type: ignore[operator]


def _strategy_result(
    state: StrategyState, reason: Reason, strategy: Strategy | None,
    missing: tuple[InputName, ...], material: tuple[str, ...] = (), bound: dict | None = None,
) -> StrategyResult:
    digest = _sha("ap-strategy-v2", state.value, reason.value, strategy.value if strategy else "",
                  stable_key(*(m.value for m in missing)), *material)
    return StrategyResult(state, reason, strategy, missing, digest, **(bound or {}))


# ---------------------------------------------------------------- strategy qualification

def qualify_strategy(name: object, declared: object, source: object) -> StrategyResult:
    """Qualify a NAMED strategy against the source description. Never raises, never falls back."""
    try:
        return _qualify(name, declared, source)
    except Exception:  # noqa: BLE001 - hostile objects must yield a refusal, never an exception
        return _strategy_result(StrategyState.UNQUALIFIED, Reason.INPUT_INVALID, None, ())


def _qualify(name: object, declared: object, source: object) -> StrategyResult:
    strategy: Strategy | None = None
    if type(name) is Strategy:
        strategy = name
    elif type(name) is str:  # exactly str: a subclass could lie in __eq__
        strategy = next((s for s in Strategy if name == s.value), None)
    if strategy is None:
        return _strategy_result(StrategyState.UNQUALIFIED, Reason.UNKNOWN_STRATEGY, None, ())
    if type(declared) is not LedgerInputs or type(source) is not SourceDescription:
        return _strategy_result(StrategyState.UNQUALIFIED, Reason.INPUT_INVALID, strategy, ())
    ledger = strategy is Strategy.LEDGER_ACCOUNTING_REGISTER
    invalid = _strategy_result(StrategyState.UNQUALIFIED, Reason.INPUT_INVALID, strategy, ())

    # only the fields this strategy uses are validated
    # exact plain str only (a subclass could lie in __eq__/__ne__); an empty 1C reference is no identity
    if not all(_scalar_ok(v) for v in (declared.register, declared.company, declared.currency,
                                       declared.tenant_id, declared.source_id,
                                       source.tenant_id, source.source_id)):
        return invalid
    register = clean_identity(declared.register)
    company = clean_identity(declared.company)
    currency = clean_identity(declared.currency)
    tenant = clean_identity(declared.tenant_id)
    source_id = clean_identity(declared.source_id)
    src_tenant = clean_identity(source.tenant_id)
    src_source = clean_identity(source.source_id)
    codes = _norm_tuple(declared.account_codes) if ledger else ()
    keys = _norm_tuple(declared.analytics_keys) if ledger else ()
    src_reg = _norm_tuple(source.accounting_registers if ledger else source.settlements_registers,
                          strict=True)
    src_codes = _norm_tuple(source.account_codes, strict=True) if ledger else ()
    src_keys = _norm_tuple(source.analytics_keys, strict=True) if ledger else ()
    src_companies = _norm_tuple(source.companies, strict=True)
    src_currencies = _norm_tuple(source.currencies, strict=True)
    if None in (src_reg, src_codes, src_keys, src_companies, src_currencies, codes, keys):
        return invalid
    for d in (declared.period_from, declared.period_until, source.covered_from, source.covered_until):
        if d is not None and not _is_date(d):
            return invalid

    # not declared at all -> the strategy cannot even be evaluated
    undeclared: list[InputName] = []
    if not register:
        undeclared.append(InputName.REGISTER)
    if ledger and not codes:
        undeclared.append(InputName.ACCOUNT_CODES)
    if ledger and not keys:
        undeclared.append(InputName.ANALYTICS_KEYS)
    if not company:
        undeclared.append(InputName.COMPANY)
    if not currency:
        undeclared.append(InputName.CURRENCY)
    if not tenant:
        undeclared.append(InputName.TENANT)
    if not source_id:
        undeclared.append(InputName.SOURCE)
    if (declared.period_from is None or declared.period_until is None
            or declared.period_from >= declared.period_until):
        undeclared.append(InputName.PERIOD)
    if undeclared:
        return _strategy_result(StrategyState.UNQUALIFIED, Reason.INPUT_NOT_DECLARED, strategy,
                                tuple(sorted(undeclared, key=lambda m: m.value)))

    # the digest covers the declared inputs AND the source fields this strategy used
    # (nested sequences are encoded structurally with stable_key, so element boundaries are unambiguous)
    material = (register, stable_key(*codes), stable_key(*keys),
                company, currency, declared.period_from.isoformat(), declared.period_until.isoformat(),
                tenant, source_id,
                "src", stable_key(*src_reg), stable_key(*src_codes), stable_key(*src_keys),
                stable_key(*src_companies), stable_key(*src_currencies),
                source.covered_from.isoformat() if source.covered_from else "",
                source.covered_until.isoformat() if source.covered_until else "",
                src_tenant, src_source)

    # the source description must belong to the declared tenant / source (caller-asserted)
    scope_missing: list[InputName] = []
    if tenant != src_tenant:
        scope_missing.append(InputName.TENANT)
    if source_id != src_source:
        scope_missing.append(InputName.SOURCE)

    # a settlements register that a well-formed source of the SAME scope does not list is ABSENT
    if not ledger and register not in src_reg and not scope_missing:
        return _strategy_result(StrategyState.ABSENT, Reason.REGISTER_NOT_IN_SOURCE, strategy,
                                (InputName.REGISTER,), material)

    missing: list[InputName] = list(scope_missing)
    if register not in src_reg:
        missing.append(InputName.REGISTER)
    if ledger and not set(codes) <= set(src_codes):
        missing.append(InputName.ACCOUNT_CODES)
    if ledger and not set(keys) <= set(src_keys):
        missing.append(InputName.ANALYTICS_KEYS)
    if company not in src_companies:
        missing.append(InputName.COMPANY)
    if currency not in src_currencies:
        missing.append(InputName.CURRENCY)
    if (source.covered_from is None or source.covered_until is None
            or declared.period_from < source.covered_from
            or declared.period_until > source.covered_until):
        missing.append(InputName.PERIOD)
    if missing:
        return _strategy_result(StrategyState.UNQUALIFIED, Reason.INPUT_NOT_IN_SOURCE, strategy,
                                tuple(sorted(missing, key=lambda m: m.value)), material)
    bound = {"register": register, "account_codes": codes, "analytics_keys": keys, "company": company,
             "currency": currency, "period_from": declared.period_from,
             "period_until": declared.period_until, "tenant_id": tenant, "source_id": source_id}
    return _strategy_result(StrategyState.QUALIFIED, Reason.ALL_INPUTS_PRESENT, strategy, (), material,
                            bound)


# ---------------------------------------------------------------- balance only

def _view(state: ApViewState, reason: Reason, balance: Decimal | None, aging_reason: Reason,
          strategy_digest: str, company: str = "", currency: str = "", tenant_id: str = "",
          source_id: str = "") -> BalanceView:
    digest = _sha("ap-balance-v2", state.value, reason.value,
                  _dec_text(balance) if balance is not None else "", aging_reason.value,
                  strategy_digest, company, currency, tenant_id, source_id)
    return BalanceView(state, reason, balance, AgingState.NOT_AVAILABLE, aging_reason, digest,
                       company=company, currency=currency, tenant_id=tenant_id, source_id=source_id)


def make_balance_view(strategy: object, closing_balance: object) -> BalanceView:
    """Label a single closing balance BALANCE_ONLY; aging is NOT_AVAILABLE. Never raises."""
    try:
        if type(strategy) is not StrategyResult or type(strategy.digest) is not str:
            return _view(ApViewState.INPUT_INVALID, Reason.INPUT_INVALID, None,
                         Reason.STRATEGY_NOT_QUALIFIED, "")
        if strategy.state is StrategyState.ABSENT:
            return _view(ApViewState.ABSENT, Reason.REGISTER_NOT_IN_SOURCE, None,
                         Reason.STRATEGY_NOT_QUALIFIED, strategy.digest)
        if strategy.state is not StrategyState.QUALIFIED:
            return _view(ApViewState.UNQUALIFIED, Reason.STRATEGY_NOT_QUALIFIED, None,
                         Reason.STRATEGY_NOT_QUALIFIED, strategy.digest)
        if not _bound_ok(strategy):  # hand-built result without bound inputs
            return _view(ApViewState.UNQUALIFIED, Reason.STRATEGY_NOT_QUALIFIED, None,
                         Reason.STRATEGY_NOT_QUALIFIED, strategy.digest)
        if not _amount_ok(closing_balance):
            return _view(ApViewState.INPUT_INVALID, Reason.BALANCE_INVALID, None,
                         Reason.STRATEGY_NOT_QUALIFIED, strategy.digest)
        return _view(ApViewState.BALANCE_ONLY, Reason.ALL_INPUTS_PRESENT, closing_balance,  # type: ignore[arg-type]
                     Reason.BALANCE_ONLY_NO_ITEMS, strategy.digest, strategy.company, strategy.currency,
                     strategy.tenant_id, strategy.source_id)
    except Exception:  # noqa: BLE001
        return _view(ApViewState.INPUT_INVALID, Reason.INPUT_INVALID, None,
                     Reason.STRATEGY_NOT_QUALIFIED, "")


# ---------------------------------------------------------------- aging from open items

def _no_aging(reason: Reason, as_of: object = None) -> AgingResult:
    when = as_of if _is_date(as_of) else None
    digest = _sha("ap-aging-v2", AgingState.NOT_AVAILABLE.value, reason.value,
                  when.isoformat() if when else "")  # type: ignore[union-attr]
    return AgingResult(AgingState.NOT_AVAILABLE, reason, when, None, (), digest)  # type: ignore[arg-type]


def _bucket(days_past_due: int) -> AgingBucket:
    if days_past_due <= 0:
        return AgingBucket.CURRENT
    if days_past_due <= 30:
        return AgingBucket.D1_30
    if days_past_due <= 60:
        return AgingBucket.D31_60
    if days_past_due <= 90:
        return AgingBucket.D61_90
    return AgingBucket.D91_PLUS


def compute_aging(strategy: object, items: object, as_of: object,
                  declared_total: object = None) -> AgingResult:
    """Aging buckets from open-item rows; the whole aging is refused on any defect. Never raises.

    ``declared_total`` (the ledger closing balance) is MANDATORY: an aging whose rows are not tied to a
    declared total is refused with ``DECLARED_TOTAL_REQUIRED`` (never an unreconciled AVAILABLE) and it
    must equal the row sum exactly. Rows, ``as_of`` and the result are bound to the qualified strategy
    (company, currency, ``period_from <= as_of < period_until``).
    """
    try:
        with localcontext(_EXACT):
            return _aging(strategy, items, as_of, declared_total)
    except Exception:  # noqa: BLE001
        return _no_aging(Reason.ITEMS_INVALID, as_of)


def _aging(strategy: object, items: object, as_of: object, declared_total: object) -> AgingResult:
    if type(strategy) is not StrategyResult or strategy.state is not StrategyState.QUALIFIED:
        return _no_aging(Reason.STRATEGY_NOT_QUALIFIED, as_of)
    if not _bound_ok(strategy) or type(strategy.digest) is not str:  # hand-built result, bound inputs lacking
        return _no_aging(Reason.STRATEGY_NOT_QUALIFIED, as_of)
    if not _is_date(as_of):
        return _no_aging(Reason.DATE_INVALID)
    if not strategy.period_from <= as_of < strategy.period_until:
        return _no_aging(Reason.AS_OF_OUT_OF_PERIOD, as_of)
    if declared_total is None:
        return _no_aging(Reason.DECLARED_TOTAL_REQUIRED, as_of)
    if type(items) is not tuple:
        return _no_aging(Reason.ITEMS_INVALID, as_of)
    if not items:
        return _no_aging(Reason.ITEMS_EMPTY, as_of)
    if len(items) > MAX_ITEMS:
        return _no_aging(Reason.TOO_MANY_ITEMS, as_of)
    if not _amount_ok(declared_total):
        return _no_aging(Reason.AMOUNT_INVALID, as_of)

    # first pass: structural checks in a fixed order; the whole aging stops at the first defect
    seen: set[tuple[str, date]] = set()
    for item in items:
        if type(item) is not OpenItem:
            return _no_aging(Reason.ITEMS_INVALID, as_of)
        if (_ident(item.company) != strategy.company or _ident(item.currency) != strategy.currency
                or _ident(item.tenant_id) != strategy.tenant_id
                or _ident(item.source_id) != strategy.source_id):
            return _no_aging(Reason.ITEM_SCOPE_MISMATCH, as_of)
        ref = _doc_key(item.doc_ref) if type(item.doc_ref) is str else ""
        if not ref:
            return _no_aging(Reason.ITEM_REF_INVALID, as_of)
        if _empty_ref(item.doc_ref):  # the 1C empty reference identifies no document
            return _no_aging(Reason.DOC_REF_EMPTY_1C, as_of)
        if item.document_date is None or item.due_date is None:
            return _no_aging(Reason.DATE_MISSING, as_of)
        if not _is_date(item.document_date) or not _is_date(item.due_date):
            return _no_aging(Reason.DATE_INVALID, as_of)
        if item.due_date < item.document_date or item.document_date > as_of:
            return _no_aging(Reason.DATE_ORDER_INVALID, as_of)
        if not _amount_ok(item.amount):
            return _no_aging(Reason.AMOUNT_INVALID, as_of)
        if item.amount < 0:
            return _no_aging(Reason.NEGATIVE_AMOUNT, as_of)
        # several instalments of one document are legal; the same document due the same day is not
        if (ref, item.due_date) in seen:
            return _no_aging(Reason.DUPLICATE_ITEM, as_of)
        seen.add((ref, item.due_date))

    totals = {b: Decimal(0) for b in AgingBucket}
    for item in items:
        totals[_bucket((as_of - item.due_date).days)] += item.amount  # type: ignore[operator]
    open_total = sum((item.amount for item in items), Decimal(0))
    if declared_total != open_total:
        return _no_aging(Reason.TOTAL_MISMATCH, as_of)

    buckets = tuple((b, totals[b]) for b in AgingBucket)
    digest = _sha("ap-aging-v2", AgingState.AVAILABLE.value, Reason.AGING_COMPUTED.value,
                  as_of.isoformat(), strategy.digest, strategy.tenant_id, strategy.source_id,  # type: ignore[union-attr]
                  _dec_text(open_total),
                  *(f"{b.value}={_dec_text(v)}" for b, v in buckets),
                  *sorted(stable_key(_doc_key(i.doc_ref), i.document_date.isoformat(),
                                     i.due_date.isoformat(), _dec_text(i.amount)) for i in items))
    return AgingResult(AgingState.AVAILABLE, Reason.AGING_COMPUTED, as_of, open_total, buckets, digest,
                       tenant_id=strategy.tenant_id, source_id=strategy.source_id)
