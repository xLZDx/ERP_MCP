# G1 evidence packet plan

Date: 2026-10-16. Purpose: assemble local G1 engineering evidence for the exact code revision. Accepted proof for code behavior is the focused local test result authored/executed by the functional-test-reviewer and e2e-runner, their findings, and GPT review of the exact final diff. It does not require separate production or deployed-database evidence. Any database used by integration tests must be disposable and local; never use production. The initial run at committed HEAD `4b9f3b08b4e75359b549bda75d6f6ec3307f248e` completed with 46 passed and 1 failed. The test-only correction is committed at `69857fd`. The distinct-cluster restore test now passes in focused runs by both functional-test-reviewer and e2e-runner at documentation HEAD `5588c06851340751fa574e182da0e9c9b03111e9`; this is one case only and does not establish the full focused set or formal G1. PM Bridge request `f4cd1c27-2b3c-4094-80f3-1fd88dbfd1e6` statically approved code HEAD `315e83149b48fcef1d3ded7c5e2325d7c3fe7cd4` with no confirmed BLOCKER/MAJOR and returned `PUSH NO-GO` pending exact-head runtime evidence. That runtime dependency is met for the restore case; a fresh PM push decision remains unrecorded.

## Evidence boundary

For this local code-review/push scope, evidence means the exact-head focused local test report plus the required agent and GPT reviews. PostgreSQL-backed tests use an invocation-owned disposable container/database to exercise the checked-in scenarios; that is test infrastructure, not an additional deployed-runtime evidence deliverable. A host `psql`, production database, deployed role inventory, production workload study, or external identity evidence is not required to support claims about what the local code/tests establish.

The tests can establish only their fixture-level behavior and tested schedules. They do not claim production deployment, production capacity, or live identity configuration. Those remain part of the formal G1/release gate, but are not extra prerequisites for a local engineering push. A local push still requires the required green focused tests, relevant reviews, and an applicable exact-head GPT decision under `D:\Repo\AGENTS.md`. The initial functional run reported 46/1; e2e-runner separately passed the explicit-COMMIT case and initially reported the restore failure at the invalid internal-helper assertion. The corrected distinct-cluster restore test has since passed under both test-agent owners. The focused test set as a whole remains incomplete. PM's prior PUSH NO-GO was conditioned on runtime evidence; the restore-case evidence now exists, but no updated PM push decision is recorded.

## Acceptance inventory

| Evidence item | Existing evidence | Still required for G1 | Evidence owner / dependency | State |
|---|---|---|---|---|
| Exact-head focused local scenarios | `test_pg_dump_restore_to_distinct_postgres_cluster` in `tests/phase2/test_g1_restore.py` passed for functional-test-reviewer and e2e-runner; both distinct PostgreSQL system identifiers and container IDs were recorded in `CHANGE_RECORD_080.md`. The broader B04–B08 set remains mapped below. | Execute and record the remaining selected scenarios, including full `test_g1_restore.py` coverage and exact candidate-head crash/transaction cases; retain per-case outcomes and non-secret fixture identity. | Functional-test-reviewer / e2e-runner; disposable local Docker fixtures. | `PARTIAL` |
| Agent findings and exact-head GPT approval | Test-agent findings and prior static GPT review are recorded in change records; the prior GPT approval covers code through `17b6de7`, not this current head. | Record the functional/E2E and relevant database/security findings, fix valid blockers, then obtain fresh GPT approval for the exact final diff and test report before push. | Test agents, relevant specialist reviewer, then GPT; no deployed database/identity/capacity evidence is required for this local push. | `OPEN` |
| Formal G1/release evidence (separate from local push) | `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` retains the G1 exit criteria; focused local scenarios are authored but unexecuted. | Complete the formal G1 criteria, including exact-head local scenario results, the capacity disposition, effective-role/grant and authenticated identity evidence, and gate-specific review. These items govern G1/release acceptance and production authorization, not the local code push. | Database/security lane and relevant identity/control-plane authority; no human owner is named. | `OPEN` |

