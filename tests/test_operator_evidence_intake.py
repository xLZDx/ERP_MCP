import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from business_ai_gateway.evidence_index import ApprovedEvidenceProvider, load_approval_index
from business_ai_gateway.evidence_store import PrivateEvidenceStore, _write_new
from business_ai_gateway.external_evidence import EvidenceRejected
from scripts.evidence_intake import intake
from tests.test_private_evidence_store import PAYLOAD, inputs


def fixture(tmp_path):
    store = PrivateEvidenceStore.create(tmp_path)
    profile = inputs()['profile']
    profile_data = json.dumps(asdict(profile), default=str).encode()
    profile_path, input_path = store._root / 'profile.json', store._root / 'input.csv'
    _write_new(profile_path, profile_data)
    _write_new(input_path, PAYLOAD)
    values = {'store_root': store._root, 'input_path': input_path,
              'input_sha256': hashlib.sha256(PAYLOAD).hexdigest(), 'profile_path': profile_path,
              'profile_sha256': hashlib.sha256(profile_data).hexdigest(), 'retention_policy_id': 'fixture-policy',
              'approved_from': datetime(2026, 1, 1, tzinfo=UTC),
              'approved_until': datetime(2030, 1, 1, tzinfo=UTC), 'approval_output': store._root / 'approval.json'}
    return store, profile, values


async def test_operator_disk_intake_index_provider_roundtrip_and_no_raw_cli_fields(tmp_path):
    store, profile, values = fixture(tmp_path)
    summary = intake(**values)
    provider = ApprovedEvidenceProvider(store, values['approval_output'], summary['approval_sha256'])
    manifest = await provider.read_manifest_after_access_gate(profile.scope.source_id,
        profile.scope.company_id, summary['evidence_id'])
    assert manifest['document_sha256'] == summary['document_sha256']
    assert summary['business_acceptance'] == 'NOT_EVALUATED'
    assert summary['native_format_validation'] == 'NOT_PROVEN'
    for private in (profile.scope.company_id, str(tmp_path), 'private-business-key', '12.340000'):
        assert private not in str(summary) + str(manifest)


def test_extend_index_creates_new_file_preserves_old_approval_and_raw_records(tmp_path):
    store, _profile, values = fixture(tmp_path)
    first = intake(**values)
    original = values['approval_output'].read_bytes()
    second = intake(**(values | {'approval_output': store._root / 'approval-v2.json',
        'existing_index': values['approval_output'], 'existing_index_sha256': first['approval_sha256']}))
    assert values['approval_output'].read_bytes() == original
    assert second['entry_count'] == 2 and second['evidence_id'] != first['evidence_id']
    assert len(list(store._root.rglob('document.bin'))) == 2
    assert len(load_approval_index(store._root / 'approval-v2.json', second['approval_sha256'])) == 2


@pytest.mark.parametrize('mutation', ['input_pin', 'profile_pin', 'expired', 'naive', 'existing_pin_missing'])
def test_intake_denial_persists_no_raw_blob_or_approval(tmp_path, mutation):
    store, _profile, values = fixture(tmp_path)
    if mutation == 'input_pin':
        values['input_sha256'] = 'f' * 64
    elif mutation == 'profile_pin':
        values['profile_sha256'] = 'f' * 64
    elif mutation == 'expired':
        values['approved_until'] = datetime(2026, 1, 2, tzinfo=UTC)
    elif mutation == 'naive':
        values['approved_from'] = values['approved_from'].replace(tzinfo=None)
    else:
        values['existing_index'] = store._root / 'unconfirmed-index.json'
    with pytest.raises(EvidenceRejected):
        intake(**values)
    assert not list(store._root.rglob('document.bin')) and not values['approval_output'].exists()


def test_existing_output_is_not_overwritten_and_outside_store_output_is_rejected(tmp_path):
    store, _profile, values = fixture(tmp_path)
    _write_new(values['approval_output'], b'preserved-synthetic-file')
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_APPROVAL_OUTPUT_INVALID$'):
        intake(**values)
    assert values['approval_output'].read_bytes() == b'preserved-synthetic-file'
    with pytest.raises(EvidenceRejected, match='^EVIDENCE_APPROVAL_OUTPUT_INVALID$'):
        intake(**(values | {'approval_output': tmp_path / 'outside.json'}))
    assert not list(store._root.rglob('document.bin'))


def test_actual_operator_cli_executes_intake_and_rejects_repeat_without_traceback(tmp_path):
    _store, _profile, values = fixture(tmp_path)
    command = [sys.executable, '-m', 'scripts.evidence_intake', '--store-root', str(values['store_root']),
        '--input', str(values['input_path']), '--input-sha256', values['input_sha256'],
        '--profile', str(values['profile_path']), '--profile-sha256', values['profile_sha256'],
        '--retention-policy-id', values['retention_policy_id'], '--approved-from', '2026-01-01T00:00:00Z',
        '--approved-until', '2030-01-01T00:00:00Z', '--approval-output', str(values['approval_output'])]
    success = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    assert success.returncode == 0 and json.loads(success.stdout)['entry_count'] == 1
    failed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    assert failed.returncode != 0 and failed.stderr.strip() == 'EVIDENCE_OPERATOR_INTAKE_REJECTED'
    assert 'Traceback' not in failed.stderr and str(tmp_path) not in success.stdout + failed.stderr
