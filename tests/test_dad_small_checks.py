from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from business_ai_gateway.dad_small_checks import (
    CashDay,
    Position,
    SmallCheckProfile,
    SmallObservation,
    evaluate_small_check,
    evaluate_small_external,
)
from business_ai_gateway.external_evidence import EvidenceClass
from tests.test_dad_reconciliation_rules import fixture as external_fixture
from tests.test_external_evidence import scope

D = Decimal


def profile(rule='DAD-SMALL-01'):
    # Synthetic source-specific selectors, not a universal chart of accounts.
    dimensions = (('counterparty', 'contract', 'document') if rule == 'DAD-SMALL-03'
                  else ('cashier', 'subdivision', 'cashbox') if rule == 'DAD-SMALL-04'
                  else ('item', 'warehouse', 'quality'))
    return SmallCheckProfile(rule, 'fixture-v1', scope(), 'd' * 64,
        ('inventory-A', 'inventory-B'), dimensions,
        (('inventory-A', 'inventory-B'),) if rule == 'DAD-SMALL-03' else (),
        date(2026, 1, 1), date(2026, 2, 1), 'fixture-native-report')


def position(**changes):
    row = Position('inventory-A', ('private-party', 'private-contract', 'private-document'),
                   D(1), D(1), D(10), D(10), D(0), D(0), 0)
    return replace(row, **changes)


def observation(candidate, rows):
    return SmallObservation(candidate.scope, candidate.fingerprint(), candidate.metadata_sha256,
                            'c' * 64, 'L1', True, rows)


def run(candidate, rows=(), **changes):
    actual = replace(observation(candidate, rows), **changes)
    return evaluate_small_check(candidate, actual, validated_profiles=frozenset({candidate.fingerprint()}))


@pytest.mark.parametrize('rule', ['DAD-SMALL-01', 'DAD-SMALL-02', 'DAD-SMALL-03', 'DAD-SMALL-04'])
def test_unconfirmed_profile_never_guesses_accounts_or_availability(rule):
    candidate = profile(rule)
    result = evaluate_small_check(candidate, observation(candidate, ()), validated_profiles=frozenset())
    assert result['status'] == 'CAPABILITY_UNSUPPORTED'
    assert not result['native_approval_inferred'] and result['human_review_required']


@pytest.mark.parametrize('changes', [
    {'complete': False}, {'metadata_sha256': 'e' * 64}, {'profile_fingerprint': 'e' * 64},
    {'scope': replace(scope(), company_id='another-company')}, {'artifact_sha256': 'bad'},
    {'evidence_level': 'private-provider-text'}, {'evidence_level': ['L1']},
])
def test_incomplete_stale_cross_scope_or_invalid_level_is_never_pass(changes):
    result = run(profile(), **changes)
    assert result['status'] == 'INCONCLUSIVE' and not result['findings']
    assert 'private-provider-text' not in str(result)


@pytest.mark.parametrize('changes', [
    {'closing_quantity': D(-1), 'movement_count': 1},
    {'closing_value': D(-1), 'credit_turnover': D(11), 'movement_count': 1},
])
def test_negative_ending_quantity_or_value_finding(changes):
    result = run(profile(), (position(**changes),))
    assert result['status'] == 'FINDING'
    assert result['findings'][0]['reason'] == 'NEGATIVE_ENDING_POSITION'
    assert 'private-party' not in str(result) and 'private-document' not in str(result)


def test_positive_empty_complete_or_within_approved_tolerance_is_pass_not_native_evidence():
    candidate = replace(profile(), quantity_tolerance=D('0.000001'))
    assert run(candidate)['status'] == 'PASS'
    result = run(candidate, (position(closing_quantity=D('-0.000001'), movement_count=1),))
    assert result['status'] == 'PASS' and result['evidence_level'] == 'L1'
    assert result['native_approval_inferred'] is False


def test_no_movement_uses_gross_activity_not_zero_net_turnover():
    candidate = profile('DAD-SMALL-02')
    assert run(candidate, (position(),))['status'] == 'FINDING'
    active = position(debit_turnover=D(5), credit_turnover=D(5), movement_count=2)
    assert run(candidate, (active,))['status'] == 'PASS'
    assert run(candidate, (replace(active, movement_count=0),))['status'] == 'INCONCLUSIVE'
    zero = position(opening_quantity=D(0), closing_quantity=D(0), opening_value=D(0), closing_value=D(0))
    assert run(candidate, (zero,))['status'] == 'PASS'


def test_simultaneous_balances_match_contract_document_currency_not_party_aggregate():
    candidate = profile('DAD-SMALL-03')
    left = position()
    right = position(account='inventory-B', opening_value=D(-10), closing_value=D(-10))
    result = run(candidate, (left, right))
    assert result['status'] == 'FINDING' and len(result['findings']) == 1
    other_contract = replace(right, analytics=('private-party', 'different-contract', 'private-document'))
    other_document = replace(right, analytics=('private-party', 'private-contract', 'different-document'))
    assert run(candidate, (left, other_contract))['status'] == 'PASS'
    assert run(candidate, (left, other_document))['status'] == 'PASS'


