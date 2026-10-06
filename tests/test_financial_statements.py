from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from business_ai_gateway.financial_statements import (
    StatementComponent,
    StatementFact,
    StatementKind,
    StatementObservation,
    StatementProfile,
    StatementRow,
    project_statement,
    reconcile_statement,
)
from tests.test_external_evidence import scope

D = Decimal


def fixture(kind=StatementKind.BALANCE_SHEET, comparative=False):
    current_scope = scope()
    previous_scope = replace(current_scope, period_start=date(2025, 12, 1), period_end=date(2026, 1, 1)) if comparative else None
    parts = ((StatementComponent('synthetic-account', 'closing', 1),) if kind == StatementKind.BALANCE_SHEET else
             (StatementComponent('synthetic-account', 'credit_turnover', 1),
              StatementComponent('synthetic-account', 'debit_turnover', -1)) if kind == StatementKind.PROFIT_LOSS else
             (StatementComponent('synthetic-cash-activity', 'cash_in', 1),
              StatementComponent('synthetic-cash-activity', 'cash_out', -1)))
    profile = StatementProfile(current_scope, 'd' * 64, 'fixture-v1', kind,
        (StatementRow('row-net', parts),), 'source-specific-native-report', date(2025, 12, 1), date(2026, 2, 1), previous_scope)

    def observation(scope_value, artifact):
        day = date(2026, 1, 31) if scope_value == current_scope else date(2025, 12, 31)
        facts = tuple(StatementFact(part.selector, part.metric, day, D(10) if index == 0 else D(3),
                                   'analytic-or-event-ref') for index, part in enumerate(parts))
        return StatementObservation(scope_value, profile.fingerprint(), profile.metadata_sha256, artifact,
                                    'L1', True, kind == StatementKind.BALANCE_SHEET, facts)

    current = observation(current_scope, 'c' * 64)
    previous = observation(previous_scope, 'e' * 64) if previous_scope else None
    return profile, current, previous


def project(profile, current, previous=None, **changes):
    args = {'validated_profiles': frozenset({profile.fingerprint()}), 'current': current, 'comparative': previous}
    return project_statement(profile, **(args | changes))


def reconcile(profile, projected, **changes):
    args = {'native_scope': profile.scope, 'native_rows': (('row-net', D(10)),),
            'native_artifact_sha256': 'f' * 64,
            'approved_native_report_profiles': frozenset({profile.fingerprint()}),
            'native_complete': True, 'native_evidence_level': 'L1'}
    return reconcile_statement(profile, projected, **(args | changes))


@pytest.mark.parametrize('kind', list(StatementKind))
def test_three_exact_profile_projections_without_universal_chart_or_native_promotion(kind):
    profile, current, _previous = fixture(kind)
    result = project(profile, current)
    assert result['status'] == 'PASS'
    assert result['rows'] == [{'row_id': 'row-net', 'amount': '10' if kind == StatementKind.BALANCE_SHEET else '7'}]
    assert result['native_approval_inferred'] is False and result['evidence_level'] == 'L1'
    assert result['human_review_required'] is True


@pytest.mark.parametrize('mutation', ['approval', 'scope', 'metadata', 'incomplete', 'unknown_opening',
                                    'level', 'missing_selector', 'unmapped', 'duplicate', 'asof', 'nan'])
def test_stale_unknown_incomplete_unmapped_or_reconstructed_balance_never_pass(mutation):
    profile, current, _previous = fixture()
    changes = {}
    if mutation == 'approval':
        changes['validated_profiles'] = frozenset()
    elif mutation == 'scope':
        current = replace(current, scope=replace(current.scope, company_id='other-company'))
    elif mutation == 'metadata':
        current = replace(current, metadata_sha256='f' * 64)
    elif mutation == 'incomplete':
        current = replace(current, complete=False)
    elif mutation == 'unknown_opening':
        current = replace(current, opening_known=False)
    elif mutation == 'level':
        current = replace(current, evidence_level='private-provider-value')
    elif mutation == 'missing_selector':
        current = replace(current, facts=())
    elif mutation == 'unmapped':
        current = replace(current, facts=(*current.facts, replace(current.facts[0], selector='unmapped-account', fact_ref='other-ref')))
    elif mutation == 'duplicate':
        current = replace(current, facts=(*current.facts, current.facts[0]))
    elif mutation == 'asof':
        current = replace(current, facts=(replace(current.facts[0], business_date=date(2026, 1, 30)),))
    else:
        current = replace(current, facts=(replace(current.facts[0], amount=D('NaN')),))
    result = project(profile, current, **changes)
    assert result['status'] != 'PASS' and result['rows'] == []
    assert 'private-provider-value' not in str(result)


