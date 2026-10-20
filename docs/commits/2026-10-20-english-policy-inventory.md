# English-only policy inventory: tracked files containing Cyrillic

Date: 2026-10-20. Base: integrate/2026-10-20 at e82022a (merged ERP_MCP + ERP_MCP_R2). English.

Policy: all text committed to git is English (operator rule 2026-10-10). This inventory lists every tracked
`.md .py .toml .yaml .yml .json .sh` file with at least one line containing a Cyrillic character (U+0400-U+04FF).
Nothing is translated here; this is the input for a separate translation sprint.

Method: `git ls-files`, UTF-8 decode, count lines with a Cyrillic character. Classification is a PATH-BASED HEURISTIC
(spot-checked, not line-by-line): files marked PROSE-TO-TRANSLATE may still contain literal 1C names or Russian test
strings that must stay (for example `scripts/real1c/*.py`, `reports/real1c/case_results.json`,
`scripts/synthetic_fixture_profiles.py`), and every class needs a human pass before editing.

## Summary

| Classification | Files | Cyrillic lines |
| --- | ---: | ---: |
| PROSE-TO-TRANSLATE | 38 | 856 |
| LOCALIZATION | 11 | 538 |
| LITERAL-1C-NAMES | 8 | 117 |
| SEMANTIC-TEST-DATA | 71 | 948 |
| Total | 128 | 2459 |

Classes: SEMANTIC-TEST-DATA = Russian strings that tests and fixtures must keep to exercise Russian 1C data;
LOCALIZATION = intentionally Russian documents (`*_RU.md`, the `spec-v0.1` Russian specification bundle);
LITERAL-1C-NAMES = 1C register, catalog, field or configuration names in source code that must stay verbatim;
PROSE-TO-TRANSLATE = documentation, reports and script text that should become English.

## Recommended next step

1. Open one translation sprint (one PR). Start with PROSE-TO-TRANSLATE docs (`.md`), then comments/docstrings in
   `scripts/**/*.py`; keep literal 1C identifiers inside code and JSON values untouched.
2. `reports/real1c/case_results.json` and `reports/real1c/summary.json` are generated evidence: fix the generator
   (`scripts/real1c/*`) and regenerate rather than hand-edit.
3. `core/DECISION_LOG.md` (15 lines) quotes operator answers and Russian terms: translate the surrounding prose, keep
   short verbatim quotes only if the operator approves the exception.
4. Add a mechanical checker (tracked-file Cyrillic scan with an allowlist file for the exceptions below) so the
   policy is enforced instead of remembered.

## Policy exception candidates (operator decision needed)

- SEMANTIC-TEST-DATA and LITERAL-1C-NAMES: Russian data is the behavior under test (1C names like `Номенклатура_Key`);
  translating would break the tests. Proposed exception: allowlisted by path, scanned by the checker.
- LOCALIZATION: the Russian Phase 2 specification bundle and `*_RU.md` documents. Either keep as an explicit
  localization exception or replace by English originals (English versions of most already exist under `docs/phase2/`).
- Third-party vendored references under `vendor/reference/` on other branches are Russian upstream text and
  must stay unmodified; on this branch they appear only as escaped titles in the document registry.
- Out of the scanned extension set: seven intentionally Russian `reports/PHASE2_S*_SPRINT_*.ru.html` reports (see the
  earlier translation commit); they need the same keep-or-drop decision.

## Files

### PROSE-TO-TRANSLATE

