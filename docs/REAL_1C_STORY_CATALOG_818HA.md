# ERP_MCP story catalogue for 818 HA SRL (read-only, OData) — v1, from the two Google Docs

Source: Dan's 8 read-only task list (T1..T8) + pilot chronicle (C5, C8, C9, C16). Produced by the functional-test-reviewer agent; all EntitySet names, account numbers and IPC/VEN semantics are UNKNOWN until live discovery.

Legend — personas: AC accountant, CA chief accountant, AU auditor, AD access admin, DO data owner.
Disposition: RR RUNNABLE_READ | NP NEEDS_PROFILE_MAPPING | UG UNSUPPORTED_GAP (truthful: CAPABILITY_UNSUPPORTED) | EV EVIDENCE_REQUIRED | WD WRITE_DEFERRED (refuse, never execute).
Tools: ABT accounting_balance_and_turnovers, APR accounting_posting_rows, INVB inventory_balance, INVM inventory_movements, CASH cash_movements, BANK bank_balance, ARB receivable_balance, APB payable_balance, ARA receivable_aging, APA payable_aging, DUP counterparty_duplicate_candidates, SAL sales_documents, PUR purchase_documents, READ onec_read, EVM external_evidence_manifest, CO companies_list, SRC sources_list, HLT source_health, CAP onec_capabilities, META onec_metadata_summary, FIND onec_find_entities, RSV rsv_metadata, STAT system_status, CLI operator CLI (not an MCP tool).
Oracles: ONAT native 1C query/report on the clone; OEXT hashed external evidence; OPDF the 21 hashed PDFs; OACL control-plane rows+audit; OFIX Fake1C/Ferma expectation; OACC accountant sign-off.
Negatives: X1 other company denied; X2 no validated profile -> SEMANTIC_PROFILE_UNVALIDATED; X3 truncation -> INCONCLUSIVE; X4 missing evidence -> EVIDENCE_REQUIRED; X5 write attempt refused, DB fingerprint unchanged; X6 metadata drift -> STALE; X7 grant revoked mid-session; X8 invalid UUID/period/top; X9 model-supplied entity/filter/URL rejected; X10 opening balance unknown -> INCONCLUSIVE; X11 synthetic presented as real; X12 evidence for wrong company/period rejected; X13 one company/source fails in a batch, rest answer.

Line format: ID | title | persona | src | G;W;T (short) | tools | disp | oracle | neg | pri

## A1. Month-close (T1, C5, C16.1)
- ST-001 | Month-closed verdict plus blockers | CA | T1,C5,NR-01 | NOT_CONFIRMED with missing definition/evidence, never "closed" from document presence | ABT,APR,EVM | EV | ONAT closing ops + OACC | closing doc exists but residual 811/821/216.1 remains | P0
- ST-002 | Actionable cleanup proposals, not a report | CA | T1,C5,C16.1 | each proposal cites rows, accounting+fiscal angle, human_review_required, no claim of execution | ABT,APR,ARB,APB | UG | OACC checklist | proposal must not claim posted | P0
- ST-003 | Compensate between accounts proposal (221/523, 224/521/544; contract/document/currency grain) | AC | T1,RO-04 | text only | ARB,APB,ABT | NP | ONAT | counterparty-only grain rejected; X5 | P0
- ST-004 | Empty 217 result is not a zero balance | AC | T1 | no data != 0.00, INCONCLUSIVE | INVB,ABT | NP | ONAT | X10 | P1
- ST-005 | Production-cost closing completeness (811/821/711), applicability-aware | AC | T1,NR-03/04 | residual only where required | ABT,APR | NP | ONAT | no-production company: not applicable | P1
- ST-006 | Document tick/flag completeness | AC | T1,C5 | list docs lacking required flags | PUR,SAL,READ | NP | ONAT | X9 | P1
- ST-007 | Fiscal angle of cleanup | CA | T1 | flagged with legal-rule version, human review | APR,ABT | UG | OACC | no generic legal conclusion | P1
- ST-008 | Tax receivable/liability (225 vs 534) vs CCAC taxpayer account | CA | T1 | compare with CCAC statement | ABT,EVM | EV | OEXT | X12 | P1
- ST-009 | Day-boundary/timezone: 31.08 vs 01.09 (Europe/Chisinau) | AC | T1,NR-10 | first in, second out | APR,PUR | NP | ONAT | naive date rejected X8 | P1
- ST-010 | Row-count tie-out: pages cover all posting rows once | AC | C6,RO-01 | no gap/duplicate, equals ONAT | APR | RR | ONAT row count | X3 | P0
- ST-011 | Determinism: repeat/concurrent identical question | AC | C16 | identical figures, no bleed | ABT,ARB | RR | OFIX | concurrent different-company never mix (X1) | P1
- ST-012 | Baseline vs workbook-guided recall | CA | C5 | recall/precision per mode | ABT,APR | EV | OACC finding list | no evidence upgrade | P1
- ST-013 | Period semantics of ABT (inclusive end, tz) | AC | T1 | inclusive documented, equals ONAT | ABT | NP | ONAT | X8 | P0

