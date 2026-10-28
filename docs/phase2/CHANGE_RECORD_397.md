# Change Record 397 - live-1C scenarios on the disposable clone (E4, E14, E23, E25, E41)

## Ownership and scope

- Date: 2026-10-28. Tests written and run by the e2e-runner agent on the disposable clone `818HA_p2diff` (licence verified working). No source or migration changed.
- Adds `tests/phase2/test_s12_s13_com_clone_scenarios.py` and `docs/phase2/S12_S13_COM_CLONE_REPORT_2026-10-28.md`.

## Safety

- Clone-only guard; least-privilege account (role CT14Писатель) for writes; every write inside a transaction that is rolled back; no POST, UNPOST or deletion. Leftover-document counts before and after were equal in all 13 live tests (clone: 63477 documents, 740 receipts, receipt hash unchanged).

## Evidence (agent-run, no mutation runs)

- 16 passed (13 live, 3 scenario-map), 0 skipped, 0 failed; ruff clean.
- E4 PASS; E25 PASS (S15 reconcile fed a real read-only listing surfaces a document without a ledger record and a ledger record without a document); E14, E23, E41 PARTIAL (see report; a real POST/UNPOST and an edit inside the compare-and-write interval are NOT_RUN; a lost reply after a real write stays UNKNOWN and is found by its change-id marker).

## Observations (not defects fixed here)

- The executor's preview check (`expected_total`) runs after the write; no production code maps executor refusals to engine events or reads the 1C data version, so the results hold under the glue in the test file.

## Not established

- GPT-PM review NOT_RUN. Formal S12/S13 acceptance NOT granted.
