"""Internal exact-profile financial statement projection; no source queries/universal chart."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum

from .external_evidence import EvidenceScope

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')


class StatementKind(StrEnum):
    BALANCE_SHEET = 'balance_sheet'
    PROFIT_LOSS = 'profit_loss'
    CASH_FLOW = 'cash_flow'


@dataclass(frozen=True, slots=True)
class StatementComponent:
    selector: str  # exact profile-owned account/activity ref, NEVER inferred from a universal chart
    metric: str
    sign: int


@dataclass(frozen=True, slots=True)
class StatementRow:
    row_id: str
    components: tuple[StatementComponent, ...]


@dataclass(frozen=True, slots=True)
class StatementProfile:
    scope: EvidenceScope
    metadata_sha256: str
    version: str
    kind: StatementKind
    rows: tuple[StatementRow, ...]
    native_report_mapping: str
    effective_from: date
    effective_until: date
    comparative_scope: EvidenceScope | None
    unmapped_nonzero_policy: str = 'INCONCLUSIVE'  # never silently ignore unclassified money
    absolute_tolerance: Decimal = Decimal(0)

    def fingerprint(self):
        self.scope.validate()
        metrics = ({'closing'} if self.kind == StatementKind.BALANCE_SHEET else
                   {'debit_turnover', 'credit_turnover'} if self.kind == StatementKind.PROFIT_LOSS else
                   {'cash_in', 'cash_out'})
        if (not isinstance(self.kind, StatementKind) or not _identifier(self.version)
                or not _sha(self.metadata_sha256) or not _identifier(self.native_report_mapping)
                or not isinstance(self.rows, tuple) or not 1 <= len(self.rows) <= 200
                or any(not isinstance(row, StatementRow) or not _identifier(row.row_id)
                       or not isinstance(row.components, tuple) or not 1 <= len(row.components) <= 64
                       or any(not isinstance(component, StatementComponent) or not _identifier(component.selector)
                              or type(component.metric) is not str or component.metric not in metrics or type(component.sign) is not int
                              or component.sign not in {-1, 1} for component in row.components)
                       or len({(part.selector, part.metric) for part in row.components}) != len(row.components)
                       for row in self.rows)
                or len({row.row_id for row in self.rows}) != len(self.rows)
                or sum(len(row.components) for row in self.rows) > 2000
                or type(self.effective_from) is not date or type(self.effective_until) is not date
                or not self.effective_from <= self.scope.period_start < self.scope.period_end <= self.effective_until
                or (self.scope.period_end - self.scope.period_start).days > 366
                or self.unmapped_nonzero_policy != 'INCONCLUSIVE'
                or not _number(self.absolute_tolerance) or not Decimal(0) <= self.absolute_tolerance <= Decimal(1)):
            raise ValueError('STATEMENT_PROFILE_INVALID')
        if self.comparative_scope is not None:
            self.comparative_scope.validate()
            current, previous = asdict(self.scope), asdict(self.comparative_scope)
            for key in ('period_start', 'period_end'):
                current.pop(key)
                previous.pop(key)
            if (current != previous or self.comparative_scope.period_end > self.scope.period_start
                    or (self.comparative_scope.period_end - self.comparative_scope.period_start).days > 366
                    or self.comparative_scope.period_start < self.effective_from):
                raise ValueError('STATEMENT_PROFILE_INVALID')
        return _fingerprint(asdict(self))


def _identifier(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _number(value):
    return (isinstance(value, Decimal) and value.is_finite() and value.copy_abs() < Decimal('1e28')
            and -6 <= value.as_tuple().exponent <= 28)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class StatementFact:
    selector: str
    metric: str
    business_date: date
    amount: Decimal
    fact_ref: str  # stable normalized analytic/event identity; duplicate amounts are not deduplicated


@dataclass(frozen=True, slots=True)
class StatementObservation:
    scope: EvidenceScope
    profile_fingerprint: str
    metadata_sha256: str
    artifact_sha256: str
    evidence_level: str
    complete: bool
    opening_known: bool
    facts: tuple[StatementFact, ...]


def _project(profile, observation, scope):
    if (not isinstance(observation, StatementObservation) or observation.scope != scope
            or observation.profile_fingerprint != profile.fingerprint()
            or observation.metadata_sha256 != profile.metadata_sha256
            or not _sha(observation.artifact_sha256) or observation.complete is not True
            or type(observation.opening_known) is not bool
            or (profile.kind == StatementKind.BALANCE_SHEET and observation.opening_known is not True)
            or type(observation.evidence_level) is not str
            or observation.evidence_level not in {'L1', 'L2-A', 'L2-B', 'L3'}
            or not isinstance(observation.facts, tuple) or len(observation.facts) > 2000):
        return None, 'STATEMENT_OBSERVATION_INCOMPLETE_OR_SCOPE_MISMATCH'
    selectors = {(component.selector, component.metric) for row in profile.rows for component in row.components}
    values, seen = {}, set()
    with localcontext() as context:
        context.prec = 120
        for fact in observation.facts:
            if (not isinstance(fact, StatementFact) or not _identifier(fact.selector) or not _identifier(fact.metric)
                    or not _identifier(fact.fact_ref) or type(fact.business_date) is not date
                    or not scope.period_start <= fact.business_date < scope.period_end or not _number(fact.amount)
                    or (fact.metric in {'debit_turnover', 'credit_turnover', 'cash_in', 'cash_out'} and fact.amount < 0)
                    or (fact.fact_ref, fact.metric) in seen):
                return None, 'STATEMENT_FACT_INVALID'
            seen.add((fact.fact_ref, fact.metric))
            key = (fact.selector, fact.metric)
            if key not in selectors:
                if fact.amount != 0:
                    return None, 'UNMAPPED_NONZERO_FACT'
                continue
            if profile.kind == StatementKind.BALANCE_SHEET and fact.business_date != scope.period_end - timedelta(days=1):
                return None, 'BALANCE_SHEET_ASOF_MISMATCH'
            values[key] = values.get(key, Decimal(0)) + fact.amount
        # Coverage must be explicit: absent selector/metric is not assumed zero.
        if not selectors.issubset(values):
            return None, 'STATEMENT_SELECTOR_COVERAGE_REQUIRED'
        rows = tuple((row.row_id, sum((values[(part.selector, part.metric)] * part.sign
                                      for part in row.components), Decimal(0))) for row in profile.rows)
        if not all(_number(amount) for _key, amount in rows):
            return None, 'STATEMENT_AGGREGATE_LIMIT'
    return rows, None


def project_statement(profile: StatementProfile, *, validated_profiles: frozenset[str],
                      current: StatementObservation | None, comparative: StatementObservation | None) -> dict:
    fingerprint = profile.fingerprint()
    result = {'statement_kind': profile.kind.value, 'profile_fingerprint': fingerprint,
              'scope_fingerprint': profile.scope.fingerprint(), 'status': 'CAPABILITY_UNSUPPORTED',
              'reason': 'STATEMENT_PROFILE_UNCONFIRMED', 'rows': [], 'comparative_rows': [],
              'human_review_required': True, 'native_approval_inferred': False, 'evidence_level': None}
    if fingerprint not in validated_profiles:
        return result
    rows, error = _project(profile, current, profile.scope)
    if error:
        result.update(status='INCONCLUSIVE', reason=error)
        return result
    previous = ()
    if profile.comparative_scope is not None:
        previous, error = _project(profile, comparative, profile.comparative_scope)
        if error or (comparative.evidence_level != current.evidence_level
                     or comparative.artifact_sha256 == current.artifact_sha256):
            result.update(status='INCONCLUSIVE', reason=error or 'COMPARATIVE_PLANE_OR_LEVEL_INVALID')
            return result
    elif comparative is not None:
        result.update(status='INCONCLUSIVE', reason='UNDECLARED_COMPARATIVE_PERIOD')
        return result
    result.update(status='PASS', reason='VALIDATED_PROFILE_PROJECTION_ONLY', evidence_level=current.evidence_level,
        rows=[{'row_id': key, 'amount': str(value)} for key, value in rows],
        comparative_rows=[{'row_id': key, 'amount': str(value)} for key, value in previous],
        result_fingerprint=_fingerprint({'profile': fingerprint, 'rows': rows, 'comparative': previous,
            'artifact': current.artifact_sha256, 'comparative_artifact': comparative.artifact_sha256 if comparative else None,
            'evidence_level': current.evidence_level}),
        semantic_artifact_sha256=current.artifact_sha256,
        comparative_artifact_sha256=comparative.artifact_sha256 if comparative is not None else None)
    return result  # private authorized data, not a public safe evidence summary


def reconcile_statement(profile: StatementProfile, projected: dict, *, native_scope: EvidenceScope,
                        native_rows: tuple[tuple[str, Decimal], ...], native_artifact_sha256: str,
                        approved_native_report_profiles: frozenset[str], native_complete: bool,
                        native_evidence_level: str, native_comparative_scope: EvidenceScope | None = None,
                        native_comparative_rows: tuple[tuple[str, Decimal], ...] | None = None,
                        native_comparative_artifact_sha256: str | None = None) -> dict:
    """Independent native report is required for acceptance; row equality alone never grants GO."""
    result = {'status': 'INCONCLUSIVE', 'reason': 'STATEMENT_NATIVE_EVIDENCE_REQUIRED', 'findings': [],
              'native_approval_inferred': False, 'human_review_required': True}
    if (projected.get('status') != 'PASS' or projected.get('profile_fingerprint') != profile.fingerprint()
            or profile.fingerprint() not in approved_native_report_profiles
            or native_scope != profile.scope or native_complete is not True
            or not _sha(native_artifact_sha256) or native_artifact_sha256 == projected.get('semantic_artifact_sha256')
            or type(native_evidence_level) is not str or native_evidence_level not in {'L1', 'L2-A', 'L2-B', 'L3'}
            or native_evidence_level != projected.get('evidence_level') or not isinstance(native_rows, tuple)
            or len(native_rows) > 200):
        return result
    if (any(not isinstance(row, tuple) or len(row) != 2 or not _identifier(row[0]) or not _number(row[1])
            for row in native_rows) or len({row[0] for row in native_rows}) != len(native_rows)):
        return result
    try:
        rows = projected['rows']
        previous = projected['comparative_rows']
        if (type(rows) is not list or not 1 <= len(rows) <= 200 or type(previous) is not list or len(previous) > 200
                or any(type(row) is not dict or set(row) != {'row_id', 'amount'}
                       or not _identifier(row['row_id']) or type(row['amount']) is not str
                       or not re.fullmatch(r'-?[0-9]{1,28}(?:\.[0-9]{1,6})?', row['amount'])
                       for row in (*rows, *previous))):
            return result
        current_values = tuple((row['row_id'], Decimal(row['amount'])) for row in rows)
        previous_values = tuple((row['row_id'], Decimal(row['amount'])) for row in previous)
        expected_hash = _fingerprint({'profile': profile.fingerprint(), 'rows': current_values, 'comparative': previous_values,
            'artifact': projected.get('semantic_artifact_sha256'), 'comparative_artifact': projected.get('comparative_artifact_sha256'),
            'evidence_level': projected.get('evidence_level')})
        if (projected.get('result_fingerprint') != expected_hash
                or len({key for key, _amount in current_values}) != len(current_values)
                or {key for key, _amount in current_values} != {row.row_id for row in profile.rows}):
            return result
    except (ValueError, TypeError, KeyError):
        return result
    actual = dict(current_values)
    expected = dict(native_rows)
    comparisons = [(actual, expected)]
    if profile.comparative_scope is not None:
        if (native_comparative_scope != profile.comparative_scope or not _sha(native_comparative_artifact_sha256)
                or native_comparative_artifact_sha256 in {native_artifact_sha256,
                    projected.get('semantic_artifact_sha256'), projected.get('comparative_artifact_sha256')}
                or not isinstance(native_comparative_rows, tuple) or len(native_comparative_rows) > 200
                or any(not isinstance(row, tuple) or len(row) != 2 or not _identifier(row[0]) or not _number(row[1])
                       for row in native_comparative_rows)
                or len({row[0] for row in native_comparative_rows}) != len(native_comparative_rows)):
            return result
        comparisons.append((dict(previous_values), dict(native_comparative_rows)))
    elif any(value is not None for value in (native_comparative_scope, native_comparative_rows,
                                             native_comparative_artifact_sha256)):
        return result
    with localcontext() as context:
        context.prec = 120
        for period_index, (actual_period, expected_period) in enumerate(comparisons):
            for key in sorted(set(actual_period) | set(expected_period)):
                if (key not in actual_period or key not in expected_period
                        or abs(actual_period[key] - expected_period[key]) > profile.absolute_tolerance):
                    result['findings'].append({'row_sha256': hashlib.sha256(key.encode()).hexdigest(),
                        'period': 'current' if period_index == 0 else 'comparative',
                        'reason': 'STATEMENT_ROW_MISSING_OR_MISMATCH'})
    result.update(status='FINDING' if result['findings'] else 'PASS', reason='INDEPENDENT_NATIVE_ROW_COMPARISON',
                  evidence_level=native_evidence_level)
    return result
