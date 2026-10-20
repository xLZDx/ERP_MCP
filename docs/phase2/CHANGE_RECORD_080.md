# Change record 080 — record G1 distinct-cluster restore runtime evidence

## What changed

- Updated the Russian and English G1 local-push reports, SDLC state, evidence packet plan and operator backlog with exact focused runtime evidence for `test_pg_dump_restore_to_distinct_postgres_cluster`.
- Recorded the source and target container IDs, PostgreSQL system identifiers, test-file digests, agent timings, assertions and JUnit warning.
- Kept the result scoped to this one restore scenario. The full focused test set remains incomplete, formal G1 remains `NOT_PASSED`, and no new PM push approval is inferred.
- Regenerated the document registry to include this record.

## Why

The prior G1 status said the corrected restore case had not run. Two authorized test agents subsequently ran the exact focused test successfully, with one additional E2E run capturing JUnit XML. The durable status needed to distinguish this runtime-proven scenario from the other still-open acceptance cases.

## Decisions and scope

- Functional-test-reviewer command: `.venv\Scripts\python.exe -m pytest -q tests/phase2/test_g1_restore.py::test_pg_dump_restore_to_distinct_postgres_cluster`, with `ERP_PHASE2_REQUIRE_PG=1` and `ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1`; result: 1 passed in 17.89s, exit 0.
- E2E-runner executed the same focused test: 1 passed in 15.27s; repeat with `--junitxml $env:TEMP\g1-distinct-restore-evidence.xml`: 1 passed in 14.82s. The repeat emitted one PytestWarning that `record_property` is incompatible with xunit2; XML properties were captured. Review characterized this as a metadata warning, not a behavioral failure.
- Runtime was reported on documentation HEAD `5588c06851340751fa574e182da0e9c9b03111e9`. The test file SHA-256 was `DD4F08C1BF5CC3270BB6E6A3C08EC30A73526C592D8F0AC7348EB11742CE66B5`; the Git blob at PM-reviewed code HEAD `315e83149b48fcef1d3ded7c5e2325d7c3fe7cd4` is `6bd93ccffaa473bf69d1463913df57c1c44b8a4a`, confirming the test source matches the reviewed code.
- Source container `r2-s13-dump-92fdb996ef79-a`, Docker ID `3b479f7701a95043d6151432d6ab2d65de0eb81f6f6fbcaf351ef573c467e367`, system identifier `7697154259177177126`; target container `r2-s13-dump-92fdb996ef79-b`, Docker ID `7a2f1d5d0d2843eafa091a5acf59bdd0fe6906aa1ac50be912db0063307b7283`, system identifier `7697154262396780582`. The identities differ. Invocation-owned containers were removed; unrelated containers were left untouched.
- Assertions confirmed more than zero rows visible before grant removal and zero afterward through the same READ COMMITTED reader session, plus fresh-context P0001 / `SCOPE_NOT_GRANTED` for source and target.
- PM Bridge request `f4cd1c27-2b3c-4094-80f3-1fd88dbfd1e6` remains the latest PM decision: `STATIC APPROVE`, no confirmed BLOCKER/MAJOR, prior `PUSH NO-GO` pending runtime evidence. The restore-case runtime dependency is now met, but no updated PM push verdict is recorded. No push was performed.
- This documentation commit does not change product code, SQL, database state, gate manifest or production authorization. Formal G1 remains `NOT_PASSED`.

## Review and verification state

- Runtime evidence was provided by the functional-test-reviewer and e2e-runner; the primary session did not run tests or checks.
- Reviewer follow-up found no BLOCKER or MAJOR. The JUnit warning affects the `record_property` metadata compatibility with xunit2; the run passed and the XML properties were captured.
- No tests, checks, builds, migrations, or database operations were run for this documentation update.
- Registry generation command: `node scripts/build_document_registry.mjs`.

## Contracts and paths

- `docs/sdlc/STATE.md`
- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.html`
- `governance/DOCUMENT_REGISTRY.md`

## Acceptance

- The restore test is recorded as runtime-proven only for the focused scenario and exact source revision; other cases are not implied to pass.
- Both reports include the test-agent results, fixture identities, warning and exact source/review relationship.
- The current PM push decision is not misrepresented as updated approval; G1 remains `NOT_PASSED` and no push is authorized by this documentation commit.
