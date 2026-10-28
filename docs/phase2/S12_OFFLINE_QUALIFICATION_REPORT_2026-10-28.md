# S12 offline qualification report (2026-10-28)

Scope: offline halves of the S12 exit scenarios against `src/business_ai_gateway/phase2/change/`. No PostgreSQL, no 1C, no COM.
Repository: `D:\Repo\ERP_MCP`, branch `codex/erp-mcp-autonomous-2026-10-21`, working-tree HEAD at run time `547a51d`.
Authority: EVALUATION_ONLY. Nothing here is a live or native-1C result.

## Commands and counts

| Step | Command (venv python) | Result |
| --- | --- | --- |
| 1. Baseline | `.venv\Scripts\python.exe -m pytest tests/phase2/test_change_offline.py tests/phase2/test_change_ledger_port.py tests/phase2/test_change_approval_digest2.py -q -p no:cacheprovider` | 545 passed, 34 skipped (all skips: `ERP_PHASE2_TEST_DSN` not set, PostgreSQL ledger-port tests; NOT_RUN) |
| 2. New file | `... -m pytest tests/phase2/test_s12_exit_scenarios_offline.py -q -p no:cacheprovider` | 369 passed |
| 3. Combined | the four files above in one invocation | 914 passed, 34 skipped, 0 failed |
| 4. Lint | `... -m ruff check tests/phase2/test_s12_exit_scenarios_offline.py` | All checks passed |
| 5. CR-395 re-run | `... -m pytest -q -p no:cacheprovider` over 50 files (test_change_*, test_s12_*, test_s14*, files importing `phase2.change`, `phase2.simulation`, `erp_mcp_private_writer`; `ERP_PHASE2_TEST_DSN` = own postgres:16.14 container) | 2143 passed, 6 skipped (test_change_ledger_dump_restore: needs r2-s13-dump-* containers), 0 failed |
| 6. CR-395 review-resolution re-run | one invocation, `-v -p no:cacheprovider -rs`, 56 files: test_change_offline / approval_digest2 / ledger_port, all test_s12_* (incl. the new `test_s12_review_resolutions_offline.py` and the live `test_s12_s13_com_clone_scenarios.py`), all test_s14*, `test_s13_budget_reservation_concurrency.py`, and non-SQL importers of the changed modules; `ERP_PHASE2_TEST_DSN` = own postgres:16.14 container (removed afterwards) | 2082 passed, 159 subtests passed, 0 failed, 0 skipped (667 s). New file: 116 tests; amendment file: 75; clone: 16; budget concurrency: 9; vat sql digest: 1 |

Regression status: the slow SQL/e2e suites and the S15 suites were not rerun at this head, and the combined regression is NOT claimed green.

Not run in step 6: the slow throwaway-database `test_change_*_sql.py` suites and the `test_s13_*_sql/e2e` files (about 7 s per test; a started run reached 2% in 17 minutes and was stopped). A grep shows none of them calls `parse_proposal`, `parse_writer_payload`, `BeginApplyEvidence` or `_change_helpers`, so the changed Python is not exercised there; their result is NOT_RUN, not PASS. `test_s15_*` was excluded by instruction.

The other `test_change_*_sql.py`, `test_change_ledger_dump_restore.py`, `test_change_registry_sql.py`, `test_change_sweeps_sql.py` files need PostgreSQL and were not run.

## Method and limits

The new file drives the real `apply_transition` engine through a small driver (`Svc`). A "write-port call" is one successful `MARK_DISPATCHED` (the only transition after which the writer may call). The "B snapshot" is a dict changed only by a fake port that refuses unless the record is `DISPATCHED`. The fake port is a stand-in, not a port test. E20 enumerates 47 deterministic interleavings (a model, not concurrency). Scenario ids are in test names (`test_eNN_*`) and in `SCENARIO_MAP`; integrity tests fail if a mapped node does not exist or a scenario test is unmapped.

## Per exit ID

