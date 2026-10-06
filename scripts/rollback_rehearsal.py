"""Validate a non-destructive rollback rehearsal manifest.

This command never changes a database or deployment. It verifies that an operator supplied
immutable release/configuration references and prints NOT_RUN until the controlled environment
executes the actual isolated restore and traffic cutover.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "current_release",
    "previous_release",
    "database_recovery_point",
    "migration_version",
    "gateway_image_digest",
    "sidecar_image_digest",
    "secret_version_ids",
    "authorized_by",
}


def validate_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != REQUIRED:
        raise ValueError("rollback manifest must contain exactly the required evidence fields")
    for key in REQUIRED:
        if key == "secret_version_ids":
            if not isinstance(payload[key], list) or not payload[key] or not all(
                isinstance(item, str) and item and "=" not in item and "\n" not in item
                for item in payload[key]
            ):
                raise ValueError("secret_version_ids must contain identifiers, never secret values")
        elif not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"rollback manifest field {key} must be a non-empty string")
    if not payload["gateway_image_digest"].startswith("sha256:"):
        raise ValueError("gateway_image_digest must be immutable sha256 digest")
    if not payload["sidecar_image_digest"].startswith("sha256:"):
        raise ValueError("sidecar_image_digest must be immutable sha256 digest")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    validate_manifest(args.manifest)
    print("rollback manifest: VALID")
    print("destructive restore/cutover: NOT_RUN (operator approval and isolated target required)")


if __name__ == "__main__":
    main()
