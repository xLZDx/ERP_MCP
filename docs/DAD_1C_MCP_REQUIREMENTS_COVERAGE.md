# DAD 1C MCP — Source Requirements & Scenario Coverage

**Status:** REVIEWED SOURCE-OF-PROBLEM + IMPLEMENTATION/TEST COVERAGE
**Revision:** 2 — consolidated after real-reference/Ferma/legacy/testbed review
**Date:** 2026-10-06
**Primary source:** Google Doc `Istoric si context 1C MCP (PLUGIN)`
**Private source:** verified through the connected Google Drive account; exact private Drive IDs/URLs are intentionally not stored in this public-repo document.
**Purpose:** ensure ERP_MCP architecture and roadmap preserve every business scenario evidenced by the DAD materials without weakening the final read-only MVP boundary.

> Security note: the source history contains a plaintext credential for the **dedicated test copy**
> of 1C. It is intentionally NOT reproduced here and MUST NOT be copied into Git, prompts, reports,
> process arguments or model-visible output. Because the credential is test-only, its presence does
> not imply a production-secret incident; nevertheless it should be referenced in ERP_MCP only via
> a local/test `secret_ref`, should not be reused elsewhere, and should be rotated if the test base is
> ever repurposed or exposed beyond the intended test environment.

---

## 1. Executive conclusion

The current ERP_MCP architecture strongly covers the **final/current DAD priority**:

- Claude/AI reads 1C only;
- one AI principal can access 30–150 companies/sources;
- grants change frequently;
- add/revoke must not require deployment/restart;
- exact company isolation is mandatory;
- access and semantic changes must be auditable;
- wrong/stale source interpretation must be diagnosable and revalidated.

The current implementation does **not** yet implement every original accounting scenario.

That is acceptable only if the uncovered scenarios are explicitly preserved in the roadmap. This
review therefore introduces two missing architectural concepts:

1. **DAD Month-Close Rule Packs** — configuration/company-aware, versioned accounting review rules.
2. **External Evidence Plane** — read-only evidence inputs outside 1C (bank statements, Z reports,
   terminal reports, tax declarations/receipts, customs reconciliation acts, e-invoices, payroll
   source documents, contracts and other primary documents).

The production 1C gateway remains read-only.

Write automation evidenced in the historical pilot (invoice creation/editing, payments, cash-register
import) is explicitly a **future write plane** and must not leak into the read-only MVP.

The supplied real 1C test-copy artifact, referred to here as `REFERENCE_TEST_BASE_A`, is now
designated as the **real-reference 1C testbed** for ERP_MCP. It complements, rather than replaces,
the Ferma synthetic/oracle testbed. The project will use both: the private reference base for real
configuration/data/known-error regression and Ferma for controlled coverage, scale, multi-company
isolation and scenarios absent from the reference corpus.

---

## 2. Source/link audit

All primary Google Drive links embedded in the source document were resolved through the connected
Drive account.

| Source | Drive ID / URL class | Result | Relevance |
|---|---|---|---|
| Main history/context | private native Google Doc | PASS | final product priority and chronology |
| Initial task list | private DOCX | PASS | 8 read/analysis tasks + 2 future write tasks |
| Pilot questions | private PDF | PASS | month-close process + environment/onboarding questions |
| 1C base copy | private ZIP, ~2.66 GB | PASS metadata/access | **designated real-reference testbed**; must be hashed, archived immutable and restored only to disposable clones before use |
| Month-close workbook | private XLSX | PASS/read | detailed account-by-account review procedure |
| Accountant screenshot | private image | PASS/read | scope correction + six “small-step” checks |
| Month-close review report | private PDF | PASS/read | shows what could/could not be inferred from 1C-only data |
| E-invoice folder | private folder | PASS | contains 21 invoice PDFs; folder-label mismatch noted privately |
| Invoice reconciliation report | private PDF | PASS/read | concrete mismatch classes and missing-evidence classes |
| 1C write verification report | private PDF | PASS/read | historical R/W pilot evidence; not current MVP scope |
| Invoice API statistics | private PDF | PASS/read | 19 pre-existing + 2 API-created = 21 documents |
| All-materials folder | private folder | PASS | coherent bundle of the above source materials |
| Diadoc example | `https://www.diadoc.ru/order1c` | PASS with anti-bot caveat | current reference page exists; direct automated open returns 403 but current crawl confirms content |

Folder consistency check:

- the e-invoice folder contains **21 PDFs**;
- all 21 invoice IDs used in the invoice reconciliation register exist in that folder;
- the reconciliation report also names seven additional primary documents that were missing from
  the supplied invoice archive; those are findings, not missing folder files.

Minor hygiene issue:

- privately rename the invoice folder to a neutral/date-based name or otherwise correct its count label to avoid confusion; do not expose the private folder name in public-repo documentation.

---

## 3. Source-priority interpretation

The source chronology changes product priority over time.

### Historical requests

The original list contains broad accounting automation, tax/payroll checks and future write
automation.

### Final/current requirement in the source

The final explicit priority is:

1. connect Claude/AI to many 1C sources;
2. **read-only only**;
3. 30–150 companies per AI principal;
4. frequently add/revoke access;
5. allow an internal operator/admin to manage this without developer intervention;
6. refresh/repair a source/profile when AI reads it incorrectly.

Therefore:

- current MVP MUST remain read-only;
- original business scenarios are preserved as semantic/evidence roadmap requirements;
- historical invoice/payment/cash writes are deferred, not silently discarded.

---

## 4. Current ERP_MCP semantic surface

Current candidate implements or has tests for:

- `sources_list`
- `companies_list`
- source health/capabilities/metadata discovery
- metadata search
- RSV metadata-only fallback
- `accounting_balance_and_turnovers`
- `accounting_posting_rows`
- `inventory_balance`
- `inventory_movements`
- `cash_movements`
- `bank_balance`
- `receivable_balance`
- `payable_balance`
- `sales_documents`
- `purchase_documents`
- bounded generic `onec_read` behind capability/policy gates
- a synthetic AR/AP aging computation contract not yet wired to real source profiles

This is a strong primitive layer, but it is not yet the DAD business-rule layer.

---

## 5. Final access/control-plane requirements

