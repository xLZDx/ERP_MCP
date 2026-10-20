# Change record 143 — CR142 disposable PostgreSQL evidence

## Goal and scope

Record the designated functional and E2E agents' runtime evidence for migration 023 at source HEAD `0d36cc977e0fc39bbf6e0107c386710de00ae206`. This commit adds only their owned test scenarios and the evidence record; it does not change migration or application source.

## Changes and affected paths

- Added `tests/phase2/test_s13_migration023.py`, owned and executed by `functional-test-reviewer`.
- Added `tests/phase2/test_s13_migration023_e2e.py`, owned and executed by `e2e-runner`.
- Added this detailed record, linked to CR142's additive migration `db/phase2/023_lifecycle_activation_cap.sql`.
- Invoked `node scripts/build_document_registry.mjs`; it completed without changing `governance/DOCUMENT_REGISTRY.md` (the generated inventory is based on Git refs and did not include these uncommitted test files).

## Runtime evidence

Both agents report PASS against migration source SHA-256 `73C30BB18301B0CDFAA7D36C53870E7316E6A3EFAC7078E402368BA496799F09` at the exact source HEAD above.

### Functional scenarios

- Command: `$env:ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS='1'; & .\.venv\Scripts\python.exe tests/phase2/test_s13_migration023.py`.
- Runtime: Python 3.14.3; Docker `postgres:16`; exact PostgreSQL patch version was not recorded.
- Test SHA-256: `33DBE1560BDFC71393EADDEA2FECE43246007D26DC72BC0EE6E02E61B71B9996`.
- The complete migration chain 001–023 applied in the invocation-owned disposable cluster. Application-role execution was denied; privileged recovery returned `LIFECYCLE_COORDINATOR_UNAVAILABLE`; lifecycle state, epoch, reason and timestamp remained unchanged; reapplying 023 was idempotent.
- Event, dispatch-permit and writer-epoch guards were exercised with an independent row lock. The default event lock wait returned in 5.135 seconds. A shorter caller timeout of 150 ms was preserved for all three paths (observed 0.274, 0.267 and 0.755 seconds).

### E2E journey

- Command: `\.venv\Scripts\python.exe tests\phase2\test_s13_migration023_e2e.py`.
- Runtime: PostgreSQL 16.14 from image `postgres:16`, image digest `sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae`; Python 3.14.3; asyncpg 0.32.0; Docker client/server 29.5.2.
- Test SHA-256: `2D920A3BB11D07E1521FFC14313B220021C4890539C0EF55253F6939F13D722A`.
- Across independent connections, the worker was denied with SQLSTATE `42501`; the privileged call failed closed with `P0001`; durable state remained unchanged. Holding the lifecycle row through another connection caused writer-epoch admission to fail with lock-timeout SQLSTATE `55P03` after 6.608 seconds client-observed. The scenario allows under 7 seconds for client/runtime overhead around the configured five-second database timeout.
- The harness confirmed that its owned container and anonymous volume were removed and the image digest was unchanged. No unrelated containers were removed.

## Limits and acceptance state

- These results prove only the migration contract exercised on disposable PostgreSQL. They do not prove coverage of every ledger mutation or a physical writer, 1C integration, service admission boundary, shared cross-process fence, coordinator readiness, external checkpoint provider, or formal S13 acceptance.
- No shared or production database was accessed; no migration was applied outside the disposable clusters. S13 remains formally `NOT_STARTED / NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`.
- DB, reliability and security reviews of the exact committed evidence are still required. `CHANGE_RECORD_142.md` is the source-time record and its pre-test `NOT_RUN` statement is superseded by this record for the two focused scenarios only.

## Ownership and next action

- The operator is accountable for delegated project closure; GPT/Codex coordinates the local work.
- `functional-test-reviewer` and `e2e-runner` own the attached tests and the reported runs. `database-reviewer`, `reliability-reviewer` and `security-reviewer` own the next independent exact-head reviews.
- Continue local S13 engineering only after reviewing this narrow result. Keep physical writer, formal gate and production acceptance open. Fresh GPT approval for the exact final branch range remains required before push.
