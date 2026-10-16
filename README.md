# ERP_MCP Release 2 (Phase 2)

Release 2 of ERP_MCP: a living model of the 1C configuration, connectors (Google Drive
capture, 1C discovery), drift detection and purchase reconciliation. It was extracted from
the Release 1 repository (`ERP_MCP`) with the history of its own paths preserved. See
`docs/phase2/EXTRACTION_NOTE.md`.

## Status

**Release 2: NO-GO.** The repository contains a local, non-production prototype. The current
gate manifest records G0 as passed for its narrow approved scope, G1–G8 as not passed, S13 as
not started for formal entry, and production authorization as none. Local prototype evidence
does not establish real 1C behavior, deployment readiness, or release approval.

Details and the release handoff: [docs/phase2/S10_RELEASE_HANDOFF.md](docs/phase2/S10_RELEASE_HANDOFF.md).

Current local engineering is S12 Contract Freeze v2.0. GPT approved the initial synthetic scope, limited to purchase-receipt `CREATE_DRAFT`, `POST`, and `UNPOST`. Receipt-to-read-back consistency was clarified during implementation and is awaiting exact-revision GPT review; final focused tests and specialist re-reviews are in progress. This local work does not authorize real COM calls or change formal gates.

## Layout

- `src/business_ai_gateway/phase2/` - R2 modules (package name kept so imports stay stable)
- `tests/phase2/` - R2 tests
- `db/phase2/` - PostgreSQL migrations
- `docs/phase2/` - design, plans, decision records, spec bundle
- `scripts/phase2/`, `scripts/phase2_capacity_drill.py` - tooling
- `core/DECISION_LOG.md` - project decision log

## Verification and evidence

Required focused tests are authored and run by `functional-test-reviewer` and `e2e-runner`
after in-scope coding is complete. The applicable harnesses, exact revisions, commands, and
results are recorded in the linked change records and gate evidence plans. Do not treat a
process exit code alone as a passing result: `NOT_RUN`, `SKIP`, missing terminal evidence, or
an unavailable dependency is not `PASS`. A `PASS` requires explicit terminal PASS evidence
correlated to the exact revision and completed harness.

This README does not prescribe full-suite or lint commands. Required test and check work
follows the current workspace ownership rules; any work that was not run is reported as
`NOT_RUN`. The current state and remaining formal acceptance are tracked in
`docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md` and
`governance/GATE_MANIFEST.json`.
