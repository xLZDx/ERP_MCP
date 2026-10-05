# Autonomous engineering execution log

## Step 21 — source-specific register capability rule

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-05

- Added migration 005 to persist register capability evidence per source.
- The Python adapter and OData sidecar require confirmation for the exact source, register entity
  set, and method. The sidecar rechecks its short-lived live-metadata profile before each operation.
- Configuration-sensitive operations, including `DrCrTurnovers`, return
  `CAPABILITY_UNSUPPORTED` when evidence is absent or stale. No alternate names are guessed and no
  speculative OData data request is issued. Positive and negative evidence is returned in the
  source capability profile.
- Added the internal ERP_MCP ↔ pinned OData sidecar contract, capability endpoint/response tests,
  migration/persistence coverage, and confirmed-positive/unsupported-negative DrCr fixtures.
- Reuse remains pinned to `hacker-cb/1c-odata` SHA
  `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`; upstream source is unchanged. No new OData protocol
  implementation, COM bridge, or GPL-derived core code was added.
- Verification: Python `67 passed, 5 skipped`; sidecar `11/11`; pinned upstream client
  `428 passed, 1 skipped`; metadata `53 passed`; PostgreSQL integration `4 passed`; Ruff,
  compileall, Bandit, and `git diff --check` pass. The rebuilt image returned `/healthz` 200 as UID
  10001 with no published ports.
- Next: publish this batch and wait for hosted CI; then continue with semantic profile/preset
  lifecycle and deterministic tests. Real-source semantic validation still requires a real 1C base.

## Step 22 — semantic profile/preset foundation

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-06

- Rechecked the pinned Aprovodka SHA `7b62c90e1fe74324605dc28d76f195200bb97252`: preset types,
  BP 3.0/UT 11/ZUP 3.1/ERP 2 data, accounting/register read-side tools, and `tests/presets.test.ts`.
  Its `verified` label refers to upstream documentation, not a concrete customer source; ERP_MCP
  therefore imports only the four preset identities as `CANDIDATE_ONLY` references.
- Added migration 006 for source/company-scoped, versioned semantic profiles and canonical mappings,
  preserving upstream repository/SHA and metadata/capability/profile fingerprints. Runtime role is
  read-only; admin role can maintain profiles/mappings but cannot delete them.
- A profile can be used only when explicitly `VALIDATED`, exact source/company and metadata match,
  metadata drift is acknowledged, and ten passing native-report reconciliation cases are present.
  Capability dependencies still require current positive source evidence and deny with
  `CAPABILITY_UNSUPPORTED` otherwise.
- Metadata-fingerprint changes automatically stale previously validated profiles via a narrow
  `SECURITY DEFINER` trigger on source capability updates; no broad runtime UPDATE privilege is
  granted.
- Verification: full Python suite `73 passed, 6 skipped`; Ruff, compileall, Bandit pass; disposable
  PostgreSQL applied migrations 001–006, privilege checker passed, PostgreSQL integration `5/5`.
  The prior capability batch CI Python job passed on `e964e32`; pinned OData job remains queued.
- Still not implemented: validated accounting mappings/tools, administrator workflows/audit, and
  actual native 1C reconciliation. No preset is promoted from candidate based solely on its name.

## Step 23 — operator profile lifecycle and audit

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-06

- Added operator-only CLI commands to create a source/company-scoped draft, add candidate mappings,
  validate, and retire profile versions. Creation requires supported live metadata and acknowledged
  stable drift state; validation compares the stored live source capability/metadata fingerprints
  and checks every mapping's exact register dependency before promotion.
- Validation normalizes evidence to ten or more distinct passing case IDs and controlled native
  report references; raw reports are not copied into PostgreSQL. Database checks enforce case count,
  uniqueness, PASS state and non-empty report references.
- Migration 007 adds an append-only profile lifecycle event table. Runtime role can only read it;
  admin can append but cannot update/delete event history. Profile administration itself is restricted
  to the admin connection.
- Added [operator workflow documentation](../docs/SEMANTIC_PROFILES.md), lifecycle and privilege
  integration coverage. Verification: Python `74 passed, 7 skipped`; disposable PostgreSQL applied
  migrations 001–007, privilege checker passed, PostgreSQL integration `6 passed`; Ruff, compileall,
  Bandit, pip-audit (`no known vulnerabilities`) and diff checks pass.
- Preset mappings remain candidate-only until a real source has been inspected and native reports
  reconciled. Canonical MCP accounting tools are still not exposed.
