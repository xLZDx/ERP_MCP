# Extraction note: Release 2 split from the Release 1 repository

## Source

- Repository: `ERP_MCP` (Release 1), worktree `D:\Repo\ERP_MCP-phase2`
- Branch: `phase2/living-model-connectors-reconciliation`
- Source HEAD: `9810c292bde83949583f5e967c884aeb8ce4b8b0` (origin copy of the branch was at `88753c2`)
- Source history: 563 commits on the branch. Preserved here: 239 commits (the ones that touch
  the path set below; commits that touched nothing in the set were pruned as empty).
- Commit hashes differ from the source because history was rewritten.

## Tool and command

`git filter-repo` was not installed, so `git filter-branch` was used on a fresh
`git clone --no-local` of the source (the source worktree was never modified):

```
git filter-branch -f --prune-empty --index-filter "sh r2_index_filter.sh" -- HEAD
```

The index filter removed every tracked file not matching this keep list:

```
git ls-files -z | grep -zvE '^(<keep patterns>)' | xargs -0 -r git rm --cached -q --ignore-unmatch
```

The final repository is a fresh `git clone --no-local` of the filtered clone with the
`origin` remote removed (no `refs/original` backup refs carried over).

## Path set carried over (with history)

- `src/business_ai_gateway/phase2/`
- `src/business_ai_gateway/__init__.py` (one-line package marker, needed for the package layout)
- `tests/phase2/` (untracked `tests/phase2/_red_tmp` is not carried; it is now git-ignored)
- `db/phase2/`
- `docs/phase2/`
- `docs/PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md`
- `reports/PHASE2_*`
- `governance/DOCUMENT_REGISTRY.md` (generated; it still lists Release 1 documents, regenerate it)
- `scripts/build_document_registry.mjs`
- `scripts/phase2/`
- `scripts/phase2_capacity_drill.py` (required by `tests/phase2/test_g1_capacity_smoke.py`)
- `core/DECISION_LOG.md` (full project decision log, including Release 1 entries)

## New files (not from the source history)

`pyproject.toml`, `README.md`, `CLAUDE.md`, `.gitignore`, this note.

`pyproject.toml` keeps the source ruff settings (line length 100, py312, isort first-party) and
pytest settings (`pythonpath = [".", "src"]`, `asyncio_mode = "auto"`), and the `integration`
marker. Dependencies are reduced to what Phase 2 imports: asyncpg, defusedxml, httpx, PyYAML.

## Not carried over, and why

- All Release 1 source (`src/business_ai_gateway/*` other than `phase2/` and `__init__.py`),
  `testbed/`, `adapters/`, `vendor/`, `deploy/`, `db/migrations/`: Release 1 owns them; Phase 2
  modules do not import them (verified by grep: no Release 1 imports in `src/.../phase2`,
  `tests/phase2`, `scripts/phase2`).
- `tests/conftest.py` and `tests/sc_stack.py`: Release 1 fixtures (fake 1C, server thread);
  no Phase 2 test uses them. Phase 2 has its own `tests/phase2/conftest.py`.
- The Release 1 `pyproject.toml` markers `e2e`, `smoke`, `user`, `admin`, `functional`:
  Release 1 suites only.
- `.gitattributes` (Release 1 fake-1C fixture rules); `docs/phase2/spec-v0.1/.gitattributes` is
  carried with its directory.
- `.github/`, Docker/compose files, `uv.lock`, `requirements-runtime.lock`, other `scripts/*`,
  Release 1 docs/reports: Release 1 tooling.
- `docs/phase2/**` and `core/DECISION_LOG.md` text may still reference Release 1 paths; this
  is historical and was not edited.

## Known follow-ups

- Regenerate `governance/DOCUMENT_REGISTRY.md` for this repository.
- `core/DECISION_LOG.md` contains Release 1 history; prune only with an explicit decision.

## Verification and later additions

- Tests in this repository (source venv with PYTHONPATH=src, run on 2026-10-10): 6126 passed, 229 skipped; `ruff check src tests`: all checks passed. These are the same counts as at source head 6ee27f1 (the 229 skipped are PostgreSQL integration tests without a DSN, NOT_RUN).
- Source commits made after the clone (decision-log entries and docs/phase2/artifacts/G3_ENGINEERING_RECONCILIATION_INDEX.md, source commits 0f1ae7d, df1036c, 903eaba, 7dae655, bc25fb6) were carried over as file content, not as history.
- This repository is the new home of Release 2. The old branch in the Release 1 repository is frozen after this extraction (decision of the operator, 2026-10-10).
