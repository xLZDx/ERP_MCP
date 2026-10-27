# Change Record 224 — make Windows mutex closure monotonic

## What changed

- `WindowsServingAuthorityMutex` now rejects ordinary `_closed` assignment and deletion after initialization. Successful `close()` performs the sole internal transition to closed after `CloseHandle` succeeds.
- The S13 disposable qualification criterion now requires premature-state mutation refusal, successful close, idempotent repeated close, and acquisition refusal after close.
- A current-turn WP0 artifact records the local/remote MCP route observations without exposing tokens or payloads.

## Why

`close()` returns early when `_closed` is true. If a caller could set that state before closing, the object would leak its kernel handle; resetting it after a successful close could then lead to `WaitForSingleObject` on a closed handle. The lifecycle state must therefore be writable only by the successful close path.

## Affected contracts and paths

- `src/erp_mcp_private_writer/windows_authority_mutex.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/artifacts/WP0_LOCAL_MCP_AND_IVAN_READONLY_RECHECK_2026-10-25.md`
- `core/LESSONS_LOG.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Decisions

Keep the Windows lifecycle transition distinct from frozen identity/configuration fields. Preserve explicit refusal after close and leave the state open if `CloseHandle` fails. A local `code-reviewer` pass found the premature `_closed=True` handle-leak path (medium severity); the finding was fixed by denying ordinary state assignment after initialization and restricting the internal transition to successful `close()`. Tool role model: GPT-6 Luna; reasoning effort was not present in launch metadata and is recorded as `NOT_RECORDED`. Do not run Windows runtime qualification until source coding is complete and the named functional/E2E roles own that phase.

## Verification state

Baseline `windows_authority_mutex.py` before this change: SHA-256 `F8B86771F79216887FFF72DAF99B058A19EA14562282D563CEC2D12FF60E8A56`.
Current source hash: `E3D25FA923350699A678B50525EC5623BE58391AE987F608861003458732D7D6`.
Baseline qualification document before this change: SHA-256 `90E9C89AAF2C81DC8BDE2909471ED92AC6D251EFBB62CFFE1C8C206F45764CF6`.
Current qualification document hash: `81D7F7CE398D04CF9D669E7AC0C5709AD5D0EDE8C9448F6A3C011CB56FD9F937`.
WP0 observation artifact hash after appending this turn's transport evidence:
`4E43F108D73EAB521370A4CC803A1E801F7F9B0BB0031A00D8413F6368442B71`.

Source inspection only. Tests, checks, build, Windows runtime, database, migrations, COM, process restarts, staging, commit and push were not run.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Ivan stack: technical owner of the licensed host boundary. After coding closure, functional/E2E roles must qualify normal close, repeated close, attempted state reset, post-close acquisition, and close/acquire concurrency; applicable Python/reliability review follows that evidence.


