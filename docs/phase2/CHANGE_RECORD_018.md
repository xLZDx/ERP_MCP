# Change record 018 — synthetic SQL end-to-end scenarios

## What changed

Completed the started `tests/phase2/test_simulation_e2e_sql.py` with combined synthetic clone, reference-writer, and
PostgreSQL ledger paths. The scenarios cover all four operation kinds, receipt/digest mismatch limits, tampered bytes,
stale previews, duplicate override, kill switch, crash before and after write, unknown-outcome recovery, repair after a
failed POST, anchor-gap hold behavior, tenant isolation, and competing writers. The repository's focused dump/restore
journey remains in `test_change_ledger_dump_restore.py`; it verifies the restored ledger history and continued chaining.

## Why

The reviewed range lacked a combined bytes-to-clone-to-ledger SQL scenario. The tests document the synthetic boundary
without claiming that the 009 digest proves the wire bytes or that any real 1C system was exercised.

## Contracts and paths

Affected paths are the simulation `SimulatedOneC`, `ReferenceWriter`, synthetic generator, approval-envelope fixtures,
Ed25519 clone receipt, and the phase2 change ledger. The clone remains in-memory and deterministic; the separate dump/restore
test owns PostgreSQL database export/import coverage.

## Verification state

Scenario code is implemented. Test execution is NOT_RUN until the full coding set is frozen and the authorized focused
test agents run one file at a time on the disposable PostgreSQL container. Any runtime-unavailable scenario must retain
its exact dependency/error and remain NOT_RUN. The test does not establish production or release-gate evidence.