| ID | Requirement | Current status | Target |
|---|---|---|---|
| DAD-ACC-01 | read-only production 1C access | IMPLEMENTED/PARTIAL evidence | structural read-only + real target zero-write proof |
| DAD-ACC-02 | 30–150 companies/sources visible to one AI principal | IMPLEMENTED synthetic | retain 30/50/100/150 evidence; add heterogeneous live pilot |
| DAD-ACC-03 | add source/grant without restart/deploy | IMPLEMENTED | production operator evidence |
| DAD-ACC-04 | revoke immediately without restart | IMPLEMENTED | production operator evidence |
| DAD-ACC-05 | exact company isolation | IMPLEMENTED synthetic/PARTIAL live | real multi-company source evidence |
| DAD-ACC-06 | self-service access administration | PARTIAL | admin CLI exists; define operator role/workflow, optional UI |
| DAD-ACC-07 | 3–8 new clients/month onboarding | PARTIAL | onboarding runbook + source/profile template |
| DAD-ACC-08 | repair source when AI reads incorrectly | PARTIAL | capability refresh + metadata drift + mapping/profile revalidation runbook |
| DAD-ACC-09 | audit who accessed which company/source | IMPLEMENTED/PARTIAL deployment | deployed audit review |
| DAD-ACC-10 | source != company | IMPLEMENTED architecture | keep invariant |

---

## 6. Environment/onboarding requirements from pilot questions

The pilot questionnaire requires more than a URL and credential.

| ID | Evidence to capture | Current status |
|---|---|---|
| DAD-ENV-01 | 1C platform version | PARTIAL/live capability/testbed |
| DAD-ENV-02 | configuration name/version | PARTIAL; profile metadata should own it |
| DAD-ENV-03 | installed extensions/plugins | PARTIAL; RSV config can list extensions; OData path needs operator inventory when unavailable |
| DAD-ENV-04 | operating system/version | NOT MODEL-DISCOVERED; operator/deployment inventory |
| DAD-ENV-05 | DBMS/version | NOT MODEL-DISCOVERED; operator/deployment inventory |
| DAD-ENV-06 | license type/external-connection restrictions | PARTIAL; operator attestation + deployment test |
| DAD-ENV-07 | connection method/topology | PARTIAL; source registry |
| DAD-ENV-08 | known correctly closed period | NOT YET; L2/L3 reconciliation fixture |
| DAD-ENV-09 | known-error period | NOT YET; L2/L3 negative golden fixture |
| DAD-ENV-10 | test copy/read-only account | local synthetic PASS; target evidence pending |

Add a versioned `source_environment_inventory` evidence object to onboarding rather than attempting to
infer OS/DBMS/license from accounting data.

---

## 7. Original DAD business tasks

| ID | Scenario | Current implementation coverage | Required completion |
|---|---|---|---|
| DAD-BIZ-01 | month-close analysis with actionable accounting/tax findings | PARTIAL primitives only | DAD rule-pack engine + external evidence + native reconciliation |
| DAD-BIZ-02 | quick client answers: VAT, liabilities, receivables, reconciliation status | PARTIAL | basic balances yes; tax/reconciliation-specific semantics missing |
| DAD-BIZ-03 | P&L / Cash Flow / Balance Sheet | NOT dedicated | validated financial-statement semantic profiles + native report reconciliation |
| DAD-BIZ-04 | pre-check VAT/IPC/VEN filings and detect unclosed/risky companies | NOT IMPLEMENTED | tax evidence adapter + versioned tax rule packs + human review |
| DAD-BIZ-05 | bank balance and bank-entry correctness | PARTIAL | `bank_balance` exists; external statement reconciliation + posting-rule checks missing |
| DAD-BIZ-06 | customs reconciliation act vs 1C | NOT IMPLEMENTED | external customs/SFS evidence + matching/reconciliation |
| DAD-BIZ-07 | payroll calculation correctness | NOT IMPLEMENTED | payroll source documents + validated payroll rules + human review |
| DAD-BIZ-08 | generate/send/receive reconciliation acts and reconcile | PARTIAL read | balances exist; document generation/delivery/intake workflow missing |
| DAD-WRITE-01 | create payments in 1C / prepare bank submission | DEFERRED WRITE | separate approved write plane after read-only MVP |
| DAD-WRITE-02 | import SFS cash-register data and post to 1C | DEFERRED WRITE | separate approved write plane |
| DAD-WRITE-03 | ingest invoices and create/edit purchases in 1C | DEFERRED WRITE | historical pilot proved feasibility; must not enter current read-only gateway |

---

## 8. Six accountant-selected “small-step” checks

The screenshot is important because it narrows the broad “close the month” idea into testable
read-only checks.

| ID | Check | Coverage | Required semantic/rule |
|---|---|---|---|
| DAD-SMALL-01 | account 211 final negatives by quantity or value | PARTIAL: internal engine; native OPEN | inventory/account rule: negative ending position |
| DAD-SMALL-02 | 211/217 positions with no movement during month | PARTIAL: internal engine; native OPEN | stale/no-movement inventory rule |
| DAD-SMALL-03 | counterparties with simultaneous/“regraded” 221/523 and 224/521 balances | PARTIAL: internal engine; native OPEN | analytic cross-account exclusivity rule |
| DAD-SMALL-04 | days when account 241 becomes negative | PARTIAL: internal engine; native OPEN | daily rolling cash balance by cashier/subdivision |
| DAD-SMALL-05 | Z-report balance/turnover vs 1C | PARTIAL: normalized engine; native/evidence OPEN | external Z-report evidence reconciliation |
| DAD-SMALL-06 | terminal report vs 1C, enumerate mismatches | PARTIAL: normalized engine; native/evidence OPEN | external terminal evidence reconciliation |

These six should become the first DAD rule-pack acceptance cases because they are small, concrete,
read-only and accountant-selected.

### 8.1 Current internal normalized acceptance engine

`dad_small_checks.py` implements the four named arithmetic checks and binds DAD-SMALL-05/06 to
the existing bounded external evidence comparator. This is an internal evaluation contract, not
a public tool or proof of live/native acceptance. The coverage table above remains PARTIAL/not
native-implemented until actual source collection, registry approval and native cases execute.

Every small-check profile is versioned and fingerprinted with exact source/company/configuration,
semantic profile, live metadata hash, selectors, ordered dimensions, period, currency/timezone,
effective dates, native-report mapping and explicit quantity/value tolerances. Approval comes from
server-side configuration; an unconfirmed profile returns `CAPABILITY_UNSUPPORTED`. There are no
global account 211/217/221/523/224/521/544/241 defaults or guessed alternate virtual-table names.

- 01 checks negative final quantity OR signed value at the approved item grain.
- 02 checks a nonzero position with zero gross movement, not zero net debit/credit turnover.
- 03 requires counterparty/contract/document grain, scoped currency, and exact approved account
  pairs. It never falls back to counterparty-only aggregate exclusivity.
- 04 requires every business day for each observed cash analytic, opening/closing continuity and
  receipt/payment arithmetic. A missing day is INCONCLUSIVE, not assumed zero activity. Findings
  enumerate business dates; analytic keys are hashed. These dated results remain private evidence.
- 05/06 preserve `EVIDENCE_REQUIRED` without matching Z/terminal inputs and enumerate existing
  normalized comparator findings without fetching URLs or creating another native-format parser.

