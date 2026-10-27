# Change Record 269 — reject cross-scope owned key locks

## What changed

- Extended the frozen key-lock preflight in `cancel_permit_v1`, `revoke_change_v1`, and the shared T6c/T6r recovery helper to compare each row's `tenant_id`, `company_id`, and `base_fingerprint` with the selected record's scope.
- Any mismatch refuses as `LOCK_PLAN_STALE` before ranked row locks or DML.
- Expanded the cancellation, revocation, and recovery qualification criteria to include cross-tenant/company mismatches.

## Why

The legacy `key_locks.owner_change_id` foreign key is single-column. It does not bind the row's tenant/company/base tuple to its owner record. Each candidate route enumerates owned rows by `owner_change_id`, while `release_zero_effect` deletes only within the function's tenant/company/base. A cross-scope row could otherwise pass the earlier base-only guard, be locked under an assumed scope identity, and remain after the owner transition. The new preflight explicitly rejects that inconsistent state.

## Evidence and limits

- Candidate guards: `db/phase2/027_private_writer_admission_schema.sql:7168-7173,8280-8285,9721-9726`.
- Legacy schema and release scope: `db/phase2/004_change_ledger.sql:266-272,446-470`.
- Qualification: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:952,956,972,974`.
- Candidate SHA-256 after this source change: `3633719F9A133A8832C3CDAEF9E55A27FC21B39D6F52AEBDF6AA070824196FEE`.
- Source review only. No SQL parser, tests, checks, build, CI, migration, database/COM operation, staging, commit, or push was performed. Candidate remains uninstalled/ungranted; runtime qualification is `NOT_RUN`, and effective grants are `NOT_VERIFIED`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. The database-reviewer role owns the later foreign-key and lock/ACL review; `functional-test-reviewer` and `e2e-runner` own the mismatch and recovery race scenarios after coding closes.
