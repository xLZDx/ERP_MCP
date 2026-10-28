# Change Record 396 - E38 parallel budget-reservation test and pytest collection fix

## Ownership and scope

- Date: 2026-10-28. Tests written and run by the functional-test-reviewer agent on its own disposable PostgreSQL 16.14 container (removed afterwards). No source or migration changed.
- Adds `tests/phase2/test_s13_budget_reservation_concurrency.py` and `tests/phase2/_s13_budget_worker.py`; renames 13 script helpers (`test_*` -> `run_*`) in `test_s13_checkpoint_suffix_functional.py`, `test_s13_migration020.py`, `test_s13_migration022_e2e.py`, `test_s13_migration023.py`; appends a follow-up section to `S13_PG_QUALIFICATION_REPORT_2026-10-28.md`.

## Evidence (agent-run, no mutation runs)

- 9 new tests pass (about 78 s): 10 spawned OS processes race real `change_ledger.claim`; amount limit at limit-1, limit, limit+1 admits exactly 4, 5, 5 of 10; count limits 4, 5, 6 admit exactly 4, 5, 6; every loser gets BUDGET_EXCEEDED; reserved total never exceeds the limit; one RESERVED row and one CLAIMED event per winner; verify_chain ok; a rolled-back or killed holder frees its slot; same-change replay reserves once.
- Five affected files: 10 passed, 0 errors, 0 skips with ERP_PHASE2_REQUIRE_PG=1; the four renamed files still print PASS when run as scripts.

## Not established

- Mixed currencies across processes, partially consumed POST amounts, grant revoke racing a claim. Mutation evidence NOT_RUN by operator rule. GPT-PM review NOT_RUN.
