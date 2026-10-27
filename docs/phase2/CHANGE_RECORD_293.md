# Change Record 293 — make mutex owner-thread close single-flight

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

Source review found that cancellation of `WindowsServingAuthorityMutex.close_async()` could leave its `asyncio.to_thread(self.close)` command running while the runtime's close lock was released. A later close retry could enqueue a second command before the owner thread exited, violating exactly-once shutdown ordering.

## Change

The mutex now stores its first asynchronous close task and shields that same task for every later `close_async()` call. Cancellation may return to the caller, but it cannot erase the in-flight command identity; a later runtime close joins the existing task instead of enqueueing another kernel close. A failed or timed-out command remains a stable fail-closed result for the object, requiring process replacement rather than guessing whether the owner thread closed the handle.

## Affected paths and contracts

- `src/erp_mcp_private_writer/windows_authority_mutex.py` — retained single-flight close task across cancellation/retry.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — repeated-cancellation and no-duplicate-close acceptance.

## Verification state

An actual read-only `code-reviewer` re-review confirmed a cancelled caller retains the same close task and no duplicate close command is queued. The agent launch did not expose exact model/effort metadata (`NOT_VERIFIED`). No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification ran. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; this cancellation interleaving needs a disposable Windows execution trace.
