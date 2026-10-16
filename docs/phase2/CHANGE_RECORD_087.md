# Change record 087 — record exact-tree G1 focused reruns

## What changed

- Recorded the complete selected functional/multiprocessing rerun: 45 passed, 0 failed, 0 skipped across the selected 22 node IDs, including all 24 MAJOR-02 parameter variants.
- Recorded the required explicit-COMMIT and distinct-cluster restore rerun by E2E: 2 passed, 0 failed, 0 skipped.
- Updated the G1 evidence plan and SDLC state with exact docs/code heads, source blob IDs, command selectors and follow-up database-review outcome.
- Corrected the earlier description of MAJOR-02 observer evidence: `wait_event=transactionid` is captured as metadata, while assertions require `wait_event_type=Lock` and the revoke backend PID in `pg_blocking_pids`.

## Why

The earlier accepted functional run had been recorded at a parent revision, with a separate 24-case rerun after the MAJOR-02 observer correction. A full selected rerun was requested to tie the entire functional set and both E2E boundary cases to the corrected source tree. The durable evidence must distinguish the documentation checkout used by the functional agent from the exact code/test commit and must not claim unprovided timings or container identities.

## Decisions and scope

- Functional/multiprocessing command: the existing focused PowerShell command in `G1_EVIDENCE_PACKET_PLAN.md`, invoking `.venv\Scripts\python.exe -m pytest -vv` with the documented 22 selected node IDs and the disposable PostgreSQL DSN/flags. It ran at documentation HEAD `0800269ccf0e9899f1b6e707ac29164c91878c86`; result was 45 passed, 0 failed, 0 skipped. The relevant test source blobs match code/test HEAD `a6263e4bafe69aedd14372f394d67da7b6fb3366`, including `test_g1_postgres_integration_review2.py` blob `ce5c2c4f86b4751b8f03744fff16831557887d4`.
- E2E command: `.venv\Scripts\python.exe -m pytest -q tests/phase2/test_g1_crash.py::test_terminate_backend_during_observed_explicit_commit tests/phase2/test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster`. It ran at detached exact code/test HEAD `a6263e4bafe69aedd14372f394d67da7b6fb3366`; result was 2 passed, 0 failed, 0 skipped.
- E2E test blobs at `a6263e4`: crash test `d899fe1b237f4d637e085ff6327f756f915dc369`; restore test `6bd93ccffaa473bf69d1463913df57c1c44b8a4a`.
- Run durations and invocation-owned container identifiers for these latest reruns were not included in the supplied run summaries. They are deliberately not inferred. The disposable functional test database was removed; no production database was used.
- Database-reviewer completed a read-only review of the exact-tree evidence: no database BLOCKER/MAJOR. The reviewer confirmed the MAJOR-02 lock evidence and bounded the explicit-COMMIT claim: it does not cover the pre-acknowledgement gap.
- This is documentation-only. It does not change application code, test code, database state, the formal G1 gate, or production authorization.
- Local push still requires a fresh GPT-PM decision for the exact final code/documentation head. Formal G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`.

## Review and verification state

- Runtime results were produced by `functional-test-reviewer` and `e2e-runner`; the primary session did not run tests.
- Exact-tree evidence review was completed by `database-reviewer`, read-only, with no database BLOCKER/MAJOR.
- Documentation facts were reconciled with the evidence plan and source blobs at the stated revisions.
- No tests, checks, builds, migrations, database operations or production actions were run for this documentation update.
- Document registry generation is recorded in its separate post-commit registry-refresh change record.
- No push was performed.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/CHANGE_RECORD_083.md`
- `docs/sdlc/STATE.md`
- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_087.md`

## Acceptance

- The complete selected local runtime set is recorded against exact source blobs and its actual documentation/code revisions.
- Explicit-COMMIT and restore results are attributed to the exact code/test commit and exact selected nodes.
- MAJOR-02 observer assertions are described accurately; observed metadata is not presented as an asserted condition.
- Missing duration/container details are not fabricated.
- Formal G1 remains `NOT_PASSED`, production authorization remains `NONE`, Release 2 remains `NO-GO`, and push remains pending fresh PM approval.
