# Change Record 291 — drain accepted control operations during runtime shutdown

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

`PrivateWriterService.shutdown()` waited for active dispatch and quiescence tasks, but `fence_scope()` can suspend during a barrier-row lookup or database closure before `_active_quiesce` is created. Shutdown could therefore conclude that no barrier was active, close the COM writer and authority mutex, and then allow that already-entered barrier operation to continue. Startup-recovery inspection had the same lease-held gap, and `prepare_to_serve()` could resume after shutdown and reopen readiness. `resume_barrier()` also needed an admission gate once shutdown starts.

## Change

`inspect_startup_recovery()`, `fence_scope()` and `resume_barrier()` now register an accepted control operation synchronously before their first suspension point, and always release that count in `finally`. The shutdown flag and registration update have no intervening `await`: a racing request is either counted and drained or refused with `WRITER_SHUTTING_DOWN`. `prepare_to_serve()` also refuses before startup and rechecks shutdown after its awaited recovery view, so it cannot reopen readiness. The lifecycle setter and `ready` property independently require shutdown to remain false. Shutdown waits for the accepted operation count to reach zero within its existing deadline before proceeding to the specific dispatch/quiescence drain and physical close. If draining times out, it latches restart-required and leaves the writer and mutex open. Previously accepted recovery/barrier work can finish under held authority; later control calls cannot start.

## Affected paths and contracts

- `src/erp_mcp_private_writer/service.py` — accepted control-operation tracking, startup readiness gate and shutdown admission gate.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — barrier-vs-shutdown race, refusal, drain and timeout cases.

## Verification state

An actual read-only `code-reviewer` pass checked accepted-operation tracking, readiness closure and the shutdown barrier race; it found no remaining concrete source finding. The agent launch did not expose exact model/effort metadata (`NOT_VERIFIED`). No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification ran. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; the DB race, Windows mutex behavior and real COM lane still require disposable qualification.
