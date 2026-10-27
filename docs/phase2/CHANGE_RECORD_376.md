# Change Record 376 - SQL-backed phase 2 tests run for the first time since migration 018

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; the functional-test-reviewer agent ran the suites and fixed tests; the coordinator
  started the disposable database and reviewed the diff.
- Changes: `tests/phase2/test_change_approval_digest2.py`, `test_change_hardening_d_sql.py`, `test_change_hardening_e_sql.py`,
  `test_change_hardening_h_sql.py`, `scripts/phase2_capacity_drill.py`, and adds `tests/phase2/test_s14_vat_amount_sql_digest.py`.
  Nothing in `src/` or `db/` changed.

## Why

Change Reviews 374 and the GPT-PM gate left one condition open: the SQL digest for the six-field line was never compared with the
Python digest, because the 602 skipped tests need `ERP_PHASE2_TEST_DSN`. An own disposable Postgres 16.14 container
(`--rm`, local port only; other containers untouched) was started and the whole `tests/phase2` directory was run against it.

## Results (FACT: saved run lines, DSN and password masked in the saved copies)

- Full SQL-backed run: 13 failed, 7761 passed, 15 skipped, 13 errors, 159 subtests passed in 50 minutes 20 seconds.
- No failure came from `vat_amount`. The 13 errors are the documented direct-run harness scripts (`fixture 'db'`/`'led'` not found).
- 11 failures were stale tests that still expected pre-migration-018 behavior: the wire payload must be the exact canonical bytes
  (`SCHEMA_INVALID` otherwise), 18 migration files instead of 17, the extra `wire_payload_sha256` event key, and a receipt signed
  over the wire payload sha instead of the typed payload digest. They were updated to the 018 contract read from the SQL, with
  assertions added (not weakened); none lost its intent.
- 2 failures came from `scripts/phase2_capacity_drill.py` importing names removed from the test harness. The drill now picks the
  single running container publishing the DSN port, which must be named by `ERP_PHASE2_TEST_CONTAINER` or start with
  `r2-s13-dump-`, and still proves the cluster by comparing `system_identifier`; anything else fails closed.
- After the fixes, the six touched files: 71 passed, 0 failed, 0 skipped, 0 errors (4 minutes 52 seconds). The full 50-minute run
  was not repeated after the fixes.
- New `test_s14_vat_amount_sql_digest.py`: the Python and SQL payload digests are equal for `vat_amount` 0, 3.5 and 1234.56 with and
  without a target version, the canonical JSON is byte-equal, and a legacy five-field line collides with no six-field digest. It
  skips with NOT_RUN when no DSN is set.

## Not established

- UNKNOWN: whether other previously passing tests are affected by the drill change (not rerun in full); behavior on the
  production database engine version; the 15 skips (no `r2-s13-dump-*` container, cluster flag off, no `RLIMIT_AS` on Windows).
- The writer stays UNQUALIFIED and disabled. NOT_RUN: GPT-PM review of this record.
