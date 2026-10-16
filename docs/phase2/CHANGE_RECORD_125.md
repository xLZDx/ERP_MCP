# Change record 125 — design S13 startup and restore lifecycle

## Finding and goal

The read-only S13 source inventory found no Python application startup, reconnect, or restore caller for `SqlChangeLedger.verify_chain()`, `check_anchor()`, or `recover_sweep()`. The checkpoint protocol can write/read a specified sequence but cannot query the latest external checkpoint. The existing in-memory sink and fake signer/verifier are explicitly TEST ONLY. Without a coordinator, startup/restore acceptance is not wired; without `latest(scope)`, a restored older-but-internally-valid database cannot compare itself with the newer external anchor.

## Design decision

Use a provider-neutral local lifecycle coordinator and add a read-only `latest(scope)` capability to the sink protocol. This makes local fail-closed ordering testable without selecting or accessing an external account. Do not invent an app/framework composition point: expose an explicit coordinator for a future service composition to call on start, reconnect, and restore. Keep external provider, authenticated latest-read, immutable retention, signer/key custody, owner, bootstrap, and deployment acceptance open. A non-empty ledger without authenticated external anchor remains unready.

## Acceptance sequence

1. Verify the local chain before any operation that may mutate it.
2. Read and authenticate the newest external checkpoint, then compare it with the local head; failures keep admission disabled and holds intact.
3. Run the bounded detailed recovery sweep only after chain/anchor validation; unresolved or incomplete work remains unready.
4. Re-verify the chain; if recovery appended events, write, read back, verify, and record the new checkpoint before readiness.
5. Keep downstream effect dispatch disabled until all checks pass; never span external I/O with a DB transaction or convert an unavailable result to success.

The complete failure, rollout, rollback, and verification mapping is in `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`.

## Affected paths

- `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`
- `docs/phase2/CHANGE_RECORD_125.md`

## Verification and limits

- Read-only source mapping came from `code-explorer` / GPT-6 Luna medium across V2-S13-01..05, migrations 004–020, `SqlChangeLedger`, and `CheckpointSink`.
- Independent prep review came from `code-architect` and `database-reviewer` / GPT-6 Luna medium. They recommended additive changes only, keeping the checkpoint store/signer as a separate formal dependency and lock-order MINOR in S18.
- This record is design-only. No tests, checks, database commands, migrations, service credentials, or production actions were run.
- Formal S13 remains `NOT_STARTED` / `NOT_APPROVED`; G1–G8, Release 2, and production status are unchanged.

## Ownership and next work

- Task accountability: operator delegated autonomous project closure to GPT/Codex; GPT/Codex executes local work and requests GPT-PM scope decisions.
- Local implementation: Codex executor after GPT-PM approves the exact S13 local scope. `implementation-engineer` can own the implementation module; only `functional-test-reviewer` and `e2e-runner` write/execute required tests after coding is complete.
- External checkpoint provider/key custody/service ownership and deployment composition are not established in canonical records. The local protocol work does not resolve those external dependencies.
- Push requires exact-head GPT approval; the earlier `705076a` approval does not extend to this or subsequent commits.
