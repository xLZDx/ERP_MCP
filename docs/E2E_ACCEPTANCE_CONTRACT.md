# ERP_MCP E2E acceptance contract (frozen)

Status: FROZEN at the commit that introduces this file. Acceptance semantics (actor, action,
expected result, negative case, evidence, classification) must not change without a new plan
amendment approved by GPT-PM. Tests may add assertions; they may not weaken a row.

Scope: local synthetic L1 (Fake1C) behind a disposable PostgreSQL 16, Redis 7 and a test-only
OIDC provider. Nothing here is native 1C reconciliation or production evidence.

Classification: `AUTO` = executed automatically by `scripts/e2e/test.ps1`; `AUTO+MANUAL` =
automated and repeated by the owner in the manual pack; `EXTERNAL-GATE` = cannot be satisfied
locally (listed in section 4).

Common rules for every row: the data plane is exercised only through the public MCP
Streamable-HTTP endpoint with OAuth bearer tokens issued by the test IdP; the Admin plane only
through `/admin/` (browser or `/admin/v1` HTTP with the real session/CSRF), except bootstrap of
exactly one initial `PLATFORM_ADMIN` and teardown. No row may mutate 1C; the Fake1C request log
must contain only GET/HEAD. Evidence = request/correlation id plus the audit event id. No token,
secret or raw accounting payload may appear in responses beyond the contract, logs or audit.

## 1. Data-plane User cases

Identities: `user_company_one` (UC1), `user_company_two` (UC2), `user_no_access` (UNA).
Baseline seed: source `fake1c-e2e`; company one and two on that source; subject grant UC1→company
one; group grant (company-two readers group)→company two; nothing for UNA.

| ID | Actor | Action | Expected result | Negative / forbidden | Evidence | Class |
|---|---|---|---|---|---|---|
| U01 | UC1, UNA | Obtain tokens via IdP, call `system_status` | UC1 token accepted and principal equals UC1 subject; token for another audience, expired, bad signature, no token are rejected | Caller-supplied identity ignored; UC1 never appears as UC2 | correlation id, audit actor | AUTO+MANUAL |
| U02 | UC1 | `system_status`, `sources_list`, `companies_list`, `source_health` | Sources/companies listed only as granted; health reports Fake1C reachable | No secret, URL userinfo or credential reference value in output | correlation id | AUTO+MANUAL |
| U03 | UC1 | `onec_capabilities`, `onec_metadata_summary`, `onec_find_entities` live | Only synthetic fixture entities; capability result derived from observed Fake1C metadata | No guessed entity or register name | correlation id | AUTO+MANUAL |
| U04 | UC1 | `onec_read` on an allowed entity with selected fields and small `top` | Bounded rows, only requested fields | No unrelated fields; no write verb ever reaches Fake1C | Fake1C request log, audit | AUTO+MANUAL |
| U05 | UC1 | Read company one data | Company one rows returned | Never rows of company two | audit company id | AUTO+MANUAL |
| U06 | UC1, UC2 | Read company two as UC1 and as UC2 | UC2 (group grant) succeeds; UC1 denied for company two | Denial occurs before any Fake1C request | Fake1C log shows no request for denied call | AUTO+MANUAL |
| U07 | UNA | Any source/company/read tool | Denied with sanitized error | No data, no source existence oracle beyond contract | audit deny event | AUTO+MANUAL |
| U08 | UC2 | Access via group membership only | Allowed through group grant; removing UC2 from the group at the IdP (new token) denies | Stale-group token behavior documented, not widened | audit | AUTO |
| U09 | UC1 | Revoke the exact grant via Admin; repeat call | Denied without gateway restart | No cached allow beyond documented TTL | audit before/after | AUTO+MANUAL |
| U10 | UC1 | Re-grant; repeat call | Access recovers without restart | — | audit | AUTO+MANUAL |
| U11 | UC1 | `onec_read` on unsupported/nonexistent entity | Fails closed with sanitized unsupported error | No alternative entity queried (Fake1C log) | audit error event | AUTO+MANUAL |
| U12 | UC1 | Call a business tool whose capability is unconfirmed/unsupported | `CAPABILITY_UNSUPPORTED` style fail-closed | No fabricated numbers | audit | AUTO+MANUAL |
| U13 | UC1 | Request above row/response limit | Result bounded and truncation signalled as the contract specifies | Unbounded response | response size assertion | AUTO+MANUAL |
| U14 | UC1 | Stop Fake1C, call, restart Fake1C, call | Sanitized upstream error within bounded time; recovery without gateway restart | Upstream URL/credentials in the error | audit error then success | AUTO+MANUAL |
| U15 | UC1 | Stop PostgreSQL, call, restart, call | Fail-closed per contract (no authorization decision without DB); recovery after restart | Allow-on-DB-failure | audit after recovery | AUTO |
| U16 | UC1 | Stop Redis, call, restart, call | Behavior exactly per rate-limit/cache contract (fail-closed or documented degraded); recovery | Silent bypass of limits not documented | metrics/audit | AUTO |
| U17 | UC1, UNA | Produce success, deny and error calls | Audit rows for each outcome with caller, source, tool, outcome | Tokens, credentials, accounting payloads in audit | DB read via evidence role | AUTO+MANUAL |
| U18 | UC1 | Run SC01..SC12 through the public MCP tools (Functional Tester suite) | Every L1 scenario PASS per `reports/FUNCTIONAL_TESTER_SC01_SC12.md` (SC06 as declared in Amendment A2; SC08 implemented, Amendment A1 retired for SC08) | Fixture arithmetic or internal function used as proof | FT report with commit SHA | AUTO |

