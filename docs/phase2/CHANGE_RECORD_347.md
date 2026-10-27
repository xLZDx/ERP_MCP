# Change Record 347 — mechanical ruff autofixes in the S13 private-writer source

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `src/erp_mcp_private_writer/` (28 files), this record and the matching log entries.

## Change

`ruff check --fix` (safe fixes only, no `--unsafe-fixes`) applied to the package. No signature or behavior
change is intended. `ct14_measure.py` (evidence-bound) was not touched.

## Verification state

- RUN: byte-compile passed; focused selection over S13, WP5, S14, writer, COM and T16 tests: 287 passed, 8 skipped, 0 failed, 128 subtests passed.
- NOT_RUN: migration harness scripts (need a disposable PostgreSQL container), review.
- Remaining findings need manual decisions and are not part of this change.
