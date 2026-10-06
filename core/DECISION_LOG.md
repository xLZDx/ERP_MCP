# ERP_MCP decision / evidence log

Append-only. One dated entry per durable decision, evidence or refusal that future work needs.

## 2026-10-06 — Freeze E2E acceptance contract before product changes

- Decision: `docs/E2E_ACCEPTANCE_CONTRACT.md` freezes U01–U18 and A01–A54 (actor, action,
  expected, negative, evidence, class) before any product fix or E2E implementation, so the
  acceptance surface cannot move during implementation. Changes need a new plan amendment.
- Decision: tracked closing documents record `CODE_EVIDENCE_SHA` and local counts and mark hosted
  CI as pending; the exact final head SHA and hosted run IDs are recorded only in the PR #11
  body/comment (a tracked file cannot contain its own commit SHA or the CI run of that commit).
- Evidence: baseline with PostgreSQL 16 + Redis 7 locally: 1157 passed, 6 skipped (previous
  checkpoint: 39 skips). Remaining skips: 3 private-Ferma, 1 real-1C OData, 1 live-RSV (now run
  and passing locally), 1 native lifecycle (passes via `scripts.rsv_native_lifecycle_harness`).
- Refusal: RSV `reveal`, `execute_query` and generic business query stay disabled (documented
  privacy/company-scope/upstream-bound constraints are not remediated).

## 2026-10-06 - Disposable local E2E environment (branch e2e/local-environment)

- Decision: gateway, Fake1C and the test IdP run as host processes (uvicorn from the worktree
  venv); only PostgreSQL 16 and Redis 7 run in compose project `erpmcp-e2e`. Rationale: identical
  issuer/audience URLs for browser and gateway, trivial stop/start fault injection; the
  production gateway image is already built and scanned in CI.
- Decision: secrets are generated randomly once under the git-ignored `.e2e/`; the test IdP is
  the only place identities live. ERP_MCP gained no user-creation path and no 1C write path.
- Evidence: see docs/E2E_ENVIRONMENT.md and the commit history of this branch.

## 2026-10-07 - E2E test scaffolding

- Decision: tests/e2e is auto-skipped only when .e2e/env.json is absent and ERP_MCP_E2E_NO_SKIP is unset; scripts/e2e/test.ps1 sets it so a missing environment is an error.
- Evidence: 12 smoke tests green against the live environment (tests/e2e/test_smoke_environment.py).

- 2026-10-07 acceptance: clean up/status/smoke/reset/smoke/up/fault/down all executed; service launch changed to cmd.exe ShellExecute so callers reading output pipes do not hang. check_document_consistency reports a stale engineering checkpoint (implementation fingerprint covers scripts/tests/testbed); refresh is left to the integrator after merge.
## 2026-10-07 — Test-only synthetic fixture semantic profiles (SC public coverage, step 1)

- Decision: reviewed synthetic fixture profiles are a code-level provider
  (`src/business_ai_gateway/fixture_profiles.py`), never a `bag.semantic_profiles` row, never
  VALIDATED, no migration. The ten-native-reports rule (DB CHECK 006, admin validate, runtime
  `require_usable_semantic_profile`) is untouched; a real VALIDATED row always wins, and any
  non-retired DB profile for the same source/company/concept blocks the fixture (no fall-through).
- Hard deny layers (each tested): (1) `Settings` rejects the file/sha settings in production,
  when incomplete, or when `BAG_ENVIRONMENT != test`; (2) provider constructor and every lookup
  require environment `test`, and `Registry(production=True, synthetic_profiles=...)` is refused;
  (3) the source must be listed in the pinned file AND carry tag `synthetic-fixture`; (4) a file
  SHA-256 mismatch fails `Runtime` startup. Open decision resolved: `development` is NOT permitted;
  the functional stack must run with `BAG_ENVIRONMENT=test`.
- Provenance: every semantic tool response now carries `profile_kind`, `evidence_level`,
  `native_reconciliation`, `warnings`; fixture responses are `SYNTHETIC_FIXTURE`/`L1`/`NOT_RUN` with
  warning `SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE`, fingerprint prefix `synthetic-fixture:` and
  success audit `detail_code=SYNTHETIC_FIXTURE_PROFILE`.
- Deviations from the design (code contradicted it): (a) `register_read` and the register
  capability evidence required by every profile tool need the OData sidecar; plain Fake1C cannot
  serve them, so a test-only protocol double `testbed/fake1c/sidecar_app.py`
  (`business_ai_gateway.testbed.fake_sidecar`) was added; (b) Fake1C ignored `$filter/$orderby/
  $select/$skip`; it now evaluates the conjunctive filters the gateway builds (read-only); (c) the
  fixture pins the metadata fingerprint only; capability evidence is bound to it by
  `require_profile_capabilities`. Re-pin with `scripts/synthetic_fixture_profiles.py --write`.

## 2026-10-07 - Refresh engineering checkpoint after SC step 1

- Evidence: with disposable PG16+Redis7 the full suite is 1170 passed, 6 skipped (baseline 1157/6 plus 13 new fixture-profile chains); `validate_scenarios.py` and `check_document_consistency.py` pass. The implementation fingerprint in `reports/CURRENT_ENGINEERING_CHECKPOINT.json` and report markers was refreshed mechanically (PR/gate dispositions unchanged: NO-GO, PARTIAL).

## 2026-10-07 - SC step 2: Fake1C data for SC04/SC05/SC07/SC09 and seed consistency

- Decision: Fake1C seed gains dates/counterparty/currency on Document_Sales/Purchases, an unposted sale for organization one (SALE-003), a backdated posted sale (SALE-004, 2025-12-31) with posting rows only for posted documents in a new AccountingRegister_Ledger, inventory item 002 (receipt 10, return recorded as an expense row 3, balance 7), an earlier cash receipt (93, 2026-03-15) so the 2026-03-01..05-01 window nets 100 = scenario fixture, and the inventory balance of item 001 corrected 7 -> 5 to equal its movements. No migration, no new tool, no return direction.
- Consequence for testers: SC11 April inventory window now contains two items; per-item net (item 001 = 5) is the SC11 invariant and item 002 net 7 equals its Balance (SC05).
- Fixture file re-pinned to the new Fake1C metadata fingerprint (sales, accounting.posting_rows, inventory.balance, bank.balance concepts added).

## 2026-10-07 - SC step 3: SC10 account turnover on Fake1C

- Decision: the fake sidecar serves a read-only `balanceAndTurnovers` virtual table for `AccountingRegister_Ledger` (capability evidence carries the live metadata fingerprint; sidecar `virtual_tables` is overridable so a missing capability is testable). Seed row 100 + 40 - 15 = 125 for organization one; other companies get no rows; naive timestamps are rejected by the existing tool validator. No metadata or migration change.

## 2026-10-07 - SC step 4: receivable_aging / payable_aging (SC01-SC03)

- Decision: two new read-only tools reuse capability keys ar.read/ap.read (no policy migration) and the existing aging engine; new concepts receivable.open_items / payable.open_items validated by `settlement_collector.py` (deviation: validator lives there, not semantic.py, to keep semantic.py unchanged) and wired into the shared registry validator chain and scripts/semantic_profiles.py. Fixture covers receivable only; payable has no fixture profile and is fail-closed. validated_profiles is derived server-side, never from tool input; evidence level is L1 for fixtures, mapping-declared for native profiles. Fake1C gains AccumulationRegister_SettlementItems (additive wiring); company-two item proves scope isolation.
- SC06 stays EXTERNAL-GATE and SC08 NOT IMPLEMENTED (out of freeze), unchanged.
