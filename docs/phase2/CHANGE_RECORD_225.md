# Change Record 225 — make the S13 restart-required latch internal

## What changed

- `PrivateWriterService` now refuses ordinary reassignment of `_restart_required` after initialization.
- The fatal latch path retains its existing `_terminal_mutation_lock` serialization and uses an internal one-way assignment to set the latch.
- The disposable qualification prerequisite now requires direct mutation refusal, unchanged readiness/dependency-call counts, and a normally functioning serialized latch.

## Why

An uncertain COM outcome or authority-release failure requires this process to remain fail-stop. If a caller could clear `_restart_required`, the service could report ready or attempt later terminal mutations without a process restart, bypassing the existing serialized fatal-latch contract.

## Affected contracts and paths

- `src/erp_mcp_private_writer/service.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `core/LESSONS_LOG.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Verification state

Baseline `service.py` before this change: SHA-256 `2C684B37DDA0A3E591467D062BAAFA63432F973F6A8002FE67E07818111075A5`.
Current source hash: `ED5ABD017E1206703BB400C19B91BFA7A5C3229C6CED69E535B5240AF819F5A0`.
Baseline qualification prerequisite before this change: SHA-256 `81D7F7CE398D04CF9D669E7AC0C5709AD5D0EDE8C9448F6A3C011CB56FD9F937`.
Current prerequisite hash: `639C58B6624C3E6486D9B780E69B178CED4975BAD32195E1E1B7A7D53BB77EAF`.

Source inspection only. Tests, checks, build, database, migrations, COM, service restarts, staging, commit and push were not run.

## Ownership and next step

Accountable owner: operator. Executor: Codex. After coding closure, functional/E2E roles qualify fatal latch serialization against terminal mutation, refusal of ordinary true/false reassignment, preserved readiness closure, and dependency-call counts; Python/reliability reviewers assess the exact final source and runtime evidence.
