# Change Record 287 — hold serving authority across private-writer dispatch

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

`PrivateWriterService.inspect_startup_recovery()` and `_quiesce_under_authority()` used the host-wide `ServingAuthorityMutex`, but `dispatch()` did not. The DB call CAS serialized identities, yet a second service process could acquire the host mutex and perform recovery while an earlier service was still executing a COM writer call. The one-way database entry guard did not close that process-takeover window.

## Change

`PrivateWriterService.dispatch()` now requires and acquires the same base-scoped host authority mutex before admission and holds it across the entire `_dispatch_once()` path, including the COM operation and signed-receipt persistence. This makes startup recovery and quiescence fail closed while a physical dispatch owns the lease. The dispatch task is shielded from request-coroutine cancellation so cancellation cannot release authority while an accepted COM operation is still pending. Its completion callback consumes any eventual task exception and releases the lease on the owning event-loop thread. If the internal task itself is cancelled during loop shutdown, the service latches restart-required and deliberately does not call `ReleaseMutex`. Windows abandons the mutex when its owning thread exits, which can precede process exit; graceful runtime shutdown must drain the COM STA before the authority-owning event-loop thread terminates. The current composition has no proven shutdown sequence, so physical worker exclusion across that failure boundary remains `NOT_RUN`.

The database admission/CAS still owns call-ID idempotency and terminal state; the host mutex is a per-base process exclusion fence. This source change does not prove COM transaction atomicity, clone identity, CT14 rights, or final 1C effects.

## Affected paths and contracts

- `src/erp_mcp_private_writer/service.py` — dispatch authority ownership, cancellation, and fail-stop release behavior.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — two-process exclusion, cancellation retention, startup recovery, quiescence, crash-window acceptance.

## Decisions

- Use the already configured named, base-scoped Windows mutex instead of adding another lock registry.
- Refuse before database admission when the mutex is unavailable or already held; do not queue a second physical writer behind an active one.
- Treat cancellation as an unknown caller outcome while the protected internal dispatch continues to its existing durable evidence path.
- Do not explicitly release the OS fence if the dispatch task itself is cancelled; require the COM STA to drain before the mutex-owning thread exits, and keep this lifecycle boundary unqualified until observed.

## Verification state

Manual source review only. No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification was run. The new acceptance criterion remains `NOT_RUN`; actual cross-process behavior and COM outcome evidence require the authorized disposable Windows clone and are owned by the functional-test reviewer and e2e-runner after coding closes.

## Current source fingerprint

- src/erp_mcp_private_writer/service.py SHA-256 after this turn's dispatch-authority change: `D4FACB78803F7CC1595C6110FE72336D8317E646E8A5113DA0F514FA9E1BDF91`.


