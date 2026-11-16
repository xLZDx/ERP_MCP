# Change Record 403 — S12/S13 refusal parity and scoped operator reads

## Scope and provenance

- Stories: S12/S13 S1.1–S1.3, as assigned for this implementation slice.
- Source contracts reviewed: `S12_CONTRACT_AMENDMENT_2026-10-28.md`, `CHANGE_RECORD_398.md`,
  `CHANGE_RECORD_399.md`, `S12_CONTRACT_FREEZE_V2_2026-10-16.md`,
  `S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`, and
  `S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md`.
- Baseline worktree already contained unrelated changes in `testlane/onec_extension/scripts/ct14_measure.py`,
  `docs/sdlc/AF_STATE.md`, and `docs/sdlc/state.json`; they were preserved. No test, check, build,
  lint, migration application, production import, live source call, or COM call was run when CR-403
  was prepared. The later S1.1 verification update below applies only to migration 028 on a disposable
  PostgreSQL instance; it does not qualify S1.2 or S1.3 runtime behavior.

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
tenant/company/source/organization/base-fingerprint binding, period, source version, and UTC
freshness all match. It does not assert `fingerprint_authenticated`; that remains a separate trusted
target-authentication guard. Missing, stale,
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
- The 39-row SQL registry mirrors public `ErrorCode` identifiers only. It does not mirror Python's
  `ErrorInfo` messages or `NextAction`, does not assert that SQL emits every Python code, and does
  not map every internal SQL exception string to this public set. In particular, `PERIOD_CLOSED`
  is present as a registry value, but migration 028 does not observe or produce an authenticated
  accounting-period result; its real-data producer remains `NOT_RUN`.
- `budget_precheck` emits `GRANT_EXHAUSTED` only for a positive effective request when reserved plus
  consumed amount already exhausts the grant. A zero request does not take this branch; an amount
  above a non-zero remainder and count/post-count ceiling failures remain `BUDGET_EXCEEDED`.
- The migration is transaction-wrapped, so an apply-time failure rolls back. There is no down
  migration. After a successful shared-database apply, rollback requires a reviewed corrective
  migration that restores the prior `budget_precheck` and removes migration-028 objects only after
  checking dependencies and consumers; this change does not authorize shared or production apply.
- Operator/auditor reads expose only current tenant/company rows, and pagination is bounded.
- Period observation now has an async producer boundary that calls the configured typed reader.
  The concrete source operation, authentication implementation, supported response/version
  semantics, and qualification evidence are still missing. Therefore real `PERIOD_CLOSED`
  production remains `NOT_RUN`.
- At CR-403 authoring time, SQL migration validity, role grants on PostgreSQL, and runtime behavior
  were `NOT_RUN`. The follow-up below later applied migration 028 only in an invocation-owned
  disposable test database; shared/staging/production migration remains `NOT_RUN`.
- Production consumer wiring, gateway imports, private-writer startup/bindings, and live/COM
  behavior are unchanged and not claimed.

## Acceptance matrix