- Hosted CI run `37375030150` on `5f7061d` passed both the gateway/database test job and pinned
  `odata-upstream` job. A duplicate same-SHA run remains queued and is not used as acceptance
  evidence.

## Step 24 — pinned semantic preset candidate data

**Status:** implemented and verified locally and in hosted CI.
**Date:** 2026-10-06

- Re-read the exact pinned Aprovodka preset files/types/tests at SHA
  `7b62c90e1fe74324605dc28d76f195200bb97252`; imported a selected, explicitly documented subset
  of entity-set hints for BP 3.0, UT 11, ZUP 3.1 and ERP 2. The source's `verified`/`common` labels
  are retained only as upstream confidence metadata, not as evidence about an installed base.
- Semantic profile creation persists candidate entity names, kinds, upstream confidence, exact
  repository/SHA/path provenance, and `CANDIDATE_ONLY` status. Candidate names are never sent to
  OData or used to promote a profile. The per-source capability check remains the only operation
  gate; unconfirmed register calls return `CAPABILITY_UNSUPPORTED`.
- Updated third-party attribution with the Aprovodka MIT notice. Added catalog invariants and a
  PostgreSQL lifecycle assertion that candidate records remain candidate-only.
- Verification: Python `74 passed, 7 skipped`; migrations 001–007 and DB privilege policy pass;
  PostgreSQL integration `6 passed`; Ruff, compileall, Bandit, pip-audit (no known vulnerabilities)
  and `git diff --check` pass. The pinned upstream source remains unchanged.
- Hosted CI run `37375751454` on `de03524` passed both gateway/database tests and the pinned upstream
  OData build, contract tests, and non-root image smoke.
- Next software work: executable company-filtered business reads, canonical accounting tools,
  completed audit/operations proof and remaining deployment/security gates. Promoting a candidate
  or validating accounting semantics still requires a real target 1C source and native reports.

## Step 25 — company-scoped account-turnover semantic vertical slice

**Status:** implemented and verified locally; phase PR / hosted CI pending.
**Date:** 2026-10-06

- Reused the pinned Aprovodka accounting contract at `7b62c90e1fe74324605dc28d76f195200bb97252`
  (`tools/accounting.ts`): BalanceAndTurnovers is period-bounded; company/account selection is an
  explicit condition. OData request construction and register execution remain in the pinned
  `hacker-cb/1c-odata` sidecar (`cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`).
- Added `accounting_balance_and_turnovers`: it authorizes the exact source/company before metadata
  or data access, accepts no caller-selected EntitySet/filter/register args, and requires a
  validated exact-company profile plus explicitly `CONFIRMED`/`HIGH` mapping, current fingerprints
  and live `balanceAndTurnovers` capability. Company conditions are built only from operator-mapped
  field/type and the registry external reference. Seven source fields map to canonical output keys;
  missing fields fail closed and numeric/currency values are not silently converted.
- Migration 008 adds explicit mapping confirmation and invalidates/audits direct post-validation
  mapping changes. Migration 009 adds semantic profile fingerprint to audit events. Operator CLI
  records controlled evidence references and append-only lifecycle events.
- Added source/company deny-before-1C, unconfirmed-mapping no-dispatch, profile scope/drift,
  condition escaping, output normalization, audit provenance and PostgreSQL trigger tests.
- Verification: full Python suite `80 passed, 7 skipped`; disposable PostgreSQL migrations 001–009,
  privilege checker PASS and integration `6 passed`; Ruff, compileall, Bandit pass. A real 1C base
  and native reports remain necessary to promote any customer mapping; remaining canonical P4 tools
  are not yet implemented.

## Step 26 — company-scoped sales and purchase document reads

**Status:** implemented; local and hosted CI PASS.
**Date:** 2026-10-06

- Extended the evidence-backed semantic mapping lifecycle to sales and purchases. Each mapping
  requires a confirmed `Document_*` EntitySet, company equality field/type, canonical field mapping,
  and a date order field; caller input cannot select an EntitySet, filter, or projection.
- Added `sales_documents` and `purchase_documents`. Both authorize the exact source/company before
  metadata or business data, require a current validated source/company profile, derive the company
  predicate only from the mapping and registered external reference, bound page size, normalize
  seven canonical document fields, and record profile/metadata fingerprints in audit.
- Protocol and transport continue through the existing pinned OData adapter/sidecar; no new OData
  protocol implementation was introduced. Other P4 domains (cash/bank, inventory, AR/AP aging,
  tax/VAT and posting trace) and real native-report reconciliation remain open.
