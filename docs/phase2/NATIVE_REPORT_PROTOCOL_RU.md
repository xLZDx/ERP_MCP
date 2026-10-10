# Phase 2 — Native 1C Report Capture and Reconciliation: Development / Production

**Version 0.1 · October 8, 2026 · DRAFT.** Covers requirements R2-REQ-13–21. This proposal does not change the current Release 1 runbook or authorize live production access or execution.

## 1. What Qualifies as Independent Evidence

A user can open the standard 1C application, generate a native report, save the original and compare it with MCP results. Qualified automation may perform those same steps through the standard UI or the same standard report object. The involvement of software **does not itself make the report synthetic**.

| Capture method | Potential Release 2 evidence eligibility |
| --- | --- |
| Standard UI report, manual | Native evidence candidate after verifying original bytes, parameters and completeness |
| Standard UI report, qualified automation | Potentially the same evidence authority, with additional recipe, runner and session provenance |
| Standard report object through qualified reporting engine/COM/batch | Candidate after comparison to UI output on the same configuration and approval of the procedure |
| Custom COM/OData query | Diagnostics; **not automatically** a standard native report |
| Synthetic/Ferma generator | Synthetic test oracle only; not real/production native evidence |
| XLSX derived from an MCP response or the same custom calculator | Not an independent oracle for validating the MCP result |

The current R1 policy accepts `NATIVE_UI_REPORT` for validation but does **not** accept `NATIVE_ENGINE_REPORT`. A new R2 policy requires a governed normative amendment and procedure qualification. Historical artifacts must not be relabeled retroactively.

**Numerical MATCH, provenance verification, accountant attestation and model acceptance are separate states.**

## 2. Environments

- **Synthetic CI:** Fixtures and mocks only; no claims of real/native accounting evidence.
- **DEV_REFERENCE:** Approved disposable copy, independent credentials/output namespace and development authorization.
- **STAGING:** Authorized reference copy, pinned identity/configuration and consistency verification.
- **PROD:** Capture capability may exist but must be **OFF by default**. Source/company/recipe-specific permission, execution window, expiry, resource budget and qualification on a safe copy are mandatory. Production identity is **not an administrator by default**.

In production, prohibit write probes, `reset.ps1`, arbitrary EPF/BSL, disabling safe mode and administrator fallback. In development, write probes or Ferma seeding are permitted only through a separately authorized disposable test harness, never through the capture recipe.

MFA requires an authorized human. An unavailable session produces `OPERATOR_ACTION_REQUIRED`.

## 3. Native Report Recipe

A recipe must bind:
- Source, configuration and platform fingerprints.
- Exact standard report object and variant hash.
- Environment and execution mode.
- Executor, selectors and processing digest.
- Schema of permitted typed parameters.
- Output format and private destination.
- Required permission set.
- Timeouts, resources and approved technical side effects.
- Qualification reference and version.

Job input includes `source_id`, `company_id`, `recipe_id`/version/hash, `authorization_id`, `scope_epoch`, `idempotency_key`, and typed parameters.

**Forbidden:** `command`, `executable`, `sql`, `bsl`, `arbitrary_url`, `connection_string`, `password`, `token`, `epf_bytes`, `force_validate`. Resolve secrets only through the server-side provider.

Parameters include account, `start_local`, `end_local_exclusive`, verified time zone, grouping, `expanded_balance`, currency basis, posted/deleted filters, and source snapshot/cutoff. The adapter must prove how wire-level periods map to native UI parameters. Never replace arbitrary boundaries with `23:59:59Z`.

## 4. Manual Baseline for Account 521.1 Trial Balance

