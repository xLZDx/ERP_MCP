"""Build a non-authorizing S10 manifest from explicitly recorded evidence results."""

from __future__ import annotations

import argparse
from importlib import import_module
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
release_manifest = import_module("business_ai_gateway.phase2.release_manifest")
assemble_manifest = release_manifest.assemble_manifest
MANIFEST_RELATIVE_PATH = release_manifest.MANIFEST_RELATIVE_PATH
fixed_manifest_output_path = release_manifest.fixed_manifest_output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, required=True,
        help="JSON file with source_head, cases, test_runs, uat and pr_number",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_output = fixed_manifest_output_path(REPO_ROOT, MANIFEST_RELATIVE_PATH)
    resolved_manifest_output = manifest_output.resolve()
    if args.output.resolve() != resolved_manifest_output:
        raise ValueError("output path must be reports/S10_RELEASE_EVIDENCE_MANIFEST.json")
    if args.input.resolve() == resolved_manifest_output:
        raise ValueError("input and output paths must differ")
    source = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(source, dict) or set(source) != {"source_head", "cases", "test_runs", "uat", "pr_number"}:
        raise ValueError("invalid S10 manifest input fields")
    manifest = assemble_manifest(REPO_ROOT, output_path=manifest_output, **source)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=manifest_output.parent,
            prefix=f".{manifest_output.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, manifest_output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    print(f"S10 engineering evidence manifest written: {manifest_output}")


if __name__ == "__main__":
    main()
