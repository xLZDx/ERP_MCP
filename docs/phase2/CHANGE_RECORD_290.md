# Change Record 290 — bound the complete private-writer close sequence

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

Change record 289 bounded service dispatch/barrier draining, but a blocked `OneCWritePort.close_after_drain()` could still leave `PrivateWriterRuntime.close()` awaiting indefinitely. Concurrent close callers could also reach the same underlying shutdown sequence at once, including duplicate mutex close requests.

## Change

`PrivateWriterRuntime.close()` now validates its bounded timeout, holds one runtime close lock (including time spent waiting behind another close), and uses a single deadline for service drain plus COM writer close. After both complete it closes/joins the authority owner. If the deadline expires while the writer is still completing shielded STA cleanup, it returns `WRITER_RUNTIME_CLOSE_TIMEOUT` without closing the serving-authority mutex. A later serialized close call can observe the completed idempotent writer close and then close/join the authority owner. Existing listener-stop precondition remains. This is a fail-closed source contract; it does not prove COM cleanup timing or cross-process takeover.

The disposable acceptance now covers concurrent close serialization, an end-to-end deadline, a blocked COM close retaining authority, a later close retry after the STA cleanup completes, and the existing successful close order.

## Affected paths and contracts

- `src/erp_mcp_private_writer/runtime_composition.py` — bounded serialized drain/close sequence.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — extended `S13-PHYSICAL-AUTHORITY-DISPATCH-01` close-timeout scenarios.

## Verification state

Manual source review only. No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification ran. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; the actual operational writer/STA composition, service listener lifecycle, and Windows two-process behavior are still unqualified.
