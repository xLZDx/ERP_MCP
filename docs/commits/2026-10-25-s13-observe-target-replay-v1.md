# S13 candidate: exact target observation replay

## Change

Added `change_ledger.observe_target_v1(text,text,uuid,text,text)` to the additive source-only schema in migration 027. It keeps the legacy API parameter order, derives the observer from the authenticated database role, plans the token's parent identity, validates lifecycle immediately after namespace 7, acquires the deduplicated signed-hash namespace-6 keys, then locks the parent record before its claim-token child and revalidates the planned token generation. An exact stored `(fingerprint,class,observed_by)` tuple returns lookup-only success without another event. A changed tuple returns `TARGET_OBSERVATION_CONFLICT` (`P0001`) before mutation. A new observation inserts one row and appends one event.

The SQL function is explicitly revoked from `PUBLIC` and all named application/private roles. The existing Python adapter already has a feature-flagged `observe_target_s13` selector; its default remains legacy and its enabled route has no fallback. No grant, default-route change, public MCP tool, COM route, or historical migration edit was made.

## Why

The legacy body at `db/phase2/005_change_registry.sql:377-401` uses `ON CONFLICT DO NOTHING` and appends `TARGET_OBSERVED` even when the row already exists. That can create duplicate events and can return success to a caller whose observation or identity differs from the durable first row. The candidate makes exact replay explicit while retaining the first observer as immutable audit attribution.

## Contracts and paths

- Uses the exclusive namespace-7 same-scope candidate fence and validates the lifecycle row before relation-row locks or writes.
- The non-locking token plan is revalidated after global namespace-6 ID fencing and under parent-first record/token row locks.
- Error precedence mirrors the legacy entry: missing/NULL token is `TICKET_SUPERSEDED`; class/fingerprint validation occurs only after the locked token is confirmed current-generation `ISSUED`.
- Candidate caller surface is the existing internal `SqlChangeLedger.observe_target`; no MCP API or private physical-writer call was added.
- The legacy function and grant remain present during additive qualification. Candidate deployment/cutover is not established.

## Verification state

- An actual focused `database-reviewer` pass found one error-precedence issue: an early NULL guard returned `SCHEMA_INVALID` before the legacy token lookup. The guard was moved after locked token-state validation (NULL token now takes the existing lookup-miss branch); follow-up found no remaining finding. When lifecycle is `NOT_READY`/`RECOVERING`, the candidate intentionally returns lifecycle refusal before token lookup as required by its acceptance contract.
- Manual source review only; no SQL parse, test, check, build, CI, migration, database query/write, COM call, staging, commit, or push was performed.
- Current whole-file migration 027 SHA-256: `F524AD655C42DD64676366D942A2C79177C1F6DCCB2F60F94E49BA72272ED77F`.
- Candidate SQL installation and disposable replay/race qualification: `NOT_RUN`.
- Effective privileges and complete cross-entry lock-order qualification: `NOT_VERIFIED`.
- Runtime flag must remain disabled until the complete candidate grant, legacy cutover, and S12/S13 gates are accepted.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. After all in-scope coding is complete, `functional-test-reviewer` and `e2e-runner` own their focused qualification scenarios; `database-reviewer` owns effective-grant/transaction review. Push/PR remains behind fresh GPT-PM approval for the exact final code head.
