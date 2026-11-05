"""Run the bounded TC001 preservation matrix and write its JSON evidence record.

Usage (from the repository root):
  .venv\\Scripts\\python.exe tests/phase2/run_tc001_r1_preservation.py

This executes deterministic offline pytest targets plus two local Node sidecar
tests. It never runs the product Gherkin scenario, a database, a migration, a
provider, a live 1C endpoint, or a production action.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import posixpath
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "57eb5b0696063237a43f5d1baf0a646278f5d832"
CHECKPOINT = "65883a5a83fbb369cbd32e5e31af3041f9d7c515"
LAST_TESTED_SOURCE = "6caf3d65e998c4d2e6698e2d6dc22d1ec7e64fc9"


PREDICATES: dict[str, dict[str, Any]] = {
    "P01": {"expected": "Baseline/checkpoint ancestry; every changed path has classification, rename/copy status, before/after runtime exports/entrypoints or explicit non-runtime N/A, and dependency propagation/exclusion rationale; unexplained R1-facing paths fail."},
    "P02": {"expected": "Supported compatibility metadata is positively recognized; unsupported, failed, fallback and malformed metadata cannot become proof or a fingerprint."},
    "P03": {"expected": "Valid source/company-bound semantic evidence is accepted; stale, cross-source, unacknowledged or malformed evidence is denied."},
    "P04": {"expected": "Normalized evidence accepts valid input and rejects bad scope, shape, MIME, size, duplicate/replay and private-scope violations; unsupported native formats stay denied."},
    "P05": {"expected": "OneC host remains pinned; redirects, encoded/oversized responses and sensitive request details fail safely."},
    "P06": {"expected": "COM bridge accepts loopback only; redirect, identity/binding mismatch, malformed and oversized responses fail closed."},
    "P07": {"expected": "RSV source/tool/secret/digest checks occur before launch or resolution; successful read-only operation is bounded and temporary config is cleaned."},
    "P08": {"expected": "Valid identity/scope works; bad signature, malformed JWKS, missing identity and under-scoped token fail closed."},
    "P09": {"expected": "Authorized requests reach the adapter only after ACL/rate/audit ordering; ACL or audit failure prevents dispatch."},
    "P10": {"expected": "Allowed admin access remains possible; restricted roles and foreign-scope mutations are denied; migration privilege shape is least-privilege by static test."},
    "P11": {"expected": "R1 MCP tools remain read-only, public custom routes are GET-only, dynamic admin routes are explicitly inventoried and authorization-wrapped (including POST/PATCH control-plane routes), OneC client has no write verbs, and production remains NO-GO/unapproved."},
    "P12": {"expected": "Start/end HEAD stable; clean relevant source and submodule; candidate package/test-support blobs match executed files; fresh no-cache candidate-bound image build and exact tested image ID/package provenance are verified."},
}


PYTEST_BY_PREDICATE: dict[str, list[str]] = {
    "P01": [
        "tests/phase2/test_tc001_r1_preservation.py::test_p01_rejects_unexplained_affected_path",
        "tests/phase2/test_tc001_r1_preservation.py::test_p01_rejects_empty_runtime_surface_or_dependency_propagation",
        "tests/phase2/test_tc001_r1_preservation.py::test_p01_accepts_explicit_non_runtime_dependency_exclusion",
    ],
    "P02": [
        "tests/test_compatibility.py::test_capability_detector_prefers_json_profile",
        "tests/test_compatibility.py::test_capability_detector_falls_back_to_atom_profile",
        "tests/test_compatibility.py::test_capability_detector_reports_unsupported_without_safe_route",
        "tests/test_compatibility.py::test_capability_detector_selects_only_explicitly_configured_fallback",
        "tests/test_compatibility.py::test_unimplemented_fallback_fails_closed_without_network_call",
        "tests/test_compatibility.py::test_capability_and_metadata_cache_expiry_observes_schema_drift",
        "tests/test_compatibility.py::test_html_metadata_response_gets_no_fingerprint",
    ],
    "P03": [
        "tests/test_semantic_profiles.py::test_validated_semantic_profile_requires_exact_source_company_schema_and_evidence",
        "tests/test_semantic_profiles.py::test_draft_or_unacknowledged_or_changed_metadata_profile_is_denied",
        "tests/test_semantic_profiles.py::test_old_or_cross_source_register_evidence_cannot_authorize_semantic_mapping",
        "tests/test_semantic_profiles.py::test_native_evidence_and_operator_cli_require_reconciliation_and_actor",
        "tests/test_semantic_profiles.py::test_account_turnovers_mapping_is_explicit_and_company_scoped",
        "tests/test_semantic_profiles.py::test_account_turnovers_mapping_refuses_guessed_entity_or_unscoped_call",
        "tests/test_semantic_profiles.py::test_settlement_balance_uses_validated_period_company_and_field_mapping",
    ],
    "P04": [
        "tests/test_external_evidence.py::test_normalized_evidence_is_immutable_bounded_and_public_manifest_minimized",
        "tests/test_external_evidence.py::test_malformed_or_cross_scope_facts_are_sanitized",
        "tests/test_external_evidence.py::test_all_frozen_evidence_classes_need_exact_confirmed_parser_profile",
        "tests/test_external_evidence.py::test_no_model_url_or_file_reference_is_accepted",
        "tests/test_external_evidence.py::test_missing_duplicate_oversized_or_mismatched_inputs_cannot_prove_pass",
        "tests/test_external_evidence.py::test_fact_count_limit_and_duplicate_headers_are_rejected",
        "tests/test_external_evidence.py::test_business_gate_does_not_invent_missing_evidence_or_accept_stale_scope",
        "tests/test_invoice_evidence.py::test_explicit_normalized_invoice_contract_preserves_exact_facts_and_private_safe_manifest",
        "tests/test_invoice_evidence.py::test_invalid_nested_schema_precision_scope_and_injected_policy_never_parse",
        "tests/test_invoice_evidence.py::test_invoice_uses_same_scope_approval_retention_and_digest_gate_as_csv",
        "tests/test_invoice_evidence.py::test_duplicate_json_key_and_oversized_payload_or_line_count_are_rejected",
        "tests/test_invoice_evidence.py::test_invoice_codec_does_not_auto_guess_utf16_or_native_document_encoding",
        "tests/test_invoice_evidence.py::test_invoice_store_wrong_mime_cannot_write_native_pdf_or_unapproved_json",
        "tests/test_private_evidence_store.py::test_real_disk_append_reopen_exact_provenance_and_private_os_permissions",
        "tests/test_private_evidence_store.py::test_path_traversal_url_or_invalid_opaque_reference_is_rejected",
        "tests/test_private_evidence_store.py::test_changed_truncated_oversized_or_uncommitted_evidence_never_reads",
        "tests/test_private_evidence_store.py::test_unconfirmed_cross_scope_and_revoked_retention_are_denied_after_reopen",
        "tests/test_private_evidence_store.py::test_native_formats_and_decompression_are_not_guessed_or_enabled",
        "tests/test_private_evidence_store.py::test_manifest_write_failure_returns_no_receipt_preserves_private_orphan_and_sanitizes_error",
        "tests/phase2/test_tc001_r1_preservation.py::test_tc001_r1_evidence_path_does_not_reach_r2_native_parser_or_vault",
    ],
    "P05": [
        "tests/test_onec_client.py::test_write_methods_do_not_exist",
        "tests/test_onec_client.py::test_upstream_http_error_does_not_expose_url_or_query_values",
        "tests/test_onec_client.py::test_upstream_network_error_is_mapped_without_chaining_request_url",
        "tests/test_onec_client.py::test_native_transport_rejects_encoding_before_unbounded_decompression",
        "tests/test_onec_client.py::test_url_is_pinned_to_registered_host",
        "tests/test_onec_client.py::test_metadata_probe_outage_is_sanitized_and_fails_closed",
        "tests/phase2/test_tc001_r1_preservation.py::test_tc001_onec_redirect_is_not_followed_or_leaked",
        "tests/test_connect_time_egress.py",
    ],
    "P06": ["tests/test_com_bridge_client.py"],
    "P07": ["tests/test_rsv_bridge.py", "tests/test_rsv_secret_privacy.py"],
    "P08": [
        "tests/test_auth.py::test_valid_token_resolves_subject_client_scope_and_groups",
        "tests/test_auth.py::test_invalid_or_under_scoped_tokens_are_denied",
        "tests/test_auth.py::test_bad_signature_is_denied",
        "tests/test_auth.py::test_jwks_validation_error_fails_closed",
        "tests/test_auth.py::test_missing_or_malformed_client_identity_fails_closed",
        "tests/test_auth.py::test_blank_primary_client_identity_does_not_fall_back",
        "tests/test_auth_jwks_http.py",
    ],
    "P09": [
        "tests/test_server_audit.py::test_source_health_success_is_audited_after_authorized_call",
        "tests/test_server_audit.py::test_durable_access_receipt_exists_before_adapter_dispatch",
        "tests/test_server_audit.py::test_pre_dispatch_audit_outage_is_sanitized_and_never_calls_adapter",
        "tests/test_server_audit.py::test_source_acl_denial_is_audited_and_stops_before_rate_limit",
        "tests/test_server_audit.py::test_redis_outage_is_audited_as_denial_and_never_calls_source",
    ],
    "P10": [
        "tests/test_admin_role_matrix.py::test_every_restricted_admin_endpoint_role_matrix",
        "tests/test_admin_role_matrix.py::test_exact_object_cross_source_mutations_are_denied_before_write",
        "tests/test_admin_api.py",
        "tests/test_admin_mutation_migration.py::test_admin_mutation_migration_is_additive_append_only_and_least_privilege",
        "tests/test_admin_platform_roles_migration.py::test_admin_platform_role_migration_is_additive_and_read_only_for_runtime",
    ],
    "P11": [
        "tests/phase2/test_tc001_r1_preservation.py::test_tc001_phase2_does_not_enable_r1_writes_or_production",
        "tests/phase2/test_tc001_r1_preservation.py::test_tc001_admin_dynamic_routes_are_classified_and_guarded",
        "tests/phase2/test_side_effect_boundary.py::test_read_only_plan_allowed_with_ordered_complete_coverage",
        "tests/phase2/test_side_effect_boundary.py::test_each_non_read_class_denies_with_its_code",
        "tests/phase2/test_side_effect_boundary.py::test_non_read_or_unknown_rights_disqualify",
        "tests/phase2/test_side_effect_boundary.py::test_read_only_rights_pass_including_normalised_spelling",
        "tests/phase2/test_side_effect_boundary.py::test_non_read_probe_denied_in_prod",
        "tests/phase2/test_side_effect_boundary.py::test_read_probe_allowed_in_prod_and_write_probe_denied_in_non_prod",
        "tests/phase2/test_release_migration.py::test_r1_schema_or_r1_object_class_is_unclassified_even_for_additive_or_destructive_kinds",
        "tests/phase2/test_g1_safety_requirements.py::test_migrations_are_isolated_from_r1_schema",
        "tests/phase2/test_g1_safety_requirements.py::test_unapproved_sql_does_not_claim_release_authority",
    ],
    "P12": [
        "tests/phase2/test_tc001_r1_preservation.py::test_p12_accepts_fully_candidate_bound_provenance",
        "tests/phase2/test_tc001_r1_preservation.py::test_p12_rejects_modified_selected_test_outside_tc001_module",
        "tests/phase2/test_tc001_r1_preservation.py::test_p12_rejects_matching_image_version_without_candidate_build_provenance",
        "tests/phase2/test_tc001_r1_preservation.py::test_p12_rejects_executable_or_dependency_worktree_delta",
        "tests/phase2/test_tc001_r1_preservation.py::test_evidence_output_rejects_path_outside_project_root",
    ],
    "STATUS_GUARD": ["tests/phase2/test_spec_catalog.py"],
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def selected_pytest_support_paths() -> list[str]:
    selected = {
        node.split("::", 1)[0]
        for nodes in PYTEST_BY_PREDICATE.values()
        for node in nodes
    }
    support = {
        name for name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "pytest.toml")
        if (ROOT / name).is_file()
    }
    test_module_paths = {}
    for path in (ROOT / "tests").rglob("*.py"):
        relative = path.relative_to(ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        test_module_paths[module] = path.relative_to(ROOT).as_posix()
    for selected_path in tuple(selected):
        path = (ROOT / selected_path).resolve()
        parent = path.parent
        while parent == ROOT or ROOT in parent.parents:
            conftest = parent / "conftest.py"
            if conftest.is_file():
                support.add(conftest.relative_to(ROOT).as_posix())
            if parent == ROOT:
                break
            parent = parent.parent
    pending = list(selected | support)
    inspected = set()
    while pending:
        relative_path = pending.pop()
        if relative_path in inspected:
            continue
        inspected.add(relative_path)
        path = ROOT / relative_path
        if not path.is_file() or path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        except (OSError, UnicodeError, SyntaxError):
            continue
        package_parts = list(Path(relative_path).with_suffix("").parts[:-1])
        for node in ast.walk(tree):
            imported_modules = []
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package_parts[: max(0, len(package_parts) - node.level + 1)]
                    if node.module:
                        base.extend(node.module.split("."))
                    imported_modules.append(".".join(base))
                    imported_modules.extend(
                        ".".join([*base, alias.name]) for alias in node.names
                        if alias.name != "*"
                    )
                elif node.module:
                    imported_modules.append(node.module)
                    imported_modules.extend(
                        f"{node.module}.{alias.name}" for alias in node.names
                        if alias.name != "*"
                    )
            for module in imported_modules:
                if module.startswith("tests.") and module in test_module_paths:
                    imported_path = test_module_paths[module]
                    if imported_path not in inspected:
                        support.add(imported_path)
                        pending.append(imported_path)
    return sorted(selected | support)


def git_clean_blob_oid(relative_path: str, content: bytes) -> str | None:
    """Return the blob OID Git would store after path-specific clean filters."""
    result = subprocess.run(
        ["git", "hash-object", f"--path={relative_path}", "--stdin"], check=False,
        cwd=ROOT,
        input=content,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("ascii", errors="replace").strip() or None


def candidate_blob_oid(ref: str, relative_path: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}:{relative_path}"], check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def candidate_path_blob_identity(
    ref: str, relative_path: str, content: bytes,
) -> dict[str, str | None]:
    """Identify working-tree bytes by the Git blob they clean to for this path."""
    return {
        "working_file_git_clean_blob_oid": git_clean_blob_oid(relative_path, content),
        "candidate_head_blob_oid": candidate_blob_oid(ref, relative_path),
    }


def candidate_blob_inventory_matches(artifact_hashes: dict[str, dict[str, Any]]) -> bool:
    return bool(artifact_hashes) and all(
        row.get("candidate_head_blob_oid") is not None
        and row.get("working_file_git_clean_blob_oid") == row.get("candidate_head_blob_oid")
        for row in artifact_hashes.values()
    )


def tool_version(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, check=False, cwd=ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        if argv and argv[0] == "corepack":
            result = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "corepack pnpm --version"], check=False,
                cwd=ROOT, capture_output=True, text=True,
            )
        else:
            raise
    return result.stdout.strip() if result.returncode == 0 else f"UNAVAILABLE(exit={result.returncode}): {result.stderr.strip()}"


def classify_path(path: str) -> dict[str, str]:
    if path in {
        "src/business_ai_gateway/dad_rules.py",
        "src/business_ai_gateway/dad_small_checks.py",
        "src/business_ai_gateway/financial_statements.py",
        "src/business_ai_gateway/invoice_rules.py",
    }:
        return {"class": "R1_internal_normalized_projection", "predicate": "P04", "rationale": "Candidate module docstrings identify internal normalized-fact/profile projections without source protocol/query integration; conditional exclusion from active R1 routes requires AST importer/entrypoint reconciliation recorded under P01."}
    if path.startswith(("src/business_ai_gateway/phase2/", "src/erp_mcp_private_writer/", "src/erp_mcp_s15/", "src/erp_mcp_s16/", "db/phase2/")):
        return {"class": "R2_isolated", "predicate": "P11", "rationale": "Separate Phase 2 package/path boundary; P01 records and requires no static import reachability from named R1 roots."}
    if path.startswith(("src/business_ai_gateway/testbed/", "testbed/", "testlane/")):
        return {"class": "test_fixture", "predicate": "P05/P06/P07", "rationale": "Synthetic fixture support only; not a production binding."}
    if path.startswith("onec_com_bridge/"):
        return {"class": "R1_shared_adapter", "predicate": "P06/P11", "rationale": "Standalone OneC COM bridge service reached by the R1 COM adapter; loopback/identity and no-write boundaries are covered under P06/P11."}
    if path.startswith("src/business_ai_gateway/adapters/onec/com_bridge"):
        return {"class": "R1_shared_adapter", "predicate": "P06/P11", "rationale": "COM loopback/response contract and read-only surface."}
    if path.startswith("src/business_ai_gateway/adapters/onec/rsv"):
        return {"class": "R1_shared_adapter", "predicate": "P07", "rationale": "Pinned read-only RSV process/secret boundary."}
    if path.startswith(("src/business_ai_gateway/adapters/onec/", "adapters/odata-sidecar/")):
        return {"class": "R1_shared_adapter", "predicate": "P05/P02", "rationale": "OneC source pinning, metadata and sidecar egress behavior."}
    if path.startswith("src/business_ai_gateway/admin_") or "/static/admin." in path:
        return {"class": "R1_admin_boundary", "predicate": "P10/P11", "rationale": "Restricted admin roles, mutation scope and privilege boundary."}
    if path.startswith("db/migrations/"):
        return {"class": "R1_database_contract", "predicate": "P10/P11", "rationale": "Static additive/least-privilege contract only; no migration execution."}
    if path.startswith("src/business_ai_gateway/"):
        if any(term in path for term in ("evidence", "invoice", "external_evidence")):
            pred = "P04"
            why = "Normalized external/invoice/private evidence scope and parsing boundary."
        elif any(term in path for term in ("auth.py", "principal.py", "company_scope.py", "business_policy.py", "registry.py")):
            pred = "P03/P08/P09"
            why = "Identity, company/source scope, semantic approval and policy boundary."
        elif any(term in path for term in ("compatibility.py", "metadata.py", "network_policy.py")):
            pred = "P02/P05"
            why = "Compatibility evidence and pinned-source network behavior."
        elif any(term in path for term in ("server.py", "app.py", "audit.py", "observability.py", "runtime.py", "tool_errors.py")):
            pred = "P09/P11"
            why = "Authorized dispatch/audit ordering and exposed read-only surface."
        else:
            pred = "P03/P09"
            why = "R1 shared/domain module inventoried; acceptance evidence is through scoped offline behavior checks and remains subject to independent review."
        return {"class": "R1_shared_runtime", "predicate": pred, "rationale": why}
    if path.startswith("scripts/"):
        if path.endswith(("assemble_release_evidence.py", "release_evidence_bundle.py")):
            return {"class": "release_evidence_tooling", "predicate": "P12", "rationale": "Exact revision evidence assembly; no live deployment is inferred."}
        return {"class": "offline_or_operational_tooling", "predicate": "P01/P11", "rationale": "Inventoried tooling; not treated as runtime product acceptance."}
    if path.startswith(("tests/", "features/")):
        return {"class": "test_or_acceptance_artifact", "predicate": "P02-P12", "rationale": "Test/specification artifact; its execution status is recorded separately and is not a product runtime path."}
    if path.startswith(("docs/", "reports/", "governance/", "decisions/", "core/")) or path.endswith((".md", ".rst", ".txt")):
        return {"class": "documentation_or_governance", "predicate": "P01/P12", "rationale": "Non-runtime documentation/decision evidence; inventoried but not treated as executable behavior."}
    if path.startswith("deploy/"):
        return {"class": "deployment_configuration", "predicate": "P11", "rationale": "Deployment/alert/runbook configuration; inventoried, with production execution explicitly excluded."}
    if path.startswith(".github/"):
        return {"class": "ci_workflow_configuration", "predicate": "P01/P12", "rationale": "CI workflow definition; no CI execution is inferred from the source diff."}
    if path.startswith(("adapters/", "db/", "src/", "testbed/")):
        return {"class": "unclassified", "predicate": "", "rationale": "Runtime path has no explicit boundary/dependency evidence; P01 remains open."}
    if path in {"LICENSE", "ERP_MCP_ENGINEERING_COMMAND_CENTER.html"}:
        return {"class": "project_metadata_or_static_report", "predicate": "P01/P12", "rationale": "License or static project status artifact, not executable product behavior."}
    if path.startswith(".env.") or path in {".dockerignore", ".gitattributes", ".gitignore"}:
        return {"class": "repository_environment_configuration", "predicate": "P01/P11", "rationale": "Container/environment/VCS configuration; runtime impact checked as configuration and not treated as R1 code."}
    if path in {"Dockerfile", "compose.development.yml", "compose.e2e.yml"}:
        return {"class": "container_configuration", "predicate": "P01/P11", "rationale": "Container orchestration/build configuration; no deployment or production action is run."}
    if path in {"pyproject.toml", "uv.lock", "package.json", "package-lock.json", "pytest.ini", "tox.ini", "Makefile"}:
        return {"class": "dependency_or_tool_configuration", "predicate": "P01/P12", "rationale": "Dependency or local tool configuration; no dependency resolution is inferred from repository contents."}
    if path == "requirements-runtime.lock":
        return {"class": "dependency_or_tool_configuration", "predicate": "P01/P12", "rationale": "Runtime dependency lockfile; dependency provenance is inventoried, not executed as live runtime proof."}
    if path.startswith("sbom/"):
        return {"class": "supply_chain_inventory", "predicate": "P01/P12", "rationale": "Software bill of materials artifact; metadata only, not executable product behavior."}
    if path in {"README.md", "CLAUDE.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md"}:
        return {"class": "project_documentation_or_policy", "predicate": "P01/P12", "rationale": "Project documentation/policy, not runtime product behavior."}
    if path.startswith((".codex/", ".claude/")):
        return {"class": "agent_workflow_configuration", "predicate": "P01/P12", "rationale": "Agent workflow metadata, not product runtime."}
    return {"class": "unclassified", "predicate": "", "rationale": "No specific evidence-backed rule for this path; P01 remains open until classified."}


def git_blob(ref: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], check=False, cwd=ROOT, capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def python_module_surface(content: bytes | None, path: str) -> dict[str, Any]:
    if content is None:
        return {"path": path, "exists": False, "exports": [], "entrypoints": [], "parse_error": None}
    try:
        tree = ast.parse(content.decode("utf-8"), filename=path)
    except (UnicodeError, SyntaxError) as exc:
        return {"path": path, "exists": True, "exports": [], "entrypoints": [], "parse_error": type(exc).__name__}
    names = set()
    declared_all = None
    entrypoints = set()
    registration_methods = {"tool", "custom_route", "route", "get", "post", "put", "patch", "delete", "websocket"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
            for decorator in node.decorator_list:
                func = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(func, ast.Attribute) and func.attr in registration_methods or isinstance(func, ast.Name) and func.id in registration_methods:
                    entrypoints.add(f"decorator:{node.name}:{ast.unparse(decorator)}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                target_names = [item.id for item in ast.walk(target) if isinstance(item, ast.Name)]
                if "__all__" in target_names:
                    value = node.value
                    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                        declared_all = sorted(
                            item.value for item in value.elts
                            if isinstance(item, ast.Constant) and isinstance(item.value, str)
                        )
                names.update(name for name in target_names if not name.startswith("_") and name != "__all__")
        elif isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
                if not (alias.asname or alias.name.split(".", 1)[0]).startswith("_")
            )
        elif isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname or alias.name for alias in node.names
                if alias.name != "*" and not (alias.asname or alias.name).startswith("_")
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in registration_methods:
            entrypoints.add(f"registration:{ast.unparse(node)}")
    exports = declared_all if declared_all is not None else sorted(names)
    return {"path": path, "exists": True, "exports": exports, "entrypoints": sorted(entrypoints), "parse_error": None}


def javascript_module_surface(content: bytes | None, path: str) -> dict[str, Any]:
    if content is None:
        return {"path": path, "exists": False, "exports": [], "entrypoints": [], "imports": []}
    text = content.decode("utf-8", errors="replace")
    exports = set(re.findall(
        r"(?m)^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
        text,
    ))
    for exported in re.findall(r"(?m)^\s*export\s*\{([^}]+)\}", text):
        for entry in exported.split(","):
            name = entry.strip().split(" as ", 1)[-1].strip()
            if name:
                exports.add(name)
    entrypoints = sorted(set(re.findall(
        r"(?m)^.*\b(?:custom_route|\.tool|\.route|\.get|\.post|\.put|\.patch|\.delete)\s*\([^\n]*",
        text,
    )))
    imports = sorted(set(re.findall(
        r"(?:from\s*|import\s*\(|require\s*\()(['\"])([^'\"]+)\1",
        text,
    )))
    import_paths = [item[1] for item in imports]
    return {
        "path": path, "exists": True, "exports": sorted(exports),
        "entrypoints": entrypoints, "imports": import_paths,
        "analysis_method": "bounded ECMAScript export/import/route registration source patterns; not a full parser",
    }


def changed_path_surface(path: str, candidate: str) -> dict[str, Any]:
    is_python_runtime = path.startswith("src/") and path.endswith(".py")
    is_javascript_runtime = (
        path.startswith(("src/", "adapters/")) and path.endswith((".js", ".mjs", ".cjs"))
    )
    if not is_python_runtime and not is_javascript_runtime:
        return {
            "surface_applicability": "not_applicable_non_runtime_python_module",
            "exports_before": [], "exports_after": [], "exports_added": [], "exports_removed": [],
            "entrypoints_before": [], "entrypoints_after": [], "entrypoints_added": [], "entrypoints_removed": [],
            "surface_parse_error": None,
        }
    surface = python_module_surface if is_python_runtime else javascript_module_surface
    before = surface(git_blob(BASELINE, path), path)
    after = surface(git_blob(candidate, path), path)
    before_exports, after_exports = set(before["exports"]), set(after["exports"])
    before_entrypoints, after_entrypoints = set(before["entrypoints"]), set(after["entrypoints"])
    return {
        "surface_applicability": "runtime_python_module" if is_python_runtime else "runtime_javascript_module",
        "exports_before": sorted(before_exports),
        "exports_after": sorted(after_exports),
        "exports_added": sorted(after_exports - before_exports),
        "exports_removed": sorted(before_exports - after_exports),
        "entrypoints_before": sorted(before_entrypoints),
        "entrypoints_after": sorted(after_entrypoints),
        "entrypoints_added": sorted(after_entrypoints - before_entrypoints),
        "entrypoints_removed": sorted(before_entrypoints - after_entrypoints),
        "surface_inventory_complete": not (before.get("parse_error") or after.get("parse_error")),
        "surface_completeness_basis": (
            "candidate and baseline module parsed; exports and registrations enumerated by the recorded bounded analyzer"
        ),
        "surface_parse_error": before.get("parse_error") or after.get("parse_error"),
        "imports_before": before.get("imports", []),
        "imports_after": after.get("imports", []),
        "import_specifiers_added": sorted(set(after.get("imports", [])) - set(before.get("imports", []))),
        "import_specifiers_removed": sorted(set(before.get("imports", [])) - set(after.get("imports", []))),
        "surface_analysis_method": after.get("analysis_method", "Python AST public binding/decorator/call scan"),
    }


def inventory(candidate: str) -> list[dict[str, Any]]:
    fields = git_bytes("diff", "--name-status", "-z", BASELINE, candidate, "--").decode("utf-8").split("\0")
    fields = [field for field in fields if field]
    output: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(fields):
        status = fields[cursor]
        cursor += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        changed_paths = fields[cursor:cursor + path_count]
        cursor += path_count
        rename_from = changed_paths[0] if status.startswith("R") and len(changed_paths) == 2 else None
        rename_to = changed_paths[1] if status.startswith("R") and len(changed_paths) == 2 else None
        copy_from = changed_paths[0] if status.startswith("C") and len(changed_paths) == 2 else None
        for index, path in enumerate(changed_paths):
            row = {
                "git_status": status,
                "path": path,
                "rename_status": "RENAMED" if rename_from is not None else "COPIED" if copy_from is not None else "NOT_RENAMED_OR_COPIED",
                "rename_from": rename_from,
                "rename_to": rename_to,
                "copy_from": copy_from,
                "copy_role": "source" if copy_from is not None and index == 0 else "destination" if copy_from is not None else None,
                **classify_path(path),
            }
            row.update(changed_path_surface(path, candidate))
            output.append(row)
    return output


def node_inventory_results(rows: list[dict[str, Any]]) -> list[str]:
    return [row["path"] for row in rows if row["class"] == "unclassified"]


def python_dependency_propagation_record(graph: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(graph)
    normalized["no_importers_or_dependent_entrypoints"] = not (
        normalized.get("direct_importers")
        or normalized.get("transitive_importers")
        or normalized.get("named_r1_roots_reaching_module")
    )
    return {
        "dependency_propagation_complete": True,
        "candidate_head_static_import_graph": normalized,
    }


def affected_path_inventory_complete(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row["class"] == "unclassified" or not row.get("rationale") or "dependency_propagation" not in row:
            return False
        if row.get("surface_applicability") in {"runtime_python_module", "runtime_javascript_module"}:
            required = (
                "exports_before", "exports_after", "exports_added", "exports_removed",
                "entrypoints_before", "entrypoints_after", "entrypoints_added", "entrypoints_removed",
                "dependency_propagation",
            )
            if (
                row.get("surface_parse_error")
                or any(key not in row for key in required)
                or row.get("surface_inventory_complete") is not True
                or not row.get("surface_completeness_basis")
            ):
                return False
            propagation = row.get("dependency_propagation")
            if (
                not isinstance(propagation, dict)
                or propagation.get("dependency_propagation_complete") is not True
            ):
                return False
            if row["surface_applicability"] == "runtime_python_module":
                graph = propagation.get("candidate_head_static_import_graph")
                if not isinstance(graph, dict) or graph.get("module_present_in_candidate") is not True:
                    return False
                importers = graph.get("direct_importers")
                transitive = graph.get("transitive_importers")
                roots = graph.get("named_r1_roots_reaching_module")
                if not all(isinstance(items, list) for items in (importers, transitive, roots)):
                    return False
                if not (importers or transitive or roots) and graph.get("no_importers_or_dependent_entrypoints") is not True:
                    return False
            else:
                imports = propagation.get("candidate_head_static_import_specifiers")
                importers = propagation.get("candidate_head_direct_importers")
                if not isinstance(imports, list) or not isinstance(importers, list):
                    return False
                if not (imports or importers) and propagation.get("no_imports_or_dependent_entrypoints") is not True:
                    return False
        elif row.get("surface_applicability") != "not_applicable_non_runtime_python_module":
            return False
        else:
            if any(row.get(key) != [] for key in (
                "exports_before", "exports_after", "exports_added", "exports_removed",
                "entrypoints_before", "entrypoints_after", "entrypoints_added", "entrypoints_removed",
            )):
                return False
            propagation = row.get("dependency_propagation")
            if row.get("path") in {
                "adapters/odata-sidecar/package.json",
                "adapters/odata-sidecar/package-lock.json",
            }:
                package_dependency = (
                    propagation.get("candidate_head_package_dependency")
                    if isinstance(propagation, dict) else None
                )
                if (
                    not isinstance(package_dependency, dict)
                    or package_dependency.get("package") != "undici"
                    or not isinstance(package_dependency.get("javascript_importers"), list)
                    or not package_dependency["javascript_importers"]
                    or package_dependency.get("dockerfile_inputs") != [
                        "adapters/odata-sidecar/Dockerfile"
                    ]
                    or package_dependency.get("dockerfile_copies_runtime_package") is not True
                ):
                    return False
                continue
            if (
                not isinstance(propagation, dict)
                or propagation.get("applicability") != "no Python runtime import edge; explicit path classification rationale applies"
                or not propagation.get("rationale")
            ):
                return False
    return True


def admin_route_inventory() -> dict[str, Any]:
    source_path = ROOT / "src/business_ai_gateway/admin_api.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_admin_routes"
    )
    route_assignment = next(
        node for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "routes" for target in node.targets)
    )
    api_loop = next(
        (node for node in function.body if isinstance(node, ast.For)
         and isinstance(node.iter, ast.Name) and node.iter.id == "routes"),
        None,
    )
    api_registration = None if api_loop is None else next(
        (node for node in ast.walk(api_loop)
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Call)
         and isinstance(node.func.func, ast.Attribute)
         and node.func.func.attr == "custom_route"),
        None,
    )
    api_wrapper = None if api_loop is None else next(
        (node for node in api_loop.body
         if isinstance(node, ast.AsyncFunctionDef) and node.name == "guarded"),
        None,
    )
    api_wrapper_return = None if api_wrapper is None else next(
        (node for node in api_wrapper.body if isinstance(node, ast.Return)), None
    )
    api_callback_is_guarded = (
        api_registration is not None
        and ast.unparse(api_registration) == "mcp.custom_route(path, methods=methods)(guarded)"
        and api_wrapper_return is not None
        and isinstance(api_wrapper_return.value, ast.Await)
        and ast.unparse(api_wrapper_return.value.value) == "api.serve(request, _handler)"
        and len(api_wrapper.args.args) > 1 and api_wrapper.args.args[-1].arg == "_handler"
        and any(isinstance(default, ast.Name) and default.id == "handler"
                for default in api_wrapper.args.defaults)
    )
    serve_method = next(
        (node for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == "AdminAPI"
         for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "serve"),
        None,
    )
    serve_try = None if serve_method is None else next(
        (node for node in serve_method.body if isinstance(node, ast.Try)), None
    )
    guard_assignment = None if serve_try is None else next(
        (node for node in serve_try.body if isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id == "guard" for target in node.targets)),
        None,
    )
    guard_expr = None if guard_assignment is None else guard_assignment.value
    csrf_mutations = False
    guard_blocks_handler_on_denial = False
    csrf_methods: list[str] = []
    if isinstance(guard_expr, ast.IfExp) and isinstance(guard_expr.test, ast.Compare):
        try:
            csrf_methods = sorted(ast.literal_eval(guard_expr.test.comparators[0]))
        except (ValueError, TypeError, IndexError):
            csrf_methods = []
        csrf_mutations = (
            isinstance(guard_expr.test.left, ast.Attribute)
            and ast.unparse(guard_expr.test.left) == "request.method"
            and len(guard_expr.test.ops) == 1 and isinstance(guard_expr.test.ops[0], ast.In)
            and set(csrf_methods) == {"POST", "PUT", "PATCH", "DELETE"}
            and isinstance(guard_expr.body, ast.Await)
            and isinstance(guard_expr.body.value, ast.Call)
            and isinstance(guard_expr.body.value.func, ast.Attribute)
            and guard_expr.body.value.func.attr == "csrf_guard"
            and isinstance(guard_expr.orelse, ast.Constant) and guard_expr.orelse.value is None
        )
    response_assignment = None if serve_try is None else next(
        (node for node in serve_try.body if isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id == "response" for target in node.targets)),
        None,
    )
    response_expr = None if response_assignment is None else response_assignment.value
    guard_blocks_handler_on_denial = (
        isinstance(response_expr, ast.IfExp)
        and ast.unparse(response_expr.test) == "guard is not None"
        and isinstance(response_expr.body, ast.Name) and response_expr.body.id == "guard"
        and isinstance(response_expr.orelse, ast.Await)
        and ast.unparse(response_expr.orelse.value) == "handler(request)"
    )
    api_guard_proven = api_callback_is_guarded and csrf_mutations and guard_blocks_handler_on_denial
    api_routes = [
        {"path": ast.literal_eval(row.elts[0]), "methods": ast.literal_eval(row.elts[1]), "handler": ast.unparse(row.elts[2]), "guard": "api.serve + conditional CSRF" if api_guard_proven else "UNVERIFIED"}
        for row in route_assignment.value.elts
    ]
    ui_direct = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Call):
            continue
        registrar = node.func
        if not isinstance(registrar.func, ast.Attribute) or registrar.func.attr != "custom_route":
            continue
        if not registrar.args or not isinstance(registrar.args[0], ast.Constant):
            continue
        if not isinstance(registrar.args[0].value, str):
            continue
        methods = next(kw.value for kw in registrar.keywords if kw.arg == "methods")
        ui_direct.append({"path": registrar.args[0].value, "methods": ast.literal_eval(methods), "handler": ast.unparse(node.args[0]), "guard": "direct_ui_handler"})
    browser_loop = next(
        node for node in function.body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Attribute) and node.test.attr == "admin_ui_enabled"
        for node in node.body if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple)
    )
    browser_registration = next(
        (node for node in ast.walk(browser_loop)
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Call)
         and isinstance(node.func.func, ast.Attribute)
         and node.func.func.attr == "custom_route"),
        None,
    )
    browser_wrapper = next(
        (node for node in browser_loop.body
         if isinstance(node, ast.AsyncFunctionDef) and node.name == "browser_route"),
        None,
    )
    browser_return = None if browser_wrapper is None else next(
        (node for node in browser_wrapper.body if isinstance(node, ast.Return)), None
    )
    browser_callback_is_guarded = (
        browser_registration is not None
        and ast.unparse(browser_registration) == "mcp.custom_route(path, methods=methods)(browser_route)"
        and browser_return is not None
        and isinstance(browser_return.value, ast.Await)
        and ast.unparse(browser_return.value.value) == "api.serve(request, _handler)"
        and len(browser_wrapper.args.args) > 1 and browser_wrapper.args.args[-1].arg == "_handler"
        and any(isinstance(default, ast.Name) and default.id == "handler"
                for default in browser_wrapper.args.defaults)
    )
    browser_guard_proven = browser_callback_is_guarded and csrf_mutations and guard_blocks_handler_on_denial
    browser_routes = [
        {"path": ast.literal_eval(row.elts[0]), "methods": ast.literal_eval(row.elts[1]), "handler": ast.unparse(row.elts[2]), "guard": "api.serve + conditional CSRF" if browser_guard_proven else "UNVERIFIED"}
        for row in browser_loop.iter.elts
    ]
    ui_direct_guarded = all(
        row["methods"] == ["GET"] for row in ui_direct
    )
    guard_proof = {
        "api_dynamic_registration_to_guard": api_guard_proven,
        "browser_registration_to_guard": browser_guard_proven,
        "csrf_mutation_methods": csrf_methods,
        "csrf_applies_to_exact_mutating_method_set": csrf_mutations,
        "csrf_denial_prevents_handler_dispatch": guard_blocks_handler_on_denial,
        "literal_ui_routes_get_only": ui_direct_guarded,
    }
    baseline_present = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE}:src/business_ai_gateway/admin_api.py"], check=False,
        cwd=ROOT, capture_output=True,
    ).returncode == 0
    return {
        "baseline_module_present": baseline_present,
        "candidate_module_path": "src/business_ai_gateway/admin_api.py",
        "candidate_module_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "candidate_dynamic_api_routes": api_routes,
        "candidate_admin_ui_literal_routes": ui_direct,
        "candidate_admin_ui_browser_routes": browser_routes,
        "candidate_admin_route_guard_proof": guard_proof,
        "comparison": "Baseline lacks admin_api.py; candidate adds the listed admin control-plane registrations. POST/PATCH are admin mutations and are authorized through AdminAPI.serve/CSRF and P10 role/scope tests; they are not classified as public R1 OneC document/register writers.",
    }


def static_predicates(rows: list[dict[str, str]], candidate: str) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    ancestry = {}
    for label, ref in (("baseline", BASELINE), ("checkpoint", CHECKPOINT)):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ref, candidate], check=False, cwd=ROOT,
            capture_output=True, text=True,
        )
        ancestry[label] = {"ref": ref, "is_ancestor": result.returncode == 0, "exit_code": result.returncode}
    unmapped = node_inventory_results(rows)
    dependency_inventory = python_dependency_inventory(candidate, rows)
    runtime_reconciliation_ok = dependency_inventory["changed_runtime_reconciliation_complete"]
    path_surface_complete = affected_path_inventory_complete(rows)
    p01_ok = (
        all(item["is_ancestor"] for item in ancestry.values())
        and not unmapped
        and dependency_inventory["complete"]
        and runtime_reconciliation_ok
        and path_surface_complete
    )
    baseline_admin_api = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE}:src/business_ai_gateway/admin_api.py"], check=False,
        cwd=ROOT, capture_output=True,
    ).returncode == 0
    results["P01"] = {
        "state": "PASS" if p01_ok else "NOT_RUN",
        "expected": PREDICATES["P01"]["expected"],
        "observed": f"Inventory contains {len(rows)} changed repository paths across the full baseline..candidate diff; all classified={not bool(unmapped)}. Dependency propagation is static AST import analysis, not a complete runtime call graph.",
        "ancestry": ancestry,
        "unclassified_paths": unmapped,
        "affected_path_inventory": rows,
        "dependency_inventory": dependency_inventory,
        "changed_runtime_reconciliation_complete": runtime_reconciliation_ok,
        "affected_path_surface_reconciliation_complete": path_surface_complete,
        "baseline_admin_api_present": baseline_admin_api,
    }
    route_comparison = admin_route_inventory()
    guard_proof = route_comparison["candidate_admin_route_guard_proof"]
    route_guard_proof_ok = (
        guard_proof["api_dynamic_registration_to_guard"]
        and guard_proof["browser_registration_to_guard"]
        and guard_proof["csrf_applies_to_exact_mutating_method_set"]
        and guard_proof["literal_ui_routes_get_only"]
        and all(row["guard"] != "UNVERIFIED"
                for row in route_comparison["candidate_dynamic_api_routes"])
        and all(row["guard"] != "UNVERIFIED"
                for row in route_comparison["candidate_admin_ui_browser_routes"])
    )
    results["P11"] = {
        "state": "PASS" if not baseline_admin_api and route_guard_proof_ok else "NOT_RUN",
        "expected": PREDICATES["P11"]["expected"],
        "observed": "Baseline admin_api absence, exact candidate registrations, handler closure forwarding, and the conditional CSRF method guard are derived from the source AST; registration guard proof must be complete.",
        "admin_route_comparison": route_comparison,
        "route_guard_proof_complete": route_guard_proof_ok,
    }

    tested_diff = git("diff", "--name-only", LAST_TESTED_SOURCE, candidate, "--")
    source_diff = [
        path for path in tested_diff.splitlines()
        if path.startswith(("src/", "adapters/", "db/", "scripts/", "testbed/"))
    ]
    results["P12"] = {
        "state": "NOT_RUN",
        "expected": PREDICATES["P12"]["expected"],
        "observed": "Exact candidate identity is evaluated after test execution using start/end HEAD, source worktree state, candidate dependency hashes, and actual image package version.",
        "candidate_full_sha": candidate,
        "last_tested_source_full_sha": LAST_TESTED_SOURCE,
        "later_source_paths": source_diff,
    }
    return results


def python_dependency_inventory(candidate: str, changed_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build bounded static imports for candidate Python modules; dynamic edges are not inferred."""
    candidate_paths = git("ls-tree", "-r", "--name-only", candidate, "--", "src", "adapters").splitlines()
    module_paths = {
        path[len("src/"):-3].replace("/", "."): path
        for path in candidate_paths if path.startswith("src/") and path.endswith(".py")
    }
    graph: dict[str, set[str]] = {module: set() for module in module_paths}
    parse_errors = []
    for module, relative_path in module_paths.items():
        try:
            source_bytes = git_blob(candidate, relative_path)
            if source_bytes is None:
                raise OSError("candidate source blob is unavailable")
            parsed = ast.parse(source_bytes.decode("utf-8"), filename=relative_path)
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append({"path": relative_path, "error": type(exc).__name__})
            continue
        package = module.split(".")[:-1]
        for node in ast.walk(parsed):
            target = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in module_paths:
                        graph[module].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    prefix = package[: max(0, len(package) - node.level + 1)]
                    target = ".".join([*prefix, *(node.module.split(".") if node.module else [])])
                else:
                    target = node.module
                if target in module_paths:
                    graph[module].add(target)
                for alias in node.names:
                    child = f"{target}.{alias.name}" if target else alias.name
                    if child in module_paths:
                        graph[module].add(child)

    roots = [
        "business_ai_gateway.adapters.onec.client",
        "business_ai_gateway.adapters.onec.com_bridge_client",
        "business_ai_gateway.adapters.onec.rsv_bridge",
        "business_ai_gateway.adapters.onec.sidecar_client",
        "business_ai_gateway.server",
        "business_ai_gateway.app",
        "business_ai_gateway.runtime",
        "business_ai_gateway.admin_api",
    ]
    missing_roots = [module for module in roots if module not in graph]
    roots = [module for module in roots if module in graph]
    reachable = set(roots)
    pending = list(roots)
    while pending:
        current = pending.pop()
        for dependency in graph.get(current, ()):
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    reverse_edges: dict[str, list[str]] = {module: [] for module in graph}
    for importer, dependencies in graph.items():
        for dependency in dependencies:
            reverse_edges.setdefault(dependency, []).append(importer)
    root_reachability: dict[str, set[str]] = {}
    for root in roots:
        seen = {root}
        pending = [root]
        while pending:
            current = pending.pop()
            for dependency in graph.get(current, ()):
                if dependency not in seen:
                    seen.add(dependency)
                    pending.append(dependency)
        root_reachability[root] = seen

    javascript_paths = {
        path for path in candidate_paths
        if path.startswith(("src/", "adapters/")) and path.endswith((".js", ".mjs", ".cjs"))
    }
    javascript_importers: dict[str, set[str]] = {path: set() for path in javascript_paths}
    javascript_external_importers: dict[str, set[str]] = {}
    for importer in javascript_paths:
        content = git_blob(candidate, importer)
        imports = javascript_module_surface(content, importer).get("imports", [])
        for specifier in imports:
            if not specifier.startswith("."):
                javascript_external_importers.setdefault(specifier, set()).add(importer)
                continue
            target_base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
            target_candidates = [target_base, *(target_base + suffix for suffix in (".mjs", ".js", ".cjs"))]
            target = next((item for item in target_candidates if item in javascript_paths), None)
            if target is not None:
                javascript_importers.setdefault(target, set()).add(importer)

    def propagation_for(module: str) -> dict[str, Any]:
        direct = sorted(reverse_edges.get(module, []))
        transitive = set(direct)
        pending_importers = list(direct)
        while pending_importers:
            importer = pending_importers.pop()
            for parent in reverse_edges.get(importer, []):
                if parent not in transitive:
                    transitive.add(parent)
                    pending_importers.append(parent)
        return {
            "module_present_in_candidate": module in graph,
            "direct_importers": direct,
            "transitive_importers": sorted(transitive),
            "named_r1_roots_reaching_module": sorted(
                root for root, reachable_from_root in root_reachability.items()
                if module in reachable_from_root
            ),
        }

    changed_path_propagation = {}
    for row in changed_rows:
        path = row["path"]
        if row.get("surface_applicability") == "runtime_python_module":
            module = path[len("src/"):-3].replace("/", ".")
            propagation = propagation_for(module)
            row["dependency_propagation"] = python_dependency_propagation_record(propagation)
            changed_path_propagation[path] = row["dependency_propagation"]
        elif row.get("surface_applicability") == "runtime_javascript_module":
            imports_after = row.get("imports_after", [])
            direct_importers = sorted(javascript_importers.get(path, set()))
            row["dependency_propagation"] = {
                "dependency_propagation_complete": True,
                "candidate_head_static_import_specifiers": imports_after,
                "candidate_head_direct_importers": direct_importers,
                "no_imports_or_dependent_entrypoints": not (imports_after or direct_importers),
                "limitation": "Bounded static ECMAScript import specifiers; dynamic imports and runtime loading are not inferred.",
            }
            changed_path_propagation[path] = row["dependency_propagation"]
        elif path in {
            "adapters/odata-sidecar/package.json", "adapters/odata-sidecar/package-lock.json",
        }:
            sidecar_dockerfile = git_blob(candidate, "adapters/odata-sidecar/Dockerfile") or b""
            row["dependency_propagation"] = {
                "candidate_head_package_dependency": {
                    "package": "undici",
                    "javascript_importers": sorted(javascript_external_importers.get("undici", set())),
                    "dockerfile_copies_runtime_package": b"node_modules/undici" in sidecar_dockerfile,
                    "dockerfile_inputs": ["adapters/odata-sidecar/Dockerfile"],
                },
            }
            changed_path_propagation[path] = row["dependency_propagation"]
        else:
            row["dependency_propagation"] = {
                "applicability": "no Python runtime import edge; explicit path classification rationale applies",
                "rationale": row.get("rationale"),
            }
            changed_path_propagation[path] = row["dependency_propagation"]
    internal_projection_exclusions = []
    for rel_path in (
        "src/business_ai_gateway/dad_rules.py",
        "src/business_ai_gateway/dad_small_checks.py",
        "src/business_ai_gateway/financial_statements.py",
        "src/business_ai_gateway/invoice_rules.py",
    ):
        module = rel_path[len("src/"):-3].replace("/", ".")
        try:
            content = git_blob(candidate, rel_path)
            doc = ast.get_docstring(ast.parse(content.decode("utf-8"))) if content is not None else None
        except (OSError, UnicodeError, SyntaxError):
            doc = None
        internal_projection_exclusions.append({
            "path": rel_path,
            "module_docstring": doc,
            "static_importers": sorted(reverse_edges.get(module, [])),
            "reachable_from_named_r1_roots": module in reachable,
            "disposition": "conditional exclusion: no static import path from selected R1 protocol/registration roots; normalized projection only per module docstring; dynamic registration/reflection is not excluded by this result",
        })
    internal_projection_exclusions_verified = all(
        item["module_docstring"] and not item["reachable_from_named_r1_roots"]
        and all(importer not in reachable for importer in item["static_importers"])
        for item in internal_projection_exclusions
    )
    isolated_phase2_modules = [
        module for module in reachable
        if module.startswith(("business_ai_gateway.phase2.", "erp_mcp_private_writer.", "erp_mcp_s15.", "erp_mcp_s16."))
    ]
    dynamic_loader_markers = ("importlib", "__import__(", "spec_from_file_location", "exec_module")
    dynamic_loader_hits = []
    for relative_path in module_paths.values():
        source_text = git_blob(candidate, relative_path).decode("utf-8")
        for marker in dynamic_loader_markers:
            if marker in source_text:
                dynamic_loader_hits.append({"path": relative_path, "marker": marker})
    dynamic_loader_scan_complete = not dynamic_loader_hits
    reconciliation = [
        {
            "path": row["path"],
            "class": row["class"],
            "module": row["path"][len("src/"):-3].replace("/", ".") if row["path"].startswith("src/") and row["path"].endswith(".py") else None,
            "reachable_from_named_r1_roots": (
                row["path"][len("src/"):-3].replace("/", ".") in reachable
                if row["path"].startswith("src/") and row["path"].endswith(".py")
                else None
            ),
            "disposition": "reachable via static import edge" if row["path"].startswith("src/") and row["path"].endswith(".py") and row["path"][len("src/"):-3].replace("/", ".") in reachable else row["rationale"],
            "exports_before": row.get("exports_before", []),
            "exports_after": row.get("exports_after", []),
            "entrypoints_before": row.get("entrypoints_before", []),
            "entrypoints_after": row.get("entrypoints_after", []),
            "dependency_propagation": row.get("dependency_propagation"),
        }
        for row in changed_rows
        if row["class"] in {"R1_shared_runtime", "R1_shared_adapter", "R1_admin_boundary", "R1_database_contract", "R1_internal_normalized_projection"}
    ]
    unresolved_runtime = [
        row["path"] for row in reconciliation
        if row["class"] == "R1_shared_runtime" and row["reachable_from_named_r1_roots"] is False
    ]
    return {
        "method": "AST import edges for tracked candidate src/**/*.py; breadth-first reachability from OneC adapter modules.",
        "limitation": "Static imports only; does not model dynamic imports, framework registration, reflection, runtime configuration, or every call/data-flow edge. No complete runtime call-graph claim is made.",
        "complete": not parse_errors and not missing_roots and internal_projection_exclusions_verified and dynamic_loader_scan_complete and not isolated_phase2_modules and affected_path_inventory_complete(changed_rows),
        "parse_errors": parse_errors,
        "missing_roots": missing_roots,
        "roots": sorted(roots),
        "reachable_modules": sorted(reachable),
        "changed_runtime_reconciliation": reconciliation,
        "affected_path_dependency_propagation": changed_path_propagation,
        "conditional_internal_projection_exclusions": internal_projection_exclusions,
        "conditional_internal_projection_exclusions_verified": internal_projection_exclusions_verified,
        "dynamic_loader_scan": {
            "searched_markers": list(dynamic_loader_markers),
            "hits": dynamic_loader_hits,
            "complete_for_these_markers_only": dynamic_loader_scan_complete,
            "limitation": "String-marker source scan supplements the static AST import graph; it cannot prove absence of all dynamic registration, reflection, generated code, or runtime configuration.",
        },
        "isolated_phase2_reachable_from_r1_roots": isolated_phase2_modules,
        "unresolved_r1_runtime_paths": unresolved_runtime,
        "changed_runtime_reconciliation_complete": not unresolved_runtime and affected_path_inventory_complete(changed_rows),
        "affected_path_surface_reconciliation_complete": affected_path_inventory_complete(changed_rows),
        "edges": {module: sorted(graph[module]) for module in sorted(reachable)},
    }