## 2. Admin cases

Identities (all at the IdP): `platform_admin` (PA), `source_admin` (SA, bound to `fake1c-e2e` only),
`access_admin` (AA), `profile_admin` (PRA), `auditor` (AUD), `admin_no_role` (NR),
`user_company_one` (data-plane-only DP). Exactly one initial PA is bootstrapped; every other role
binding is created through `/admin/`.

| ID | Actor | Action | Expected | Negative / forbidden | Evidence | Class |
|---|---|---|---|---|---|---|
| A01 | PA | OIDC login, `/admin/v1/me`, logout, reuse old cookie | `me` returns PA subject/role; after logout old cookie denied | Protected data after logout | audit login/logout | AUTO+MANUAL |
| A02 | none | Call Admin API without a session | 401/redirect, no data | Any admin data | response | AUTO+MANUAL |
| A03 | PA token | Admin call with wrong audience | Denied | Acceptance of data-plane audience | audit deny | AUTO |
| A04 | PA token | Admin call without `erp_mcp:admin` scope | Denied | — | audit deny | AUTO |
| A05 | DP | Admin login/API with a data-plane-only user | Denied, no admin data | — | audit deny | AUTO+MANUAL |
| A06 | PA | Reach every admin read/write surface | Authorized | — | audit | AUTO+MANUAL |
| A07 | SA | Operate on own source; try another source | Own allowed; other source denied | Cross-source read/mutation | audit | AUTO+MANUAL |
| A08 | AA | Create/revoke grants; try source/profile/role changes | Grants allowed; others 403 | Role/profile/source mutation | audit | AUTO+MANUAL |
| A09 | PRA | Profile operations; try grants/sources | Profile allowed; others 403 | — | audit | AUTO+MANUAL |
| A10 | AUD | Read audit/sources/grants; attempt any mutation | Reads allowed; all mutations 403 | Any mutation side effect | audit | AUTO+MANUAL |
| A11 | NR | Authenticated user with no role | Denied everywhere | — | audit | AUTO+MANUAL |
| A12 | SA | Use object ids of a different source (company, grant, profile) | Denied/not found, no side effect | Existence oracle, mutation | DB unchanged | AUTO+MANUAL |
| A13 | PA | Mutation with valid CSRF | Accepted | — | audit | AUTO |
| A14 | PA | Mutation with missing/invalid CSRF | Rejected, no side effect | — | audit/none | AUTO+MANUAL |
| A15 | PA | Inspect browser storage after login | No access/refresh/id token in localStorage/sessionStorage; cookie HttpOnly | Token in JS-readable storage | browser evaluation | AUTO+MANUAL |
| A16 | PA | Probe Fake1C URL | Safe capability summary returned | Credentials in response | audit | AUTO+MANUAL |
| A17 | PA | Register Fake1C source | Source created | Plain secret stored/returned | audit, DB | AUTO+MANUAL |
| A18 | PA | Register URL with userinfo | Rejected | — | response | AUTO+MANUAL |
| A19 | PA | Register disallowed host | Rejected | Any outbound request to it | response, no egress | AUTO+MANUAL |
| A20 | PA | Register/probe URL that redirects unsafely | Rejected; redirect not followed to disallowed target | Egress to redirect target | response | AUTO |
| A21 | PA | Missing/broken secret reference | Rejected / probe fails closed | Secret value leaked in error | response | AUTO+MANUAL |
| A22 | PA | Search API responses and audit for secret values | None present | Any secret value | scan result | AUTO |
| A23 | PA | Register Synthetic Company One | Created | — | audit | AUTO+MANUAL |
| A24 | PA | Register Synthetic Company Two | Created | — | audit | AUTO+MANUAL |
| A25 | PA | Company whose source_id mismatches | Rejected | — | response | AUTO+MANUAL |
| A26 | PA | Duplicate external reference | Deterministic documented behavior (same result every time) | Silent overwrite of another company | response | AUTO+MANUAL |
| A27 | AA | Create subject grant | Created | — | audit | AUTO+MANUAL |
| A28 | AA | Create group grant | Created | — | audit | AUTO+MANUAL |
| A29 | AA | Replay same idempotency key and payload | Same semantic result, single row | Duplicate row | DB count | AUTO+MANUAL |
| A30 | AA | Same key with different payload | 409 conflict | Applying the second payload | DB unchanged | AUTO+MANUAL |
| A31 | AA | Revoke by exact grant id | Revoked | Revoking other grants | audit | AUTO+MANUAL |
| A32 | AA | Mutate with stale row version | 409 conflict | Lost update | DB unchanged | AUTO+MANUAL |
| A33 | AA, UC1 | Revoke access; data-plane call | Denied without restart | — | audit | AUTO+MANUAL |
| A34 | PA | Create/bind platform role | Bound | — | audit | AUTO+MANUAL |
| A35 | PA | Sensitive role mutation without step-up ACR | Rejected; with step-up accepted | Mutation without step-up | audit | AUTO+MANUAL |
| A36 | PA | Step-up with old `auth_time` | Rejected until fresh auth | Stale auth accepted | audit | AUTO |
| A37 | PA, UC1 | Bind a platform role to a user | Source/company ACL unchanged (role never widens data access) | Data access gained from role | data-plane denial | AUTO+MANUAL |
| A38 | PA | Refresh source metadata | Fingerprint recorded from observed metadata | — | audit | AUTO+MANUAL |
| A39 | PA | Refresh with Fake1C down/broken metadata | Failure recorded, no invented fingerprint, previous evidence preserved | Fabricated fingerprint | DB | AUTO+MANUAL |
| A40 | PRA | Validate/acknowledge a stale profile | Rejected | Stale acknowledgement accepted | audit | AUTO |
| A41 | PRA | Reference an unknown capability | Fails closed | Implicit allow | response | AUTO+MANUAL |
| A42 | AA | Add explicit deny alongside allow | Deny wins at runtime | Allow wins | data-plane denial | AUTO+MANUAL |
| A43 | AUD | Inspect admin audit for actor, client, action, target, reason, request/idempotency key, outcome | All present | Secrets/tokens/raw rows | audit view | AUTO+MANUAL |
| A44 | evidence role | Attempt UPDATE/DELETE on audit history as runtime and control roles | Permission denied | Any success | SQL error | AUTO |
| A45 | PA | Keyboard-only navigation across Admin UI | All actions reachable and operable | Keyboard trap | browser | AUTO+MANUAL |
| A46 | PA | Focus behavior (dialogs, errors, route change) | Visible focus, logical return | Lost focus | browser | AUTO+MANUAL |
| A47 | PA | 200% zoom | No loss of content/function | Clipped controls | screenshot | AUTO+MANUAL |
| A48 | PA | Narrow (~400 px) viewport | Usable without horizontal page scroll | — | screenshot | AUTO+MANUAL |
| A49 | PA | Loading, empty, error, 403, 409, stale states | Each is rendered distinctly and not by colour alone | Blank/hanging view | screenshots | AUTO+MANUAL |
| A50 | PA | Stop/restart Fake1C during Admin use | Clear failure then recovery without restart | Hang, leaked internals | audit | AUTO+MANUAL |
| A51 | PA | Stop/restart Redis | Behavior per contract, recovery | Undocumented bypass | metrics/audit | AUTO+MANUAL |
| A52 | PA | IdP/JWKS unavailable then restored | Fail-closed for new tokens, bounded latency, recovery | Accepting unverifiable tokens | audit | AUTO+MANUAL |
| A53 | PA | Stop/restart PostgreSQL (disposable env only) | Fail-closed, recovery | Mutation without audit | audit after recovery | AUTO |
| A54 | PA | Secret-provider failure then recovery | Probe/registration fails closed with sanitized error; recovery | Secret value in error | audit | AUTO+MANUAL |