## A2. Quick client answers (T2)
- ST-014 | VAT payable: output vs input vs net | AC | T2,RO-08 | provisional if period open | ABT | NP vat.liability | ONAT VAT | X2,X1 | P0
- ST-015 | Debts: payables by counterparty/contract with aging | AC | T2,RO-09,SC01 | buckets sum to APB total | APB,APA | NP payable.open_items | ONAT | opening_items_known false -> INCONCLUSIVE | P0
- ST-016 | Who owes us: ARB ties to receivables account | AC | T2,RO-09,SC03 | debtors separate from unapplied advances | ARB,ARA,ABT | RR | ONAT 221 | X1 | P0
- ST-017 | Budget liabilities by type | AC | T2 | VAT, income tax, CAS/CASS | ABT | NP tax.liabilities | ONAT | globally guessed accounts = defect | P1
- ST-018 | Cash+bank position by account/currency | AC | T2,SC09 | separable, point-in-time | BANK,CASH | RR | ONAT | date w/o offset X8 | P1
- ST-019 | Mixed-currency totals: no silent conversion | AC | T2 | per-currency rows | ARB,ABT | NP fx.rate | ONAT | silent summation | P1
- ST-020 | "Datorii" disambiguation | AC | T2 | structured multi-class answer | APB,ABT | NP | OACC | - | P2
- ST-021 | Reconciliation status with counterparty X | AC | T2,T8 | CAPABILITY_UNSUPPORTED | NONE | UG | - | no invented status | P2
- ST-022 | Answer provenance on every number | AC | T2,C16 | source/company/period/evidence level; L1 never as real | all data tools | RR | OFIX | X11 | P1
- ST-023 | As-of freshness (clone dated 2026-09-15) | CA | C6 | states data-as-of | ABT,HLT | NP source.as_of | OACC | stale flagged | P1

## A3. Financial statements (T3)
- ST-024 | P&L per template, provisional if 811/821 unallocated | CA | T3,RO-10 | ties to ONAT | ABT | UG | ONAT P&L | X2; unmapped nonzero not dropped | P0
- ST-025 | Balance sheet A = L+E, opening known | CA | T3,RO-12 | - | ABT | UG | ONAT | X10 | P0
- ST-026 | Cash flow (direct) from cash/bank flows | CA | T3,RO-11 | - | CASH,BANK | UG | ONAT+OEXT | never from closing balances | P0
- ST-027 | Comparative Aug vs Jul same profile/currency | CA | T3 | - | ABT | UG | ONAT | differing profile refused | P1
- ST-028 | Free-form "useful" template | CA | T3 | labelled non-template, assumptions | ABT | UG | OACC | X11 | P2
- ST-029 | Zero-activity company: explicit zeros | AC | T3 | missing rows never PASS | ABT | UG | ONAT | - | P1
- ST-030 | Statement vs native report diff | AU | T3 | FINDING with hashed diff | ABT | UG | ONAT | - | P1

