# Change record 127 — reconcile S13 backlog after fence reviews

## Goal

Make the current backlog agree with the corrected S13 lifecycle design and independent architecture/database review. The prior row said to reconcile migrations and implement gaps but did not identify the required cross-process fence, anti-rollback latest-read, or suffix classification.

## Changes

- Updated the current S13 backlog row to distinguish the existing recovery SQL prototype from the missing startup/restore coordinator.
- Recorded the design prerequisites: inventory mutation/permit/dispatch paths and lock order; durable per-scope `RECOVERING` state and monotonic epoch; ordered suffix classification; provider-authenticated anti-rollback latest read; exact GPT-PM scope decision before implementation.
- Kept formal S13 `NOT_STARTED` / `NOT_APPROVED`, and kept real provider, signer, and service composition as separate formal dependencies.
- Refreshed the generated document registry after creating this record.
- Refreshed the authorized ERP source-observation row with this pass's read-only connector retry result.

## Evidence and limits

- The source design was corrected in CR126 using independent security, reliability, architecture, and database reviews.
- Current database review found the existing event-chain and recovery advisory locks do not serialize startup with all ledger mutations and physical dispatch. See `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`.
- The read-only calls `ERP_MCP_REAL1.sources_list` and `ERP_MCP_REAL1.system_status` both returned MCP `-32603: Internal error`; no ERP source evidence was collected. This records a connector/tool failure, not ERP state.
- This is documentation/backlog reconciliation only. No source code, tests, checks, database commands, migrations, or production systems were changed or run.
- Local branch before this record: `73c2d50`; `origin/main` remains `a2778ea`. These docs are local and require exact-head GPT review before push.

## Ownership and next action

- Task accountability: operator delegated project closure to GPT/Codex; GPT/Codex executes local work.
- S13 implementation owner: GPT/Codex under delegated local scope; database/security review lanes validate the additive contract. No external service owner is recorded.
- Next: finish path/lock inventory, receive GPT-PM response to the already-sent scope request or send one corrected request after that request is conclusively resolved, then implement only the authorized local scope. Required test authors/executors after coding: `functional-test-reviewer` and `e2e-runner`.
