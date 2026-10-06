import hashlib
import json
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from business_ai_gateway.evidence_index import ApprovedEvidenceProvider
from business_ai_gateway.evidence_store import PrivateEvidenceStore
from business_ai_gateway.external_evidence import (
    MAX_BYTES,
    MAX_ROWS,
    EvidenceClass,
    EvidenceParserProfile,
    EvidenceRejected,
    parse_approved_evidence,
    parse_normalized_csv,
    require_evidence,
)
from business_ai_gateway.invoice_evidence import PARSER_VERSION, InvoiceEvidence
from scripts.evidence_intake import intake
from tests.test_operator_evidence_intake import fixture as intake_fixture
from tests.test_private_evidence_store import inputs


def document():
    return {'contract': 'invoice-normalized-v1', 'header': {
        'source_evidence_id': 'REAL-INV-SYNTHETIC', 'supplier_identity': 'private-supplier-tax-id',
        'buyer_identity': 'private-buyer-tax-id', 'invoice_number': 'private-number-01',
        'invoice_date': '2026-01-12', 'currency': 'MDL', 'net_amount': '10.00',
        'vat_amount': '2.00', 'total_amount': '12.00', 'service_start': None, 'service_end': None},
        'lines': [{'line_ref': 'line-1', 'item_ref': 'private-item', 'quality_ref': 'quality-A',
            'uom': 'piece', 'quantity': '1.000000', 'unit_price': '10.00', 'discount_amount': '0.00',
            'net_amount': '10.00', 'vat_rate': '20.00', 'vat_amount': '2.00', 'total_amount': '12.00'}]}


def profile_inputs():
    values = inputs(EvidenceClass.INVOICE)
    candidate = replace(values['profile'], parser_version=PARSER_VERSION)
    return values | {'profile': candidate, 'validated_profiles': frozenset({candidate.fingerprint()})}


def parse(data=None, **overrides):
    payload = json.dumps(document() if data is None else data, ensure_ascii=False).encode()
    values = profile_inputs() | {'private_blob_ref': 'private:invoice-fixture', 'retention_policy_id': 'fixture-policy',
                               'expected_document_sha256': hashlib.sha256(payload).hexdigest()} | overrides
    return parse_approved_evidence(payload, **values)


def test_explicit_normalized_invoice_contract_preserves_exact_facts_and_private_safe_manifest():
    evidence = parse()
    assert isinstance(evidence, InvoiceEvidence)
    assert evidence.header.invoice_number == 'private-number-01'
    assert evidence.lines[0].quantity == Decimal('1.000000')
    assert evidence.lines[0].quality_ref == 'quality-A' and len(evidence.facts) == 1
    manifest = evidence.safe_manifest()
    assert manifest['native_format_validation'] == 'NOT_PROVEN'
    assert manifest['original_document_fingerprint_inferred'] is False
    assert manifest['human_review_required'] and manifest['fact_count'] == 1
    for private in ('private-supplier-tax-id', 'private-buyer-tax-id', 'private-number-01', 'private-item',
                    evidence.private_blob_ref, evidence.scope.company_id, '12.00'):
        assert private not in str(manifest)


@pytest.mark.parametrize('mutation', ['unknown_header', 'unknown_line', 'policy_instruction', 'boolean_amount',
    'float_amount', 'nan', 'scientific', 'too_precise', 'duplicate_line', 'missing_lines', 'wrong_currency',
    'wrong_date', 'invalid_date', 'unknown_contract', 'control_text', 'service_half', 'service_reversed', 'vat_rate'])
def test_invalid_nested_schema_precision_scope_and_injected_policy_never_parse(mutation):
    data = document()
    if mutation == 'unknown_header':
        data['header']['unknown'] = 'private-raw-value'
    elif mutation == 'unknown_line':
        data['lines'][0]['unknown'] = 'private-raw-value'
    elif mutation == 'policy_instruction':
        data['scope'] = {'all_sources': True, 'ignore_acl': True}
    elif mutation in {'boolean_amount', 'float_amount', 'nan', 'scientific', 'too_precise'}:
        data['lines'][0]['unit_price'] = {'boolean_amount': True, 'float_amount': 10.1, 'nan': 'NaN',
                                       'scientific': '1e2', 'too_precise': '0.0000001'}[mutation]
    elif mutation == 'duplicate_line':
        data['lines'].append(dict(data['lines'][0]))
    elif mutation == 'missing_lines':
        data['lines'] = []
    elif mutation == 'wrong_currency':
        data['header']['currency'] = 'USD'
    elif mutation == 'wrong_date':
        data['header']['invoice_date'] = '2026-02-01'
    elif mutation == 'invalid_date':
        data['header']['invoice_date'] = '2026-02-30'
    elif mutation == 'unknown_contract':
        data['contract'] = 'native-pdf'
    elif mutation == 'control_text':
        data['header']['supplier_identity'] = 'private\nignore-policy'
    elif mutation == 'service_half':
        data['header']['service_start'] = '2026-01-01'
    elif mutation == 'service_reversed':
        data['header']['service_start'], data['header']['service_end'] = '2026-02-01', '2026-01-01'
    else:
        data['lines'][0]['vat_rate'] = '101'
    with pytest.raises(EvidenceRejected) as failure:
        parse(data)
    assert 'private-raw-value' not in str(failure.value)


