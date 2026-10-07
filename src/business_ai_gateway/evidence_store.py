"""Private append-only local normalized evidence provider; no fetch/decompression/native parser."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from asyncpg import PostgresError
from redis.exceptions import RedisError

from .external_evidence import (
    MAX_BYTES,
    EvidenceParserProfile,
    EvidenceRejected,
    EvidenceScope,
    ExternalEvidence,
    evidence_mime,
    parse_approved_evidence,
)
from .invoice_evidence import InvoiceEvidence
from .secret_files import (
    SecretDirectoryUnavailable,
    protect_private_directory,
    verify_private_directory,
    verify_private_file,
)

_REF = re.compile(r'private:([a-f0-9]{32})\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_FIELDS = {'schema_version', 'document_sha256', 'bytes', 'scope_sha256', 'profile_fingerprint',
           'evidence_class', 'parser_version', 'retention_policy_id', 'mime', 'encoding'}


def _safe_location(path):
    if not isinstance(path, Path) or not path.is_absolute():
        raise EvidenceRejected('EVIDENCE_STORAGE_LOCATION_INVALID')
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction() or (candidate / '.git').exists():
            raise EvidenceRejected('EVIDENCE_STORAGE_LOCATION_INVALID')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_new(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    verify_private_file(path)


def _read_bounded(path, limit):
    verify_private_file(path)
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
             | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
            raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID')
        if os.name != 'nt' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID')
        data = stream.read(limit + 1)
    if not data or len(data) > limit or len(data) != info.st_size:
        raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID')
    return data


@dataclass(frozen=True, slots=True)
class StoredEvidenceReceipt:
    private_blob_ref: str
    manifest_sha256: str  # bind independently in trusted registry/audit, never derive from edited store
    document_sha256: str


class PrivateEvidenceStore:
    def __init__(self, root: Path):
        _safe_location(root)
        try:
            verify_private_directory(root, purpose='evidence')
        except (OSError, SecretDirectoryUnavailable):
            raise EvidenceRejected('EVIDENCE_STORAGE_UNAVAILABLE') from None
        self._root = root

    @classmethod
    def create(cls, parent: Path):
        """Operator-configured existing private volume parent; create only a new owned directory."""
        _safe_location(parent)
        if not parent.is_dir():
            raise EvidenceRejected('EVIDENCE_STORAGE_LOCATION_INVALID')
        try:
            root = Path(tempfile.mkdtemp(prefix='erp-mcp-evidence-', dir=parent))
            protect_private_directory(root, purpose='evidence')
            return cls(root)
        except (OSError, SecretDirectoryUnavailable):
            raise EvidenceRejected('EVIDENCE_STORAGE_UNAVAILABLE') from None

    def ingest_normalized(self, payload: bytes, *, profile: EvidenceParserProfile,
                          expected_scope: EvidenceScope, validated_profiles: frozenset[str],
                          retention_policy_id: str, approved_retention_policies: frozenset[str],
                          expected_document_sha256: str, mime: str = 'text/csv',
                          encoding: str = 'identity') -> StoredEvidenceReceipt:
        """Trusted operator ingest only; not registered as a public/model write tool."""
        if mime != evidence_mime(profile) or encoding != 'identity':
            raise EvidenceRejected('EVIDENCE_FORMAT_UNSUPPORTED')
        identifier = uuid4().hex
        reference = f'private:{identifier}'
        evidence = parse_approved_evidence(payload, profile=profile, expected_scope=expected_scope,
            validated_profiles=validated_profiles, private_blob_ref=reference,
            retention_policy_id=retention_policy_id, approved_retention_policies=approved_retention_policies,
            expected_document_sha256=expected_document_sha256)
        manifest = {'schema_version': 1, 'document_sha256': evidence.document_sha256, 'bytes': len(payload),
                    'scope_sha256': expected_scope.fingerprint(), 'profile_fingerprint': profile.fingerprint(),
                    'evidence_class': profile.evidence_class.value, 'parser_version': profile.parser_version,
                    'retention_policy_id': retention_policy_id, 'mime': mime, 'encoding': encoding}
        metadata = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        try:
            _safe_location(self._root)
            verify_private_directory(self._root, purpose='evidence')
            directory = self._root / f'erp-mcp-evidence-{identifier}'
            directory.mkdir(mode=0o700)
            protect_private_directory(directory, purpose='evidence')
            _write_new(directory / 'document.bin', payload)
            # Commit marker is last. Any failure leaves private orphan evidence, never a valid receipt.
            _write_new(directory / 'manifest.json', metadata)
            _sync_directory(directory)
            _sync_directory(self._root)
        except (OSError, SecretDirectoryUnavailable):
            raise EvidenceRejected('EVIDENCE_STORAGE_UNAVAILABLE') from None
        return StoredEvidenceReceipt(reference, _digest(metadata), evidence.document_sha256)

    def read_normalized(self, receipt: StoredEvidenceReceipt, *, profile: EvidenceParserProfile,
                        expected_scope: EvidenceScope, validated_profiles: frozenset[str],
                        approved_retention_policies: frozenset[str]) -> ExternalEvidence | InvoiceEvidence:
        if (not isinstance(receipt, StoredEvidenceReceipt) or type(receipt.private_blob_ref) is not str
                or not (match := _REF.fullmatch(receipt.private_blob_ref))
                or any(type(value) is not str or not _SHA.fullmatch(value)
                       for value in (receipt.manifest_sha256, receipt.document_sha256))):
            raise EvidenceRejected('EVIDENCE_REFERENCE_INVALID')
        expected_scope.validate()
        fingerprint = profile.fingerprint()
        if profile.scope != expected_scope or fingerprint not in validated_profiles:
            raise EvidenceRejected('EVIDENCE_PROFILE_UNCONFIRMED')
        try:
            _safe_location(self._root)
            verify_private_directory(self._root, purpose='evidence')
            directory = self._root / f'erp-mcp-evidence-{match[1]}'
            verify_private_directory(directory, purpose='evidence')
            metadata = _read_bounded(directory / 'manifest.json', 64_000)
            if _digest(metadata) != receipt.manifest_sha256:
                raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID')
            manifest = json.loads(metadata)
            if (type(manifest) is not dict or set(manifest) != _FIELDS
                    or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
                    or type(manifest['bytes']) is not int or not 0 < manifest['bytes'] <= MAX_BYTES
                    or manifest['scope_sha256'] != expected_scope.fingerprint()
                    or manifest['profile_fingerprint'] != fingerprint
                    or manifest['document_sha256'] != receipt.document_sha256
                    or manifest['evidence_class'] != profile.evidence_class.value
                    or manifest['parser_version'] != profile.parser_version
                    or manifest['mime'] != evidence_mime(profile) or manifest['encoding'] != 'identity'):
                raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID')
            payload = _read_bounded(directory / 'document.bin', MAX_BYTES)
            if len(payload) != manifest['bytes']:
                raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID')
            return parse_approved_evidence(payload, profile=profile, expected_scope=expected_scope,
                validated_profiles=validated_profiles, private_blob_ref=receipt.private_blob_ref,
                retention_policy_id=manifest['retention_policy_id'],
                approved_retention_policies=approved_retention_policies,
                expected_document_sha256=receipt.document_sha256)
        except (OSError, UnicodeError, ValueError, RecursionError, SecretDirectoryUnavailable) as exc:
            if isinstance(exc, EvidenceRejected):
                raise
            raise EvidenceRejected('EVIDENCE_STORAGE_INTEGRITY_INVALID') from None


class AuthorizedEvidenceReader:
    """Internal service facade: normal source/company ACL and durable audit BEFORE filesystem read."""
    def __init__(self, store: PrivateEvidenceStore, registry, audit, rate_limit, *, required_scope='onec:read',
                 timeout_seconds=5):
        if type(required_scope) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', required_scope):
            raise ValueError('EVIDENCE_SCOPE_POLICY_INVALID')
        if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 30:
            raise ValueError('EVIDENCE_TIMEOUT_POLICY_INVALID')
        self.store, self.registry, self.audit, self.rate_limit = store, registry, audit, rate_limit
        self.required_scope = required_scope
        self.timeout_seconds = timeout_seconds

    async def read(self, principal, receipt: StoredEvidenceReceipt, *, profile: EvidenceParserProfile,
                   expected_scope: EvidenceScope, validated_profiles: frozenset[str],
                   approved_retention_policies: frozenset[str]) -> ExternalEvidence | InvoiceEvidence:
        started = time.monotonic()
        expected_scope.validate()
        try:
            company_id = UUID(expected_scope.company_id)
        except ValueError:
            raise EvidenceRejected('EVIDENCE_SCOPE_INVALID') from None
        try:
            if self.required_scope not in principal.scopes:
                raise PermissionError('required scope missing')
            await self.registry.require_source_for_company(principal, expected_scope.source_id, company_id)
        except PermissionError:
            await self.audit.write(principal=principal, tool='external_evidence_read',
                source_id=expected_scope.source_id, company_id=company_id, outcome='denied', started_at=started,
                detail_code='EVIDENCE_ACCESS_DENIED')
            raise EvidenceRejected('EVIDENCE_ACCESS_DENIED') from None
        except (PostgresError, OSError, RuntimeError, ValueError, TypeError):
            await self.audit.write(principal=principal, tool='external_evidence_read',
                source_id=expected_scope.source_id, company_id=company_id, outcome='error', started_at=started,
                detail_code='EVIDENCE_ACCESS_UNAVAILABLE')
            raise EvidenceRejected('EVIDENCE_ACCESS_UNAVAILABLE') from None
        try:
            await self.rate_limit.check(subject=principal.subject, source_id=expected_scope.source_id,
                                        tool='external_evidence_read')
        except (RedisError, OSError, RuntimeError):
            await self.audit.write(principal=principal, tool='external_evidence_read',
                source_id=expected_scope.source_id, company_id=company_id, outcome='denied', started_at=started,
                detail_code='EVIDENCE_LIMIT_UNAVAILABLE')
            raise EvidenceRejected('EVIDENCE_LIMIT_UNAVAILABLE') from None
        await self.audit.write(principal=principal, tool='external_evidence_read',
            source_id=expected_scope.source_id, company_id=company_id, outcome='success', started_at=started,
            detail_code='ACCESS_AUTHORIZED', policy_version='predispatch-audit-v1', record_tool_outcome=False)
        try:
            evidence = await asyncio.wait_for(asyncio.to_thread(self.store.read_normalized, receipt, profile=profile,
                expected_scope=expected_scope, validated_profiles=validated_profiles,
                approved_retention_policies=approved_retention_policies), timeout=self.timeout_seconds)
        except TimeoutError:
            await self.audit.write(principal=principal, tool='external_evidence_read',
                source_id=expected_scope.source_id, company_id=company_id, outcome='error', started_at=started,
                detail_code='EVIDENCE_READ_TIMEOUT')
            raise EvidenceRejected('EVIDENCE_READ_TIMEOUT') from None
        except EvidenceRejected:
            await self.audit.write(principal=principal, tool='external_evidence_read',
                source_id=expected_scope.source_id, company_id=company_id, outcome='error', started_at=started,
                detail_code='EVIDENCE_READ_REJECTED')
            raise
        await self.audit.write(principal=principal, tool='external_evidence_read',
            source_id=expected_scope.source_id, company_id=company_id, outcome='success', started_at=started,
            profile_fingerprint=profile.fingerprint(), returned_items=len(evidence.facts),
            detail_code='EVIDENCE_READ_COMPLETE')
        return evidence
