# Change Record 205 — refuse concurrent writer requests before admission

## What changed

- `PrivateWriterService.dispatch()` now checks the base-local lock and returns stable `WRITER_BUSY` before prechecks, durable admission, or writer selection whenever a call or barrier already holds it.
- The accepted path acquires and releases the lock explicitly in `try/finally`; cross-process ownership remains enforced by the durable PostgreSQL admission contract.
- Added `S13-WRITER-QUEUE-REFUSAL-01` for concurrent dispatch and barrier-held cases.

## Why

The old `async with Lock` path queued every concurrent dispatch behind a potentially stalled physical call or barrier. Each waiting request retained parsed request state and its payload without a bound. The COM lane itself admits one in-flight operation; immediate refusal preserves that single-writer safety rule without accumulating application-level waiters.

## Evidence and verification state

- Source checkpoint SHA-256: `src/erp_mcp_private_writer/service.py` `F8DEF4DD4B910AB8894D25665C681D8AF133AFCCB35E9B250F86089345C24CEF`; qualification plan `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6`.
- The same source snapshot includes change 204's bounded startup-inventory mapping; only the lock-busy refusal is attributed here.
- Static source inspection only. Tests/checks/build, database or migration execution, service startup, COM, and disposable qualification were not run. `S13-WRITER-QUEUE-REFUSAL-01` remains `NOT_RUN`.
- The source file had pre-existing modifications. This record attributes only the lock-busy refusal and bounded in-process dispatch admission above to change 205.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after source coding closes, assign stalled-call and barrier-lock concurrency scenarios to the functional/E2E roles; verify the refusal is immediate and occurs before prechecks and durable state changes.