def test_case_rows(xml_path: Path) -> list[dict[str, str]]:
    root = ET.parse(xml_path).getroot()
    rows: list[dict[str, str]] = []
    for case in root.iter("testcase"):
        props = case.find("properties")
        nodeid = ""
        if props is not None:
            for prop in props.findall("property"):
                if prop.get("name") == "nodeid":
                    nodeid = prop.get("value", "")
                    break
        status = "passed"
        if case.find("failure") is not None:
            status = "failed"
        elif case.find("error") is not None:
            status = "error"
        elif case.find("skipped") is not None:
            status = "skipped"
        rows.append({"nodeid": nodeid or f"{case.get('classname')}::{case.get('name')}", "status": status})
    return rows


def matches(requested: str, nodeid: str) -> bool:
    def normalize(value: str) -> str:
        value = value.replace("\\", "/")
        return value.removesuffix(".py").replace("/", ".")

    wanted = "::".join(normalize(part) for part in requested.split("::"))
    actual = "::".join(normalize(part) for part in nodeid.split("::"))
    if "::" not in requested:
        return actual.startswith(wanted + "::")
    return actual == wanted or actual.startswith(wanted + "[")


def run_pytest() -> dict[str, Any]:
    all_requested = list(dict.fromkeys(node for nodes in PYTEST_BY_PREDICATE.values() for node in nodes))
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = "src" + (os.pathsep + existing if existing else "")
    with tempfile.TemporaryDirectory(prefix="tc001-junit-") as temp_dir:
        xml_path = Path(temp_dir) / "tc001.xml"
        pytest_base_temp = Path(temp_dir) / "pytest-basetemp"
        argv = [
            sys.executable, "-m", "pytest", "-q",
            f"--junitxml={xml_path}", f"--basetemp={pytest_base_temp}",
            *all_requested,
        ]
        started = time.perf_counter()
        result = subprocess.run(argv, check=False, cwd=ROOT, env=env, capture_output=True, text=True)
        duration = round(time.perf_counter() - started, 3)
        cases = test_case_rows(xml_path) if xml_path.is_file() else []
    by_predicate: dict[str, dict[str, Any]] = {}
    for predicate, requested in PYTEST_BY_PREDICATE.items():
        selected = [case for case in cases if any(matches(item, case["nodeid"]) for item in requested)]
        not_found = [item for item in requested if not any(matches(item, case["nodeid"]) for case in cases)]
        passed = sum(case["status"] == "passed" for case in selected)
        failed = sum(case["status"] in {"failed", "error"} for case in selected)
        skipped = sum(case["status"] == "skipped" for case in selected)
        ok = result.returncode == 0 and bool(selected) and not not_found and not failed and skipped == 0
        deselected_match = __import__("re").search(r"\b(\d+) deselected\b", result.stdout)
        deselected = int(deselected_match.group(1)) if deselected_match else 0
        by_predicate[predicate] = {
            "state": "PASS" if ok else "NOT_RUN",
            "expected": PREDICATES[predicate]["expected"] if predicate in PREDICATES else "All catalog metadata tests pass and product cases remain NOT_RUN.",
            "observed": f"{passed} passed, {failed} failed/error, {skipped} skipped; missing requested nodes={len(not_found)}.",
            "requested_nodes": requested,
            "executed_nodes": [case["nodeid"] for case in selected],
            "missing_nodes": not_found,
            "counts": {"passed": passed, "failed_or_error": failed, "skipped": skipped, "deselected": deselected},
        }
    return {
        "argv": argv,
        "cwd": str(ROOT),
        "environment": {"PYTHONPATH": env["PYTHONPATH"]},
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "case_count": len(cases),
        "case_rows": cases,
        "predicates": by_predicate,
    }