## Candidate criterion-to-test map

This source-observed map names candidate scenarios and their evidence limits. It is not a claim that any test passed. Required/supplemental selection is recorded below after read-only review by the functional-test reviewer, E2E runner and database reviewer (GPT-6 Luna, 2026-10-16); database/security gate review of the complete evidence package remains outstanding. Files and cases outside this table remain governed by their own sprint coverage.

| G1 criterion | Candidate test/scenario | Required or supplemental | What a passing result can support | What it cannot prove |
|---|---|---|---|---|
| Tenant/source/company isolation and scope spoofing (G1-B04) | `test_g1_postgres_integration.py::test_cross_tenant_source_company_reads_empty_and_provenance_hidden`; `::test_guc_spoof_returns_nothing`; revocation coverage `test_g1_postgres_integration_review2.py::test_m2_role_scope_change_bumps_epoch_and_old_context_cannot_commit` and `::test_major02_scope_rechecked_after_source_lock`; restore behavior in `test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster` | Required candidates. M2 checks stale context after role-scope epoch change; MAJOR-02 checks the separately recorded revoke-barrier race after source lock. | Denial/empty result behavior for the fixture roles and scopes on the tested migration set | Deployed tenant isolation or authorization outside that fixture/database |
| Runtime-role privilege boundary (G1-B05) | `test_g1_postgres_integration.py::test_runtime_roles_cannot_update_delete_truncate_or_insert`; `test_g1_postgres_integration_hardening.py::test_n6_add_role_scope_validates_role_and_blocks_direct_dml`; restored effective ACL comparison in `test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster` | Required local test candidates; no separate catalog capture for deployed roles is required for this code push | Behavior and effective ACLs within the test cluster and declared fixture roles | The actual deployed role map or permissions on a live system; those are outside this local code-push claim |
| Approver independence and evidence trust (G1-B05) | `test_g1_postgres_integration.py::test_promote_requires_independent_approver_and_blocks_direct_head_change`; `test_g1_postgres_integration_hardening.py::test_n2_dual_duty_login_cannot_promote`; `test_g1_postgres_integration_review2.py::test_m1_absent_forged_expired_revoked_untrusted_evidence_cannot_promote` | Required local DB-boundary candidates. N2 covers the distinct case where one fixture login has both worker and promoter memberships. | Database rejection of the covered dual-duty, direct-head, and invalid-evidence cases | Deployed identity configuration; that is outside this local code-push claim |
| Server-authoritative record time (G1-B06) | `test_g1_postgres_integration.py::test_backdated_recorded_at_is_overwritten`; supplemental ordering case `test_g1_postgres_integration_hardening.py::test_n3_ingest_seq_recorded_at_and_commit_order_agree` | Backdated `recorded_at` denial is required. N3 is supplemental because current B06 wording requires database-authoritative record time, not a separate ingest/commit ordering guarantee. | The DB fixture ignores the covered caller time | Clock quality or timestamp provenance in a deployed environment |
| Lease, CAS, replay, fencing and outbox concurrency (G1-B07) | `test_g1_postgres_integration.py::test_stale_fence_rejected`, `::test_duplicate_digest_conflict`, `::test_two_session_concurrent_promote_has_one_winner`; hardening `test_n7_retry_and_replay_compare_all_columns`, `::test_n8_outbox_claim_finish_lease_attempts_and_skip_locked`, `::test_n8_concurrent_claims_do_not_overlap`; review2 `test_b1_page_replay_identical_ok_changed_batch_conflicts`, `::test_b2_claim_generation_fences_reclaim_by_same_name`; multiprocessing `test_g1_concurrency_mp.py::test_six_processes_acquire_same_job_exactly_one_wins`, `::test_killed_lease_holder_is_reaped_and_its_old_fence_is_dead`, `::test_two_processes_commit_same_prior_cursor_different_pages_one_wins`, `::test_two_processes_commit_identical_page_is_applied_once`; supplemental sequential busy case hardening `test_n5_second_acquire_is_job_unavailable_not_unique_violation` | Required candidates cover separate lease/replay/outbox invariants, head CAS, process acquisition and both cursor races. N5 is supplemental because it tests a sequential busy response, not a distinct concurrent-worker acceptance. | Only the tested transaction/process interleavings and invariants | Untested contention shapes, production workload or all failure schedules |
| Termination during explicit COMMIT and crash recovery (G1-B07) | Required gap case: `test_g1_crash.py::test_terminate_backend_during_observed_explicit_commit`; supplemental recovery cases: `::test_sigkill_backend_crash_recovery` for both `kind="page"` and `kind="ingest"` | The observed explicit-COMMIT case is required for the documented gap; both parameterized crash-recovery paths are supplemental unless gate-specific review identifies one as necessary for a named criterion | The observed commit-processing boundary or the separately selected page/ingest recovery case, if its observer/fixture establishes it | The narrower post-WAL-commit/pre-ack ambiguity window unless separately observed |
| Separate-cluster restore (G1-B08) | Required candidate: `test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster`; supplemental same-cluster case: `::test_pg_dump_restore_is_identical_and_guards_still_hold` | The distinct-cluster scenario is required; same-cluster restore is supplemental and cannot substitute. | Distinct cluster identity plus the comparisons/assertions actually performed by the required scenario | Production backup readiness, restore objectives or untested target environments. The test recreates custom role names but does not compare `pg_auth_members`, login attributes or deployed login assumption paths; those remain separate effective-role evidence. |
| Capacity qualification | `test_g1_capacity_smoke.py::test_capacity_drill_small_run_recounts_clean` and its cluster-identity refusal cases | Supplemental only; production capacity qualification is not required for this local code push | Small local drill behavior, recount and refusal of disallowed cluster targets | Representative capacity, production sizing or workload acceptance thresholds |
| Static migration/safety preflight | `test_g1_migration_contract.py`; `test_g1_safety_requirements.py` | Supplemental preflight, not runtime gate evidence | Selected textual guardrails in the checked-in SQL | PostgreSQL behavior, effective grants or G1 closure |
| Guard load-bearing mutation | `test_g1_guard_mutations.py::test_guard_is_red_when_removed_and_green_on_baseline` | Supplemental unless gate reviewer explicitly requires the mutation matrix | The tested guards are load-bearing for the mutation/probe pairs exercised | General security completeness or a substitute for direct negative integration cases |

