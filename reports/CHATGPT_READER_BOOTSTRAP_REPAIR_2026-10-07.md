# ChatGPT / 818HA reader bootstrap repair — 2026-10-07 (executed 2026-10-08)

Final verdict: **PARTIAL / BLOCKED on one operator-owned prerequisite.**

- Credential bootstrap, gateway restart, real source health, ACL, read-only mode and both OAuth audience paths: **PASS**.
- Business tools on the real source (`payable_balance`, `accounting_*`, `payable_aging`): **fail closed by design** with
  `SEMANTIC_PROFILE_UNVALIDATED`. The real source has ten `DRAFT` profiles and no `VALIDATED` one. A profile becomes
  `VALIDATED` only with at least ten genuine native 1C report captures (DB CHECK in migration 006). The captures are the
  owner's evidence and were not fabricated. This is a separate functional prerequisite, not a credential defect.

## 1. Root cause and timeline (local time, UTC+3)

| When | Event |
|---|---|
| 10-07 ~20:00-22:50 | ChatGPT plugin `ERP_MCP_REAL1` connected (OAuth, `system_status`, `sources_list`, `companies_list` PASS). Source tools failed. |
| 10-07 22:57 | Gateway on `127.0.0.1:21000` restarted by the launcher of `D:\Repo\ERP_MCP-integration-candidate` (PID 46912). `Start-E2eComponent` imported `env.ps1` but never provided `ERP_MCP_818HA_USER` / `ERP_MCP_818HA_PASSWORD`. |
| 10-07 | Gateway log: `RuntimeError: missing environment secret: ERP_MCP_818HA_USER` when the source adapter resolved its secret reference. |
| 10-08 00:0x | Launcher fixed (section 3), only the gateway restarted through `scripts\e2e\fault.ps1`. Source tools succeed. |

Root cause: the source `onec-818ha-reference` stores secret references (`ERP_MCP_818HA_USER`, `ERP_MCP_818HA_PASSWORD`) with
`BAG_SECRET_PROVIDER=env`. The reader pair was only ever present in the shell of whoever ran the lane setup, so any restart from
a clean shell lost it.

A second, different finding appeared once credentials worked: `source_health`, `onec_capabilities`, `onec_metadata_summary` and
`onec_find_entities` take no `company_id`, so `registry.require_source` demands a **source-wide** grant (`company_id IS NULL`).
`user_company_one` (the ChatGPT subject) holds a company-scoped grant only, so these four are `AccessDenied` for it by design.
`auditor` holds a source-wide grant and passes. Grants were not changed.

## 2. Files changed

| File | Reason |
|---|---|
| `scripts\e2e\_common.ps1` | Dot-sources the reader helper; the real-1C gateway launches inside `Invoke-818HAReaderEnvironment` (both variables together, process scope, restored afterwards) and inside `Invoke-WithoutAmbientSecrets`; new `Test-E2eGatewayNeedsReader`, `Assert-E2eReaderAvailable`. |
| `scripts\e2e\fault.ps1` | Runs the pre-flight before `start`/`restart` so a working gateway is never stopped when its replacement cannot start. |
| `scripts\e2e\reset.ps1` | Refuses to run on the real local 1C profile (`REAL1C_RESET_REFUSED`) because it drops the schema; it was never run. |
| `scripts\real1c\reader_environment.ps1` | Existing helper from the previous repair; unchanged (reviewed: functions only, exact lane guard, approved identity, no partial pair, redacted failures, buffers cleared). |
| `scripts\real1c\qa_reader_environment\test_gateway_launch_integration.py` | New: 7 tests for the launch wiring and 2 for the reset guard. |
| `scripts\real1c\qa_reader_environment\test_reader_environment.py` | Existing: 13 loader tests. |

