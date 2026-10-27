# Change Record 217 — bound the private-writer quiescence wait

## What changed

- Added a 30-second maximum for `PrivateWriterService.barrier_wait_seconds`.
- Values above the maximum fail with the existing stable `BARRIER_TIMEOUT_INVALID` code; smaller positive values remain configurable.
- Added an exact boundary scenario to `S13-BOUND-TIMEOUT-CONFIG-01`.

## Why

The service uses this setting to bound startup recovery and quiescence waits, but previously accepted every finite positive value. A deployment typo or accidental very large value could turn the intended bounded wait into an effectively unbounded request wait. The default remains five seconds, while a 30-second ceiling allows bounded operational tuning without disabling the timeout.

## Affected contracts and paths

- `src/erp_mcp_private_writer/service.py` — service configuration validation.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — timeout boundary qualification.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` — distinction between the caller wait, retained close task, and PostgreSQL transaction deadline.

## Evidence and verification state

- `service.py` was already modified before this turn; pre-edit whole-file SHA-256: `F8DEF4DD4B910AB8894D25665C681D8AF133AFCCB35E9B250F86089345C24CEF`.
- Current `service.py` whole-file SHA-256: `368BB58B46C76A38A7D6695CCD55754BA96FE46EB312919D143F091B607583F9`.
- Current qualification prerequisite SHA-256: `10AE3114EED89507B497CFCD5A14A19D18F7F972D018DFAD7484DBF1684ECA6F`.
- Source-only. No tests/checks/build, listener startup, database operation, migration, staging, commit, or push ran. Runtime qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after code closure, functional/E2E roles must verify invalid types, non-finite values, huge integers, values above 30 seconds, and the exact accepted boundary at 30 seconds.