## 3. Scenario matrix

SC01..SC12 are defined by `docs/QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md` section 5 and
`testbed/scenarios/accounting_scenarios.json`; U18 is satisfied only when the Functional Tester
report shows PASS for all twelve through public MCP tools at the exact code evidence SHA,
except for the declared dispositions of Amendments A1 and A2 below: SC06 EXTERNAL-GATE (A1, kept by
A2) and, until A2 takes effect, SC08 NOT IMPLEMENTED (A1; retired by A2 once approved). A declared
disposition is reported explicitly and never counted as PASS.

### Amendment A1 (2026-10-07) - SC06 and SC08 dispositions for U18

Status: PROPOSED to GPT-PM in the sprint-end review; effective only once approved. The original
row text above is kept unchanged; this amendment narrows how U18 may be reported, it does not
reclassify SC06 or SC08 as passed.

Reason: the Functional Tester proved that two of the twelve scenarios cannot reach PASS inside the
frozen scope. SC06 (`vat-mixed`): the freeze (section 3.3) allows configuration-specific VAT/tax
views only when a source/company profile is validated, and validation needs ten native report
references, so it is an EXTERNAL-GATE. SC08 (`duplicate-counterparty`): duplicate-counterparty
detection is not among the committed read-only lanes of `SCOPE_FREEZE_BASELINE_2026-10-06.md`;
adding it is scope expansion and needs an explicit operator rebaseline (then a candidate tool with
`merge_count=0`, a duplicate pair in the seed and positive/negative/isolation/audit coverage).

