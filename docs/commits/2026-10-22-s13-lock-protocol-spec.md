# Change record: specify S13 fence key and lock ranks

Date: 2026-10-22  
Scope: S13 database fence implementation contract; documentation only.

This record documents the initial proposal. The current protocol is refined in
`2026-10-22-s13-timeout-code-mapping.md`: migration 020 already uses namespace 5 for sweep
serialization, so the current design preserves namespace 5 and assigns namespace 7 to the new
scope fence. Do not implement the initial namespace/rank bullets below without that correction.

## What changed

- Specified the scope advisory-lock key as a domain-prefixed, length-delimited `(tenant_id, company_id)` tuple in namespace 5, using shared locks for mutation and exclusive locks for recovery/barrier transitions.
- Specified domain-prefixed global-ID locks in namespace 6 for globally unique `call_id`, `change_id`, and optional `grant_id`, including the exact `(6, hashtext(domain_prefix || canonical_uuid::text))` mapping using the existing two-integer advisory-lock convention. Multiple IDs are sorted deterministically.
- Recorded the fixed acquisition rank: scope fence; global IDs; existing kill-switch/hold/business-key namespaces 2–4 in numeric order; rows in the reviewed token/record/secondary order; event-chain namespace 1 last.
- Defined the existing five-second lock-timeout cap, preservation/restoration of shorter caller settings, SQLSTATE `55P03` mapping to `LEDGER_LOCK_TIMEOUT`, and full top-level rollback. This remains distinct from business `LOCK_BUSY`.
- Clarified that 32-bit collisions in namespaces 5 and 6 preserve same-key exclusion but may delay recovery or cause unrelated IDs across scopes to contend.

## Why

The source audit established that scope fencing alone cannot order caller-controlled global conflict keys. The prior design also left the fence-key derivation, lock rank, and timeout/refusal contract unspecified. These choices now form a reviewable design direction before writing SQL or adapters.

## Source and review evidence

- Existing lock namespaces 1–4 and named-lock helper: `db/phase2/008_change_hardening_b.sql:1510-1521`.
- Existing five-second lock-wait cap: `db/phase2/023_lifecycle_activation_cap.sql:12-20`; restoration on success and exception: `db/phase2/024_restore_caller_lock_timeout.sql:9-30`.
- Cross-scope `change_id` and `grant_id` source evidence is recorded in `docs/commits/2026-10-22-s13-cross-scope-conflict-map.md`; S12's global `call_id` uniqueness rule is in `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md:140-143`.
- Read-only database-reviewer pass: 0 BLOCKER, 0 MAJOR, 1 MINOR, 1 INFO. The MINOR about 32-bit hash collisions was closed by stating the recovery wait cost accurately. INFO: namespaces 5 and 6 are design-only; they must be added in a future migration. Role: `database-reviewer`; model: role default GPT-6 Luna; reasoning effort: not exposed in returned agent metadata.
- The earlier GPT-PM design review request `875580c2-0610-452c-bf74-678f455bf59e` selected shared per-scope mutation fencing plus canonical internal ordering. It is not approval of these exact implementation parameters or an additive migration.
- Correct-route review request `fb3529c1-83e9-4eab-a4f3-1a5fb13d3c64` reviewed SHA-256 `2500FFD7A45A4A53390D8B73FFC3D297F662BC4AC43B0418639D2EF6E461D4C0` and returned `REVISE` (1 MAJOR, 1 MINOR). A separate continuation request `c9b13d91-4b2c-4d4c-9d4a-98eac51fe352` was mistakenly routed to PM Bridge project `erp` and returned `REVISE` (4 MAJOR); it was not an ERP_MCP approval. Durable status for revised-patch request `6f70e13f-a1ab-47e4-adb0-b4e9b207b21d` remains `uncertain` / `CHATGPT_SEND_UNCONFIRMED`, with `sendPhase=sending`, no `userTurnId` and no `replyId`. A later conversation `peek` exposed text claiming `APPROVE` for attachment SHA-256 `805CC5CE3E2EF47F7FE850DD6CC841916D74FB771A2AEA0F2AF000CF8ADE0F21`, but that text is not correlated to the request and does not authorize a commit. The current working-tree/index contents also diverge from that attachment; a fresh exact-diff review through project `erp_mcp` is required before any local commit.

## Limits and next step

- This is documentation only. Namespaces 5 and 6, timeout-to-code mapping, and API participation are not implemented or runtime-qualified.
- No tests, checks, builds, CI, migrations, database writes, COM calls, or service actions were run for this change.
- Accountable owner: operator; executor: Codex. Next: get exact design review, complete API-level acquisition coverage, and only then prepare an additive migration; retain recovery refusal and lifecycle `NOT_READY`.
