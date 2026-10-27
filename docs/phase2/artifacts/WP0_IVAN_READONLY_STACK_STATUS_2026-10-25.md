# WP0 Ivan stack status — read-only recheck

Date: 2026-10-25. Scope: read-only SSH verification of the already-running Ivan test stack. No
service was stopped, started, restarted, or reconfigured. No credential file or secret value was
read.

## Commands and observed results

Strict-host-key SSH status command:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
```

The command returned all nine components as `True`:

```text
postgres=True
redis=True
apache=True
proxy8191=True
proxy8192=True
proxy8193=True
sidecar=True
idp=True
gateway=True
```

Read-only path listing:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -Command Get-ChildItem -LiteralPath 'D:\1c\mcp' ^| Select-Object Name,Mode,LastWriteTime"
```

The listing contained the expected `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, and
`venv` directories and stack scripts including `run-mcp-stack.ps1`. The listing is not evidence
that credentials or application configuration are valid; no such files were opened. An earlier
attempt to combine the two remote commands was rejected by the local PowerShell parser before SSH
ran; the separate strict-host-key commands above succeeded.

## Evidence boundary and next step

This proves only the point-in-time stack status command and directory listing over the trusted SSH
endpoint. It does not prove the 1C base fingerprint, configuration/platform identity, effective
`CT14Писатель` rights, COM write behavior, S13 PostgreSQL grants, or writer-boundary qualification.
Those remain pending their read-only, source-backed verification and later disposable qualification.

Accountable task owner: operator. Executor: Codex. Technical host/connection owner: Ivan stack
(`ERP_MCP_Ivan_Stack`), per `REMOTE_1C_HOST_STACK_2026-10-11.md`.