All candidates remain unexecuted in this pass. The authorized test agents must report the exact command, head, local disposable fixture, per-case result, skip, omission and failure. Static preflight does not substitute for the focused local test result. Production capacity, deployed grants, and external identity configuration remain formal G1/release concerns, separate from local push acceptance.

## Reviewed focused local test set (proposal, PARTIALLY RUN)

Read-only selection reconciled by `functional-test-reviewer` (GPT-6 Luna, low), `e2e-runner` (GPT-6 Luna, low) and `database-reviewer` (GPT-6 Luna, medium; 2026-10-16). This is the recommended focused local set for test-agent execution. Test-agent reports plus fresh GPT review of the exact diff/results are the evidence for this code push; this does not claim production readiness. The distinct-cluster restore case is `PASS` as recorded in `CHANGE_RECORD_080.md`; other items remain `NOT_RUN` until executed.

| Acceptance area | Proposed included scenario(s) | Reason / limit |
|---|---|---|
| G1-B04 scope isolation, spoofing and revocation | `test_cross_tenant_source_company_reads_empty_and_provenance_hidden`; `test_guc_spoof_returns_nothing`; `test_m2_role_scope_change_bumps_epoch_and_old_context_cannot_commit`; `test_major02_scope_rechecked_after_source_lock` | Both revocation cases are included: M2 checks epoch invalidation of an old context; MAJOR-02 checks the previously recorded revoke-barrier race after source lock. |
| G1-B05 local database privileges | `test_runtime_roles_cannot_update_delete_truncate_or_insert`; `test_n6_add_role_scope_validates_role_and_blocks_direct_dml` | Covers test-role direct DML and role-scope guard behavior in the disposable fixture. |
| G1-B05 local approver/evidence boundary | `test_promote_requires_independent_approver_and_blocks_direct_head_change`; `test_m1_absent_forged_expired_revoked_untrusted_evidence_cannot_promote`; `test_n2_dual_duty_login_cannot_promote` | N2 is required because one fixture login with both worker and promoter memberships is a distinct database control. |
| G1-B06 database-authoritative record time | `test_backdated_recorded_at_is_overwritten` | Required: directly checks rejection/overwrite of caller-supplied past time. Commit-order test `test_n3_ingest_seq_recorded_at_and_commit_order_agree` is supplemental because separate commit-order acceptance is not stated in the backlog. |
| G1-B07 fencing, replay and outbox leases | `test_stale_fence_rejected`; `test_duplicate_digest_conflict`; `test_two_session_concurrent_promote_has_one_winner`; `test_n7_retry_and_replay_compare_all_columns`; `test_n8_outbox_claim_finish_lease_attempts_and_skip_locked`; `test_n8_concurrent_claims_do_not_overlap`; `test_b1_page_replay_identical_ok_changed_batch_conflicts`; `test_b2_claim_generation_fences_reclaim_by_same_name`; `test_six_processes_acquire_same_job_exactly_one_wins`; `test_killed_lease_holder_is_reaped_and_its_old_fence_is_dead`; `test_two_processes_commit_same_prior_cursor_different_pages_one_wins`; `test_two_processes_commit_identical_page_is_applied_once` | Required candidates cover lease lifecycle, replay comparison, fencing, outbox, head CAS, process acquisition and both cursor races based on the G1-B07 acceptance. The sequential busy response `test_n5_second_acquire_is_job_unavailable_not_unique_violation` is supplemental; it does not add a separate concurrent-worker invariant. The finite set does not cover every interleaving. |
| G1-B07 observed termination during explicit COMMIT | `test_terminate_backend_during_observed_explicit_commit` | Required for the documented missing boundary; report `NOT_RUN` if the observer cannot prove COMMIT was underway before termination. |
| G1-B08 separate-cluster restore | `test_pg_dump_restore_to_distinct_postgres_cluster` | Required candidate; same-cluster restore cannot substitute. |

