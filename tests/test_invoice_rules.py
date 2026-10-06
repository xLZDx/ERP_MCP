import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from business_ai_gateway.external_evidence import (
    EvidenceClass,
    EvidenceParserProfile,
    parse_approved_evidence,
)
from business_ai_gateway.invoice_evidence import PARSER_VERSION
from business_ai_gateway.invoice_rules import (
    InvoiceArchiveProof,
    InvoiceRuleProfile,
    InvoiceSourceObservation,
    evaluate_invoice,
)
from tests.test_external_evidence import scope
from tests.test_invoice_evidence import document

D = Decimal


def fixture(data=None, **profile_changes):
    data = document() if data is None else data
    expected_scope = replace(scope(), company_id=str(uuid4()), period_end=date(2026, 3, 1))
    parser = EvidenceParserProfile('fixture-parser', 'v1', EvidenceClass.INVOICE, expected_scope, PARSER_VERSION)
    payload = json.dumps(data).encode()
    evidence = parse_approved_evidence(payload, profile=parser, expected_scope=expected_scope,
        validated_profiles=frozenset({parser.fingerprint()}), private_blob_ref='private:invoice-fixture',
        retention_policy_id='fixture-policy', approved_retention_policies=frozenset({'fixture-policy'}),
        expected_document_sha256=hashlib.sha256(payload).hexdigest())
    profile = InvoiceRuleProfile(expected_scope, 'd' * 64, 'fixture-v1', evidence.header.buyer_identity,
        (('private-item', 'native-item'),), 'fixture-native-report', date(2026, 1, 1), date(2026, 3, 1), None)
    profile = replace(profile, **profile_changes)
    source = InvoiceSourceObservation(expected_scope, profile.fingerprint(), 'd' * 64, 'c' * 64, 'L1', True,
        evidence.header.invoice_number, True, False, evidence.header,
        tuple(replace(line, item_ref='native-item') for line in evidence.lines),
        date(2026, 1, 1), date(2026, 2, 1), None, None)
    archive = InvoiceArchiveProof(expected_scope, evidence.header.invoice_number,
                                  evidence.header.supplier_identity, 'e' * 64, True)
    return profile, evidence, source, archive


def run(profile, evidence, native_source, archive, **overrides):
    args = {'validated_rule_profiles': frozenset({profile.fingerprint()}), 'invoice': evidence,
        'validated_parser_profiles': frozenset({evidence.profile_fingerprint}), 'source': native_source, 'archive': archive,
        'validated_archive_proofs': frozenset({archive.fingerprint()}) if archive else frozenset()}
    return evaluate_invoice(profile, **(args | overrides))


