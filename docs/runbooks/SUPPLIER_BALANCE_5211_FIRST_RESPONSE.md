# Supplier payable snapshot: account 521.1 (read-only, first-response workflow)

Status: **implemented in isolated branch**; not a general AP or overdue-aging approval.
Scope: ERP_MCP, current validated-machine reference source `onec-818ha-reference`, company 818 HA SRL.
Do **not** confuse the real-1C reference *clone* with a confirmed current production 1C base.

## Frozen requirement / Definition of Done trace

This is **not a new semantic accounting tool, scope rebaseline, or general AP feature**:
it is a bounded first-response presentation of the existing `HYB-1`
(`accounting_balance_by_analytics`, explicitly frozen under ADR-0008 and the
2026-10-07 operator rebaseline). All additional business scopes remain deferred
under `SCOPE-1` until their own requirements and acceptance are approved.

| Existing requirement | Applied behavior | DoD impact |
|---|---|---|
| `HYB-1`, `FR-E1`, `FR-E2` | Only the exact validated 521.1 account profile; source-controlled OData/COM routing, no universal accounts | `D7` capability, `D9` machine-level only; native UI approval still **OPEN** |
| `FR-D1`, `NFR-R2` | Bounded GUID-filter batches, row/pagination completeness, combined response byte cap, no unbounded fallback | `D8` bounded read, `D14` robustness tests |
| `FR-A2`, `FR-B1` | Server-side source/company ACL and independent raw catalog entitlement for names | `D3` isolation; unauthorized names withheld |
| `FR-F1`, `NFR-S1` | Separate durable access/completion audit for every catalog batch, unexpected audit failures block the answer | `D11` fail-closed audit |
| `NFR-S3`, `TEST-REF-1` | Read-only 818HA reference clone; no posted entries, no arbitrary 1C code or native-proof claims | `D5` read-only; `D9` native sign-off **OPEN** |
| `SCOPE-1` | No new `payable.balance` / `payable.open_items` privileges or unproven semantic mapping | `D0` trace updated; `D16` production **NO-GO** |

These rows identify gates **advanced by code and tests**, not closed: signed native
1C reports, complete supplier accounts, aging reconciliation, production access
and operator release approval remain separate external gates.

## What the first answer must include

1. Resolve **source/company** from `sources_list` / `companies_list`. No invented IDs.
2. `source_health` must be healthy; `onec_capabilities` compatible and stable.
3. For 521.1, call `accounting_balance_by_analytics` with a **timezone-aware end-of-day** `as_of`.
   Example August Moldova: `2026-08-31T23:59:59+03:00`. Bare `2026-08-31` is invalid.
4. If the result includes `supplier_summary.status == COMPLETE`, present the list,
   `balance_credit` (what is recorded as payable) and `balance_debit` (advances/overpayments)
   **in separate columns**. Never silently net credits against debits across contracts,
   documents, currencies, or suppliers.
5. The `supplier_summary` exists only for an **exact single-account mapping to 521.1**
   with a stable validated profile and non-truncated source response. Catalog names are read
   only using the independently authorized and audited `onec_read` tool. If the raw-catalog
   grant is missing, return allowed supplier refs with `supplier_name = null`, never bypass ACL.
6. Always label the result `ACCOUNT_521_1_ONLY` and repeat evidence level/native status
   from the underlying analytics tool. `PROFILE_VALIDATED_MACHINE` is **not** a signed native
   UI account-card / supplier-reconciliation report.
7. Missing rows, missing currency confirmation, stale profile, denied raw catalog, incomplete
   page, unknown source, or missing evidence are **not** reported as zero or as global AP.
   For a full AP report, include other confirmed vendor-liability accounts only with their own
   exact validated mappings; do not infer 521.1 is all supplier debt.

## Root-cause analysis (2026-10-09)

PostgreSQL `bag.audit_events` on `onec-818ha-reference`:
- `payable_balance`: `SEMANTIC_PROFILE_UNVALIDATED` because **`payable.balance`**
  is not mapped and validated for the real 818HA company.
- `payable_aging`: `SEMANTIC_PROFILE_UNVALIDATED` because **`payable.open_items`**
  has no independently confirmed open-invoice/payment/allocation/due-date semantic profile.
- `accounting_balance_by_analytics`: the previously supplied date-only `as_of`
  generated a `ValueError`. An RFC3339 local-end-of-day timestamp succeeded.