Truncated, stale, cross-company, duplicate, nonfinite, inconsistent or wrong-grain observations
cannot PASS. Inputs are bounded to 2000 normalized rows and a 366-day window. Results retain their
original evidence level and always require human review; no L2/native approval is inferred.
Live source collectors, runtime ACL/audit tool exposure, validated source profiles and native
acceptance remain locally/open or operator-evidence work, not closed by these fixture tests.

---

## 9. Month-close workbook coverage

The workbook contains 203 indexed rows. The account-rule table begins around row 22 and continues
through account/cost rows near 194, followed by required document/archive tasks through row 202.

The correct implementation is NOT 180 hard-coded `if account == ...` branches in gateway code.

Use a versioned rule pack:

```text
rule_pack = DAD_MD_MONTH_CLOSE_V1
  rule_id
  source semantic concept
  account/dimension selector
  period/window
  comparison/condition
  required external evidence
  severity
  explanation
  remediation guidance
  legal/policy source version
  native-report evidence mapping
```

### 9.1 Rule families evidenced by workbook

| Family | Examples from workbook | Current coverage |
|---|---|---|
| Intangible/fixed assets | in-service state, useful life, depreciation pairing, cadastral/acceptance documents | NOT IMPLEMENTED as rules |
| Depreciation | monthly correctness, start date, cap at original value, correct correspondent expense account | NOT IMPLEMENTED |
| Construction/WIP/fixed-asset capitalization | transfer 121→123, completeness of cost basis | NOT IMPLEMENTED |
| Inventory/materials | negative qty/value, slow-moving stock, consumption norms | PARTIAL primitives |
| Low-value assets | in-service rules, value thresholds, wear correlation | NOT IMPLEMENTED |
| WIP/finished goods/goods | slow-moving, negative balances, amount-vs-quantity asymmetry, correct cost account | PARTIAL primitives |
| AR/customer advances | 221↔523 exclusivity, slow-moving, negatives, e-invoice completeness, FX revaluation | PARTIAL balances only |
| AP/vendor advances | 224↔521/544 exclusivity, monthly supplier completeness, negatives, FX | PARTIAL balances only |
| Tax receivables/liabilities | 225↔534, CCAC, VAT advance formulas, 533/534 reporting/calculation checks | NOT IMPLEMENTED |
| Cash | no negative balance, cashier/subdivision analytics, MCC reconciliation, legal cash limits | PARTIAL 1C-only |
| Bank/card | bank-client statement match, bank analytics, BNM FX conversion | PARTIAL 1C-only |
| Terminal/transit cash | account 245 should close; terminal report reconciliation | NOT IMPLEMENTED |
| Capital/equity | statutory capital vs ASP, reserves vs charter/minutes, prior-period correction evidence | NOT IMPLEMENTED |
| Profit/loss closing | prior-year statements, reforming balance, no residual where prohibited | NOT IMPLEMENTED |
| Loans/leasing | contracts, maturity classification, FX, reconciliation acts | NOT IMPLEMENTED |
| Payroll | withholding, negative employee balance, sick leave, bonuses, vacation | NOT IMPLEMENTED |
| Expense advances | >30-day outstanding, supporting receipts | NOT IMPLEMENTED |
| Tax/social/medical obligations | monthly/periodic reporting, CCAC matching, tax tables | NOT IMPLEMENTED |
| Revenue classification | correct account/analytics/VAT | PARTIAL posting primitive only |
| Expense classification | correct account/analytics/nomenclature group, payroll placement | PARTIAL posting primitive only |
| Production costs | 811/821 should close as defined, allocation completeness | PARTIAL posting/turnover primitives |
| Required archive evidence | policies, inventory acts, IPC/TVA tables, payroll docs, expense reports | NOT IMPLEMENTED |

### 9.2 Critical lesson from accountant feedback

The workbook is company/activity specific.

Therefore a rule must have applicability predicates:

- configuration/profile;
- company/activity;
- account/subaccount use;
- legal/tax regime;
- currency;
- required evidence availability;
- effective date/version.

Do not globally assert that every company must use/close the same account in the same way.

---

## 10. Month-close report findings → required scenarios

The generated August review demonstrates why reconstructed postings alone are insufficient.

Required acceptance scenarios:

- DAD-MC-001: 811/821 debit activity with missing/incorrect allocation;
- DAD-MC-002: negative finished-production balance;
- DAD-MC-003: cost-of-sales/revenue relationship requiring native context;
- DAD-MC-004: closing document exists but does not prove the entire month is closed;
- DAD-MC-005: account 211 negative-position detection;
- DAD-MC-006: account 211 no-movement/slow-moving positions;
- DAD-MC-007: absence of 217 extracted rows must not be interpreted as zero balance;
- DAD-MC-008: daily 241 cash balance, preferably by cashier;
- DAD-MC-009: 221/523, 224/521, 224/544 checks at contract/document/currency analytics, not only counterparty aggregate;
- DAD-MC-010: tax filing checks require submitted declarations/receipts;
- DAD-MC-011: bank/Z/terminal checks require external evidence;
- DAD-MC-012: depreciation/payroll checks require supporting data;
- DAD-MC-013: “month closed” requires source-native evidence and accountant-approved definition;
- DAD-MC-014: reconstructed cumulative history with unknown opening balances must be labelled inconclusive, not treated as native balance;
- DAD-MC-015: debit==credit equality is not by itself accounting correctness.

Current P4/P5 must add these as explicit negative/INCONCLUSIVE cases.

---

## 11. Invoice/e-factura scenario coverage

The linked invoice folder contains 21 PDFs. The reconciliation report evidences the following
distinct scenarios.

| ID | Scenario | Current coverage |
|---|---|---|
| DAD-INV-01 | payment exists but purchase/receipt is missing | PARTIAL: normalized correlation rule; live/native OPEN |
| DAD-INV-02 | one PDF has two qualities/items but 1C collapsed them into one line | PARTIAL: normalized quality/line comparison; native extraction OPEN |
| DAD-INV-03 | supplier/company ID differs between PDF and 1C master data | PARTIAL: scoped identity comparison; live/native OPEN |
| DAD-INV-04 | wrong product mapping / two product types represented as one item | PARTIAL: exact approved item mapping; live/native OPEN |
| DAD-INV-05 | invoice date and 1C registration period differ; VAT deduction period requires review | PARTIAL: period human-review finding; no legal tax approval |
| DAD-INV-06 | service covers multiple periods; accrual/period allocation required | PARTIAL: scoped allocation-review rule; native proof OPEN |
| DAD-INV-07 | production overhead account 821 remains unresolved after invoice review | PARTIAL: profile-only overhead rule; native proof OPEN |
| DAD-INV-08 | 1C receipt exists but primary document is absent from archive | PARTIAL: exact archive-proof contract; original verification OPEN |
| DAD-INV-09 | amount/VAT exact match across invoice vs 1C | PARTIAL: normalized totals comparison; native/public delivery OPEN |
| DAD-INV-10 | line-level quantity/price/amount/VAT comparison | PARTIAL: normalized line comparison; native/public delivery OPEN |
| DAD-INV-11 | 1-cent line VAT differences but correct invoice VAT total | PARTIAL: explicit versioned exact-header tolerance; native acceptance OPEN |

