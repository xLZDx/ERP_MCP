# Change Record 267 — close revoke-change key-lock planning

## What changed

- `revoke_change_v1` rejects any owned key-lock row whose frozen base fingerprint differs from its owner record before ranked row locks or DML, with `LOCK_PLAN_STALE`.
- Namespace-4 key-lock identities now use the frozen `(base_fingerprint,key_hash)` values instead of assuming the record's base.
- The planned row cap counts distinct related parent-record IDs.
- Expanded `S13-REVOKE-CHANGE-PARENT-RANK-01` for the mismatched-base refusal, distinct-parent cap, and exact key-lock identity.

## Why

The legacy `key_locks` table references `records(change_id)` without a composite constraint tying its base fingerprint to the owning record. The revoke core releases only rows for the record's base, so a mismatched owned row must fail closed rather than allow terminalization with a stale resource. Deduplicating parent IDs makes the planned cap equal the actual row-lock set.

## Evidence and limits

- Candidate plan check, parent deduplication and namespace-4 identities: `db/phase2/027_private_writer_admission_schema.sql:7162-7209`.
- Legacy key-lock DDL and release behavior: `db/phase2/004_change_ledger.sql:266-272,446-470`.
- Qualification: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:956`.
- Candidate SHA-256 after this source change: `D074EDCBA2704206FAA5952B4E4E4F2FEF522B2ECE12BD352D586514FD389759`.
- Source inspection only. No SQL parser, tests, checks, build, CI, migration, database/COM operation, staging, commit, or push was performed. Candidate remains uninstalled/ungranted; runtime is `NOT_RUN`, and effective grants are `NOT_VERIFIED`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. The database-reviewer role owns later lock and ACL review; `functional-test-reviewer` and `e2e-runner` own the mapped revoke and recovery scenarios after coding closes.