@pytest.mark.parametrize('changes', [
    {'movement_count': True}, {'movement_count': -1}, {'closing_value': D('NaN')},
    {'closing_value': D('Infinity')}, {'debit_turnover': D(-1)}, {'closing_value': D('0.0000001')},
    {'analytics': ('private-party',)}, {'account': 'not-profile-approved'},
    {'closing_value': D(12)}, {'closing_value': D('1e28')},
])
def test_invalid_normalized_facts_cannot_become_findings_or_pass(changes):
    result = run(profile(), (position(**changes),))
    assert result['status'] == 'INCONCLUSIVE' and result['findings'] == []


def test_duplicate_rows_reject_instead_of_double_counting():
    assert run(profile(), (position(), position()))['status'] == 'INCONCLUSIVE'


def test_inventory_profile_cannot_drop_item_grain():
    with pytest.raises(ValueError, match='^DAD_SMALL_PROFILE_INVALID$'):
        replace(profile(), dimensions=('warehouse',)).fingerprint()


def test_reversed_duplicate_account_pairs_do_not_duplicate_findings():
    with pytest.raises(ValueError, match='^DAD_SMALL_PROFILE_INVALID$'):
        replace(profile('DAD-SMALL-03'), account_pairs=(('inventory-A', 'inventory-B'),
                ('inventory-B', 'inventory-A'))).fingerprint()


def cash_rows(candidate):
    day = candidate.scope.period_start
    rows = []
    while day < candidate.scope.period_end:
        rows.append(CashDay('inventory-A', ('cashier-1', 'subdivision-1', 'cashbox-1'),
                            day, D(-1), D(0), D(0), D(-1)))
        day += timedelta(days=1)
    return tuple(rows)


def test_daily_cash_reports_every_negative_date_with_exact_analytics():
    candidate = profile('DAD-SMALL-04')
    result = run(candidate, cash_rows(candidate))
    assert result['status'] == 'FINDING' and len(result['findings']) == 31
    assert result['findings'][0]['business_date'] == '2026-01-01'
    assert result['findings'][-1]['business_date'] == '2026-01-31'
    assert 'cashier-1' not in str(result)


def test_complete_positive_daily_cash_is_pass_and_position_rows_cannot_substitute_daily_series():
    candidate = profile('DAD-SMALL-04')
    rows = tuple(replace(row, opening_value=D(1), closing_value=D(1)) for row in cash_rows(candidate))
    assert run(candidate, rows)['status'] == 'PASS'
    assert run(candidate, (position(),))['status'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('mutation', ['missing', 'discontinuous', 'duplicate', 'wrong_day', 'negative_receipt', 'empty'])
def test_daily_cash_missing_coverage_or_bad_balance_never_infers_zero_activity(mutation):
    candidate = profile('DAD-SMALL-04')
    rows = cash_rows(candidate)
    if mutation == 'missing':
        rows = rows[1:]
    elif mutation == 'discontinuous':
        rows = (replace(rows[0], opening_value=D(0), closing_value=D(0)), *rows[1:])
    elif mutation == 'duplicate':
        rows = (*rows, rows[0])
    elif mutation == 'wrong_day':
        rows = (replace(rows[0], business_date=date(2025, 12, 31)), *rows[1:])
    elif mutation == 'negative_receipt':
        rows = (replace(rows[0], receipts=D(-1)), *rows[1:])
    else:
        rows = ()
    assert run(candidate, rows)['status'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('changes', [
    {'accounts': ()}, {'accounts': ('x', 'x')}, {'dimensions': ('counterparty',)},
    {'account_pairs': (('inventory-A', 'unknown'),)}, {'quantity_tolerance': D(2)},
    {'effective_until': date(2026, 1, 15)}, {'native_report_mapping': 'https://arbitrary-host'},
])
def test_invalid_or_aggregate_only_cross_balance_profile_is_rejected(changes):
    with pytest.raises(ValueError, match='^DAD_SMALL_PROFILE_INVALID$'):
        replace(profile('DAD-SMALL-03'), **changes).fingerprint()


@pytest.mark.parametrize('rule_id,kind', [('DAD-SMALL-05', EvidenceClass.Z_REPORT),
                                        ('DAD-SMALL-06', EvidenceClass.TERMINAL_REPORT)])
def test_z_and_terminal_reuse_existing_bounded_comparator_and_require_evidence(rule_id, kind):
    rule, document, actual = external_fixture(kind)
    rule = replace(rule, rule_id=rule_id)
    inputs = {'validated_rules': frozenset({rule.fingerprint()}), 'external': (document,),
              'validated_evidence_profiles': frozenset({document.profile_fingerprint}),
              'observation': actual, 'validated_semantic_scopes': frozenset({rule.scope.fingerprint()})}
    assert evaluate_small_external(rule, **inputs)['status'] == 'PASS'
    changed = replace(actual.facts[0], amount=D('13.34'))
    inputs['observation'] = replace(actual, facts=(changed,))
    result = evaluate_small_external(rule, **inputs)
    assert result['status'] == 'FINDING' and result['findings'][0]['reason'] == 'AMOUNT_MISMATCH'
    inputs['external'] = ()
    assert evaluate_small_external(rule, **inputs)['status'] == 'EVIDENCE_REQUIRED'
    with pytest.raises(ValueError, match='^DAD_SMALL_EXTERNAL_RULE_INVALID$'):
        evaluate_small_external(replace(rule, evidence_class=EvidenceClass.BANK_STATEMENT), **inputs)