def test_explicit_zero_selector_is_not_equivalent_to_missing_extracted_rows():
    profile, current, _previous = fixture()
    assert project(profile, replace(current, facts=()))['status'] == 'INCONCLUSIVE'
    result = project(profile, replace(current, facts=(replace(current.facts[0], amount=D(0)),)))
    assert result['status'] == 'PASS' and result['rows'][0]['amount'] == '0'


def test_balance_facts_cannot_be_used_as_cash_flow_or_pnl_turnovers():
    for kind in (StatementKind.CASH_FLOW, StatementKind.PROFIT_LOSS):
        profile, _current, _previous = fixture(kind)
        row = replace(profile.rows[0], components=(StatementComponent('synthetic-account', 'closing', 1),))
        with pytest.raises(ValueError, match='^STATEMENT_PROFILE_INVALID$'):
            replace(profile, rows=(row,)).fingerprint()


def test_distinct_gross_cash_movements_do_not_collapse_equal_values_or_net_zero():
    profile, current, _previous = fixture(StatementKind.CASH_FLOW)
    inflow, outflow = current.facts
    current = replace(current, facts=(inflow, replace(inflow, fact_ref='other-event'), outflow))
    assert project(profile, current)['rows'][0]['amount'] == '17'


def test_current_and_comparative_require_separate_complete_scoped_snapshots_and_native_reports():
    profile, current, previous = fixture(comparative=True)
    projected = project(profile, current, previous)
    assert projected['status'] == 'PASS' and projected['comparative_rows'][0]['amount'] == '10'
    assert project(profile, current)['status'] == 'INCONCLUSIVE'
    assert project(profile, current, replace(previous, artifact_sha256=current.artifact_sha256))['status'] == 'INCONCLUSIVE'
    assert reconcile(profile, projected)['status'] == 'INCONCLUSIVE'
    result = reconcile(profile, projected, native_comparative_scope=profile.comparative_scope,
        native_comparative_rows=(('row-net', D(10)),), native_comparative_artifact_sha256='a' * 64)
    assert result['status'] == 'PASS' and result['native_approval_inferred'] is False
    result = reconcile(profile, projected, native_comparative_scope=profile.comparative_scope,
        native_comparative_rows=(('row-net', D(11)),), native_comparative_artifact_sha256='a' * 64)
    assert result['status'] == 'FINDING' and result['findings'][0]['period'] == 'comparative'


@pytest.mark.parametrize('mutation', ['mapping', 'scope', 'same_plane', 'level', 'incomplete', 'duplicate', 'tamper', 'artifact'])
def test_native_reconciliation_rejects_forged_incomplete_cross_scope_and_same_plane(mutation):
    profile, current, _previous = fixture()
    projected, changes = project(profile, current), {}
    if mutation == 'mapping':
        changes['approved_native_report_profiles'] = frozenset()
    elif mutation == 'scope':
        changes['native_scope'] = replace(profile.scope, company_id='another-company')
    elif mutation == 'same_plane':
        changes['native_artifact_sha256'] = current.artifact_sha256
    elif mutation == 'level':
        changes['native_evidence_level'] = 'L2-A'
    elif mutation == 'incomplete':
        changes['native_complete'] = False
    elif mutation == 'duplicate':
        changes['native_rows'] = (('row-net', D(10)), ('row-net', D(10)))
    elif mutation == 'artifact':
        projected['semantic_artifact_sha256'] = 'a' * 64
    else:
        projected['rows'][0]['amount'] = '999'
    assert reconcile(profile, projected, **changes)['status'] == 'INCONCLUSIVE'


def test_native_row_mismatch_is_minimized_finding_not_waived_go():
    profile, current, _previous = fixture()
    result = reconcile(profile, project(profile, current), native_rows=(('row-net', D(11)),))
    assert result['status'] == 'FINDING' and 'row-net' not in str(result)
    assert result['native_approval_inferred'] is False


def test_report_mapping_name_alone_is_not_native_profile_approval():
    profile, current, _previous = fixture()
    result = reconcile(profile, project(profile, current),
                       approved_native_report_profiles=frozenset({profile.native_report_mapping}))
    assert result['status'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('changes', [{'absolute_tolerance': D(2)}, {'unmapped_nonzero_policy': 'IGNORE'},
                                   {'native_report_mapping': 'https://model-url'}, {'rows': ()}])
def test_unsafe_missing_or_unbounded_statement_profile_is_rejected(changes):
    profile, _current, _previous = fixture()
    with pytest.raises(ValueError, match='^STATEMENT_PROFILE_INVALID$'):
        replace(profile, **changes).fingerprint()
