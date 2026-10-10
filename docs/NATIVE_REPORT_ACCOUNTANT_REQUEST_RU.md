# Accountant Request: Native 1C Reports for Profile Validation (818 HA)

**Purpose (Release 1 validation request):** Until the real-source semantic profile has been verified, the ChatGPT plugin must not provide trusted answers about balances, turnovers, or accounts payable (`SEMANTIC_PROFILE_UNVALIDATED`). An independent person must verify the profile against genuine standard 1C reports. This R1 procedure calls for **at least ten distinct original reports captured through the native 1C UI**; report-engine evidence is not automatically eligible under this policy. The full requirements are in [Native Report Capture](NATIVE_REPORT_CAPTURE_RUNBOOK.md).

**Important:** This is an operational request, not permission to connect to a business production database or access financial data without grants. Later Phase 2 proposals for qualified native engine automation do **not** retroactively change this R1 policy.

## Procedure: One Original Report Per Case

1. Open the authorized 818 HA database copy dated September 15, 2026, for the period **August 1–31, 2026**.
2. For each case below, run the specified standard report in the actual 1C client and export the original as XLSX or MXL.
3. Place the export under `D:\ERP_MCP_Testbed\1c\reference\native_reports\captures\<case-number>` with filename `native_report.xlsx`.
4. Calculate its immutable byte digest: `Get-FileHash -Algorithm SHA256 <file>`.
5. Complete the case in `D:\ERP_MCP_Testbed\1c\reference\native_reports\native-evidence.TEMPLATE.json`, including `report_name` as shown in the 1C client, `generated_at` from the client, `native_report_sha256`, and independently verified `signed_by`. Mark `status: PASS` **only when the independently produced native report matches the gateway's relevant output under the same scope and cutoff**; otherwise record `FAIL` or `INCONCLUSIVE`. Never use the gateway's output as its own expected value.

The sample template and validation code must be reviewed for evidence-provenance/authentication controls. Merely entering a `signed_by` string or a SHA-256 claim does **not** establish independent human attestation.

## Required Evidence Cases

| Case | Claim under examination | Original 1C report |
| --- | --- | --- |
| NR-01 | Month-end closing totals | Standard trial balance and month-end closing operations |
| NR-02 | Account 216.1 balance as of August 31 | Account card or trial balance for 216.1 |
| NR-03 | Account 811.1 turnover in August | Account card for 811.1 |
| NR-04 | Account 821 turnover in August | Account card for 821, including cost-allocation breakdown |
| NR-05 | Negative balances on account 211 | Inventory/product/warehouse trial balance |
| NR-06 | Account 211 items without movement in August | Product/warehouse movement report for August |
| NR-07 | Cash account 241.1 closing balance and sign | Cashbook or cash account card by cash register and day |
| NR-08 | Find 21 provided invoices | Purchasing/receipts documents and VAT purchase ledger |
| NR-09 | Payments with no goods-receipt documents | Bank records, advance reports, purchasing documents |
| NR-10 | August 31 receipts lacking original supporting documents | Receipts register dated August 31, 2026 |
| **NR-11** | **Accounts payable on 521.1 as of August 31** | **Trial balance or account card for 521.1, expanded by supplier and contract** |

**NR-11 is additional.** The first ten cases do not establish account 521 coverage, even though account 521.1 is required to answer “How much do we owe each supplier?” Profile-wide validation requires the full set of relevant cases; passing unrelated cases does not automatically prove account 521.1 accuracy.

## After Obtaining the Reports

An authorized operator may execute the documented profile validation command only against the approved environment:

```text
scripts/semantic_profiles.py validate --profile-id <id> --evidence-file native-evidence.json --actor <id>
```

This historical validation contract requires ten distinct evidence-backed PASS cases with hashes. The actual accounting mapping decision remains the accountable operator's responsibility.

For the referenced 818 HA configuration, an **account-based** strategy is needed: `accounting_balance_by_analytics` is the intended route for account 521.1. The generic `payable_balance` route is not an equivalent replacement because the settlement accumulation register assumed by that route is absent from this configuration; supplier settlements are represented in account 521. Do not invent a missing register or infer due dates/aging from a balance alone.

**Current profile readiness must be checked separately; this document does not assert that the real 1C source, 521.1 semantic mapping, independent accountant sign-off, or production release is presently validated.**
