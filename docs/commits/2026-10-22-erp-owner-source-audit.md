# Change record: Record ERP service ownership lookup

## Change

- Updated the authorized ERP source-observation row in `docs/phase2/OPERATOR_BACKLOG.md` to state that repository ownership sources do not identify an ERP connector/service owner.

## Why

The autonomous handoff needs a real owner for the connector reauthentication and route recovery dependency. The project requires checking canonical ownership records instead of assigning a gate, lane, or role label as a person or service owner.

## Contracts and paths

- Documentation only; no owner was invented and no external party was contacted.
- Lookup scope was this repository: searched for `CODEOWNERS`, owner/ownership/route/service registry paths, and owner/responsible fields under `governance/`.
- No `CODEOWNERS` or separate owner registry was found. The only governance path matching owner-related records was `governance/GATE_MANIFEST.json`; searching its governance documents returned no owner/responsible assignments.

## Decisions

- Keep the ERP connector/service owner as unknown in canonical records.
- The operator remains the accountable owner of delegated project closure; that does not make the operator the connector's technical owner. Codex remains executor.

## Verification state

- Read-only repository path and governance-text searches completed on 2026-10-22.
- No tests, checks, builds, CI, migrations, external communications, staging, or commits were run for this ownership lookup.

## Later correction (2026-10-22)

The operator supplied the missing technical ownership distinction: `ERP_MCP_Ivan_Stack` owns the existing Ivan host/connection boundary, while the operator is accountable for this delegated project task and Codex is executor. This does not identify a separate named human contact for future deployed-grant confirmation or the not-yet-existing private writer service. The earlier repository search remains an accurate description of what those canonical records contained at the time; it no longer supports calling the existing Ivan connection unowned.
