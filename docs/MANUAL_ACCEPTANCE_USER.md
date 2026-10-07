# Manual acceptance — SIMPLE USER (data-plane)

Version: draft for candidate `integration/1c-mvp-production-candidate`. Tested commit SHA: `____________`.
Derived from the frozen contract `docs/E2E_ACCEPTANCE_CONTRACT.md` (rows U01..U17 marked AUTO+MANUAL).
Synthetic Fake1C data only. Passing this suite is NOT native 1C reconciliation and NOT production approval.

You act ONLY as a data user. Never open `/admin/`, never use the Admin identities, never read the
Admin manual. The operator performs the "OPERATOR STEP" lines from the separate Admin identity.

## 0. Start the environment (one command)

```powershell
Set-Location D:\Repo\ERP_MCP-integration-candidate
powershell -File scripts\e2e\up.ps1 -Seed baseline
powershell -File scripts\e2e\status.ps1
```

Expected: `status.ps1` ends with every component `healthy` (PostgreSQL, Redis, Fake1C, test IdP,
gateway), schema version 14, exit code 0. If anything is not healthy: stop, do not test, copy the
status output into the evidence sheet.

To return to a clean state at any time: `powershell -File scripts\e2e\reset.ps1`.

## 1. Connect as a user

Your identities (passwords are generated per environment and stored in `.e2e\credentials.json` — open that file
locally; never paste it anywhere):

| Name | Purpose |
|---|---|
| `user_company_one` | normal user with access to Synthetic Company One |
| `user_company_two` | normal user with access to Synthetic Company Two (via group) |
| `user_no_access` | authenticated user with no grants |

Start the client:

```powershell
powershell -File scripts\e2e\open-user-client.ps1 -User user_company_one
```

It opens (or prints exact steps for) an MCP client against `http://127.0.0.1:18000/mcp`
using a token issued by the test IdP. Confirm the client lists the server tools before you start.
Use `-User user_company_two` / `-User user_no_access` where a case says so.

How to record: for each case fill the table row in section 3 (observed result, request/correlation id from the tool
response, notes) and tick exactly one box.

## 2. Cases

### Run order (important)

The baseline grants give `user_company_one` access to Synthetic Company One only. Tools that work on the
whole source (`source_health`, `onec_capabilities`, `onec_metadata_summary`, `onec_find_entities`,
`onec_read`) need a source-wide grant, which would also open company two. Therefore run in three parts:

- Part 1 (baseline grants only): U01, U05, U06, U07, U09, U10.
- Part 2: OPERATOR STEP S1 — the operator creates a temporary source-wide subject grant for
  `user_company_one` on `fake1c-e2e` in the Admin Control Center (Admin manual, case A27), then you run
  U02, U03, U04, U11, U12, U13, U14. Afterwards OPERATOR STEP S2 — the operator revokes that exact grant.
- Part 3: U17 (audit), after all calls above.

Business tools answer from a reviewed synthetic fixture profile: every business answer shows
`profile_kind = SYNTHETIC_FIXTURE`, `evidence_level = L1`, `native_reconciliation = NOT_RUN`. That is expected
and means "synthetic test data, not a real 1C reconciliation".

Legend: **Setup** = state before you act. **Do** = exact tool call. **Expect** = visible result.
**Forbidden** = if you see this, mark FAIL and stop that case. Evidence = what you write down.

### U01 — Identity
- Setup: environment healthy; client connected as `user_company_one`.
- Do: call `system_status` with no arguments.
- Expect: success; the response/audit identity is `user_company_one` (not any other name).
- Do (2): reconnect with `-User user_no_access` and call `system_status`.
- Expect (2): success identity is `user_no_access`, never `user_company_one`.
- Forbidden: any identity you did not log in as; a request accepted without a token.
- Evidence: correlation id for both calls. [ ] PASS  [ ] FAIL

### U02 — Discovery
- Setup: connected as `user_company_one`.
- Do: call `sources_list`, then `companies_list` with `source_id = fake1c-e2e`, then `source_health` with `source_id = fake1c-e2e`.
- Expect: source `fake1c-e2e` listed; Synthetic Company One listed; health is reachable/healthy.
- Forbidden: a password, token, secret name value, or a URL containing a user name.
- Evidence: correlation ids. [ ] PASS  [ ] FAIL

