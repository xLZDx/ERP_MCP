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
## 2026-10-07 - E2E remediation 2: tests on the fixture-profile stack (U05-U07, U10, U12, U14-U16, U18)

- Decision: the E2E sidecar component runs a recording wrapper (testbed/fake1c/sidecar_recording_app.py: method, path, operation, entity_set, top/skip, select field names; never headers/filter text/tokens). With the sidecar configured the gateway reads entity data through it, so user tests use UpstreamLog (Fake1C + sidecar) for no-upstream-traffic and bounded/projected-read proofs; U14 Fake1C outage uses source_health and metadata (not onec_read); a new sidecar outage test covers onec_read.
- Decision: U05/U06 assert exact row content under the fixture profile; BLOCKED skips removed. U07 asserts companies_list audits success with returned_items=0. U10 asserts data after re-grant. U12 splits: concepts without fixture mapping (receivable_balance, payable_balance, payable_aging) still fail closed; fixture-confirmed tools are asserted SYNTHETIC_FIXTURE/L1/NOT_RUN. Naive timestamps in old U12 args were a latent test defect (ValueError, not the capability gate).
- Decision: U14-U16 assert transport_error is None, sanitized audit detail codes; U15 uses onec_read that succeeds when healthy under a temporary source-wide grant; U16 checks /metrics (BAG_METRICS_TOKEN) error counter.
- Decision: U18 is exact: SC01..SC12 present; SC01-05,07,09-12 passed; SC06 xfail EXTERNAL-GATE and SC08 xfail NOT IMPLEMENTED only; no failure/error; only skips allowed are two dev-mode-only FT cases (admin.py grant manipulation, skipped by design when a bearer token is set; covered by U09/U10). FT_BEARER_TOKEN* wired from the IdP; uc1 has a temporary source-wide grant for the run. FT_EXPECT_CAPABILITY_ENFORCEMENT=0 only unskips a case that proves grant denial (E2E keeps capability enforcement off).

## 2026-10-07 - E2E remediation 3: docs, U04 on the sidecar recorder, checkpoint re-pin

- Decision: docs/E2E_ENVIRONMENT.md documents the fixture-profile stack, relocation (E2E_PORT_OFFSET/E2E_PROJECT_SUFFIX), process identity, skip policy and the in-memory IdP revoked_sids limitation. U04 accepts the sidecar POST /v1/read as the read-only upstream verb and proves projection/top on the sidecar recorder. Engineering checkpoint fingerprint re-pinned (implementation content changed) and dashboard synced; no gate status changed (NO-GO/PARTIAL untouched).
- Evidence (alternate topology offset 3000, project erpmcp-e2e-rem, from clean): smoke 15 passed; user 52 passed 0 skipped after reset; fault stop/start of fake1c, sidecar, idp, gateway, redis, postgres each flips status 1 then 0. One non-reproduced U18 failure (SC05 inventory_balance CAPABILITY_UNSUPPORTED) occurred once in the first full run after a fresh up; three later runs (partial order and full) passed.

## 2026-10-07 - Admin defect fix P4 (branch fix/admin-defects)

- Decision: `parse_metadata` rejects well-formed XML that is not OData `$metadata` (root must be Edmx with Schema/EntityType/EntitySet). An HTML 200 for `$metadata` therefore yields metadata_supported=false and no fingerprint, so the admin refresh fails with an audited error and the previous STABLE evidence is untouched (A39). Regression: tests/test_metadata.py, tests/test_compatibility.py.

## 2026-10-07 - Admin defect fix P8 (branch fix/admin-defects)

- Decision: server-side fix, UI keeps its key (scripts/verify_admin_ui.py already requires key retention on retry). A prior idempotency outcome of `error` (domain write rolled back; only reservation and audit row persisted) with the same actor+command+payload fingerprint is re-armed to `pending` and re-executed; success still replays, different payload/command still 409 (A29/A30), concurrent callers serialize on the row lock. Regression: tests/test_admin_mutations_postgres.py::test_failed_attempt_is_retryable_with_the_same_key_and_payload. No migration.

## 2026-10-07 - Admin defect fix P1/P2/P3 audit gaps (branch fix/admin-defects)

- Decision: no CHECK constraint exists on bag.admin_audit_events.action (only outcome IN success/error/denied/conflict), so no migration. New action values: `session.login`, `session.logout` (A01, verified subject/client from the session; client_id stored in the Redis session record), `auth.denied` (A03/A04), `source.probe` (A16; actor, target host only, outcome, no URL or secrets).
- Decision (flood control): a rejected bearer is audited only when it is JWT-shaped (3 base64url segments, <=8 KiB) and at most 30 rows/minute/process; the row uses actor `unverified` and carries no token material or unverified claims. Plain garbage, scanners and missing credentials leave no row. Audit write failures never change the 401/probe response.
- Regression: tests/test_admin_session.py (login/logout audit, bounded denial audit).

