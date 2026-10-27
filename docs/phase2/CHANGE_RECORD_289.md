# Change Record 289 — drain private-writer operations before runtime close

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

The runtime exposed a synchronous `close()` that closed the Windows authority handle directly. It did not stop dispatch admission, await the service's retained dispatch/quiescence tasks, or close the COM STA first. A mutex owner thread that is deliberately non-daemon therefore needs a concrete close sequence; callers must not release authority while an accepted COM call is still unresolved.

## Change

`PrivateWriterService.shutdown()` now permanently rejects new dispatches for that instance, marks readiness false, awaits retained dispatch and barrier tasks within a bounded deadline, and waits for the local dispatch lock to drain. Timeout latches restart-required and raises an unknown-outcome service error. `OneCWritePort.close_after_drain()` is now part of the explicit port contract. `PrivateWriterRuntime.close()` is asynchronous and sequences service shutdown, writer/COM close, then Windows mutex owner-thread close. It requires the HTTP/MCP listener to have stopped first. If draining or COM close fails, control flow does not close the mutex, so another process cannot take over while the physical outcome is unclear.

The source contract does not supply an actual listener or operational COM writer. Concrete shutdown behavior and a two-process proof remain qualification work.

## Affected paths and contracts

- `src/erp_mcp_private_writer/service.py` — permanent dispatch shutdown gate, active-task drain, bounded fail-stop behavior.
- `src/business_ai_gateway/phase2/change_ledger/write_port.py` — mandatory idempotent `close_after_drain()` port operation.
- `src/erp_mcp_private_writer/runtime_composition.py` — asynchronous drain/COM/mutex close order.
- `src/erp_mcp_private_writer/windows_authority_mutex.py` — dedicated kernel mutex owner thread, thread-independent lease, close/join protocol.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — exact close-order, failure and second-process acceptance.

## Verification state

Manual source inspection only. No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification was run. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`. The COM STA must implement and evidence `close_after_drain`; runtime host supervision must stop the listener before invoking this API.
