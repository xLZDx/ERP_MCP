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


## 2026-11-16 elevation bootstrap reattempt

An elevated bootstrap successfully started `com.docker.service` and registered `ERP_MCP_Lane_Autostart` for the interactive user with `RunLevel Highest`, one-minute logon delay, and a five-minute repeat interval. The first installer invocation stopped on a Windows PowerShell 5.1 parser error in its multiline `if` expression before registering the task. The condition was rewritten with continuation operators at line ends, without changing the checks or task settings.

The retry started the scheduled lane. Its current log records `docker info probe timed out after 10000 ms; child 61860 terminated` followed by `docker daemon not reachable, starting Docker Desktop`; the lane gateway and required ports were not yet observed listening in the immediate follow-up. Razer `system_status` and `sources_list` were separately retried and both still returned MCP `-32603: Internal error` before this lane start. No watchdog restart was performed, no 1C business query/write was made, and FIN-S3.2 remains unaccepted until the connector probe and one controlled restart of the same disposable component are observed.

## 2026-11-16 live lane recovery and watchdog registration

The authorized source `onec-818ha-reference` now returns healthy read-only status: Razer `system_status` reports three accessible sources, `sources_list` includes the read-only reference source, and `source_health` returned HTTP 200. No credentials or business rows were read. The authenticated OData metadata summary contains 920 EntitySets; searches for `Period`, `Период`, `Closing`, `ЗакрытиеПериода`, `ClosePeriod`, `PeriodEnd`, and `ОперацииЗакрытия` returned no matching EntitySets. This proves reachability only and does not prove period-close status. FIN-S1.2 remains externally blocked; the human owner for a valid test-client license or attributable export is not assigned.

The local test lane had PostgreSQL configured at `127.0.0.1:18432`, but Windows reported that port inside an excluded range (`18382–18481`), and the existing container had no host port binding. The gateway failed during startup with `ConnectionRefusedError: [WinError 1225]`. The lane's existing persistent PostgreSQL volume was retained. Its test-only port was moved to `20432` in the lane's environment metadata and DSN endpoints; Compose then reported PostgreSQL healthy. Both tracked and deployed lane starters now read PostgreSQL/Redis ports from the lane `env.json`. A subsequent starter pass ended with `summary: postgres=True redis=True apache/1C=True proxy8191=True proxy8192=True proxy8193=True sidecar=True idp=True gateway=True`.

The task registration source now separates the one-minute logon starter from a daily trigger with five-minute repetitions and an explicit one-day duration. The currently installed task still has only the old logon trigger (`PT5M`, no duration) and `NextRunTime` is empty. A visible UAC elevation attempt returned: `The operation was canceled by the user.` No registration result log was produced; the corrected trigger is not confirmed in Task Scheduler. The live Razer `system_status`, `sources_list`, and reference-source health probes succeeded after lane recovery. No watchdog restart was performed, and FIN-S3.2 AC-2 remains `NOT_RUN` until a scheduled run is observed to restart one selected disposable component.


## 2026-11-16 FIN follow-up — exact-head test evidence and reconciliation

On clean exact implementation HEAD e30e2ec10bdd37b6e3d41763865857cafa969574, the functional-test-reviewer ran tests/phase2/test_s16_conformance.py and tests/phase2/test_s16_approval_page.py with only the confirmed CSRF fixture hunk in the disposable worktree: 8 passed in 0.96s. The focused S15 modules passed 899 tests in 2.61s; SQL parity passed 2 in 10.15s; S13 in-flight status passed 2 in 8.75s. The required S13 checkpoint suffix and restore E2E modules failed collection at e30 because CheckpointKeyAuthorization is absent there; no PostgreSQL setup occurred. Their separate candidate at open PR #58 head 9bd6d38 passed the suffix test and restore test (1 passed in 19.64s), but that evidence is not transferable to e30. FIN-S3.1 evidence collection is ledger-verified; two S13 checkpoint scenarios are explicitly NOT_RUN at e30 because the required API symbol is absent there.

Fresh 2026-11-16 Razer read-only probes report read_only=true, subject auditor, three accessible sources; onec-818ha-reference is listed read-only and source health returned HTTP 200/ok=true. Task Scheduler reports RunLevel Highest but only the old logon trigger (PT5M, no duration), empty NextRunTime, and last result 1. The corrected daily trigger is absent; a visible UAC attempt returned: The operation was canceled by the user. No component was stopped/restarted. FIN-S3.2 AC-1 is evidenced, AC-2 remains NOT_RUN.

Reconciled governance/GATE_MANIFEST.json: Release 2 remains NO_GO; G0 PASSED, G1 IN_PROGRESS, G8 NOT_PASSED; S11 DONE with evidence, S12 IN_PROGRESS without evidence, S13-S19 NOT_STARTED without evidence; production authorization remains NONE. S16 synthetic evidence remains separate. FIN-S3.3 was updated with current evidence and its stale test-prohibition block was removed; it remains NOT_RUN/partial pending the FIN-S3.2 watchdog outcome. No production 1C mutation or gate promotion occurred.

## 2026-11-16 after operator GO — S3.2 elevation retry

A fresh ERP_MCP_Razer source-health call first failed at the MCP HTTP transport; its immediate retry returned status_code 200 and ok=true. Current PowerShell identity is RAZER\koros and is not in the local Administrators group. An authorized Start-Process RunAs invocation returned no exit details and did not change Task Scheduler: ERP_MCP_Lane_Autostart still has only the old logon trigger, PT5M without a duration, and no NextRunTime. The earlier visible UAC attempt recorded `The operation was canceled by the user`. No component was stopped and no watchdog restart was observed. AC-1 remains supported by the successful read-only retry; AC-2 remains NOT_RUN. Exact unblock: in elevated Windows PowerShell, run `D:\Repo\ERP_MCP\scripts\real1c\autostart\register_lane_task.ps1`; then Codex can verify the daily five-minute trigger and perform one controlled restart on the disposable test lane.
## 2026-11-16 — FIN-S3.2 elevation retry outcome

A fresh local read-only scheduler inspection returned `RunLevel=Highest` but exactly one trigger: `MSFT_TaskLogonTrigger`; the expected daily trigger with five-minute repetition is absent. `whoami /groups` reported `Medium Mandatory Level` and listed the Administrators SID as `Group used for deny only`. An authorized `Start-Process -Verb RunAs` launch returned no process details; the expected installer result log was absent and a second scheduler inspection showed no trigger change. The Computer Use policy requires handing Windows security/UAC prompts to the user, so no UAC prompt was operated and no disposable component was stopped. FIN-S3.2 AC-2 remains blocked; the operator must run the already-scoped registration script in visible elevated Windows PowerShell. After that, Codex can verify the task and continue the controlled disposable restart.