Not mine and not touched: `scripts\e2e\envctl.py`, `src\business_ai_gateway\auth.py`, `src\business_ai_gateway\settings.py`,
`tests\test_auth.py` (another session's staged multi-audience OAuth work; it is the code that makes the ChatGPT audience valid).

## 3. Correct gateway startup

Run from the owning worktree `D:\Repo\ERP_MCP-integration-candidate`:

```powershell
$env:E2E_DIR  = 'D:\ERP_MCP_Testbed\real1c_e2e'
$env:E2E_REAL1C = '1'
.\scripts\e2e\fault.ps1 -Component gateway -Action restart
```

Order inside the script: (1) pre-flight runs the same validation as the launch (reference state directory, `BAG_ENVIRONMENT=test`,
`BAG_SECRET_PROVIDER=env`, no partial pair, identity `ERP_MCP_TEST_READER`, DPAPI blob readable and well formed) with an empty
action; (2) only then the gateway is stopped; (3) `Import-E2eEnv`, then the launch inside the reader scope and with unrelated
credential-looking variables hidden; (4) `/healthz` and `/readyz` are awaited. Ownership: the existing foreign-listener guard
(pid file with start time, command line and venv ancestry) stays active, nothing was killed outside the gateway. IdP (worktree
`ERP_MCP-chatgpt`), PostgreSQL, Redis, sidecar, lane proxies, the OpenAI tunnel client and cloudflared were not touched.

## 4. Secret management and security verification

- Blob `D:\secrets\erp_mcp\test_reader_password.dpapi`: exists, CurrentUser DPAPI, decrypts for `RAZER\koros`, 32 characters, no CR/LF/NUL.
  Same reader and blob as `scripts\real1c\lane_setup.py::_reader_credentials`. No password is in code, files, registry or arguments.
- Blob ACL (changed 2026-10-08 on operator GO): it granted `Authenticated Users` Modify and `Users` Read. Inheritance was removed and the file now grants only
  `RAZER\koros` Modify, `NT AUTHORITY\SYSTEM` FullControl and `BUILTIN\Administrators` FullControl; the loader still decrypts it. The previous SDDL is kept
  in the session scratch folder (`blob_acl_backup_20261008.sddl`) for rollback with `Set-Acl`/`icacls /reset`. The other secrets in that folder were not changed.
- The operator shell has `GMAIL_APP_PASSWORD`; before this fix every child inherited it. The launch now hides variables matching
  `TOKEN|SECRET|PASSW|CREDENTIAL|API_KEY|ACCESS_KEY|PRIVATE_KEY|APP_PASSWORD` that are not `BAG_*`/`E2E_*`/`FAKE*`/reader pair, and restores them.
- Leak scan (this run): 3308 files (testbed logs, chatgpt logs, `reports`, `core`, `docs`, session scratch) and every `bag.audit_events` row:
  **0 occurrences** of the reader secret. Tool errors are generic (`Error executing tool ...`); audit stores `outcome`/`detail_code` only.
- Files written: none generated. (No JSON/config was written by this fix, so the PowerShell 5.1 BOM concern did not arise; changed `.ps1` files are ASCII.)
- Not changed: 1C permissions, 1C users, OAuth plugin, tunnel, IdP.

## 5. Tests (commands run with `D:\Repo\ERP_MCP-integration-candidate\.venv`)

| Check | Result |
|---|---|
| `pytest scripts/real1c/qa_reader_environment` | 22 passed (13 loader + 7 launch wiring + 2 reset guard) |
| `pytest tests/test_auth.py` | 10 passed (2 audience-specific) |
| `pytest tests/test_auth.py tests/test_auth_jwks_http.py tests/test_admin_auth.py tests/test_secrets.py tests/test_odata_sidecar_client.py tests/test_server_audit.py` | 64 passed |
| `pytest tests` (full) | 1869 passed, 331 skipped, **1 failed** |
| the failure | `tests/test_operations_artifacts.py::test_fault_injection_and_runbook_artifacts_are_present`: `stale engineering checkpoint: implementation content changed`. The pinned implementation fingerprint no longer matches the working tree (this change plus the other session's uncommitted `src` edits). Resolved by repinning at commit time, see section 9. |
| negative, live | restart with a foreign reader identity in the environment: `ERP_READER_UNEXPECTED_IDENTITY`, gateway PID unchanged, `/healthz` 200 (never stopped) |
| repeatability, live | two real restarts, both `ready`, source tools green after each |

The 331 skips are the standing e2e skip policy (`EXTERNAL-GATE: validated profile requires native reconciliation evidence`). Skipped is not passed.

## 6. Real source and tool status (gateway `127.0.0.1:21000`, source `onec-818ha-reference`)

| Tool | Identity | Result |
|---|---|---|
| `/healthz`, `/readyz`, IdP `/healthz`, issuer discovery (local and quick tunnel) | - | 200 |
| `system_status` | `user_company_one` | OK, `read_only=true` |
| `sources_list` | `user_company_one` | OK, reference marked `real-reference`, synthetic portfolio labelled separately |
| `companies_list` | `user_company_one` | OK, `3e31afc5-351f-4f36-8074-99129fa3d911` (818 HA SRL) |
| `source_health` | `auditor` | **OK `status_code 200`** (real reader credentials in use) |
| `onec_capabilities` | `auditor` | OK, platform 8.3.27.2342, 920 entity sets, `ODATA_JSON_V3`, `SUPPORTED` |
| `onec_metadata_summary`, `onec_find_entities` | `auditor` | OK |
| the four source-level tools | `user_company_one` | `AccessDenied` (company-scoped grant only), by design |
| `payable_balance`, `accounting_balance_and_turnovers`, `accounting_posting_rows`, `accounting_balance_by_analytics`, `payable_aging` | `user_company_one` | authorised (`ACCESS_AUTHORIZED`), then **denied `SEMANTIC_PROFILE_UNVALIDATED`** |

A missing profile is reported as an error, never as a zero balance.

## 7. ChatGPT and Claude regression

- Gateway audiences: `BAG_OAUTH_AUDIENCE=http://127.0.0.1:21000/mcp` (Claude/local) and `BAG_OAUTH_ADDITIONAL_AUDIENCES` = the exact tunnel resource
  `https://tunnel-service.gateway.unified-0.internal.api.openai.org/v1/mcp/tunnel_6ac64553de90819188eaf83bc540eb7a` (ChatGPT). Signature, issuer, scope and company checks unchanged.
- IdP client `erp-mcp-chatgpt` allows both audiences; `erp-mcp-claude-desktop` the local one. Redirect URIs unchanged.
- Live, after the restart: local audience with `onec:read` = HTTP 200; foreign audience, missing `onec:read`, no token, garbage token = HTTP 401.
- Unit: audience tests pass (section 5).
- **Not proven live after the restart:** an actual ChatGPT call. A ChatGPT token for the tunnel audience can only come from the browser flow, and the
  test IdP does not mint it through the headless client. Evidence before the restart: audit shows `erp-mcp-chatgpt`/`user_company_one`, 25 events, last 2026-10-07 21:03 UTC.
  The first call from ChatGPT after recovery is the remaining live confirmation.
- Tunnel: `tunnel-client.exe --profile erp-mcp-local` (PID 34352) and the quick tunnel to the IdP (`cloudflared`) are running and untouched.

## 8. Business acceptance: «Сколько должны каждому поставщику по счёту 521.1 на 31.08.2026?»

**Through ERP_MCP (production path): BLOCKED**, `accounting_balance_by_analytics` and `payable_balance` return `SEMANTIC_PROFILE_UNVALIDATED`. This is the correct fail-closed behaviour.

**Diagnostic reconciliation (not an ERP_MCP-validated answer).** The production tool and adapter code were run against the real reference publication
(read-only GET through the lane proxy, reader credentials only in that process) with a test-harness mapping built from live keys instead of a validated profile.
Route `odata`, reason `capability_available`, 15 rows, not truncated. The supplier is the counterparty analytics; rows are per contract.

Result: 10 suppliers (counterparty analytics, 15 rows per contract), account 521.1 only, 2026-08-31T23:59:59Z. The net payable total (credit minus debit) equals the operator's established reference checkpoint: difference **0.00**. Company, account, date and direction (net = credit - debit for a liability account) are as intended. The currency reference came back empty, so the amounts are the regulated-currency balance as the register reports it; this was not compared with a native report, which is exactly what profile validation adds.

The per-supplier table (names and amounts) is business data and is kept outside Git, as the native-report runbook requires: `D:\ERP_MCP_Testbed\real1c_e2e\private_evidence\diagnostic_reconciliation\supplier_balances_521_1_2026-08-31.txt`. Do not quote it as an attested ERP_MCP answer.

## 9. Remaining blockers and limitations

1. **Operator-owned:** validate the semantic profile of `onec-818ha-reference` (>= 10 genuine native report captures reconciled by PASS cases, then the admin validation step).
   Until then the five business tools stay closed for that source. Minimum action: supply the native captures.
   The engine-report generator cannot help: its class `NATIVE_ENGINE_REPORT` never validates a profile, and it would copy the 4 GB probe clone again.
   Prepared 2026-10-08: the accountant request `docs/NATIVE_REPORT_ACCOUNTANT_REQUEST_RU.md`, private capture folders `NR-01`..`NR-11` and a `PENDING` evidence template
   under `D:\ERP_MCP_Testbed\1c\reference\native_reports\`. NR-11 (account 521.1 by counterparty and contract) is added because the ten mandatory cases do not cover account 521.
   `payable_balance` cannot be mapped on this base (no accumulation register of counterparty settlements); the supplier question is served by `accounting_balance_by_analytics`.
2. **ACL decision (deliberately not done):** granting `user_company_one` a source-wide access would expose metadata of all companies of the source, and ChatGPT needs none of those four tools for business answers. Recommendation: do not grant.
3. **Commit and pin:** the other session's four staged OAuth files (`envctl.py`, `auth.py`, `settings.py`, `test_auth.py`) are still uncommitted, so the working tree differs from the pinned fingerprint. The committed tree is consistent.
4. The OpenAI tunnel check by a real ChatGPT call after the restart (section 7).
5. Operational follow-ups, out of scope: durable HTTPS IdP instead of the Cloudflare quick tunnel.

Closed on 2026-10-08 (operator GO): `reset.ps1` now refuses to run when `E2E_REAL1C=1` (`REAL1C_RESET_REFUSED`, two tests); the reader blob ACL was tightened (section 4).

## 10. Safe rollback

Source rollback: restore `scripts\e2e\_common.ps1`, `fault.ps1`, `reset.ps1` from `git` (`git checkout -- <path>`) and delete the new test file; the gateway then
returns to launching without the reader pair (source tools fail again). Runtime rollback: `fault.ps1 -Component gateway -Action restart` with the restored scripts.
No database, grant, IdP, tunnel or 1C state was modified, so there is nothing to roll back there. The one non-code change is the blob ACL:
restore it with `icacls D:\secrets\erp_mcp\test_reader_password.dpapi /inheritance:e` (the file then inherits the folder ACL again) or `Set-Acl` from the saved SDDL.

## 11. Acceptance against the terminal conditions

| # | Condition | Status |
|---|---|---|
| 1 | Correct gateway reliably loads reader credentials | PASS (2 restarts, negative case) |
| 2 | Real source health | PASS |
| 3 | Authorised real data reads | PASS for source/metadata tools (`auditor`); company tools authorised but blocked by the profile |
| 4 | Read-only and ACL enforced | PASS (`read_only=true`, company-scoped denial observed, no write path used) |
| 5 | ChatGPT and local audience paths | PASS for gateway acceptance and negatives; live ChatGPT call pending |
| 6 | Financial tools produce attributable output or a verified blocker | Blocker verified and recorded: `SEMANTIC_PROFILE_UNVALIDATED` (10 DRAFT profiles) |
| 7 | Final business query through ERP_MCP | BLOCKED (diagnostic figures in section 8 only) |
| 8 | Restart and recovery repeatable | PASS |
| 9 | Report records evidence and limitations | this document |
