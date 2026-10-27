# Change Record 268 — fail closed on mismatched recovery key locks

## What changed

- The shared T6c/T6r recovery helper rejects an owned key-lock row whose frozen `base_fingerprint` differs from the selected record's base, returning `LOCK_PLAN_STALE` before row locks or DML.
- Added the same mismatch refusal to both T6c and T6r qualification criteria.

## Why

The helper releases key-lock effects through `release_zero_effect`, which only affects rows matching the selected record's base. The legacy table has no composite owner/base constraint. Rejecting a mismatched row prevents permit cancellation from committing a terminal transition while leaving an owned resource behind.

## Evidence and limits

- Candidate preflight: `db/phase2/027_private_writer_admission_schema.sql:8272-8284`.
- Legacy key-lock DDL and release behavior: `db/phase2/004_change_ledger.sql:266-272,446-470`.
- Qualification criteria: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:972,974`.
- Candidate SHA-256 after this source change: `BEB30AA538520AD1865D1D48DDB185301DC033AA8E638CDBA8F58D97BF1DAC0C`.
- Source inspection only. No SQL parser, tests, checks, build, CI, migration, database/COM operation, staging, commit, or push was performed. Candidate remains uninstalled/ungranted; runtime qualification is `NOT_RUN`, and effective grants are `NOT_VERIFIED`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. The database-reviewer role owns later recovery lock/ACL review; `functional-test-reviewer` and `e2e-runner` own T6c/T6r mismatch and recovery race scenarios after coding closes.
