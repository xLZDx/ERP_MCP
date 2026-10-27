# Change Record 288 — keep serving mutex ownership off the event-loop thread

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

Change record 287 added a dispatch-scoped Windows mutex lease, but the lease was owned by the asyncio event-loop thread. Windows mutex ownership is thread-bound: terminating that thread can abandon the kernel mutex even when a separate COM STA thread or process component is still alive. A client cancellation is handled by shielding the inner dispatch, but loop shutdown can still expose this ownership mismatch.

## Change

`WindowsServingAuthorityMutex` now creates one dedicated non-daemon authority-owner thread. That thread performs the zero-timeout kernel wait, holds the named mutex while a logical lease is active, and performs the matching release. Logical `_WindowsLease` values are thread-independent, bound to an opaque per-lease ID, and checked against the owner thread's state. `try_acquire()` remains non-queued; a process-local reservation prevents recursion across multiple objects for the same base. A request timeout or owner-thread/API error retains the local reservation and fails closed because the caller cannot know whether the OS lock was acquired or released. `close()` refuses while any logical lease remains, then asks the owner thread to close the handle and joins it; the worker is non-daemon so event-loop-thread exit alone cannot abandon a held kernel mutex while the process is still alive.

This deliberately favors safety over availability: if an internal dispatch task is cancelled before its completion callback can release the logical lease, the service latches restart-required and `close()` refuses. The host supervisor must terminate/replace that process after confirming the disposable COM worker is stopped; no call is retried based only on process shutdown. Graceful integration still needs to stop new admission, drain active COM work, release leases, then close the authority runtime.

## Affected paths and contracts

- `src/erp_mcp_private_writer/windows_authority_mutex.py` — stable OS mutex owner thread and thread-independent leases.
- `src/erp_mcp_private_writer/service.py` — dispatch lease retained through cancellation-safe outcome processing.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — owner-thread, event-loop-loss, two-process and shutdown acceptance.

## Verification state

Manual source review only. No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification was run. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; the service lifecycle still needs an explicit graceful stop path, and Windows process/thread behavior requires disposable two-process evidence.
