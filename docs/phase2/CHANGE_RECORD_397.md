# Change Record 397 - live-1C scenarios on the disposable clone (E4, E14, E23, E25, E41)

## Ownership and scope

- Date: 2026-10-28. Tests written and run by the e2e-runner agent on the disposable clone `818HA_p2diff` (licence verified working). No source or migration changed.
- Adds `tests/phase2/test_s12_s13_com_clone_scenarios.py` and `docs/phase2/S12_S13_COM_CLONE_REPORT_2026-10-28.md`.

## Safety

- Clone-only guard; least-privilege account (role CT14Писатель) for writes; no POST, UNPOST or deletion. The live tests are rolled-back document writes plus ONE persistent, authorized mutation of the disposable test account `CT14_NARROW` (password reset, role set reset, possible Users catalog binding item), verified by a principal snapshot (names, flags, sorted roles; before 78 users and 30 catalog items, after 78 and 30; no other user changed; `CT14_NARROW` has exactly the two reviewed roles; binding item not created in the final run).
- Leftover-document counts before and after were equal in all live tests (clone: 63477 documents, 740 receipts; selected-field regression snapshot, 12-hex digest of selected receipt fields, not full-object equivalence).

## Evidence (agent-run, no mutation runs)

- 16 passed (13 live, 3 scenario-map), 0 skipped, 0 failed; ruff clean.
- E4 and E25: PARTIAL at exit-scenario level; PASS only for the measured component/live-clone subset; NOT_RUN/UNKNOWN: PostgreSQL ledger integration (E25 uses FakeLedger), production evidence/content-hash derivation (test-local definition, production UNKNOWN), production glue for 1C reads and executor-to-engine events. E25 (S15 reconcile fed a real read-only listing surfaces a document without a ledger record and a ledger record without a document); E14, E23, E41 PARTIAL (see report; a real POST/UNPOST and an edit inside the compare-and-write interval are NOT_RUN; an injected reply loss after a real write, inside an open rolled-back transaction, stays UNKNOWN and is found by its change-id marker; real session loss and uncertain commit are NOT_RUN).
- Final run: 387 passed (370 offline + 17 clone-file) with the principal snapshot test. The slow SQL/e2e and S15 suites were not rerun at this head; the combined regression is NOT claimed green.

## Observations (not defects fixed here)

- The executor's preview check (`expected_total`) runs after the write; no production code maps executor refusals to engine events or reads the 1C data version, so the results hold under the glue in the test file.

## Not established

- GPT-PM review NOT_RUN. Formal S12/S13 acceptance NOT granted.
