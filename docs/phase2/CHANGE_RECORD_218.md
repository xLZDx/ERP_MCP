# Change Record 218 — freeze the barrier timeout after construction

## What changed

- `PrivateWriterService` now rejects reassignment or deletion of `_barrier_wait_seconds` after initialization with `BARRIER_TIMEOUT_CONFIGURATION_IMMUTABLE`.
- Extended `S13-BOUND-TIMEOUT-CONFIG-01` to exercise replacement, deletion, and delete-then-reassign attempts.

## Why

The 30-second constructor limit would not remain effective if the timeout could be changed later. The service uses the same value for startup, quiescence, and reconciliation deadlines. Freezing this one safety configuration prevents an in-process caller from silently extending those waits while leaving the service's independent runtime state mutable.

## Affected contracts and paths

- `src/erp_mcp_private_writer/service.py` — private writer configuration invariant.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — timeout configuration qualification.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` — immutable bounded wait contract and retained mutex ownership.

## Evidence and verification state

- `service.py` was already modified before this turn. Hash before the preceding 30-second-bound edit: `F8DEF4DD4B910AB8894D25665C681D8AF133AFCCB35E9B250F86089345C24CEF`.
- Current `service.py` SHA-256: `27F95F216030067CBF65CB5D43A3503F53D2CE87BF933BCDFBE922D01A850768`.
- Current qualification prerequisite SHA-256: `3EB488E9EE42D702E1146EF28C6C7C7D0A87AF9DB86EAF35E4316073C06E6E9C`.
- Source-only. No tests/checks/build, listener startup, database operation, migration, staging, commit, or push ran. Runtime qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after code closure, functional/E2E roles verify the 30-second boundary and mutation/deletion resistance, then Python/reliability reviewers inspect the exact final source and timeout behavior.
