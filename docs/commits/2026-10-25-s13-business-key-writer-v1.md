# S13 candidate business-key writer

## Change

Added ungranted `change_ledger.declare_business_key_v1` in migration 027 and an opt-in no-fallback route from the existing `SqlChangeLedger.declare_business_key` method. The candidate takes the shared kill-switch fence, exclusive scope fence and early lifecycle row, then namespace-6 `record-change-id` and the exact legacy namespace-4 business-key identity before locking the parent record and business-key child.

It snapshots both the record and its globally keyed `business_keys` child before the conflict fences. After taking the parent record lock and validating its snapshot, it takes the child lock and compares both row presence and the full row to the planned child; a changed or newly inserted/deleted child fails `LOCK_PLAN_STALE` before DML. The same parent-first ordering serializes this route with the still-reachable legacy implementation. The candidate preserves the legacy digest and exact replay behavior, updates the business-key row, resets `VALIDATED` to `PROPOSED` when the identity changes, and emits the original single-event fields. Candidate EXECUTE is explicitly revoked from `PUBLIC` and all named application/private roles.

## Why

The legacy routine locks `records` before its globally keyed `business_keys.change_id` UPSERT and before the namespace-4 duplicate-validation key. The candidate moves both conflict arbiters before relation rows without changing the established API default or duplicate-key identity.

## Scope and compatibility

- This is additive source only; legacy routing remains default and the explicit S13 feature flag remains off.
- No historical migration, grant, data, public MCP surface, physical COM path or production behavior changed.
- The legacy route remains reachable pending all-path fence and effective-privilege qualification.

## Verification state

- A focused actual `database-reviewer` source pass found no BLOCKER/MAJOR in plan/current child equality, legacy-route serialization, namespace/row order, replay/error precedence, lifecycle reset, or event semantics; reviewer model/effort was unavailable.
- No SQL parse, tests, checks, build, CI, migration, database query/write or COM call ran.
- Current whole-file migration 027 SHA-256: `51CA4C23B9BF85B73773CB8BC8FDFFE23AB74AA02D4884307B9C1F4B19BF359`.
- `S13-DECLARE-BUSINESS-KEY-01` remains `NOT_RUN`; effective grants remain `NOT_VERIFIED`.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: `database-reviewer` role.
- Later behavior qualification: `functional-test-reviewer` and `e2e-runner` after coding completes.
- Push/PR requires fresh GPT-PM approval for the exact final code head.
