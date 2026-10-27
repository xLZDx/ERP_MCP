# Validate S13 barrier snapshot ordering — 2026-10-22

## Change

- Hardened `PrivateWriterService._barrier_snapshot_valid` to reject non-canonical UUID strings
  and call-ID tuples that are not lexically ordered.
- Required `unresolved_call_ids` to preserve the order induced by the complete `call_ids` tuple.

## Why

The durable-store contract requires every barrier poll to return the same deterministic, complete,
unpaginated pre-barrier call set. The coordinator previously checked uniqueness and set membership,
but accepted reordered snapshots. A reordered or non-canonical response could obscure whether a store
returned the same barrier membership across polls.

## Contracts and paths

- `src/erp_mcp_private_writer/service.py`: fail-closed validation of the store's `BarrierSnapshot`.
- This does not change the database admission protocol, the call set itself, barrier persistence,
  readiness, or physical writer behavior.
- Canonical call IDs follow `CallIdentity`, which normalizes `change_id` and `call_id` with
  `str(UUID(...))`; the store must return those canonical lowercase UUID strings in sorted order.

## Verification state

- Manually inspected the validator and the `AdmissionStore` ordering contract in the same module.
- No tests, checks, builds, CI, migrations, database calls, service actions, or COM calls were run.
- Functional and E2E coverage of malformed, reordered, duplicate, incomplete, and stable repeated
  barrier snapshots remains pending until all in-scope coding is complete.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Test ownership: `functional-test-reviewer` and `e2e-runner` after code completion.
- Next: verify the full adapter preserves this canonical order under durable repeated barrier polls;
  do not use this validation alone as evidence that the store returns a complete snapshot.
