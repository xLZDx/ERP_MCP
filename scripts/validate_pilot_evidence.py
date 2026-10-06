from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from business_ai_gateway.pilot_evidence import validate_pilot_manifest

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "deploy/pilot/evidence.manifest.template.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P9 pilot/production evidence gates")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--require-go",
        action="store_true",
        help="fail unless the manifest supports a fully evidenced PRODUCTION_GO decision",
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read pilot evidence manifest: {type(exc).__name__}", file=sys.stderr)
        return 2

    issues, go_ready = validate_pilot_manifest(manifest)
    decision = manifest.get("decision") if isinstance(manifest, dict) else "INVALID"
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
    print(f"decision={decision}; production_go_supported={str(go_ready).lower()}")
    if args.require_go and not go_ready:
        print("PRODUCTION GO blocked: required evidence is missing or invalid", file=sys.stderr)
        return 1
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