def sidecar_dependency_provenance(candidate: str) -> dict[str, Any]:
    manifest_relative_path = "adapters/odata-sidecar/package.json"
    lock_relative_path = "adapters/odata-sidecar/package-lock.json"
    manifest_path = ROOT / manifest_relative_path
    lock_path = ROOT / lock_relative_path
    manifest_bytes = manifest_path.read_bytes()
    lock_bytes = lock_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    lock = json.loads(lock_bytes)
    candidate_manifest_result = subprocess.run(
        ["git", "show", f"{candidate}:adapters/odata-sidecar/package.json"], check=False,
        cwd=ROOT, capture_output=True,
    )
    candidate_lock_result = subprocess.run(
        ["git", "show", f"{candidate}:adapters/odata-sidecar/package-lock.json"], check=False,
        cwd=ROOT, capture_output=True,
    )
    candidate_manifest = (
        json.loads(candidate_manifest_result.stdout)
        if candidate_manifest_result.returncode == 0 else None
    )
    candidate_lock = (
        json.loads(candidate_lock_result.stdout)
        if candidate_lock_result.returncode == 0 else None
    )
    manifest_blob_identity = candidate_path_blob_identity(
        candidate, manifest_relative_path, manifest_bytes,
    )
    lock_blob_identity = candidate_path_blob_identity(
        candidate, lock_relative_path, lock_bytes,
    )
    return {
        "manifest_path": "adapters/odata-sidecar/package.json",
        "lockfile_path": "adapters/odata-sidecar/package-lock.json",
        "working_tree_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "working_tree_lockfile_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "working_tree_manifest_undici": manifest.get("dependencies", {}).get("undici"),
        "working_tree_lock_root_undici": lock.get("packages", {}).get("", {}).get("dependencies", {}).get("undici"),
        "working_tree_lock_resolved_undici": lock.get("packages", {}).get("node_modules/undici", {}).get("version"),
        "candidate_head_manifest_sha256": hashlib.sha256(candidate_manifest_result.stdout).hexdigest() if candidate_manifest is not None else None,
        "candidate_head_lockfile_sha256": hashlib.sha256(candidate_lock_result.stdout).hexdigest() if candidate_lock is not None else None,
        "working_tree_manifest_git_clean_blob_oid": manifest_blob_identity["working_file_git_clean_blob_oid"],
        "candidate_head_manifest_blob_oid": manifest_blob_identity["candidate_head_blob_oid"],
        "working_tree_lockfile_git_clean_blob_oid": lock_blob_identity["working_file_git_clean_blob_oid"],
        "candidate_head_lockfile_blob_oid": lock_blob_identity["candidate_head_blob_oid"],
        "candidate_head_manifest_undici": candidate_manifest.get("dependencies", {}).get("undici") if candidate_manifest is not None else None,
        "candidate_head_lock_root_undici": candidate_lock.get("packages", {}).get("", {}).get("dependencies", {}).get("undici") if candidate_lock is not None else None,
        "candidate_head_lock_resolved_undici": candidate_lock.get("packages", {}).get("node_modules/undici", {}).get("version") if candidate_lock is not None else None,
        "working_tree_matches_candidate_head": (
            candidate_manifest is not None and candidate_lock is not None
            and candidate_blob_inventory_matches({
                manifest_relative_path: manifest_blob_identity,
                lock_relative_path: lock_blob_identity,
            })
        ),
        "candidate_head_commit": candidate,
    }


