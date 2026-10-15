# Change record 024 — dump/restore container selection

## What changed

`test_change_ledger_dump_restore.py` now honors `ERP_PHASE2_TEST_CONTAINER` for the exact disposable container and verifies
that its published PostgreSQL port matches the DSN before checking cluster identity. The existing prefix-based port
discovery remains available when no explicit container is selected.

## Why

Independent verification found the test's `docker ps --filter publish=<port>` returned no match for its own running
container, despite `docker port` confirming the mapping. The error occurred before any dump/restore database work.

## Contracts and paths

The change keeps the `r2-s13-dump-*` name boundary and DSN/system-identifier equality check. It selects only the exact
container created for this verifier and does not broaden test cleanup or database ownership.

## Verification state

Harness change is implemented. The dump/restore file has not run successfully on this container selection yet; all
remaining requested files stay NOT_RUN until the independent runner resumes.