## A4. Quality control (T4)
- ST-031 | VAT pre-filing expected figures from 1C | AC | T4,RO-13 | human review | ABT,PUR,SAL | UG | ONAT VAT register | - | P0
- ST-032 | Filed VAT declaration+receipt vs 1C | CA | T4,RO-13 | - | EVM,ABT | EV | OEXT | X12 | P0
- ST-033 | IPC declaration vs payroll tax balances | CA | T4,RO-14 | form meaning UNKNOWN | EVM,ABT | EV | OEXT | X4 | P1
- ST-034 | VEN declaration vs income/tax data | CA | T4,RO-15 | form meaning UNKNOWN | EVM,ABT | EV | OEXT | X4 | P1
- ST-035 | Portfolio scan: which of 30..150 companies have an unclosed month | CA | T4,RO-30 | failed company listed, rest answered | CO,SRC,ABT | UG | OFIX+ONAT sample | X13,X1 | P0
- ST-036 | Risk ranking uses rule-evidenced flags only | CA | T4 | - | CO,ABT | UG | OACC | invented probability = defect | P2
- ST-037 | "What to adjust before filing" (July receipt booked in August) | AC | T4,RO-27 | review item only | PUR,APR | NP vat.register | ONAT | - | P1

## A5. Bank (T5)
- ST-038 | Closing balance per bank account/currency vs statement | AC | T5,RO-16 | per-account reconcile | BANK,EVM | EV | OEXT | combined sum = defect | P0
- ST-039 | Statement period/account mismatch rejected | AC | T5 | - | EVM | EV | OEXT | X12 | P1
- ST-040 | Unmatched items both directions, explicit tolerance | AC | T5 | - | CASH,EVM | EV | OEXT | tolerance undeclared -> INCONCLUSIVE | P1
- ST-041 | Statement format: CSV accepted; PDF/MT940 CAPABILITY_UNSUPPORTED | AC | T5 | - | EVM | EV | - | URL evidence X9 | P2
- ST-042 | Operation type correct (supplier payment not "other") | AC | T5,RO-17 | - | APR,PUR,READ | NP bank.operation_type | ONAT | X9 | P0
- ST-043 | Settlement account correct (advance vs settlement) | AC | T5 | APR has no amounts -> partial flagged | APR | NP | ONAT | - | P1
- ST-044 | Payments to individuals: withholding settings | AC | T5 | - | APR,READ | NP counterparty.kind | ONAT | payroll privacy ST-052 | P1
- ST-045 | Imported-services VAT self-calculation flag | AC | T5 | flag missing = finding | PUR,APR,READ | NP document.flag.vat_reverse_charge | ONAT | domestic supplier no finding | P0

## A6. Customs (T6)
- ST-046 | Automatic monthly request to Customs | AC | T6 | must not send; CAPABILITY_UNSUPPORTED | NONE | UG | - | - | P2
- ST-047 | Customs act vs 1C import VAT/duty per declaration | AC | T6,RO-18 | - | EVM,ABT,APR | EV | OEXT | wrong IDNO X12 | P1
- ST-048 | Which companies do customs operations | CA | T6 | - | CO,APR | NP company.activity.customs | OACC | - | P2

## A7. Payroll (T7)
- ST-049 | Recompute gross to net vs timesheet | CA | T7,RO-19 | - | EVM,ABT | EV | OEXT | X4 | P0
- ST-050 | Sick leave/vacation/bonus recomputation | CA | T7 | - | EVM | EV | OEXT | X4 | P1
- ST-051 | Negative employee settlement balances | AC | T7 | - | ABT | NP payroll.employee_settlements | ONAT | - | P1
- ST-052 | Payroll personal data protected | AU | T7 | masked/denied, audit row | ABT,APR | NP | OACL | permission is accounting.read only (no payroll scope) | P0
- ST-053 | Withholding/contribution recomputation by versioned rule pack | CA | T7 | human review | ABT | UG | OACC | no invented rate | P1
- ST-054 | Payroll in a separate source linked to the company | AD | T7,RO-32 | - | SRC,CO | NP | OACL | link must not widen grant X1 | P1