def p12_gate_checks(
    *,
    candidate: str,
    head_after_run: str,
    source_worktree_clean: bool,
    dependency_hashes_match_candidate: bool,
    image_undici_version: str | None,
    candidate_undici_version: str | None,
    selected_test_hashes_match_candidate: bool,
    tested_image_id: str | None,
    image_build: dict[str, Any],
) -> dict[str, bool]:
    build_provenance = image_build or {}
    build_succeeded = build_provenance.get("build_exit_code") == 0
    build_candidate_matches = build_provenance.get("candidate_head") == candidate
    build_inputs_clean = build_provenance.get("build_inputs_clean") is True
    build_label_matches = build_provenance.get("candidate_label") == candidate
    build_image_matches_tested = (
        build_provenance.get("image_id") is not None
        and build_provenance.get("image_id") == tested_image_id
    )
    submodule_matches_candidate = (
        build_provenance.get("submodule_clean_at_candidate_gitlink") is True
        and build_provenance.get("candidate_submodule_gitlink_sha")
        == build_provenance.get("submodule_worktree_head")
    )
    return {
        "head_unchanged_through_run": head_after_run == candidate,
        "source_worktree_clean_against_candidate": source_worktree_clean,
        "manifest_and_lock_hashes_match_candidate": dependency_hashes_match_candidate,
        "image_installed_undici_matches_candidate": (
            candidate_undici_version is not None
            and image_undici_version == candidate_undici_version
        ),
        "selected_test_and_support_hashes_match_candidate": selected_test_hashes_match_candidate,
        "fresh_image_build_succeeded_this_run": build_succeeded,
        "image_build_candidate_head_matches": build_candidate_matches,
        "image_build_inputs_are_clean_candidate_archive": build_inputs_clean,
        "image_candidate_label_matches": build_label_matches,
        "tested_image_is_exact_built_image": build_image_matches_tested,
        "dockerfile_submodule_matches_candidate_gitlink": submodule_matches_candidate,
    }


