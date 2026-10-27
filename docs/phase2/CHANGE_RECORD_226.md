# Change Record 226 — bind COM STA coordination primitives

## What changed

- `ComStaLane` now treats `_lock`, `_queue`, `_ready`, and `_closed` as immutable configuration references alongside connector and apartment callbacks.
- The lifecycle objects remain internally mutable: queue operations, lock state, and future completion still use their existing behavior.
- The disposable qualification criterion covers replacement/deletion refusal and no callback effects.

## Why

Replacing a lock, worker queue, or completion future after construction can detach async admission from the worker or cause startup/shutdown callers to observe a substituted signal. These references are part of the lane's trusted composition and should remain identity-stable while the worker mutates the referenced objects normally.

## Affected contracts and paths

- `src/erp_mcp_private_writer/com_sta_lane.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `core/LESSONS_LOG.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Verification state

Baseline `com_sta_lane.py` before this change: SHA-256 `225B6E45762322AFDDADBAFEA4C2650E9E4EA3DC074661B17651B58DB49CEA1C`.
Current source hash: `7530A28B5BC90D812A6BDD5D39882374D32C5823730A579EE04797702FBC13A1`.
Baseline qualification prerequisite before this change: SHA-256 `639C58B6624C3E6486D9B780E69B178CED4975BAD32195E1E1B7A7D53BB77EAF`.
Current prerequisite hash: `75968BD5834336247FC79B22AD0FA280892CE29442EBD2A909933C74B4460FE9`.

Source inspection only. Tests/checks/build, Windows STA/COM, database, migration, staging, commit and push did not run.

## Ownership and next step

Accountable owner: operator. Executor: Codex. After source coding closes, functional/E2E roles qualify stable coordination identities, normal thread-affine behavior and zero callback calls on rejected mutation; Python/reliability reviewers inspect shutdown/cancellation and lifecycle guarantees.
