# S13 candidate: exact signed evidence replay

## Change

Added `change_ledger.record_evidence_v1` to additive migration 027 and a flag-gated adapter route from the existing internal `SqlChangeLedger.record_evidence` method. The adapter allocates an evidence UUID before invoking SQL and passes it as the final candidate argument. Legacy routing remains the default.

The candidate preserves the legacy content, binding, signature, key-role, permit and evidence-kind checks. It takes the exclusive namespace-7 scope fence and early lifecycle-row lock, followed by sorted namespace-6 `record-change-id:v1:` / `evidence-record-id:v1:` keys before business-row locks. New rows use the exact preallocated global ID. A logical-key replay returns the prior ID only when scope, change, kind, content hash, observed time, JSON content, signer key, signature, binding, generation, call ID and authenticated `recorded_by` all match. A changed tuple returns `EVIDENCE_IDENTITY_CONFLICT` (`P0001`) before DML or event append.

The candidate signature is explicitly revoked from `PUBLIC` and all named application/private roles. No candidate grant, default-route change, public MCP tool, physical COM route, historical migration edit or cutover was made.

## Why

The final legacy function in migration 019 returns the existing `evidence_id` when `(change_id,kind,content_hash)` conflicts, without comparing the rest of the immutable signed tuple. This can alias a different actor or a valid but changed envelope to the first stored evidence row.

## Verification state

- Manual source inspection only; no SQL parse, test, check, build, CI, migration, database query/write, COM call, staging, commit, or push was performed.
- Candidate installation and exact/conflicting replay scenarios: `NOT_RUN`.
- Effective privileges and all-path namespace/row ordering: `NOT_VERIFIED`.
- Runtime flag must remain disabled until full candidate cutover, effective-grant review and S12/S13 qualification pass.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. After all in-scope coding, `functional-test-reviewer` and `e2e-runner` own focused replay/race scenarios; `database-reviewer` owns effective privilege and transaction review. Push/PR still requires fresh GPT-PM approval for the exact final code head.