def p12_run_provenance(
    candidate: str,
    head_after_run: str,
    dependency_provenance: dict[str, Any],
    node_result: dict[str, Any],
    source_worktree_before: list[str],
    verifier_negative_tests_pass: bool,
) -> dict[str, Any]:
    source_worktree = git(
        "status", "--porcelain", "--", "src", "adapters", "db", "scripts", "testbed",
        "vendor/reference/1c-odata-v3",
    ).splitlines()
    excluded_node_modules = [
        line for line in source_worktree
        if line.startswith("?? adapters/odata-sidecar/node_modules/")
    ]
    relevant_source_worktree = [
        line for line in source_worktree if line not in excluded_node_modules
    ]
    excluded_before_node_modules = [
        line for line in source_worktree_before
        if line.startswith("?? adapters/odata-sidecar/node_modules/")
    ]
    relevant_source_worktree_before = [
        line for line in source_worktree_before if line not in excluded_before_node_modules
    ]
    candidate_lock_version = dependency_provenance["candidate_head_lock_resolved_undici"]
    image_matches_candidate = (
        node_result["image_id"] is not None
        and node_result["dependency_probe_exit_code"] == 0
        and node_result["installed_undici_version"] == candidate_lock_version
    )
    test_artifact_paths = selected_pytest_support_paths()
    test_artifact_paths = sorted(set(test_artifact_paths) | {
        "tests/phase2/run_tc001_r1_preservation.py",
    })
    test_artifact_hashes = {}
    for relative_path in test_artifact_paths:
        source_path = ROOT / relative_path
        working_content = source_path.read_bytes() if source_path.is_file() else None
        current_hash = hashlib.sha256(working_content).hexdigest() if working_content is not None else None
        candidate_hash = sha256_at(candidate, relative_path)
        working_blob_oid = (
            git_clean_blob_oid(relative_path, working_content)
            if working_content is not None else None
        )
        candidate_oid = candidate_blob_oid(candidate, relative_path)
        test_artifact_hashes[relative_path] = {
            "path": relative_path,
            "working_file_sha256": current_hash,
            "candidate_head_blob_sha256": candidate_hash,
            "working_file_git_clean_blob_oid": working_blob_oid,
            "candidate_head_blob_oid": candidate_oid,
            "working_file_matches_candidate_blob": candidate_oid is not None and working_blob_oid == candidate_oid,
        }
    test_artifacts_match = candidate_blob_inventory_matches(test_artifact_hashes)
    head_unchanged = head_after_run == candidate
    source_clean = not relevant_source_worktree and not relevant_source_worktree_before
    manifest_and_lock_match = dependency_provenance["working_tree_matches_candidate_head"]
    build_provenance = node_result.get("image_build_provenance", {})
    p12_checks = p12_gate_checks(
        candidate=candidate,
        head_after_run=head_after_run,
        source_worktree_clean=source_clean,
        dependency_hashes_match_candidate=manifest_and_lock_match,
        image_undici_version=node_result["installed_undici_version"],
        candidate_undici_version=candidate_lock_version,
        selected_test_hashes_match_candidate=test_artifacts_match,
        tested_image_id=node_result["image_id"],
        image_build=build_provenance,
    )
    p12_checks["candidate_binding_negative_tests_pass"] = verifier_negative_tests_pass
    p12_ok = all(p12_checks.values())
    return {
        "state": "PASS" if p12_ok else "NOT_RUN",
        "expected": PREDICATES["P12"]["expected"],
        "observed": (
            "HEAD remained unchanged; relevant source worktree is clean except generated sidecar node_modules; "
            "manifest/lock and selected test/support blobs match candidate; fresh no-cache build came from candidate archive and the exact tested image is bound to candidate."
            if p12_ok else
            "Exact candidate binding is not proven: check HEAD stability, relevant source cleanliness, candidate manifest/lock hashes, actual image-installed undici, and candidate blob hashes for the executed test module and runner."
        ),
        "candidate_full_sha": candidate,
        "head_after_run": head_after_run,
        "head_unchanged_through_run": head_unchanged,
        "source_worktree_porcelain": source_worktree,
        "source_worktree_porcelain_before": source_worktree_before,
        "source_worktree_after_exact_node_modules_exclusion": relevant_source_worktree,
        "source_worktree_before_after_exact_node_modules_exclusion": relevant_source_worktree_before,
        "source_worktree_clean_against_candidate": source_clean,
        "excluded_generated_node_modules_paths": excluded_node_modules,
        "excluded_generated_node_modules_paths_before": excluded_before_node_modules,
        "sidecar_dependency_source_provenance": dependency_provenance,
        "manifest_and_lock_hashes_match_candidate": manifest_and_lock_match,
        "candidate_lock_undici_version": candidate_lock_version,
        "image_installed_undici_version": node_result["installed_undici_version"],
        "image_installed_undici_matches_candidate": image_matches_candidate,
        "test_artifact_identity": test_artifact_hashes,
        "test_artifact_hashes_match_candidate_blobs": test_artifacts_match,
        "image_build_provenance": build_provenance,
        "invariant_checks": p12_checks,
        "candidate_binding_test_state": "PASS" if verifier_negative_tests_pass else "NOT_RUN",
        "last_tested_source_full_sha": LAST_TESTED_SOURCE,
        "later_source_paths_since_last_tested": git(
            "diff", "--name-only", LAST_TESTED_SOURCE, candidate, "--"
        ).splitlines(),
    }


