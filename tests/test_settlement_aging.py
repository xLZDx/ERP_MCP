from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext

import pytest

from business_ai_gateway.aging import aggregate_open_items
from business_ai_gateway.settlement_aging import (
    AgingProfile,
    SettlementAllocation,
    SettlementDocument,
    SettlementObservation,
    SettlementPayment,
    evaluate_aging,
)
from tests.test_external_evidence import scope

D = Decimal


def fixture(kind='AR'):
    source_scope = replace(scope(), period_start=date(2026, 9, 1), period_end=date(2026, 10, 7))
    profile = AgingProfile(source_scope, 'd' * 64, 'fixture-v1', kind, date(2026, 10, 6),
        date(2026, 1, 1), date(2027, 1, 1), 'source-confirmed-due', 'source-explicit-allocation', 'native-aging-report')
    document = SettlementDocument('private-doc', 'private-party', 'private-contract', date(2026, 9, 1),
                                  date(2026, 9, 6), D(100))
    payment = SettlementPayment('private-payment', 'private-party', 'private-contract', date(2026, 9, 5), D(40))
    allocation = SettlementAllocation('allocation-1', payment.payment_ref, document.document_ref, date(2026, 9, 5), D(40))
    actual = SettlementObservation(source_scope, profile.fingerprint(), profile.metadata_sha256, 'c' * 64,
        'L1', True, True, (document,), (payment,), (allocation,))
    return profile, actual


def run(profile, actual, **overrides):
    return evaluate_aging(profile, actual, validated_profiles=overrides.get('validated_profiles',
                                                                       frozenset({profile.fingerprint()})))


@pytest.mark.parametrize('kind', ['AR', 'AP'])
def test_partial_settlement_reuses_existing_exact_bucket_contract_without_native_promotion(kind):
    profile, actual = fixture(kind)
    result = run(profile, actual)
    assert result['status'] == 'PASS' and result['rows'][0]['buckets']['days_1_30'] == '60'
    assert result['rows'][0]['unapplied_credit'] == '0'
    assert result['evidence_level'] == 'L1' and result['native_approval_inferred'] is False


def test_unallocated_advance_credit_does_not_net_against_other_document_or_contract():
    profile, actual = fixture()
    advance = replace(actual.payments[0], payment_ref='advance', contract_ref='another-contract', amount=D(10))
    result = run(profile, replace(actual, payments=(*actual.payments, advance)))
    assert result['rows'][0]['buckets']['days_1_30'] == '60'
    assert result['rows'][0]['unapplied_credit'] == '10'


def test_document_overpayment_is_visible_credit_anomaly_not_silently_clamped():
    profile, actual = fixture()
    payment = replace(actual.payments[0], amount=D(110))
    allocation = replace(actual.allocations[0], amount=D(110))
    result = run(profile, replace(actual, payments=(payment,), allocations=(allocation,)))
    assert result['status'] == 'FINDING' and result['rows'][0]['unapplied_credit'] == '10'
    assert result['anomalies'][0]['reason'] == 'DOCUMENT_OVERSETTLED'
    assert 'private-doc' not in str(result['anomalies'])


def test_multiple_explicit_allocation_events_same_payment_document_are_preserved():
    profile, actual = fixture()
    first = replace(actual.allocations[0], amount=D(10))
    second = replace(first, allocation_ref='allocation-2', allocation_date=date(2026, 9, 6), amount=D(30))
    result = run(profile, replace(actual, allocations=(first, second)))
    assert result['status'] == 'PASS' and result['rows'][0]['buckets']['days_1_30'] == '60'


@pytest.mark.parametrize('mutation', ['approval', 'metadata', 'scope', 'incomplete', 'opening', 'level',
    'duplicate_doc', 'future_payment', 'cross_party', 'cross_contract', 'unknown_document',
    'before_document', 'payment_overallocated', 'duplicate_allocation', 'nan', 'negative_magnitude'])
def test_unconfirmed_incomplete_or_ambiguous_relationships_never_guess_settlement_or_pass(mutation):
    profile, actual = fixture()
    overrides = {}
    if mutation == 'approval':
        overrides['validated_profiles'] = frozenset()
    elif mutation == 'metadata':
        actual = replace(actual, metadata_sha256='e' * 64)
    elif mutation == 'scope':
        actual = replace(actual, scope=replace(actual.scope, company_id='other-company'))
    elif mutation == 'incomplete':
        actual = replace(actual, complete=False)
    elif mutation == 'opening':
        actual = replace(actual, opening_items_known=False)
    elif mutation == 'level':
        actual = replace(actual, evidence_level='private-provider-value')
    elif mutation == 'duplicate_doc':
        actual = replace(actual, documents=(*actual.documents, actual.documents[0]))
    elif mutation == 'future_payment':
        actual = replace(actual, payments=(replace(actual.payments[0], payment_date=date(2026, 10, 7)),))
    elif mutation == 'cross_party':
        actual = replace(actual, payments=(replace(actual.payments[0], counterparty_ref='other-party'),))
    elif mutation == 'cross_contract':
        actual = replace(actual, payments=(replace(actual.payments[0], contract_ref='other-contract'),))
    elif mutation == 'unknown_document':
        actual = replace(actual, allocations=(replace(actual.allocations[0], document_ref='missing-doc'),))
    elif mutation == 'before_document':
        actual = replace(actual, allocations=(replace(actual.allocations[0], allocation_date=date(2026, 8, 31)),))
    elif mutation == 'payment_overallocated':
        actual = replace(actual, allocations=(replace(actual.allocations[0], amount=D(41)),))
    elif mutation == 'duplicate_allocation':
        actual = replace(actual, allocations=(*actual.allocations, actual.allocations[0]))
    elif mutation == 'nan':
        actual = replace(actual, documents=(replace(actual.documents[0], amount=D('NaN')),))
    else:
        actual = replace(actual, documents=(replace(actual.documents[0], amount=D(-100)),))
    result = run(profile, actual, **overrides)
    assert result['status'] != 'PASS' and result['rows'] == []
    assert 'private-provider-value' not in str(result)


def test_existing_bucket_contract_does_not_round_large_micro_unit_amounts_under_ambient_precision():
    rows = [{'counterparty_id': 'fixture', 'currency': 'MDL', 'due_date': '2026-01-01',
             'open_amount': '999999999999999999999999999.000001'},
            {'counterparty_id': 'fixture', 'currency': 'MDL', 'due_date': '2026-01-01', 'open_amount': '0.000001'}]
    with localcontext() as context:
        context.prec = 5
        result = aggregate_open_items(rows, as_of=date(2026, 10, 6))
    assert result[0]['buckets']['days_91_plus'] == '999999999999999999999999999.000002'


@pytest.mark.parametrize('mutation', ['float', 'unknown_field', 'huge_rows', 'bad_currency', 'control_party', 'scale'])
def test_existing_bucket_contract_now_has_bounded_exact_canonical_input(mutation):
    rows = [{'counterparty_id': 'fixture', 'currency': 'MDL', 'due_date': '2026-01-01', 'open_amount': '1'}]
    if mutation == 'float':
        rows[0]['open_amount'] = 1.1
    elif mutation == 'unknown_field':
        rows[0]['query'] = 'private-native-query'
    elif mutation == 'huge_rows':
        rows *= 2001
    elif mutation == 'bad_currency':
        rows[0]['currency'] = 'private-currency'
    elif mutation == 'control_party':
        rows[0]['counterparty_id'] = 'private\nparty'
    else:
        rows[0]['open_amount'] = '0.0000001'
    with pytest.raises(ValueError):
        aggregate_open_items(rows, as_of=date(2026, 10, 6))