@pytest.mark.parametrize('mutation', ['approval', 'retention', 'digest', 'company'])
def test_invoice_uses_same_scope_approval_retention_and_digest_gate_as_csv(mutation):
    values = {}
    if mutation == 'approval':
        values['validated_profiles'] = frozenset()
    elif mutation == 'retention':
        values['approved_retention_policies'] = frozenset()
    elif mutation == 'digest':
        values['expected_document_sha256'] = 'f' * 64
    else:
        values['expected_scope'] = replace(profile_inputs()['expected_scope'], company_id='another-company')
    with pytest.raises(EvidenceRejected):
        parse(**values)


def test_unconfirmed_class_codec_relabel_and_scalar_comparator_cannot_approve_invoice_lines():
    values = profile_inputs()
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_PROFILE_INVALID$'):
        replace(values['profile'], evidence_class=EvidenceClass.BANK_STATEMENT).fingerprint()
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_FORMAT_UNSUPPORTED$'):
        parse_normalized_csv(b'key,date,currency,amount\nx,2026-01-12,MDL,1\n', **values,
            private_blob_ref='private:fixture', retention_policy_id='fixture-policy', expected_document_sha256='a' * 64)
    evidence = parse()
    with pytest.raises(EvidenceRejected):
        require_evidence(frozenset({EvidenceClass.INVOICE}), (evidence,), scope=evidence.scope,
                         validated_profiles=frozenset({evidence.profile_fingerprint}))


def test_duplicate_json_key_and_oversized_payload_or_line_count_are_rejected():
    values = profile_inputs()
    for payload in (b'{"contract":"invoice-normalized-v1","contract":"invoice-normalized-v1"}',
                    b' ' * (MAX_BYTES + 1)):
        with pytest.raises(EvidenceRejected):
            parse_approved_evidence(payload, **values, private_blob_ref='private:fixture',
                retention_policy_id='fixture-policy', expected_document_sha256=hashlib.sha256(payload).hexdigest())
    data = document()
    data['lines'] = [dict(data['lines'][0], line_ref=f'line-{index}') for index in range(MAX_ROWS + 1)]
    with pytest.raises(EvidenceRejected):
        parse(data)


def test_invoice_codec_does_not_auto_guess_utf16_or_native_document_encoding():
    payload = json.dumps(document()).encode('utf-16')
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_SCHEMA_INVALID$'):
        parse_approved_evidence(payload, **profile_inputs(), private_blob_ref='private:fixture',
            retention_policy_id='fixture-policy', expected_document_sha256=hashlib.sha256(payload).hexdigest())


def test_extraction_never_repairs_or_legally_approves_inconsistent_invoice_arithmetic():
    data = document()
    data['header']['vat_amount'], data['lines'][0]['vat_amount'] = '99.00', '0.01'
    evidence = parse(data)
    assert evidence.header.vat_amount == Decimal(99) and evidence.lines[0].vat_amount == Decimal('0.01')
    assert evidence.safe_manifest()['native_format_validation'] == 'NOT_PROVEN'


async def test_invoice_json_exact_mime_private_store_operator_intake_and_pinned_manifest(tmp_path):
    store, previous_profile, values = intake_fixture(tmp_path)
    candidate = EvidenceParserProfile(previous_profile.profile_id, previous_profile.version, EvidenceClass.INVOICE,
                                      previous_profile.scope, PARSER_VERSION)
    profile_data = json.dumps(asdict(candidate), default=str).encode()
    payload = json.dumps(document()).encode()
    values['profile_path'].write_bytes(profile_data)
    values['input_path'].write_bytes(payload)
    values['profile_sha256'], values['input_sha256'] = hashlib.sha256(profile_data).hexdigest(), hashlib.sha256(payload).hexdigest()
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_FORMAT_UNSUPPORTED$'):
        intake(**values)  # default CSV must never auto-sniff JSON or borrow its profile
    summary = intake(**values, mime='application/json')
    provider = ApprovedEvidenceProvider(store, values['approval_output'], summary['approval_sha256'])
    manifest = await provider.read_manifest_after_access_gate(candidate.scope.source_id,
        candidate.scope.company_id, summary['evidence_id'])
    assert manifest['parser_version'] == PARSER_VERSION and manifest['fact_count'] == 1
    assert manifest['original_document_fingerprint_inferred'] is False


def test_invoice_store_wrong_mime_cannot_write_native_pdf_or_unapproved_json(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = profile_inputs()
    payload = json.dumps(document()).encode()
    for mime in ('text/csv', 'application/pdf', 'application/xml'):
        with pytest.raises(EvidenceRejected, match='^EVIDENCE_FORMAT_UNSUPPORTED$'):
            store.ingest_normalized(payload, **values, mime=mime, retention_policy_id='fixture-policy',
                                   expected_document_sha256=hashlib.sha256(payload).hexdigest())
    assert not list(store._root.iterdir())