1. Open the approved 1C source/copy through the standard client. Verify infobase identity, company, and currency/data freshness.
2. Select the standard trial balance for the account. An alternative report is acceptable only as an explicitly approved equivalent procedure.
3. Set company **818 HA SRL**, account **521.1**, and the period **August 1–31, 2026**, inclusive in the database's local time. Canonical interval: `[2026-08-01 00:00, 2026-09-01 00:00)`. Confirm the database time zone independently; do not infer it from the user's location.
4. Use counterparty → contract grouping and expanded balances. Required columns: opening debit/credit, turnover debit/credit, and closing debit/credit. Record currency, units and every active filter.
5. Wait until generation completes and verify no hidden row limit. Save the original XLSX/MXL and, if needed, PDF or screenshots of headers/settings. Do not edit values in Excel. A screenshot of only part of the table is **not** complete evidence.
6. Ingest the original bytes, hash and manifest into the private evidence store as `UNATTESTED`. A Drive location does **not** establish native origin.
7. Compare with MCP using the **same snapshot, cutoff and parameters**, checking all six values and **every row**. Scope, currency or coverage mismatches must never receive PASS.
8. An independent accountant approves or rejects the attestation. A separate model approver binds usable mappings to the verified evidence coverage. One matching case does not validate the whole system.

Financial values supplied in conversation remain `USER_SUPPLIED_NOT_ATTESTED`. Different opening balances and turnovers can produce an equal closing net amount; comparing only the final number is prohibited. A private arithmetic note may accompany the user's personal files but must not be inserted into Git fixtures.

## 5. Standard UI Automation

Required sequence:

1. Verify application process and identity.
2. Verify exact infobase and company.
3. Open the standard report.
4. Set and read back every required parameter.
5. Generate and wait for completion.
6. Verify headers, six columns and completeness.
7. Export the original report.
8. Hash and ingest the original bytes.
9. Safely close **only the owned report or session**.

Unknown dialogs/selectors, wrong database, or configuration mismatch cause denial. Never guess clicks on a similar-looking production form.

The existence of DC_MCP file operations is **not evidence of an available UI executor**. A separate feasibility spike must identify a real supported UI automation interface and its permissions; otherwise fall back to manual baseline capture.

Qualification requires manual and automated UI reports on the same stable database copy/configuration, identical report object, variant, parameters, columns, totals and rows, plus evidence of read-only rights and approved technical effects. Requalify affected procedures after configuration, UI or recipe changes.

## 6. COM, Standard Engine and Batch Execution

An engine recipe must invoke the **standard report object**, not a custom query recreated from its business logic. Existing runbooks identify UI-dependent trial balances and account cards: empty output through an external connection means `CAPTURE_UNSUPPORTED` or `INCOMPLETE`, **not zero**. A transition to the UI procedure is permitted only if separately approved and with new provenance, never by disguising a custom query as native evidence.

`/Execute` is an optional mechanism for launching a **previously reviewed, pinned processing artifact**. It requires source-specific authorization, fixed digest/signature, allowlisted path/parameters and side-effect evaluation. No arbitrary EPF supplied through an AI request; no disabling protections or elevated identity.

A wrapper may control parameters and export. It must not compute expected totals using the same proprietary algorithm being validated. Reading from the same underlying source may be appropriate; using the same internally computed result on both sides is **not independent verification**.

## 7. Preflight and Authorization

A permit binds actor, source, company, environment, procedure, hash, execution modes, time window, expiry, maximum runs, budget, output classification and approver.

Before dispatch, validate:
- Current grant, epoch and revocation.
- Matching source configuration and qualified recipe.
- Ownership of the worker/runtime.
- Availability of secret references **without echoing values**.
- Source readiness and maintenance window.
- Physical-backend lease and capacity budget.
- Mandatory `audit START` event.

Do not stop a running gateway because a requested job or replacement worker is unavailable. Report jobs must not restart the gateway, IdP or 1C. Cancel affects **only the owned job**, with PID, process-start-time and foreign-process guards.

Child processes must not inherit unrelated Gmail, API or SSH credentials. Never probe for secrets through unrelated pytest helpers.

## 8. Side Effects and Source Consistency

Standard reports execute code from the specific 1C configuration. Calling an account a reader does **not** prove that no settings or service logs are written. Business-write permissions for documents and accounting postings must be denied. Technical writes require explicit classification and evidence coverage.

Do not claim that the production database is byte-identical before and after report generation: service metadata may legitimately change.

Development qualification should use a stable disposable copy. Production requires a proven snapshot, cutoff, and source version, or an approved read window and before/after source markers.

The **same reporting date** does not prove that no backdated posting occurred between the native report and MCP reads. If source consistency is unproven, return `INCONCLUSIVE SOURCE_CHANGED_OR_UNPROVEN`.

