"""Profile-bound internal invoice comparisons; no source protocol, posting or tax-law inference."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, localcontext

from .external_evidence import EvidenceClass, EvidenceParserProfile, EvidenceRejected, EvidenceScope
from .invoice_evidence import (
    PARSER_VERSION,
    InvoiceEvidence,
    InvoiceHeader,
    InvoiceLine,
    invoice_facts_fingerprint,
)

_HASH = re.compile(r'[a-f0-9]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def _text(value):
    return (type(value) is str and 0 < len(value) <= 128
            and not any(ord(character) < 32 or ord(character) == 127 for character in value))


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _number(value):
    return (isinstance(value, Decimal) and value.is_finite() and value.copy_abs() < Decimal('1e28')
            and -6 <= value.as_tuple().exponent <= 28)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class InvoiceRuleProfile:
    scope: EvidenceScope
    metadata_sha256: str
    pack_version: str
    expected_buyer_identity: str
    item_mapping: tuple[tuple[str, str], ...]  # exact external→native references, not guessed labels
    native_report_mapping: str
    effective_from: date
    effective_until: date
    production_overhead_rule: str | None  # explicit source-specific applicability; no universal 821
    quantity_tolerance: Decimal = Decimal(0)
    price_tolerance: Decimal = Decimal(0)
    net_tolerance: Decimal = Decimal(0)
    line_vat_tolerance: Decimal = Decimal(0)
    header_tolerance: Decimal = Decimal(0)
    allow_line_rounding_when_totals_exact: bool = False
    amount_encoding: str = 'net_plus_vat_normalized_v1'

    def fingerprint(self):
        self.scope.validate()
        if (not _hash(self.metadata_sha256) or not _text(self.expected_buyer_identity)
                or type(self.pack_version) is not str or not _ID.fullmatch(self.pack_version)
                or type(self.native_report_mapping) is not str or not _ID.fullmatch(self.native_report_mapping)
                or not isinstance(self.item_mapping, tuple) or not 1 <= len(self.item_mapping) <= 2000
                or any(not isinstance(pair, tuple) or len(pair) != 2 or not all(_text(item) for item in pair)
                       for pair in self.item_mapping)
                or len({pair[0] for pair in self.item_mapping}) != len(self.item_mapping)
                or len({pair[1] for pair in self.item_mapping}) != len(self.item_mapping)
                or type(self.effective_from) is not date or type(self.effective_until) is not date
                or not self.effective_from <= self.scope.period_start < self.scope.period_end <= self.effective_until
                or (self.scope.period_end - self.scope.period_start).days > 366
                or any(not _number(value) or not Decimal(0) <= value <= Decimal(1) for value in (
                    self.quantity_tolerance, self.price_tolerance, self.net_tolerance,
                    self.line_vat_tolerance, self.header_tolerance))
                or type(self.allow_line_rounding_when_totals_exact) is not bool
                or self.amount_encoding != 'net_plus_vat_normalized_v1'
                or (self.production_overhead_rule is not None and
                    (type(self.production_overhead_rule) is not str or not _ID.fullmatch(self.production_overhead_rule)))):
            raise ValueError('INVOICE_RULE_PROFILE_INVALID')
        return _fingerprint(asdict(self))


@dataclass(frozen=True, slots=True)
class InvoiceSourceObservation:
    scope: EvidenceScope
    rule_profile_fingerprint: str
    metadata_sha256: str
    artifact_sha256: str
    evidence_level: str
    complete: bool
    matched_invoice_number: str  # approved collector correlation, never an assumed line ordinal
    receipt_exists: bool
    payment_exists: bool
    header: InvoiceHeader | None
    lines: tuple[InvoiceLine, ...]
    booking_period_start: date
    booking_period_end: date
    service_allocation_confirmed: bool | None
    production_overhead_resolved: bool | None


@dataclass(frozen=True, slots=True)
class InvoiceArchiveProof:
    scope: EvidenceScope
    invoice_number: str
    supplier_identity: str
    original_document_sha256: str
    private_blob_verified: bool

    def fingerprint(self):
        self.scope.validate()
        if (not _text(self.invoice_number) or not _text(self.supplier_identity)
                or not _hash(self.original_document_sha256) or self.private_blob_verified is not True):
            raise ValueError('INVOICE_ARCHIVE_PROOF_INVALID')
        return _fingerprint(asdict(self))


def _valid_header(header, scope):
    return (isinstance(header, InvoiceHeader) and all(_text(value) for value in (
        header.source_evidence_id, header.supplier_identity, header.buyer_identity, header.invoice_number))
        and type(header.invoice_date) is date and scope.period_start <= header.invoice_date < scope.period_end
        and header.currency == scope.currency
        and all(_number(value) for value in (header.net_amount, header.vat_amount, header.total_amount))
        and ((header.service_start is None and header.service_end is None) or
             (type(header.service_start) is date and type(header.service_end) is date
              and header.service_start < header.service_end)))


def _valid_lines(lines):
    if not isinstance(lines, tuple) or not 1 <= len(lines) <= 2000:
        return False
    seen = set()
    for line in lines:
        if (not isinstance(line, InvoiceLine) or not all(_text(value) for value in
                (line.line_ref, line.item_ref, line.uom))
                or (line.quality_ref is not None and not _text(line.quality_ref))
                or not all(_number(value) for value in (line.quantity, line.unit_price, line.discount_amount,
                    line.net_amount, line.vat_rate, line.vat_amount, line.total_amount))
                or not Decimal(0) <= line.vat_rate <= Decimal(100) or line.line_ref in seen):
            return False
        seen.add(line.line_ref)
    return True


def evaluate_invoice(profile: InvoiceRuleProfile, *, validated_rule_profiles: frozenset[str],
                     invoice: InvoiceEvidence | None, validated_parser_profiles: frozenset[str],
                     source: InvoiceSourceObservation | None, archive: InvoiceArchiveProof | None,
                     validated_archive_proofs: frozenset[str]) -> dict:
    """Trusted server inputs only. PASS means normalized comparison, never legal/native acceptance."""
    fingerprint = profile.fingerprint()
    level = source.evidence_level if isinstance(source, InvoiceSourceObservation) else None
    safe_level = level if type(level) is str and level in {'L1', 'L2-A', 'L2-B', 'L3'} else None
    result = {'pack_id': 'DAD-INVOICE', 'pack_version': profile.pack_version, 'profile_fingerprint': fingerprint,
              'scope_fingerprint': profile.scope.fingerprint(), 'status': 'CAPABILITY_UNSUPPORTED',
              'reason': 'INVOICE_PROFILE_UNCONFIRMED', 'findings': [], 'checks': [], 'evidence_level': safe_level,
              'human_review_required': True, 'native_approval_inferred': False, 'legal_conclusion_inferred': False}
    if fingerprint not in validated_rule_profiles:
        return result
    if not isinstance(source, InvoiceSourceObservation):
        result.update(status='INCONCLUSIVE', reason='SOURCE_OBSERVATION_REQUIRED')
        return result
    if (source.scope != profile.scope or source.rule_profile_fingerprint != fingerprint
            or source.metadata_sha256 != profile.metadata_sha256 or source.complete is not True
            or not _hash(source.artifact_sha256) or safe_level is None or not _text(source.matched_invoice_number)
            or type(source.receipt_exists) is not bool or type(source.payment_exists) is not bool
            or (source.service_allocation_confirmed is not None and type(source.service_allocation_confirmed) is not bool)
            or (source.production_overhead_resolved is not None and type(source.production_overhead_resolved) is not bool)
            or type(source.booking_period_start) is not date or type(source.booking_period_end) is not date
            or not profile.scope.period_start <= source.booking_period_start < source.booking_period_end <= profile.scope.period_end
            or (source.receipt_exists and (not _valid_header(source.header, profile.scope) or not _valid_lines(source.lines)))
            or (not source.receipt_exists and (source.header is not None or source.lines != ()))):
        result.update(status='INCONCLUSIVE', reason='SOURCE_OBSERVATION_INCOMPLETE_OR_SCOPE_MISMATCH')
        return result
    if invoice is None:
        result.update(status='EVIDENCE_REQUIRED', reason='PRIMARY_INVOICE_REQUIRED')
        if source.receipt_exists:
            result['findings'].append({'rule_id': 'DAD-INV-08', 'reason': 'PRIMARY_ARCHIVE_EVIDENCE_MISSING'})
        return result
    if not isinstance(invoice, InvoiceEvidence):
        result.update(status='INCONCLUSIVE', reason='STRUCTURED_INVOICE_EVIDENCE_REQUIRED')
        return result
    try:
        parser_fingerprint = invoice.parser_profile.fingerprint()
    except (EvidenceRejected, AttributeError):
        parser_fingerprint = None
    if (invoice.scope != profile.scope or invoice.parser_version != PARSER_VERSION
            or not isinstance(invoice.parser_profile, EvidenceParserProfile)
            or invoice.parser_profile.evidence_class != EvidenceClass.INVOICE
            or invoice.parser_profile.parser_version != invoice.parser_version
            or invoice.parser_profile.scope != profile.scope
            or parser_fingerprint != invoice.profile_fingerprint
            or parser_fingerprint not in validated_parser_profiles or not _hash(invoice.document_sha256)
            or not _valid_header(invoice.header, profile.scope) or not _valid_lines(invoice.lines)
            or source.matched_invoice_number != invoice.header.invoice_number
            or (source.receipt_exists and source.header.invoice_number != invoice.header.invoice_number)
            or invoice.header.buyer_identity != profile.expected_buyer_identity
            or (source.receipt_exists and source.header.buyer_identity != profile.expected_buyer_identity)):
        result.update(status='INCONCLUSIVE', reason='INVOICE_SCOPE_PROFILE_OR_CORRELATION_MISMATCH')
        return result
    if source.artifact_sha256 == invoice.document_sha256:
        result.update(status='INCONCLUSIVE', reason='OBSERVATION_PLANES_NOT_INDEPENDENT')
        return result
    if invoice.normalized_facts_sha256 != invoice_facts_fingerprint(invoice.scope, invoice.profile_fingerprint,
                                                                   invoice.header, invoice.lines):
        result.update(status='INCONCLUSIVE', reason='INVOICE_FACTS_FINGERPRINT_MISMATCH')
        return result
    mapping = dict(profile.item_mapping)
    if any(line.item_ref not in mapping for line in invoice.lines):
        result.update(status='CAPABILITY_UNSUPPORTED', reason='ITEM_MAPPING_UNCONFIRMED')
        return result
    checks = {f'DAD-INV-{index:02}': {'rule_id': f'DAD-INV-{index:02}', 'status': 'PASS',
               'reason': 'NORMALIZED_COMPARISON_ONLY', 'applicable': True} for index in range(1, 12)}
    findings = []
    if invoice.header.service_start is None:
        checks['DAD-INV-06'].update(status='INCONCLUSIVE', reason='NO_SERVICE_PERIOD_DECLARED', applicable=False)
    if profile.production_overhead_rule is None:
        checks['DAD-INV-07'].update(status='INCONCLUSIVE', reason='NOT_APPLICABLE_TO_PROFILE', applicable=False)

    def finding(number, reason, line_ref=None):
        identifier = f'DAD-INV-{number:02}'
        checks[identifier].update(status='FINDING', reason=reason)
        record = {'rule_id': identifier, 'reason': reason}
        if line_ref is not None:
            record['line_sha256'] = hashlib.sha256(line_ref.encode()).hexdigest()
        findings.append(record)

    if not source.receipt_exists:
        if source.payment_exists:
            finding(1, 'PAYMENT_WITHOUT_RECEIPT')
        else:
            finding(1, 'SOURCE_RECEIPT_MISSING')
        # Missing receipt cannot manufacture ten successful comparisons.
        for identifier, check in checks.items():
            if identifier != 'DAD-INV-01':
                check.update(status='INCONCLUSIVE', reason='SOURCE_RECEIPT_REQUIRED')
        result.update(status='FINDING', reason='SOURCE_RECEIPT_MISSING', findings=findings, checks=list(checks.values()))
        return result
    archive_confirmed = False
    if isinstance(archive, InvoiceArchiveProof):
        try:
            archive_confirmed = (archive.scope == profile.scope and archive.invoice_number == invoice.header.invoice_number
                and archive.supplier_identity == invoice.header.supplier_identity
                and archive.original_document_sha256 not in {invoice.document_sha256, source.artifact_sha256}
                and archive.fingerprint() in validated_archive_proofs)
        except ValueError:
            pass
    if not archive_confirmed:
        checks['DAD-INV-08'].update(status='EVIDENCE_REQUIRED', reason='VERIFIED_PRIMARY_ARCHIVE_REQUIRED')
    native = {line.line_ref: line for line in source.lines}
    if len(source.lines) < len(invoice.lines) and len({line.quality_ref for line in invoice.lines}) > 1:
        finding(2, 'ITEM_QUALITIES_COLLAPSED_OR_LINES_MISSING')
    if source.header.supplier_identity != invoice.header.supplier_identity:
        finding(3, 'SUPPLIER_IDENTITY_MISMATCH')
    if not source.booking_period_start <= invoice.header.invoice_date < source.booking_period_end:
        finding(5, 'REGISTRATION_PERIOD_REVIEW_REQUIRED')  # NEVER assert VAT deductibility/illegality
    if (invoice.header.service_start is not None and source.service_allocation_confirmed is not True
            and not source.booking_period_start <= invoice.header.service_start < invoice.header.service_end <= source.booking_period_end):
        finding(6, 'MULTIPERIOD_SERVICE_ALLOCATION_REVIEW')
    if profile.production_overhead_rule is not None and source.production_overhead_resolved is not True:
        finding(7, 'PROFILE_APPROVED_OVERHEAD_REMAINS_UNRESOLVED')
    with localcontext() as context:
        context.prec = 120
        headers_exact = all(getattr(source.header, key) == getattr(invoice.header, key)
                            for key in ('net_amount', 'vat_amount', 'total_amount'))
        if any(abs(getattr(source.header, key) - getattr(invoice.header, key)) > profile.header_tolerance
               for key in ('net_amount', 'vat_amount', 'total_amount')):
            finding(9, 'INVOICE_TOTAL_OR_VAT_MISMATCH')
        for header, lines in ((invoice.header, invoice.lines), (source.header, source.lines)):
            if (abs(header.net_amount + header.vat_amount - header.total_amount) > profile.header_tolerance
                    or any(abs(sum(getattr(line, key) for line in lines) - getattr(header, key))
                           > profile.header_tolerance for key in ('net_amount', 'vat_amount', 'total_amount'))):
                finding(9, 'HEADER_LINE_TOTALS_INCONSISTENT')
            for line in lines:
                if abs(line.quantity * line.unit_price - line.discount_amount - line.net_amount) > profile.net_tolerance:
                    finding(10, 'LINE_NET_ARITHMETIC_INCONSISTENT', line.line_ref)
                if abs(line.net_amount + line.vat_amount - line.total_amount) > profile.net_tolerance:
                    finding(10, 'LINE_GROSS_ARITHMETIC_INCONSISTENT', line.line_ref)
        for line in invoice.lines:
            observed = native.pop(line.line_ref, None)
            if observed is None:
                finding(10, 'SOURCE_LINE_MISSING', line.line_ref)
                continue
            if observed.item_ref != mapping[line.item_ref]:
                finding(4, 'ITEM_MAPPING_MISMATCH', line.line_ref)
            if observed.quality_ref != line.quality_ref or observed.uom != line.uom:
                finding(10, 'QUALITY_OR_UOM_MISMATCH', line.line_ref)
            for field, tolerance in (('quantity', profile.quantity_tolerance), ('unit_price', profile.price_tolerance),
                                     ('discount_amount', profile.net_tolerance), ('net_amount', profile.net_tolerance)):
                if abs(getattr(observed, field) - getattr(line, field)) > tolerance:
                    finding(10, f'{field.upper()}_MISMATCH', line.line_ref)
            if observed.vat_rate != line.vat_rate:
                finding(10, 'DECLARED_VAT_RATE_MISMATCH', line.line_ref)
            vat_difference = abs(observed.vat_amount - line.vat_amount)
            allowed_rounding = (profile.allow_line_rounding_when_totals_exact and headers_exact
                                and vat_difference <= profile.line_vat_tolerance)
            if vat_difference and not allowed_rounding:
                finding(11, 'LINE_VAT_ROUNDING_NOT_ALLOWED', line.line_ref)
            if abs(observed.total_amount - line.total_amount) > profile.net_tolerance and not (
                    allowed_rounding and abs(observed.total_amount - line.total_amount) <= profile.line_vat_tolerance):
                finding(10, 'LINE_TOTAL_MISMATCH', line.line_ref)
        for line_ref in native:
            finding(10, 'EXTRA_SOURCE_LINE', line_ref)
    result.update(status='EVIDENCE_REQUIRED' if not archive_confirmed else 'FINDING' if findings else 'PASS',
        reason='VERIFIED_PRIMARY_ARCHIVE_REQUIRED' if not archive_confirmed else 'VALIDATED_NORMALIZED_INVOICE_COMPARISON',
        findings=findings, checks=list(checks.values()), semantic_artifact_sha256=source.artifact_sha256,
        normalized_carrier_sha256=invoice.document_sha256)
    return result