def build_candidate_image(candidate: str) -> dict[str, Any]:
    root_context_paths = [".dockerignore", "adapters/odata-sidecar"]
    root_archive_argv = ["git", "archive", "--format=tar", candidate, *root_context_paths]
    root_archive = subprocess.run(root_archive_argv, check=False, cwd=ROOT, capture_output=True)
    submodule_path = "vendor/reference/1c-odata-v3"
    gitlink_result = subprocess.run(
        ["git", "ls-tree", candidate, submodule_path], check=False, cwd=ROOT,
        capture_output=True, text=True,
    )
    gitlink_fields = gitlink_result.stdout.strip().split()
    gitlink_sha = gitlink_fields[2] if len(gitlink_fields) >= 3 and gitlink_fields[0] == "160000" else None
    submodule_head_result = subprocess.run(
        ["git", "-C", submodule_path, "rev-parse", "HEAD"], check=False, cwd=ROOT,
        capture_output=True, text=True,
    )
    submodule_head = submodule_head_result.stdout.strip() if submodule_head_result.returncode == 0 else None
    submodule_status_result = subprocess.run(
        ["git", "-C", submodule_path, "status", "--porcelain", "--untracked-files=all"], check=False,
        cwd=ROOT, capture_output=True, text=True,
    )
    submodule_status = submodule_status_result.stdout.splitlines() if submodule_status_result.returncode == 0 else [submodule_status_result.stderr.strip()]
    submodule_clean_at_gitlink = (
        gitlink_sha is not None and submodule_head == gitlink_sha
        and submodule_status_result.returncode == 0 and not submodule_status
    )
    submodule_archive_argv = (
        ["git", "-C", submodule_path, "archive", "--format=tar", gitlink_sha]
        if gitlink_sha is not None else None
    )
    submodule_archive = (
        subprocess.run(submodule_archive_argv, check=False, cwd=ROOT, capture_output=True)
        if submodule_archive_argv is not None and submodule_clean_at_gitlink else None
    )
    image_tag = f"erp-mcp-tc001-sidecar:{candidate[:12]}-{time.time_ns()}"
    build_argv: list[str] | None = None
    build = None
    archive_ready = (
        root_archive.returncode == 0 and submodule_clean_at_gitlink
        and submodule_archive is not None and submodule_archive.returncode == 0
    )
    context_dir = None
    if archive_ready:
        with tempfile.TemporaryDirectory(
            prefix=".tc001-candidate-context-", dir=ROOT / "tests/phase2"
        ) as context_dir:
            with tarfile.open(fileobj=io.BytesIO(root_archive.stdout), mode="r:") as archive_stream:
                archive_stream.extractall(context_dir)
            vendor_context = Path(context_dir) / submodule_path
            vendor_context.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(submodule_archive.stdout), mode="r:") as archive_stream:
                archive_stream.extractall(vendor_context)
            build_argv = [
                "docker", "build", "--no-cache", "--tag", image_tag,
                "--label", f"com.erp-mcp.tc001.candidate_sha={candidate}",
                "--file", str(Path(context_dir) / "adapters/odata-sidecar/Dockerfile"), context_dir,
            ]
            build = subprocess.run(build_argv, check=False, cwd=ROOT, capture_output=True)
    root_archive_ok = root_archive.returncode == 0
    submodule_archive_ok = submodule_archive is not None and submodule_archive.returncode == 0
    return {
        "candidate_head": candidate,
        "build_context_method": "candidate root git archive plus verified submodule gitlink archive, extracted into isolated context",
        "root_build_context_paths": root_context_paths,
        "root_context_archive_argv": root_archive_argv,
        "root_context_archive_exit_code": root_archive.returncode,
        "root_context_archive_sha256": hashlib.sha256(root_archive.stdout).hexdigest() if root_archive_ok else None,
        "submodule_path": submodule_path,
        "candidate_submodule_gitlink_sha": gitlink_sha,
        "submodule_worktree_head": submodule_head,
        "submodule_worktree_status": submodule_status,
        "submodule_clean_at_candidate_gitlink": submodule_clean_at_gitlink,
        "submodule_context_archive_argv": submodule_archive_argv,
        "submodule_context_archive_exit_code": submodule_archive.returncode if submodule_archive is not None else None,
        "submodule_context_archive_sha256": hashlib.sha256(submodule_archive.stdout).hexdigest() if submodule_archive_ok else None,
        "build_context_clean_candidate": archive_ready,
        "build_inputs_clean": archive_ready,
        "build_argv": build_argv,
        "build_exit_code": build.returncode if build is not None else None,
        "build_stdout": build.stdout.decode("utf-8", errors="replace") if build is not None else "",
        "build_stderr": build.stderr.decode("utf-8", errors="replace") if build is not None else (root_archive.stderr.decode("utf-8", errors="replace") or submodule_archive.stderr.decode("utf-8", errors="replace") if submodule_archive is not None else "Candidate Docker context could not be assembled from the expected root/submodule commits."),
        "configured_image_tag": image_tag,
        "image_id": None,
        "repo_digests": [],
        "candidate_label": None,
        "image_inspect_argv": None,
        "image_inspect_exit_code": None,
    }


