# Change record 083 — close the MAJOR-02 test-evidence gap

## What changed

- Recorded the test correction and accepted 24-case rerun for MAJOR-02 in the G1 evidence plan, backlog, SDLC state and Russian/English local-push reports.
- Reconciled the earlier raw 45-case functional run and its later database-review finding with the corrected test evidence.
- Recorded the database-reviewer confirmation, silent-failure-hunter limitations, static code-review result and current PM decision dependency.
- Regenerated the document registry. This record and the documentation updates are a local docs-only commit; no test code is changed here.

## Why

The previous MAJOR-02 test used a delay and task-state check that did not prove the API request had reached the source-row-lock wait before the revoke transaction committed. Database-reviewer correctly rejected those 24 results as acceptance evidence. The functional-test-reviewer changed the test to expose and assert the actual lock-wait boundary, reran the complete parameter matrix, and the database-reviewer confirmed the original evidence gap was closed. The documentation now records that sequence without erasing the rejected raw result.

## Decisions and scope

- Current code/test HEAD: `a6263e4bafe69aedd14372f394d67da7b6fb3366`.
- Functional-test-reviewer changed `tests/phase2/test_g1_postgres_integration_review2.py` in code commit `a6263e4bafe69aedd14372f394d67da7b6fb3366`, linked to `CHANGE_RECORD_082.md`. At that HEAD, test blob is `ce5c2c4f86b4751b8f03744fff16831557887d4`; the pre-fix blob was `3c55ecf49918c7dce19ebba42fc0635bdacf2772`.
- The corrected test observes the exact API SQL active, `wait_event_type=Lock`, and `pg_blocking_pids` containing the revoke backend before committing the revoke transaction. It records `wait_event=transactionid` as observed metadata but does not assert that subtype. Every parameter case records the asserted observer proof. If the boundary cannot be observed within its bounded timeout, the test cancels the query, rolls back, and reports `NOT_RUN` instead of passing.
- Functional-test-reviewer ran all 24 MAJOR-02 cases: 24 passed, 0 failed, 0 skipped in 16.56 seconds. Example observer evidence: API PID 103; revoke PID 111; blocking PID list `[111]`.
- Test environment: disposable PostgreSQL 16, loopback-only container `r2-g1-major02-fc4656ff7646`, Docker ID `4c1b46bb1c2fe381b78744f94478c2ace7c7b6e53299a439c0db8434c47b3c6f`, invocation token `fc4656ff764647008ee273aae33a4e0d`, port `11069`. The exact owned container and volume were removed after the run.
- Database-reviewer re-reviewed the correction and confirmed that the original MAJOR evidence gap was resolved. Silent-failure-hunter found no BLOCKER/MAJOR and confirmed the explicit observer conditions prevent false PASS. That review was read-only and did not rerun tests; it noted that the `wait_event` subtype is not directly asserted, while `pg_blocking_pids` is. Static code-reviewer inspected all 40 changed paths in `origin/main..HEAD` (23 commits) and found no code BLOCKER/MAJOR or direct regression.
- The other selected runtime results remain separately scoped: the initial broad functional run at `73e4253b571fa45382af6f954f773e1eae5f91be` reported 45 passed, 0 failed, 0 skipped in 57.13 seconds across 22 node IDs, but its 24 MAJOR-02 cases were not accepted until corrected and rerun; e2e-runner passed observed explicit-COMMIT in 14.74 seconds; functional-test-reviewer and e2e-runner passed the distinct-cluster restore scenario as recorded in `CHANGE_RECORD_080.md`. The corrected 24 cases replace the invalid MAJOR-02 evidence from the earlier broad run.
- PM reply `b7f84f7a-3875-4ee1-b839-2556c5eb1f8a` is still the latest decision and said `PUSH NO-GO` until the selected evidence was complete. Runtime and relevant specialist evidence are now complete, but no fresh PM decision for the exact current HEAD is recorded. No push was performed.
- Formal G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`. Local selected tests do not supply production identity, grants or capacity evidence and do not upgrade the formal gate.

## Review and verification state

- Functional-test-reviewer authored/executed the focused 24-case correction; database-reviewer confirmed the prior evidence gap is resolved.
- E2E evidence and static code-review evidence are scoped as listed above; silent-failure-hunter reviewed read-only and did not rerun the tests.
- No tests, checks, builds, migrations or database operations were run for this documentation update. Only the document registry generator was run.

## Contracts and paths

- `tests/phase2/test_g1_postgres_integration_review2.py` (code change already committed in 082; not modified by this documentation commit)
- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/sdlc/STATE.md`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.html`
- `governance/DOCUMENT_REGISTRY.md`

## Acceptance

- MAJOR-02 is marked accepted only for the corrected 24-case execution with observer proof and database-reviewer confirmation.
- The earlier 45-case output is preserved as a raw run; its original 24 MAJOR-02 variants are not counted as accepted evidence.
- Explicit-COMMIT and restore outcomes remain separate and unchanged.
- Push remains pending a fresh exact-head PM decision; formal G1 remains `NOT_PASSED` and production authorization remains `NONE`.
