# Change record 144 — restore caller lock timeout after lifecycle fence read

## Goal and scope

Address reliability review MINOR from exact HEAD `7af9ecda9cccb0eddf77e3b2d37fc22f1e0f0c3d`: migration 023 set a transaction-local five-second `lock_timeout`, which remained active for unrelated later lock acquisitions in the caller's transaction. The safety cap should apply only while acquiring the lifecycle fence row.

## Changes and affected paths

- Added `db/phase2/024_restore_caller_lock_timeout.sql`, an additive migration requiring the complete 001–023 chain.
- Added private `change_ledger.lock_lifecycle_fence(text,text)`, which preserves the lifecycle `FOR SHARE` lock through transaction end but restores the caller's prior `lock_timeout` immediately after acquisition. An exception block restores it when acquisition fails and re-raises the original error.
- Replaced the event, dispatch-permit, and writer-epoch functions to use the private reader; preserved tenant/company scope checks, role checks, row-lock mode, lifecycle refusals, and writer permit/epoch validation.
- Updated the lifecycle design, S13 acceptance map, and operator backlog to capture the reliability finding and pending verification state.

## Verification state

- Migration 024 is source-only at this change record's preparation. Disposable PostgreSQL functional/E2E tests and DB/reliability/security review are `NOT_RUN` pending completion of coding and the designated agent phase.
- CR142 migration 023 remains unchanged. CR143's focused tests and reviews remain evidence for migration 023 at its exact recorded source HEAD; they do not verify migration 024.
- Do not apply migrations 022–024 to a shared or production database. No shared/live database was accessed.

## Known limits and acceptance

- This change bounds acquisition wait; it does not bound how long a transaction may hold the lifecycle row lock.
- The SQL fence still does not prove that every physical writer uses the epoch check or that an external call remains covered until independently proven completion. No READY transition is added; recovery remains fail-closed.
- Formal S13 remains `NOT_STARTED / NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`.

## Ownership and next action

- The operator remains accountable for delegated project closure; GPT/Codex implements the local change.
- `functional-test-reviewer` and `e2e-runner` own tests for successful timeout restoration, preservation of shorter caller timeouts, timeout errors and transaction-local restoration. `database-reviewer`, `reliability-reviewer`, and `security-reviewer` own fresh reviews of the resulting exact head.
- Keep production activation and push behind the existing external/final GPT approval gates. No production or shared-database action is authorized by this local migration.