### U03 — Metadata discovery
- Setup: as U02.
- Do: call `onec_capabilities`, `onec_metadata_summary`, `onec_find_entities` (all with `source_id = fake1c-e2e`).
- Expect: only synthetic fixture entities appear (for example sales/receipt/payment style documents and counterparties).
- Forbidden: entity names that are not in the synthetic fixture.
- Evidence: correlation ids. [ ] PASS  [ ] FAIL

### U04 — Bounded raw read
- Setup: as U02.
- Do: `onec_read` on the sales document entity of the fixture, selecting only the four fields the tool help lists
  (reference, number, posted flag, amount), `top = 2`.
- Expect: at most 2 rows, only the four fields.
- Forbidden: other fields, more than 2 rows.
- Evidence: correlation id, row count. [ ] PASS  [ ] FAIL

### U05 — Own company
- Setup: connected as `user_company_one`.
- Do: call `sales_documents` with `source_id = fake1c-e2e` and company one's id `00000000-0000-0000-0000-000000000001`.
- Expect: the company-one sales documents (for example the posted sale and the unposted sale); every answer
  is labelled `SYNTHETIC_FIXTURE`; no document of company two.
- Forbidden: any row that belongs to company two.
- Evidence: correlation id. [ ] PASS  [ ] FAIL

### U06 — Company isolation
- Setup: connected as `user_company_one`.
- Do: repeat the U05 call with company two's id `00000000-0000-0000-0000-000000000002`.
- Expect: denied (access/company error), no rows.
- Do (2): reconnect as `user_company_two`, call with company two's id.
- Expect (2): data for company two.
- Forbidden: company two data returned to `user_company_one`.
- Evidence: correlation ids. [ ] PASS  [ ] FAIL

### U07 — No access
- Setup: connected as `user_no_access`.
- Do: call `sources_list`, `companies_list` (`fake1c-e2e`), `onec_read`.
- Expect: no sources/companies shown or a clear denied error for each; no data.
- Forbidden: any business data.
- Evidence: correlation ids. [ ] PASS  [ ] FAIL

### U09 — Revoke without restart
- Setup: `user_company_one` can read (U05 passed).
- OPERATOR STEP: the operator revokes the exact subject grant for `user_company_one` on `fake1c-e2e` in the Admin Control Center (they follow the Admin manual, case A31/A33).
- Do: repeat the U05 call (do not restart anything).
- Expect: denied immediately.
- Forbidden: data returned after revoke.
- Evidence: correlation id, time of revoke. [ ] PASS  [ ] FAIL

### U10 — Recovery
- OPERATOR STEP: the operator re-creates the grant.
- Do: repeat the U05 call.
- Expect: data returned again without any restart.
- Evidence: correlation id. [ ] PASS  [ ] FAIL

### U11 — Unsupported entity
- Setup: connected as `user_company_one`.
- Do: `onec_read` with entity name `Catalog_DoesNotExist`.
- Expect: clear "unsupported / not found" error; no data.
- Forbidden: the server "guessing" another entity and returning its rows; stack traces; internal URLs.
- Evidence: correlation id. [ ] PASS  [ ] FAIL

### U12 — Unsupported capability
- Setup: as above.
- Do: call a business tool that needs a capability not confirmed for this synthetic source (for example `inventory_movements` or `accounting_posting_rows` if the status shows it unconfirmed).
- Expect: "capability unsupported/not confirmed" style refusal.
- Forbidden: invented numbers.
- Evidence: correlation id, tool name. [ ] PASS  [ ] FAIL

### U13 — Limits
- Setup: as U04.
- Do: request `top = 100000` (or the maximum the client accepts).
- Expect: the response is capped to the documented limit and says so (truncation/limit notice).
- Forbidden: an unbounded or very large response.
- Evidence: correlation id, rows returned. [ ] PASS  [ ] FAIL

### U14 — Upstream outage and recovery
- Do: `powershell -File scripts\e2e\fault.ps1 -Component fake1c -Action stop`, then repeat U04.
- Expect: a short, sanitized "upstream unavailable" error (within about 30 seconds).
- Forbidden: the upstream address/credentials in the error; a hang.
- Do (2): `powershell -File scripts\e2e\fault.ps1 -Component fake1c -Action start`, repeat U04 without restarting the gateway.
- Expect (2): normal result again.
- Evidence: both correlation ids. [ ] PASS  [ ] FAIL

### U17 — Audit
- Setup: you have run at least one success (U05), one denial (U06 or U07) and one error (U11 or U14).
- OPERATOR STEP: the operator opens the audit view (Admin identity `auditor`, Admin manual A43) or runs `powershell -File scripts\e2e\status.ps1 -Json`-linked audit export as documented in `docs/E2E_ENVIRONMENT.md`.
- Expect: an event for each of your calls with caller, source, tool and outcome.
- Forbidden: tokens, passwords or business rows in any event.
- Evidence: event ids. [ ] PASS  [ ] FAIL

