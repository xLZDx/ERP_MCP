"""Inventory frozen traceability rows without inferring closure from file existence."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

IMPLEMENTATION = {
    "FR-A1": ["src/business_ai_gateway/auth.py", "tests/test_auth.py"],
    "FR-A2": ["src/business_ai_gateway/registry.py"],
    "FR-A3": ["src/business_ai_gateway/registry.py"],
    "FR-B1": ["src/business_ai_gateway/registry.py"],
    "FR-B2": ["src/business_ai_gateway/secrets.py"],
    "NFR-P1": ["src/business_ai_gateway/fanout.py", "tests/test_fanout.py"],
    "NFR-P2": ["scripts/performance_benchmark.py", "tests/test_measured_performance.py"],
    "P6-SEC-1": ["src/business_ai_gateway/adapters/onec/rsv_bridge.py", "tests/test_rsv_bridge.py"],
    "SCOPE-1": ["docs/SCOPE_FREEZE_BASELINE_2026-10-06.md", "tests/test_documentation_package.py"],
    "TEST-FERMA-1": ["testbed/ferma_onec/package_loader.py", "testbed/ferma_onec/target_guard.py",
                     "testbed/ferma_onec/reconcile.py", "tests/test_ferma_package_boundary.py",
                     "tests/test_ferma_reconcile.py"],
}


def build(root: Path) -> dict[str, object]:
    rows = []
    for line in (root / "docs/REQUIREMENTS_TRACEABILITY.md").read_text(encoding="utf-8").splitlines():
        columns = [column.strip() for column in line.split("|")]
        if len(columns) != 6 or columns[1] in {"Req", "---", ""}:
            continue
        identifier, requirement, design, gates = columns[1:5]
        references = IMPLEMENTATION.get(identifier, [])
        if any(not (root / reference).is_file() for reference in references):
            raise ValueError(f"implementation reference missing for {identifier}")
        rows.append({
            "requirement_id": identifier, "requirement": requirement, "design": design,
            "gates": gates, "implementation_references": references,
            "status": "DEFERRED" if identifier.startswith("FUT-") else "OPEN_REQUIRES_EVIDENCE_REVIEW",
        })
    if not rows or len({row["requirement_id"] for row in rows}) != len(rows):
        raise ValueError("traceability matrix is empty or contains duplicate IDs")
    return {
        "schema_version": 1,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "freeze_baseline": "57eb5b0696063237a43f5d1baf0a646278f5d832",
        "production_decision": "NO-GO", "requirements": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = build(Path(__file__).resolve().parents[1])
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"frozen requirements inventoried: {len(evidence['requirements'])}")


if __name__ == "__main__":
    main()
