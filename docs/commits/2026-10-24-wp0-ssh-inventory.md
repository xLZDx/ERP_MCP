# WP0 read-only strict-SSH directory inventory

## Change

Recorded a read-only inventory of the Ivan MCP stack directory after confirming strict SSH access.

## Why

The autonomous continuation requires evidence for the remote connection and accessible stack
layout without restarting services or reading credentials. A directory listing advances that
inventory but cannot prove which 1C clone is configured or establish effective grants/COM rights.

## Affected paths

- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`

## Evidence and limits

Command, from `D:\Repo\ERP_MCP`:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "cmd.exe /c dir D:\1c\mcp"
```

Exit code: `0`. The output listed directories `app`, `data`, `dl`, `env`, `logs`, `runtime`,
`tunnel`, and `venv`, plus ten files totaling 25,019 bytes, including `run-mcp-stack.ps1` and
`register-stack-task.ps1`. No file contents or credentials were read; no service was started or
restarted. This is evidence only for strict-SSH host trust, command success and directory
visibility. Clone/base identity, effective PostgreSQL and 1C grants, COM connectivity, and the
physical writer transaction boundary remain unverified. No tests, checks, build, CI, migration,
database write, staging, commit or push ran.