### Coverage decisions and remaining evidence boundaries

- The earlier MAJOR-02 revoke-barrier finding and the G1-B04 revoked-scope requirement make `test_major02_scope_rechecked_after_source_lock` required alongside M2. N2 is included because dual worker/promoter membership is a distinct database control. N3 remains supplemental because B06 does not separately require ingest/commit ordering.
- Actual deployed-role/grant capture, external approver/evidence identity, production capacity disposition, and gate-specific review remain formal G1/release items. They do not replace or add prerequisites to the local push's focused test, specialist-review, and exact-head GPT gates.
- Static preflight, capacity smoke, guard mutation, general page/ingest crash-recovery and same-cluster restore remain supplemental or excluded as described in the candidate map unless gate review records a specific reason to add them.

### Proposed broader focused invocation (NOT_RUN)

The following command was prepared by `e2e-runner` (GPT-6 Luna, low effort) from the reconciled B04–B08 selection. It is recorded for the agents' local execution and has not been executed. Integration and multiprocessing cases require `ERP_PHASE2_TEST_DSN` pointing to a disposable PostgreSQL role with `CREATE DATABASE` and `CREATE ROLE` privileges. Crash and restore cases use invocation-owned disposable clusters and require Docker plus the opt-in flag. Never use a production DSN. The disposable PostgreSQL is part of local test setup, not a separate production/runtime evidence deliverable.

