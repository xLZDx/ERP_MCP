"""Bounded normalized evidence input, not a native-document parser or public upload API."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_BYTES = 4_000_000
MAX_ROWS = 2000
_HASH = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_AMOUNT = re.compile(r"^-?[0-9]{1,28}(?:\.[0-9]{1,6})?$")


class EvidenceRejected(ValueError):
    """Fixed-code failure; never carries the raw document, identity or parser exception."""


class EvidenceClass(StrEnum):
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    Z_REPORT = "z_report"
    TERMINAL_REPORT = "terminal_report"
    MCC_REPORT = "mcc_report"
    TAX_FILING = "tax_filing"
    TAX_RECEIPT = "tax_receipt"
    CUSTOMS_CCAC = "customs_ccac"
    PAYROLL_SOURCE = "payroll_source"
    CONTRACT = "contract"
    RECONCILIATION_ACT = "reconciliation_act"
    CADASTRAL_EXTRACT = "cadastral_extract"
    CORPORATE_MINUTES = "corporate_minutes"
    INVENTORY_ACT = "inventory_act"


@dataclass(frozen=True, slots=True)
class EvidenceScope:
    source_id: str
    company_id: str
    configuration_fingerprint: str
    semantic_profile_fingerprint: str
    period_start: date
    period_end: date  # exclusive
    currency: str
    timezone: str

    def validate(self) -> None:
        if any(not isinstance(value, str) or not _ID.fullmatch(value)
               for value in (self.source_id, self.company_id)):
            raise EvidenceRejected("EVIDENCE_SCOPE_INVALID")
        if any(not isinstance(value, str) or not _HASH.fullmatch(value)
               for value in (self.configuration_fingerprint, self.semantic_profile_fingerprint)):
            raise EvidenceRejected("EVIDENCE_SCOPE_INVALID")
        if (type(self.period_start) is not date or type(self.period_end) is not date
                or self.period_start >= self.period_end
                or not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency)):
            raise EvidenceRejected("EVIDENCE_SCOPE_INVALID")
        try:
            if not isinstance(self.timezone, str) or len(self.timezone) > 64:
                raise ValueError("invalid timezone")
            ZoneInfo(self.timezone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise EvidenceRejected("EVIDENCE_SCOPE_INVALID") from None

    def fingerprint(self) -> str:
        self.validate()
        encoded = json.dumps(asdict(self), default=str, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceParserProfile:
    profile_id: str
    version: str
    evidence_class: EvidenceClass
    scope: EvidenceScope
    parser_version: str = "external-normalized-csv-v1"

    def fingerprint(self) -> str:
        self.scope.validate()
        if (not isinstance(self.profile_id, str) or not _ID.fullmatch(self.profile_id)
                or not isinstance(self.version, str) or not _ID.fullmatch(self.version)
                or not isinstance(self.evidence_class, EvidenceClass)
                or not (self.parser_version == "external-normalized-csv-v1" or (
                    self.evidence_class == EvidenceClass.INVOICE
                    and self.parser_version == "external-normalized-invoice-json-v1"))):
            raise EvidenceRejected("EVIDENCE_PROFILE_INVALID")
        encoded = json.dumps({"id": self.profile_id, "version": self.version,
                              "class": self.evidence_class.value, "scope": self.scope.fingerprint(),
                              "parser_version": self.parser_version}, sort_keys=True)
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceFact:
    key: str
    business_date: date
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ExternalEvidence:
    scope: EvidenceScope
    evidence_class: EvidenceClass
    document_sha256: str
    profile_fingerprint: str
    parser_version: str
    private_blob_ref: str
    retention_policy_id: str
    facts: tuple[EvidenceFact, ...]
    parser_profile: EvidenceParserProfile

    def safe_manifest(self) -> dict:
        # No private blob path, business keys, dates, company/source names or raw accounting values.
        return {"scope_sha256": self.scope.fingerprint(), "evidence_class": self.evidence_class.value,
                "document_sha256": self.document_sha256, "profile_fingerprint": self.profile_fingerprint,
                "parser_version": self.parser_version, "fact_count": len(self.facts),
                "raw_document_retained_by_parser": False, "native_format_validation": "NOT_PROVEN",
                "human_review_required": True}


def parse_normalized_csv(
    payload: bytes, *, profile: EvidenceParserProfile, expected_scope: EvidenceScope,
    validated_profiles: frozenset[str], private_blob_ref: str, retention_policy_id: str,
    approved_retention_policies: frozenset[str], expected_document_sha256: str,
) -> ExternalEvidence:
    """Consume uploaded bytes only; registry/retention approval comes from trusted server config.

    Exact headers key,date,currency,amount are a normalized exchange contract, not guessed bank,
    PDF, Z, tax or payroll formats. No URL/file fetching, blob writes or business PASS is performed.
    """
    if profile.parser_version != 'external-normalized-csv-v1':
        raise EvidenceRejected('EVIDENCE_FORMAT_UNSUPPORTED')
    fingerprint, digest = validate_evidence_input(payload, profile=profile, expected_scope=expected_scope,
        validated_profiles=validated_profiles, private_blob_ref=private_blob_ref,
        retention_policy_id=retention_policy_id, approved_retention_policies=approved_retention_policies,
        expected_document_sha256=expected_document_sha256)
    facts = []
    keys = set()
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != ["key", "date", "currency", "amount"]:
            raise EvidenceRejected("EVIDENCE_SCHEMA_INVALID")
        for row in reader:
            if len(facts) >= MAX_ROWS or set(row) != set(reader.fieldnames):
                raise EvidenceRejected("EVIDENCE_INPUT_LIMIT")
            key = row["key"]
            if (not isinstance(key, str) or not key or len(key) > 128
                    or any(ord(character) < 32 or ord(character) == 127 for character in key)
                    or key in keys or row["currency"] != expected_scope.currency
                    or not isinstance(row["amount"], str) or not _AMOUNT.fullmatch(row["amount"])):
                raise EvidenceRejected("EVIDENCE_FACT_INVALID")
            if not isinstance(row["date"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["date"]):
                raise EvidenceRejected("EVIDENCE_FACT_INVALID")
            business_date = date.fromisoformat(row["date"])
            if not expected_scope.period_start <= business_date < expected_scope.period_end:
                raise EvidenceRejected("EVIDENCE_SCOPE_MISMATCH")
            keys.add(key)
            facts.append(EvidenceFact(key, business_date, row["currency"], Decimal(row["amount"])))
    except EvidenceRejected:
        raise
    except (UnicodeError, csv.Error, TypeError, ValueError, InvalidOperation):
        raise EvidenceRejected("EVIDENCE_SCHEMA_INVALID") from None
    if not facts:
        raise EvidenceRejected("EVIDENCE_REQUIRED")
    return ExternalEvidence(expected_scope, profile.evidence_class, digest, fingerprint,
                            profile.parser_version, private_blob_ref, retention_policy_id, tuple(facts), profile)


def validate_evidence_input(
    payload: bytes, *, profile: EvidenceParserProfile, expected_scope: EvidenceScope,
    validated_profiles: frozenset[str], private_blob_ref: str, retention_policy_id: str,
    approved_retention_policies: frozenset[str], expected_document_sha256: str,
) -> tuple[str, str]:
    """Shared exact approval/retention/scope/digest gate for explicitly selected normalized codecs."""
    expected_scope.validate()
    fingerprint = profile.fingerprint()
    if profile.scope != expected_scope or fingerprint not in validated_profiles:
        raise EvidenceRejected("EVIDENCE_PROFILE_UNCONFIRMED")
    if (not isinstance(private_blob_ref, str)
            or not re.fullmatch(r"private:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", private_blob_ref)
            or not isinstance(retention_policy_id, str) or not _ID.fullmatch(retention_policy_id)
            or retention_policy_id not in approved_retention_policies):
        raise EvidenceRejected("EVIDENCE_RETENTION_UNCONFIRMED")
    if type(payload) is not bytes or not payload or len(payload) > MAX_BYTES:
        raise EvidenceRejected("EVIDENCE_INPUT_LIMIT")
    digest = hashlib.sha256(payload).hexdigest()
    if not isinstance(expected_document_sha256, str) or digest != expected_document_sha256:
        raise EvidenceRejected("EVIDENCE_FINGERPRINT_MISMATCH")
    return fingerprint, digest


def evidence_mime(profile: EvidenceParserProfile) -> str:
    profile.fingerprint()
    return 'application/json' if profile.parser_version == 'external-normalized-invoice-json-v1' else 'text/csv'


def parse_approved_evidence(payload: bytes, **approved_inputs):
    """No sniffing/fallback: only an explicitly approved codec can receive the bytes."""
    profile = approved_inputs['profile']
    profile.fingerprint()
    if profile.parser_version == 'external-normalized-invoice-json-v1':
        from .invoice_evidence import parse_normalized_invoice

        return parse_normalized_invoice(payload, **approved_inputs)
    return parse_normalized_csv(payload, **approved_inputs)


def require_evidence(
    required: frozenset[EvidenceClass], evidence: tuple[ExternalEvidence, ...], *,
    scope: EvidenceScope, validated_profiles: frozenset[str],
) -> None:
    """Gate normalized inputs only; passing this gate is never a business/accounting PASS."""
    scope.validate()
    if (not isinstance(evidence, tuple) or len(evidence) > 64
            or not isinstance(required, frozenset) or any(not isinstance(item, EvidenceClass) for item in required)):
        raise EvidenceRejected("EVIDENCE_SCHEMA_INVALID")
    for item in evidence:
        if (not isinstance(item, ExternalEvidence) or item.scope != scope
                or not isinstance(item.evidence_class, EvidenceClass)
                or not isinstance(item.profile_fingerprint, str)
                or item.profile_fingerprint not in validated_profiles
                or not isinstance(item.parser_profile, EvidenceParserProfile)
                or item.parser_profile.scope != scope or item.parser_profile.evidence_class != item.evidence_class
                or item.parser_profile.parser_version != item.parser_version
                or not isinstance(item.document_sha256, str) or not _HASH.fullmatch(item.document_sha256)
                or not isinstance(item.facts, tuple) or not item.facts or len(item.facts) > MAX_ROWS
                or item.parser_version != "external-normalized-csv-v1"):
            raise EvidenceRejected("EVIDENCE_INCONCLUSIVE")
        try:
            if item.parser_profile.fingerprint() != item.profile_fingerprint:
                raise EvidenceRejected("EVIDENCE_INCONCLUSIVE")
        except EvidenceRejected:
            raise EvidenceRejected("EVIDENCE_INCONCLUSIVE") from None
    if not required.issubset({item.evidence_class for item in evidence}):
        raise EvidenceRejected("EVIDENCE_REQUIRED")
