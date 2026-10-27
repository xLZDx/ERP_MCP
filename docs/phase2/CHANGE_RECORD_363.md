# Change Record 363 - classification of skipped phase 2 tests

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Documentation only. No source or test file is changed. Basis: a static search of every skip call in `tests/phase2`
  (16 call sites in 13 files); no test was run for this record.

## Classification (FACT: from the skip call sites)

| Skip cause | Where | Class | Meaning |
|---|---|---|---|
| `ERP_PHASE2_TEST_DSN` not set | `test_ed25519_sql.py`, `test_g1_postgres_integration*.py`, `_pg_harness.py`, `test_change_ledger_dump_restore.py` | environment-gated | Runs only against a disposable PostgreSQL; the skip text starts with `NOT_RUN`, so the report cannot read it as a pass. |
| DSN shape (no password / no host) | `test_g1_capacity_smoke.py` | environment-gated | Negative-path tests need a URL DSN. |
| Backend not observed waiting on a lock within the timeout | `test_g1_crash.py`, `test_g1_postgres_integration_review2.py` | timing-gated | The skip says `NOT_RUN`; a skip here means the race was not reproduced, not that the guard held. |
| Trusted `citext` unavailable in the disposable image | `test_s13_current_turn_sql.py` | image-gated | Needs an image that permits trusted extension creation. |
| Platform | `test_safe_parser.py` (RLIMIT_AS is POSIX only; message pipes are Windows only), `test_ct14_inventory_script_input_boundary.py` (needs Windows PowerShell) | platform-gated | Each pair covers both platforms; one half always skips. |
| Not every guard test ran in the session | `test_g1_guard_mutations.py` | summary-only | Skips the summary table when the guard tests did not all run. |

## Not established

- UNKNOWN: the exact split of the 602 skips among these classes; it needs a run with `-rs`, which the coordinator does not
  perform (development rule: tests are run by the named test agents).
- The two lock-timing skips are the only ones where a skip can hide a failing guard; they should be read as NOT_RUN.

## Verification state

- RUN: static search only. NOT_RUN: any test.
