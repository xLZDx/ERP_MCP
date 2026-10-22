# WP2 inherited red-test classification — 2026-10-21

Scope: classify the inherited failing/error test names recorded for the 2026-10-20
integration. This is a source- and record-based triage, not a reproduced test run.
The names below were extracted from the two named integration evidence files with
output restricted to test identifiers. No customer fixture or traceback content is
included here.

## Evidence and limits

- `docs/BACKLOG_INHERITED_2026-10-21.md`, item ERPMCP-INH-003, records a merged run
  with 12 failures, 13 errors, and 6,847 passes. It says causes were mainly
  disposable-PostgreSQL and other environment dependencies, but does not assign a
  cause to each test.
- The same item says the 12/13 name set matched an earlier detached ERP_MCP_R2 run.
  This is inherited run evidence, not a run independently reproduced in this turn.
- The 13 database migration names below are classified as **database-environment
  candidates** from their PostgreSQL migration / connection / locking scope and the
  inherited run summary. Exact exception causes remain NOT_VERIFIED until an
  authorized test owner captures sanitized failure details with the declared
  disposable database available.
- The 14 failures below are **code/contract candidates** based on the source test
  scope. Their individual causes are NOT_VERIFIED. In particular, tests explicitly
  described as offline use synthetic in-memory data and should not be presumed to
  need PostgreSQL or 1C.
- No tests, checks, database commands, or mutation scenarios were run for this
  classification.
- The identifiers were read from the two backlog-named files using a PowerShell
  filter that emitted only lines matching a test identifier (`tests/...::...`); no
  traceback or result body was emitted:
  `D:\Repo\Trash\_integrate\out_ERPMCP_r2m.p2.fail.txt` and
  `D:\Repo\Trash\_integrate\out_ERPMCP_base.main.fail.txt`.

## Thirteen inherited errors

| Test identifier | Preliminary class | Evidence and remaining acceptance |
|---|---|---|
| `tests/phase2/test_s13_checkpoint_suffix_functional.py::test_migration_026` | Database-environment candidate | Migration test; inherited summary cites disposable PostgreSQL as a main dependency. Exact error unverified. |
| `tests/phase2/test_s13_migration020.py::test_api_and_clean_off` | Database-environment candidate | Migration/API lifecycle test; exact error unverified. |
| `tests/phase2/test_s13_migration020.py::test_batch_bound_and_concurrent_serialization` | Database-environment candidate | Database batch/concurrency scenario; exact error unverified. |
| `tests/phase2/test_s13_migration020.py::test_each_active_hold_blocks_off` | Database-environment candidate | Database hold-state scenario; exact error unverified. |
| `tests/phase2/test_s13_migration020.py::test_partial_failure_t9_retry_and_repair` | Database-environment candidate | Database failure/retry scenario; exact error unverified. |
| `tests/phase2/test_s13_migration020.py::test_t9_t12_delays_and_cleanup_stages` | Database-environment candidate | Database lifecycle/cleanup scenario; exact error unverified. |
| `tests/phase2/test_s13_migration022_e2e.py::test_cross_connection_recovery_fence` | Database-environment candidate | Cross-connection recovery scenario; exact error unverified. |
| `tests/phase2/test_s13_migration022_e2e.py::test_unresolved_calls_hold_recovery` | Database-environment candidate | Recovery and unresolved-call scenario; exact error unverified. |
| `tests/phase2/test_s13_migration023.py::test_bounded_lock_waits` | Database-environment candidate | Database locking scenario; exact error unverified. |
| `tests/phase2/test_s13_migration023.py::test_migration_is_idempotent` | Database-environment candidate | Migration scenario; exact error unverified. |
| `tests/phase2/test_s13_migration023.py::test_recovery_is_denied_and_fail_closed` | Database-environment candidate | Database recovery scenario; exact error unverified. |
| `tests/phase2/test_s13_migration023.py::test_success_restores_caller_lock_timeout` | Database-environment candidate | Database session-setting scenario; exact error unverified. |
| `tests/phase2/test_s13_migration023.py::test_timeout_savepoint_restores_setting_and_outer_transaction` | Database-environment candidate | Database transaction/savepoint scenario; exact error unverified. |

## Fourteen inherited failures

| Test identifier | Preliminary class | Evidence and remaining acceptance |
|---|---|---|
| `tests/phase2/test_docs_evidence_consistency.py::test_old_g1_notes_carry_a_superseded_banner` | Documentation/contract candidate | Static evidence consistency assertion; exact mismatch unverified. |
| `tests/phase2/test_g1_capacity_smoke.py::test_verify_cluster_accepts_only_the_container_cluster` | Environment or contract candidate | Cluster identity assertion; the name suggests environment sensitivity, but source and failure details do not establish the cause. |
| `tests/phase2/test_s13_lifecycle_preflight.py::S13LifecyclePreflightTests::test_valid_preflight_returns_checkpoint_evidence_but_never_ready` | Code/contract candidate | In-memory lifecycle contract; does not by itself imply an external database dependency. Exact mismatch unverified. |
| `tests/phase2/test_s13_lifecycle_preflight_e2e.py::test_s13_preflight_successful_chain_and_exact_scope_latest_stays_not_ready` | Code/contract candidate | Local orchestration boundary uses in-memory checkpoint/port doubles; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_all_four_operation_kinds_applied_with_verified_receipts` | Offline simulation/code candidate | Test module documents synthetic data with no PostgreSQL, network, or real 1C. Exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_timeout_then_repair_via_state_read_then_retry_without_duplicate` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_timeout_on_create_leaves_no_document_and_retry_creates_exactly_one` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_duplicate_detection_override_and_injected_duplicate_mode` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_stale_expected_version_is_rejected_without_write` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_tampered_bytes_detected_and_truth_log_shows_what_landed` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_two_interleaved_writers_only_one_wins_on_expected_version` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/phase2/test_simulation_scenarios_offline.py::test_separate_clone_labels_are_isolated` | Offline simulation/code candidate | Same offline test boundary; exact mismatch unverified. |
| `tests/test_chatgpt_mcp_contract.py::test_all_public_mcp_tools_are_explicitly_read_only_for_chatgpt` | Public-tool contract candidate | Static tool metadata/annotation contract; exact mismatch unverified. |
| `tests/test_operations_artifacts.py::test_fault_injection_and_runbook_artifacts_are_present` | Documentation/artifact candidate | File-presence/reference checks; exact missing item unverified. |

The extracted identifier set contains 27 items: 13 errors and 14 failures. The
historical backlog calls out 12 Phase 2 failures and 2 main-set failures, which
reconciles to 14. The eight offline simulation failures are individually named
above; the earlier hand-over summary omitted two names. This count reconciliation
uses identifiers only and does not establish failure causes.

## Acceptance and owner

WP2 is **partially classified; runtime acceptance is NOT_RUN**. The test owners are
`functional-test-reviewer` and `e2e-runner`; they must reconcile all 14 failure and
13 error identifiers against sanitized historical failure metadata, then run only the
focused cases after all coding is complete. Classify each result as code defect,
declared environment dependency, or historical flake only when the execution
evidence supports that conclusion. The executor must preserve exact commands,
revision, environment and sanitized result. No named human or service owner for the
historical result archive is established by the in-scope records.
