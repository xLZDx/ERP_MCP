# Change record: Validate S13 invocation context shape

## What changed

`InvocationContext.__post_init__` now validates the exact CAS UUID, canonical service/change/call/permit UUIDs, nonblank trimmed host/scope values, lowercase SHA-256 fingerprints/digests, positive epoch/generation integers, operation-specific target/pre-version shape, nullable repair-authorization UUID, and callable one-way COM-entry guard. The coordinator calls `require_matches` before selecting the physical writer method; it binds the context back to the ticket, permit, active service instance, configured host and base, normalizing UUID case only for ticket/permit change and call IDs.

The same change now validates `ReceiptLookupKey` before recovery can pass it to the writer's read-only receipt lookup: canonical nonzero UUIDs, nonzero dispatch CAS, positive generation/authority epoch, lowercase SHA-256 digests, trimmed scope/host, nullable canonical repair UUID, and operation-specific target/pre-version shape. Invalid lookup identities fail closed with `RECEIPT_LOOKUP_KEY_INVALID`.

## Why

The context is created by the coordinator but consumed by a future physical COM adapter. Type annotations alone do not reject malformed runtime values. Refusing malformed context at construction narrows adapter error paths while preserving the rule that these fields are comparison bindings, not authorization. The explicit equality check also prevents a correctly shaped context from another ticket, permit, process instance, host or base being passed to an adapter.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/write_port.py`
- `src/erp_mcp_private_writer/service.py` (context construction and pre-writer binding check)
- `docs/phase2/OPERATOR_BACKLOG.md`

## Decisions

Database entry authorization remains the one-way `begin_com_entry` CAS. The equality check does not authenticate values or prove entitlement, permit validity, base identity, CT14 behavior or physical completion; it does not wire a physical writer. Operational COM integration remains gated on canonical mapping and the production evidence boundary.

Receipt-key validation is shape validation only. It does not prove that a receipt exists, is authentic, matches the database attempt or establishes an outcome; the production verifier and durable store remain authoritative.

The disposable prerequisite now assigns `S13-INVOCATION-CONTEXT-BINDING-01` to malformed and cross-call context refusal, including the expected unresolved attempt when context rejection occurs after `mark_invoking` but before the one-way COM-entry CAS. `S13-RECEIPT-LOOKUP-KEY-SHAPE-01` covers recovery-key constructor boundaries.

The source lock inventory and disposable qualification plan now also distinguish current
`begin_apply`/`record_call` behavior from the additive intent/attempt contract. The new
`S13-BEGIN-APPLY-LOCK-CALL-ID-01` scenario covers parent-before-token locking, immutable replay,
abandoned global call-ID reservation, the `(change_id,generation)` limits of current permit/deadline
keys, and the exact intent-to-attempt identity binding. This is source/design traceability only;
the candidate remains `NOT_RUN`.

The same source inventory now records why the existing observation/evidence replay scenarios are
decisive: `observe_target` can append a duplicate event after a skipped insert, and
`record_evidence` can return an existing ID for a valid same-key envelope without comparing the
full immutable tuple. Their qualification remains `NOT_RUN`; this edit makes no runtime or schema
claim.

## Verification state

Source inspection and one fresh Python-reviewer pass found no source-level findings on `ReceiptLookupKey`; the reviewer did not run tests or checks. Functional/E2E behavior remains NOT_RUN. No build, migration, SQL execution, database write, COM invocation, staging, commit, or push was performed.