Read-only MVP may support these comparisons without writing to 1C if invoice/evidence files are
provided through the evidence plane.

### Historical write pilot

Current normalized intake now supports an explicitly approved INVOICE-only JSON codec containing
the complete quantity/price/VAT/item/quality/header facts in §11. Private storage/operator intake/
index/manifest route support its exact MIME/profile; no content sniffing, class relabelling or raw
identity/value exposure. Duplicate/extra/schema/precision/scope inputs fail closed. Carrier SHA is
not an original PDF fingerprint; extraction never fixes invoice arithmetic or approves tax law.
Structured input was implemented before the internal rule pack below. Native PDF/XML extraction,
original archive, live source collectors and real REAL-INV-001..011 corpus acceptance remain OPEN.

`invoice_rules.py` now implements an INTERNAL versioned normalized comparison pack for all eleven
logical cases. Synthetic acceptance fixtures use the frozen REAL-INV-001..011 IDs but are NOT the
private real corpus. Scope/metadata/item/buyer/native-report mapping and amount encoding are exact
profile-bound; missing/stale/unapproved/cross-company/incomplete or same-plane facts cannot PASS.
Private identities/values are not emitted in findings. Original archive proof binds exact scope,
invoice/supplier identity and verified private blob digest; a normalized carrier/source-result
digest cannot be relabelled as the original PDF. Without confirmed archive proof the receipt case
is `EVIDENCE_REQUIRED`, including when normalized JSON exists.

Invoice fact snapshots are separately fingerprinted so detached/altered parsed header/lines fail
before comparison. Missing receipt never manufactures ten other PASS results; service/overhead
checks carry explicit applicability. There is no global 821 or legal VAT-period conclusion.
Registration/service periods produce human-review findings, not a tax deductibility decision.
Quantity/price/discount/net/VAT/total comparisons use explicit versioned tolerances. Line VAT
rounding is allowed ONLY by profile and when all invoice header totals match EXACTLY; it cannot
waive a total mismatch. Mathematical line/header inconsistencies remain findings, not corrections.
All results preserve the supplied evidence level and deny native/legal approval inference.

Internal logical rules are implemented; public invoice tool/live source collection, verified raw
archive/native PDF/XML extraction, approved real profiles and private real-corpus/native acceptance
remain OPEN. The table above describes native/business-delivery gaps, not a full engineering GO.

The source also proves historical test capability to:

- create/edit a purchase document;
- write item lines;
- persist quantity/price/amount/VAT;
- re-open and read values;
- create two previously missing invoices through an API path.

This is useful evidence for a future write product, but the final requirement explicitly returned
to read-only. Do not re-enable write operations in current ERP_MCP.

Future write acceptance must additionally prove:

- idempotency/no duplicates;
- transaction/rollback behavior;
- posting vs saving distinction;
- approval;
- source/company authorization;
- exact audit;
- safe re-read;
- no generic arbitrary mutation.

---

## 12. External Evidence Plane — missing architecture now added to roadmap

Many DAD checks compare 1C to something outside 1C.

Required evidence classes include:

- bank statements / bank-client exports;
- Z reports;
- payment-terminal reports;
- MCC cash-register data;
- CCAC taxpayer account;
- customs reconciliation acts;
- VAT / IPC / VEN declarations and receipts;
- e-factura / invoice PDFs;
- payroll time sheets, payroll registers, sick-leave/bonus/vacation source docs;
- contracts;
- cadastral extracts;
- corporate minutes;
- reconciliation acts;
- inventory/commissioning/write-off acts.

Proposed boundary:

```text
External Evidence
 uploads / approved connectors / SFS-bank exports
             |
             v
 Evidence Ingest / Parser
  fingerprint + provenance
  no model-supplied arbitrary URL
             |
             v
 Evidence Normalizer
             |
             +----------------------+
             |                      |
             v                      v
        DAD Rule Engine        Reconciliation Engine
             |                      |
             +----------+-----------+
                        |
                        v
                  ERP_MCP result
                  + evidence refs
```

Rules:

- external evidence is read-only input;
- source and document fingerprint required;
- do not silently retain raw customer documents beyond approved retention;
- never let evidence values contaminate the independent expected/oracle path in L2;
- missing evidence yields `INCONCLUSIVE/EVIDENCE_REQUIRED`, not a guessed PASS/FAIL.

### 12.1 Internal private normalized evidence provider

`evidence_store.py` adds an append-only local provider for the existing approved normalized CSV
contract across the 14 frozen evidence classes. It does NOT parse native PDF/XML/bank/payroll
formats, infer their schema, accept arbitrary URLs or decompress uploads. Only `text/csv` with
identity encoding is accepted; existing 4 MB/2000-fact parser, exact digest/profile/scope and
approved retention policy checks run before raw bytes are persisted.

Storage is created only as a new task-owned directory on an operator-configured volume outside
Git, with opaque server-generated references. Directory junctions/symlinks, file hardlinks,
path traversal, wrong permissions, altered/truncated/oversized artifacts and changed scope,
profile or retention approval are rejected. Shared OS permission code verifies protected NTFS
binary DACLs (current service identity/SYSTEM/Administrators only) or Unix 0700/0600. Read checks
never silently repair/widen an existing store's permissions.

Each blob/manifest is created exclusively, flushed/fsynced; manifest is the final commit marker.
Unix directory entries are fsynced too. A failed write leaves a private uncommitted/orphan artifact,
not a usable receipt. There is no overwrite/delete/automatic retention API. Separate trusted
registry state must retain the returned manifest/document hashes; recomputing approval from a
modified store is forbidden. Reopen verifies both pinned hashes and reparses bounded bytes.

The internal `AuthorizedEvidenceReader` requires OAuth scope, current source/company ACL, rate
check and durable access audit before filesystem reads, then completion/error audit. It does not
expose a public upload or model-authored profile/policy approval tool. Windows CI executes actual
inherited file DACL verification and rejection after an owned test file is widened to Everyone.
The service read has a server-configured five-second deadline (maximum 30); timeout records an
error, never a business success. Cancellation/timeout cannot stop an already running filesystem
thread, but that bounded thread is read-only and cannot return data to the cancelled request.

