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

Independent focused PostgreSQL runs passed: migration 017 regressions 4/4, migration 016 regressions 7/7, and related
hardening G/D, approval digest, ledger, registry, sweeps, dump/restore and Ed25519 SQL files all passed. Independent
manual migration review found no BLOCKER/MAJOR in wiring, ACL, trigger, concurrency/order or receipt state handling.
Evidence is recorded in the run logs listed in `CHANGE_RECORD_018.md` and the independent verification handoff. The
simulation remains NON-GATING, and no release or real-system status changes.
