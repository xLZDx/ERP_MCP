# S13 business-key mutation and validation lock note

Date: 2026-10-22  
Reviewed source HEAD: `0fe023db1ec2adcf1820356db1dd1db09d23c3ab`  
Review type: read-only source inspection; no database connection or migration execution.

## Source facts

- `db/phase2/005_change_registry.sql:101-111` defines `change_ledger.business_keys`; `key_hash` is mutable at the table-contract level.
- `db/phase2/005_change_registry.sql:486-526` defines `declare_business_key`. It locks the parent `records` row at line 500, reads any prior business-key row, then inserts or updates `key_hash` and override fields at lines 510-526. This path does not acquire the named business-key advisory lock used by validation.
- `db/phase2/008_change_hardening_b.sql:290-337` defines `validate`. It locks the parent `records` row at lines 297-299, reads the business key at lines 305-306, then acquires the named key lock at lines 309-310 before its duplicate scan.
- `db/phase2/005_change_registry.sql:1306-1327` revokes table access from PUBLIC and grants `declare_business_key` to `requester_role`; this source definition does not establish effective installed grants, role memberships, owner/admin access, or deployment drift.

## Assessment and limit

The two functions serialize on the same change's parent row, but only `validate` participates in the named key-lock protocol. A validation's duplicate scan therefore is not source-level serialized with every concurrent business-key mutation on a different change. This is a concurrency concern requiring a transaction-level design and evidence; this source inspection alone does not prove an incorrect accepted state, a production exposure, or a deadlock.

Changing only the historical `validate` definition would not establish a complete protocol. A candidate design must account for both the old and new key when a declaration changes `key_hash`, acquire all relevant key locks in one deterministic order before row locks, and re-read/revalidate the parent and key rows after acquiring those locks. The design must also cover every other path that can mutate the indexed conflict identity, transaction boundaries, trigger/event locks, and concurrent key changes. These are design requirements to validate, not an approved implementation.

## Acceptance and next step

S13 remains `NOT_APPROVED`; lifecycle remains `NOT_READY` and recovery refusal remains in force. Before proposing an additive migration or changing either function, obtain effective deployed grants/owners and identify the actual writer/service transaction boundary. Then prepare a full lock-order design and falsifiable concurrency scenarios for the authorized disposable-database test phase, followed by database, reliability, and security review. The operator's 2026-10-22 clarification assigns the Ivan stack as the technical owner of the private writer host boundary and the operator as accountable task owner. No individual human contact is named for deployed-grant evidence or transaction-boundary confirmation; this is a contact gap, not an unassigned delegated task. Codex executes local inventory and implementation work. No tests, checks, builds, migrations, live database access, SSH access, or secret inspection were performed for this source note.