- Verification: Python `83 passed, 7 skipped`; disposable PostgreSQL 16 migrations 001–009, DB
  privilege policy and PostgreSQL integration `6 passed`; Ruff, compileall, Bandit, pip-audit and
  diff check PASS. Hosted CI run `37380789434` passed both `test` and `odata-upstream` jobs on
  commit `b212790`.

## Step 27 — source-capability-gated inventory balance snapshot

**Status:** implemented; local and hosted CI PASS.
**Date:** 2026-10-06

- Reused pinned Aprovodka `getAccumulationBalance` semantics and its `Balance(Period, Condition)`
  shape, plus UT11/ERP2 candidate descriptions for `AccumulationRegister_ТоварыНаСкладах`; the
  preset entity name remains advisory and is never selected automatically. Reused pinned OData
  `RegisterHelper.balance` and the existing sidecar's live metadata capability gate.
- Added `inventory.balance` profile mapping with exact accumulation-register entity, `Balance`
  dependency, required company dimension, and reviewed item/warehouse/quantity projection.
  `inventory_balance` requires an explicit timezone-qualified point-in-time period and exact
  source/company authorization. It does not infer quantity by summing documents or switch methods.
- Positive semantic/capability/normalization/runtime fixtures and negative tests prove unconfirmed,
  cross-source, stale, or unavailable capability evidence cannot dispatch a register request.
  PostgreSQL lifecycle coverage includes inventory and purchase mapping confirmation/profile load.
- Local full suite at implementation: Python `90 passed, 7 skipped`; Ruff, compileall, Bandit,
  pip-audit and diff check PASS. Disposable PostgreSQL 16 migrations 001–009 and DB privilege
  policy PASS; integration `6 passed`. Hosted CI run `37381909454` passed both jobs on `90cd70c`.

## Step 28 — source-capability-gated bank balance snapshot

**Status:** implemented; local and hosted CI PASS.
**Date:** 2026-10-06

- Reused Aprovodka's pinned `getAccumulationBalance` implementation/tests and UT11's
  `AccumulationRegister_ДенежныеСредстваБезналичные` preset description. The upstream preset marks
  this candidate `common`; it is not treated as source evidence. Reused pinned OData `Balance` and
  the sidecar's exact live metadata recheck.
- Added `bank.balance` with a source/company-scoped `Balance` mapping for bank-account reference,
  currency and amount, plus the `bank_balance` tool. EntitySet and all projection/filter fields must
  be operator-confirmed; monetary values are preserved without conversion.
- Tests cover typed company filtering, explicit timezone period, canonical output, exact live
  capability evidence, and PostgreSQL profile lifecycle. No caller-supplied register/filter and no
  OData protocol code were added.
- Local full suite: Python `93 passed, 7 skipped`; disposable PostgreSQL 16 migrations 001–009,
  privilege policy and integration `6 passed`; Ruff, compileall, Bandit, pip-audit and diff check
  PASS. Hosted CI run `37382615109` passed both jobs on `c6605b8`.

## Step 29 — company-scoped receivable/payable balance snapshots

**Status:** implemented locally; verification and publication in progress.
**Date:** 2026-10-06

- Reused Aprovodka's pinned UT11 candidate inventory for customer/supplier settlement accumulation
  registers and its existing point-in-time accumulation `Balance(Period, Condition)` implementation
  and tests. The candidate names are explicitly tagged `common` and never selected automatically.
- Added distinct `receivable.balance` / `payable.balance` mapping contracts and MCP tools. Each
  requires exact source/company authorization, a validated profile and exact live source
  `AccumulationRegister_*/Balance` capability; canonical projection is counterparty, contract and
  amount. Caller input cannot choose a register or filter.
- These tools deliberately return balances only: they do not calculate aging, overdue days, net
  positions, or infer due dates. Such semantics need a separate reviewed profile and native report
  reconciliation.
- Local full suite: Python `101 passed, 7 skipped`; disposable PostgreSQL 16 migrations 001–009,
  privilege policy and integration `6 passed`; Ruff, compileall, Bandit pass. Hosted CI and final
  pip-audit/diff-check for this batch follow publication.

## Step 30 — P5 deterministic L1 seed and accounting scenario contract

**Status:** implemented locally; publication/hosted CI pending.
**Date:** 2026-10-06