- There is one **VALIDATED / MACHINE** profile, `real-1c-818ha-521-1-machine`, with
  only `account.balance_by_analytics` mapped `CONFIRMED`. The OData metadata is `STABLE`.
- MCP error envelopes had obscured domain-specific codes as generic `INVALID_ARGUMENT`;
  the operator should read audit `detail_code` before proposing any waiver or role change.

`payable.balance` and `payable.open_items` must not be made VALIDATED by changing status,
reusing the 521.1 profile, turning off security, or fabricating native UI evidence.

## Live read-only verification (2026-10-09)

For `818HA_test_ready`, 31.08.2026 23:59:59 +03:
- 15 account-analytics rows, `truncated = false`, 10 distinct counterparty GUIDs.
- 10/10 names resolved through an authorized `onec_read` call.
- 521.1 gross credit: **638948.76** (currency code not independently verified).
- 521.1 gross debit: **15899.09**.
- Gateway provenance: `evidence_level=PROFILE_VALIDATED_MACHINE`,
  `native_reconciliation=MACHINE_TWO_SOURCE`, no native sign-off inferred.
The above are historical testbed observations, not hardcoded product values or fixture data.

## Proper completion of the other two semantic tools

- **`payable_balance`**: choose the confirmed 1C register/virtual table and **company +
  counterparty + contract + currency** columns, verify all opening balances and period logic,
  create an exact mapping and run approved reconciliation evidence against native 1C reports.
- **`payable_aging`**: confirm document-level open items and allocations, due-date semantics,
  partially paid invoices, unapplied advances, multiple currencies and snapshot completeness.
  Aging buckets must reconcile to independently verified open-item totals. If no such source
  is proven, return `SEMANTIC_PROFILE_UNVALIDATED` with a remediation reason.
- **User-facing errors**: distinguish schema/capability unavailability, missing exact profile,
  invalid date-time offset and genuine transport errors, while keeping private DB errors hidden.
- **Production**: validate the intended live base, accountant reports and controls before
  directing these tools to a non-clone source.

## Review remediation — 2026-10-09

One independent review sweep on the first PR head identified five findings,
all addressed in the same bounded follow-up:
- **P1 trace:** frozen requirement `HYB-1` and related FR/NFR IDs explicitly map
  to DoD gates above; no new product scope or premature D9/production closure.
- **P2 filter size:** exact GUID-name lookups are split into independently audited
  batches that never exceed the configured `max_filter_chars`.
- **P2 response envelopes:** sidecar `page` flags are honored; direct OData/Atom
  responses without `page` use the strictly bounded `top = requested refs + 1`.
  No truncated name result is labelled complete.
- **P2 GUID case:** returned catalog references are canonicalized with UUID parsing
  and checked against the exact requested set; unrequested/invalid refs fail closed.
- **P2 combined response:** the complete response, not just upstream rows, must
  fit `max_response_bytes` before a success audit/return.

Tests cover 150 suppliers, pageless returns, uppercase GUIDs, malformed/unrequested
refs, mid-batch authorization revocation, and oversized combined JSON.
The preceding first-response accounting totals are not hardcoded by the feature.

## Security gate repair (2026-10-09)

The initial PR CI run failed the fail-closed security image scan, *not* accounting or
pytest: the prior pinned Chainguard Wolfi runtime carried 14 Trivy MEDIUM findings
in glibc 2.44-r7 and Python 3.14 prior to the patched 2026-10-08 build.
The tested registry manifest index was re-pinned in the Dockerfile to
`sha256:95b155651d82460ced732db7ddd81f0888267d8cc9fc97d9f0e993deac398d07`.
The local Windows/Docker build was successful; a fresh Trivy 0.75.0 vulnerability
scan of the rebuilt `erp-mcp-gateway:supplier5211-security` returned zero findings.
No severity threshold or skip/ignore policy was lowered.
Hosted image/SBOM and final PR CI remain separately required.

## Regression checks

```powershell
$env:PYTHONPATH = 'D:\Repo\ERP_MCP-supplier-debt-report\src'
D:\Repo\ERP_MCP-integration-candidate\.venv\Scripts\python.exe -m pytest -q tests/test_supplier_debt_summary.py tests/test_supplier_debt_mcp_integration.py tests/test_analytics_balance_routing.py tests/test_server_audit.py
```

Verify data controls: exact account-only scope, company ACL, extra raw catalog ACL+durable audit,
no cross-currency sum, null contract tolerated, no total on truncated page, no amount inflation.
MCP code changes require deployment/restart and server tool discovery on the target integration,
not merely a local green test.
