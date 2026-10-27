# Change Record 220 — freeze COM STA lifecycle callbacks

## What changed

- `ComStaLane` now rejects replacement or deletion of its `connect`, `disconnect`, `initialize_sta`,
  and `uninitialize_sta` callbacks after construction.
- Added qualification `S13-COM-STA-CONFIG-IMMUTABILITY-01` for mutation refusal, zero callback
  calls on refusal, and continued mutable lifecycle state.

## Why

The lane validates these callbacks at construction and relies on them to create/release one COM
connection on one STA thread. Replacing them afterward could redirect connection setup or cleanup
after the initial configuration check. Lifecycle state remains mutable because the worker needs it
for normal start, invoke, drain, and close behavior.

## Affected contracts and paths

- `src/erp_mcp_private_writer/com_sta_lane.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Evidence and verification state

`com_sta_lane.py` was already untracked before this edit. Its captured pre-edit SHA-256 was
`FCA7ADD800DA92166622A3D8A9447563C2C50F54FA28FB68D7498B0A4DEE9845`. The implementation and
qualification are source-only; tests/checks/build, Windows COM activation, database access,
staging, commit, and push were not run. Runtime qualification remains `NOT_RUN`.

Current `com_sta_lane.py` SHA-256: `225B6E45762322AFDDADBAFEA4C2650E9E4EA3DC074661B17651B58DB49CEA1C`.
Qualification prerequisite after later source closures SHA-256: `90E9C89AAF2C81DC8BDE2909471ED92AC6D251EFBB62CFFE1C8C206F45764CF6`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after code closure, functional/E2E roles qualify
callback mutation refusal alongside startup/cancellation/drain/close behavior; a Python/reliability
reviewer checks the STA cleanup and outcome-unknown boundary.
