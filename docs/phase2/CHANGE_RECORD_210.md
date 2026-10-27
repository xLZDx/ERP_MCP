# Change Record 210 — freeze the S13 schema routing decision

## What changed

- `SqlChangeLedger` now rejects reassignment and deletion of its private-writer-schema routing flag after construction.
- The legacy-to-S13 route decision is fixed for the lifetime of one adapter instance. S13-enabled routing cannot be silently downgraded to legacy methods by ordinary attribute mutation.

## Why

The adapter deliberately fails closed when a selected S13 entry is unavailable and never falls back to the legacy mutation path. A mutable routing flag could change that contract after construction, allowing later calls on the same adapter instance to select older SQL functions. Freezing this decision keeps routing stable for the lifetime of the connection adapter.

## Evidence and verification state

- Changed source: `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`, `SqlChangeLedger.__setattr__` and `__delattr__`.
- Source SHA-256: `8D7F014245E71DBC9C5B985C452B87E0DCEE465FC60DBCD97BE7AA3AEE67B329`.
- The implementation and S13 routing inventory were inspected in the current turn. No tests/checks/build, SQL parsing, migration, database operation, staging, commit or push was run.
- Functional regression coverage for both enabled and disabled configuration, including attempted reassignment and deletion, remains `NOT_RUN` and is assigned to the required functional-test phase after coding closes.
- This hardens the in-process configuration boundary. It is not protection against hostile code with direct access to `object.__setattr__`, and does not verify database grants or activate the candidate migration.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue the S13 all-path source closure; after coding closes, have the functional-test reviewer cover immutable routing and no-fallback behavior, then measure installed effective grants and qualify candidate behavior only in the approved disposable database.
