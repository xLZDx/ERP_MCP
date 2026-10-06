from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_preflight import validate_release_tree
from scripts.rollback_rehearsal import validate_manifest


def test_release_preflight_requires_normative_evidence():
    paths = validate_release_tree(Path(__file__).parents[1])
    assert "docs/adr/ADR-0003-reuse-before-rewrite.md" in paths


def test_rollback_manifest_rejects_secret_values(tmp_path):
    payload = {
        "current_release": "ec1ca10",
        "previous_release": "5ff7ccf",
        "database_recovery_point": "2026-10-06T08:00:00Z",
        "migration_version": "009",
        "gateway_image_digest": "sha256:" + "a" * 64,
        "sidecar_image_digest": "sha256:" + "b" * 64,
        "secret_version_ids": ["projects/p/secrets/rsv-config/versions/3"],
        "authorized_by": "incident-operator@example.test",
    }
    path = tmp_path / "rollback.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_manifest(path)["migration_version"] == "009"
    payload["secret_version_ids"] = ["password=private"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="secret values"):
        validate_manifest(path)
