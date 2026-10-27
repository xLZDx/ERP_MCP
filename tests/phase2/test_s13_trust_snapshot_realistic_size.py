"""A realistically large trust snapshot decodes under the 8 MiB ceiling, with margin."""
from __future__ import annotations

import json

from erp_mcp_private_writer.postgres_evidence_trust import (
    _MAX_SIGNERS,
    _MAX_SNAPSHOT_BYTES,
    PostgresEvidenceTrustSource,
)


def _signer(index: int) -> dict[str, object]:
    return {
        "key_id": f"key-{index:05d}",
        "key_version": "v1",
        "public_key_hex": f"{index:064x}",
        "signer_role": "writer_receipt",
        "service_id": "erp-mcp-private-writer",
        "host_id": f"host-{index % 64:02d}",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "revoked_at": None,
        "allowed_scopes": [
            {
                "tenant_id": f"tenant-{scope:02d}",
                "company_id": f"company-{scope:02d}",
                "organization_ref": f"org-{scope:02d}",
                "base_fingerprint": f"{scope:064x}",
            }
            for scope in range(4)
        ],
        # Every history entry must be a signer of the same snapshot and the last one is the current key.
        "rotation_history": [{"key_id": f"key-{index:05d}", "key_version": "v1"}],
    }


def test_the_maximum_signer_count_with_realistic_scopes_fits_the_ceiling_with_margin():
    payload = {
        "revision": "1",
        "loaded_at": "2026-10-26T00:00:00Z",
        "signers": [_signer(index) for index in range(_MAX_SIGNERS)],
        "process_bindings": [],
        "oracle_artifacts": [],
        "outcome_version_floors": [],
    }
    text = json.dumps(payload, separators=(",", ":"))
    size = len(text.encode("utf-8"))

    snapshot = PostgresEvidenceTrustSource._decode(text)

    assert len(snapshot.signers) == _MAX_SIGNERS
    # Record the measured size: the ceiling must leave at least 25% headroom for this shape.
    assert size < _MAX_SNAPSHOT_BYTES * 0.75, size
