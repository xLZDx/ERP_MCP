# Change Record 192 — reject pre-held relation locks across the database

## What changed

private_writer_assert_transaction_v1 now rejects every granted relation lock stronger than AccessShareLock in the current database, regardless of schema. It already rejected all granted advisory locks. The prior predicate limited stronger relation-lock rejection to change_ledger relations, despite the entry contract requiring a fresh transaction before any ranked or blocking relation lock.

## Why

A caller could otherwise enter a protected S13 routine while already holding a row/table lock in a different schema, violating the fresh-transaction/first-lock invariant and allowing an external lock edge to participate in a cycle. The private-writer adapter uses a dedicated pool and bounded top-level transactions; unrelated AccessShareLock metadata/read locks remain allowed.

## Affected contract and path

- db/phase2/027_private_writer_admission_schema.sql
- change_ledger.private_writer_assert_transaction_v1() and every candidate entry that invokes it
- Added qualification row `S13-FIRST-LOCK-DOMAIN-01`: pre-hold a stronger relation lock outside `change_ledger`, verify the S13 entry returns `MUTATION_TRANSACTION_INVALID` before candidate DML, and retain an `AccessShareLock` positive control. The case remains `NOT_RUN`.

## Verification state

Source inspection only. No SQL parser, test/check, build, migration, database call, staging, commit or push ran. Candidate 027 remains unparsed, uninstalled and ungranted. Runtime result is NOT_RUN; effective candidate privileges are NOT_MEASURABLE on the current disposable database. The original standalone snapshot hash was not captured before the next edit to candidate 027; the combined current candidate hash is recorded in `CHANGE_RECORD_193.md`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue all-path S13 source lock/FK/trigger/effect closure; after coding closes, assign the negative cross-schema lock case and AccessShare control to database reviewer plus functional/E2E roles as applicable.
