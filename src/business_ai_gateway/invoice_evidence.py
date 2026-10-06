"""Explicit normalized invoice JSON exchange; NOT PDF/XML extraction or legal VAT validation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .external_evidence import (
    MAX_ROWS,
    EvidenceClass,
    EvidenceParserProfile,
    EvidenceRejected,
    EvidenceScope,
    validate_evidence_input,
)

PARSER_VERSION = 'external-normalized-invoice-json-v1'
_HEADER = {'source_evidence_id', 'supplier_identity', 'buyer_identity', 'invoice_number', 'invoice_date',
           'currency', 'net_amount', 'vat_amount', 'total_amount', 'service_start', 'service_end'}
_LINE = {'line_ref', 'item_ref', 'quality_ref', 'uom', 'quantity', 'unit_price', 'discount_amount',
         'net_amount', 'vat_rate', 'vat_amount', 'total_amount'}
_AMOUNT = re.compile(r'-?[0-9]{1,28}(?:\.[0-9]{1,6})?\Z')


def _text(value):
    if (type(value) is not str or not value or len(value) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise EvidenceRejected('EVIDENCE_INVOICE_FACT_INVALID')
    return value


def _amount(value):
    if type(value) is not str or not _AMOUNT.fullmatch(value):
        raise EvidenceRejected('EVIDENCE_INVOICE_FACT_INVALID')
    amount = Decimal(value)
    if amount.copy_abs() >= Decimal('1e28'):
        raise EvidenceRejected('EVIDENCE_INVOICE_FACT_INVALID')
    return amount


def _date(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise EvidenceRejected('EVIDENCE_INVOICE_FACT_INVALID')
    return date.fromisoformat(value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceRejected('EVIDENCE_SCHEMA_INVALID')
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class InvoiceHeader:
    source_evidence_id: str
    supplier_identity: str
    buyer_identity: str
    invoice_number: str
    invoice_date: date
    currency: str
    net_amount: Decimal
    vat_amount: Decimal
    total_amount: Decimal
    service_start: date | None
    service_end: date | None  # exclusive, explicitly supplied; not guessed from document text


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    line_ref: str  # canonical correlation ref established by approved source mapping, not assumed ordinal
    item_ref: str
    quality_ref: str | None
    uom: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    vat_rate: Decimal  # declared normalized percentage, not an authoritative tax rate
    vat_amount: Decimal
    total_amount: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceEvidence:
    scope: EvidenceScope
    document_sha256: str  # normalized carrier bytes; NEVER relabel as original/native PDF digest
    profile_fingerprint: str
    parser_version: str
    private_blob_ref: str
    retention_policy_id: str
    header: InvoiceHeader
    lines: tuple[InvoiceLine, ...]
    parser_profile: EvidenceParserProfile

    @property
    def evidence_class(self):
        return EvidenceClass.INVOICE

    @property
    def facts(self):
        return self.lines  # generic provider item count only; scalar DAD comparator rejects this type

    def safe_manifest(self):
        return {'scope_sha256': self.scope.fingerprint(), 'evidence_class': EvidenceClass.INVOICE.value,
                'document_sha256': self.document_sha256, 'profile_fingerprint': self.profile_fingerprint,
                'parser_version': self.parser_version, 'fact_count': len(self.lines),
                'raw_document_retained_by_parser': False, 'native_format_validation': 'NOT_PROVEN',
                'fingerprint_plane': 'NORMALIZED_CARRIER',
                'original_document_fingerprint_inferred': False, 'human_review_required': True}


def parse_normalized_invoice(payload: bytes, **approved_inputs) -> InvoiceEvidence:
    profile = approved_inputs['profile']
    if profile.parser_version != PARSER_VERSION or profile.evidence_class != EvidenceClass.INVOICE:
        raise EvidenceRejected('EVIDENCE_FORMAT_UNSUPPORTED')
    fingerprint, digest = validate_evidence_input(payload, **approved_inputs)
    scope = approved_inputs['expected_scope']
    try:
        value = json.loads(payload.decode('utf-8-sig'), object_pairs_hook=_unique)
        if (type(value) is not dict or set(value) != {'contract', 'header', 'lines'}
                or value['contract'] != 'invoice-normalized-v1' or type(value['header']) is not dict
                or set(value['header']) != _HEADER or type(value['lines']) is not list
                or not 1 <= len(value['lines']) <= MAX_ROWS):
            raise EvidenceRejected('EVIDENCE_SCHEMA_INVALID')
        header = value['header']
        start = _date(header['service_start']) if header['service_start'] is not None else None
        end = _date(header['service_end']) if header['service_end'] is not None else None
        if (start is None) != (end is None) or (start is not None and not start < end):
            raise EvidenceRejected('EVIDENCE_INVOICE_FACT_INVALID')
        parsed_header = InvoiceHeader(*(_text(header[key]) for key in
            ('source_evidence_id', 'supplier_identity', 'buyer_identity', 'invoice_number')),
            _date(header['invoice_date']), _text(header['currency']),
            *(_amount(header[key]) for key in ('net_amount', 'vat_amount', 'total_amount')), start, end)
        if (parsed_header.currency != scope.currency
                or not scope.period_start <= parsed_header.invoice_date < scope.period_end):
            raise EvidenceRejected('EVIDENCE_SCOPE_MISMATCH')
        lines = []
        seen = set()
        for row in value['lines']:
            if type(row) is not dict or set(row) != _LINE:
                raise EvidenceRejected('EVIDENCE_SCHEMA_INVALID')
            quality = _text(row['quality_ref']) if row['quality_ref'] is not None else None
            line = InvoiceLine(_text(row['line_ref']), _text(row['item_ref']), quality, _text(row['uom']),
                *(_amount(row[key]) for key in ('quantity', 'unit_price', 'discount_amount',
                                              'net_amount', 'vat_rate', 'vat_amount', 'total_amount')))
            if line.line_ref in seen or not Decimal(0) <= line.vat_rate <= Decimal(100):
                raise EvidenceRejected('EVIDENCE_INVOICE_FACT_INVALID')
            seen.add(line.line_ref)
            lines.append(line)
    except EvidenceRejected:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise EvidenceRejected('EVIDENCE_SCHEMA_INVALID') from None
    # Arithmetic/rounding/period/legal conclusions belong to approved rules, not extraction.
    return InvoiceEvidence(scope, digest, fingerprint, profile.parser_version, approved_inputs['private_blob_ref'],
        approved_inputs['retention_policy_id'], parsed_header, tuple(lines), profile)