def run_node_sidecar(candidate: str, expected_undici_version: str | None) -> dict[str, Any]:
    argv = [
        "docker", "run", "--rm", "--network", "none", "--entrypoint", "node",
        "<built-image-id>", "--test", "packages/client/sidecar/egress.test.mjs",
        "packages/client/sidecar/server.test.mjs",
    ]
    started = time.perf_counter()
    try:
        image_build = build_candidate_image(candidate)
        image_tag = image_build["configured_image_tag"]
        if image_build["build_exit_code"] != 0:
            return {
                "argv": argv,
                "cwd": str(ROOT),
                "exit_code": image_build["build_exit_code"],
                "duration_seconds": round(time.perf_counter() - started, 3),
                "stdout": "",
                "stderr": image_build["build_stderr"],
                "state": "NOT_RUN",
                "test_run": False,
                "dependency_probe_argv": None,
                "dependency_probe_exit_code": None,
                "dependency_probe_stdout": "",
                "dependency_probe_stderr": "",
                "installed_undici_version": None,
                "expected_locked_undici_version": expected_undici_version,
                "installed_undici_matches_working_tree_lock": False,
                "image_inspect_argv": None,
                "image_inspect_exit_code": None,
                "configured_image_tag": image_tag,
                "image_id": None,
                "repo_digests": [],
                "image_digest": None,
                "image_digest_source": "unavailable; candidate image build failed",
                "image_build_provenance": image_build,
                "network": "none",
            }
        inspect_result = subprocess.run(
            ["docker", "image", "inspect", image_tag], check=False, cwd=ROOT,
            capture_output=True, text=True,
        )
        if inspect_result.returncode != 0:
            return {
                "argv": argv,
                "cwd": str(ROOT),
                "exit_code": inspect_result.returncode,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "stdout": "",
                "stderr": inspect_result.stderr or inspect_result.stdout,
                "state": "NOT_RUN",
                "test_run": False,
                "dependency_probe_argv": None,
                "dependency_probe_exit_code": None,
                "dependency_probe_stdout": "",
                "dependency_probe_stderr": "",
                "installed_undici_version": None,
                "expected_locked_undici_version": expected_undici_version,
                "installed_undici_matches_working_tree_lock": False,
                "image_inspect_argv": ["docker", "image", "inspect", image_tag],
                "image_inspect_exit_code": inspect_result.returncode,
                "configured_image_tag": image_tag,
                "image_id": None,
                "repo_digests": [],
                "image_digest": None,
                "image_digest_source": "unavailable; docker image inspect failed",
                "image_build_provenance": image_build,
                "network": "none",
            }
        inspected = json.loads(inspect_result.stdout)
        if not isinstance(inspected, list) or not inspected or not inspected[0].get("Id"):
            raise ValueError("docker image inspect returned no immutable image ID")
        image = inspected[0]
        image_id = image["Id"]
        repo_digests = image.get("RepoDigests") or []
        image_build["image_id"] = image_id
        image_build["repo_digests"] = repo_digests
        image_build["image_inspect_argv"] = ["docker", "image", "inspect", image_tag]
        image_build["image_inspect_exit_code"] = inspect_result.returncode
        image_build["candidate_label"] = (image.get("Config", {}).get("Labels") or {}).get(
            "com.erp-mcp.tc001.candidate_sha"
        )
        argv[argv.index("<built-image-id>")] = image_id
        dependency_probe_argv = [
            "docker", "run", "--rm", "--network", "none", "--entrypoint", "node",
            image_id, "-e",
            "process.stdout.write(JSON.stringify(require('/app/node_modules/undici/package.json').version))",
        ]
        dependency_probe = subprocess.run(
            dependency_probe_argv, check=False, cwd=ROOT, capture_output=True, text=True,
        )
        installed_undici_version = None
        if dependency_probe.returncode == 0:
            try:
                installed_undici_version = json.loads(dependency_probe.stdout.strip())
            except (json.JSONDecodeError, TypeError):
                installed_undici_version = None
        dependency_version_matches = (
            installed_undici_version is not None
            and expected_undici_version is not None
            and installed_undici_version == expected_undici_version
        )
        result = subprocess.run(argv, check=False, cwd=ROOT, capture_output=True, text=True)
        test_exit_ok = result.returncode == 0
        return {
            "argv": argv,
            "cwd": str(ROOT),
            "exit_code": result.returncode,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "state": "PASS" if test_exit_ok and dependency_version_matches else "FAIL" if not test_exit_ok else "NOT_RUN",
            "test_run": True,
            "test_state": "PASS" if test_exit_ok else "FAIL",
            "dependency_probe_argv": dependency_probe_argv,
            "dependency_probe_exit_code": dependency_probe.returncode,
            "dependency_probe_stdout": dependency_probe.stdout,
            "dependency_probe_stderr": dependency_probe.stderr,
            "installed_undici_version": installed_undici_version,
            "expected_locked_undici_version": expected_undici_version,
            "installed_undici_matches_working_tree_lock": dependency_version_matches,
            "image_inspect_argv": ["docker", "image", "inspect", image_tag],
            "image_inspect_exit_code": inspect_result.returncode,
            "image_inspect_stdout": inspect_result.stdout,
            "configured_image_tag": image_tag,
            "image_id": image_id,
            "repo_digests": repo_digests,
            "image_digest": repo_digests[0] if repo_digests else image_id,
            "image_digest_source": "RepoDigests[0]" if repo_digests else "Docker immutable image Id",
            "image_build_provenance": image_build,
            "network": "none",
        }
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        return {
            "argv": argv,
            "cwd": str(ROOT),
            "exit_code": None,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "stdout": "",
            "stderr": str(exc),
            "state": "NOT_RUN",
            "test_run": False,
            "dependency_probe_argv": None,
            "dependency_probe_exit_code": None,
            "dependency_probe_stdout": "",
            "dependency_probe_stderr": str(exc),
            "installed_undici_version": None,
            "expected_locked_undici_version": expected_undici_version,
            "installed_undici_matches_working_tree_lock": False,
            "image_inspect_argv": ["docker", "image", "inspect", image_tag],
            "image_inspect_exit_code": None,
            "configured_image_tag": image_tag,
            "image_id": None,
            "repo_digests": [],
            "image_digest": None,
            "image_digest_source": "unavailable; image could not be resolved",
            "image_build_provenance": image_build if "image_build" in locals() else {},
            "network": "none",
        }


