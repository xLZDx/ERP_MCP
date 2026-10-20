# Change record 145 — disposable PostgreSQL evidence for migrations 023–024

## Goal and scope

Record designated functional and E2E agent evidence for the timeout-restoration follow-up in migration 024. Source HEAD under test was `4f421280d9fbfbd06016acc279b6ef900a9f6591`. The source migration and application code were not changed by this evidence commit.

## Changes and affected paths

- Updated `tests/phase2/test_s13_migration023.py`, owned and executed by `functional-test-reviewer`.
- Updated `tests/phase2/test_s13_migration023_e2e.py`, owned and executed by `e2e-runner`.
- Added this detailed evidence record, linked to CR144's `db/phase2/024_restore_caller_lock_timeout.sql`.

## Functional PostgreSQL evidence

- Exact command: `$env:ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS='1'; & .\.venv\Scripts\python.exe tests/phase2/test_s13_migration023.py`.
- Runtime: Python 3.14.3; PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1); invocation-owned disposable Docker cluster.
- Test SHA-256: `8B7AFA442D05DB53035539B1CA2F370D2E8D0C87CACB9513C7FA2BDB9D7F4982`.
- Full chain 001–024 applied. Existing CR142 refusal, unchanged-state, idempotency, and lock-cap scenarios passed. The default event wait completed in 6.203 seconds against the test's under-seven-second tolerance; caller-selected 150 ms waits completed in 1.196, 0.911, and 0.414 seconds for event, permit, and writer paths, each under the existing 1.5-second test tolerance.
- After successful lifecycle fence-row lock paths, `SHOW lock_timeout` restored the caller value (`0` and `150ms`) for event, permit, and writer paths. A lock-timeout error inside a savepoint restored `150ms`; the enclosing transaction then successfully executed `SELECT 1`.
- The harness removed its own container and volume. The test agent made no source or migration edits.

## E2E PostgreSQL evidence

- Exact command: `\.venv\Scripts\python.exe tests\phase2\test_s13_migration023_e2e.py`.
- Runtime: PostgreSQL 16.14 (`postgres:16`, image ID `sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae`); Python 3.14.3; asyncpg 0.32.0; Docker client/server 29.5.2.
- Test SHA-256: `F4AC4AECC4627CE712DE82C88C4AE3FF31620F695E52179809339409D642638A`.
- Full chain 001–024 applied. A successful writer-fence read restored the transaction setting from the capped path to `9s`. The worker denial and privileged recovery refusal remained fail-closed with unchanged state. Independent-session contention returned SQLSTATE `55P03` in 5.389 seconds.
- The harness confirmed that its owned container and anonymous volume were absent after completion and that the image ID was unchanged.

## Iteration history and limitations

- Earlier test invocations exposed test-harness issues: migration/setup ordering, reuse of an unresolved fixture, an invalid transaction-state method in teardown, and one transient client-observed 150 ms lock timeout exceeding the strict 1.5-second threshold. The designated agent corrected fixture/teardown ownership and repeated the focused run without weakening thresholds; the final functional invocation passed. A parse-only E2E attempt stopped before creating a container; the corrected E2E invocation passed.
- Evidence is limited to the tested migration behavior on disposable PostgreSQL. It does not prove physical-writer or 1C coverage, all ledger mutation paths, service admission integration, a READY transition, or formal S13 acceptance.
- No shared or production database was accessed. Migrations 022–024 remain unapplied outside the disposable test clusters. Formal S13 is `NOT_STARTED / NOT_APPROVED`; G1–G8 are `NOT_PASSED`; Release 2 is `NO-GO`; production authorization is `NONE`.
- Exact-head DB, reliability, and security reviews completed at `3a5f71d`; their results and qualifications are recorded in the CR146 reconciliation below.

## Review qualification (added by CR146)

The DB reviewer confirmed that the savepoint scenario proves the outer transaction remains usable with its prior timeout after the failed statement is rolled back. It does not isolate the restoration executed by migration 024's exception handler from the setting rollback caused by the savepoint itself. Migration source statically restores the prior value before rethrowing; treat the functional runtime assertion as savepoint/outer-transaction evidence, not isolated proof of that handler branch. CR146 records this qualification and the exact-head DB/reliability/security review outcomes.

## Ownership and next action

- The operator remains accountable for delegated project closure; GPT/Codex executes the local work.
- `functional-test-reviewer` and `e2e-runner` own the tests and reported runs. `database-reviewer`, `reliability-reviewer`, and `security-reviewer` own the next independent exact-head reviews.
- Continue only local engineering until every S13 acceptance item and required formal gate has evidence; fresh GPT approval for the exact final branch head is still required before push.
