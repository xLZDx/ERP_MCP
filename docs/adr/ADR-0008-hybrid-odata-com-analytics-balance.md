# ADR-0008 — Hybrid OData + COM read route for balances with analytics

**Status:** ACCEPTED (GPT-PM plan APPROVE `erp_mcp-integration-candidate-2026-10-07T14-18-25-002Z-789f07`, plan hash `10a152d9…13ce`)
**Date:** 2026-10-07
**Change class:** C3
**Operator decision:** 2026-10-07, hybrid OData + COM "to cover all cases". This is an explicit operator rebaseline for the COM fallback route (see §9); the tool itself traces to the frozen requirements DAD-SMALL-03, DAD-BIZ-02 and DAD-BIZ-08.

## Context

Account totals are available (`accounting_balance_and_turnovers`) but several frozen DAD requirements need balances
**by analytics** (counterparty, contract, item, warehouse): the 221/523 and 224/521 exclusivity check, supplier and
customer debt per counterparty, 211 positions per item and warehouse, reconciliation acts.

Live evidence on the real reference publication (read-only, reader identity): `AccountingRegister_Хозрасчетный` exposes
the function imports `Balance`, `ExtDimensions` and `RecordsWithExtDimensions`; `Balance(Period=…, AccountCondition=…,
Condition=…)` returns `Account_Key`, `ExtDimension1..3` with their `_Type`, split debit/credit balances and the company
dimension. An earlier audit statement that this route does not exist was wrong (only entity sets had been listed) and is
corrected in the decision log.

OData publication is not guaranteed on every client base, and a base may publish the register without the function.
ADR-0004 already says routing comes from observed capability evidence. ADR-0005 lists a COM/native-query bridge as an
approved integration boundary.

## Decision

1. A new semantic concept `account.balance_by_analytics` and a read-only MCP tool
   `accounting_balance_by_analytics(source_id, company_id, as_of)`. The account set, analytics slot meanings and field
   projection belong to the validated semantic profile, never to the caller. Capability scope is `accounting.read`.
2. **Two routes, one canonical contract.** OData (primary) and COM (fallback) return identical canonical rows and carry
   a `route` provenance field. Company scope, ACL, bounds and audit are identical on both routes.
3. **The route is decided before execution**, only from persisted evidence:

   | OData capability for the exact current metadata fingerprint | COM binding | Route |
   |---|---|---|
   | AVAILABLE (`balance` on the mapped register, live metadata evidence, same fingerprint) | any | OData |
   | proven UNSUPPORTED/ABSENT (the register is in the live profile and the method is recorded absent for the same fingerprint) | matching and approved | COM |
   | proven UNSUPPORTED/ABSENT | none/mismatch/invalid | `CAPABILITY_UNSUPPORTED` |
   | UNKNOWN (no profile, stale fingerprint, register not listed, evidence not live) or drift not acknowledged | any | fail closed, no OData business rows, no COM call |

4. **No runtime fallback.** Any error from the selected OData route (timeout, 401/403, 404, 5xx, malformed response,
   provenance mismatch, truncation anomaly) fails closed. It never switches the request to COM. "Unavailable" is not
   "unsupported".
5. The caller cannot pass or influence route, bridge id, COM path, secret reference or query text. The tool schema has
   exactly three parameters; the profile owns everything else.
6. **COM binding** (operator-approved, server-side): exact `source_id`; `binding_id` and `version`; clone/base identity;
   `configuration_fingerprint` and `metadata_fingerprint`; `source_base_url_sha256`; `credential_identity` (the source
   username secret reference); reader secret references (resolved only in the bridge, never returned); allowed
   company external references; `status`; approval instant. A change of `Source.base_url`, the source credential identity,
   the configuration fingerprint or the metadata fingerprint invalidates the binding until re-approval. A request for a
   company that the binding does not list is denied before any COM call. Audit records `selected_route`,
   binding id/version and profile fingerprint, and the route-selection reason code.
7. **The COM fallback is a separate local bridge process**, never a library inside the gateway: loopback only, bearer
   token, one fixed code-owned query template (balance of the accounting register by analytics), structured validated
   parameters only (account keys from the approved profile, as-of instant, company reference), no caller text, no write, no
   generic execute, reader identity from a secret reference, row cap, timeout, one connection per binding, sanitized
   errors. RSV `query`, `execute_query` and `reveal` stay denied (ADR-0005 and the P6 disposition are unchanged).
