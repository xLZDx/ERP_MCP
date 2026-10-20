# Remote 1C host (Ivan): independent test environment and MCP stack - runbook

Status date: 2026-10-11. Scope: test infrastructure for the Release 1 gateway lane. No Release 2 code runs here. Nothing in this document is production, staging, or a gate pass.

## 1. What this is

A second Windows machine (the 1C host, named "Ivan") that holds its own copy of the 1C platform, a copy of the lane test base, and a full copy of the Release 1 MCP stack. It is reachable from:

- Claude Code (this operator's machine) over Tailscale: `http://100.88.71.74:21000/mcp`, MCP server name `erp-mcp-ivan`.
- ChatGPT over an OpenAI Secure MCP Tunnel (`erp-mcp-ivan`), with OAuth against a test IdP that is published through Tailscale Funnel.

```text
Claude Code ---- Tailscale (100.88.71.74:21000) ----------------------+
                                                                     v
ChatGPT --> OpenAI tunnel --> tunnel-client (Ivan) --> gateway :21000 --> sidecar :21768 --> proxies :8191-8193 --> Apache :8088 --> 1C file base
   |                                                       ^ JWKS (loopback)
   +--> browser login --> https://ivan.tail08f9f9.ts.net (Tailscale Funnel, port 443) --> test IdP :21080
```

## 2. Operator-reported result

On 2026-10-11 the operator reported that the ChatGPT connector was created and that everything works, and pasted ChatGPT's own result of two calls through the connector: `system_status` PASS (read-only true, user `auditor`, 3 sources visible, row limit 200, adapters `ODATA_JSON_V3`, `ODATA_ATOM_V3`, `HTTP_QUERY_FALLBACK`; the payload's mode label reads `1c-production`, which is the gateway's own string and not evidence that production data is involved) and `sources_list` PASS (`onec-818ha-down`, `onec-818ha-drift`, `onec-818ha-reference`, all read-only). That ChatGPT output is the operator-supplied evidence for the ChatGPT path; the assistant did not independently see the ChatGPT login or those calls, and ChatGPT itself noted that the two calls prove the control methods, not data access per source.

What the assistant observed on the host: tunnel-client connected to the control plane, `/readyz` 200, OAuth discovery through the tunnel succeeded (harpoon request to the protected-resource metadata returned 200), MCP commands were forwarded on the main channel after the connector was created, and all supported data tools answered through Tailscale (section 9). Not yet exercised through ChatGPT: the data tools (`accounting_balance_by_analytics` etc.).

## 3. Channel and process model

- Tailscale (`100.88.71.74`, MagicDNS `ivan.tail08f9f9.ts.net`) plus key-only OpenSSH (`BatchMode=yes`); the existing trading-assistant project already uses the same host and account.
- The OpenSSH session is elevated, and child processes of an SSH session die with it. Long-lived processes therefore start from the scheduled task `ERP_MCP_Ivan_Stack` (logon + 1 minute, repeated hourly, idempotent, interactive logon of the same user). To start it by hand: `schtasks /run /tn ERP_MCP_Ivan_Stack`.
- PostgreSQL refuses to run with administrator rights; it is started through `pg_ctl` (restricted token) by `setup-mcp-data.ps1`.

## 4. Layout on the host (all under `D:\1c`; no Windows services, no PATH change; the only machine-wide change is the COM registration)

| Path | Content |
| --- | --- |
| `env\1cv8_x64\8.3.27.2342` | copy of the local per-user 1C platform; `comcntr.dll` registered with `regsvr32` |
| `env\bases\818HA_test_ready` | copy of the lane test base clone |
| `env\apache24`, `env\odata\erp_mcp_ref` | Apache with the 1C web extension and the OData publication |
| `mcp\runtime` | portable Node 24, PostgreSQL 16.9, Redis 5.0.14.1 |
| `mcp\app\gateway`, `mcp\app\sidecar`, `mcp\venv` | gateway source (Release 1 commit `ea4defa`), OData sidecar, Python 3.13 venv from the hash-locked runtime requirements |
| `mcp\tunnel` | `tunnel-client.exe` and `cloudflared.exe` (OpenAI v0.0.16 bundle) |
| `mcp\env` | secrets and config; ACL restricted to the current user and Administrators |
| `mcp\logs` | component logs (`stack.log`, `gateway.err.log`, `tunnel.err.log`, ...) |

Ports: PostgreSQL 18432, Redis 19379, Apache 8088, lane proxies 8191-8193, sidecar 21768, IdP 21080 (loopback only), tunnel-client health 21090 (loopback), gateway 21000 (bound to the Tailscale address). Funnel publishes only the IdP: `https://ivan.tail08f9f9.ts.net` (port 443) to `127.0.0.1:21080`.

## 5. Secrets inventory (names only, never values)

| Secret | Where it lives | Notes |
| --- | --- | --- |
| 1C read-only reader password | `mcp\env\test_reader_password.dpapi` and `D:\1c\secrets` | CurrentUser DPAPI; decrypted in-process by the stack task into the gateway environment only |
| OpenAI runtime API key (tunnel) | `mcp\env\tunnel_api_key.dpapi` | CurrentUser DPAPI; decrypted in-process by `run-tunnel.ps1` |
| Tunnel id | `mcp\env\tunnel.json` | not secret |
| Gateway env, IdP config, IdP signing key, redis.conf, role hashes | `mcp\env` | test-lane values copied from the operator's lane; ACL restricted |
| Claude long-lived test token | operator's Claude Code config (`erp-mcp-ivan`) | bound to issuer and audience; re-mint after any issuer change |

A DPAPI blob opens only for the same Windows user on the same machine. It must be created on the host that uses it.

## 6. Applying and operating

Scripts live in `scripts/remote/` of this repository. Run them on the host with `powershell -NoProfile -ExecutionPolicy Bypass -File <script>` (the default execution policy blocks `.ps1`).

| Task | How |
| --- | --- |
| Read-only host discovery | `discover-host.ps1 -OutFile <path>` (pass `-OutFile` explicitly) |
| Verify the 1C copy and COM class | `verify-1c-env.ps1` |
| Publish the base over OData (Apache) | `setup-1c-odata.ps1 -BaseName 818HA_test_ready -Alias erp_mcp_ref` |
| Install portable runtimes | `install-mcp-runtimes.ps1` |
| PostgreSQL / Redis init, start, restore | `setup-mcp-data.ps1 -Action Init|Start|Restore|Status|Stop` |
| Python venv | `setup-mcp-venv.ps1` |
| Start or check the whole stack | `run-mcp-stack.ps1 -Action Start|Status` (also what the scheduled task runs) |
| Register the scheduled task and lock the ACL | `register-stack-task.ps1` |
| Store the tunnel id and key | `set-tunnel-secret.ps1` (interactive hidden prompt, or `-TunnelId <id> -FromStdin` when a caller pipes the key over SSH) |
| Run or check the OpenAI tunnel client | `run-tunnel.ps1 -Action Doctor|Run` |
| Mint a long-lived test token | `mint-token.ps1` (writes only the token to stdout; the caller must not echo it) |
| Prove the 1C reader and OData | `store-and-test-reader.ps1 -SkipStore -Url <odata $metadata url>` |

Typical operations:

- Status: `run-mcp-stack.ps1 -Action Status` should show every component `True`.
- Restart one component: stop its process (it is found by its listening port), then `schtasks /run /tn ERP_MCP_Ivan_Stack`; the stack script starts only what is down.
- Redeploy gateway code: extract the new commit into `mcp\app\gateway` (note below), restart the gateway, run the tool probe.
- Re-issue the Claude token (after any issuer or audience change): run `mint-token.ps1` on the host, register the output with `claude mcp add-json erp-mcp-ivan ... --scope user`.
- Rotate the tunnel key: create a new runtime key in the OpenAI console, revoke the old one, run `set-tunnel-secret.ps1` again, restart tunnel-client.

## 7. Connector setup (ChatGPT)

Values below are not secrets. The login password for the test user is kept in a private file on the operator machine and is not recorded here.

| Field | Value |
| --- | --- |
| Connection | Tunnel, tunnel id stored in `mcp\env\tunnel.json` (name `erp-mcp-ivan`) |
| Authentication | OAuth, registration method "User-Defined OAuth Client" (the IdP has no dynamic client registration) |
| OAuth client ID | `erp-mcp-chatgpt` (public client, no secret) |
| Token endpoint auth method | `none`, PKCE `S256` |
| Authorization / token URL | `https://ivan.tail08f9f9.ts.net/realms/erp-mcp-test/protocol/openid-connect/auth` and `.../token` |
| Scopes | `openid profile onec:read` |
| Audience | `https://tunnel-service.gateway.unified-0.internal.api.openai.org/v1/mcp/<tunnel id>` (accepted by the gateway through `BAG_OAUTH_ADDITIONAL_AUDIENCES` and listed in the IdP client) |
| Redirect URIs known to the IdP client | `https://chatgpt.com/connector_platform_oauth_redirect` and the connector-specific `https://chatgpt.com/connector/oauth/<id>` shown by ChatGPT |

## 8. State transfer (how the host was seeded)

The lane database (source registry with secret references, capabilities, grants, profiles) was moved with `pg_dumpall --roles-only` and `pg_dump` from the local lane container and restored into the portable PostgreSQL. The dump holds no 1C passwords, only secret reference names; role password hashes are the lane's test hashes. The 1C reader password was re-protected with DPAPI on the host.

Lessons from the seeding (each cost a failed attempt):

- A newer `pg_dump` writes `\restrict` / `\unrestrict` meta-commands that psql 16.9 rejects; strip them.
- The dump's `LOCALE_PROVIDER = libc LOCALE = 'en_US.utf8'` is invalid for the Windows build; remove it from `CREATE DATABASE`.
- With `--auth-host=scram-sha-256` the superuser has no password; the restore step briefly adds a loopback `trust` line for `postgres` and restores `pg_hba.conf` afterwards (`setup-mcp-data.ps1 -Action Restore`).
- `git archive` applies the checkout line-ending conversion (CRLF) and breaks the SHA-256 pin of `testbed/real1c/fixtures/test_lane_profiles.json`; copy that file byte for byte from the worktree after extracting.
- The Apache publication alias must match the base URL stored in the source registry (`/erp_mcp_ref/...`).

## 9. Test-lane profile mode and what the data tools return

Release 1 commit `ea4defa` (separate local commit in the Release 1 worktree, not pushed) adds an opt-in, test-environment-only mode. It needs `BAG_ENVIRONMENT=test` and these variables together: `BAG_TEST_LANE_PROFILES_FILE`, `BAG_TEST_LANE_PROFILES_SHA256`, `BAG_TEST_LANE_UNRECONCILED_SOURCES` (set in the host's gateway env and in the local lane's `env.ps1`). Responses carry `profile_kind=TEST_LANE_UNRECONCILED`, `evidence_level=L1`, `native_reconciliation=NOT_RUN` and the warning `TEST_LANE_PROFILE_NOT_RECONCILED_NOT_NATIVE`. They are not accountant-reconciled evidence and do not move any gate. A live database profile for the same scope still wins.

| Tool | Result on this base |
| --- | --- |
| `system_status`, `sources_list`, `source_health`, `companies_list` | work |
| `accounting_balance_by_analytics` | works (machine-reconciled profile; `as_of` must carry an explicit timezone offset, e.g. `2026-08-31T23:59:59+03:00`; a bare date gives an opaque error) |
| `accounting_balance_and_turnovers`, `accounting_posting_rows`, `sales_documents`, `purchase_documents`, `counterparty_duplicate_candidates` | work under the test-lane profile (the last needed `AccumulationRegister_Продажи*` added to the source allow-list in both databases) |
| `payable_balance`, `receivable_balance`, `bank_balance`, `cash_movements`, `inventory_balance`, `inventory_movements`, aging tools | return a tool error: this base's live metadata has no matching register, so no honest mapping exists |

## 10. Troubleshooting (symptoms seen)

| Symptom | Cause and fix |
| --- | --- |
| `.ps1 cannot be loaded because running scripts is disabled` | use `-ExecutionPolicy Bypass` |
| `Execution of PostgreSQL by a user with administrative permissions is not permitted` | start through `pg_ctl` (done by `setup-mcp-data.ps1`) |
| Process dies when the SSH session ends | start it from the scheduled task, not from the session |
| OData returns 401 for the reader | the base copy lacks the reader user: use the clone that carries it (`818HA_test_ready`), not the reference copy |
| MCP tool returns only "Error executing tool ..." on a date argument | `as_of` without timezone offset |
| `SYNTHETIC_FIXTURE_PROFILES_HASH_MISMATCH` at gateway start | the pinned JSON file was altered (line endings); re-copy it byte for byte |
| `Funnel is not enabled on your tailnet` | operator enables Funnel (and HTTPS certificates) in the Tailscale admin console |
| `invalid_target: audience not permitted` when minting a token | the IdP client audiences still list another address; update `idp-config.json` and restart the IdP |
| tunnel-client: `oauth discovery: destination origin is not trusted` | pass `--mcp.oauth-trusted-origin <issuer origin>` (set in `run-tunnel.ps1`) |
| tunnel-client: `base URL must use https` and `unsupported channel "harpoon"` | the MCP target is plain http inside Tailscale; run with `--harpoon.allow-plaintext-http` (set in `run-tunnel.ps1`) |
| ChatGPT: "Some app settings were rejected" while creating the custom MCP server | observed only with the IdP on the non-standard port `:8443`; after moving the IdP to port 443 the operator could create the connector. ChatGPT's own error body was never seen, so the port is the likely, not proven, cause |
| Claude token returns 401 after an issuer change | the token is bound to the issuer and audience; mint a new one |

## 11. Security notes

- The gateway is bound to the Tailscale address and requires a bearer token; Funnel exposes only the IdP, not the gateway.
- The IdP is a test IdP with a password grant for test users; it is published publicly only because ChatGPT's OAuth flow needs a public authorization server. Do not point it at real users or a production base.
- The OpenAI runtime API key was once pasted into a PowerShell prompt and thereby into a screenshot; it was declared compromised and replaced. The old key must be revoked in the OpenAI console (operator action; not verified here). The private files that carried the new key and the connector parameters must be deleted by the operator after use.
- Nothing was written to the 1C base; all reads go through the read-only reader and the read-only gateway tools.

## 12. Open items

- Operator: revoke the exposed old OpenAI key; delete the private key file and the connector parameter sheet.
- Review and publish: three local R2 commits and the Release 1 commit `ea4defa` are not pushed; push needs a GPT-PM APPROVE on the exact head.
- A stray duplicate `scripts/remote/discover-host - Copy.ps1` was committed by mistake; remove it in a follow-up.
- The long-lived Claude token and the public IdP address are test conveniences; production would need a named domain, short-lived tokens and a real identity provider.

## 13. Real-difference reconciliation experiment (2026-10-11)

State change on the host: the OData alias `erp_mcp_ref` now points at the base `D:\1c\env\bases\818HA_p2diff`, a byte-for-byte copy of `818HA_test_ready` in which ONE posted purchase document of 2026-08 was edited on a disposable local clone (a known +100.00 on the service line, reposted; the 521.1 credit movement became 2600 instead of 2500) and the file was shipped to the host. The original publication descriptor is kept as `D:\1c\env\odata\erp_mcp_ref\default.vrd.bak-818HA_test_ready`.

- Why the clone is edited locally: the host has no 1C client license, so COM writes are possible only on the licensed local machine. The host serves the result through the Apache OData extension, which needs no client license.
- Tools: `testlane/tools/edit_purchase_on_clone.py` (refuses any path except the `818HA_p2diff` clone; dry run by default), `scripts/remote/repoint-odata-base.ps1` (repoint plus Apache restart through the stack task).
- Revert on the host: `repoint-odata-base.ps1 -BaseName 818HA_test_ready`.
- Result: side A (local reference) vs side B (host, modified) through the Phase 2 test-lane MCP: the 521.1 closing-balance comparison returns `PARTIAL_MISMATCH` / `CLOSING_VALUES_DIFFER` with exactly one difference (`ROW_MISSING_IN_A`: a credit-100 row for the edited counterparty exists only on side B); the baseline run before the edit was identical on both sides. Both sides carry the machine-reconciled labels, so this is a machine copy-consistency detection, not a native 1C PASS.
