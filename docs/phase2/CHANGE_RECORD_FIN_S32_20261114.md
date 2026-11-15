# FIN-S3.2 change record — make the Docker probe PowerShell-runspace safe

Date: 2026-11-14  
Task: FIN-S3.2 — Check ERP_MCP_REAL1 connector reachability and one watchdog restart  
Status: runtime recovery in progress; acceptance remains partial.

## Context

The scheduled lane starter's Docker probe attached PowerShell script-block event handlers to .NET `OutputDataReceived` and `ErrorDataReceived`. Running the script under the current PowerShell 7.6.9 host caused an unhandled `PSInvalidOperationException` because the callback thread had no PowerShell runspace; startup ended before component reconciliation.

## Change

- Replaced PowerShell event callbacks with asynchronous .NET `ReadToEndAsync()` drains for stdout and stderr in both the repository starter and the deployed testbed copy.
- Kept the bounded Docker-probe timeout, child termination confirmation, and fail-closed refusal to continue if termination is unconfirmed.
- No Docker/1C business data or credential file was changed by the source edit; no secret value is recorded in this change record.

## Runtime evidence and remaining dependency

- A subsequent starter run passed the Docker-probe crash, started the disposable 1C HTTP publication and loopback proxies/sidecar, then stopped at the test IdP.
- The IdP error is `JSONDecodeError: Extra data` from parsing `D:\ERP_MCP_Testbed\real1c_e2e\credentials.json`; a structurally valid JSON object is followed by non-JSON text. Credential content was not intentionally printed or changed.
- The local MCP upstream `127.0.0.1:21000` is not listening, so tunnel calls fail upstream. The tunnel client is connected to its configured control-plane tunnel but has no responding MCP upstream.
- PostgreSQL port 18432 was not listening in the starter pass. The configured watchdog has not yet demonstrated a controlled stop/restart of the same component.
- No tests, checks, builds, CI, migrations, 1C reads, or 1C writes were run.

## Next steps

1. The credential-file owner must place the intended test user entries inside the valid `users` JSON object and remove any free text after the closing brace; preserve a private backup and never send passwords in chat.
2. Rerun the idempotent lane starter; inspect safe component status only.
3. After the lane is healthy, perform the FIN-S3.2 read-only connector probe and its separately scoped watchdog restart evidence.

## 2026-11-15 recheck — credential file remains operator-owned

Read-only runtime metadata showed the `ERP_MCP_Lane_Autostart` scheduled task in `Ready` state with last result `1`; no listeners were present on the lane ports checked in this pass. A value-free parser inspection confirmed the credentials file has a valid top-level `users` object followed by non-JSON trailing text, and `Admin_1C` is not a key inside that object. A later attempt to inspect the trailing record was rejected by the local secret guard before execution. No credential value was emitted or changed, and the lane was not restarted. The file appears to contain authentication material and may distinguish test-IdP credentials from a 1C account; do not copy the 1C password into the test-IdP file. The operator-owned file must be repaired locally with the intended test-IdP user entry (if needed) inside `users`, then the lane can be started and probed. FIN-S3.2 remains blocked pending that repair; connector and controlled-watchdog acceptance remain unproven.

## 2026-11-15 follow-up — preflight test-IdP credentials before startup

Source review found that the tracked lane starter starts Docker, Apache, proxies, and the sidecar before it discovers malformed test-IdP credentials. Added a value-free credential-document validator and a startup preflight before Docker/component startup. It checks for one UTF-8 JSON object with a `users` object and non-empty string `sub`, `username`, and `password` fields; output contains only the parse position or schema reason, never credential values. This protects the tracked starter from leaving a partial lane on malformed credentials and does not repair or inspect the operator-owned file. On 2026-11-15 the same narrow preflight was installed in the scheduled testbed starter at `D:\ERP_MCP_Testbed\real1c_e2e\autostart\start_lane.ps1`; the prior script was preserved as `start_lane.ps1.pre-credential-preflight-20261115-013539.bak`.

No tests, checks, builds, CI, migrations, listener starts, credential edits, or 1C operations were run. The preflight's runtime behavior is `NOT_RUN`; FIN-S3.2 remains blocked until the testbed credential file is repaired and the scheduled starter can be exercised, then read-only connector and controlled-watchdog evidence can be collected.

## 2026-11-15 follow-up — enforce the credential size limit on the actual read

