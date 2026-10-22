# Change record: narrow the WP0 cross-base row-count discrepancy

Date: 2026-10-22
Scope: append current-turn read-only SSH and MCP comparison evidence to the WP0 access/source record.

## What changed

- Recorded a strict-host-key Ivan SSH status check and a names-only stack-directory listing.
- Repeated source-health and account 521.1 analytics reads from the local and Ivan gateways with short-lived auditor tokens held in process.
- Compared normalized row groups without emitting account amounts, names, references, or tokens. A first-pass payload digest appeared only in the agent tool output and was not copied to the repository record.
- Narrowed the mismatch from a raw 15-versus-16 row count to 10 common groups and one Ivan-only group; documented that the reason remains unknown and the bases are not reconciled.

## Why

The existing WP0 note recorded 15 local versus 16 Ivan rows but did not identify whether the difference came from changed common groups or an extra normalized group. This follow-up provides a privacy-preserving comparison of the common groups and prevents matching profile metadata from being mistaken for matching source contents.

## Contracts and paths

- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md`: current read-only observations and remaining discrepancy.
- `scripts/real1c/gateway_client.py`: in-process token and MCP client helpers.
- `src/business_ai_gateway/server.py`: source-health and account-balance MCP tools; normal gateway audit behavior.
- `src/business_ai_gateway/analytics_balance.py`: normalized row identity includes account, typed analytics references, and currency.
- `core/LESSONS_LOG.md`: lesson to compare grouped identities and aggregate amounts when raw row counts differ.

## Verification state

- Strict SSH used `BatchMode=yes` and `StrictHostKeyChecking=yes` as `koros@100.88.71.74`; status exited 0 with nine components `True`.
- Local and Ivan `source_health` returned `ok=true`; both account reads returned without MCP error. Row/profile comparisons were calculated in process; only safe counts and Boolean comparisons were emitted.
- No names, references, balances, full payloads, or access tokens were emitted or copied into repository records. A first-pass payload digest was emitted only in the agent tool output and was not retained in the repository. No 1C writes, COM writes, migrations, deployments, or service restarts were performed.
- The source difference remains unresolved; no accounting or cross-base PASS is claimed. No tests/checks/builds were run.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Technical host/connection owner: Ivan stack (`ERP_MCP_Ivan_Stack`). No individual owner for the extra data group is recorded.
- Next: after coding is complete, have the functional/E2E roles run the mapped comparison on the authorized disposable path; retain `NOT_RECONCILED` until the extra group has an evidence-backed disposition.