| ID | Offline status | Offline evidence | NOT_RUN (live) |
| --- | --- | --- | --- |
| E4 | PARTIAL at exit-scenario level; PASS only for the measured component/live-clone subset | `test_e4_*` (7 tests), `test_t4_refusals`, `test_t6_refusals_per_guard` | PostgreSQL ledger integration; production evidence/content-hash derivation (UNKNOWN); production glue for 1C reads and executor-to-engine events |
| E5 | PASS | `test_e5_*` (4 tests incl. caller-class parametrization), cross-class matrix tests | token audience/scope, 1C rights |
| E6 | PASS (offline) | limit boundaries (exhausted vs exceeded), negative/non-decimal, window first/last instant and +03:00 offset, currency, VAT 0/10/20 with rate-consistent amounts, mixed VAT, scope, all arrival orders of the budget; total != lines+VAT refused as `AMOUNT_INCONSISTENT` on both parse paths (`test_s12_amendment_395_offline.py`, G1); closed period as `PERIOD_CLOSED` (G2) | real closed-period observation from 1C (no `period_closed` producer yet); contract currency lookup; VAT-inclusive convention vs the real 1C includes-VAT flag (open operator decision); concurrent reservations |
| E11 | PARTIAL | off writes once; unavailable store = STOP_EFFECTS for every subject; matrix tests | real store and port counter |
| E13 | PARTIAL | checkpoint/ownership-row failures give zero port calls and never APPLIED | raising audit sink, service layer, 1C snapshot |
| E14 | PARTIAL | own approval needed, parent verified, digest change, nonce replay, expiry, expired grant | posted flag and registrar rows in B |
| E15 | PASS (offline half) | closed catalogue, delete/pay fields refused | natural-language mapping above this package; E42 indirect paths |
| E20 | PASS (model) | 47 interleavings of approve/claim/begin with edit/revoke/role change, oracle written from the scenario | multi-process races |
| E23 | PARTIAL | version check before any call; edit inside compare-and-write gives PRE_WRITE refusal, FAILED_APPLY, reservation released | the real compare-and-write and B snapshot |
| E24 | PASS (offline) | queued: expired, `PERIOD_CLOSED` (with and without a digest change), `GRANT_EXHAUSTED`; window miss and oversized request stay `BUDGET_EXCEEDED`; running: write completes, reservation consumed, no new step; unknown outcome keeps reservation | real period state from 1C; SQL ledger still raises `BUDGET_EXCEEDED` for an exhausted grant (migrations not edited) |
| E29 | PARTIAL | no approve for the author class, spoofed fields refused, chat-like text is inert data | absence of an approve tool on the MCP surface; HTTP rejection |
| E32 | PARTIAL | 4 scopes, cross-company claim, cross-execution, revoked role, IdP outage (blank evidence refuses all 24 events), mixed-source refs | denial at the port, real IdP, altered queue row |
| E38 | PARTIAL | exact-limit chain create/post/unpost with invariant after each step, mixed currency, unknown keeps reservation | parallel processes, CT13 three-limit matrix on rows |
| E41 | PARTIAL | activation before each of 7 boundaries x 4 readings (incl. unavailable store); unwind; in-flight call; REVOKE voids | blocked real 1C call, operator in-flight list (G3) |
| E45 | PARTIAL | every illegal (state, event) pair over 11 states refused with record untouched; terminal states; unknown never a failure by time/expiry | status-reporting projection (G3) |

## Defects and gaps found

No defect was found in `src/business_ai_gateway/phase2/change`, and no source or existing test was changed. Two failures during authoring were wrong test expectations (guard order: `CLAIM_EXPIRED` precedes `APPROVAL_EXPIRED`; ref scope check precedes shape check) and were corrected in the new file.

- G1 (RESOLVED by CR-395, 2026-10-28): `parse_proposal` / `parse_writer_payload` now refuse a line whose amount differs from round(quantity x price, 2) or whose VAT differs from round(amount x rate / (100 + rate), 2) (VAT0/10/20; other codes: refused as AMOUNT_INCONSISTENT (review resolution)) with `AMOUNT_INCONSISTENT`. Evidence: `tests/phase2/test_s12_amendment_395_offline.py` (amount, VAT, half-up edges, zero rate, unknown code, wide operands, both paths) and `test_e6_total_amount_different_from_lines_plus_vat_is_refused_as_amount_inconsistent`. Open: VAT-inclusive convention requires the writer to set the 1C includes-VAT flag TRUE.
- Contract status of the new codes: `PERIOD_CLOSED` and `GRANT_EXHAUSTED` exist in the PYTHON model only. The SQL ledger still raises `BUDGET_EXCEEDED` for an exhausted grant (E38 asserts exactly that), no cross-layer parity test exists, and no real-1C producer of the period observation exists; no end-to-end qualification of these codes is claimed.
- G2 (RESOLVED in the Python model only, by CR-395): the registry has 39 codes; `PERIOD_CLOSED` (T6, only for a positively observed closed period) and `GRANT_EXHAUSTED` (reserved + consumed >= limit, positive request) are distinct. Evidence: `test_s12_amendment_395_offline.py`, `test_e24_*`, `test_t6_refusals_per_guard`, `test_t5_refusals_per_guard`. Not done: `period_closed` producer (1C read), SQL ledger emission of `GRANT_EXHAUSTED`.
- G3 (STILL OPEN): the package has no operator-facing in-flight/unresolved listing or status projection (E41, E45 parts).