| Cyrillic lines | File |
| ---: | --- |
| 467 | `reports/real1c/case_results.json` |
| 75 | `scripts/real1c/details_report.py` |
| 49 | `scripts/real1c/raw_l2.py` |
| 48 | `scripts/real1c/native_checks.py` |
| 32 | `scripts/real1c/report.py` |
| 18 | `reports/RSVDATA_EXTENSION_AUDIT.md` |
| 17 | `docs/phase2/artifacts/G3_ENGINEERING_RECONCILIATION_INDEX.md` |
| 15 | `core/DECISION_LOG.md` |
| 15 | `scripts/synthetic_fixture_profiles.py` |
| 14 | `scripts/real1c/com_oracle.py` |
| 12 | `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` |
| 11 | `scripts/real1c/native_engine_reports.py` |
| 11 | `scripts/real1c/probes.py` |
| 9 | `scripts/real1c/run_lane.py` |
| 7 | `scripts/real1c/com_fingerprint.py` |
| 7 | `scripts/real1c/lane_setup.py` |
| 6 | `docs/phase2/S11_SCOPE_DECISIONS_AND_GATE_MANIFEST_2026-10-12.md` |
| 4 | `docs/adr/ADR-0008-hybrid-odata-com-analytics-balance.md` |
| 4 | `docs/phase2/S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` |
| 4 | `reports/real1c/summary.json` |
| 3 | `docs/FERMA_1C_SYNTHETIC_TESTBED_IMPLEMENTATION.md` |
| 3 | `docs/NATIVE_REPORT_CAPTURE_RUNBOOK.md` |
| 3 | `docs/SEMANTIC_PROFILES.md` |
| 3 | `docs/phase2/S11_DECISION_RECORDS_AND_THREAT_MODEL_2026-10-12.md` |
| 3 | `reports/EXECUTION_LOG.md` |
| 3 | `scripts/phase2/build_spec_bundle.py` |
| 2 | `scripts/real1c/documentation.py` |
| 1 | `docs/ADAPTER_INTAKE_PLAN.md` |
| 1 | `docs/COMPATIBILITY.md` |
| 1 | `docs/INTEGRATION.md` |
| 1 | `docs/phase2/OPERATOR_BACKLOG.md` |
| 1 | `docs/phase2/S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md` |
| 1 | `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md` |
| 1 | `docs/phase2/artifacts/REMOTE_1C_HOST_STACK_2026-10-11.md` |
| 1 | `docs/runbooks/COM_BRIDGE_AND_PARITY.md` |
| 1 | `reports/CHATGPT_READER_BOOTSTRAP_REPAIR_2026-10-07.md` |
| 1 | `scripts/real1c/sanitize.py` |
| 1 | `scripts/real1c/stories.py` |

### LOCALIZATION

| Cyrillic lines | File |
| ---: | --- |
| 120 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/01_TDD_RU.md` |
| 67 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/05_NATIVE_REPORT_PROTOCOL_RU.md` |
| 60 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/03_STORIES_RU.md` |
| 53 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/04_TEST_PLAN_RU.md` |
| 47 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/stories.yaml` |
| 44 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/06_DECISIONS_SOURCES_RU.md` |
| 43 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/02_PLAN_RU.md` |
| 32 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/test_cases.yaml` |
| 28 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/07_DATA_MODEL_API_RU.md` |
| 22 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/docs/08_COMPLETION_RU.md` |
| 22 | `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/requirements.yaml` |

### LITERAL-1C-NAMES

| Cyrillic lines | File |
| ---: | --- |
| 48 | `src/business_ai_gateway/semantic.py` |
| 32 | `src/business_ai_gateway/testbed/fake1c.py` |
| 25 | `onec_com_bridge/query.py` |
| 4 | `src/business_ai_gateway/phase2/_identity.py` |
| 3 | `src/business_ai_gateway/server.py` |
| 2 | `src/business_ai_gateway/analytics_balance.py` |
| 2 | `src/business_ai_gateway/phase2/change/proposal.py` |
| 1 | `src/business_ai_gateway/supplier_debt_summary.py` |

### SEMANTIC-TEST-DATA

