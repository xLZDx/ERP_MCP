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

## 2026-10-07 - Data-plane User E2E suite U01-U18 (branch e2e/user-flows)

- Decision: Fake1C (testbed/fake1c/app.py) now records every request (method, path, user agent,
  numeric $top/$skip, credentials-present flag; no header values) at `/__ft__/requests`, the same
  shape as the Functional Tester recorder, so U04/U06/U11/U13/U14 can prove "only GET/HEAD" and
  "no upstream request on denial". The fake also honours `$select`/`$skip` like real OData.
- Finding (needs GPT-PM contract clarification): the baseline seed grants UC1 a company-one grant
  only, but source-level tools (source_health, onec_*) require a source-wide grant in the registry
  (`g.company_id IS NULL`), and a source-wide grant also covers company two. U02-U04/U11-U14 therefore
  run under a temporary source-wide grant created/revoked through the Admin API; U05-U10 use the
  baseline company-scoped grants. The denial under the company-only grant is asserted explicitly.
- Evidence: collect-only and ruff clean; not yet executed (environment owned by lane A).
- U05-U10 written under the baseline seed. Company row-content assertions skip with the explicit reason `BLOCKED-no-validated-semantic-profile` (a validated profile needs native reconciliation evidence, intentionally not faked); access decisions are proven by the `ACCESS_AUTHORIZED` audit receipt and the Fake1C request log. U08 removes the group at the IdP by editing the git-ignored `.e2e/idp-config.json` and restarting the test IdP, restoring the original bytes in `finally`.
- U11-U18 written. Outage rows (U14-U16) use scripts/e2e/fault.ps1 inside `outage()` whose `finally` always restarts the component; recovery is polled on an observable condition (a successful call), the gateway is never restarted. Observed contract recorded in the tests: with Redis down the rate-limited source/company tools fail closed while system_status/sources_list (no limiter) keep working; onec_read bounds rows by clamping `$top` to max_rows and exposes no truncation flag. U18 runs `pytest tests/functional` with FT_* wired from .e2e/env.json, or skips with `FT-suite-not-merged`.
- Lint-only follow-up: removed an unused noqa in testbed/fake1c/app.py (ruff RUF100).
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
- Executed against the live environment (up.ps1 -Seed baseline, then test.ps1 -Suite user): 41 passed, 3 skipped (U05/U06 row-content `BLOCKED-no-validated-semantic-profile` x2, U18 `FT-suite-not-merged`), 0 failed. One test defect fixed: U12 expected CamelCase exception names but the audit detail_code is `SEMANTIC_PROFILE_UNVALIDATED`. Observation: the MCP client sees only the generic text "Error executing tool <name>" for every failure; specific codes are visible only in audit rows. The pre-existing lane-A PostgreSQL volume `erpmcp-e2e-pgdata` (old secrets) was removed with `down.ps1 -Purge` to initialise this worktree's own secrets.
# Decision log (functional-tester branch qa/functional-tester-sc01-sc12)

## 2026-10-07 - Black-box functional suite for SC01-SC12

- Decision: author tests/functional (real MCP Streamable-HTTP client, env-parametrised FT_*) and a
  private disposable stack (scripts/ft, ports 25432/26379/28766/28000). No src/, migration or
  security-boundary change.
- Decision: statuses are observed at run time. A scenario is PASS only if a public tool answered and
  the invariant held; otherwise EXTERNAL-GATE (tool fails closed: no VALIDATED semantic profile, and
  bag.semantic_profiles requires ten native-report cases by DB check constraint) or NOT IMPLEMENTED
  (no public tool/data). No synthetic profile or native evidence was fabricated.
- Evidence: Fake1C is synthetic L1 only; never native 1C reconciliation.
- Commit: see git log on this branch.

## 2026-10-07 - Dispositions and token default

- SC10 args now timezone-qualified (tester bug). SC06 encoded EXTERNAL-GATE (VAT only when validated), SC08 NOT IMPLEMENTED (outside frozen scope; needs operator rebaseline). FT_BEARER_TOKEN is now the default identity for every call.

