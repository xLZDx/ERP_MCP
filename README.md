# ERP_MCP Release 2 (Phase 2)

Release 2 of ERP_MCP: a living model of the 1C configuration, connectors (Google Drive
capture, 1C discovery), drift detection and purchase reconciliation. It was extracted from
the Release 1 repository (`ERP_MCP`) with the history of its own paths preserved. See
`docs/phase2/EXTRACTION_NOTE.md`.

## Status

**NO-GO / IMPLEMENTED_UNVERIFIED.** The code is implemented and its unit tests pass, but it
is not wired into any gateway runtime and has not been verified against a real 1C or a
production-like environment. Nothing here is released.

Details and the release handoff: [docs/phase2/S10_RELEASE_HANDOFF.md](docs/phase2/S10_RELEASE_HANDOFF.md).

## Layout

- `src/business_ai_gateway/phase2/` - R2 modules (package name kept so imports stay stable)
- `tests/phase2/` - R2 tests
- `db/phase2/` - PostgreSQL migrations
- `docs/phase2/` - design, plans, decision records, spec bundle
- `scripts/phase2/`, `scripts/phase2_capacity_drill.py` - tooling
- `core/DECISION_LOG.md` - project decision log

## Running the tests

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest tests/phase2 -q --ignore=tests/phase2/_red_tmp
.venv\Scripts\python.exe -m ruff check src tests
```

PostgreSQL integration tests are skipped unless `ERP_PHASE2_TEST_DSN` points to a disposable
database.
