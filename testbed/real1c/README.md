# Real 1C integration target

This directory documents L2/L3 integration, but does not contain licensed 1C binaries or database
files.

## Environment variables

- `ONEC_TEST_BASE_URL` — OData root, e.g. `https://host/base/odata/standard.odata`
- `ONEC_TEST_USERNAME`
- `ONEC_TEST_PASSWORD`
- `ONEC_TEST_PLATFORM_VERSION_HINT` — optional evidence only

When `ONEC_TEST_BASE_URL` is absent, real-1C tests skip. Real-1C tests (`tests/real1c`, the L2 lane in
`scripts/real1c`) run only against the local real 1C reference clone and never against Fake1C; the L2 stand
starts no Fake1C and no fake sidecar (see `E2E_REAL1C=1` in `docs/E2E_ENVIRONMENT.md`).

## L2

Use a real file-mode 1C test base with the deterministic synthetic seed and snapshot contract.

## L3

Use a server-mode 1C test environment with the same scenario set. DBMS choice is an environment
concern; ERP_MCP must still access business objects through the supported 1C integration boundary,
not by emulating or directly querying internal 1C SQL tables.