## 2026-10-07 - Suite moved onto the fixture-profile stack

- Stack now BAG_ENVIRONMENT=test with the reviewed synthetic fixture profile file (SHA-256 pinned at setup), source tag synthetic-fixture, test-only fake sidecar behind a recording wrapper (:28767). SC01-SC05, SC07, SC09-SC12 evaluate real tool output (PASS, L1 synthetic only); SC06 EXTERNAL-GATE, SC08 NOT IMPLEMENTED by decision. Final run 73 passed, 3 skipped (needs-oidc-identity), 2 xfailed (SC06, SC08).

## 2026-10-07 - Review remediation F1-F6 (aging fail-closed, honest audit)

- Decision: the sidecar client `read` now returns the envelope `page`; receivable/payable aging treats `page.truncated` (any non-False value) as INCONCLUSIVE/AGING_ROWS_TRUNCATED with no partial rows. Other semantic tools already echo `result["page"]`, so they now expose the flag without further change.
- Decision: float amounts with more than 15 significant digits are rejected as SETTLEMENT_FACT_INVALID instead of rounded (chosen over parse_float=Decimal to avoid changing numeric typing of every other tool). Row parsing catches only OpenItemsInvalid (unhashable record types are now bad data); evaluate_aging/scope/profile errors propagate and audit as outcome=error. A response without a `value` list is INCONCLUSIVE/SOURCE_RESPONSE_INVALID, never an empty PASS.
- Decision: audit vocabulary is unchanged (success/error/denied; no migration). COMPANY_SCOPE_MISMATCH, SETTLEMENT_FACT_INVALID, AGING_ROWS_TRUNCATED and SOURCE_RESPONSE_INVALID audit as `error` (closest existing non-success value; `denied` is reserved for authorization). Non-conclusive aging detail_code is `<profile marker>:<reason>` (e.g. SYNTHETIC_FIXTURE_PROFILE:AGING_ROWS_TRUNCATED); exception-path audit also keeps the marker and profile fingerprint.
- Decision: profile_provenance raises PROFILE_PROVENANCE_UNKNOWN unless profile_kind is VALIDATED_NATIVE or SYNTHETIC_FIXTURE.

## 2026-10-07 - Review remediation F7: test doubles out of the production image

- Decision: `.dockerignore` gains `**/testbed` so `src/business_ai_gateway/testbed/` (Fake1C, fake sidecar) is not in the production build context; the root `testbed` entry only matched the top-level directory. No production module imports the package (static test asserts this and the Dockerfile COPY lines). Scripts copied into the image that import it (fanout_load_drill, synthetic_fixture_profiles) are CI/test tools and are not run from the image; the CI image smoke only imports business_ai_gateway.app.

## 2026-10-07 - Review remediation F8: product chain tests cannot silently skip

- Decision: the four product chain modules share `tests/sc_stack.py` PG_MARKS/needs_pg; with ERP_MCP_REQUIRE_DB_TESTS=1 and no BAG_PRIVILEGE_TEST_DATABASE_URL they fail (fixture `require_pg_database`) instead of skipping; CI sets the variable on the pytest step. Assertions strengthened: naive-timestamp tests assert error detail/no audit row and no upstream read, SC04 asserts the exact audit rows, stale-fingerprint and invalid-VALIDATED-row tests assert no upstream read; dead `deltas` line removed.

## 2026-10-07 - Review remediation: fallout and checkpoint re-pin

- Decision: test doubles in tests/test_server_audit.py that stand in for the registry now carry `profile_kind: VALIDATED_NATIVE` like the real registry (required by the stricter profile_provenance); SC04 audit assertions match the exact rows (access row plus tool row); engineering checkpoint fingerprint and report markers re-pinned to the new implementation content. Full suite with own PG/Redis and ERP_MCP_REQUIRE_DB_TESTS=1: 1189 passed, 140 skipped (live-stack e2e/functional suites and the 6 env-gated tests).
## 2026-10-07 - Admin E2E suite A01-A54 (branch e2e/admin-flows)

