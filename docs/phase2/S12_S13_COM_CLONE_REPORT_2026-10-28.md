# S12/S13 live-1C halves on the disposable clone (2026-10-28)

Scope: live halves of exit scenarios E4, E14, E23, E25, E41. Clone identity: `818HA_p2diff` (name only; the `ct14_common.guard` refuses any other base).
Authority: EVALUATION_ONLY. Branch `codex/erp-mcp-autonomous-2026-10-21`; no commit was made by this work.
Test file: `tests/phase2/test_s12_s13_com_clone_scenarios.py` (13 live tests + 3 scenario-map tests).

## Safety model actually enforced

- Every document write is inside `НачатьТранзакцию` ... `ОтменитьТранзакцию` (context manager `rolled_back_txn`, which also asserts that no transaction stays active).
- All writes use `CT14_NARROW` (role `CT14Писатель`). The administrator account is used only for `ct14_narrow_ops.prepare_user` (existing setup, resets the narrow account's roles and password) and for read-only snapshots.
- The writer is the real `execute_create_draft`. No POST, no UNPOST, no hard delete anywhere in the file.
- Per-test bracket (fixture `bracket`): before and after, the administrator connection snapshots (a) the row count of all 208 document types, (b) a hash over key fields and data version of all supplier receipts, (c) the number of leftover test documents (incoming number prefix `S12S13-`). Any difference fails the test and stops the remaining tests.

## Commands and results

| Step | Command (venv python, from `D:\Repo\ERP_MCP`) | Result |
| --- | --- | --- |
| Run 1 | `.venv\Scripts\python.exe -m pytest tests/phase2/test_s12_s13_com_clone_scenarios.py -q -s -p no:cacheprovider` | 1 failed, 15 passed (141 s). The failure was a test defect in my own assertion (label literal `"MACHINE_VERIFIED"` vs the module constant `LABEL_MACHINE_VERIFIED`); fixed. |
| Run 2 (final) | same | 16 passed, 0 failed, 0 skipped (96 s) |
| Lint | `.venv\Scripts\python.exe -m ruff check tests/phase2/test_s12_s13_com_clone_scenarios.py` | All checks passed |

Earlier authoring failures (not product bugs): a reserved word `В` used as a query alias, a `DATEDIFF` overflow in seconds, and the shared helper `_change_helpers.raw_create` defaults being rejected by the new amount-consistency rule (`AMOUNT_INCONSISTENT`) added concurrently by the engineer. The new file uses its own consistent proposal (`raw_ok`: qty 2, price 10.50, VAT20, amount 21.00, VAT 3.50) and does not depend on the shared default.

## Leftover-document counts before and after (every live test)

Identical in all 13 live tests (the bracket asserts full equality of the snapshot, and it passed): document types with rows 54, total documents 63477, supplier receipts 740 (719 posted), receipt hash `61444e6452d5` before == after, leftover test documents 0 before and 0 after. Per-test `EVIDENCE` lines are printed with `-s`.

## Per scenario

| ID | Status | Live evidence | NOT_RUN / limits |
| --- | --- | --- | --- |
| E4 | PASS | Rejected, expired (deadline, sweep, final EXPIRED), digest-changed approval (real digests), stale state digest at begin-apply: 0 port calls, in-transaction receipt count unchanged, clone snapshot unchanged. A control on the fully approved path shows the harness does see the write (+1 in transaction, marker and content hash read back, unposted) and rollback restores the snapshot. | Ledger rows (PostgreSQL). The engine evidence bits come from test-side glue; no production glue exists. |
| E14 | PARTIAL | POST with only the draft's approval (claim refused), PARENT_NOT_VERIFIED, replayed/expired nonce, expired approval, and a hand edit after approval (live content digest differs, begin-apply `DIGEST_MISMATCH`): 0 port calls, draft stays unposted and keeps the edited content. | A real POST/UNPOST was forbidden on this run: posted flag and registrar rows after a refused POST on a posted target are NOT_RUN. |
| E23 | PARTIAL | A hand edit changes the 1C `ВерсияДанных` and the content digest; with no edit the version is stable; with the edit the engine refuses `STALE_VERSION` at begin-apply, nothing is written (same count, version and content afterwards). | The edit inside the compare-and-write interval is NOT_RUN: no live update executor exists. |
| E25 | PASS | A read-only adapter (`CloneReceiptLookup`) over all 740 receipts, marked or not, declares `population_scope`/`enumerates_unmarked=True` truthfully. Real S15 `reconcile` gives: unmarked count equals an independent admin count; a marked document with no ledger row is `ORPHAN_MARKER` for exactly that change and ref; a hand-made unmarked copy adds exactly one `UNMARKED_DOCUMENT`; a ledger row without a document is `LEDGER_MISSING_IN_1C`; a ledgered document with a matching record has no finding; after a hand edit it is `CONTENT_CHANGED`; a wrong required scope is `INCONCLUSIVE/POPULATION_NOT_ESTABLISHED`. | Real PostgreSQL ledger (fake `LedgerPort`). Content-hash definition is the file's own (plan A10 UNKNOWN). The baseline clone is DIRTY by design (all pre-existing receipts are unmarked or orphan). |
| E41 | PARTIAL | 4 kill readings x 7 boundaries: `KILL_SWITCH_ACTIVE`, 0 port calls, count before == after, the port path is shut. In-flight call with a lost reply (real write, then a raised error) under each of 4 readings: executor `COM_WRITE_OUTCOME_UNKNOWN`, engine `APPLY_UNKNOWN` (not FAILED_APPLY), reservation kept, no new dispatch, the document exists once and is found by marker, `RESOLVE_FOUND` not failed. A pre-write refusal (`COM_REFERENCE_NOT_FOUND`) is FAILED_APPLY with nothing written. UNKNOWN_OUTCOME ledger rows resolve to `FOUND_BY_MARKER` / `NOT_FOUND_BY_MARKER`, never by resend. | Real kill-switch store, operator in-flight list (gap G3), a genuinely severed COM session. |

## Observations (no product bug confirmed)

- The executor's only comparison against a preview is `expected_total`, and it runs after the write: a stale preview gives `COM_WRITTEN_READBACK_MISMATCH` (outcome unknown, document id attached) but the draft already exists (test `test_e23_live_executor_total_check_...`). There is no pre-write expected-version check in the executor; E23 relies on the engine's `version_equals_approved`, which production glue must compute from the 1C data version.
- No production glue exists that maps executor refusals to engine events or reads 1C version/digest; this file supplies it, so these results qualify the engine, executor and clone together under that glue only.