@pytest.mark.parametrize('case', [f'REAL-INV-{index:03}' for index in range(1, 12)])
def test_all_eleven_frozen_logical_cases_with_synthetic_normalized_fixtures_not_real_corpus(case):
    data = document()
    if case in {'REAL-INV-002', 'REAL-INV-011'}:
        data['lines'].append(dict(data['lines'][0], line_ref='line-2',
                                 quality_ref='quality-B' if case == 'REAL-INV-002' else 'quality-A'))
        data['header'].update(net_amount='20.00', vat_amount='4.00', total_amount='24.00')
    if case == 'REAL-INV-006':
        data['header'].update(service_start='2026-01-01', service_end='2026-03-01')
    changes = {'production_overhead_rule': 'source-overhead-01'} if case == 'REAL-INV-007' else {}
    if case == 'REAL-INV-011':
        changes = {'line_vat_tolerance': D('0.01'), 'allow_line_rounding_when_totals_exact': True}
    profile, evidence, source, archive = fixture(data, **changes)
    if case == 'REAL-INV-001':
        source = replace(source, receipt_exists=False, payment_exists=True, header=None, lines=())
    elif case == 'REAL-INV-002':
        source = replace(source, lines=(replace(source.lines[0], quantity=D(2), net_amount=D(20),
            vat_amount=D(4), total_amount=D(24)),))
    elif case == 'REAL-INV-003':
        source = replace(source, header=replace(source.header, supplier_identity='different-native-supplier'))
    elif case == 'REAL-INV-004':
        source = replace(source, lines=(replace(source.lines[0], item_ref='wrong-native-item'),))
    elif case == 'REAL-INV-005':
        source = replace(source, booking_period_start=date(2026, 2, 1), booking_period_end=date(2026, 3, 1))
    elif case == 'REAL-INV-006':
        source = replace(source, service_allocation_confirmed=False)
    elif case == 'REAL-INV-007':
        source = replace(source, production_overhead_resolved=False)
    elif case == 'REAL-INV-008':
        archive = None
    elif case == 'REAL-INV-010':
        source = replace(source, lines=(replace(source.lines[0], quantity=D(2)),))
    elif case == 'REAL-INV-011':
        source = replace(source, lines=(replace(source.lines[0], vat_amount=D('1.99'), total_amount=D('11.99')),
                                      replace(source.lines[1], vat_amount=D('2.01'), total_amount=D('12.01'))))
    result = run(profile, evidence, source, archive)
    expected = 'PASS' if case in {'REAL-INV-009', 'REAL-INV-011'} else 'EVIDENCE_REQUIRED' if case == 'REAL-INV-008' else 'FINDING'
    assert result['status'] == expected
    if case not in {'REAL-INV-008', 'REAL-INV-009', 'REAL-INV-011'}:
        number = int(case.rsplit('-', 1)[1])
        assert any(item['rule_id'] == f'DAD-INV-{number:02}' for item in result['findings'])
    assert result['evidence_level'] == 'L1' and result['native_approval_inferred'] is False
    assert result['legal_conclusion_inferred'] is False and result['human_review_required'] is True
    for private in ('private-supplier-tax-id', 'private-buyer-tax-id', 'private-number-01',
                    evidence.scope.company_id, 'different-native-supplier', 'wrong-native-item'):
        assert private not in str(result)


@pytest.mark.parametrize('mutation', ['rule', 'metadata', 'scope', 'incomplete', 'level', 'boolean_flag',
    'same_plane', 'parser', 'wrong_number', 'buyer', 'detached_facts', 'missing_source', 'missing_invoice'])
def test_unconfirmed_incomplete_cross_scope_detached_or_unindependent_facts_never_pass(mutation):
    profile, evidence, source, archive = fixture()
    overrides = {}
    if mutation == 'rule':
        overrides['validated_rule_profiles'] = frozenset()
    elif mutation == 'metadata':
        source = replace(source, metadata_sha256='f' * 64)
    elif mutation == 'scope':
        source = replace(source, scope=replace(source.scope, company_id=str(uuid4())))
    elif mutation == 'incomplete':
        source = replace(source, complete=False)
    elif mutation == 'level':
        source = replace(source, evidence_level='private-provider-error')
    elif mutation == 'boolean_flag':
        source = replace(source, service_allocation_confirmed=1)
    elif mutation == 'same_plane':
        source = replace(source, artifact_sha256=evidence.document_sha256)
    elif mutation == 'parser':
        overrides['validated_parser_profiles'] = frozenset()
    elif mutation == 'wrong_number':
        source = replace(source, matched_invoice_number='another-invoice')
    elif mutation == 'buyer':
        source = replace(source, header=replace(source.header, buyer_identity='another-buyer'))
    elif mutation == 'detached_facts':
        evidence = replace(evidence, header=replace(evidence.header, vat_amount=D(999)))
    elif mutation == 'missing_source':
        overrides['source'] = None
    else:
        overrides['invoice'] = None
    result = run(profile, evidence, source, archive, **overrides)
    assert result['status'] != 'PASS' and 'private-provider-error' not in str(result)


