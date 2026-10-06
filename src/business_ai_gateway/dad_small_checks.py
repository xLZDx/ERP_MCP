"""Internal, profile-bound DAD small checks over normalized facts; no protocol/query engine."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext

from .dad_rules import ReconciliationRule, evaluate_reconciliation
from .external_evidence import EvidenceClass, EvidenceScope

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_RULES = {'DAD-SMALL-01', 'DAD-SMALL-02', 'DAD-SMALL-03', 'DAD-SMALL-04'}


def _identifier(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _number(value):
    return (isinstance(value, Decimal) and value.is_finite()
            and value.copy_abs() < Decimal('1e28') and -6 <= value.as_tuple().exponent <= 28)


@dataclass(frozen=True, slots=True)
class SmallCheckProfile:
    rule_id: str
    version: str
    scope: EvidenceScope
    metadata_sha256: str
    accounts: tuple[str, ...]
    dimensions: tuple[str, ...]
    account_pairs: tuple[tuple[str, str], ...]
    effective_from: date
    effective_until: date
    native_report_mapping: str
    amount_tolerance: Decimal = Decimal(0)
    quantity_tolerance: Decimal = Decimal(0)

    def fingerprint(self):
        self.scope.validate()
        if (type(self.rule_id) is not str or self.rule_id not in _RULES or not _identifier(self.version)
                or type(self.metadata_sha256) is not str or not _SHA.fullmatch(self.metadata_sha256)
                or not _identifier(self.native_report_mapping)
                or not isinstance(self.accounts, tuple) or not 1 <= len(self.accounts) <= 64
                or not all(_identifier(item) for item in self.accounts)
                or len(set(self.accounts)) != len(self.accounts)
                or not isinstance(self.dimensions, tuple) or not 1 <= len(self.dimensions) <= 8
                or not all(_identifier(item) for item in self.dimensions)
                or len(set(self.dimensions)) != len(self.dimensions)
                or (self.rule_id in {'DAD-SMALL-01', 'DAD-SMALL-02'} and 'item' not in self.dimensions)
                or (self.rule_id == 'DAD-SMALL-03' and not
                    {'counterparty', 'contract', 'document'}.issubset(self.dimensions))
                or not isinstance(self.account_pairs, tuple) or len(self.account_pairs) > 32
                or any(not isinstance(pair, tuple) or len(pair) != 2
                       or not all(_identifier(item) and item in self.accounts for item in pair)
                       or pair[0] == pair[1] for pair in self.account_pairs)
                or len(set(self.account_pairs)) != len(self.account_pairs)
                or len({frozenset(pair) for pair in self.account_pairs}) != len(self.account_pairs)
                or (self.rule_id == 'DAD-SMALL-03') != bool(self.account_pairs)
                or type(self.effective_from) is not date or type(self.effective_until) is not date
                or not self.effective_from <= self.scope.period_start < self.scope.period_end <= self.effective_until
                or (self.scope.period_end - self.scope.period_start).days > 366
                or any(not _number(value) or not Decimal(0) <= value <= Decimal(1)
                       for value in (self.amount_tolerance, self.quantity_tolerance))):
            raise ValueError('DAD_SMALL_PROFILE_INVALID')
        return hashlib.sha256(json.dumps(asdict(self), default=str, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Position:
    account: str
    analytics: tuple[str, ...]  # exact profile order; never counterparty-only aggregation
    opening_quantity: Decimal
    closing_quantity: Decimal
    opening_value: Decimal
    closing_value: Decimal  # signed debit-minus-credit balance per validated profile
    debit_turnover: Decimal
    credit_turnover: Decimal
    movement_count: int  # gross events, not net turnover


@dataclass(frozen=True, slots=True)
class CashDay:
    account: str
    analytics: tuple[str, ...]
    business_date: date
    opening_value: Decimal
    receipts: Decimal
    payments: Decimal
    closing_value: Decimal


@dataclass(frozen=True, slots=True)
class SmallObservation:
    scope: EvidenceScope
    profile_fingerprint: str
    metadata_sha256: str
    artifact_sha256: str
    evidence_level: str
    complete: bool
    rows: tuple[Position | CashDay, ...]


def _key(account, analytics):
    return hashlib.sha256(json.dumps([account, analytics], separators=(',', ':')).encode()).hexdigest()


def evaluate_small_check(profile: SmallCheckProfile, observation: SmallObservation | None, *,
                         validated_profiles: frozenset[str]) -> dict:
    """Approval sets are server-side configuration, never MCP/model input. No native promotion."""
    fingerprint = profile.fingerprint()
    level = observation.evidence_level if isinstance(observation, SmallObservation) else None
    safe_level = level if type(level) is str and level in {'L1', 'L2-A', 'L2-B', 'L3'} else None
    result = {'rule_id': profile.rule_id, 'rule_version': profile.version,
              'rule_fingerprint': fingerprint, 'scope_fingerprint': profile.scope.fingerprint(),
              'status': 'CAPABILITY_UNSUPPORTED', 'reason': 'DAD_PROFILE_UNCONFIRMED',
              'findings': [], 'human_review_required': True, 'native_approval_inferred': False,
              'evidence_level': safe_level}
    if fingerprint not in validated_profiles:
        return result
    if not isinstance(observation, SmallObservation):
        result.update(status='INCONCLUSIVE', reason='SEMANTIC_OBSERVATION_REQUIRED')
        return result
    if (observation.scope != profile.scope or observation.profile_fingerprint != fingerprint
            or observation.metadata_sha256 != profile.metadata_sha256
            or observation.complete is not True or safe_level is None
            or type(observation.artifact_sha256) is not str or not _SHA.fullmatch(observation.artifact_sha256)
            or not isinstance(observation.rows, tuple) or len(observation.rows) > 2000):
        result.update(status='INCONCLUSIVE', reason='SEMANTIC_OBSERVATION_INCOMPLETE_OR_SCOPE_MISMATCH')
        return result
    result.update(status='INCONCLUSIVE', reason='NORMALIZED_FACTS_INVALID')
    keys = set()
    positions = {}
    days = {}
    with localcontext() as context:
        context.prec = 80
        for row in observation.rows:
            if (not isinstance(row, CashDay if profile.rule_id == 'DAD-SMALL-04' else Position)
                    or row.account not in profile.accounts or not isinstance(row.analytics, tuple)
                    or len(row.analytics) != len(profile.dimensions)
                    or not all(_identifier(item) for item in row.analytics)):
                return result
            key = (row.account, row.analytics)
            if isinstance(row, CashDay):
                if (type(row.business_date) is not date
                        or not profile.scope.period_start <= row.business_date < profile.scope.period_end
                        or not all(_number(value) for value in
                                   (row.opening_value, row.receipts, row.payments, row.closing_value))
                        or row.receipts < 0 or row.payments < 0
                        or abs(row.opening_value + row.receipts - row.payments - row.closing_value)
                        > profile.amount_tolerance):
                    return result
                unique = (*key, row.business_date)
                days.setdefault(key, {})[row.business_date] = row
            else:
                if (not all(_number(value) for value in (row.opening_quantity, row.closing_quantity,
                        row.opening_value, row.closing_value, row.debit_turnover, row.credit_turnover))
                        or row.debit_turnover < 0 or row.credit_turnover < 0
                        or type(row.movement_count) is not int or not 0 <= row.movement_count <= 10_000_000
                        or (row.movement_count == 0 and (row.debit_turnover or row.credit_turnover
                            or row.opening_quantity != row.closing_quantity))
                        or abs(row.opening_value + row.debit_turnover - row.credit_turnover - row.closing_value)
                        > profile.amount_tolerance):
                    return result
                unique = key
                positions[key] = row
            if unique in keys:
                return result
            keys.add(unique)
        findings = []
        for key, row in positions.items():
            reason = None
            if profile.rule_id == 'DAD-SMALL-01' and (
                    row.closing_quantity < -profile.quantity_tolerance
                    or row.closing_value < -profile.amount_tolerance):
                reason = 'NEGATIVE_ENDING_POSITION'
            if profile.rule_id == 'DAD-SMALL-02' and row.movement_count == 0 and (
                    abs(row.closing_quantity) > profile.quantity_tolerance
                    or abs(row.closing_value) > profile.amount_tolerance):
                reason = 'POSITION_WITHOUT_MOVEMENT'
            if reason:
                findings.append({'key_sha256': _key(*key), 'reason': reason})
        if profile.rule_id == 'DAD-SMALL-03':
            for left_account, right_account in profile.account_pairs:
                for (account, analytics), left in positions.items():
                    right = positions.get((right_account, analytics)) if account == left_account else None
                    if (right is not None and abs(left.closing_value) > profile.amount_tolerance
                            and abs(right.closing_value) > profile.amount_tolerance):
                        findings.append({'key_sha256': _key(f'{left_account}.{right_account}', analytics),
                                         'reason': 'SIMULTANEOUS_ANALYTIC_BALANCES'})
        if profile.rule_id == 'DAD-SMALL-04':
            if not days:
                result.update(reason='DAILY_CASH_COVERAGE_REQUIRED')
                return result
            for key, series in days.items():
                previous = None
                current = profile.scope.period_start
                while current < profile.scope.period_end:
                    row = series.get(current)
                    if row is None or (previous is not None and
                            abs(previous - row.opening_value) > profile.amount_tolerance):
                        result.update(reason='DAILY_CASH_COVERAGE_OR_CONTINUITY_INVALID')
                        return result
                    if row.closing_value < -profile.amount_tolerance:
                        findings.append({'key_sha256': _key(*key), 'business_date': current.isoformat(),
                                         'reason': 'NEGATIVE_DAILY_CASH'})
                    previous = row.closing_value
                    current += timedelta(days=1)
    result.update(status='FINDING' if findings else 'PASS', reason='VALIDATED_NORMALIZED_SMALL_CHECK',
                  findings=sorted(findings, key=lambda item: json.dumps(item, sort_keys=True)),
                  semantic_artifact_sha256=observation.artifact_sha256)
    return result


def evaluate_small_external(rule: ReconciliationRule, **evidence_inputs) -> dict:
    """DAD-SMALL-05/06 reuse the existing bounded, provenance-bound comparison engine."""
    required = {'DAD-SMALL-05': EvidenceClass.Z_REPORT, 'DAD-SMALL-06': EvidenceClass.TERMINAL_REPORT}
    if rule.rule_id not in required or rule.evidence_class != required[rule.rule_id]:
        raise ValueError('DAD_SMALL_EXTERNAL_RULE_INVALID')
    return evaluate_reconciliation(rule, **evidence_inputs)
