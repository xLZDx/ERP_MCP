# Remove unused noqa comments from phase2 files (2026-10-20)

The phase2 branch added 30 `# noqa` comments for rules the project config does not enable, raising `ruff check src tests` from 5 (BASE) to 35 RUF100 findings. `ruff check src tests --fix` removed exactly the 35 unused-noqa suffixes (26 files, 35 lines changed, comments only; no code change). Result: see final run in STATE_ERPMCP.md.