| Item | State | Evidence in this change | Remaining acceptance / dependency | Owner and next action |
| --- | --- | --- | --- | --- |
| S1.1 public 39-code SQL mirror and exhausted-budget code | Implemented; disposable-PostgreSQL runtime-proven; scoped GPT-PM review APPROVE (0 findings); not delivered | Migration 028 and the exact set of 39 Python enum codes; focused test, database review and scoped GPT-PM result are recorded below and in `docs/sdlc/verify-evidence.md` | AC-1–AC-3 are satisfied for S1.1 scope. Source commit also contains S1.3 code and is not upstream; at review HEAD `03297eca` the branch had 19 mixed commits ahead. No shared/production migration or real period producer is claimed. | Codex: prepare a safely isolated S1.1 delivery range; keep the hard push gate and do not start S1.2 until delivery is resolved |
| S1.2 period and budget producers | Budget snapshot implemented, unverified; period reader producer boundary implemented, source qualification NOT_RUN | `budget_snapshot` reads live grant/reservation rows; `build_begin_apply_evidence` calls configured `PeriodSnapshotReader`, clears caller flags and validates tenant/company/source/organization/base fingerprint, version, auth reference, and UTC freshness; it does not assert `fingerprint_authenticated` | Disposable PostgreSQL behavior; evidence-backed authenticated source operation and gateway integration | Codex: coordinate database qualification and qualify a supported read-only source operation; keep real period production unavailable until then |
| S1.3 scoped operator/auditor reads | Implemented, unverified | `list_inflight`, `operator_status`, `assert_scope`, bounded pagination, explicit `PUBLIC` revoke and role grants; wrappers/spec in `sql_ledger.py` | Verify exact SQL catalog signatures/grants and tenant isolation against a disposable database | Codex: arrange independent database review and test-owner qualification after coding |
| S1.1 SQL parity and exhausted-grant behavior | Runtime-proven in an invocation-owned disposable PostgreSQL database; scoped GPT-PM APPROVE | The focused S1.1 run below passed 2/2, including migration application/reapplication, exact code-set equality and budget boundaries; request `d7b9c1f0-6a42-4c83-9f1e-2058de37a4b6` returned APPROVE with 0 BLOCKER / 0 MAJOR / 0 MINOR for the S1.1 scope | Not pushed; the source commit also contains S1.3 changes and current branch has 19 mixed commits ahead. Shared migration and real period observation remain NOT_RUN. Sprint-level AF phase-8 preflight separately refused due to stale tested-head evidence; it is not an additional S1.1 AC. | Codex: isolate a task-specific delivery path and resolve the branch-level hard push gate before starting S1.2 |
| S1.2/S1.3 runtime and real-data evidence | NOT_RUN / UNQUALIFIED as stated above | CR-403 records the implemented boundaries and their test/data limitations | Qualified real period/budget readers and SQL scope/grant verification are not established by the S1.1 run | Codex: preserve those separate states; do not infer their closure from S1.1 |

## S1.1 verification follow-up — 2026-10-31

- Code implementation is the committed migration 028 in `4779ae9d8e3abe3c4b4beff2cadb74a85fda7b5a`.
- At current code HEAD `e523b3727e8d86050e48fd3d62f281a3764fe174`, `e2e-runner` ran
  `.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s12_sql_code_parity.py` against an
  invocation-owned disposable PostgreSQL database: **2 passed in 24.72s**. AC-1 checks exact
  39-code equality, both amendment codes, migration reapplication, and role/table privileges.
  AC-2 checks exhausted positive grant → `GRANT_EXHAUSTED`, excessive request with non-zero
  remainder → `BUDGET_EXCEEDED`, and the zero-amount boundary.
- The test file was already untracked before this verification; its SHA-256 was unchanged across
  the run: `0373605827DAFEAFCF025F8084C9582309DB4975182ECF137DA651CE2480755B`. Its author is not
  established by this record.
- A read-only `database-reviewer` review of the S1.1 portion of commit 4779ae9 found no database
  correctness blocker. It confirmed the registry guard, transaction boundary, retained lock path,
  grant classifications, and runtime test coverage. It did not rerun tests or apply a migration.
- The reviewer requested the explicit AC-3 boundaries and post-apply rollback path now recorded
  above. No shared/staging/production database was changed. GPT-PM returned `APPROVE` with 0
  BLOCKER / 0 MAJOR / 0 MINOR for the S1.1 scope of commit
  `4779ae9d8e3abe3c4b4beff2cadb74a85fda7b5a` (request
  `d7b9c1f0-6a42-4c83-9f1e-2058de37a4b6`); this does not approve the separate S1.3 changes in that
  commit or create the formal AF phase-8 artifact. A phase-8 preflight at HEAD
  `03297eca8fb4939bbc3f3677acdc4be1672af618` was refused before PM submission because the sprint
  `verify-evidence.json` remains bound to tested HEAD `6caf3d65e998` and reports later code changes.
  The migration has not been pushed or applied to a shared/staging/production database.