- Decision: the Admin suite runs on seed mode bootstrap-only; source, companies, role bindings and grants are created through /admin/ by the `world` fixture (tests/e2e/admin/admin_support.py). The suite fails loudly (never skips) when the environment is not pristine.
- Decision: contract rows whose evidence the product does not currently produce (login/logout audit rows for A01, audit trail for 401 denials in A03/A04) are asserted strictly in their own tests so a failure is visible and classified, not weakened.
- Evidence: batches so far (A01-A54) collect cleanly and are ruff-clean; executed next against the live environment.
- 2026-10-07 acceptance: clean up/status/smoke/reset/smoke/up/fault/down all executed; service launch changed to cmd.exe ShellExecute so callers reading output pipes do not hang. check_document_consistency reports a stale engineering checkpoint (implementation fingerprint covers scripts/tests/testbed); refresh is left to the integrator after merge.
- Finding (live run 1, 62 passed / 20 failed): Admin UI inline onclick handlers are blocked by the page CSP script-src self, so Create grant, Sign out, dialog Submit/Cancel and Retry do nothing in a real browser; tests isolate this in test_A45_ui_actions_are_not_blocked_by_the_page_csp and open dialogs programmatically for other rows.
- Finding: profile validation cannot succeed locally without register-capability evidence (no sidecar): CAPABILITY_UNSUPPORTED; validation-success tests report this as an environment limitation.
- Evidence (live, seed bootstrap-only, two consecutive full runs from a reset environment): 76 passed / 12 failed / 12 deselected(smoke) in 459s and 528s with an identical failure set; every failure is a strict product-defect or environment-limitation test (audit gaps A01/A03/A16, broken metadata accepted A39, inline onclick blocked by CSP A45/A49, focus loss A46, same-dialog retry 409 A50, no register-capability evidence A06/A40).

## 2026-10-07 - Admin defect fix P4 (branch fix/admin-defects)

- Decision: `parse_metadata` rejects well-formed XML that is not OData `$metadata` (root must be Edmx with Schema/EntityType/EntitySet). An HTML 200 for `$metadata` therefore yields metadata_supported=false and no fingerprint, so the admin refresh fails with an audited error and the previous STABLE evidence is untouched (A39). Regression: tests/test_metadata.py, tests/test_compatibility.py.

## 2026-10-07 - Admin defect fix P8 (branch fix/admin-defects)

- Decision: server-side fix, UI keeps its key (scripts/verify_admin_ui.py already requires key retention on retry). A prior idempotency outcome of `error` (domain write rolled back; only reservation and audit row persisted) with the same actor+command+payload fingerprint is re-armed to `pending` and re-executed; success still replays, different payload/command still 409 (A29/A30), concurrent callers serialize on the row lock. Regression: tests/test_admin_mutations_postgres.py::test_failed_attempt_is_retryable_with_the_same_key_and_payload. No migration.

## 2026-10-07 - Admin defect fix P1/P2/P3 audit gaps (branch fix/admin-defects)

- Decision: no CHECK constraint exists on bag.admin_audit_events.action (only outcome IN success/error/denied/conflict), so no migration. New action values: `session.login`, `session.logout` (A01, verified subject/client from the session; client_id stored in the Redis session record), `auth.denied` (A03/A04), `source.probe` (A16; actor, target host only, outcome, no URL or secrets).
- Decision (flood control): a rejected bearer is audited only when it is JWT-shaped (3 base64url segments, <=8 KiB) and at most 30 rows/minute/process; the row uses actor `unverified` and carries no token material or unverified claims. Plain garbage, scanners and missing credentials leave no row. Audit write failures never change the 401/probe response.
- Regression: tests/test_admin_session.py (login/logout audit, bounded denial audit).