### U18 — Scenario checks SC01–SC12 (synthetic data; company one, April 2026)

Automated proof: `powershell -File scripts\e2e\test.ps1 -Suite user` (case U18 runs the independent functional
tester suite; attach its junit file `.e2e\evidence\...`). Hands-on spot checks (as `user_company_one` after
S1 where a source-wide tool is needed; timestamps must carry a timezone, for example `2026-04-30T00:00:00+00:00`):

| SC | Tool and arguments | Expected visible result | Forbidden |
|---|---|---|---|
| SC01 | `receivable_aging`, company one, `as_of` 2026-04-30T00:00:00+00:00 | counterparty `…0001`: overdue more than 30 days = 420 of open balance 500 | overdue larger than open balance |
| SC02 | same call, counterparty `…0004` | charged 1000, paid 250, open 750 | open balance not positive |
| SC03 | same call, counterparty `…0005` | open 0 and unapplied credit 125 shown separately | credit netted into open |
| SC04 | `sales_documents` then `accounting_posting_rows` (wide window) | the unposted sale has no posting rows; the posted sale has rows | postings for the unposted sale |
| SC05 | `inventory_movements` (April) and `inventory_balance` | item 002: +10, −3, balance 7; item 001: net 5, balance 5 | balance different from movements |
| SC06 | — | NOT AVAILABLE: VAT views exist only for a validated profile (external gate) | invented VAT numbers |
| SC07 | `accounting_posting_rows` for December 2025 | the backdated sale posts in 2025-12 and is absent from April | posting in the wrong period |
| SC08 | `counterparty_duplicate_candidates`, `source_id` of the Fake1C source, company one, `top` left at its default; then company two (`user_company_two`, own grant); then company one with `top` = 3 | company one: status `FINDING`, reason `DUPLICATE_CANDIDATES_FOUND`, `candidate_count` 2, `group_count` 1, `merge_count` 0, one group of exactly the two counterparties named `Synthetic customer` (codes `C001` and `C001D`, refs `…0001` and `…0003`); provenance `profile_kind` SYNTHETIC_FIXTURE, `evidence_level` L1, `native_reconciliation` NOT_RUN. Company two: status `PASS`, reason `NO_DUPLICATE_CANDIDATES`, zero groups. `top` = 3: status `INCONCLUSIVE`, reason `COUNTERPARTY_ROWS_TRUNCATED`, no groups (no partial result) | a merge or any change to the counterparties (the tool is read-only); company two seeing company one's pair; a partial FINDING under `top` = 3; SC08 shown as native 1C or production evidence (it is synthetic L1 only) |
| SC09 | `bank_balance` and `cash_movements` (2026-03-01 to 2026-05-01) | bank 250, cash 100, combined 350 shown separately | cash and bank mixed |
| SC10 | `accounting_balance_and_turnovers` (April, timezone-qualified) | opening 100 + debit 40 − credit 15 = closing 125 | naive timestamps accepted |
| SC11 | `inventory_movements` (April) | item 001: receipt 7, expense −2, net 5 | positive expense sign |
| SC12 | `cash_movements` (April) | receipt 10, expense −3, net 7 | positive expense sign |

Evidence: correlation ids. [ ] PASS  [ ] FAIL

## 3. Result sheet (copy and fill)

| Case | PASS/FAIL | Observed result | Correlation / request id | Notes |
|---|---|---|---|---|
| U01 | | | | |
| U02 | | | | |
| U03 | | | | |
| U04 | | | | |
| U05 | | | | |
| U06 | | | | |
| U07 | | | | |
| U09 | | | | |
| U10 | | | | |
| U11 | | | | |
| U12 | | | | |
| U13 | | | | |
| U14 | | | | |
| U17 | | | | |
| U18 (SC01–SC12) | | | | |

Attach: tested commit SHA, `status.ps1` output, date/time, your tester name. Redact tokens and passwords.

## 4. Stop conditions

Stop immediately and mark FAIL if: a call appears to change 1C data, you see another company's data,
you see a credential or token, or the environment touches anything other than the local disposable stack.

## 5. Teardown

```powershell
powershell -File scripts\e2e\down.ps1
```

Use `-Purge` to remove generated credentials and volumes completely.
