# Change record: Record ERP MCP route recheck

## Change

- Updated the authorized source-observation row in `docs/phase2/OPERATOR_BACKLOG.md` with the read-only connector recheck performed on 2026-10-22.
- Recorded that three `erp-mcp-chatgpt` calls returned `UNAUTHORIZED` requiring reauthentication and three `ERP_MCP_REAL1` calls returned MCP `-32603: Internal error`; the third call to each was a status-only retry.
- Recorded that the available session tools have no app connect/reauth operation, so connector recovery requires app-level reauthentication or service-side route recovery.

## Why

The active autonomous task requires current evidence for source access. The earlier backlog contained only the 2026-10-17 failure observation; this recheck independently reproduced the unavailable routes without requesting business records.

## Contracts and paths

- This changes documentation only and does not change gate, manifest, authorization, or source status.
- Only safe system-status and source-list endpoints were called. No source-health, company-list, business-data, SSH, database, or 1C calls were made. No credentials or business data were read or recorded.

## Decisions

- Keep G1/G2 source observation `NOT_RUN`; connector errors do not establish source health or authorization.
- Keep the route blocked until the relevant connector/service owner restores an authorized route. Canonical records do not identify that owner.
- Do not attempt to substitute permission-setting or data-read tools for the missing connect/reauth operation.

## Verification state

- Directly observed six read-only MCP calls on 2026-10-22: three `erp-mcp-chatgpt` calls returned `UNAUTHORIZED`; three `ERP_MCP_REAL1` calls returned `-32603: Internal error`. Each connector received status and source-list calls, followed by one status-only retry.
- Inspected available tool metadata and the Plugin Management skill. Available management actions cover permissions, dependencies, discovery, suggestions, and removal, but provide no connect/reauth operation for either connector. This establishes a session-tool limitation, not a permanent connector outage; app-level reauthentication remains the next step for `erp-mcp-chatgpt`.
- No tests, checks, builds, CI, migrations, SSH, database, or 1C calls, staging, or commit were performed for this documentation update. The six ERP MCP status/source-list calls above are the only external calls.

## Later correction (2026-10-22)

The operator clarified that those connected-app errors came from the wrong route for this task. Do not use `ERP_MCP_REAL1`; use the local gateway with a short-lived in-process token. A later direct local read returned `source_health.ok=true` and 15 machine-reconciled rows for the scoped 521.1 request; see `docs/phase2/artifacts/WP0_MCP_ACCESS_RECHECK_2026-10-22.md`. This does not erase the earlier connector-call observations; it supersedes their interpretation as a blocker to the approved local route. The operator is accountable; Ivan Stack is the technical owner of the remote host/connection boundary.