| Cyrillic lines | File |
| ---: | --- |
| 96 | `tests/test_semantic_profiles.py` |
| 93 | `testlane/onec_extension/scripts/ct14_measure.py` |
| 76 | `testbed/fake1c/fixtures/seed.json` |
| 61 | `tests/test_server_audit.py` |
| 53 | `testlane/onec_extension/scripts/ct14_rights_allowlist.json` |
| 52 | `testlane/onec_extension/scripts/ct14_rights_state.json` |
| 46 | `testbed/fake1c/fixtures/synthetic_profiles.json` |
| 46 | `testlane/onec_extension/scripts/ct14_narrow_ops.py` |
| 44 | `tests/test_registry_postgres_integration.py` |
| 36 | `tests/real1c/test_native_engine_reports.py` |
| 29 | `testlane/onec_extension/STATUS.md` |
| 29 | `tests/phase2/test_ap_account_strategy.py` |
| 24 | `testbed/real1c/provisional_profiles_818ha.json` |
| 21 | `testlane/onec_extension/scripts/ct14_iterate.py` |
| 21 | `tests/test_analytics_balance_mapping.py` |
| 17 | `testlane/onec_extension/scripts/ct14_effective_rights.py` |
| 16 | `testlane/tools/edit_purchase_on_clone.py` |
| 12 | `tests/test_com_bridge.py` |
| 9 | `testlane/onec_extension/scripts/ct14_create_ext.py` |
| 9 | `tests/test_analytics_real_shape.py` |
| 8 | `testlane/onec_extension/scripts/ct14_recon.py` |
| 7 | `testlane/onec_extension/scripts/ct14_check_ext.py` |
| 7 | `testlane/onec_extension/scripts/ct14_denied.py` |
| 7 | `testlane/onec_extension/scripts/ct14_eventlog.py` |
| 7 | `testlane/onec_extension/scripts/ct14_ext_flags.py` |
| 7 | `testlane/onec_extension/scripts/ct14_rightcheck.py` |
| 6 | `testlane/onec_extension/README.md` |
| 6 | `testlane/onec_extension/scripts/ct14_ext_safe_off.py` |
| 6 | `testlane/onec_extension/scripts/ct14_extprops.py` |
| 6 | `tests/test_odata_sidecar_client.py` |
| 6 | `tests/test_rsv_bridge.py` |
| 5 | `testlane/onec_extension/scripts/ct14_other_ext.py` |
| 5 | `tests/test_company_scope_runtime.py` |
| 5 | `tests/test_turnover_account_scope.py` |
| 4 | `tests/functional/test_20_raw_l1_cross_checks.py` |
| 4 | `tests/phase2/test_change_approval_digest2.py` |
| 4 | `tests/real1c/test_oracle_guard.py` |
| 4 | `tests/test_counterparty_tools_surface.py` |
| 4 | `tests/test_duplicate_counterparties_unit.py` |
| 4 | `tests/test_purchase_receipts_filter.py` |
| 3 | `tests/com_bridge_fakes.py` |
| 3 | `tests/test_counterparty_lookup.py` |
| 3 | `tests/test_provisional_profiles.py` |
| 3 | `tests/test_supplier_debt_summary.py` |
| 2 | `tests/phase2/test_identity.py` |
| 2 | `tests/phase2/test_validation_coverage.py` |
| 2 | `tests/phase2/test_workbench_review.py` |
| 2 | `tests/real1c/test_public_sanitizer.py` |
| 2 | `tests/test_analytics_balance_routing.py` |
| 2 | `tests/test_rsv_wire_limits.py` |
| 2 | `tests/test_supplier_debt_review_findings.py` |
| 1 | `testlane/onec_extension/scripts/ct14_compare_rights.py` |
| 1 | `testlane/onec_extension/scripts/ct14_prune.py` |
| 1 | `tests/e2e/user/test_u05_u08_company_scope.py` |
| 1 | `tests/e2e/user/test_u09_u10_grant_lifecycle.py` |
| 1 | `tests/phase2/test_change_offline.py` |
| 1 | `tests/phase2/test_evidence_attestation.py` |
| 1 | `tests/phase2/test_jobs_api.py` |
| 1 | `tests/phase2/test_jobs_api_bypass.py` |
| 1 | `tests/phase2/test_posted_receipts.py` |
| 1 | `tests/phase2/test_release_migration.py` |
| 1 | `tests/phase2/test_release_rollback.py` |
| 1 | `tests/real1c/test_details_report.py` |
| 1 | `tests/real1c/test_manifest_schema_sanitize.py` |
| 1 | `tests/real1c/test_report.py` |
| 1 | `tests/real1c/test_run_lane.py` |
| 1 | `tests/test_com_bridge_client.py` |
| 1 | `tests/test_live_rsv_metadata.py` |
| 1 | `tests/test_machine_profile_postgres.py` |
| 1 | `tests/test_sc08_duplicate_counterparty_chain.py` |
| 1 | `tests/test_supplier_debt_mcp_integration.py` |
