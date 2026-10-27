# Change record 185 — enforce READ COMMITTED for owned ledger calls

## What changed

`SqlChangeLedger.invoke()` now issues `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` as the
first SQL statement inside its owned top-level transaction and verifies the reported isolation
before role/scope setup or function invocation. The private-writer store applies the same bounded
set-and-readback sequence before any identity query or fence.

## Why

The accepted S13 lock-plan requires authoritative reads after advisory fences to use fresh
`READ COMMITTED` statement snapshots. The adapter owns each top-level transaction and rejects
nested transactions, but previously relied on the server/session default without enforcing or
recording that isolation contract.

## Affected contract and path

- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py` — owned top-level SQL API calls.
- `src/erp_mcp_private_writer/postgres_store.py` — bounded private-writer transactions.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, §§ “Canonical advisory rank”
  and “Complete lock-plan contract” — fresh `READ COMMITTED` snapshots after applicable fences.

## Decisions and boundaries

- Isolation is set as the first SQL command and read back before any role, scope, database-identity
  query, or fence; a mismatch aborts the operation with a fixed internal code.
- The adapter remains the only transaction owner for these calls and still refuses an already
  active connection transaction.
- This change does not install migration 027, prove effective grants, change a candidate selector,
  or qualify PostgreSQL lock behavior.

## Verification state

- Manually inspected both transaction entry orders and compared them with the accepted S13
  contract; the private-writer read-back remains inside the existing transaction deadline.
- No tests, checks, SQL parsing, build, CI, migration, database transaction through this adapter,
  staging, commit, or push was run for this change. Runtime behavior is `NOT_RUN`.
- A separate read-only catalog query against the disposable lane database `business_ai` ran as
  `business_ai_admin`: schema `change_ledger` was absent; there were zero `change_ledger` table
  grants, functions, or named S13 roles in that database. Therefore effective S13 grants remain
  `NOT_MEASURABLE` there; the uninstalled candidate file is not database evidence.

## Remaining acceptance and ownership

This closes only the adapter's explicit transaction-isolation declaration. S13 transaction/lock
qualification remains `NOT_RUN`; the lane lacks the candidate schema and roles, and no SQL parse,
concurrency case, or exact installed-grant query can establish the candidate's behavior. The
operator is accountable task owner; Codex is executor; database-reviewer and the functional/E2E
test roles own their later review and qualification work. Next: finish all source coding, then have
the test owners qualify the additive schema on an explicitly disposable database and obtain the
database/reliability reviews. Do not install the candidate in a live or shared database.