Runtime now wires the optional provider through a pinned private approval index and the read-only
`external_evidence_manifest` tool. Operator normalized intake creates a NEW index, preserves prior
records and prints only hashes/counts/opaque IDs. Gateway inputs cannot authorize paths, hashes,
profiles or policies. Index hash/permission/scope/window checks run before AND after blob reading;
revoked/stale approvals are never served from a trusted cache. See Integration's operator runbook.
Approval expiry bounds read authorization, not automatic retention/destruction guarantees.

Still OPEN: deployment identity/volume, backup/restore/retention approval, native format parsers and
real source reconciliation. Local file
fsync/reopen and fixture permission checks are not production WORM/PITR/retention approval.

---

## 13. DAD rule-pack architecture

Add a policy/rule layer above primitive semantic tools.

Suggested interfaces:

```text
dad_month_close_review(source_id, company_id, period, rule_pack_id, evidence_refs[])
dad_inventory_quality(...)
dad_counterparty_balance_review(...)
dad_cash_negative_days(...)
dad_bank_reconciliation(...)
dad_terminal_reconciliation(...)
dad_invoice_reconciliation(...)
dad_tax_precheck(...)
dad_payroll_precheck(...)
```

Do not implement these as unrestricted AI-written queries.

Each rule compiles to approved semantic operations plus optional evidence comparisons.

Result envelope:

```json
{
  "rule_id": "DAD-MC-009",
  "status": "PASS|FINDING|INCONCLUSIVE|EVIDENCE_REQUIRED",
  "company_id": "...",
  "period": "...",
  "finding": "...",
  "evidence": {
    "onec": ["..."],
    "external": ["..."],
    "native_report": ["..."]
  },
  "confidence": "validated-profile-only",
  "human_review_required": true
}
```

Tax/payroll/legal conclusions always retain human-review requirement unless a separately approved
regulated workflow says otherwise.

---

## 14. Financial statement semantic layer

Original DAD task explicitly requests:

- P&L;
- Cash Flow;
- Balance Sheet.

Current account-turnover primitives are not sufficient to claim these reports are implemented.

Add:

- `financial_statement_balance_sheet`
- `financial_statement_profit_loss`
- `financial_statement_cash_flow`

Requirements:

- exact configuration/company semantic profile;
- chart-of-accounts mapping;
- period rules;
- currency policy;
- comparative period where required;
- native 1C report reconciliation;
- no universal hard-coded Moldovan/Russian account assumptions.

### 14.1 Internal normalized projection and native comparison contract

`financial_statements.py` implements an INTERNAL exact-profile projection for all three statement
kinds. It is not yet the three public/live semantic tools above. Approved profile fingerprints bind
source/company/configuration/metadata, chart/activity selector + metric/sign/row mapping, currency/
timezone, period/comparative period, effective dates, native report mapping and tolerance. There
are no global account numbers, invented cash classifications or unrestricted formula/query input.

- Balance Sheet accepts complete known-opening `closing` snapshots at the exact end-of-period day.
- P&L accepts confirmed gross debit/credit period facts with profile-owned signs.
- Cash Flow accepts confirmed `cash_in`/`cash_out` activity facts, NEVER inferred from closing cash
  balances; distinct gross events are not deduplicated merely because amounts/net totals match.
- Every selector/metric requires explicit extracted coverage (including explicit zero); missing
  rows, unclassified nonzero amounts, duplicate facts, stale/cross-scope/incomplete/nonfinite data
  cannot PASS. No silent “unmapped ignore” option exists.
- Comparative periods require separate complete same-profile/currency/timezone observations.
  Required comparative native rows also cannot be skipped in native comparison.

Projection PASS means `VALIDATED_PROFILE_PROJECTION_ONLY`, not native/business acceptance. Returned
money is private authorized data, never public evidence. Result fingerprints bind rows plus source
artifact/evidence-level provenance and reject detached/mutated projection data. Native comparison
requires exact approved PROFILE fingerprint (a shared report-name alias is insufficient), exact
scope, completeness, independent artifacts and preserved evidence level; mismatches return hashed
findings. Neither projection nor equal native rows automatically approves a source/release/GO.

Public statement tools, runtime/live source collectors, approved chart/activity mappings, real
configuration native reports and required case coverage remain OPEN. This contract's synthetic
L1 fixtures are not native 1C or financial/legal validation.

---

## 15. Tax and payroll guardrails

### Tax

VAT/IPC/VEN checks are not ordinary balance lookups.

Require:

- jurisdiction/effective-date rule pack;
- filed declaration + receipt evidence;
- 1C supporting balances/turnovers/documents;
- legal-rule provenance;
- human review;
- explicit `INCONCLUSIVE` when external evidence is missing.

### Payroll

Require:

- payroll documents;
- time sheets;
- sick leave;
- bonus orders;
- vacation calculations;
- payroll/tax registers;
- source-specific mapping;
- human review.

Do not allow the model to invent a payroll/tax rule from generic accounting knowledge.

---

## 16. Access administration/product workflow

The final source requirement asks who can independently grant/revoke access.

Implement operator workflow:

```text
ROLE: SOURCE_ACCESS_ADMIN

can:
  create/update source metadata (not secrets directly)
  bind secret reference
  register companies
  grant/revoke principal/group -> source/company
  trigger capability refresh
  request semantic revalidation
  view audit / health / drift

cannot:
  read raw secret values
  bypass company ACL
  edit audit history
  enable unvalidated semantic mappings
  enable write tools
```

Initial implementation may be CLI/API. UI is optional for MVP but the operator workflow must be
documented and tested.

---

## 17. “Claude reads incorrectly” recovery workflow

The source explicitly asks how to update a connection when AI reads incorrectly.

Required runbook:

1. identify source/company/request ID;
2. inspect audit + exact semantic profile;
3. refresh live metadata/capabilities;
4. compare fingerprint;
5. if drifted, block affected semantic tools;
6. review mapping/profile;
7. run L1 fixture;
8. run L2/native reconciliation where material;
9. publish new profile version;
10. retire/rollback old profile;
11. re-run user question with new profile;
12. preserve before/after evidence.

Do not “teach Claude” by silently changing prompts while leaving source semantics unversioned.

---

## 18. Legacy implications

The DAD source does not currently name a concrete 8.2/7.7 customer target.

Therefore legacy remains demand-driven and MUST NOT block the modern 8.3 MVP.

The Diadoc reference currently states:

- support for multiple 1C 8.2/8.3 configurations;
- 1C 7.7 module support ended on 2026-09-01.

Baseline implementation strategy:

```text
modern 8.3
  -> primary OData route
  -> isolated RSV/COM fallback only where approved

legacy 8.2
  -> dedicated Windows VM/service
  -> exact version/configuration snapshot
  -> narrow read-only adapter
  -> separate license/security review

legacy 7.7
  -> containerized parser/reference path where file/metadata parsing is sufficient
  -> dedicated compatible Windows/x86 VM only when actual 7.7 runtime behavior is required
```

