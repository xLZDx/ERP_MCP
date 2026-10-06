"""Internal validated-profile document/payment allocation before reused aging buckets."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, localcontext

from .aging import aggregate_open_items
from .external_evidence import EvidenceScope

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _number(value):
    return (isinstance(value, Decimal) and value.is_finite() and value.copy_abs() < Decimal('1e28')
            and -6 <= value.as_tuple().exponent <= 28)


@dataclass(frozen=True, slots=True)
class AgingProfile:
    scope: EvidenceScope
    metadata_sha256: str
    version: str
    kind: str  # AR or AP; positive document debt and negative credit explicitly normalized
    as_of: date
    effective_from: date
    effective_until: date
    due_date_rule: str
    settlement_relation: str
    native_report_mapping: str
    amount_encoding: str = 'positive_document_and_payment_magnitudes_v1'

    def fingerprint(self):
        self.scope.validate()
        if (type(self.kind) is not str or self.kind not in {'AR', 'AP'} or not _sha(self.metadata_sha256)
                or not all(_id(value) for value in (self.version, self.due_date_rule,
                                                   self.settlement_relation, self.native_report_mapping))
                or type(self.as_of) is not date or not self.scope.period_start <= self.as_of < self.scope.period_end
                or type(self.effective_from) is not date or type(self.effective_until) is not date
                or not self.effective_from <= self.scope.period_start <= self.as_of < self.effective_until
                or self.scope.period_end > self.effective_until
                or self.amount_encoding != 'positive_document_and_payment_magnitudes_v1'):
            raise ValueError('AGING_PROFILE_INVALID')
        return hashlib.sha256(json.dumps(asdict(self), default=str, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SettlementDocument:
    document_ref: str
    counterparty_ref: str
    contract_ref: str
    document_date: date
    due_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class SettlementPayment:
    payment_ref: str
    counterparty_ref: str
    contract_ref: str
    payment_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class SettlementAllocation:
    allocation_ref: str
    payment_ref: str
    document_ref: str
    allocation_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class SettlementObservation:
    scope: EvidenceScope
    profile_fingerprint: str
    metadata_sha256: str
    artifact_sha256: str
    evidence_level: str
    complete: bool
    opening_items_known: bool
    documents: tuple[SettlementDocument, ...]
    payments: tuple[SettlementPayment, ...]
    allocations: tuple[SettlementAllocation, ...]


def evaluate_aging(profile: AgingProfile, observation: SettlementObservation | None, *,
                   validated_profiles: frozenset[str]) -> dict:
    fingerprint = profile.fingerprint()
    result = {'kind': profile.kind, 'profile_fingerprint': fingerprint,
              'scope_fingerprint': profile.scope.fingerprint(), 'status': 'CAPABILITY_UNSUPPORTED',
              'reason': 'AGING_PROFILE_UNCONFIRMED', 'rows': [], 'anomalies': [], 'evidence_level': None,
              'native_approval_inferred': False, 'human_review_required': True}
    if fingerprint not in validated_profiles:
        return result
    if (not isinstance(observation, SettlementObservation) or observation.scope != profile.scope
            or observation.profile_fingerprint != fingerprint or observation.metadata_sha256 != profile.metadata_sha256
            or not _sha(observation.artifact_sha256) or observation.complete is not True
            or observation.opening_items_known is not True or type(observation.evidence_level) is not str
            or observation.evidence_level not in {'L1', 'L2-A', 'L2-B', 'L3'}
            or any(not isinstance(items, tuple) or len(items) > 2000 for items in
                   (observation.documents, observation.payments, observation.allocations))):
        result.update(status='INCONCLUSIVE', reason='AGING_OBSERVATION_INCOMPLETE_OR_SCOPE_MISMATCH')
        return result
    result.update(status='INCONCLUSIVE', reason='SETTLEMENT_FACT_INVALID')
    documents, payments = {}, {}
    for rows, expected_type, key, target in ((observation.documents, SettlementDocument, 'document_ref', documents),
                                            (observation.payments, SettlementPayment, 'payment_ref', payments)):
        for row in rows:
            if (not isinstance(row, expected_type) or not _id(getattr(row, key))
                    or not _id(row.counterparty_ref) or not _id(row.contract_ref)
                    or not _number(row.amount) or row.amount < 0 or getattr(row, key) in target):
                return result
            business_date = row.document_date if isinstance(row, SettlementDocument) else row.payment_date
            if type(business_date) is not date or business_date > profile.as_of:
                return result
            if isinstance(row, SettlementDocument) and type(row.due_date) is not date:
                return result
            target[getattr(row, key)] = row
    document_paid = dict.fromkeys(documents, Decimal(0))
    payment_used = dict.fromkeys(payments, Decimal(0))
    seen = set()
    with localcontext() as context:
        context.prec = 120
        for allocation in observation.allocations:
            if (not isinstance(allocation, SettlementAllocation) or not _number(allocation.amount)
                    or not _id(allocation.allocation_ref)
                    or not _id(allocation.payment_ref) or not _id(allocation.document_ref)
                    or allocation.amount < 0 or type(allocation.allocation_date) is not date
                    or allocation.allocation_date > profile.as_of
                    or allocation.payment_ref not in payments or allocation.document_ref not in documents
                    or allocation.allocation_ref in seen):
                return result
            document, payment = documents[allocation.document_ref], payments[allocation.payment_ref]
            if (document.counterparty_ref != payment.counterparty_ref or document.contract_ref != payment.contract_ref
                    or allocation.allocation_date < max(document.document_date, payment.payment_date)):
                return result
            seen.add(allocation.allocation_ref)
            document_paid[allocation.document_ref] += allocation.amount
            payment_used[allocation.payment_ref] += allocation.amount
            if payment_used[allocation.payment_ref] > payment.amount:
                result.update(reason='PAYMENT_OVERALLOCATED')
                return result
        open_items = []
        for key, document in documents.items():
            remaining = document.amount - document_paid[key]
            if remaining < 0:
                result['anomalies'].append({'document_sha256': hashlib.sha256(key.encode()).hexdigest(),
                                           'reason': 'DOCUMENT_OVERSETTLED'})
            open_items.append({'counterparty_id': document.counterparty_ref, 'currency': profile.scope.currency,
                               'due_date': document.due_date.isoformat(), 'open_amount': str(remaining)})
        for key, payment in payments.items():
            credit = payment.amount - payment_used[key]
            if credit:
                open_items.append({'counterparty_id': payment.counterparty_ref, 'currency': profile.scope.currency,
                                   'due_date': profile.as_of.isoformat(), 'open_amount': str(-credit)})
        if len(open_items) > 2000 or any(not _number(Decimal(row['open_amount'])) for row in open_items):
            result.update(reason='AGING_INPUT_LIMIT')
            return result
        # Reuse the existing bucket contract; no currency conversion or cross-item credit netting.
        rows = aggregate_open_items(open_items, as_of=profile.as_of)
    result.update(status='FINDING' if result['anomalies'] else 'PASS', reason='VALIDATED_SETTLEMENT_AGING_ONLY',
                  rows=rows, evidence_level=observation.evidence_level, artifact_sha256=observation.artifact_sha256)
    return result  # private authorized output; not production/native acceptance
