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

Independent run of `test_simulation_e2e_sql.py` passed 14/14. The separate PostgreSQL dump/restore journey passed 6/6,
including restored history and continued chain append. The full independent focused list passed 849 tests across 16 files;
`test_change_port.py` is absent, and its existing counterpart `test_change_ledger_port.py` passed 16/16. Each file ran in a
separate pytest process with a distinct basetemp; logs are under
`D:\Temp\claude\d--Repo\97a99f8c-e320-4800-a0f3-451a82795360\scratchpad`. Migration review found no BLOCKER/MAJOR.
This does not establish production or release-gate evidence.

An independent end-to-end code review found no BLOCKER/MAJOR and one MINOR: the tamper case's mismatching digest is
arbitrary rather than derived from the received wire bytes. The adjacent test comment now states that limited assertion;
the typed-payload versus wire-byte digest gap remains explicit and is not claimed closed.