Do not install a matrix of old 1C runtimes on the main modern test host. Side-by-side legacy
installations can change shared COM registration and reduce reproducibility.

Docker remains appropriate around legacy runtimes for parsers, wrappers, orchestration and normalized
adapter APIs. A real old Windows 1C runtime is not required to live inside Docker unless a specific
Windows-container lane has been proven reproducible for that exact target.

No proprietary 1C installer/configuration binary may be committed to Git or published in a public
container image.

---

## 19. Coverage status after this review

### Current implementation

**NO — not every historical business scenario is implemented.**

Implemented foundation is strongest in:

- dynamic access;
- company isolation;
- metadata/capability routing;
- account turnover;
- sales/purchases;
- inventory;
- bank/cash;
- AR/AP;
- posting rows;
- audit/provenance.

Missing business layers include:

- DAD month-close rule pack;
- external evidence plane;
- tax declaration validation;
- payroll validation;
- P&L/CF/BS semantic reports;
- bank/Z/terminal/customs reconciliation;
- invoice/PDF reconciliation;
- reconciliation-act workflow.

### Architecture/roadmap after this review

**YES — every evidenced scenario is now assigned to one of four explicit lanes:**

1. **Current read-only core** — access/control + 1C primitives.
2. **Read-only DAD semantic/evidence expansion** — month close, external reconciliations, reports,
   tax/payroll prechecks.
3. **Legacy compatibility** — demand-driven isolated 8.2/7.7.
4. **Future write automation** — invoices/payments/cash-register posting under a separate write
   security model.

No scenario is silently dropped.

---

## 20. Recommended execution priority

### DAD-R0 — final access/control problem first

Close production-grade:

- 30–150 source/company access;
- grant/revoke without restart;
- onboarding/offboarding;
- drift recovery;
- audit/provenance;
- structural read-only enforcement.

### DAD-R0.5 — restore the real-reference test base

Prepare the supplied real test copy as an immutable reference corpus:

- download/store it only in local/private testbed storage;
- compute SHA-256 and inventory the archive;
- keep one untouched golden copy;
- restore separate disposable clones;
- identify exact 1C platform/configuration/schema;
- capture metadata/configuration fingerprint;
- create a read-only observation identity;
- do not mutate the golden/reference copy.

### DAD-R1 — real-source discovery, parity and semantic profile

Against the read-only clone:

- capability handshake;
- OData metadata and/or COM metadata;
- exact company discovery;
- OData↔COM parity where both paths exist;
- account/posting/document/register inventory;
- native report inventory;
- semantic profile draft for the exact configuration;
- zero-write observation evidence.

### DAD-R2 — accountant-selected six small checks

Implement DAD-SMALL-01 through DAD-SMALL-06.

Run the first four against the real-reference base as soon as the required native semantics are
validated. The Z-report and terminal cases remain `EVIDENCE_REQUIRED` until the matching external
reports are supplied.

### DAD-R3 — invoice/e-factura read-only reconciliation

Use the supplied invoice corpus as a real-world regression suite:

- parse/fingerprint external invoice evidence;
- match to 1C purchases/receipts/payments;
- run DAD-INV-01..11;
- preserve known good and known-error cases;
- no 1C mutation is required.

### DAD-R4 — DAD month-close rule packs

Encode the workbook as versioned, applicability-aware rules; start with rule families already
supported by validated P4 primitives.

### DAD-R5 — Ferma controlled synthetic expansion

Use Ferma to generate what the real-reference base cannot guarantee:

- deterministic rare edge cases;
- multi-company collision/isolation cases;
- fan-in/fan-out company networks;
- partial settlement/credit note/return/idempotency cases;
- repeatable golden expected/oracle results;
- scale beyond one real reference source.

### DAD-R6 — financial statements

Validated Balance Sheet / P&L / Cash Flow semantic tools with native 1C reconciliation.

### DAD-R7 — regulated/external-heavy checks

Tax, payroll, customs, CCAC, statutory-document validations with explicit external evidence and human
review.

### DAD-R8 — future write product

Only after explicit governance/security scope change:

- invoice posting;
- payments;
- cash-register import;
- any other write automation.

The write plane must be separately authorized and must never be inferred from the existence of the
historical test write credential or historical pilot code.

---

## 21. Acceptance gate

The DAD problem statement is considered fully covered in roadmap only if:

- every requirement ID in this document has an owner/lane;
- no read-only requirement depends on future write capability;
- every rule states its evidence dependencies;
- missing external evidence returns INCONCLUSIVE/EVIDENCE_REQUIRED;
- every company-scoped result proves company isolation;
- tax/payroll/legal checks retain human review;
- version/configuration-specific assumptions live in profiles/rule packs;
- source/profile drift fails closed;
- real 1C/native report reconciliation exists for accounting semantic claims;
- the real-reference original is immutable and only disposable clones are exercised;
- Ferma expected/oracle calculation remains independent from 1C/ERP_MCP actual observations;
- private source archives, credentials and raw client/test documents stay outside Git/public CI;
- historical customer/test credentials/raw documents are never committed to ERP_MCP.


---

## 22. Real-reference testbed decision

The supplied real 1C test copy is now an explicit project asset for **private/local validation**.

For repository documentation and CI it MUST be referred to by a neutral alias such as:

```text
REFERENCE_TEST_BASE_A
```

Do not commit its raw file, credentials, customer-identifying contents or Drive links to the public
repository.

### 22.1 Reference-copy topology

Use three logical states:

```text
REFERENCE_TEST_BASE_A_GOLDEN
  immutable archive / restore source
  never opened for mutation tests

REFERENCE_TEST_BASE_A_RO
  restored disposable clone
  read-only identity
  capability/profile/native-report/MCP validation

REFERENCE_TEST_BASE_A_RW
  separately restored disposable clone
  test-only write identity
  only for isolated historical/future write integration tests
  never used to justify writes in the production gateway
```

Before any test:

1. calculate archive SHA-256;
2. record archive size and source date;
3. inventory contained backup/artifact formats;
4. identify exact configuration/platform requirements;
5. restore a clone;
6. fingerprint resulting metadata/configuration;
7. verify the target marker before any write-capable test.

### 22.2 Why the real reference is valuable

It supplies something neither Fake1C nor synthetic data can provide alone:

- real configuration-specific metadata;
- real chart of accounts and analytics;
- real historical document structures;
- real operational mistakes;
- real primary-document correlation cases;
- accountant-reviewed findings;
- native 1C behavior for the concrete configuration.

It therefore becomes the first source for converting candidate semantic mappings into validated
source-specific mappings.

---

## 23. Existing local modern 1C engineering environment