## A8. Reconciliation acts (T8)
- ST-055 | Act data per counterparty/contract/currency at date | AC | T8,RO-20 | - | ARB,APB,ABT | NP | ONAT | contract-less aggregate insufficient | P0
- ST-056 | Act document generation | AC | T8 | CAPABILITY_UNSUPPORTED | NONE | UG | - | - | P1
- ST-057 | Send act to the client's client | AC | T8 | never executed; refused | NONE | WD | - | - | P1
- ST-058 | Received act vs 1C, document-level differences | AC | T8,RO-20 | - | EVM,ARB,APB | EV | OEXT | X12 | P0
- ST-059 | Currency/contract split differences | AC | T8 | - | EVM,ARB | EV | OEXT | no FX guess | P1
- ST-060 | Act date differs from period end | AC | T8 | INCONCLUSIVE | EVM | EV | OEXT | - | P1
- ST-061 | Duplicate counterparties: act per canonical party, never merged | AC | T8,SC08 | merge_count 0 | DUP,ARB | NP | OFIX+ONAT | - | P1
- ST-062 | Act workflow state tracking | CA | T8 | - | NONE | UG | - | - | P2

## A9. 21 invoices / e-Factura (C8, C9)
- ST-063 | 21 invoices vs 1C control totals incl. "2 API-created" caveat | AC | C8,NR-08 | - | PUR,EVM | EV | OPDF | if the 2 absent from RO clone: report, not a tool defect | P0
- ST-064 | Aggregate anchors: 6 invoices 73,108.42 incl VAT = 27.42% of 266,614.64; affected lines 36,528.82 (candidates) | AU | C8 | anchor promoted to PASS only after native confirmation | PUR,EVM | EV | OPDF+ONAT | - | P0
- ST-065 | Re-ingest same PDF/number is idempotent | AC | C8 | - | EVM | EV | OPDF | - | P1
- ST-066 | Invoice of company B under company A | AC | C8 | - | EVM,PUR | EV | OPDF | X1,X12 | P1
- ST-067 | e-Factura (SFS) registry vs 1C purchases, both directions | AC | C8 | - | EVM,PUR,SAL | EV | OEXT | X4 | P1
- ST-068 | "Enter the invoices into 1C automatically" | AC | C9 | refused, DB fingerprint unchanged | NONE | WD | - | X5 | P0
- ST-069 | Unit conversion (kg vs t) with tolerance | AC | C8,DAD-INV-10 | - | PUR,EVM | EV | OPDF | no implicit conversion | P2
- ST-070 | Evidence privacy: no raw PDF content/identifiers | DO | C8 | - | EVM | EV | OACL | - | P1