def sha256_at(ref: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{ref}:{path}"], check=False, cwd=ROOT, capture_output=True)
    if result.returncode:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def resolve_output_path(requested_output: Path) -> Path:
    root = ROOT.resolve()
    candidate = requested_output if requested_output.is_absolute() else root / requested_output
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Evidence output must stay within project root: {root}") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output_path = resolve_output_path(args.output) if args.output is not None else None

    candidate = git("rev-parse", "HEAD")
    if output_path is None:
        output_path = resolve_output_path(Path(
            f"tests/phase2/evidence/tc001-r1-preservation-{candidate[:7]}-run.json"
        ))
    before_status = git("status", "--porcelain").splitlines()
    source_worktree_before = git(
        "status", "--porcelain", "--", "src", "adapters", "db", "scripts", "testbed",
        "vendor/reference/1c-odata-v3",
    ).splitlines()
    paths = inventory(candidate)
    static = static_predicates(paths, candidate)
    pytest_result = run_pytest()
    dependency_provenance = sidecar_dependency_provenance(candidate)
    node_result = run_node_sidecar(
        candidate,
        dependency_provenance["working_tree_lock_resolved_undici"],
    )
    predicates = {**static, **pytest_result.pop("predicates")}
    p11_test_state = predicates["P11"]["state"]
    p01_test_state = predicates["P01"]["state"]
    predicates["P01"] = {
        **static["P01"],
        "state": "PASS" if static["P01"]["state"] == "PASS" and p01_test_state == "PASS" else "NOT_RUN",
        "negative_test_state": p01_test_state,
    }
    predicates["P11"]["state"] = (
        "PASS" if static["P11"]["state"] == "PASS" and p11_test_state == "PASS" else "NOT_RUN"
    )
    predicates["P11"]["admin_route_comparison"] = static["P11"]["admin_route_comparison"]
    p05_pytest = predicates["P05"]["state"] == "PASS"
    predicates["P05"]["state"] = "PASS" if p05_pytest and node_result["state"] == "PASS" else "NOT_RUN"
    predicates["P05"]["observed"] += (
        f" OData sidecar Node cases: {node_result['state']}"
        f" (exit={node_result['exit_code']}, {node_result['duration_seconds']}s); "
        f"installed undici={node_result['installed_undici_version']}, "
        f"working-tree undici={dependency_provenance['working_tree_lock_resolved_undici']}, "
        f"candidate-HEAD undici={dependency_provenance['candidate_head_lock_resolved_undici']}."
    )
    predicates["P05"]["node_execution"] = node_result
    predicates["P05"]["sidecar_dependency_provenance"] = dependency_provenance
    if node_result["state"] != "PASS":
        exact_failure = node_result["stderr"] or node_result["stdout"]
        if node_result["image_id"] is not None and not node_result["installed_undici_matches_working_tree_lock"]:
            exact_failure = (
                "Image undici version did not match the working-tree lock: "
                f"installed={node_result['installed_undici_version']!r}, "
                f"locked={node_result['expected_locked_undici_version']!r}; "
                f"dependency probe stdout={node_result['dependency_probe_stdout']!r}; "
                f"stderr={node_result['dependency_probe_stderr']!r}"
            )
        predicates["P05"]["node_test_blocker"] = {
            "exact_observed_failure": exact_failure,
            "installed_undici_version": node_result["installed_undici_version"],
            "expected_locked_undici_version": node_result["expected_locked_undici_version"],
            "configured_image_tag": node_result["configured_image_tag"],
            "resolved_image_id": node_result["image_id"],
            "build_exit_code": node_result["image_build_provenance"].get("build_exit_code"),
            "owner": "Codex",
            "next_action": "Codex resolves the recorded candidate build or lock-version mismatch. Commit the intended dependency delta before the exact-candidate run, then rerun the aggregate procedure; do not infer a missing source dependency from a build or test failure.",
        }
    head_after_run = git("rev-parse", "HEAD")
    p12_negative_tests_pass = predicates["P12"]["state"] == "PASS"
    p12_provenance = p12_run_provenance(
        candidate, head_after_run, dependency_provenance, node_result, source_worktree_before,
        p12_negative_tests_pass,
    )
    predicates["P12"] = p12_provenance

    # Native-format N/A is deliberately limited to normalized R1 CSV/JSON paths.
    exclusions = [
        {"item": "Native PDF/XLSX parser/sandbox", "state": "NOT_APPLICABLE", "reason": "The inspected R1 evidence path accepts normalized CSV/JSON and rejects native formats; no native parser is in this scope."},
        {"item": "R2 safe_parser.py and artifact_vault.py", "state": "EXCLUDED", "reason": "Separate R2 phase2 boundary; no R1 import/reachability is claimed by this procedure."},
        {"item": "Live 1C/COM writer and production binding", "state": "NOT_RUN", "reason": "No live endpoint or production authorization is in scope; release manifest remains NO_GO."},
        {"item": "PostgreSQL migrations/effective runtime roles", "state": "NOT_RUN", "reason": "No database target or migration execution; P10 uses only deterministic static/unit checks."},
        {"item": "Alert delivery and B3 authoritative evidence", "state": "NOT_RUN", "reason": "Separate TC002 evidence requires external delivery and authoritative report provenance."},
        {"item": "Product Gherkin R2-TC-001", "state": "NOT_RUN", "reason": "The catalog and Gherkin mark it @not_implemented; this aggregate procedure is supporting preservation evidence only."},
    ]
    evidence = {
        "schema_version": 1,
        "task_id": "R2-US-001",
        "acceptance_case": "R2-TC-001",
        "formal_requirement": "R2-REQ-01",
        "story_status": "IN_PROGRESS",
        "tc001_product_case_status": "NOT_RUN",
        "independent_review_disposition": "OPEN_PENDING_INDEPENDENT_REVIEW",
        "supersedes": [
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4.json", "reason": "Initial aggregate with JUnit path normalization defect; not acceptance evidence."},
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4-final.json", "reason": "Earlier incomplete changed-path inventory; superseded."},
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4-verified.json", "reason": "Earlier incomplete changed-path inventory and P11 coverage; superseded."},
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4-review2.json", "reason": "Final aggregate exposed a test-fixture AST extraction defect; P11 and the overall run failed, so superseded by corrected rerun."},
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4-review3.json", "reason": "Pytest predicates passed but P05's server test could not import the required vendored client and P12 counted local node_modules as dirty source; superseded by corrected evidence with exact dependency/build limitation and source-only status."},
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4-review4.json", "reason": "Harness attempt completed test subprocesses but failed to write evidence due Windows corepack.cmd version-probe launch handling."},
            {"path": "tests/phase2/evidence/tc001-r1-preservation-9f891e4-review5.json", "reason": "Corrected 499-case aggregate passed, but P05 ran against the incomplete host Node environment before the vendor runtime image was available; superseded by offline container test execution."},
        ],
        "gpt_pm_contract_request_id": "62af8553-262b-4d1b-83ae-6c17ad179db1",
        "baseline_full_sha": BASELINE,
        "checkpoint_full_sha": CHECKPOINT,
        "candidate_full_sha": candidate,
        "tested_full_sha": candidate if predicates["P12"]["state"] == "PASS" else None,
        "test_execution_git_head": candidate,
        "git_head_after_execution": head_after_run,
        "source_hashes_sha256": {
            path: sha256_at(candidate, path)
            for path in [
                "src/business_ai_gateway/adapters/onec/client.py",
                "src/business_ai_gateway/adapters/onec/com_bridge_client.py",
                "src/business_ai_gateway/adapters/onec/rsv_bridge.py",
                "src/business_ai_gateway/auth.py",
                "src/business_ai_gateway/server.py",
                "scripts/assemble_release_evidence.py",
            ]
        },
        "working_tree_before": before_status,
        "working_tree_clean": not bool(before_status),
        "test_artifact_provenance": {
            "test_module_path": "tests/phase2/test_tc001_r1_preservation.py",
            "runner_path": "tests/phase2/run_tc001_r1_preservation.py",
            "working_tree_state": "Working artifact hashes and candidate HEAD blob hashes are both recorded in P12.",
            "sha256": {
                "test_module": hashlib.sha256((ROOT / "tests/phase2/test_tc001_r1_preservation.py").read_bytes()).hexdigest(),
                "runner": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
        },
        "dependency_preparation": {
            "sidecar_dependency_provenance": dependency_provenance,
            "runtime_image": {
                "configured_tag": node_result["configured_image_tag"],
                "immutable_image_id": node_result["image_id"],
                "repo_digests": node_result["repo_digests"],
                "image_digest": node_result["image_digest"],
                "image_digest_source": node_result["image_digest_source"],
                "build_command_provenance": node_result["image_build_provenance"],
                "tested_git_head": candidate,
                "tested_worktree_dependency_delta": not dependency_provenance["working_tree_matches_candidate_head"],
                "candidate_image_context_undici_lock_version": dependency_provenance["candidate_head_lock_resolved_undici"],
                "working_tree_undici_lock_version": dependency_provenance["working_tree_lock_resolved_undici"],
                "image_installed_undici_version": node_result["installed_undici_version"],
                "image_installed_undici_matches_lock": node_result["installed_undici_matches_working_tree_lock"],
            },
            "note": "Each run builds from a git archive of explicit Docker inputs at candidate HEAD with --no-cache and a candidate SHA label, then executes and dependency-probes the inspected immutable image ID with network disabled.",
        },
        "predicate_results": predicates,
        "exclusions_and_not_run": exclusions,
        "pytest_execution": pytest_result,
        "node_execution": node_result,
        "review_disposition": "OPEN until independent review of this evidence and scope is recorded.",
    }
    overall = (
        all(item.get("state") == "PASS" for item in predicates.values())
        and pytest_result["exit_code"] == 0
        and node_result["state"] == "PASS"
    )
    evidence["procedure_result"] = "READY_FOR_INDEPENDENT_REVIEW" if overall else "OPEN"
    evidence["working_tree_after"] = git("status", "--porcelain").splitlines()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    evidence["test_artifact_provenance"]["sha256"]["evidence_record_payload"] = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    record_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    checksum_path = output_path.with_suffix(output_path.suffix + ".sha256")
    checksum_path.write_text(f"{record_sha256}  {output_path.name}\n", encoding="ascii")
    print(f"TC001 procedure result: {evidence['procedure_result']}")
    states = ", ".join(f"{key}={value.get('state')}" for key, value in predicates.items())
    print(f"predicate states: {states}")
    print(f"pytest: {len(pytest_result['case_rows'])} cases, exit={pytest_result['exit_code']}, {pytest_result['duration_seconds']}s")
    if pytest_result["stdout"]:
        print(pytest_result["stdout"], end="")
    if pytest_result["stderr"]:
        print(pytest_result["stderr"], file=sys.stderr, end="")
    print(f"evidence: {output_path.relative_to(ROOT)}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
