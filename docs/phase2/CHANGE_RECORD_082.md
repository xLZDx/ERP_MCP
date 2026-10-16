# Change record 082 — observe the MAJOR-02 lock boundary

## What changed

- Replaced the fixed 700 ms delay in `test_major02_scope_rechecked_after_source_lock` with a bounded PostgreSQL activity observer.
- Before committing the competing transaction, the observer now requires the exact API backend to be active on the selected API statement, waiting on a PostgreSQL lock, and blocked by the backend holding the revocation/source-lock transaction.
- If that boundary is not observed within 10 seconds, the scenario cancels the pending API call, rolls back both transactions, and reports `NOT_RUN` through an explicit pytest skip. It cannot pass without the observed boundary.
- The eight mutation categories and three modes remain unchanged, retaining all 24 parameter combinations.

## Why

The prior fixed sleep and `task.done()` assertion did not prove that the API had reached the source-row lock before revocation committed. A delayed API could start after revocation and fail at its initial scope check, falsely passing the test without exercising the post-lock recheck.

## Decisions and scope

- The observer correlates `pg_stat_activity` for the API backend with `pg_blocking_pids` and the revocation transaction's backend PID. It does not assume a particular PostgreSQL lock wait event name.
- The transaction ordering and expected outcomes after the lock boundary are preserved.
- Only the test file is changed. No product code, SQL migration, or database state is changed by this commit.
- Runtime evidence is pending at commit time and will be recorded separately against the exact committed test blob. No result is inferred from this source change.

## Review and verification state

- Manual source review confirms that the test cannot proceed to the post-revocation assertions until the API statement, lock wait, and blocker PID are observed together.
- No test, lint, build, migration, or other check was run before this coding commit. The subsequent focused run is limited to the 24 MAJOR-02 parameter combinations on a newly created invocation-owned loopback PostgreSQL 16 instance.

## Contracts and paths

- `tests/phase2/test_g1_postgres_integration_review2.py::test_major02_scope_rechecked_after_source_lock`
- `db/phase2/003_security_hardening.sql` — existing role-scope epoch trigger and post-lock scope recheck behavior exercised by this test

## Acceptance

- Each of the 24 cases must observe the API lock boundary before the revocation transaction commits; cases that fail to observe it are `NOT_RUN`, never `PASS`.
- The focused runtime result, exact test blob, PostgreSQL fixture identity, and cleanup state will be reported after execution.
