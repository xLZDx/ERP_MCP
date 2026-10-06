import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from pydantic import ValidationError

from business_ai_gateway.audit import (
    Audit,
    AuditUnavailable,
    begin_request_correlation_id,
    current_request_correlation_id,
    end_request_correlation_id,
)
from business_ai_gateway.evidence_index import (
    ApprovedEvidenceProvider,
    EvidenceApproval,
    load_approval_index,
)
from business_ai_gateway.evidence_store import PrivateEvidenceStore, _write_new
from business_ai_gateway.external_evidence import EvidenceRejected
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from tests.test_private_evidence_store import PAYLOAD, ingest, inputs
from tests.test_server_audit import RecordingAudit, TestRegistry


def fixture(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    values = inputs()
    receipt = ingest(store, values)
    approval = EvidenceApproval(receipt.private_blob_ref.removeprefix('private:'), receipt,
        values['profile'], 'fixture-policy', datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
    path = store._root / 'approval.json'
    data = json.dumps({'schema_version': 1, 'entries': [approval.as_record()]}, sort_keys=True).encode()
    _write_new(path, data)
    digest = hashlib.sha256(data).hexdigest()
    provider = ApprovedEvidenceProvider(store, path, digest, clock=lambda: datetime(2026, 10, 6, tzinfo=UTC))
    return provider, approval, data


async def test_actual_private_store_pinned_index_returns_only_minimized_manifest(tmp_path):
    provider, approval, _data = fixture(tmp_path)
    result = await provider.read_manifest_after_access_gate(approval.profile.scope.source_id,
        UUID(approval.profile.scope.company_id), approval.evidence_id)
    assert result['document_sha256'] == hashlib.sha256(PAYLOAD).hexdigest()
    assert result['native_format_validation'] == 'NOT_PROVEN' and result['fact_count'] == 1
    for private in ('private-business-key', approval.profile.scope.company_id,
                    approval.receipt.private_blob_ref, '12.340000', str(tmp_path)):
        assert private not in str(result)


@pytest.mark.parametrize('mutation', ['company', 'source', 'reference', 'expired', 'not_yet_approved'])
async def test_different_scope_absent_or_outside_approval_window_never_exposes_other_record(tmp_path, mutation):
    provider, approval, _data = fixture(tmp_path)
    source, company, identity = approval.profile.scope.source_id, approval.profile.scope.company_id, approval.evidence_id
    if mutation == 'company':
        company = str(uuid4())
    elif mutation == 'source':
        source = 'different-source'
    elif mutation == 'reference':
        identity = uuid4().hex
    elif mutation == 'expired':
        provider.clock = lambda: datetime(2027, 1, 1, tzinfo=UTC)
    else:
        provider.clock = lambda: datetime(2025, 12, 31, tzinfo=UTC)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_REQUIRED$'):
        await provider.read_manifest_after_access_gate(source, company, identity)


@pytest.mark.parametrize('mutation', ['duplicate', 'wrong_profile', 'unknown_field', 'boolean_version',
                                    'missing_entries', 'bad_receipt', 'wrong_class', 'naive_time'])
def test_even_operator_pinned_invalid_index_is_rejected_without_raw_context(tmp_path, mutation):
    provider, approval, data = fixture(tmp_path)
    decoded = json.loads(data)
    if mutation == 'duplicate':
        decoded['entries'].append(approval.as_record())
    elif mutation == 'wrong_profile':
        decoded['entries'][0]['profile_fingerprint'] = 'f' * 64
    elif mutation == 'unknown_field':
        decoded['private-field'] = 'private-dsn-password'
    elif mutation == 'boolean_version':
        decoded['schema_version'] = True
    elif mutation == 'missing_entries':
        decoded['entries'] = []
    elif mutation == 'bad_receipt':
        decoded['entries'][0]['receipt']['private_blob_ref'] = 'private:../outside'
    elif mutation == 'wrong_class':
        decoded['entries'][0]['profile']['evidence_class'] = 'z_report'
    else:
        decoded['entries'][0]['approved_until'] = '2027-01-01T00:00:00'
    data = json.dumps(decoded).encode()
    provider.index_path.write_bytes(data)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_APPROVAL_INVALID$') as failure:
        load_approval_index(provider.index_path, hashlib.sha256(data).hexdigest())
    assert 'private-dsn-password' not in str(failure.value)


def test_duplicate_json_key_rejected_even_with_pinned_hash(tmp_path):
    provider, _approval, _data = fixture(tmp_path)
    data = b'{"schema_version":1,"schema_version":1,"entries":[]}'
    provider.index_path.write_bytes(data)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_APPROVAL_INVALID$'):
        load_approval_index(provider.index_path, hashlib.sha256(data).hexdigest())


async def test_index_change_during_blob_read_revokes_result_before_return(tmp_path, monkeypatch):
    provider, approval, _data = fixture(tmp_path)
    original = provider.store.read_normalized

    def read(*args, **kwargs):
        evidence = original(*args, **kwargs)
        provider.index_path.write_bytes(b'{}')
        return evidence

    monkeypatch.setattr(provider.store, 'read_normalized', read)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_APPROVAL_STALE$'):
        await provider.read_manifest_after_access_gate(approval.profile.scope.source_id,
            approval.profile.scope.company_id, approval.evidence_id)


def test_naive_operator_approval_is_not_silently_assigned_machine_timezone(tmp_path):
    _provider, approval, _data = fixture(tmp_path)
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_APPROVAL_INVALID$'):
        replace(approval, approved_from=approval.approved_from.replace(tzinfo=None)).as_record()


@pytest.mark.parametrize('values', [{'evidence_store_root': 'private-sensitive-path'},
    {'evidence_store_root': 'relative', 'evidence_approval_index': 'relative', 'evidence_approval_sha256': 'a' * 64},
    {'evidence_approval_sha256': 'not-a-digest'}])
def test_provider_configuration_is_all_or_none_absolute_and_hash_pinned_with_private_inputs_hidden(values):
    with pytest.raises(ValidationError) as failure:
        Settings(**values)
    assert 'private-sensitive-path' not in str(failure.value)


def mcp_fixture(provider):
    audit, rate = RecordingAudit(), SimpleNamespace(check=AsyncMock())
    runtime = SimpleNamespace(audit=audit, registry=TestRegistry(), rate_limit=rate, evidence_provider=provider)
    return build_mcp(Settings(), runtime), audit, rate


async def test_actual_sdk_manifest_tool_after_acl_rate_receipt_never_returns_raw_facts(tmp_path, monkeypatch):
    provider, approval, _data = fixture(tmp_path)
    mcp, audit, rate = mcp_fixture(provider)
    original = provider.read_manifest_after_access_gate

    async def read(*args):
        rate.check.assert_awaited_once()
        assert len(audit.events) == 1 and audit.events[0]['detail_code'] == 'ACCESS_AUTHORIZED'
        return await original(*args)

    monkeypatch.setattr(provider, 'read_manifest_after_access_gate', read)
    result = await mcp.call_tool('external_evidence_manifest', {'source_id': approval.profile.scope.source_id,
        'company_id': approval.profile.scope.company_id, 'evidence_id': approval.evidence_id})
    decoded = json.loads(result.content[0].text)
    assert decoded['business_acceptance'] == 'NOT_EVALUATED'
    assert decoded['native_approval_inferred'] is False
    assert 'private-business-key' not in str(result) and '12.340000' not in str(result)
    assert len(audit.events) == 2 and audit.events[-1]['detail_code'] == 'EVIDENCE_MANIFEST_COMPLETE'


@pytest.mark.parametrize('failure', ['acl', 'audit', 'rate'])
async def test_actual_sdk_manifest_tool_denial_never_calls_provider(failure):
    provider = SimpleNamespace(read_manifest_after_access_gate=AsyncMock())
    mcp, audit, rate = mcp_fixture(provider)
    source_id = 'forbidden' if failure == 'acl' else 'synthetic-source'
    if failure == 'audit':
        audit.write = AsyncMock(side_effect=AuditUnavailable('AUDIT_UNAVAILABLE'))
    elif failure == 'rate':
        rate.check.side_effect = ConnectionError('synthetic outage')
    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool('external_evidence_manifest', {'source_id': source_id,
            'company_id': str(uuid4()), 'evidence_id': uuid4().hex})
    provider.read_manifest_after_access_gate.assert_not_awaited()


async def test_disabled_provider_is_unsupported_and_malicious_error_details_are_not_echoed():
    mcp, audit, _rate = mcp_fixture(None)
    args = {'source_id': 'synthetic-source', 'company_id': str(uuid4()), 'evidence_id': uuid4().hex}
    result = await mcp.call_tool('external_evidence_manifest', args)
    assert json.loads(result.content[0].text)['status'] == 'CAPABILITY_UNSUPPORTED'
    assert audit.events[-1]['outcome'] == 'denied'
    provider = SimpleNamespace(read_manifest_after_access_gate=AsyncMock(side_effect=EvidenceRejected('private-key-secret')))
    mcp, _audit, _rate = mcp_fixture(provider)
    result = await mcp.call_tool('external_evidence_manifest', args)
    assert 'private-key-secret' not in str(result)
    assert json.loads(result.content[0].text)['reason'] == 'EVIDENCE_READ_REJECTED'


@pytest.mark.skipif(not os.getenv('BAG_PRIVILEGE_TEST_DATABASE_URL'), reason='requires disposable PostgreSQL')
async def test_sdk_real_private_provider_and_actual_postgres_audit_receipt_then_readonly_denial(tmp_path, monkeypatch):
    provider, approval, _data = fixture(tmp_path)
    connection = await asyncpg.connect(os.environ['BAG_PRIVILEGE_TEST_DATABASE_URL'])
    audit = Audit(SimpleNamespace(require_pool=lambda: connection), include_query=False)
    runtime = SimpleNamespace(audit=audit, registry=TestRegistry(), rate_limit=SimpleNamespace(check=AsyncMock()),
                              evidence_provider=provider)
    mcp = build_mcp(Settings(), runtime)
    original = provider.read_manifest_after_access_gate

    async def read(*args):
        row = await connection.fetchrow('SELECT detail_code, query_json FROM bag.audit_events WHERE request_id=$1',
                                         current_request_correlation_id())
        assert row['detail_code'] == 'ACCESS_AUTHORIZED' and row['query_json'] is None
        return await original(*args)

    mocked = AsyncMock(side_effect=read)
    monkeypatch.setattr(provider, 'read_manifest_after_access_gate', mocked)
    token, correlation = begin_request_correlation_id()  # direct SDK call omits transport middleware
    arguments = {'source_id': approval.profile.scope.source_id, 'company_id': approval.profile.scope.company_id,
                 'evidence_id': approval.evidence_id}
    try:
        await connection.execute('SET ROLE business_ai_app')
        result = await mcp.call_tool('external_evidence_manifest', arguments)
        assert json.loads(result.content[0].text)['business_acceptance'] == 'NOT_EVALUATED'
        rows = await connection.fetch('SELECT detail_code, query_json FROM bag.audit_events WHERE request_id=$1',
                                      correlation)
        assert len(rows) == 2 and all(row['query_json'] is None for row in rows)
        assert {row['detail_code'] for row in rows} == {'ACCESS_AUTHORIZED', 'EVIDENCE_MANIFEST_COMPLETE'}
        mocked.reset_mock()
        async with connection.transaction(readonly=True):
            with pytest.raises(UnexpectedToolError):
                await mcp.call_tool('external_evidence_manifest', arguments)
        mocked.assert_not_awaited()
        # Synthetic append-only rows retained. Source/company ACL contract stub is NOT native acceptance.
    finally:
        end_request_correlation_id(token)
        await connection.close()