A separate local engineering environment already exists for transport/security testing:

- 1C:Enterprise 8.3.27.2342 x64 full platform;
- Community/Developer License active;
- per-user `V83.COMConnector` works;
- disposable local file-mode test base exists;
- RSV Data v1.3.0 was installed into the disposable base;
- COM bridge health and metadata calls were exercised;
- the CFE was exported to XML/BSL and audited.

This environment is **not** the accounting reference base.

Its purpose is:

- P6 COM lifecycle;
- extension behavior/security review;
- bridge reconnect/timeout/failure tests;
- metadata normalization.

The real-reference restored clone is for accounting/configuration validation.

---

## 24. P6 / RSV production disposition

Live audit of the official release established that the extension is useful but not automatically
safe as a generic production business-data path.

Current ERP_MCP policy remains:

| Operation | Disposition |
|---|---|
| ping | ALLOW behind source ACL |
| config | metadata-only ALLOW candidate |
| describe | metadata-only ALLOW candidate |
| get_structure | metadata-only ALLOW candidate |
| help | metadata-only ALLOW candidate |
| query | DENY by default pending zero-write + company-scope proof |
| execute_query | DENY |
| reveal | HARD DENY |
| direct RSV HTTP MCP exposed to AI | DENY |

Reasons:

- anonymization can persist a token-map record;
- privileged reveal is not ERP_MCP principal/company-scoped;
- no immutable company predicate is provided by the extension itself;
- arbitrary query execution is not a bounded-cost semantic contract.

The real-reference base does not weaken these conclusions. It provides a place to verify exact
configuration capability and parity, not permission to expose generic query/reveal.

---

## 25. What the real-reference base can close

Once restored privately, `REFERENCE_TEST_BASE_A_RO` can provide real evidence for:

### D7 — compatibility/capability

- exact platform/configuration fingerprint;
- exact metadata inventory;
- exact source capabilities;
- positive/negative virtual-table evidence;
- OData/COM route selection;
- source-specific drift behavior.

### D8 — data plane

- real metadata smoke;
- real entity/document reads;
- real register reads where supported;
- OData↔COM result parity on selected safe reads;
- paging/count/limits/failure behavior.

### D9 — accounting

- account balances/turnovers;
- posting rows;
- sales/purchases;
- inventory;
- bank/cash;
- receivable/payable;
- source-specific semantic profile;
- native-report comparison;
- known-error negative regression.

### D5 — read-only

Using the RO clone and read-only identity:

- capture before/after fingerprints;
- exercise the gateway;
- verify no business state changes;
- verify no write tool is exposed;
- verify logs/audit contain no credentials.

### P6

- COM connect/disconnect/restart;
- metadata fallback;
- route normalization;
- error sanitization.

It does **not** by itself provide production deployment evidence, multi-company scale evidence or
external-document evidence.

---

## 26. Real-world regression corpus from the supplied materials

The real-reference source bundle already contains accountant-reviewed scenarios. These should be
encoded as private test-case aliases rather than client-identifying names in public repository code.

Recommended canonical aliases:

```text
REAL-INV-001 payment exists, receipt missing
REAL-INV-002 source invoice has two item qualities; 1C has one combined line
REAL-INV-003 supplier identity mismatch
REAL-INV-004 incorrect nomenclature/item mapping
REAL-INV-005 source document date differs from 1C registration/tax period
REAL-INV-006 service spans periods and requires accrual/allocation review
REAL-INV-007 production-overhead allocation remains unresolved
REAL-INV-008 1C receipt exists while primary archive evidence is missing
REAL-INV-009 invoice total and VAT match exactly
REAL-INV-010 line-level quantity/price/amount/VAT comparison
REAL-INV-011 small line-rounding differences while invoice total remains correct
```

A private evidence manifest outside Git maps these aliases to actual source documents.

Public tests may use sanitized/synthetic fixtures reproducing the same logical shapes.

---

## 27. Invoice corpus as a read-only acceptance gate

The supplied invoice archive and real test base allow a strong read-only vertical:

```text
primary invoice
     |
     v
Evidence parser
 fingerprint/provenance
     |
     v
normalized invoice facts
     |
     +-----------------------------+
     |                             |
     v                             v
real 1C purchase/receipt      payment / other 1C facts
     |                             |
     +--------------+--------------+
                    |
                    v
             reconciliation
                    |
                    v
PASS / FINDING / EVIDENCE_REQUIRED / INCONCLUSIVE
```

Compare at minimum:

- document number;
- supplier identity;
- date/accounting period;
- currency;
- item identity;
- quantity/UOM;
- unit price;
- amount before tax;
- VAT rate;
- VAT amount;
- total;
- matched payment/receipt where relevant.

Tolerance rules must be explicit and versioned.

Do not turn a PDF mismatch directly into a write action in the read-only MVP.

---

## 28. What one real test base cannot prove

The real-reference base is extremely useful but must not become a false universal oracle.

It cannot by itself prove:

### 28.1 30–150 source scale

Use:

- Fake1C/control-plane load;
- Ferma-generated source/company sets;
- later heterogeneous live pilot sources.

### 28.2 Cross-company isolation

If the reference source has only one relevant organization, it cannot prove multi-company leakage
resistance.

Use Ferma/multi-company synthetic bases and later a true multi-organization source.

### 28.3 Missing edge cases

If a scenario does not exist in the reference data, absence is not evidence of support.

Examples may include:

- credit notes;
- returns;
- partial settlements;
- multiple currencies;
- same-name parties;
- duplicate replay/idempotency;
- failed posting legs;
- unusual inventory states.

Generate these with Ferma.

### 28.4 External reconciliation

1C alone cannot prove:

- bank statement equality;
- Z-report equality;
- terminal report equality;
- customs/CCAC equality;
- filed VAT/IPC/VEN correctness;
- primary-document completeness;
- payroll-source correctness.

These require the External Evidence Plane.

### 28.5 Production operations

A local restored copy cannot close:

- production IdP;
- production network/egress;
- production secret provider;
- pilot-user acceptance;
- release authority;
- production backup/PITR.

---

## 29. Dual P5 strategy — real reference + controlled synthetic

P5 is now explicitly split into two complementary tracks.

### P5-A — Real Reference

```text
private supplied test copy
        |
        v
REFERENCE_TEST_BASE_A_RO
        |
        +-> exact metadata/capabilities
        +-> source-specific semantic profile
        +-> native reports
        +-> known real findings
        +-> invoice reconciliation
        +-> OData/COM parity
```

Primary question:

> Does ERP_MCP correctly understand and read this real 1C configuration?

### P5-B — Ferma Controlled Synthetic

