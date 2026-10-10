# ERP_MCP Release 2 (Phase 2)

Standalone repository for ERP_MCP Release 2. Status: NO-GO / IMPLEMENTED_UNVERIFIED.

- Project decision log: `core/DECISION_LOG.md` (append durable decisions there; also
  `docs/phase2/DECISION_LOG.md` for Phase 2 design decisions).
- Start with `docs/phase2/README.md` and `docs/phase2/S10_RELEASE_HANDOFF.md`.
- Extraction provenance: `docs/phase2/EXTRACTION_NOTE.md`.

## Phase 2 rules (short)

- Phase 2 modules are unwired and must not import Release 1 code. Release 1 lives in a
  separate repository; do not copy it here.
- Fail closed: unknown inputs are refused, errors are safe (no secrets or DSNs in messages).
- Do not claim PASS/DONE without evidence actually observed; report missing evidence as NOT_RUN.
- Tests: `python -m pytest tests/phase2 -q --ignore=tests/phase2/_red_tmp`; lint:
  `python -m ruff check src tests`.
- All text committed to git is English.
