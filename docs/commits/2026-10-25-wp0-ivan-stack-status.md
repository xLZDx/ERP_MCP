# WP0 strict-SSH Ivan stack status

## Change

Recorded a read-only status query of the named Ivan stack over the already trusted SSH host key.

## Why

Criterion 1 requires restored ERP MCP access and trusted SSH; criterion 2 requires the Ivan stack evidence to be distinguished from the unproven database/COM writer boundary.

## Evidence and limits

At 2026-10-25 00:07 Europe/Chisinau, strict SSH to `koros@100.88.71.74` ran `D:\1c\mcp\run-mcp-stack.ps1 -Action Status` and returned exit code 0 with `True` for postgres, redis, apache, proxies 8191–8193, sidecar, IdP and gateway. No service was started or restarted and no secret/config values were read. This does not correlate a configured clone/base, measure effective S13 database grants, or prove the actual COM transaction boundary. The command output is recorded in `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`.

No test, check, build, CI, migration, DB write, COM or git stage/commit/push ran.

## Affected paths

- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`
- `docs/phase2/OPERATOR_BACKLOG.md`