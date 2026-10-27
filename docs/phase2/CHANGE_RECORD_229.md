# Change Record 229 — freeze S13 dispatch-gate composition

## What changed

- Added slots to `DispatchGate` for its ledger, checkpoint sink, signer, verifier and two feature flags.
- Reassignment and deletion of those dependencies/flags now fail with `S13_CONFIGURATION_IMMUTABLE` after construction.
- Both `real_checkpoint_sink` and `private_writer_schema_enabled` require exact booleans; the existing ledger/schema parity check remains.
- Added the source-only qualification case `S13-CHECKPOINT-GATE-CONFIG-IMMUTABILITY-01`.

## Why

The dispatch gate's composed dependencies control checkpoint writes and permit issuance. Replacing one after construction could switch the authority or persistence path without rebuilding the gate. Freezing references closes that configuration mutation path while preserving the existing fail-closed behavior when a real trusted sink and signer are absent.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/checkpoint.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `core/LESSONS_LOG.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Verification state

The source file already had uncommitted changes before this turn; its immediate pre-edit hash was not captured. Current source SHA-256: `1C7A9301C9A9BD2CB114ECFC2C4F2A03BB48BFA69DE5674A14F441C323009072`.

Qualification prerequisite SHA-256 after adding the SQL ledger's no-instance-dictionary case: `7002F62E949C8F20B87ABEB8455EF614912F51C200AB7216982DA9CEA29DF75C`.

Source inspection only. Tests/checks/build, database calls, migrations, COM activity, staging, commit and push did not run. The qualification case remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. After code closes, `functional-test-reviewer` owns the exact mutation/enablement cases. Continue source/grant closure before attempting disposable qualification or runtime activation.
