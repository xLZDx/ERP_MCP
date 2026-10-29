# Change Record 403 — S12/S13 refusal parity and scoped operator reads

## Scope and provenance

- Stories: S12/S13 S1.1–S1.3, as assigned for this implementation slice.
- Source contracts reviewed: `S12_CONTRACT_AMENDMENT_2026-10-28.md`, `CHANGE_RECORD_398.md`,
  `CHANGE_RECORD_399.md`, `S12_CONTRACT_FREEZE_V2_2026-10-16.md`,
  `S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`, and
  `S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md`.
- Baseline worktree already contained unrelated changes in `testlane/onec_extension/scripts/ct14_measure.py`,
  `docs/sdlc/AF_STATE.md`, and `docs/sdlc/state.json`; they were preserved. No test, check, build,
  lint, migration application, production import, live source call, or COM call was run for this change.

## Implemented

### S1.1 — closed public refusal vocabulary and budget classification

`db/phase2/028_refusal_codes_parity.sql` creates an additive registry with the exact 39 public
`ErrorCode` values from `src/business_ai_gateway/phase2/change/errors.py`. It checks the expected
count on application. This is the public contract vocabulary; it does not claim that every
technical SQL exception string elsewhere is one of these 39 business refusal codes.

The candidate migration replaces `budget_precheck` with the existing 027 implementation plus the
narrow amendment rule: a positive effective request against zero remaining reserved/consumed
amount raises `GRANT_EXHAUSTED`. Zero requests, larger requests against a non-zero remainder,
inactive/missing grants, invalid windows, count ceilings, non-finite values, and currency failures
retain their existing classifications. The existing lock and atomic reservation path remain the
enforcement boundary. Migration 027 and earlier migrations were not edited.

### S1.2 — period and budget producers

The migration adds `budget_snapshot`, which reads the current scoped grant and reservation rows,
computes remaining amount and maps it to `OK`, `EXCEEDED`, or `EXHAUSTED`. The adapter converts
the real SQL result to `BudgetCheck`. This is an advisory live snapshot only; existing atomic
claim/reservation logic remains authoritative.

`change/observations.py` defines a server-bound period snapshot reader contract and the async
`build_begin_apply_evidence` producer. It calls the configured reader, ignores and clears any
pre-existing period flags, and derives the closed/open flags only when authentication reference,
source/tenant/company binding, period, source version, and freshness all match. Missing, stale,
mismatched, or reader-error evidence fails closed with a fixed safe error. No arbitrary URL, SQL,
COM call, or caller boolean is accepted. No qualified concrete 1C reader is established in the
reviewed evidence, so the boundary is implemented but real period production remains unqualified
and gateway execution is not wired.

### S1.3 — operator/auditor scoped status and inflight reads

The candidate migration adds `list_inflight(tenant, company, limit, offset)` with a 1–100 page
bound and status-only fields, and `operator_status(tenant, company, change_id)` with a minimized
status projection. Both require `assert_scope`, independently check operator/auditor role
membership, use `SECURITY DEFINER` with `search_path=pg_catalog,pg_temp`, have explicit owner and
grant declarations, and revoke `PUBLIC`. Foreign-scope rows are filtered by both scope keys and
missing rows return the same `CHANGE_NOT_FOUND` response. Neither read returns payload or evidence
content. `SqlChangeLedger` exposes matching `SPEC` entries and typed async wrappers.

## Contract decisions and limitations

- `GRANT_EXHAUSTED` is distinct only when requested effective amount is positive and remaining
  amount is zero. A positive request that exceeds a non-zero remainder remains `BUDGET_EXCEEDED`.
- The SQL error-code registry is a mirrored closed contract list. Runtime/error catalog parity has
  not been executed because this coding phase prohibits tests/checks.
- Operator/auditor reads expose only current tenant/company rows, and pagination is bounded.
- Period observation now has an async producer boundary that calls the configured typed reader.
  The concrete source operation, authentication implementation, supported response/version
  semantics, and qualification evidence are still missing. Therefore real `PERIOD_CLOSED`
  production remains `NOT_RUN`.
- SQL migration validity, role grants on a disposable PostgreSQL instance, and runtime behavior are
  `NOT_RUN`; migration 028 has not been applied.
- Production consumer wiring, gateway imports, private-writer startup/bindings, and live/COM
  behavior are unchanged and not claimed.

## Acceptance matrix

| Item | State | Evidence in this change | Remaining acceptance / dependency | Owner and next action |
| --- | --- | --- | --- | --- |
| S1.1 public 39-code SQL mirror and exhausted-budget code | Implemented, unverified | Migration 028 explicit 39-code insertion and narrow `budget_precheck` override; source Python registry has 39 enum members by inspection | Functional SQL/Python parity and boundary scenarios; disposable PostgreSQL application | Codex: delegate focused tests after coding phase; test owner runs them; no migration execution in this turn |
| S1.2 period and budget producers | Budget snapshot implemented, unverified; period reader producer boundary implemented, source qualification NOT_RUN | `budget_snapshot` reads live grant/reservation rows; `build_begin_apply_evidence` calls configured `PeriodSnapshotReader`, clears caller flags and validates binding/version/auth reference/freshness | Disposable PostgreSQL behavior; evidence-backed authenticated source operation and gateway integration | Codex: coordinate database qualification and qualify a supported read-only source operation; keep real period production unavailable until then |
| S1.3 scoped operator/auditor reads | Implemented, unverified | `list_inflight`, `operator_status`, `assert_scope`, bounded pagination, explicit `PUBLIC` revoke and role grants; wrappers/spec in `sql_ledger.py` | Verify exact SQL catalog signatures/grants and tenant isolation against a disposable database | Codex: arrange independent database review and test-owner qualification after coding |
| Runtime and migration evidence | NOT_RUN | Explicitly no tests/checks/builds/migrations/live/COM calls were run | Required disposable SQL and focused functional evidence | Codex: queue with test owners after all assigned coding is complete |

## Changed files

- `db/phase2/028_refusal_codes_parity.sql` — new additive SQL candidate.
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py` — matching read/snapshot SPEC and wrappers.
- `src/business_ai_gateway/phase2/change/observations.py` — new fail-closed period reader and evidence producer boundary.
- `docs/phase2/CHANGE_RECORD_403.md` — this record.

No commit was created. No unrelated dirty files were changed.
