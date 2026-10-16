# Change record 074 — reconcile G1 evidence agents and correct DB policy note

## What changed

- Reconciled the G1 focused runtime set after read-only reviews by `functional-test-reviewer`, `e2e-runner`, and `database-reviewer`.
- Made `test_n2_dual_duty_login_cannot_promote` required for the distinct dual worker/promoter-membership database boundary.
- Made `test_major02_scope_rechecked_after_source_lock` required because G1-B04 includes revoked-scope denial and the earlier MAJOR-02 revoke-barrier finding remains relevant.
- Kept N3 commit-order and N5 sequential busy-response cases supplemental; aligned the candidate and focused-set tables accordingly. Added N7, N8 lifecycle, and killed lease-holder recovery to the focused B07 proposal.
- Documented that distinct-cluster restore does not prove role-membership chains or deployed login assumption paths.
- Added the E2E runner's exact proposed focused command and environment requirements. It is a plan only and remains unexecuted.
- Corrected `docs/sdlc/STATE.md`: workspace rules prohibit pytest, not database operations generally. Recorded that no DB capture was collected because `ERP_PHASE2_TEST_DSN` was unset and `psql` was unavailable in this environment.

## Why

The operator asked to use the appropriate test/E2E/database agents for evidence and pointed out that the workspace rules do not ban database work. Inspection confirmed the blanket DB prohibition existed only as an inaccurate statement in the SDLC state artifact; `D:\Repo\AGENTS.md` explicitly prohibits pytest and selected automated checks but contains no blanket database-operation prohibition. The test plan also had inconsistent required/supplemental classifications and an incomplete proposed command.

## Reviewers and evidence

- `functional-test-reviewer` / GPT-6 Luna, low: reconciled B04–B08 coverage and confirmed the required/supplemental selection.
- `e2e-runner` / GPT-6 Luna, low: prepared explicit focused pytest invocation, fixture prerequisites and evidence boundaries.
- `database-reviewer` / GPT-6 Luna, medium: reviewed DB role/grant, approver, transaction, crash and restore evidence boundaries; identified role-membership limitation in restore evidence.
- All three reviews were read-only. No tests, DB connection, migration, or Docker operation was run. A documentation whitespace diff check (`git diff --check`) was run; it emitted only Git's LF-to-CRLF conversion warnings.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/sdlc/STATE.md`
- `core/DECISION_LOG.md`
- `docs/phase2/CHANGE_RECORD_074.md`

## Verification state

- Focused test command is `NOT_RUN` because workspace rules prohibit pytest. The written command is not runtime evidence.
- Direct DB evidence was not collected: `ERP_PHASE2_TEST_DSN` was not configured and `psql` was unavailable. This is an environment dependency, not a policy prohibition.
- Any future DB operation must use an explicitly authorized disposable target and must not access production.
- G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`.