## A10. Access and operations (C16)
- ST-071 | New client onboarding by a non-engineer (3-8/month) | AD | C16.b | data only after profile validation | SRC,CO,CAP,HLT,CLI | UG | OACL | grant w/o profile X2 | P0
- ST-072 | Revoke effective next call incl in-flight | AD | C16.b,RO-31 | - | CO,ABT | RR | OACL audit | X7 | P0
- ST-073 | Dry-run grant with company identity confirmation | AD | C16.b | - | CLI | UG | OACL | X1 | P1
- ST-074 | Bulk grant/revoke via CSV, partial failure, idempotent | AD | C16.b,RO-30 | - | CLI | UG | OACL | X13 | P1
- ST-075 | List 150 visible companies with paging; two principals disjoint | AD | C16,RO-30 | - | CO | RR | OACL | X1 | P1
- ST-076 | Audit completeness and append-only | AU | C16,RO-34 | 1 audit row each; UPDATE/DELETE denied | all tools | RR | OACL | tampering denied | P0
- ST-077 | Time-boxed auditor access | AD | C16.b | expires automatically | CLI,CO | UG | OACL | X7 | P1
- ST-078 | "Claude read it wrong" recovery loop | AD | C16.c,RO-33 | request id, audit, profile fix, revalidate, rerun | ABT,CLI,CAP | NP | ONAT | prompt tweak w/o profile version is not a fix | P0
- ST-079 | Metadata drift -> STALE, fail closed | AD | C16.c,RO-33 | - | ABT,CAP,META | RR | OFIX | X6 | P0
- ST-080 | Profile template reuse; per-company validation cost | AD | C16 | - | CLI | NP | OACL | one validation never validates another | P1
- ST-081 | Health across N sources; slow source doesn't block | AD | C16 | - | SRC,HLT,STAT | RR | OFIX | X13 | P1
- ST-082 | Data-owner secret handoff outside chat | DO | C16 | secret in chat/tool output redacted+rejected | CLI | UG | OACL | - | P1
- ST-083 | Secret hygiene sweep over all outputs/audit/logs | AU | C16 | no secret pattern | all | RR | artifact grep | any hit fails | P0
- ST-084 | Zero-write proof: DB fingerprint before/after full catalogue | AU | C16.3,DAD-ACC-01 | - | all | RR | ONAT fingerprint | X5 | P0
- ST-085 | R/W-capable identity (Admin_1C class) rejected or flagged | AD | C16.3 | production runtime must not start with it | HLT,CAP,CLI | RR | ONAT permission probe | - | P0
- ST-086 | Source outage -> typed error, no stale cache, recovers w/o restart | AD | C16 | - | ABT,HLT | RR | OFIX | cached numbers never shown as current | P1
- ST-087 | READ abuse: action/post/$batch/function via entity_set or filter | AU | C16.3 | - | READ | WD | ONAT fingerprint | X5,X9 | P0
- ST-088 | "Close the month / post / unpost / set the tick" | AC | C5,C16.3 | - | NONE | WD | - | X5 | P0
- ST-089 | WR-01: pay suppliers from a list | AC | WR-01 | - | NONE | WD | - | X5 | P1
- ST-090 | WR-02: import SFS cash-register data | AC | WR-02 | - | NONE | WD | - | X5 | P1