8. **Parity proof** (OData result equals COM result) is claimed only with: a dedicated disposable clone with an immutable
   run identity; a separate OData publication physically bound to the same clone; the COM binding on that exact clone;
   a manifest with clone identity, publication identity, metadata fingerprint and pre/post fingerprints; proof before
   comparison that both sides address the same database (the publication descriptor's infobase path is the COM clone
   path); neither side uses the reference clone. Without a separate publication the result is reported as
   **cross-copy comparison**, never as parity proof. The harness refuses a mismatched pair before reading data.

## Canonical contract

Mapping (`account.balance_by_analytics`), validated at confirmation and at runtime:

```json
{
  "entity_set": "AccountingRegister_<Name>",
  "method": "balance",
  "company_scope": {"field": "<Property>", "value_type": "guid|string"},
  "accounts": [{"code": "521.1", "account_key": "<guid>"}],
  "account_field": "Account_Key",
  "analytics": [
    {"slot": 1, "role": "counterparty", "ref_field": "ExtDimension1", "type_field": "ExtDimension1_Type",
     "expected_type": "Catalog.Контрагенты"}
  ],
  "amount_fields": {"debit": "<Property>", "credit": "<Property>"},
  "currency_field": "<Property>|null",
  "required_register_capabilities": [{"entity_set": "AccountingRegister_<Name>", "method": "balance"}]
}
```

- 1 to 16 accounts; keys are GUIDs; the code is display metadata verified by the operator when confirming.
- 1 to 3 analytics slots with roles from a fixed vocabulary (`counterparty`, `contract`, `item`, `warehouse`,
  `cash_desk`, `employee`, `bank_account`, `other`); `expected_type` is optional and, when set, a row with another type
  fails closed.
- Amounts are the **split** debit/credit balance fields (the signed `…Balance` fields place a debit balance as a
  negative credit), parsed as `Decimal`; non-finite or non-numeric values fail closed.

Canonical row: `account` (code from the profile), `account_key`, `analytics` (list of `{slot, role, ref, type}` with
`type` normalised to `Catalog.<Name>` style), `balance_debit`, `balance_credit` (decimal strings), `currency_ref`.
Response: `rows`, `row_count`, `truncated`, `as_of`, `route`, `route_reason`, profile and metadata provenance.
A row whose account is outside the approved set, or whose company dimension differs from the requested company, fails
closed (`COMPANY_SCOPE_MISMATCH` / `SOURCE_RESPONSE_INVALID`). If the source page information is absent or
inconsistent the call fails closed; a truncated page is returned with `truncated: true` and is never presented as
complete.

### Bridge wire contract (gateway client ↔ bridge)

`POST /v1/balance_by_analytics` with `Authorization: Bearer <token>` and JSON body
`{binding_id, binding_version, source_id, as_of, company_external_ref, account_keys[], max_rows}` →
`{binding_id, binding_version, source_id, base_identity:{clone_identity, metadata_fingerprint}, rows:[{account_key,
analytics:[{ref,type}×3], debit, credit, currency_ref}], truncated}`. `GET /v1/identity` returns the binding identity
without business data. The bridge holds its own binding table (id → source, version, base location, reader secret
reference, allowed companies) and refuses any request that does not match it exactly.

## Consequences

- Per-counterparty and per-item balances become available on bases with OData and on bases without it.
- A second integration boundary exists on the Windows host that must be deployed, licensed and monitored; production
  topology and licensing for 30–150 bases are **open** and documented in the runbook, not decided here.
- COM-only sources (no OData publication at all) need a source kind in the registry; that is a follow-up and is out of
  this ADR's implementation scope. This ADR covers bases that publish OData metadata and prove the function absent.
- The bridge is a new adapter family: see §9.

## What the bridge may never do

Write; execute caller text; accept a path, secret reference or user from the caller; bind to the reference clone in
tests or the parity proof; return a secret; answer for a source or company it was not bound to; be called as an
automatic fallback of an OData failure.

## 9. Scope-freeze note

`SCOPE_FREEZE_BASELINE_2026-10-06.md` freezes new adapter families. The operator's explicit decision of 2026-10-07 is the
rebaseline authority for the COM fallback of this one capability; the freeze document records it. No other scope is
added by this ADR.
