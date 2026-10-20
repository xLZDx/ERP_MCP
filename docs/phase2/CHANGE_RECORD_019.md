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

The independent verifier used `ERP_PHASE2_TEST_CONTAINER` with its unique `r2-s13-dump-20261015-1505` container. Shared
harness tests passed. The dump/restore guard initially failed before DB work with Docker's publish filter, so change 024
added explicit container selection and `docker port` verification; the corrected dump/restore test passed 6/6.
