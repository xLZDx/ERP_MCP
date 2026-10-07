import hashlib
import json
import os
import stat
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from business_ai_gateway import evidence_store
from business_ai_gateway.audit import AuditUnavailable
from business_ai_gateway.evidence_store import (
    AuthorizedEvidenceReader,
    PrivateEvidenceStore,
    StoredEvidenceReceipt,
)
from business_ai_gateway.external_evidence import (
    MAX_BYTES,
    EvidenceClass,
    EvidenceParserProfile,
    EvidenceRejected,
)
from business_ai_gateway.principal import Principal
from business_ai_gateway.secret_files import verify_private_directory, verify_private_file
from tests.test_external_evidence import scope

PAYLOAD = b'key,date,currency,amount\nprivate-business-key,2026-01-12,MDL,12.340000\n'


def inputs(kind=EvidenceClass.BANK_STATEMENT):
    candidate = EvidenceParserProfile('fixture', 'v1', kind, replace(scope(), company_id=str(uuid4())))
    return {'profile': candidate, 'expected_scope': candidate.scope,
            'validated_profiles': frozenset({candidate.fingerprint()}),
            'approved_retention_policies': frozenset({'fixture-policy'})}


def ingest(store, values):
    return store.ingest_normalized(PAYLOAD, **values, retention_policy_id='fixture-policy',
                                  expected_document_sha256=hashlib.sha256(PAYLOAD).hexdigest())


@pytest.mark.parametrize('kind', list(EvidenceClass))
def test_real_disk_append_reopen_exact_provenance_and_private_os_permissions(tmp_path, kind):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs(kind)
    receipt = ingest(store, values)
    verify_private_directory(store._root, purpose='evidence')
    files = list(store._root.rglob('*'))
    for file in files:
        if file.is_file():
            verify_private_file(file)  # actual NTFS DACL/Unix mode, not mocked
    reopened = PrivateEvidenceStore(store._root)
    evidence = reopened.read_normalized(receipt, **values)
    assert evidence.facts[0].key == 'private-business-key' and evidence.evidence_class == kind
    assert evidence.document_sha256 == receipt.document_sha256
    assert evidence.safe_manifest()['native_format_validation'] == 'NOT_PROVEN'
    manifest = next(store._root.rglob('manifest.json')).read_text()
    for private in ('private-business-key', values['expected_scope'].company_id, str(tmp_path)):
        assert private not in manifest + repr(receipt) + str(evidence.safe_manifest())
    if os.name != 'nt':
        assert stat.S_IMODE(store._root.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(file.stat().st_mode) == 0o600 for file in files if file.is_file())


