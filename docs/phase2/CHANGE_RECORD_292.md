# Change Record 292 — keep Windows mutex waits off the service event loop

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

The authority mutex used a dedicated owner thread, but synchronous `threading.Event.wait()` still ran on the caller thread for acquire/release responses. Because the service calls those methods from async dispatch, startup and quiescence paths, an owner-thread scheduling/API stall could block the event loop for up to the command timeout and delay service deadlines.

## Change

`ServingAuthorityMutex.try_acquire()` and `ServingAuthorityLease.release()` are now awaitable. The Windows adapter delegates bounded owner-thread response waits to `asyncio.to_thread`; the event loop stays schedulable while the owner thread performs its zero-timeout OS mutex operation. Lease release records a one-way release-started state before the await so concurrent/retried release cannot submit a duplicate kernel release. If an acquisition is cancelled while the worker response is pending, its same-process reservation is retained and the service latches restart-required; it does not guess whether OS authority was acquired. Release cancellation likewise fails the service closed. Runtime close awaits the owner-thread join off-loop; single-flight task preservation across repeated cancellation is recorded in change record 293.

## Affected paths and contracts

- `src/business_ai_gateway/phase2/change_ledger/write_port.py` — async serving-mutex and lease-release protocol.
- `src/erp_mcp_private_writer/windows_authority_mutex.py` — async acquire/release/close wrappers and single-use lease release.
- `src/erp_mcp_private_writer/service.py` — await authority acquire/release and fail-stop cancellation paths.
- `src/erp_mcp_private_writer/runtime_composition.py` — asynchronous owner-thread close.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — event-loop responsiveness and pending-command cancellation cases.

## Verification state

An actual read-only `code-reviewer` pass rechecked async acquire/release cancellation and shutdown lease invariants and found no remaining source-level blocker. The agent launch did not expose exact model/effort metadata (`NOT_VERIFIED`). No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification ran. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; cancellation settlement, Windows scheduling, and two-process exclusion need disposable evidence.
