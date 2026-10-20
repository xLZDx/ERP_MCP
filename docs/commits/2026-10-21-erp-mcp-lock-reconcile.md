# Reconcile uv.lock and requirements-runtime.lock after the ERP_MCP_R2 merge (2026-10-21)

## What changed
- `uv.lock`: regenerated with plain `uv lock` (no `--upgrade`, existing resolutions kept; still 96 packages). Only root-package metadata changed: runtime dependency `pyyaml`, dev extra `jsonschema`, new `testlane` extra (`mcp`, `uvicorn`), and the matching `requires-dist` entries.
- `requirements-runtime.lock`: refreshed with the documented export command (`uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements-runtime.lock`). The only difference is the `# via` annotation of `pyyaml` (now `erp-mcp` and `uvicorn`); no pins or hashes changed.

## Why
The merge of ERP_MCP_R2 added `PyYAML>=6,<7`, `jsonschema>=4,<5` (dev) and the `testlane` extra to `pyproject.toml`, but the locks were not regenerated. At ffbfb608 `uv lock --check` failed ("The lockfile at `uv.lock` needs to be updated"), which would fail the CI step "Verify exact Python runtime lock" and `uv sync --locked`.

## Verification (uv 0.12.9 local; CI pins 0.12.23)
- Before: `uv lock --check` exited with the error above.
- After: `uv lock --check` passes; the CI export to a temp file compared line by line (after the two header lines, as CI does) equals the committed `requirements-runtime.lock`.
- Not run: `uv sync`, tests, CI itself. Local uv version differs from the CI pin.