## B. MISSING ACCOUNTING COVERAGE (AX) — not covered by RO/NR/SC
- AX-001 Depreciation: monthly amount, start date, cap at cost, expense account | AC | ABT,APR | NP fixed_asset.depreciation | ONAT | P1
- AX-002 Fixed-asset register vs GL tie-out | AU | ABT | NP | ONAT | P1
- AX-003 Asset in-service state vs depreciation start; disposal | AC | APR | NP | ONAT | P2
- AX-004 Month-end FX revaluation + difference accounts | AC | ABT,ARB,APB,BANK | NP fx.revaluation | ONAT | rate source unmapped -> INCONCLUSIVE | P0
- AX-005 Official BNM rate on date vs rate used in 1C | AU | EVM,ABT | EV | OEXT | X12 | P1
- AX-006 Advance reports: accountable-person balances >30 days, negatives | AC | ABT,APR | NP accountable.persons | ONAT | personal-data rule | P1
- AX-007 Advance reports without supporting receipts | AU | EVM | EV | OEXT | X4 | P1
- AX-008 Inter-company/related-party balances across portfolio | CA | CO,ARB,APB | UG (conflicts with isolation) | ONAT both | one-side grant must get X1 | P1
- AX-009 Old payables/receivables as write-off candidates | CA | ARA,APA | NP | ONAT | proposal only X5 | P1
- AX-010 Inventory count act vs book balance | AC | INVB,EVM | EV | OEXT | X12 | P1
- AX-011 Intramonth negative stock (daily replay) | AC | INVM,INVB | NP inventory.movements | ONAT | X10 | P1
- AX-012 Cost-price anomalies | AC | INVB,INVM | NP inventory.cost | ONAT | quantity-only partial | P2
- AX-013 VAT register totals vs VAT ledger turnovers | AC | PUR,SAL,ABT | NP vat.register | ONAT | VAT-mixed distinguishable | P0
- AX-014 e-Factura issued vs 1C sales completeness | AC | SAL,EVM | EV | OEXT | X4 | P1
- AX-015 Input VAT deducted without valid invoice/supplier registration | AC | PUR,READ | NP counterparty.vat_status | ONAT | review item | P1
- AX-016 CAS/CASS/income-tax accounts equal payroll sums | AC | ABT | NP | ONAT | P1
- AX-017 Contributions accrued vs paid vs taxpayer statement | CA | ABT,BANK,EVM | EV | OEXT | X12 | P1
- AX-018 Withholding on non-resident payments | AC | PUR,APR | NP | ONAT | rule version required | P1
- AX-019 Imported-services VAT total vs VAT ledger | AC | PUR,ABT | NP | ONAT | P1
- AX-020 Closing income/expense accounts + financial-result transfer (month vs year-end) | CA | ABT | NP period.closing | ONAT | non-applicable month not a finding | P1
- AX-021 Cash limit and end-of-day cash balance | AC | CASH,ABT | NP cash.limit | ONAT | limit order missing X4 | P1
- AX-022 Cash payment to one counterparty over legal cap | AC | CASH | UG (legal rule pack) | OACC | no invented threshold | P2
- AX-023 Bank fee/commission classification | AC | APR | NP (needs amounts) | ONAT | partial flagged | P1
- AX-024 Document-level duplicates (number,date,counterparty,amount) | AC | PUR,SAL | RR | ONAT | no merge X5 | P1
- AX-025 Document date vs posting period delta, bulk (SC07 ext) | AC | PUR,APR | NP | ONAT | X8 | P1
- AX-026 Unposted/deletion-marked documents in the month (SC04 ext) | AC | PUR,SAL | NP | ONAT | unposted rows no movement | P1
- AX-027 Contract vs document currency mismatch | AC | PUR,SAL,ARB | NP | ONAT | P1
- AX-028 Supplier invoice vs receipt vs payment round trip | AC | PUR,APR | NP | ONAT | P1
- AX-029 Period-lock integrity: edits after the closing date | AU | NONE | UG (no change-log read) | - | CAPABILITY_UNSUPPORTED | P1
- AX-030 Blank mandatory fields (IDNO, contract, VAT rate) | AU | READ,PUR | NP master_data.quality | ONAT | READ guessed entity X9 | P1
- AX-031 Consolidation preconditions across 30..150 companies | CA | CO,META | UG | OFIX | X13 | P2
- AX-032 Inventory register vs GL 211 value | AC | INVB,ABT | NP | ONAT | value absent -> partial flagged | P1
- AX-033 GL balance with blank counterparty analytics | AC | ABT,ARB,APB | NP | ONAT | P1
- AX-034 Revenue cut-off (shipment 31.08, invoice next month) | AC | SAL,APR | NP | ONAT | P1
- AX-035 Prepaid-expense amortization completeness | AC | APR,ABT | NP | ONAT | P2
- AX-036 Vacation accrual/provision reasonableness | CA | ABT | NP | OACC | P2
- AX-037 Loans/leasing: interest accrual, current/non-current split | CA | ABT,APR | NP | ONAT | P2
- AX-038 Statutory capital vs registry extract | AU | ABT,EVM | EV | OEXT | X12 | P2
- AX-039 Tax-regime applicability (VAT payer or not) gates every VAT rule | CA | ABT | NP company.tax_regime | OACC | no global per-account assumption | P0
- AX-040 Decimal precision: sums to the bani, no float drift, negative zero | AU | ABT,APR | RR | ONAT | P1