def test_repeated_ingest_creates_new_immutable_records_never_overwrites(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    first, second = ingest(store, values), ingest(store, values)
    assert first.private_blob_ref != second.private_blob_ref
    assert first.document_sha256 == second.document_sha256
    assert len(list(store._root.glob('erp-mcp-evidence-*'))) == 2
    assert store.read_normalized(first, **values).facts == store.read_normalized(second, **values).facts


@pytest.mark.parametrize('reference', ['private:../escape', 'private:../../x', 'file:///private',
                                      'https://private.example', 'private:C:\\private', 'private:abc', None])
def test_path_traversal_url_or_invalid_opaque_reference_is_rejected(tmp_path, reference):
    store = PrivateEvidenceStore.create(tmp_path)
    receipt = StoredEvidenceReceipt(reference, 'a' * 64, 'b' * 64)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_REFERENCE_INVALID$'):
        store.read_normalized(receipt, **inputs())


@pytest.mark.parametrize('mutation', ['blob', 'manifest', 'both', 'oversized_blob', 'oversized_manifest', 'missing_manifest'])
def test_changed_truncated_oversized_or_uncommitted_evidence_never_reads(tmp_path, mutation):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    receipt = ingest(store, values)
    blob, manifest = next(store._root.rglob('document.bin')), next(store._root.rglob('manifest.json'))
    if mutation == 'missing_manifest':
        # Move this owned synthetic commit marker aside, retaining the orphan without deleting data.
        manifest.rename(manifest.with_name('orphan-manifest.json'))
    elif mutation == 'oversized_manifest':
        manifest.write_bytes(b'x' * 64_001)
    elif mutation == 'manifest':
        manifest.write_bytes(b'{}')
    else:
        data = b'x' * (MAX_BYTES + 1) if mutation == 'oversized_blob' else PAYLOAD.replace(b'12.340000', b'99.990000')
        blob.write_bytes(data)
        if mutation == 'both':
            fields = json.loads(manifest.read_text())
            fields['document_sha256'] = hashlib.sha256(data).hexdigest()
            manifest.write_text(json.dumps(fields))
    with pytest.raises(EvidenceRejected):
        store.read_normalized(receipt, **values)


def test_unconfirmed_cross_scope_and_revoked_retention_are_denied_after_reopen(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    receipt = ingest(store, values)
    for overrides in ({'validated_profiles': frozenset()},
                      {'expected_scope': replace(values['expected_scope'], company_id=str(uuid4()))},
                      {'approved_retention_policies': frozenset()}):
        with pytest.raises(EvidenceRejected):
            store.read_normalized(receipt, **(values | overrides))


@pytest.mark.parametrize('overrides', [{'mime': 'application/pdf'}, {'mime': 'application/zip'},
                                     {'encoding': 'gzip'}, {'encoding': 'deflate'}])
def test_native_formats_and_decompression_are_not_guessed_or_enabled(tmp_path, overrides):
    store = PrivateEvidenceStore.create(tmp_path)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_FORMAT_UNSUPPORTED$'):
        store.ingest_normalized(PAYLOAD, **inputs(), **overrides, retention_policy_id='fixture-policy',
                                expected_document_sha256=hashlib.sha256(PAYLOAD).hexdigest())
    assert not list(store._root.iterdir())


def test_store_cannot_be_created_inside_git_or_open_non_task_directory(tmp_path):
    repository = tmp_path / 'synthetic-repo'
    repository.mkdir()
    (repository / '.git').mkdir()
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_STORAGE_LOCATION_INVALID$'):
        PrivateEvidenceStore.create(repository)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_STORAGE_UNAVAILABLE$'):
        PrivateEvidenceStore(tmp_path)


def test_real_hardlinked_blob_is_denied_without_reading_external_data(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    receipt = ingest(store, values)
    blob = next(store._root.rglob('document.bin'))
    os.link(blob, tmp_path / 'synthetic-hardlink.bin')
    with pytest.raises(EvidenceRejected):
        store.read_normalized(receipt, **values)


def service():
    store = SimpleNamespace(read_normalized=Mock(return_value=SimpleNamespace(facts=(1,))))
    registry = SimpleNamespace(require_source_for_company=AsyncMock())
    audit = SimpleNamespace(write=AsyncMock())
    rate = SimpleNamespace(check=AsyncMock())
    return AuthorizedEvidenceReader(store, registry, audit, rate), store, registry, audit, rate


PRINCIPAL = Principal('synthetic-subject', 'synthetic-client', frozenset({'onec:read'}), frozenset(), {})


async def test_service_orders_acl_rate_durable_receipt_before_private_filesystem_read():
    reader, store, registry, audit, rate = service()
    values = inputs()

    def read(*_args, **_kwargs):
        registry.require_source_for_company.assert_awaited_once()
        rate.check.assert_awaited_once()
        audit.write.assert_awaited_once()
        assert audit.write.call_args.kwargs['detail_code'] == 'ACCESS_AUTHORIZED'
        assert audit.write.call_args.kwargs['record_tool_outcome'] is False
        return SimpleNamespace(facts=(1,))

    store.read_normalized.side_effect = read
    await reader.read(PRINCIPAL, StoredEvidenceReceipt('private:' + 'a' * 32, 'b' * 64, 'c' * 64), **values)
    assert audit.write.await_count == 2
    assert audit.write.call_args.kwargs['detail_code'] == 'EVIDENCE_READ_COMPLETE'


@pytest.mark.parametrize('failure', ['acl', 'rate', 'audit'])
async def test_service_acl_rate_or_audit_denial_never_touches_private_store(failure):
    reader, store, registry, audit, rate = service()
    if failure == 'acl':
        registry.require_source_for_company.side_effect = PermissionError('private-company-id')
    elif failure == 'rate':
        rate.check.side_effect = ConnectionError('rate unavailable')
    else:
        audit.write.side_effect = AuditUnavailable('AUDIT_UNAVAILABLE')
    with pytest.raises((EvidenceRejected, AuditUnavailable)):
        await reader.read(PRINCIPAL, StoredEvidenceReceipt('private:' + 'a' * 32, 'b' * 64, 'c' * 64), **inputs())
    store.read_normalized.assert_not_called()


async def test_missing_oauth_scope_is_denied_before_registry_and_filesystem():
    reader, store, registry, audit, _rate = service()
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_ACCESS_DENIED$'):
        await reader.read(replace(PRINCIPAL, scopes=frozenset()),
            StoredEvidenceReceipt('private:' + 'a' * 32, 'b' * 64, 'c' * 64), **inputs())
    store.read_normalized.assert_not_called()
    registry.require_source_for_company.assert_not_awaited()
    assert audit.write.call_args.kwargs['outcome'] == 'denied'


def test_real_file_permission_widening_is_rejected_without_implicit_acl_repair(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    receipt = ingest(store, values)
    blob = next(store._root.rglob('document.bin'))
    if os.name == 'nt':
        environment = {name: os.environ[name] for name in ('PATH', 'SystemRoot', 'TEMP', 'TMP',
                       'USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if name in os.environ}
        environment['ERP_MCP_OWNED_EVIDENCE_FILE'] = str(blob)
        environment['PSModulePath'] = str(Path(os.environ['SystemRoot']) /
            'System32' / 'WindowsPowerShell' / 'v1.0' / 'Modules')
        script = """
        $ErrorActionPreference='Stop'
        $ownedAcl=Get-Acl -LiteralPath $env:ERP_MCP_OWNED_EVIDENCE_FILE
        $everyone=[Security.Principal.SecurityIdentifier]::new('S-1-1-0')
        $ownedRule=[Security.AccessControl.FileSystemAccessRule]::new($everyone,'Read','Allow')
        $ownedAcl.AddAccessRule($ownedRule)
        Set-Acl -LiteralPath $env:ERP_MCP_OWNED_EVIDENCE_FILE -AclObject $ownedAcl
        """
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            env=environment, capture_output=True, timeout=30, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0
    else:
        blob.chmod(0o644)
    with pytest.raises(EvidenceRejected):
        store.read_normalized(receipt, **values)
    if os.name != 'nt':
        assert stat.S_IMODE(blob.stat().st_mode) == 0o644  # read did not silently reset permissions


def test_manifest_write_failure_returns_no_receipt_preserves_private_orphan_and_sanitizes_error(tmp_path, monkeypatch):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    original = evidence_store._write_new

    def write(path, data):
        if path.name == 'manifest.json':
            raise OSError('private-volume-account-path')
        return original(path, data)

    monkeypatch.setattr(evidence_store, '_write_new', write)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_STORAGE_UNAVAILABLE$') as failure:
        ingest(store, values)
    assert failure.value.__suppress_context__ is True
    assert len(list(store._root.rglob('document.bin'))) == 1
    assert not list(store._root.rglob('manifest.json'))
    verify_private_file(next(store._root.rglob('document.bin')))


def test_exclusive_blob_creation_never_overwrites_a_persisted_record(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    receipt = ingest(store, values)
    with pytest.raises(FileExistsError):
        evidence_store._write_new(next(store._root.rglob('document.bin')), b'corruption')
    assert store.read_normalized(receipt, **values).document_sha256 == receipt.document_sha256


async def test_real_slow_thread_read_times_out_with_error_audit_not_business_success():
    reader, store, _registry, audit, _rate = service()
    reader.timeout_seconds = 1
    entered, release = threading.Event(), threading.Event()

    def slow(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=3)  # bounded owned fixture; no write side effects
        return SimpleNamespace(facts=(1,))

    store.read_normalized.side_effect = slow
    task = asyncio.create_task(reader.read(PRINCIPAL,
        StoredEvidenceReceipt('private:' + 'a' * 32, 'b' * 64, 'c' * 64), **inputs()))
    try:
        assert await asyncio.to_thread(entered.wait, 0.8) and not task.done()
        with pytest.raises(EvidenceRejected, match='^EVIDENCE_READ_TIMEOUT$'):
            await task
    finally:
        release.set()
    assert audit.write.await_count == 2 and audit.write.call_args.kwargs['outcome'] == 'error'
    assert audit.write.call_args.kwargs['detail_code'] == 'EVIDENCE_READ_TIMEOUT'


def test_real_junction_or_symlink_store_root_is_rejected(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    alias = tmp_path / 'erp-mcp-evidence-alias'
    if os.name == 'nt':
        environment = {name: os.environ[name] for name in ('PATH', 'SystemRoot', 'TEMP', 'TMP',
                       'USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if name in os.environ}
        environment['PSModulePath'] = str(Path(os.environ['SystemRoot']) /
            'System32' / 'WindowsPowerShell' / 'v1.0' / 'Modules')
        environment['ERP_MCP_OWNED_LINK'] = str(alias)
        environment['ERP_MCP_OWNED_TARGET'] = str(store._root)
        script = "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:ERP_MCP_OWNED_LINK -Target $env:ERP_MCP_OWNED_TARGET | Out-Null"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            env=environment, capture_output=True, timeout=30, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0 and alias.is_junction()
    else:
        alias.symlink_to(store._root, target_is_directory=True)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_STORAGE_LOCATION_INVALID$'):
        PrivateEvidenceStore(alias)
import asyncio
