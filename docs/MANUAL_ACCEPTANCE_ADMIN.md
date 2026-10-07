# Manual acceptance — ADMIN Control Center

Version: draft for candidate `integration/1c-mvp-production-candidate`. Tested commit SHA: `____________`.
Derived from the frozen contract `docs/E2E_ACCEPTANCE_CONTRACT.md` (rows A01..A54 marked AUTO+MANUAL).
Synthetic Fake1C only. This is not native 1C reconciliation and not production approval.

This pack uses ADMIN identities only. It shares no credentials or roles with the User pack. Do not
use `user_company_one`/`user_company_two`/`user_no_access` here except where a case names the
data-plane user explicitly (A05, A33, A37, A42).

## 0. Start the environment in bootstrap-only state

```powershell
Set-Location D:\Repo\ERP_MCP-integration-candidate
powershell -File scripts\e2e\down.ps1 -Purge
powershell -File scripts\e2e\up.ps1 -Seed bootstrap-only
powershell -File scripts\e2e\status.ps1
```

Expected: all components healthy, exit 0, and exactly ONE platform binding (`platform_admin` as
PLATFORM_ADMIN). There is no source, company or grant yet: you create them in this suite.

Open the Admin UI in a normal browser (new profile or private window): `http://127.0.0.1:18000/admin/`.
Passwords of the test identities are in `.e2e\credentials.json` (local file; never paste elsewhere).

| Identity (IdP user) | Role you will give it during the suite |
|---|---|
| `platform_admin` | PLATFORM_ADMIN (already bound) |
| `source_admin` | SOURCE_ADMIN for `fake1c-e2e` only (A34) |
| `access_admin` | ACCESS_ADMIN (A34) |
| `profile_admin` | PROFILE_ADMIN (A34) |
| `auditor` | AUDITOR (A34) |
| `admin_no_role` | none |
| `user_company_one` | data-plane user only (never an admin) |

Important: ERP_MCP does not create IdP users. They already exist in the test IdP; ERP_MCP only binds
subjects/groups to roles and grants.

How to record: result sheet in section 3. Record HTTP status/UI state, request id, audit event id.

## 1. Cases (run in this order; each depends on earlier setup)

### A02 / A11 / A05 — Denials first
- Do: open `/admin/` without logging in. Expect: redirected to login, no admin data. [ ] PASS [ ] FAIL
- Do: log in as `admin_no_role`. Expect: denied page, no menus/data. [ ] PASS [ ] FAIL
- Do: log in as `user_company_one`. Expect: denied (no Admin access for data-plane users). [ ] PASS [ ] FAIL
- Forbidden: any admin data visible. Evidence: screenshot + request id.

### A01 — Login and logout
- Do: log in as `platform_admin`; open `/admin/v1/me`.
- Expect: subject `platform_admin`, role PLATFORM_ADMIN.
- Do: sign out, then press browser Back and reload `/admin/v1/me`.
- Expect: no data (401/redirect). Forbidden: any admin data after sign-out. [ ] PASS [ ] FAIL

### A15 — No tokens in browser storage
- Do (logged in): browser developer tools → Application → Local Storage and Session Storage for `127.0.0.1:18000`.
- Expect: no access/refresh/id token strings; the session cookie is marked HttpOnly.
- Forbidden: any `eyJ…` token in storage. [ ] PASS [ ] FAIL

### A16–A21 — Source onboarding (as `platform_admin`)
- A16 Do: Sources → Probe, URL `http://127.0.0.1:18766/odata/standard.odata`. Expect: safe capability summary. [ ] PASS [ ] FAIL
- A17 Do: register source id `fake1c-e2e` with that URL and the secret references shown in the form. Expect: created. [ ] PASS [ ] FAIL
- A18 Do: try URL `http://user:pass@127.0.0.1:18766/odata/standard.odata`. Expect: rejected. [ ] PASS [ ] FAIL
- A19 Do: try URL `http://example.com/odata`. Expect: rejected (host not allowed). [ ] PASS [ ] FAIL
- A21 Do: register with a secret reference that does not exist. Expect: rejected / fails closed, message does not show any secret. [ ] PASS [ ] FAIL
- Forbidden for all: a credential value anywhere on screen. Evidence: request ids, audit event ids.

### A23–A26 — Companies
- A23 Do: register `Synthetic Company One`, id `00000000-0000-0000-0000-000000000001`, source `fake1c-e2e`. Expect: created. [ ] PASS [ ] FAIL
- A24 Do: register `Synthetic Company Two`, id `…0002`, same source. Expect: created. [ ] PASS [ ] FAIL
- A25 Do: register a company with a source id that does not match the external reference's source. Expect: rejected. [ ] PASS [ ] FAIL
- A26 Do: register a third company reusing company one's external reference. Expect: a clear, deterministic refusal (same message every time). [ ] PASS [ ] FAIL

### A34 / A35 / A37 — Platform roles
- A34 Do: bind `source_admin` as SOURCE_ADMIN for `fake1c-e2e`; `access_admin` as ACCESS_ADMIN; `profile_admin` as PROFILE_ADMIN; `auditor` as AUDITOR. Expect: each binding listed. [ ] PASS [ ] FAIL
- A35 Do: repeat a role binding while logged in WITHOUT step-up. Expect: the UI demands re-authentication with the step-up level; after step-up it succeeds. Forbidden: success without step-up. [ ] PASS [ ] FAIL
- A37 Do: confirm in the data-plane (User pack U07) that giving `user_company_one` any admin role did NOT grant data access. Expect: no data access appears from a role alone. [ ] PASS [ ] FAIL

