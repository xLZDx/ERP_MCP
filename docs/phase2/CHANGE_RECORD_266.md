# Change Record 266 — close cancel-permit key-lock planning

## What changed

- `cancel_permit_v1` now rejects an owned `key_locks` row whose frozen `base_fingerprint` differs from its selected parent record, using `LOCK_PLAN_STALE` before ranked row locks or DML.
- The namespace-4 plan now derives every key identity from the frozen row's own `(base_fingerprint, key_hash)` rather than assuming the parent base.
- The 200-row lock cap now counts distinct planned parent-record identities, matching the later signed-order lock set.
- Expanded `S13-CANCEL-PERMIT-RANK-01` with the mismatched-base refusal, distinct-parent cap, and exact namespace-4 identity requirement.

## Why

The legacy `key_locks` table has a single-column foreign key to `records(change_id)`, not a composite invariant tying the row's base fingerprint to its owner record. `release_zero_effect` only changes key-lock rows matching the record's base. The candidate must therefore reject an inconsistent owned row before state changes and must not derive an advisory identity from an assumed rather than frozen key-lock value. Deduplicating parent IDs also prevents duplicate references to one record from consuming multiple units of the cap.

## Evidence and limits

- Candidate size check, base-consistency refusal, parent deduplication, and lock identity: `db/phase2/027_private_writer_admission_schema.sql:9697-9749`.
- Legacy key-lock DDL and release behavior: `db/phase2/004_change_ledger.sql:266-272,446-470`.
- Qualification: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:952`.
- Candidate SHA-256 after this source change: `D9FAE6DF318AFBF23D59AD391B08FB10715A06211B7AFECFA597FE2825228F75`.
- Source inspection only. No SQL parser, tests, checks, build, CI, migration, database/COM operation, staging, commit, or push was performed. Runtime acceptance remains `NOT_RUN`; effective candidate grants remain `NOT_VERIFIED`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. The database-reviewer role owns the later SQL lock/ACL review; `functional-test-reviewer` and `e2e-runner` own the mapped cancellation and recovery races after coding closes.
