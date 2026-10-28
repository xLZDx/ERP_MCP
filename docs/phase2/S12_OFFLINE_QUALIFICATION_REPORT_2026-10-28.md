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

The other `test_change_*_sql.py`, `test_change_ledger_dump_restore.py`, `test_change_registry_sql.py`, `test_change_sweeps_sql.py` files need PostgreSQL and were not run.

## Method and limits

The new file drives the real `apply_transition` engine through a small driver (`Svc`). A "write-port call" is one successful `MARK_DISPATCHED` (the only transition after which the writer may call). The "B snapshot" is a dict changed only by a fake port that refuses unless the record is `DISPATCHED`. The fake port is a stand-in, not a port test. E20 enumerates 47 deterministic interleavings (a model, not concurrency). Scenario ids are in test names (`test_eNN_*`) and in `SCENARIO_MAP`; integrity tests fail if a mapped node does not exist or a scenario test is unmapped.

## Per exit ID

| ID | Offline status | Offline evidence | NOT_RUN (live) |
| --- | --- | --- | --- |
| E4 | PASS | `test_e4_*` (7 tests), `test_t4_refusals`, `test_t6_refusals_per_guard` | ledger rows and B snapshot (PostgreSQL + 1C) |
| E5 | PASS | `test_e5_*` (4 tests incl. caller-class parametrization), cross-class matrix tests | token audience/scope, 1C rights |
| E6 | PARTIAL | limit boundaries, negative/non-decimal, window first/last instant and +03:00 offset, currency, VAT 0/10/20, mixed VAT, scope, all arrival orders of the budget | closed-period from 1C settings; contract currency lookup; total != lines+VAT refusal (G1, G2); concurrent reservations |
| E11 | PARTIAL | off writes once; unavailable store = STOP_EFFECTS for every subject; matrix tests | real store and port counter |
| E13 | PARTIAL | checkpoint/ownership-row failures give zero port calls and never APPLIED | raising audit sink, service layer, 1C snapshot |
| E14 | PARTIAL | own approval needed, parent verified, digest change, nonce replay, expiry, expired grant | posted flag and registrar rows in B |
| E15 | PASS (offline half) | closed catalogue, delete/pay fields refused | natural-language mapping above this package; E42 indirect paths |
| E20 | PASS (model) | 47 interleavings of approve/claim/begin with edit/revoke/role change, oracle written from the scenario | multi-process races |
| E23 | PARTIAL | version check before any call; edit inside compare-and-write gives PRE_WRITE refusal, FAILED_APPLY, reservation released | the real compare-and-write and B snapshot |
| E24 | PARTIAL | queued: expired, digest (period analogue), exhausted grant; running: write completes, reservation consumed, no new step; unknown outcome keeps reservation | PERIOD_CLOSED / GRANT_EXHAUSTED codes absent (G2); real period state |
| E29 | PARTIAL | no approve for the author class, spoofed fields refused, chat-like text is inert data | absence of an approve tool on the MCP surface; HTTP rejection |
| E32 | PARTIAL | 4 scopes, cross-company claim, cross-execution, revoked role, IdP outage (blank evidence refuses all 24 events), mixed-source refs | denial at the port, real IdP, altered queue row |
| E38 | PARTIAL | exact-limit chain create/post/unpost with invariant after each step, mixed currency, unknown keeps reservation | parallel processes, CT13 three-limit matrix on rows |
| E41 | PARTIAL | activation before each of 7 boundaries x 4 readings (incl. unavailable store); unwind; in-flight call; REVOKE voids | blocked real 1C call, operator in-flight list (G3) |
| E45 | PARTIAL | every illegal (state, event) pair over 11 states refused with record untouched; terminal states; unknown never a failure by time/expiry | status-reporting projection (G3) |

## Defects and gaps found

No defect was found in `src/business_ai_gateway/phase2/change`, and no source or existing test was changed. Two failures during authoring were wrong test expectations (guard order: `CLAIM_EXPIRED` precedes `APPROVAL_EXPIRED`; ref scope check precedes shape check) and were corrected in the new file.

- G1 (product/spec gap, not fixed): `parse_proposal` accepts a line `amount` / `vat_amount` that disagrees with quantity * price and the VAT rate. The numbers are digest-bound, so the approver sees them, but E6 "a total different from lines+VAT" is not refused offline. Needs a spec decision (rounding and VAT rules) before code.
- G2: the 36-code registry has no `PERIOD_CLOSED` or `GRANT_EXHAUSTED`; the model reports these as `DIGEST_MISMATCH` and `BUDGET_EXCEEDED`. The plan text names them; decide whether to add codes or amend the plan.
- G3: the package has no operator-facing in-flight/unresolved listing or status projection (E41, E45 parts).
