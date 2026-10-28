# Change Record 394 - S12 offline and S13 PostgreSQL qualification runs at the current head

## Ownership and scope

- Date: 2026-10-28. Test authoring and execution by the functional-test-reviewer and e2e-runner agents; the coordinator ran no tests.
- Adds `tests/phase2/test_s12_exit_scenarios_offline.py`, `docs/phase2/S12_OFFLINE_QUALIFICATION_REPORT_2026-10-28.md`, `docs/phase2/S13_PG_QUALIFICATION_REPORT_2026-10-28.md` and `docs/phase2/artifacts/S13_PG_GRANTS_MATRIX_2026-10-28.json`. No source or migration file changed.

## Evidence (agent-run, no mutation runs)

- S12 offline: 914 passed, 34 skipped (PostgreSQL ledger-port tests, NOT_RUN there), 0 failed; ruff clean. Offline halves: E4, E5, E15, E20 PASS; E6, E11, E13, E14, E23, E24, E29, E32, E38, E41, E45 PARTIAL with their live halves named NOT_RUN in `SCENARIO_MAP`.
- S13 PostgreSQL 16.14 in a task-owned container (removed afterwards): migrations 001-027 applied, 027 re-applied clean on an empty chain; effective grants measured per role with SET ROLE (no PUBLIC EXECUTE, no direct table writes, add_role_scope not runtime-executable, the private writer role executes 13 of 57 private_writer functions, the evidence-ingest role executes none). DSN-backed batch 957 passed, 2 environmental failures (container name expected by capacity-smoke; passed on a correctly named container). Harness-cluster batch 212 passed, 13 collection errors from script helpers named test_*(db, led) that pytest collects; run as scripts all 8 print PASS. Dump/restore 6 of 6.

## Gaps found, not fixed (need a decision)

- G1: parse_proposal accepts an amount or vat_amount that disagrees with quantity x price and the VAT rate (E6).
- G2: no PERIOD_CLOSED or GRANT_EXHAUSTED error codes; they surface as DIGEST_MISMATCH and BUDGET_EXCEEDED.
- G3: no operator list of in-flight changes or status function (E41, E45).
- E38 parallel budget reservation on the change ledger: no multi-process test exists.

## Not established

- Every live-1C half, the external anchor store, production keys, real concurrency for E20. GPT-PM review NOT_RUN.