### A07–A10, A12 — Role separation (log in as each identity)
- `source_admin`: can edit `fake1c-e2e` only. Try another source id/object id → denied, no change (A07, A12). [ ] PASS [ ] FAIL
- `access_admin`: can create/revoke grants; sources/profiles/roles → 403 (A08). [ ] PASS [ ] FAIL
- `profile_admin`: can work on profiles; grants/sources → 403 (A09). [ ] PASS [ ] FAIL
- `auditor`: read-only everywhere; any mutation → 403 (A10). [ ] PASS [ ] FAIL

### A27–A33, A42 — Grants (as `access_admin`)
- A27 Do: create a subject grant for `user_company_one` on `fake1c-e2e`. Expect: created. [ ] PASS [ ] FAIL
- A28 Do: create a group grant for the company-two readers group. Expect: created. [ ] PASS [ ] FAIL
- A29 Do: submit the same create again with the same idempotency key. Expect: same result, no duplicate row. [ ] PASS [ ] FAIL
- A30 Do: same key with a different payload. Expect: conflict (409). [ ] PASS [ ] FAIL
- A32 Do: edit with an outdated row version (open the grant in two tabs, save in one, then the other). Expect: conflict. [ ] PASS [ ] FAIL
- A31/A33 Do: revoke the exact grant id; the user repeats a read (User pack U09). Expect: denied without any restart. [ ] PASS [ ] FAIL
- A42 Do: add an explicit deny for the same user next to an allow. Expect: user is denied (deny wins). [ ] PASS [ ] FAIL

### A14 — CSRF
- Do (developer tools): replay any mutating request without the CSRF header, then with a wrong value. Expect: both rejected, nothing changed. [ ] PASS [ ] FAIL

### A38 / A39 / A41 — Metadata and profiles (as `profile_admin`/`platform_admin`)
Note: validating a semantic profile successfully needs ten native-report references, which do not exist in this
synthetic environment. Do NOT try to make validation succeed. Only the refusals and fail-closed behavior below
are in scope; the success path is an EXTERNAL GATE (native 1C evidence).
- A38 Do: Refresh metadata for `fake1c-e2e`. Expect: fingerprint recorded. [ ] PASS [ ] FAIL
- A39 Do: `powershell -File scripts\e2e\fault.ps1 -Component fake1c -Action stop`, refresh again. Expect: failure recorded, no new fingerprint invented; then start Fake1C again. [ ] PASS [ ] FAIL
- A41 Do: reference a capability name that does not exist. Expect: rejected (fails closed). [ ] PASS [ ] FAIL

### A43 — Audit (as `auditor`)
- Do: open the audit view. Expect: rows with actor, client, action, target, reason, request/idempotency key, outcome for the steps above.
- Forbidden: tokens, secrets, raw accounting rows. [ ] PASS [ ] FAIL

### A45–A49 — Accessibility and states (as `platform_admin`)
- A45 Keyboard only (Tab/Shift+Tab/Enter/Space/Esc): reach and operate every action; no trap. [ ] PASS [ ] FAIL
- A46 Focus: visible focus ring; after a dialog closes focus returns to its trigger. [ ] PASS [ ] FAIL
- A47 Browser zoom 200%: all content/controls reachable, nothing clipped. [ ] PASS [ ] FAIL
- A48 Window about 400 px wide: usable without horizontal page scroll. [ ] PASS [ ] FAIL
- A49 Find a loading, empty, error, 403, 409 and stale state; each is distinct and not shown by colour alone. [ ] PASS [ ] FAIL

### A50–A54 — Dependency outages (disposable environment only; one at a time)
For each: stop it, use the Admin UI, expect a clear fail-closed message within about 30 seconds and no hang or
leaked internals; start it again and expect recovery without restarting the gateway.
- A50 Fake1C: `fault.ps1 -Component fake1c -Action stop|start`. [ ] PASS [ ] FAIL
- A51 Redis: `fault.ps1 -Component redis -Action stop|start`. [ ] PASS [ ] FAIL
- A52 IdP/JWKS: `fault.ps1 -Component idp -Action stop|start` (existing sessions per contract; new logins fail closed). [ ] PASS [ ] FAIL
- A54 Secret provider: follow `docs/E2E_ENVIRONMENT.md` "secret-provider failure" step. [ ] PASS [ ] FAIL
(A53, PostgreSQL stop, is automated only; do not run it manually unless the operator asks.)

## 2. Evidence and stop conditions

For every case: HTTP status, UI state, request id, audit event id, screenshot where noted. Redact tokens, passwords, names.
Stop and mark FAIL if a secret/token is visible, a mutation succeeds that must be denied, or any action touches anything outside the local disposable stack.

## 3. Result sheet (copy and fill)

| Case | PASS/FAIL | HTTP / UI state | Request id | Audit event id | Notes |
|---|---|---|---|---|---|
| A01 | | | | | |
| A02/A05/A11 | | | | | |
| A07–A10/A12 | | | | | |
| A14 | | | | | |
| A15 | | | | | |
| A16–A21 | | | | | |
| A23–A26 | | | | | |
| A27–A33/A42 | | | | | |
| A34/A35/A37 | | | | | |
| A38/A39/A41 | | | | | |
| A43 | | | | | |
| A45–A49 | | | | | |
| A50–A52/A54 | | | | | |

## 4. Teardown

```powershell
powershell -File scripts\e2e\down.ps1 -Purge
```