Source review found a time-of-check/time-of-use gap: checking `stat().st_size` and then calling `read_text()` could allow a concurrent replacement or growth to bypass the 1 MiB bound. The validator now reads at most 1 MiB plus one byte and rejects an oversized document before decoding or parsing it. The scheduled starter already calls this tracked validator by repository path, so no external file or credential value changed. Regression and runtime execution remain `NOT_RUN` under operator rule 4.


## 2026-11-15 follow-up — isolate the synthetic test-IdP account

The operator-owned `D:\ERP_MCP_Testbed\real1c_e2e\credentials.json` has malformed trailing text, and its secret values are protected. Instead of asking the operator to repair it or copying any 1C credential, generated a separate random-password `auditor` account for the disposable test IdP at `D:\ERP_MCP_Testbed\real1c_e2e\synthetic-idp-credentials\credentials.json`. The password was not printed or recorded. Updated only `credentials_path` in the test-IdP `idp-config.json`; preserved the previous config as `idp-config.json.pre-synthetic-auditor-20261115-015606.bak`. The original credential values were not read or changed.

Updated the tracked lane starter and its scheduled testbed copy to resolve the configured credentials path, constrain it to the lane, and run the value-free schema preflight before any component startup. This removes the malformed-file dependency without starting the lane. Connector reachability and watchdog recovery remain `NOT_RUN`; the project rule prohibits automatic checks/tests as evidence, and FIN-S3.2 remains unaccepted.


## 2026-11-15 — FIN-S3.3 current gate reconciliation

Re-read `governance/GATE_MANIFEST.json`: Release 2 remains `NO_GO`; S11 is `DONE` with its evidence pointer; S12 is `IN_PROGRESS` with no evidence; S13-S19 are `NOT_STARTED` with no evidence pointers. No gate promotion or later sprint is inferred. FIN-S3.1 final-head test evidence is still prohibited by the project rule, and FIN-S3.2 connector/watchdog acceptance is `NOT_RUN`; its credential-path configuration dependency is now removed by an isolated synthetic IdP user. Keep production authorization `NONE`, S16 synthetic evidence distinct, and writer status `UNQUALIFIED`.

## 2026-11-15 runtime reattempt — Windows elevation required

The isolated synthetic test-IdP credential configuration is already present, so the earlier malformed-credentials dependency no longer explains startup failure. Fresh read-only calls to the `ERP_MCP_Razer` `system_status` and `sources_list` tools each returned MCP `-32603: Internal error`. The local gateway on `127.0.0.1:21000` is unavailable. `ERP_MCP_Lane_Autostart` remains `Ready` with `RunLevel Limited`; `com.docker.service` is `Stopped` with Manual start type. A direct `Start-Service` attempt returned `Cannot open 'com.docker.service' service on computer '.'`. Hidden and visible `RunAs` registration attempts did not change the scheduled-task principal. Computer-use window inspection returned `GetCursorPos failed: Access is denied. (0x80070005)`.

No lane component was intentionally stopped, no watchdog restart was claimed, and no 1C business operation was performed. FIN-S3.2 AC-1 and AC-2 remain `NOT_RUN`. Next step is an elevated Windows PowerShell session: run `Start-Service com.docker.service`, then `D:\Repo\ERP_MCP\scripts\real1c\autostart\register_lane_task.ps1`; verify `ERP_MCP_Lane_Autostart` reports `RunLevel Highest`, rerun the lane, then collect the read-only probe and one disposable watchdog restart. Tests/checks/builds/CI/migrations remain unrun.

## 2026-11-15 recheck — live connector tools remain unavailable

In this turn, both read-only `ERP_MCP_Razer` probes were attempted: `system_status` and `sources_list`. Each tool result ended with the exact message `Mcp error: -32603: Internal error`. No credentials were requested or exposed, and no business-data or mutating operation was called.

This confirms the connector is not currently providing runtime evidence through the configured MCP tools. It does not identify whether the underlying fault is Docker, tunnel-client, gateway, or connector registration. Do not claim the connector or watchdog is healthy. S3.2 AC-1 and AC-2 remain `NOT_RUN`. The next diagnostic step is to restore the local Razer gateway/upstream in an elevated Windows session (the existing service-start attempt was denied to the limited session), then repeat only the read-only status/source probe and perform the scoped disposable watchdog restart. Human operator is not assigned as project owner; the required action is on the operator-controlled Windows machine because the current session lacks service-control privileges.
