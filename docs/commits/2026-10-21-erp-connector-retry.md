# ERP connector retry evidence — 2026-10-21

## Scope

- Repository: `D:\Repo\ERP_MCP`
- Base revision: `edac009`
- Operation: repeat only the read-only ERP_MCP_REAL1 status/source liveness calls after the first WP0 result.

## Observed result

- `ERP_MCP_REAL1.system_status({})` returned MCP `-32603: Internal error`.
- `ERP_MCP_REAL1.sources_list({})` returned MCP `-32603: Internal error`.
- `ERP_MCP_REAL1.source_health({source_id: "onec-818ha-reference"})` returned MCP `-32603: Internal error`.
- No accounting/business-read tool was called and no business data was received.
- The failure is at the connected tool/connector boundary. The underlying service cause is unknown.

## Change and verification state

Updated `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md` and `core/LESSONS_LOG.md` to retain the repeated result without claiming source health. No service, credentials, tokens, configuration, tests, or business data were changed or accessed. Follow-up depends on recovery of the ERP connector route; no reauthentication control is available in the tools used by this session.
