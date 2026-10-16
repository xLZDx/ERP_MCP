# Change record 126 — correct S13 startup/restore design from independent reviews

## Finding and goal

The S13 lifecycle design in CR125 proposed readiness based on process-local orchestration and existing SQL locks. Independent security and reliability review found that this does not prove an external checkpoint is the anti-rollback latest record, does not bind the signed checkpoint scope before SQL mutation, does not classify events after the anchor under the S12 contract, and does not fence concurrent writers or stale processes across instances. Migration 020's recovery advisory lock covers the sweep only. Repeated anchor mismatch can also append duplicate `ANCHOR_GAP` events; retry/backoff/readiness-reason behavior was unspecified.

This record corrects the design before source implementation. A READY-producing coordinator is not accepted until the shared fence protocol and complete mutation/dispatch coverage have a database-reviewed contract.

## Design decisions

- Require provider-authenticated anti-rollback `latest(scope)`, valid signature, and exact tenant/company equality before any mutating SQL call. Signature validity alone does not prove latestness.
- Verify the complete local chain; establish that the checkpoint is an exact ancestor; classify the entire ordered tail under S12 §9. Do not require the checkpoint to equal the present head: T10, T13, and observation reads may be included in the next checkpoint when their complete transition state meets the contract.
- Treat `check_anchor()` as an ancestor-membership check that may mutate by declaring `ANCHOR_GAP`; it does not prove provider latestness or suffix eligibility.
- Require a shared cross-process per-scope fence covering ledger mutation and dispatch transitions, in-flight permits/calls, stale-process behavior, bounded acquisition, crash release, and fence-loss readiness invalidation. Existing per-process readiness and migration 020's sweep lock are insufficient.
- Candidate additive DB contract from database review: durable per-scope `RECOVERING` state plus a monotonic fencing epoch; all relevant mutation, permit, and dispatch-CAS paths honor it; writer checks epoch in the immediate pre-call CAS; recovery gates READY on no unresolved/in-flight effect without independent completion evidence; final READY transition atomically rechecks epoch, chain, suffix, sweep result, and unresolved calls. Enumerate every path and lock order before implementation.
- Specify bounded retry/backoff and structured `NOT_READY` cause/last-attempt state. Repeated identical anchor-gap declaration must not grow the ledger indefinitely; make SQL declaration idempotent or otherwise guard duplicate invocation. This SQL change requires its own database-reviewed implementation scope.
- Keep formal S13 `NOT_STARTED` / `NOT_APPROVED`, and do not claim a production provider, signer/custody, service composition, or runtime acceptance from local design.

## Affected paths

- `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`
- `docs/phase2/CHANGE_RECORD_126.md`
- `docs/sdlc/STATE.md` (current reconciliation and phase status)
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md` (current S13 disposition)

## Evidence and verification state

- `security-reviewer` / GPT-6 Luna medium: identified ancestor-plus-S12-tail requirement, anti-rollback provider requirement, exact tenant/company binding; read-only, no tests/checks/DB.
- `reliability-reviewer` / GPT-6 Luna medium: one MAJOR (missing cross-process fence), two MINOR findings (duplicate anchor-gap append and unspecified retry policy); read-only, no tests/checks/DB.
- Follow-up architecture and database reviews found no existing safe fence and recommended the additive epoch contract recorded in the design. Full mutation/dispatch path inventory and lock-order review remain pending before implementation.
- No tests, checks, builds, migrations, or database commands were run for this record.
- Document registry refresh is a documentation-generation step and will be recorded after the change is complete.

## Ownership and next action

- Task accountability: operator delegated autonomous project closure to GPT/Codex; GPT/Codex executes local documentation/design work.
- Technical design and DB contract: project S13 engineering/database review lanes; no named human/service owner is recorded.
- Next: resolve fence design with architecture/database evidence; revise and submit an exact local engineering scope decision to GPT-PM. Only then implement the approved coordinator/fence changes. After all coding, `functional-test-reviewer` and `e2e-runner` own tests; relevant specialist reviews follow.
- Push remains subject to fresh exact-head GPT approval. No approval from an earlier range carries forward.
