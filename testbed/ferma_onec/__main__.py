from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .package_loader import load_seed_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Ferma scenario artifact without seeding 1C")
    parser.add_argument("operation", choices=["verify"])
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    seed = load_seed_inputs(args.package)
    print(json.dumps({"schema_version": seed.manifest.schema_version,
                      "scenario_id": seed.manifest.scenario_id, "run_id": seed.manifest.run_id,
                      "manifest_fingerprint": hashlib.sha256(seed.manifest.model_dump_json().encode()).hexdigest(),
                      "event_count": len(seed.events), "master_data_count": len(seed.master_data),
                      "status": "PACKAGE_VERIFIED", "native_reconciliation": "NOT_RUN"}, indent=2))


if __name__ == "__main__":
    main()
