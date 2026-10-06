"""Operator-pinned private approval index. No model-authored paths, hashes, policies or profiles."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from .evidence_store import (
    PrivateEvidenceStore,
    StoredEvidenceReceipt,
    _read_bounded,
    _safe_location,
)
from .external_evidence import EvidenceClass, EvidenceParserProfile, EvidenceRejected, EvidenceScope
from .secret_files import SecretDirectoryUnavailable

_SHA = re.compile(r'[a-f0-9]{64}\Z')
_KEY = re.compile(r'[a-f0-9]{32}\Z')
_POLICY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_SCOPE_FIELDS = set(EvidenceScope.__dataclass_fields__)
_PROFILE_FIELDS = {'profile_id', 'version', 'evidence_class', 'scope', 'parser_version'}
_ENTRY_FIELDS = {'evidence_id', 'receipt', 'profile', 'profile_fingerprint', 'retention_policy_id',
                 'approved_from', 'approved_until'}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
        result[key] = value
    return result


def _instant(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class EvidenceApproval:
    evidence_id: str
    receipt: StoredEvidenceReceipt
    profile: EvidenceParserProfile
    retention_policy_id: str
    approved_from: datetime
    approved_until: datetime

    def as_record(self):
        if (any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
                for value in (self.approved_from, self.approved_until))
                or self.approved_from >= self.approved_until):
            raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
        return {'evidence_id': self.evidence_id, 'receipt': asdict(self.receipt),
                'profile': json.loads(json.dumps(asdict(self.profile), default=str)),
                'profile_fingerprint': self.profile.fingerprint(), 'retention_policy_id': self.retention_policy_id,
                'approved_from': self.approved_from.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'approved_until': self.approved_until.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}


def _entry(record):
    if type(record) is not dict or set(record) != _ENTRY_FIELDS:
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    identity, receipt, profile = record['evidence_id'], record['receipt'], record['profile']
    if (type(identity) is not str or not _KEY.fullmatch(identity) or type(receipt) is not dict
            or set(receipt) != {'private_blob_ref', 'manifest_sha256', 'document_sha256'}
            or receipt['private_blob_ref'] != f'private:{identity}'
            or any(type(receipt[key]) is not str or not _SHA.fullmatch(receipt[key])
                   for key in ('manifest_sha256', 'document_sha256'))
            or type(profile) is not dict or set(profile) != _PROFILE_FIELDS
            or type(profile['scope']) is not dict or set(profile['scope']) != _SCOPE_FIELDS
            or type(record['retention_policy_id']) is not str or not _POLICY.fullmatch(record['retention_policy_id'])):
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    candidate = profile_from_record(profile)
    if candidate.fingerprint() != record['profile_fingerprint']:
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    start, end = _instant(record['approved_from']), _instant(record['approved_until'])
    if start >= end:
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    return EvidenceApproval(identity, StoredEvidenceReceipt(**receipt), candidate,
                            record['retention_policy_id'], start, end)


def profile_from_record(profile) -> EvidenceParserProfile:
    """Approved operator config format, not a document-authored instruction or source protocol."""
    if (type(profile) is not dict or set(profile) != _PROFILE_FIELDS
            or type(profile['scope']) is not dict or set(profile['scope']) != _SCOPE_FIELDS):
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    try:
        values = dict(profile['scope'])
        if str(UUID(values['company_id'])) != values['company_id']:
            raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
        for key in ('period_start', 'period_end'):
            if type(values[key]) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', values[key]):
                raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
            values[key] = date.fromisoformat(values[key])
        candidate = EvidenceParserProfile(profile['profile_id'], profile['version'], EvidenceClass(profile['evidence_class']),
            EvidenceScope(**values), profile['parser_version'])
        candidate.fingerprint()
        return candidate
    except (ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, EvidenceRejected):
            raise
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID') from None


def load_approval_index(path: Path, expected_sha256: str) -> tuple[EvidenceApproval, ...]:
    if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    try:
        _safe_location(path)
        data = _read_bounded(path, 512_000)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise EvidenceRejected('EVIDENCE_APPROVAL_STALE')
        decoded = json.loads(data, object_pairs_hook=_unique)
        if (type(decoded) is not dict or set(decoded) != {'schema_version', 'entries'}
                or type(decoded['schema_version']) is not int or decoded['schema_version'] != 1
                or type(decoded['entries']) is not list or not 1 <= len(decoded['entries']) <= 64):
            raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
        entries = tuple(_entry(item) for item in decoded['entries'])
        if len({item.evidence_id for item in entries}) != len(entries):
            raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
        return entries
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, SecretDirectoryUnavailable) as exc:
        if isinstance(exc, EvidenceRejected):
            raise
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID') from None


class ApprovedEvidenceProvider:
    """Read-only provider invoked only AFTER gateway source/company ACL/rate/durable audit gate."""
    def __init__(self, store: PrivateEvidenceStore, index_path: Path, index_sha256: str, *, clock=None):
        self.store, self.index_path, self.index_sha256 = store, index_path, index_sha256
        self.clock = clock or (lambda: datetime.now(UTC))

    def _approved(self, source_id, company_id, evidence_id):
        if type(evidence_id) is not str or not _KEY.fullmatch(evidence_id):
            raise EvidenceRejected('EVIDENCE_REFERENCE_INVALID')
        entries = load_approval_index(self.index_path, self.index_sha256)
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
        for entry in entries:
            if (entry.evidence_id == evidence_id and entry.profile.scope.source_id == source_id
                    and entry.profile.scope.company_id == str(company_id)
                    and entry.approved_from <= now < entry.approved_until):
                return entry
        # Same result for absent, different-company or expired approval. Never reveal other entries.
        raise EvidenceRejected('EVIDENCE_REQUIRED')

    def _read_manifest(self, source_id, company_id, evidence_id):
        entry = self._approved(source_id, company_id, evidence_id)
        evidence = self.store.read_normalized(entry.receipt, profile=entry.profile,
            expected_scope=entry.profile.scope, validated_profiles=frozenset({entry.profile.fingerprint()}),
            approved_retention_policies=frozenset({entry.retention_policy_id}))
        if self._approved(source_id, company_id, evidence_id) != entry:
            raise EvidenceRejected('EVIDENCE_APPROVAL_STALE')
        return evidence.safe_manifest()  # no raw facts, private paths/refs, amounts or identities

    async def read_manifest_after_access_gate(self, source_id, company_id, evidence_id):
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._read_manifest, source_id, company_id, evidence_id),
                                          timeout=5)
        except TimeoutError:
            raise EvidenceRejected('EVIDENCE_READ_TIMEOUT') from None