## 2026-10-07 - Admin defect fix P5/P6 (branch fix/admin-defects)

- Decision (P5): all inline `on*` attributes removed from the admin UI; controls carry `data-act` and a single delegated click listener dispatches through an `ACTIONS` registry (functions looked up at call time because several are overridden). CSP is unchanged (script-src 'self', no unsafe-inline). Static guards: tests/test_admin_ui_asset.py (no on* attribute, every data-act registered) and scripts/verify_admin_ui.py (same regex plus the real CSP header on the served page, console CSP violations fail the run).
- Decision (P6): after a render, if focus fell to <body> (route change replaced the nav button, or a closed dialog's opener was re-rendered) focus moves to the main h1 (tabindex -1); a failed Submit restores focus to the previously focused control inside the dialog after the buttons are re-enabled.

## 2026-10-07 - Admin defect fixes: verification and checkpoint re-pin (branch fix/admin-defects)

- Evidence: full pytest with own postgres:16-alpine + redis:7-alpine and ERP_MCP_REQUIRE_DB_TESTS=1: 1196 passed, 228 skipped (baseline 1189 + 7 new tests; skips are env-gated e2e/functional/private); ruff, compileall, scripts/verify_admin_ui.py (real Chromium, page CSP enforced) and check_document_consistency pass. test_admin_api double updated for the new `mutations` attribute used by the rejected-bearer audit. Engineering checkpoint fingerprint and report markers re-pinned.
- Not verified live: the live admin E2E suite could not start because the shared compose volume erpmcp-e2e-pgdata holds a password from an earlier environment (InvalidPasswordError in envctl ensure-roles); fixing it needs `down.ps1 -Purge` (volume deletion), left to the operator. Note: a leftover ignored .e2e/ directory makes the unit suite activate the e2e fixtures and fail massively; keep it out of the worktree when running the full suite.

## 2026-10-07 - Scope dispositions for SC01-SC12 and integration of lane branches

- Decision: SC04/05/07/09/10/11/12 close through a test-only synthetic fixture profile provider (hard-denied
  in production, non-test environments and non-synthetic sources; never native evidence); SC01-SC03 close
  through new receivable_aging/payable_aging (frozen scope SS3.3 AR/AP aging, scope-preserving wiring);
  SC06 (VAT) is EXTERNAL-GATE (VAT views only when a validated profile exists); SC08 (duplicate-counterparty
  detection) is outside the frozen scope and stays NOT IMPLEMENTED pending an explicit operator rebaseline.
- Decision: source-level tools (source_health, onec_*) need a source-wide grant; the baseline seed keeps
  user_company_one company-scoped, and the manual/E2E packs use an explicit temporary source-wide grant
  (operator step) for those cases only. A company-only grant never opens source-level tools or other companies.
- Decision: lane branches (PR #13-#18) are integrated by merge commits (full history, no squash).
- Decision: down.ps1 removes .e2e/env.json (the READY marker) so plain pytest never runs tests/e2e against a
  stopped environment; the Admin product defects P1-P6/P8 found by the Admin E2E suite were fixed on
  fix/admin-defects (strict CSP kept, no migration).
- Evidence: Functional Tester run d8f322b: 73 passed, 3 skipped (needs-oidc-identity), 2 xfailed (SC06, SC08);
  product remediation suite 1189 passed; admin-defects suite 1196 passed (own PG/Redis).

## 2026-10-07 - Admin E2E on candidate d493edb: capability refusal mapping, row labels, declared EXTERNAL-GATE

- Decision: CapabilityUnsupported raised inside an Admin mutation (e.g. profile validate without register-capability evidence) is a domain refusal and now maps to HTTP 409 with the unchanged code CAPABILITY_UNSUPPORTED instead of HTTP 500 ADMIN_DEPENDENCY_FAILED; unmapped exceptions still map to sanitized 500. Regression test: tests/test_admin_api.py::test_capability_refusal_is_a_conflict_not_a_server_fault. No gate was weakened.
- Decision: A06 validate/scope-mapping rows assert the PLATFORM_ADMIN is authorized (4xx domain refusal, never 200/201, audited as error not denied) while the read-only role gets 403; native reconciliation evidence is never fabricated. A40 half "validated profile turns stale on drift" is an explicit EXTERNAL-GATE skip with the exact reason "EXTERNAL-GATE: validated profile requires native reconciliation evidence", the single entry of ALLOWED_SKIP_REASONS in tests/e2e/skip_policy.py (policy test updated).
- Decision: Admin UI row action buttons share visible labels (Edit / disable, Revoke); each now has a row-specific aria-label that starts with the visible label (WCAG 2.5.3). A45 "keyboard trap" was a test defect: the trap detector compared labels, so adjacent identical-label row buttons looked like one element; it now compares DOM index and position.
- Decision: A38 expects the EntitySet count of the live Fake1C $metadata instead of a hard-coded 10 (the product lane extended Fake1C to 12).
- Evidence: unit/static tests for the 409 mapping and the aria-labels pass; the live admin rerun result is recorded below once executed.
- Evidence: admin suite live on candidate d493edb + these changes, two consecutive runs from a reset environment: 87 passed, 1 skipped (declared EXTERNAL-GATE), 0 failed (470 s and 465 s); engineering checkpoint re-pinned to implementation_sha256 3efb2f8f; document consistency PASS.

## 2026-10-07 - verify_admin_ui matches row-specific aria-labels

- Decision: scripts/verify_admin_ui.py located the 1C sources row action by the exact accessible name "Edit / disable"; after the row-specific aria-label change (WCAG 2.5.3) the accessible name is "Edit / disable <row>", so the browser contract check timed out. The script now matches the visible-label prefix and takes the first row button. No product behavior and no gate changed.
- Evidence: scripts/verify_admin_ui.py PASS locally; engineering checkpoint re-pinned to implementation_sha256 8e190e0f; document consistency PASS. The full matrix and live E2E are rerun on this exact code.

## 2026-10-07 - Release-candidate closing evidence on code 8283403

- Decision: closing documents record CODE_EVIDENCE_SHA `8283403` and local counts; hosted CI is PENDING in tracked files, and the exact final head SHA and hosted run ID go only into the PR #11 body/comment (no tracked commit after a green hosted run). Production deployment stays NO-GO; owner manual acceptance stays PENDING.
- Evidence: verification matrix 31/31 exit 0; pytest 1206 passed / 232 skipped; E2E smoke 16, User 52 (0 skipped), Admin 87 + 1 declared EXTERNAL-GATE skip; Functional Tester rerun at 8283403: 73 passed / 3 skipped / 2 xfailed (SC06 EXTERNAL-GATE, SC08 NOT IMPLEMENTED, needs operator rebaseline), Fake1C 14 GET + 1 HEAD, sidecar 57 read + 4 capabilities, no write verbs, audit/log scans clean. All synthetic L1; not native 1C.
- Refusal: no PRODUCTION GO claimed; SC08 not implemented because it is outside the scope freeze; no fake "create IdP user" feature.

## 2026-10-07 - Sprint-end local reviewer findings closed (security, silent-failure)

- Decision: two local sonnet reviewers (security-reviewer on the Admin mutation/UI diff, silent-failure-hunter on the Admin error paths and skip policy) found no BLOCKER; every closable finding was fixed inside the frozen scope, no migration, no new feature.
- Fixed: S1 a retried errored idempotency key now re-runs the egress/DNS/health preflight (only a 'success' row skips it); F7 non-string exception codes are sanitized in the HTTP mapper and the failure-row audit; F8 the Admin workflow dialog rotates its idempotency key when the payload changes (unchanged retry keeps the key) and shows the conflict remedy; F1/F2 the E2E skip policy can no longer be widened by environment (prefix-checked, blank entries ignored, cleared by test.ps1, effective allowlist printed, collection-time skips and a second allowlisted skip fail); F4 DB-backed test proves CapabilityUnsupported -> 409 + audit error + idempotency error + rollback + retry/conflict; A06 expectation tightened to a single outcome.
- Accepted as documented limitations (no change): F3 the declared A40 skip is a placeholder, the stale-on-drift behaviour is covered by the PG integration test only; F5 refusals raised before the idempotency reservation (payload validation, source preflight) are not audited by design; F6 capability.refresh writes capability evidence through a separate pool connection, so a failure after that write reports error while the evidence persists (pre-existing, not introduced by this sprint).
- Evidence: admin/refusal/skip-policy/PG test files green with ERP_MCP_REQUIRE_DB_TESTS=1; scripts/verify_admin_ui.py PASS. Full matrix, E2E and Functional Tester are rerun on the new code before the final push.

## 2026-10-07 - Final local evidence on code 0f0c031

- Decision: code evidence SHA is `0f0c031` (after the sprint-end reviewer fixes). Tracked closing documents record it with local counts; hosted CI stays PENDING there and the exact final head SHA and hosted run ID go only into the PR #11 body/comment.
- Evidence: verification matrix 31/31 exit 0; full pytest 1224 passed / 232 skipped; E2E smoke 29 passed (16 environment checks + 13 skip-policy tests that carry the e2e marker); User U01-U18 52 passed, 0 skipped; Admin A01-A54 87 passed + 1 declared EXTERNAL-GATE skip; Functional Tester 73 passed / 3 skipped / 2 xfailed / 0 failed, hygiene 4/4. Upstream traffic in the FT run: Fake1C 17 GET + 1 HEAD, sidecar 57 read + 5 capabilities, no write verbs; the small increase against the previous run is attributed (inference) to the 60 s metadata cache.
- All evidence is synthetic L1; nothing is native 1C or production evidence. Production deployment NO-GO.
