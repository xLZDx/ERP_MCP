# Functional Tester report — SC01–SC12

Candidate: `integration/1c-mvp-production-candidate`, code evidence head `8283403`
(Functional Tester worktree fast-forwarded to exactly this head; `git status` clean after the run).
Date: 2026-10-07. Suite: `tests/functional/**` (black-box, public MCP tools only).

## Evidence level — read this first

Every PASS below is **synthetic L1 evidence**. The stack is the private functional-tester stack
(`scripts/ft/setup.ps1`: PostgreSQL 16 :25432, Redis :26379, recording Fake1C :28766, fake OData
sidecar :28767, gateway :28000, dev mode). Fake1C is not a native 1C base. Business data comes from the
test-only synthetic fixture profile provider (`profile_kind=SYNTHETIC_FIXTURE`, `evidence_level=L1`,
`native_reconciliation=NOT_RUN`). Nothing here is native 1C, L2 reconciliation or production evidence.

## Result

73 passed, 3 skipped, 2 xfailed, 0 failed, 0 errors (78 tests, 202.87 s). Identical to the earlier
run at `d8f322b`. The first attempt on this head ran with no stack environment loaded and skipped all 78
tests; it is not a result for the code and was discarded (cause: the suite reads only `FT_*` variables
written by `scripts/ft/setup.ps1`).

## Scenario matrix

Columns: positive contract, wrong company denied before upstream, unsupported capability fails closed,
company isolation, request correlation and company scope in audit.

| Scenario | positive | wrong company | unsupported capability | isolation | audit |
|---|---|---|---|---|---|
| SC01 | PASS | PASS | PASS | PASS | PASS |
| SC02 | PASS | PASS | PASS | PASS | PASS |
| SC03 | PASS | PASS | PASS | PASS | PASS |
| SC04 | PASS | PASS | PASS | PASS | PASS |
| SC05 | PASS | PASS | PASS | PASS | PASS |
| SC06 | XFAIL (EXTERNAL-GATE) | PASS | PASS | n/a | PASS |
| SC07 | PASS | PASS | PASS | PASS | PASS |
| SC08 | XFAIL (NOT IMPLEMENTED) | n/a | n/a | n/a | n/a |
| SC09 | PASS | PASS | PASS | PASS | PASS |
| SC10 | PASS | PASS | PASS | PASS | PASS |
| SC11 | PASS | PASS | PASS | PASS | PASS |
| SC12 | PASS | PASS | PASS | PASS | PASS |

Additional passing tests: naive-timestamp rejection (SC01, SC10), truncated aging is INCONCLUSIVE
(`AGING_ROWS_TRUNCATED`), raw L1 cross-checks (SC11/SC05 item nets and balance register, SC12/SC09 cash
windows, SC04 unposted document has no raw ledger rows, raw read bounded by `top`), authorization and
isolation (revoked source grant denies before any upstream request and restores, company-scoped grant,
unknown source and company/source mismatch, unsupported entities fail closed, mutation surface absent),
discovery (exact reviewed read-only tool set, source and both companies listed, synthetic-only metadata,
result bounds).

## Skips and expected failures (exact dispositions)

| Test | Reason string | Disposition |
|---|---|---|
| SC06 positive (xfail) | EXTERNAL-GATE SC06 (vat-mixed): VAT/tax views exist only when a source/company profile is validated (freeze 3.3); no VAT tool or fixture profile exists | EXTERNAL-GATE: validated profile needs ten native report references. |
| SC08 positive (xfail) | NOT IMPLEMENTED SC08 (duplicate-counterparty): detection is outside the frozen scope | Needs an explicit operator scope rebaseline. Not implemented, not faked. |
| `test_oidc_identity_without_grants_is_denied` | needs-oidc-identity: set FT_BEARER_TOKEN_NO_ACCESS | The FT stack is dev mode without an IdP. The same behaviour is exercised in the OIDC E2E user suite (identity `user_no_access`). |
| `test_oidc_company_two_identity_cannot_read_company_one` | needs-oidc-identity: set FT_BEARER_TOKEN_COMPANY_TWO | Same: covered by the OIDC E2E user suite (identity `user_company_two`). |
| `test_business_capability_denied_for_identity_without_capability` | needs-oidc-identity + business-capability enforcement environment (E2E) | Same: covered by the E2E user/admin suites with enforcement enabled. |

## Upstream traffic and hygiene

Recorded after the whole run (`/__ft__/requests`):

| Recorder | Requests | Breakdown |
|---|---|---|
| Fake1C | 15 | 14 GET, 1 HEAD, 0 write verbs |
| OData sidecar | 61 | 61 POST: 57 `/v1/read`, 4 `/v1/capabilities/registers` |

Whole-run hygiene tests (4/4 PASS): only GET/HEAD reached 1C; the sidecar saw only the two read-only
protocol paths; audit rows contain no tokens, credentials or raw accounting rows; the gateway log contains
no tokens, credentials or raw accounting rows (scan ran, not skipped).

## Not verified here

OIDC and capability-enforcement paths of the FT stack (covered by the E2E suites instead), SC06 and SC08
behaviour, native reconciliation of any figure. The recorder counts are per process lifetime and were not
cross-checked against the gateway log.