- Fake1C now loads the versioned `erp-mcp-synthetic-v1` JSON seed as its single source of truth and
  exposes sales/purchase plus inventory, bank, receivable and payable fixture EntitySets in metadata
  and GET responses. All fixture routes remain read-only.
- Upgraded the ten accounting scenarios to schema v2 with stable fixture IDs, executable expected
  invariants, and explicit `NOT_RUN` native 1C reconciliation status. The validator computes a
  canonical seed SHA-256 and rejects broken invariants or synthetic evidence falsely marked as
  native. Added a real-L2 snapshot manifest template whose required values are clearly unfilled.
- CI now runs `scripts/validate_scenarios.py`. Verification: Python `104 passed, 7 skipped`; Ruff,
  compileall, Bandit, pip-audit and scenario validator pass. Hosted CI run `37383877277` passed both
  jobs. These L1 artifacts are not L2/L3
  environment evidence and do not unblock native report validation.

## Step 31 — P6 isolated RSV bridge process and health boundary

**Status:** implementation in progress; data route intentionally fail-closed.
**Date:** 2026-10-06

- Re-read the pinned MIT `mcp-rsv-data` bridge contract (`serve.go`, `onec.go`, `config.go`) and
  product guide. Reuse is via the existing MCP stdio process; no COM/native-query/stdio protocol
  implementation was added to ERP_MCP.
- Added an MCP SDK process client with strict source-ID-to-config mapping, minimal child environment,
  exact upstream tool inventory check, ping-only health, restart-per-check recovery and sanitized
  errors. Added runtime wiring, paired absolute-path settings, negative tool-inventory/path tests,
  and a Windows installation/ACL/recovery runbook.
- Generic `query`/`execute_query` are not forwarded. Bridge health is not source capability evidence;
  until per-source/company query mapping can enforce company scope, business reads remain
  `CAPABILITY_UNSUPPORTED`.
- Initial targeted tests: 9 passed; Ruff reported import/style findings, corrected before final
  verification. Full suite, hosted CI and Windows/COM smoke remain pending.

## Step 32 — P7 legacy demand gate

**Status:** deferred for modern MVP; no 8.2 target evidence exists.
**Date:** 2026-10-06

- Kept the GPL-3.0 1c-mcp-toolkit on the isolated-service-only path. No source or dependency from it
  is added to ERP_MCP core.
- Formalized the demand gate: reopen only for a named 1C 8.2.13+ target and accountable owner, then
  do license/isolation/read-only review before deployment. This avoids shipping an unused legacy
  route or claiming platform compatibility without a test target.

## Step 33 — P8 protected aggregate HTTP metrics

**Status:** implementation in progress.
**Date:** 2026-10-06

- Added dependency-free HTTP request count, in-flight and latency histogram metrics. Labels have
  fixed route/method/status cardinality and never contain source/company/subject, URL IDs, or query
  data. `/metrics` is not found unless a 32-byte bearer token is explicitly configured.
- Added endpoint authorization, settings and middleware tests; documented per-process/reset behavior
  and secret-store handling. This is a narrow observability slice; it does not close D12 or replace
  audit, source-health, database, or distributed telemetry.
- Full local verification: Python `112 passed, 7 skipped`; Ruff, Bandit, compileall, pip-audit,
  scenario validator and diff-check pass. Hosted CI run `37384949997` passed both jobs.

## Step 34 — P9 fail-closed pilot evidence gate

**Status:** implementation in progress; production GO remains blocked by absent external evidence.
**Date:** 2026-10-06

- Added a privacy-safe manifest template bound to an exact 40-character release SHA and positive
  pilot scope counts. Fixed gate names cover CI/config/auth/secrets/isolation/capabilities, ten
  native reconciliations, zero-write/audit, load/resilience, backup/restore/rollback, operations,
  privacy, user acceptance, and release approval.
- Added strict schema/evidence metadata validation and a `--require-go` mode. Unknown/freeform
  fields are rejected to discourage PII/secret collection. CI validates the template and asserts
  that an empty template cannot pass GO. Evidence artifacts remain in an approved external store;
  a human reviewer must verify their contents and hashes.
- No real pilot/native report/IdP/restore evidence is available, so current disposition is
  explicitly `NOT_READY` rather than inferred or synthesized.
- Verification: Python `116 passed, 7 skipped`; Ruff, Bandit, compileall, pip-audit, scenario
  validator and diff-check pass. The template validates; `--require-go` fails as intended. Positive
  and negative evidence fixtures pass. P9 test job passed in run `37385325901`; upstream image
  job is pending completion.
