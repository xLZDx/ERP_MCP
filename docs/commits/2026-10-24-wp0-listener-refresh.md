# Change record: Refresh local Phase-2 listener evidence

## What changed

- Appended timestamped strict-SSH, Ivan-stack status, and local Phase-2 MCP listener evidence to `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`.
- Added the same local-versus-remote distinction to the autonomous continuation prompt so later work does not mistake Ivan's nine-component status for the local 21200 process.

## Why

The operator's prior checkpoint identified a project-venv process on local port 21200. A fresh
status script on Ivan's SSH host lists only its nine stack components; it does not report the local
test-lane MCP. The local listener therefore needed its own current evidence and must not be
restarted just because it is absent from the remote stack status.

## Evidence and limits

- Strict SSH to `koros@100.88.71.74` succeeded with host-key checking; the read-only status script returned `True` for PostgreSQL, Redis, Apache, proxies 8191–8193, sidecar, IdP and gateway.
- Local PowerShell reported `127.0.0.1:21200`, PID `32428`, executable `C:\Python314\python.exe`; a bounded process query confirmed the command line matches `testlane.phase2_mcp` without emitting the full command line.
- The listener already existed. No process was started, restarted, or replaced. No MCP tool, database query, COM call, business-data read, test, check, migration, stage, commit, or push was performed.

## Affected paths

- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
