# Change record 017 — receipt hardening

## What changed

- Added `db/phase2/017_receipt_hardening.sql` after migration 016.
- Carry receipt-required markers when claim generation advances, reject late receipts after a change leaves APPLYING, and prevent one Ed25519 public key from crossing between `receipt_role` and another verifier role. Existing conflicting rows make migration fail closed.
- Added focused regression coverage in `test_change_hardening_i_sql.py` and updated the 016 role test to assert the newly enforced registration boundary.
- Added migration 017 to the shared PostgreSQL harness, dump/restore migration list, and the 16-to-17 migration length assertions.

## Why

Review of migration 016 identified three minor gaps: a repeated claim did not inherit receipt requirements, a receipt could be appended after terminal completion, and the same public key could be registered for different purposes.

## Contracts and paths

Affected contracts are claim-generation fencing, dispatch receipt evidence, verifier-key purpose separation, and the ordered migration chain. Migration 017 preserves existing 016 entry-point grants and repeats the final `SECURITY DEFINER`, pinned `search_path`, `ledger_owner`, and no-`PUBLIC EXECUTE` wiring pattern.

## Verification state

Code and focused SQL tests are implemented. PostgreSQL tests, independent verification, and catalog/ACL runtime inspection are NOT_RUN at this record; they are scheduled after all in-scope code is complete. The simulation remains NON-GATING, and no release or real-system status changes.
