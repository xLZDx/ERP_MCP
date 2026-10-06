"""Inventory frozen traceability rows without inferring closure from file existence."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

IMPLEMENTATION = {
    "DAD-1": ["src/business_ai_gateway/dad_small_checks.py", "src/business_ai_gateway/dad_rules.py",
              "tests/test_dad_small_checks.py", "tests/test_dad_reconciliation_rules.py"],
    "DAD-2": ["src/business_ai_gateway/invoice_evidence.py", "tests/test_invoice_evidence.py",
              "src/business_ai_gateway/invoice_rules.py", "tests/test_invoice_rules.py"],
    "DAD-4": ["src/business_ai_gateway/financial_statements.py", "tests/test_financial_statements.py"],
    "FR-E1": ["src/business_ai_gateway/semantic.py", "src/business_ai_gateway/aging.py",
              "src/business_ai_gateway/settlement_aging.py", "tests/test_settlement_aging.py"],
    "DAD-3": ["src/business_ai_gateway/dad_rules.py", "tests/test_dad_reconciliation_rules.py"],
    "DAD-5": ["src/business_ai_gateway/dad_rules.py", "src/business_ai_gateway/external_evidence.py",
              "tests/test_dad_reconciliation_rules.py"],
    "EVID-1": ["src/business_ai_gateway/external_evidence.py", "tests/test_external_evidence.py",
               "src/business_ai_gateway/evidence_store.py", "tests/test_private_evidence_store.py",
               "src/business_ai_gateway/secret_files.py", "src/business_ai_gateway/evidence_index.py",
               "tests/test_evidence_approval_index.py", "scripts/evidence_intake.py",
               "tests/test_operator_evidence_intake.py"],
    "FR-A1": ["src/business_ai_gateway/auth.py", "tests/test_auth.py"],
    "FR-F1": ["src/business_ai_gateway/audit.py", "src/business_ai_gateway/server.py",
              "tests/test_server_audit.py", "tests/test_audit_provenance.py",
              "tests/test_audit_metric_contract.py"],
    "NFR-R2": ["src/business_ai_gateway/auth.py", "tests/test_auth_jwks_http.py",
               "scripts/fault_injection_runner.py", "tests/test_rsv_process_lifecycle.py"],
    "FR-A2": ["src/business_ai_gateway/registry.py"],
    "FR-A3": ["src/business_ai_gateway/registry.py"],
    "FR-B1": ["src/business_ai_gateway/registry.py"],
    "FR-B2": ["src/business_ai_gateway/secrets.py"],
    "FR-C1": ["src/business_ai_gateway/compatibility.py", "scripts/capability_registry_cli.py",
              "tests/test_capability_registry_cli.py", "tests/test_capability_registry_postgres.py"],
    "FR-C2": ["src/business_ai_gateway/registry.py", "scripts/capability_registry_cli.py",
              "tests/test_capability_registry_postgres.py"],
    "NFR-L1": ["vendor/intake.json", "scripts/assemble_release_evidence.py",
               "scripts/write_image_provenance.py", "tests/test_release_evidence_assembly.py"],
    "NFR-P1": ["src/business_ai_gateway/fanout.py", "tests/test_fanout.py"],
    "NFR-O1": ["src/business_ai_gateway/observability.py", "src/business_ai_gateway/audit.py",
               "tests/test_audit_metric_contract.py", "scripts/validate_prometheus.py"],
    "NFR-P2": ["scripts/performance_benchmark.py", "tests/test_measured_performance.py",
               "scripts/postgres_pool_benchmark.py", "tests/test_postgres_pool_benchmark.py"],
    "P6-SEC-1": ["src/business_ai_gateway/adapters/onec/rsv_bridge.py", "tests/test_rsv_bridge.py",
                 "tests/test_rsv_process_lifecycle.py", "scripts/rsv_process_harness.py",
                 "src/business_ai_gateway/secret_files.py", "tests/test_rsv_secret_privacy.py",
                 "tests/test_rsv_native_lifecycle.py", "scripts/rsv_native_lifecycle_harness.py",
                 "src/business_ai_gateway/adapters/onec/rsv_privacy.py", "tests/test_rsv_wire_limits.py"],
    "SCOPE-1": ["docs/SCOPE_FREEZE_BASELINE_2026-10-06.md", "tests/test_documentation_package.py",
                "scripts/engineering_checkpoint.py", "tests/test_engineering_checkpoint.py"],
    "TEST-FERMA-1": ["testbed/ferma_onec/package_loader.py", "testbed/ferma_onec/target_guard.py",
                     "testbed/ferma_onec/reconcile.py", "tests/test_ferma_package_boundary.py",
                     "tests/test_ferma_reconcile.py", "testbed/ferma_onec/exporter.py",
                     "tests/test_ferma_exporter.py"],
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