```text
Ferma deterministic universe
        |
        +-> independent expected/oracle
        |
        v
test-only 1C seeder
        |
        v
AccountingSynthetic
        |
        +-> native 1C behavior
        |
        v
ERP_MCP observation
        |
        v
three-plane comparison
```

Primary questions:

> Can we deliberately generate every required edge case?

> Does ERP_MCP remain correct when the scenario topology changes?

Neither track replaces the other.

---

## 30. Test pyramid after the update

```text
L1 — Fake1C
  fast deterministic CI
  protocol/contracts/security/failure tests

L2-A — Ferma -> real 1C synthetic
  controlled scenario completeness
  independent expected/oracle

L2-B — real-reference test copy
  real configuration
  real documents
  real known errors
  native report/profile validation

L3 — controlled target/pilot
  production-like identity/network/secrets
  real users and target-specific reconciliation
```

Evidence must always identify which level produced it.

No L1/L2 result may be labelled L3.

---

## 31. Ferma responsibilities after the DAD review

Ferma remains authoritative for:

- deterministic synthetic economy;
- logical business time;
- canonical companies/products/locations;
- canonical economic events;
- company-network topologies;
- independent economic expected/oracle;
- reproducible scenario provenance.

ERP_MCP MUST NOT duplicate that generator.

ERP_MCP adds only:

- scenario-package ingestion;
- concrete 1C mapping profile;
- test-only business-document seeder;
- native 1C observer;
- normal read-only ERP_MCP observer;
- reconciliation evidence.

The seeder must never read Ferma expected results while creating 1C data.

---

## 32. Real-reference artifact handling

Private test material may contain realistic/customer-derived data even when the base is designated
for testing.

Required handling:

- local/private testbed storage only;
- no Git;
- no public CI artifact upload;
- no model-visible raw credential values;
- no raw archive attached to public issues/PRs;
- checksum and metadata may be stored;
- evidence summaries should use aliases;
- raw primary documents should follow approved retention/access policy.

Suggested private layout:

```text
D:\ERP_MCP_Testbed\reference\base-a\
  source\
    original-archive
  golden\
    immutable-backup
  clones\
    readonly\
    write-disposable\
  evidence\
    source-manifest.json
    checksums.sha256
    native-reports\
    reconciliations\
```

---

## 33. Test credential policy

Because the credential in the source history belongs to the dedicated test copy:

- it may be used only for that private test environment;
- it is not a production secret;
- it must still not appear in Git, logs, prompts, reports or process arguments;
- represent it as a secret reference, e.g. `local-test/reference-base-a/admin`;
- if read-only validation is possible with a lower-privilege account, prefer it;
- use a write-capable test identity only on the disposable RW clone;
- rotate it if the environment becomes shared beyond its intended test boundary or is repurposed.

The production gateway must never depend on this credential.

---

## 34. Real-reference execution sequence

### Stage A — acquire and preserve

1. download/copy the private archive to local testbed storage;
2. compute SHA-256;
3. record size/source date;
4. inspect archive structure without modifying contents;
5. identify backup format;
6. preserve immutable golden artifact.

### Stage B — restore RO clone

1. restore to a separate local base;
2. record platform/configuration version;
3. capture configuration/metadata fingerprint;
4. enumerate organizations;
5. create/use least-privilege read identity;
6. verify source is marked TEST/REFERENCE.

### Stage C — discovery

1. OData availability;
2. metadata;
3. COM capability;
4. exact document/register entities;
5. native report availability;
6. candidate semantic mappings.

### Stage D — read-only parity

For selected safe objects:

1. read through native/COM path;
2. read through OData where supported;
3. read through ERP_MCP;
4. normalize;
5. compare;
6. preserve evidence.

### Stage E — DAD small checks

Run DAD-SMALL-01..04 against validated semantics.

DAD-SMALL-05..06 require matching external evidence.

### Stage F — invoice corpus

Run REAL-INV-001..011 with private document aliases.

### Stage G — native reconciliation

Promote mappings only after required native-report cases pass.

### Stage H — optional RW disposable lane

Only when testing the historical/future write adapter:

1. restore a fresh RW clone;
2. create explicit test-run marker;
3. perform idempotent test writes;
4. re-read result;
5. verify no duplicate;
6. discard/reset the clone.

This stage has no authority over the production read-only gateway.

---

## 35. Evidence and result taxonomy

Every business rule/test should return one of:

```text
PASS
FINDING
INCONCLUSIVE
EVIDENCE_REQUIRED
CAPABILITY_UNSUPPORTED
ERROR
```

Examples:

- missing bank statement -> `EVIDENCE_REQUIRED`;
- source has no supported register -> `CAPABILITY_UNSUPPORTED`;
- reconstructed history lacks opening balance -> `INCONCLUSIVE`;
- known invoice mismatch reproduced -> `FINDING`;
- native report and ERP_MCP agree -> `PASS`.

Do not coerce missing evidence into PASS.

---

## 36. Public/private evidence split

Because ERP_MCP is a public repository:

### Public/repository-safe

- requirement IDs;
- sanitized scenario aliases;
- synthetic fixtures;
- hashes/digests;
- configuration family/version if non-sensitive;
- code/test results;
- aggregate non-identifying reconciliation summaries.

### Private/local only

- credentials;
- raw 1C archive/backup;
- raw invoice PDFs;
- customer/company identifiers;
- bank/customs/tax/payroll documents;
- private Google Drive links/IDs;
- any source material not explicitly approved for publication.

Before commit, review this document and related reports for private identifiers.

---

## 37. Updated final architecture

```text
                         Claude / AI
                              |
                              v
                           ERP_MCP
                   OAuth / ACL / Audit
                              |
          +-------------------+--------------------+
          |                   |                    |
          v                   v                    v
    1C Data Plane      External Evidence      DAD Rule Engine
 OData / COM / legacy    read-only input       versioned rules
          |                   |                    |
          +-------------------+--------------------+
                              |
                              v
                       Findings / Answers
                              |
                              v
                      provenance/evidence


Test and assurance plane:

          +---------------------+----------------------+
          |                                            |
          v                                            v
  Real Reference Testbed                        Ferma Synthetic
  real config/documents                         deterministic world
  known real errors                             independent oracle
          |                                            |
          +---------------------+----------------------+
                              |
                              v
                    Native 1C reconciliation
                              |
                              v
                         ERP_MCP proof
```

---

## 38. Final implementation principle

The complete project is not “an MCP that can query 1C”.

It is a governed business-assurance gateway in which:

- access is dynamic and company-scoped;
- transport capability is discovered rather than guessed;
- accounting semantics are versioned and validated;
- real reference data proves configuration fidelity;
- Ferma proves controlled scenario coverage and independence;
- external evidence is explicit when 1C alone is insufficient;
- missing evidence is visible;
- production remains read-only;
- legacy is isolated;
- future writes require a separate security/governance product boundary.
