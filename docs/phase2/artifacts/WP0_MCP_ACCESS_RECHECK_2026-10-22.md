# WP0 MCP connection and permission recheck

Date: 2026-10-22  
Initial scope: the first connected-app check read connector status and app-permission metadata only; it read no ERP business data, credentials, tokens, DSNs, or database keys. The later dated follow-up below separately records an authorized local gateway business read with values suppressed.

## Observed results

| Connector | `system_status` result | App permission metadata | Interpretation |
|---|---|---|---|
| `erp-mcp-chatgpt` | `UNAUTHORIZED`: the app connection requires reauthentication | App uses the default setting, `Allow low-risk actions` | Permission policy does not restore the expired/invalid app connection. Data access is not verified. |
| `ERP_MCP_REAL1` | MCP error `-32603: Internal error` | App-specific setting is `Allow all actions`; it does not ask before reading or taking action | The elevated app permission setting is not evidence of a working connector or ERP authorization. The backend error remains unresolved. |

The app-permission metadata was read with the Plugin Management permission-inspection capability. No permission setting was changed. The available tools expose no reconnect/reauthentication operation.

## Follow-up correction (2026-10-22)

The table above records the earlier connected-app route failures only. The operator clarified
that `ERP_MCP_REAL1` is the wrong route for this work and must not be used; the local gateway
is the approved path. The operator also verified Ivan's host key in `known_hosts` under
`100.88.71.74` and supplied the matching fingerprint. This turn confirmed strict SSH acceptance
with `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74` and observed all
nine `run-mcp-stack.ps1 -Action Status` components as `True`; no service was restarted.

Using the project venv, `LaneEnv.load()`, and an in-process short-lived `auditor` token, the
local MCP endpoint returned `source_health.ok=true` and a 15-row account-521.1 analytical read
for the operator-selected reference company and offset-aware cutoff. The result carried
`VALIDATED_MACHINE_RECONCILED`, `PROFILE_VALIDATED_MACHINE`, `MACHINE_TWO_SOURCE`, and
`MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. No token, row, amount, or name was printed.
A previously recorded Ivan read contained 16 rows and remains unreconciled against the local
15-row result. This is source-runtime evidence, not native accounting attestation or a G1/G2
gate pass. The operator is accountable; Ivan Stack is technical owner of the existing host/
connection boundary; Codex performed this delegated read-only execution.

Next action: after all in-scope coding, have the test roles perform and record the mapped
cross-lane comparison. Do not use `ERP_MCP_REAL1`, reauthenticate the ChatGPT connector, or
restart the verified Apache/proxies/Ivan stack as part of this path.

## Historical local lane startup observation — 2026-10-22 (superseded by the follow-up correction below)

- `docker start erpmcp-e2e-real1c-postgres-1 erpmcp-e2e-real1c-redis-1` exited 0 and returned both container names. This records the start command result only; no database health check or migration was run.
- The project startup script `scripts/e2e/fault.ps1` started the local IdP on port `21080` and gateway on port `21000`; its startup readiness checks completed. Environment variable values and credentials were not printed.
- Port `21200` was already listening. Metadata-only process inspection identified `testlane.phase2_mcp` rooted in this repository, but its executable was `C:\Python314\python.exe`, not the required `D:\Repo\ERP_MCP\.venv\Scripts\python.exe`. No duplicate was launched and the existing process was not stopped or restarted because its owner/session is unknown.
- At this earlier point in the session, the remote Ivan stack was not started because strict SSH trust had not yet been established. The later follow-up below records the operator-provided trusted identity and successful strict SSH status query; the old limitation is not current guidance. No other containers or processes were touched by the historical startup commands described here.

These historical local start results did not repair the two connected-app errors above or prove that the connected ERP data sources were available. The gateway startup readiness checks were service-start checks, not test-suite results. No schema migration, business-data query, or write was performed in that startup activity.

### Historical remaining-local-listener observation — 2026-10-22 (superseded by the follow-up correction below)

A historical read-only listener check found Apache `18088` and the three read-only proxies `8191`–`8193` not listening; the sidecar `21768` was listening. A direct attempt to launch Apache and the proxies through hidden `Start-Process` calls was rejected by the execution policy before the command ran. No Apache/proxy process was started by that attempt. No alternative wrapper or shell was used to bypass the rejection. The later operator clarification and follow-up listener check supersede this point-in-time state: Apache and proxies are already up on 8088 and 8191–8193, and must not be restarted. The earlier rejection remains historical evidence, not a current startup blocker or next action.