### Preparing the disposable DSN on Windows (setup only; NOT_RUN)

The integration and multiprocessing cases use Python `asyncpg`; they do not require a host-installed `psql`. The crash and restore cases provision their own invocation-owned PostgreSQL containers and call `pg_dump`/`pg_restore` inside those containers. A local `psql` executable is optional for manual inspection, not a prerequisite for this focused set. Docker client/server and the `postgres:16` image must be available. Bind the separately provisioned test server to loopback only, and use its superuser only against this disposable container because fixtures create/drop databases and roles.

In the same PowerShell session intended for a future permitted run, start a dedicated ephemeral container and construct its DSN as follows. The random container name and password are per invocation; no volume or port is shared with an existing service:

```powershell
$g1Name = "erp-r2-g1-pg-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
$g1Password = [guid]::NewGuid().ToString('N')
docker run --detach --rm --name $g1Name `
  --publish 127.0.0.1::5432 `
  --env "POSTGRES_PASSWORD=$g1Password" `
  postgres:16
if ($LASTEXITCODE -ne 0) { throw "Could not start the disposable G1 PostgreSQL container" }

$g1PortLine = docker port $g1Name 5432/tcp
if ($LASTEXITCODE -ne 0 -or $g1PortLine -notmatch '^127\.0\.0\.1:(\d+)$') {
  throw "The disposable PostgreSQL port is not bound to loopback"
}
$env:ERP_PHASE2_TEST_DSN = "postgresql://postgres:$g1Password@127.0.0.1:$($Matches[1])/postgres"
$env:ERP_PHASE2_REQUIRE_PG = "1"
$env:ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS = "1"
```

Before local test execution, poll `docker exec $g1Name pg_isready -U postgres -q` until it returns zero, with a finite timeout, and confirm the DSN points to `127.0.0.1` and this invocation's published port. Keep the password only in the current shell; do not record it in logs or evidence. After the test agents finish and evidence is captured, stop only this exact invocation-owned container with `docker stop $g1Name`; `--rm` removes the disposable container and its anonymous data volume. If setup fails, report the exact Docker error and leave unrelated containers untouched.

```powershell
# The disposable DSN and flags above must be set in this same PowerShell session.

pytest -q `
  tests/phase2/test_g1_postgres_integration.py::test_cross_tenant_source_company_reads_empty_and_provenance_hidden `
  tests/phase2/test_g1_postgres_integration.py::test_guc_spoof_returns_nothing `
  tests/phase2/test_g1_postgres_integration_review2.py::test_m2_role_scope_change_bumps_epoch_and_old_context_cannot_commit `
  tests/phase2/test_g1_postgres_integration_review2.py::test_major02_scope_rechecked_after_source_lock `
  tests/phase2/test_g1_postgres_integration.py::test_runtime_roles_cannot_update_delete_truncate_or_insert `
  tests/phase2/test_g1_postgres_integration_hardening.py::test_n6_add_role_scope_validates_role_and_blocks_direct_dml `
  tests/phase2/test_g1_postgres_integration.py::test_promote_requires_independent_approver_and_blocks_direct_head_change `
  tests/phase2/test_g1_postgres_integration_hardening.py::test_n2_dual_duty_login_cannot_promote `
  tests/phase2/test_g1_postgres_integration_review2.py::test_m1_absent_forged_expired_revoked_untrusted_evidence_cannot_promote `
  tests/phase2/test_g1_postgres_integration.py::test_backdated_recorded_at_is_overwritten `
  tests/phase2/test_g1_postgres_integration.py::test_stale_fence_rejected `
  tests/phase2/test_g1_postgres_integration.py::test_duplicate_digest_conflict `
  tests/phase2/test_g1_postgres_integration.py::test_two_session_concurrent_promote_has_one_winner `
  tests/phase2/test_g1_postgres_integration_hardening.py::test_n7_retry_and_replay_compare_all_columns `
  tests/phase2/test_g1_postgres_integration_hardening.py::test_n8_outbox_claim_finish_lease_attempts_and_skip_locked `
  tests/phase2/test_g1_postgres_integration_hardening.py::test_n8_concurrent_claims_do_not_overlap `
  tests/phase2/test_g1_postgres_integration_review2.py::test_b1_page_replay_identical_ok_changed_batch_conflicts `
  tests/phase2/test_g1_postgres_integration_review2.py::test_b2_claim_generation_fences_reclaim_by_same_name `
  tests/phase2/test_g1_concurrency_mp.py::test_six_processes_acquire_same_job_exactly_one_wins `
  tests/phase2/test_g1_concurrency_mp.py::test_killed_lease_holder_is_reaped_and_its_old_fence_is_dead `
  tests/phase2/test_g1_concurrency_mp.py::test_two_processes_commit_same_prior_cursor_different_pages_one_wins `
  tests/phase2/test_g1_concurrency_mp.py::test_two_processes_commit_identical_page_is_applied_once `
  tests/phase2/test_g1_crash.py::test_terminate_backend_during_observed_explicit_commit `
  tests/phase2/test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster
