# Change Record 398 - review fixes for the S12 amendment (CR-395)

## Ownership and scope

- Date: 2026-10-28. Two independent read-only reviews (python-reviewer, silent-failure-hunter) of the CR-395 diff found 0 BLOCKER, 5 MAJOR, 4 MINOR. Fixes by the implementation-engineer; tests by the functional-test-reviewer; the coordinator ran no tests.

## Changes

- `BeginApplyEvidence.period_observed_open` (default False) must be True for BEGIN_APPLY; closed -> PERIOD_CLOSED, absent observation -> DIGEST_MISMATCH (the engine no longer fails open on a missing period observation).
- An unknown `vat_rate_code` is refused as AMOUNT_INCONSISTENT; `vat_rate_percent_table()` exposes the engine table and a test compares it to `com_vat_table`.
- ArithmeticError inside the amount check returns SCHEMA_INVALID; parse_proposal, _parse_draft and parse_writer_payload cannot raise from it.
- New `src/erp_mcp_private_writer/refusal_mapping.py`: `map_executor_refusal(code, outcome_unknown)` over all 17 executor refusal codes; unknown codes and outcome_unknown map to CALL_UNKNOWN, only a known pre-write refusal maps to REFUSED_BEFORE_WRITE.
- Amendment documents: SQL ledger out of scope (still raises BUDGET_EXCEEDED until a new migration), VAT-on-top documents unsupported, production binding must set the includes-VAT constant TRUE.
- Clone scenarios now use the real mapping function and a write-counting connection (zero writes on refused paths, positive in the control run).

## Evidence (agent-run, no mutation runs)

- One invocation over 56 files: 2082 passed, 159 subtests passed, 0 failed, 0 skipped (116 new tests in `test_s12_review_resolutions_offline.py`, 75 in the amendment file, 16 live clone tests, 9 budget-concurrency tests), PostgreSQL 16.14 on a task-owned container (removed). The slow SQL/e2e suites (`test_change_*_sql.py`, `test_s13_*` SQL/e2e) were not rerun after these fixes; a grep shows none imports the changed parsers or helpers, so their last green run (CR-394, 957 passed) stands but is not re-proved at this head.

## Contract status (no end-to-end claim)

- `PERIOD_CLOSED` and `GRANT_EXHAUSTED` exist in the PYTHON model only. The SQL ledger still raises `BUDGET_EXCEEDED` for an exhausted grant (E38 asserts exactly that), no cross-layer parity test exists, and no real-1C producer of the period observation exists. No end-to-end qualification of these codes is claimed.
- E4 and E25 are relabelled: PARTIAL at exit-scenario level; PASS only for the measured component/live-clone subset. Not run / unknown: PostgreSQL ledger integration (E25 uses FakeLedger), production evidence/content-hash derivation, production glue for 1C reads and executor-to-engine events.
- The slow SQL/e2e suites and the S15 suites were not rerun at this head; the combined regression is NOT claimed green.

## Still open

- Producers for BudgetCheck.EXHAUSTED and the period observation from real data; SQL migration for the new codes; G3 (operator list of in-flight changes, status function). GPT-PM review NOT_RUN.
