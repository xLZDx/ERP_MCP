"""Explicit operator-only normalized evidence intake; new approval index, never 1C/model writes."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from business_ai_gateway.evidence_index import (
    EvidenceApproval,
    _instant,
    _unique,
    load_approval_index,
    profile_from_record,
)
from business_ai_gateway.evidence_store import (
    PrivateEvidenceStore,
    _read_bounded,
    _safe_location,
    _sync_directory,
    _write_new,
)
from business_ai_gateway.external_evidence import MAX_BYTES, EvidenceRejected
from business_ai_gateway.secret_files import SecretDirectoryUnavailable


def intake(*, store_root: Path, input_path: Path, input_sha256: str, profile_path: Path,
           profile_sha256: str, retention_policy_id: str, approved_from: datetime,
           approved_until: datetime, approval_output: Path, existing_index: Path | None = None,
           existing_index_sha256: str | None = None, mime: str = 'text/csv') -> dict:
    """Pins/profile/window are explicit operator approval. This never approves native semantics."""
    if (not isinstance(approved_from, datetime) or approved_from.tzinfo is None
            or not isinstance(approved_until, datetime) or approved_until.tzinfo is None
            or not approved_from <= datetime.now(UTC) < approved_until):
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    if (existing_index is None) != (existing_index_sha256 is None):
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    _safe_location(input_path)
    _safe_location(profile_path)
    _safe_location(approval_output)
    store = PrivateEvidenceStore(store_root)
    if approval_output.parent != store_root or approval_output.exists():
        raise EvidenceRejected('EVIDENCE_APPROVAL_OUTPUT_INVALID')
    payload = _read_bounded(input_path, MAX_BYTES)
    profile_data = _read_bounded(profile_path, 32_000)
    if hashlib.sha256(profile_data).hexdigest() != profile_sha256:
        raise EvidenceRejected('EVIDENCE_APPROVAL_STALE')
    profile = profile_from_record(json.loads(profile_data, object_pairs_hook=_unique))
    previous = load_approval_index(existing_index, existing_index_sha256) if existing_index else ()
    if len(previous) >= 64:
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    # Existing index and caller-pinned document/profile all checked before persisting new bytes.
    receipt = store.ingest_normalized(payload, profile=profile, expected_scope=profile.scope,
        validated_profiles=frozenset({profile.fingerprint()}), retention_policy_id=retention_policy_id,
        approved_retention_policies=frozenset({retention_policy_id}), expected_document_sha256=input_sha256,
        mime=mime)
    approval = EvidenceApproval(receipt.private_blob_ref.removeprefix('private:'), receipt, profile,
                                retention_policy_id, approved_from, approved_until)
    entries = [item.as_record() for item in previous] + [approval.as_record()]
    data = json.dumps({'schema_version': 1, 'entries': entries}, sort_keys=True).encode()
    # Size/schema verified before commit, and new-only exclusive publication.
    if len(data) > 512_000:
        raise EvidenceRejected('EVIDENCE_APPROVAL_INVALID')
    _write_new(approval_output, data)
    _sync_directory(store_root)
    digest = hashlib.sha256(data).hexdigest()
    load_approval_index(approval_output, digest)
    return {'approval_sha256': digest, 'evidence_id': approval.evidence_id,
            'document_sha256': receipt.document_sha256, 'entry_count': len(entries),
            'raw_document_retained_privately': True, 'native_format_validation': 'NOT_PROVEN',
            'business_acceptance': 'NOT_EVALUATED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store-root', 'input', 'profile', 'approval-output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('input-sha256', 'profile-sha256', 'retention-policy-id', 'approved-from', 'approved-until'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--existing-index', type=Path)
    parser.add_argument('--existing-index-sha256')
    parser.add_argument('--mime', choices=('text/csv', 'application/json'), default='text/csv')
    args = parser.parse_args()
    try:
        result = intake(store_root=args.store_root, input_path=args.input, input_sha256=args.input_sha256,
            profile_path=args.profile, profile_sha256=args.profile_sha256,
            retention_policy_id=args.retention_policy_id, approved_from=_instant(args.approved_from),
            approved_until=_instant(args.approved_until), approval_output=args.approval_output,
            existing_index=args.existing_index, existing_index_sha256=args.existing_index_sha256, mime=args.mime)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, SecretDirectoryUnavailable):
        raise SystemExit('EVIDENCE_OPERATOR_INTAKE_REJECTED') from None
    print(json.dumps(result, sort_keys=True))  # hashes/counts only, never paths/identity/raw facts


if __name__ == '__main__':
    main()