```

The parameterized MAJOR-02 node selects all 24 combinations (8 mutation categories × 3 modes). Preserve the complete report, exact code/migration revision, per-case results and non-secret environment identity. The explicit-COMMIT case must show the observer saw the deferred-trigger lock wait before termination; the restore case must show distinct container identities and PostgreSQL system identifiers. Results from this command would cover only these synthetic scenarios and would not establish deployed identities, role memberships or capacity.

## Ordered assembly sequence

1. Preserve source-review evidence for exact code HEAD `315e83149b48fcef1d3ded7c5e2325d7c3fe7cd4`: PM Bridge returned `STATIC APPROVE`, no confirmed BLOCKER/MAJOR, and `PUSH NO-GO` pending runtime evidence. That evidence is now recorded for the distinct-cluster restore case only; the broader focused set remains incomplete.
2. Functional-test-reviewer and e2e-runner continue with the remaining accepted scenarios, recording exact-head outcomes. After evidence is complete, obtain an updated PM push decision; the current documentation commit does not change code or authorize push.
3. Collect effective-role/grant evidence and authenticated approver/evidence identity evidence on the authorized disposable environment. Do not query or change a live or production database for this packet.
4. Have the database/security lane record the workload envelope and capacity disposition, using `CAPACITY_DRILL.md` only as historical prototype context.
5. Assemble the exact-head evidence index, obtain gate-specific review, then update `governance/GATE_MANIFEST.json` only if the evidence actually satisfies the G1 exit criteria.

## Status boundary

Local push status: `NOT_READY`. The initial focused run at committed HEAD `4b9f3b08b4e75359b549bda75d6f6ec3307f248e` reported 46 passed and 1 failed because the reader directly called internal `living.assert_scope`. After the test-only correction in `69857fd`, `test_pg_dump_restore_to_distinct_postgres_cluster` passed under both test-agent owners on documentation HEAD `5588c06851340751fa574e182da0e9c9b03111e9`; the changed source file matches the Git blob `6bd93ccffaa473bf69d1463913df57c1c44b8a4a` at PM-reviewed code HEAD `315e83149b48fcef1d3ded7c5e2325d7c3fe7cd4`. Its live SHA-256 is `DD4F08C1BF5CC3270BB6E6A3C08EC30A73526C592D8F0AC7348EB11742CE66B5`. This proves only that restore case; the full focused set and formal G1 remain incomplete. The prior PM response was `STATIC APPROVE`, no confirmed BLOCKER/MAJOR, `PUSH NO-GO` pending runtime. A fresh PM push decision after the newly recorded runtime result is still needed. Formal G1 remains `NOT_PASSED`, production authorization is `NONE`, and Release 2 remains `NO-GO` pending its full gate evidence.
