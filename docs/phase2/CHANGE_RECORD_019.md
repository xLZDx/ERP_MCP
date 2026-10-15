# Change record 019 — isolated test-container selection

## What changed

The shared phase2 PostgreSQL harness now accepts `ERP_PHASE2_TEST_CONTAINER` to select the exact disposable container
whose PostgreSQL cluster must match `ERP_PHASE2_TEST_DSN`. The legacy default remains for existing callers.

## Why

Independent verification requires a unique `r2-s13-dump-<tag>` container and must not inspect or stop another session's
database container.

## Contracts and paths

Only `_pg_harness.container_guard`/Docker access selection changes. The harness still checks that exactly the selected
container is running and that its PostgreSQL system identifier matches the DSN before database tests proceed.

## Verification state

Source change implemented. The independent test phase has not started; the verifier was asked to pause until this update
is committed. Runtime behavior remains NOT_RUN.