No-business-write qualification combines rights, a fixed contract, a reviewed recipe and observation of relevant data objects with explicit coverage. A production write probe is never acceptable. When technical effects are unverified, automated production capture must be denied; an authorized person may instead use manual export or an approved safe copy.

## 9. Trust, Comparison and Applicability States

**Artifact trust:** `UNATTESTED`, `ORIGIN_VERIFIED`, `ATTESTED`, `REVOKED`.

**Comparison result:** `MATCH`, `MISMATCH`, `INCONCLUSIVE`, `ERROR`, `NOT_RUN`.

**Applicability:** `CURRENT`, `SUPERSEDED`, `EXPIRED`, `SCOPE_MISMATCH`, `POLICY_STALE`.

**Evidence authority:** `SYNTHETIC`, `DEV_REFERENCE`, `STAGING`, `PROD_QUALIFIED`.

A hash only proves byte equality with a reference. A signature without trustworthy signer, key and actor management does not establish truth.

Actual artifact bytes and attestation must be linked by foreign keys to an immutable revision, exact scope, model and policy. An uploader or connector cannot set `VALIDATED`.

A new revision ends applicability to the latest data, but historical PASS on the original bytes is preserved. Forged evidence or revoked signer authority generates a distinct revocation event.

## 10. Bootstrap Candidate Mapping

Public business tools remain disabled until their mapping is validated.

To break a circular dependency, a **separate private evaluation runner** may execute a pinned candidate mapping on an approved copy through an existing read-only adapter. Its output is `EVALUATION_ONLY`, **not** a native oracle or public semantic-gate bypass.

The native export comes independently from the standard reporting route. Only after comparison and approval may the resulting mapping become an accepted binding, followed by a canonical MCP replay.

## 11. Twelve Additional Qualification Cases

These Release 2 cases supplement, but do not replace, existing Release 1 `NR-01` through `NR-10`. The presence of any ten files is not proof of sufficient independent accounting coverage.

| Case | Required qualification |
| --- | --- |
| R2-NR-01 | Account 521.1 August trial balance, all six totals |
| R2-NR-02 | Counterparty trial balance, completeness and aggregates |
| R2-NR-03 | Counterparty/contract trial balance with expanded debit and credit, no hidden netting |
| R2-NR-04 | Account 521.1 card with each posting, document, date and corresponding account |
| R2-NR-05 | July and July 31/August 1 boundary, opening continuity |
| R2-NR-06 | Native posted-purchases journal for MOLDRETAIL |
| R2-NR-07 | Unposted/deleted negative corpus on a development copy, without creating production documents |
| R2-NR-08 | Debit and credit on distinct contracts of the same supplier |
| R2-NR-09 | Currency/units mismatch yields scope refusal |
| R2-NR-10 | Backdated correction in a separate test corpus creates a new current run and historical record |
| R2-NR-11 | Manual UI compared with qualified UI automation |
| R2-NR-12 | Manual UI compared with a qualified standard engine where supported; otherwise `UNSUPPORTED` |

## 12. Financial Comparison Rules

`net_liability = credit - debit`.

`closing_net = opening_net + credit_turnover - debit_turnover` is an **additional consistency check**, not a replacement for direct comparison of expanded native debit and credit balances.

Comparison key: `tenant / company / account / counterparty_ref / contract / currency_basis / report_grain`. Inferred name aliases require evidence.

Verify scope, precision, cutoff and completeness **before** arithmetic. Use Decimal, an approved tolerance/rounding policy, and signed differences. Binary float comparison or adjusting values merely to match final totals is prohibited.

Accounting-based balances do **not** establish aging or due dates. For 818HA, an absent settlement register must be handled through a separate explicitly qualified ledger strategy, not by filling in plausible register names. Posted purchases require their own original native journal contract.

## 13. Production Delivery Boundary

The product may include safe API, queue and executor contracts and a manual intake flow. **Automatic production capture remains OFF** until a source-specific recipe is qualified and permitted.

There is no debug bypass, headless password grant, or temporary disabling of semantic checks. An expired grant or recipe returns a safe reason for denial, while preserving authorized history according to policy.

**This is a design protocol. It is not evidence that native production capture has been authorized or executed.**
