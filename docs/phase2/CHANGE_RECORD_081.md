# Change record 081 — record selected G1 runtime and MAJOR-02 evidence gap

> This is the point-in-time record of the raw selected run and the database-reviewer finding. The MAJOR-02 gap was later fixed and re-reviewed; current accepted evidence and status are recorded in `CHANGE_RECORD_083.md`.

## What changed

- Recorded the raw selected G1 functional and E2E execution results at code/test HEAD `73e4253b571fa45382af6f954f773e1eae5f91be` in the evidence plan, SDLC state, operator backlog and Russian/English status reports.
- Distinguished raw passing output from accepted acceptance evidence. The 24 MAJOR-02 parameter cases are `NOT_ACCEPTED` because the current test does not prove that the API reached the source-row-lock wait before grant revocation.
- Recorded the database-reviewer finding, exact test synchronization concern, required fix/rerun owner, pending silent-failure-hunter outcome, and continued PM push NO-GO.
- Preserved separate PASS claims only for the observed explicit-COMMIT case and distinct-cluster restore case.

## Why

The focused local runs produced passing output, but post-runtime database review found that the MAJOR-02 test's `sleep(0.7)` followed by `not task.done()` is not a synchronization barrier. The API may start after grant revocation, so the 24 passing parameter variants can miss the intended race and falsely appear to prove it. The evidence record must not treat those outputs as acceptance until the test proves the wait boundary and all 24 variants are rerun.

## Decisions and scope

- Exact code/test HEAD for the recorded raw results: `73e4253b571fa45382af6f954f773e1eae5f91be`.
- Functional-test-reviewer command shape: `.venv\Scripts\python.exe -m pytest -vv` with the 22 exact node IDs selected in `G1_EVIDENCE_PACKET_PLAN.md` (excluding the separately E2E-owned observed-COMMIT case and restore case). Environment: `ERP_PHASE2_TEST_DSN=postgresql://postgres:<redacted>@127.0.0.1:25279/postgres`, `ERP_PHASE2_REQUIRE_PG=1`, `ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1`. Raw outcome: 45 passed, 0 failed, 0 skipped in 57.13s. MAJOR-02 contributed 24 parameter cases.
- Functional source blobs at that HEAD: integration `e526e9c5c517555f0afb5940104ef97d99bc0f1b`; review2 `3c55ecf49918c7dce19ebba42fc0635bdacf2772`; hardening `7400a2e4289da931fb5983149b7e64af58dddbf4`; concurrency `4a5dd19f6e1da82f4f1c79ccd65831eb0f9f5ea4`.
- Functional fixture: disposable loopback PostgreSQL 16 container `r2-g1-db-rem-0ff89394cfe8`, Docker ID `6718d13f070c8023a1dc9b9d5270363786cfa182ff84fce2f5a357599fd1fee3`, token `0ff89394cfe84ebb8ded87395ac55c83`, port `25279`. Its exact container and volume were removed after the run. The DSN password is redacted and is not recorded.
- E2E-runner observed-COMMIT scenario: one exact test passed in 14.74s. Test blob `d899fe1b237f4d637e085ff6327f756f915dc369` matches the reviewed code HEAD. The fixture container was `r2-s13-dump-8e58d44ae1c9-a`, Docker ID `8d3165f1203e8255a85fdd6322ed17da04f624ad4cb56ddce0565c98582b6c17`, PostgreSQL system identifier `7697156701606625318`; it was cleaned. The observer saw PID 131 active on COMMIT and the advisory lock ungranted before termination; rollback assertions passed.
- Distinct-cluster restore remains independently passed by both test-agent roles as detailed in `CHANGE_RECORD_080.md`.
- Static code-reviewer inspected all 40 changed paths in `origin/main..HEAD` (23 commits) and found no code BLOCKER/MAJOR or direct regression. Database-reviewer then reported the MAJOR-02 evidence gap above. Silent-failure-hunter post-runtime outcome is pending.
- PM reply `b7f84f7a-3875-4ee1-b839-2556c5eb1f8a` approved the correction/runtime but retained `PUSH NO-GO` until the complete accepted focused evidence set was available. Because MAJOR-02 evidence is not accepted, no new PM decision is requested yet and no push was performed.
- Functional-test-reviewer owns fixing test synchronization and rerunning all 24 MAJOR-02 variants. E2E-runner and database-reviewer should review the corrected observation boundary and results before exact-head PM review.
- Formal G1 remains `NOT_PASSED`; production authorization is `NONE`; Release 2 remains `NO-GO`. This is a documentation-only record and does not update the gate manifest or production state.

## Review and verification state

- Raw runtime results above were produced by the authorized functional-test-reviewer and e2e-runner. The 24 MAJOR-02 outcomes are raw passes but `NOT_ACCEPTED` as criterion evidence pending a test correction and complete rerun.
- Fresh database-reviewer finding: MAJOR evidence gap in the test's lock-wait synchronization. Fresh silent-failure-hunter result: pending; no outcome is inferred.
- No tests, checks, builds, migrations, or database operations were run for this documentation update. Only the document registry generator is permitted for this documentation task.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/sdlc/STATE.md`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.html`
- `governance/DOCUMENT_REGISTRY.md`

## Acceptance

- The 45-case functional run is recorded as raw observed output; MAJOR-02's 24 variants are explicitly `NOT_ACCEPTED` until corrected and rerun.
- The explicit-COMMIT and restore passes remain scoped to their independently proven scenarios.
- The database-reviewer finding, exact fix/rerun owner, PM NO-GO state and pending silent-failure-hunter outcome are explicit.
- Formal G1 and production authorization are not upgraded by local tests or this documentation commit.
