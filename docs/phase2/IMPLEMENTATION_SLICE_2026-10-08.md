# Phase 2 implementation slice: observed model, temporal history and connector contracts

Date: 2026-10-08
Branch: phase2/living-model-connectors-reconciliation
Local checkout: D:\Repo\ERP_MCP-phase2
Status: implementation prototype under R2 design scope, **not deployed**.
Release 1 main/runtime/database/1C/tunnel are unchanged.

## Completed

- structural_hash.py: namespace-qualified EDMX structural and raw SHA-256; bounded XML and failure handling.
- structural_diff.py: deterministically classify ADDED/MODIFIED/REMOVED, fail conservatively on unattributed structural drift.
- model_graph.py: scoped dependency impact closure; unknown and unmapped modifications block conservatively; unrelated additions may remain unaffected when the dependency inventory is complete.
- temporal.py: explicit append-only reference ledger, known-time versus source-effective-time, out-of-order changes, unknown effective-time and GAP events. **Offline in-memory reference model**, NOT a durable PostgreSQL ledger.
- onec_discovery.py: injected, registry-resolved read-only metadata fetch contract after source-wide ACL. No caller-supplied host or credentials, no direct network or database mutation.
- drive_changes.py: change-page/cursor CAS contract; scope-projected candidates remain UNATTESTED. It does NOT fetch Drive or store a cursor; caller must commit page+cursor atomically.

## Verification

Run in isolated .venv:
    .\.venv\Scripts\python.exe -m pytest -q tests\phase2
    .\.venv\Scripts\ruff.exe check src\business_ai_gateway\phase2 tests\phase2

Most recent local result: 74 passed; Ruff All checks passed (recheck on final commit).
Tests use synthetic fixtures/callbacks: **no PostgreSQL, 1C, Google Drive, UI/native reports, production or OAuth smoke test was performed by this slice.** Product acceptance UAT remains NOT_RUN.

## Blockers and required gates

1. PostgreSQL S2 migration: an attempt to write separate phase2 SQL DDL via the connected desktop tool was rejected by safety checks. No SQL applied, no production PostgreSQL touched. Do not try an alternate command/execution channel to bypass the tool's restriction. Need an authorized review/deployment workflow for additive migration in an isolated test database.
2. Persistence: define and verify tenant/source-scoped FKs, events, schema observations, accepted heads, immutable history, bitemporal as-of queries, role split (scanner/reader/approver), RLS and write-denial in disposable PostgreSQL. No state is promoted from scanner.
3. Drive OAuth: must be authorized for ERP_MCP separately; ChatGPT's own connected Drive account grants no automatic service permissions. Verify file vs folder and new-child access with scoped PoC; callbacks are only offline contracts so far.
4. 1C connection: use existing server registry and source-level metadata ACL in a separate authorized worker, with adaptive rate budget and no source load until approved; no arbitrary COM/raw SQL/EPF.
5. Native reconciliation: real artifacts and independent accounting attestation still missing for relevant operations. Connector candidates cannot be VALIDATED. Release 1 evidence defects and native report gate remain R1 responsibility.
6. Production: no Phase 2 migrations, switches, report UI automation, R1 process restarts or source grants are authorized in this slice.

## Next implementation order

- Approve dedicated Phase2 test PostgreSQL and guarded migration.
- Add durable repository/transactions with tests for concurrency, CAS acceptance and foreign-tenant denial.
- Integrate 1C discovery via existing registered source only after source-wide ACL permission.
- Do a real Google Drive permissions/new-file PoC with explicit account authorization; add OAuth and delta feed only then.
- Connect private evidence store + native 1C UI report capture (dev clone first), deterministic 521.1 and posted purchases comparison, independent accounting approval.
- Shadow compare R1/R2, benchmark 30/50/100/150 sources, separate production qualification and GO.

## No silent claims

74 unit/spec tests are not an SQL integration test or production capability. The term Living Registry is an architectural target; persistent PostgreSQL acceptance is NOT_RUN at this point. Phase 1 continues separately.
