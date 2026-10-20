# ERP_MCP Claude project guidance

Read `AGENTS.md` first, then `docs/DOCUMENT_INDEX.md` before implementation or architectural work.

ERP_MCP is ONE project: the read-only 1C MCP gateway (the former "Release 1") together with the
living model, connectors and reconciliation work (the former "Release 2" / "Phase 2"). There is no
separate Release 1 / Release 2 repository any more; the two lines were merged on 2026-10-20 (see
`docs/phase2/EXTRACTION_NOTE.md` for the provenance of the second line). The `phase2` directory and
package names are kept for now so that imports stay stable; renaming them is a separate refactor.

## Boundaries (gateway)

1. No mutation tools or write-capable transport paths in the production artifact.
2. No arbitrary target URLs, direct 1C SQL, secrets in source/logs/results, or caller-supplied identity.
3. Authorization and audit happen through the control plane before a data-plane call.
4. Capability routing is based on observed source behavior and metadata, not configuration names alone.
5. MIT-compatible upstream behavior should be reused with provenance; copyleft code stays isolated.

## Living model / connectors / reconciliation rules (`src/business_ai_gateway/phase2/`)

- The living-model modules are unwired from the gateway runtime and must not import gateway runtime
  code unless a documented, reviewed integration story says so.
- Fail closed: unknown inputs are refused, errors are safe (no secrets or DSNs in messages).
- Do not claim PASS/DONE without evidence actually observed; report missing evidence as NOT_RUN.
- Status: NO-GO / IMPLEMENTED_UNVERIFIED. Start with `docs/phase2/README.md` and
  `docs/phase2/S10_RELEASE_HANDOFF.md`; gate state is in `governance/GATE_MANIFEST.json`.
- Durable decisions go to `core/DECISION_LOG.md` (and `docs/phase2/DECISION_LOG.md` for design decisions);
  lessons go to `core/LESSONS_LOG.md`.
- Focused tests: `python -m pytest tests/phase2 -q --ignore=tests/phase2/_red_tmp`; lint:
  `python -m ruff check src tests`.
- All text committed to git is English.

For implementation status and known gaps, inspect the current code and the normative documents rather
than assuming that the full future architecture has already been implemented.