## C. COVERAGE GAP LIST (requirements missing, not just tests; new tools need scope rebaseline)
- REQ-GAP-01 no accountant-approved definition of "month closed".
- REQ-GAP-02 no public rule-pack tool/output contract for "actionable proposal".
- REQ-GAP-03 no Moldova jurisdiction rule pack with legal source/effective dates.
- REQ-GAP-04 ABT has no account/analytics parameter; per-account (216.1, 241.1) contract undefined.
- REQ-GAP-05 APR projection has no amounts; doc-to-posting join unspecified.
- REQ-GAP-06 INVB has no value (RO-02 value, 211 GL tie-out unanswerable).
- REQ-GAP-07 document attributes (flags, operation type, contract, currency, VAT flag, deletion mark) not in canonical projections.
- REQ-GAP-08 no profile concepts for VAT liability, budget obligations, VAT register.
- REQ-GAP-09 no statement tools/template governance/versioning.
- REQ-GAP-10 evidence plane takes only normalized CSV (no PDF/XML/MT940 parsers, no upload workflow).
- REQ-GAP-11 no portfolio-level scan / per-company failure isolation / time-cost budget for 150 companies.
- REQ-GAP-12 no access-admin role workflow, dry-run, bulk op, expiring grants.
- REQ-GAP-13 validation cost at scale (10 native PASS cases per profile vs 3-8 new clients/month).
- REQ-GAP-14 payroll personal data has no permission separate from accounting.read.
- REQ-GAP-15 no policy for outbound communications (customs request, sending acts).
- REQ-GAP-16 onec_read refusal contract for actions/POST/$batch not stated as requirement.
- REQ-GAP-17 time semantics undefined (Europe/Chisinau, inclusive end, copy date vs as-of).
- REQ-GAP-18 no multi-currency policy (BNM rate source, revaluation, conversion refusal).
- REQ-GAP-19 rule applicability predicates (tax regime, activity) have no profile concept.
- REQ-GAP-20 no read-only change-history/period-lock audit.
- REQ-GAP-21 cross-company elimination conflicts with isolation; decision unrecorded.
- REQ-GAP-22 workbook families without rule/test: fixed assets, FX, advances, accruals, loans, equity.
- REQ-GAP-23 no master-data quality scan requirement.
- REQ-GAP-24 clone provenance unrecorded (do the 2 API-created invoices exist in the RO clone?).
- REQ-GAP-25 client-facing answers lack provenance/evidence-level/human-review contract.
- REQ-GAP-26 no oracle protocol (who produces and signs native reports; NR-01..10 all NEEDS_NATIVE_CONFIRMATION).
- REQ-GAP-27 no glossary for IPC, VEN, CCAC, "importul de servicii diferite de curs".

New product tools needed (scope rebaseline): rule-pack/month-close review (ST-002,007,012,031,036,053); financial statements (ST-024..030); portfolio scan (ST-035); act generation/tracking/sending (ST-021,056,057,062); outbound customs request (ST-046); access-admin workflow (ST-071,073,074,077,082); change-history read (AX-029); legal-cap rule pack (AX-022); consolidation/cross-company (AX-008,031). Profile-concept additions only (no new tool): all NP stories.

## D. Counts (130 = ST 90 + AX 40)
Class: RR 16 (ST14+AX2), NP 53 (25+28), UG 26 (22+4), EV 29 (23+6), WD 6 (6+0).
Priority: P0 37 (34+3), P1 76 (47+29), P2 17 (9+8).
Weak points: only 16/130 runnable today and all need a validated profile; the whole data plane sits behind "10 native PASS cases per profile"; fixture-profile tests can still pass with a wrong account/sign/period boundary — close with ST-010, ST-013, ST-016, AX-040 against ONAT on the real clone.