@pytest.mark.parametrize('mutation', ['company', 'invoice', 'supplier', 'carrier_hash', 'unconfirmed', 'not_verified'])
def test_primary_archive_cannot_be_borrowed_relabelled_or_self_asserted(mutation):
    profile, evidence, source, archive = fixture()
    overrides = {}
    if mutation == 'company':
        archive = replace(archive, scope=replace(archive.scope, company_id=str(uuid4())))
    elif mutation == 'invoice':
        archive = replace(archive, invoice_number='different-invoice')
    elif mutation == 'supplier':
        archive = replace(archive, supplier_identity='different-supplier')
    elif mutation == 'carrier_hash':
        archive = replace(archive, original_document_sha256=evidence.document_sha256)
    elif mutation == 'unconfirmed':
        overrides['validated_archive_proofs'] = frozenset()
    else:
        archive = replace(archive, private_blob_verified=False)
        # Invalid proofs are not valid server approvals.
        overrides['validated_archive_proofs'] = frozenset()
        result = evaluate_invoice(profile, validated_rule_profiles=frozenset({profile.fingerprint()}),
            invoice=evidence, validated_parser_profiles=frozenset({evidence.profile_fingerprint}), source=source,
            archive=archive, validated_archive_proofs=frozenset())
        assert result['status'] == 'EVIDENCE_REQUIRED'
        return
    assert run(profile, evidence, source, archive, **overrides)['status'] == 'EVIDENCE_REQUIRED'


def test_rounding_cannot_waive_a_changed_invoice_header_total():
    data = document()
    data['lines'].append(dict(data['lines'][0], line_ref='line-2'))
    data['header'].update(net_amount='20.00', vat_amount='4.00', total_amount='24.00')
    profile, evidence, source, archive = fixture(data, line_vat_tolerance=D('0.01'),
                                               allow_line_rounding_when_totals_exact=True)
    source = replace(source, header=replace(source.header, vat_amount=D('4.01'), total_amount=D('24.01')),
        lines=(source.lines[0], replace(source.lines[1], vat_amount=D('2.01'), total_amount=D('12.01'))))
    result = run(profile, evidence, source, archive)
    assert result['status'] == 'FINDING'
    assert {'DAD-INV-09', 'DAD-INV-11'}.issubset({item['rule_id'] for item in result['findings']})


def test_source_profile_applicability_and_missing_receipt_do_not_manufacture_all_checks_pass():
    profile, evidence, source, archive = fixture()
    result = run(profile, evidence, source, archive)
    checks = {item['rule_id']: item for item in result['checks']}
    assert checks['DAD-INV-07']['applicable'] is False
    assert checks['DAD-INV-06']['applicable'] is False
    source = replace(source, receipt_exists=False, payment_exists=True, header=None, lines=())
    result = run(profile, evidence, source, archive)
    assert sum(item['status'] == 'PASS' for item in result['checks']) == 0


def test_scalar_profile_cannot_be_attached_to_structured_invoice_facts():
    profile, evidence, source, archive = fixture()
    scalar = replace(evidence.parser_profile, parser_version='external-normalized-csv-v1')
    evidence = replace(evidence, parser_profile=scalar, profile_fingerprint=scalar.fingerprint())
    result = run(profile, evidence, source, archive)
    assert result['status'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('changes', [{'header_tolerance': D(2)}, {'quantity_tolerance': D('NaN')},
    {'item_mapping': (('private-item', 'native-item'), ('private-item', 'another-item'))},
    {'item_mapping': (('private-item', 'native-item'), ('another-item', 'native-item'))},
    {'amount_encoding': 'guess-inclusive-vat'}, {'native_report_mapping': 'https://model-fetch-url'}])
def test_invalid_universal_or_guessing_rule_configuration_is_not_available(changes):
    profile, _evidence, _source, _archive = fixture()
    with pytest.raises(ValueError, match='^INVOICE_RULE_PROFILE_INVALID$'):
        replace(profile, **changes).fingerprint()