Amended U18 semantics, which `tests/e2e/user/test_u18_functional_tester_suite.py` enforces
exactly: SC01-SC05, SC07 and SC09-SC12 (ten scenarios) must PASS through public MCP tools at the
exact code evidence SHA; SC06 must be reported `xfail` with reason `EXTERNAL-GATE` and SC08 `xfail`
with reason `NOT IMPLEMENTED`; any other scenario that is skipped, xfailed, failed or errored fails
U18, and a SC06/SC08 that unexpectedly passes also fails U18 (the declaration must then be
retired). U18 is therefore reported as "10 of 12 PASS, 2 declared dispositions", never as 12/12.
Production readiness claims must not depend on SC06 or SC08. Retiring this amendment requires either
the operator rebaseline for SC08 and a validated profile for SC06, or an explicit operator waiver.

### Amendment A2 (2026-10-07) - SC08 implemented under the operator rebaseline

Status: PROPOSED to GPT-PM in the SC08 sprint-end review; effective only once approved. The text of
Amendment A1 above is kept unchanged as history. A2 retires only the SC08 half of A1.

Authority: the operator rebaseline of 2026-10-07 (explicit answer "implement"), recorded in
`SCOPE_FREEZE_BASELINE_2026-10-06.md` section 8.1. SC08 `duplicate-counterparty` is now delivered by
one read-only tool, `counterparty_duplicate_candidates`, whose detection semantics are frozen in
`docs/SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md`. SC06 is unchanged: it stays an EXTERNAL-GATE.

Amended U18 semantics, enforced exactly by `tests/e2e/user/test_u18_functional_tester_suite.py`:
SC01-SC05, SC07, SC08 and SC09-SC12 (eleven scenarios) must PASS through public MCP tools at the
exact code evidence SHA; SC06 must be reported `xfail` with reason `EXTERNAL-GATE`; any other
scenario that is skipped, xfailed, failed or errored fails U18, including SC08, and an SC06 that
unexpectedly passes also fails U18 (the declaration must then be retired). U18 is reported as "11 of
12 PASS, 1 declared disposition (SC06)", never as 12/12. SC08 evidence is synthetic L1 only: it never
counts as native reconciliation, and production readiness claims must not depend on it. Production
returns `SEMANTIC_PROFILE_UNVALIDATED` for the tool until an operator-validated profile exists.

## 4. EXTERNAL-GATE (never satisfied locally)

Native 1C accounting/business report reconciliation (L2/L3), authorized real accounting base and
configuration, production-like IdP/OData/secrets/RSV outage evidence, production
retention/backup/PITR/DR evidence, customer/pilot approval. RSV `reveal`, `execute_query` and
generic business query remain disabled; metadata-only native checks are the only native scope.