## Changed files

- `db/phase2/028_refusal_codes_parity.sql` — new additive SQL candidate.
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py` — matching read/snapshot SPEC and wrappers.
- `src/business_ai_gateway/phase2/change/observations.py` — new fail-closed period reader and evidence producer boundary.
- `docs/phase2/CHANGE_RECORD_403.md` — this record.

The source commit is `4779ae9d8e3abe3c4b4beff2cadb74a85fda7b5a`; it also contains S1.3 observation
code, which was outside the scoped S1.1 review. Later evidence reconciliation was committed as
`03297eca8fb4939bbc3f3677acdc4be1672af618`. No unrelated dirty files were changed.

## FIN-S1.2 real-source discovery follow-up — 2026-11-16

- Read-only command: `.venv\Scripts\python.exe -m scripts.real1c.period_lock_evidence_readonly`.
- The protected COM reader connected to the fixed disposable clone `818HA_test_ready` and returned one row from
  `РегистрСведений.ДатыЗапретаИзменения`: all-users scope, no section/object scope, restriction date `2025-12-31`.
  The observed configuration was `БухгалтерияДляМолдовы` version `3.0.67.1`; the metadata fingerprint was
  `91409995b2a67a79fda459fe12eb33587589f8679ed318d71a6a6e544f0632ee`.
- The script classifies this as `CANDIDATE_NOT_GATE_ACCEPTANCE`. It proves that a protected, read-only COM query
  can retrieve a bounded raw date-lock fact from this clone. It does not prove the business meaning of that date,
  map a requested accounting month to closed/open, or provide a gateway-wired `PeriodSnapshotReader`.
- The same read-only metadata inspection found a distinct `ВыполнениеРегламентныхОперацийНДС` register with 30
  current rows, but that register is VAT-specific and does not establish general accounting-month closure. The
  `ОчередьРегламентныхОпераций` register returned zero rows. 1C's official configuration documentation describes
  date-ban settings as protection "starting from the specified date"; that is an edit cutoff, not by itself proof
  that a whole accounting month was closed: <https://its.1c.ru/db/content/erp25ltsdoc/src/%D0%B2%D0%B2%D0%B5%D0%B4%D0%B5%D0%BD%D0%B8%D0%B5.htm>.
- FIN-S1.2 AC-1 remains open. Before deriving `PERIOD_CLOSED`, qualify the register's period semantics against this
  exact configuration version or identify an authoritative general close-month status source, then bind the read to
  the registered source/company/base identity. No credential value, document rows, or write operation was used. No
  tests or checks were run.

### 2026-11-16: bounded close-operation inventory

- Extended the same protected COM diagnostic to query only `Документ.РегламентнаяОперация` date, displayed state,
  and posted flag, capped at 1,000 rows. It emits counts by calendar month/state/posted flag; it emits no document
  references, organization names, amounts, or credentials.
- The rerun returned 233 records spanning `2022-12` through `2026-06`. States include `Выполнено` and
  `Пропущено`; every returned record had `Проведен=false`. Several 2023 months include a skipped operation.
- This is new candidate evidence about the clone's close-operation history, not proof that the target month is
  accounting-closed. In particular, the diagnostic does not know which operations are required for a month, why
  an operation was skipped, whether later changes invalidated the close, or how the configuration derives its
  final month-close status. It therefore remains `CANDIDATE_NOT_GATE_ACCEPTANCE` and does not feed
  `AuthenticatedPeriodSnapshot.closed`.
- The installed client exposes `CommonModules.ЗакрытиеМесяца`, `CommonModules.ЗакрытиеМесяцаВызовСервера`,
  and `DataProcessors.ЗакрытиеМесяца` metadata, but no versioned source/export was found in the repository.
  The next qualification step is to inspect the exact 3.0.67.1 close-month implementation or identify a published,
  authenticated status source, then verify what `Выполнено` and `Пропущено` mean across all required operations.
- No writes, postings, or tests were performed. The query was run only against the fixed disposable clone
  `818HA_test_ready`; this does not validate the registered gateway source/company binding.

## FIN-S1.2 metadata cross-check and remaining period-status gap — 2026-11-16

- Found the local versioned export `D:/ERP_MCP_Testbed/1c/reference/exports/config/fin_s12_full_config_20261108`. Its `Configuration.xml` declares 3.0.67.1. A protected read-only COM query of fixed clone `818HA_test_ready` also reports 3.0.67.1 and 1,184 metadata object names; the export's six metadata-kind name set has the same 1,184 entries and SHA-256 `91409995b2a67a79fda459fe12eb33587589f8679ed318d71a6a6e544f0632ee`. This compares configuration version and metadata names only; BSL contents are not hashed against the live infobase.
- `scripts/real1c/period_lock_evidence_readonly.py` now checks that version/name-set pair and fails closed on mismatch. The diagnostic exited 0 and remained `CANDIDATE_NOT_GATE_ACCEPTANCE`; it returned one all-user date lock through 2025-12-31 and 233 close-operation records. It did not return business rows or credential values.
- The exported 3.0.67.1 close-month implementation builds a dynamic per-period/per-organization table containing `Требуется`, `Состояние`, and `Устарела`. Its logic uses accounting policy, primary-document presence, and stale-operation data. The raw operation states `Выполнено` and `Пропущено` alone cannot establish closure. Therefore AC-1 remains OPEN/NOT_RUN; no `AuthenticatedPeriodSnapshot.closed` is emitted and no gateway reader is qualified.
- Next implementation step: add a bounded, read-only source for the dynamic required/stale close status (or a select-only equivalent derived from this exact export), validate it against the clone, then wire it through the registered source/company binding. No tests, checks, writes, or postings were run.

## FIN-S1.2 native close-flow status follow-up — 2026-11-16

- `python -m scripts.real1c.period_status_native_readonly --period 2025-12` completed with exit code 0 against the fixed `818HA_test_ready` file clone. It returned 18 native status rows, zero blocking required operations, and `close_flow_ready=true`. The new blocking count uses the exact rule in the exported 3.0.67.1 close-month form: a required operation blocks unless it is skipped or completed and not stale. Empty results fail closed (`close_flow_ready=false`).
- This answers whether the configured close workflow has a blocking required operation. It does **not** mean the accounting period is formally closed, and it does not produce `AuthenticatedPeriodSnapshot.closed` or `PERIOD_CLOSED`.
- Read-only gateway evidence this turn: `ERP_MCP_Razer` lists `onec-818ha-reference` as read-only; `companies_list` maps company `3e31afc5-351f-4f36-8074-99129fa3d911` to organization `019bbaa8-5131-11ee-aa2f-d85ed30dc416`; the selected organization from the COM clone has the same SHA-256 as that external reference. A filtered OData read of `Catalog_Организации` returned that reference with `DeletionMark=false`. This confirms the company reference mapping, not that the fixed file clone and registered gateway source are the same physical information base.
- `source_health` returned `200/ok=true`, but `onec_find_entities` for `Закрытие` returned an empty result. The registered OData source therefore has no discovered close-status EntitySet; the only computed status read so far uses a local file clone and is not bound to the gateway source/company/base identity.
- A second read-only search for `Регламентная` also returned an empty EntitySet list. The current registered OData catalog therefore exposes neither a discovered month-close status set nor a discovered scheduled-operation set; this does not prove those objects are absent from the 1C configuration itself.
- FIN-S1.2 remains open. Remaining AC-1 evidence is a supported authenticated close-status operation on the registered source, tied to the source/company/base/version/freshness binding, plus a qualified mapping from that result to accounting-period closed/open. No test, check, write, posting, or production call was made for this follow-up.
