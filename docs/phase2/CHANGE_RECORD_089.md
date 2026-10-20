# Change record 089 — reconcile G1 local-push reports with exact-tree evidence

## What changed

- Updated the Russian and English G1 local-push reports with the accepted exact-tree selected results: functional/multiprocessing 45 passed, 0 failed, 0 skipped; E2E explicit-COMMIT plus distinct-cluster restore 2 passed, 0 failed, 0 skipped.
- Recorded that the functional invocation used documentation HEAD `0800269ccf0e9899f1b6e707ac29164c91878c86`, with relevant test blobs matching code/test HEAD `a6263e4bafe69aedd14372f394d67da7b6fb3366`; the E2E invocation used detached exact code/test HEAD `a6263e4bafe69aedd14372f394d67da7b6fb3366`.
- Recorded the database-reviewer's exact-tree follow-up: no database BLOCKER/MAJOR, MAJOR-02 lock evidence confirmed, and the explicit-COMMIT scenario does not cover the post-WAL-commit/pre-acknowledgement gap.
- Preserved current decision states: fresh PM verdict pending, local push `PENDING_PM`, formal G1 `NOT_PASSED`, production authorization `NONE`, and Release 2 `NO-GO`.
- Corrected the report's MAJOR-02 description: `wait_event_type=Lock` and blocking PID are asserted; `wait_event=transactionid` is captured as metadata but not asserted.
- Refreshed the standard provenance and whole-page copy controls in both reports.

## Why

The previous reports described only the initial raw 45-case run and the later 24-case correction rerun. They omitted the subsequent complete exact-tree functional set and the paired E2E rerun, which left the current local-push evidence incomplete in the operator-facing handoff.

## Decisions and scope

- Latest functional evidence: 45 passed, 0 failed, 0 skipped over the selected 22 node IDs at documentation HEAD `0800269ccf0e9899f1b6e707ac29164c91878c86`. The MAJOR-02 test blob at both that docs HEAD and code/test HEAD `a6263e4bafe69aedd14372f394d67da7b6fb3366` is `ce5c2c4f86b4751b8f03744fff16831557887d4f`.
- Latest E2E evidence at detached code/test HEAD `a6263e4bafe69aedd14372f394d67da7b6fb3366`: `.venv\Scripts\python.exe -m pytest -q tests/phase2/test_g1_crash.py::test_terminate_backend_during_observed_explicit_commit tests/phase2/test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster`; result 2 passed, 0 failed, 0 skipped.
- Latest rerun durations and invocation-owned container identifiers were not available in the supplied run summaries and are not inferred.
- `py -3` initially failed because its configured Python 3.15 path did not exist. The same report utility was run successfully with `C:\Python314\python.exe`:
  - `C:\Python314\python.exe C:\Users\koros\.claude\tools\report_conform.py D:\Repo\ERP_MCP_R2\reports\G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html D:\Repo\ERP_MCP_R2\reports\G1_LOCAL_PUSH_STATUS_2026-10-16.html`
  - `C:\Python314\python.exe C:\Users\koros\.claude\tools\report_conform.py D:\Repo\ERP_MCP_R2\reports --check` — `all reports carry the mandated block`.
- This update changes reports only. It does not alter code, tests, databases, gate manifests, or production authorization. No push was performed.
- The shared document registry is refreshed separately after this report commit, following the repository's generated-index pattern.

## Review and verification state

- Report conformance completed successfully for both files; directory check passed.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- `.claude/` was preserved as unrelated untracked work.

## Contracts and paths

- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.html`
- `docs/phase2/CHANGE_RECORD_089.md`

## Acceptance

- The Russian and English reports carry the same exact-tree test and reviewer facts in localized form.
- Bounded COMMIT coverage is stated without implying the pre-acknowledgement window was tested.
- PM, formal G1, production, and Release 2 states remain accurate.
- Both reports include the mandated provenance/copy block and pass the report directory check.
