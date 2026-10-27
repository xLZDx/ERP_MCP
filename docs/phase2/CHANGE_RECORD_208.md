# Change Record 208 — fence dispatch-receipt verification against verifier-key mutation

## What changed

- `record_dispatch_receipt_v1` now takes a non-locking verifier-key snapshot after the S13 scope/lifecycle fences and acquires the same key-material advisory identity as registration, approval, and revocation before namespace 6 and record locks.
- The routine now locks the verifier row and compares its complete value with the snapshot before signature verification and receipt/event mutation.
- Missing keys retain `EVIDENCE_UNSIGNED`; a key that appears or changes while planning fails closed as `LOCK_PLAN_STALE`.

## Why

The previous candidate validated a receipt signature against a verifier row without joining the common key-material serialization protocol. This aligns receipt verification with the S13 source lock order and prevents a concurrent key mutation from changing signer material across validation and insertion.

## Evidence and verification state

- Changed source: `db/phase2/027_private_writer_admission_schema.sql`, routine `record_dispatch_receipt_v1`.
- Candidate migration SHA-256 after this change: `FA50C41E08EC16D267D051190FD9D5180B438E6A1C5F052341605478C6EC22E8`.
- This migration was untracked at the start of this turn and already contained substantial candidate SQL. This record attributes only the verifier-key snapshot, material fence, locked-row comparison, and stable refusal behavior above to this change.
- Manual source inspection only. SQL parsing, tests/checks/build, migration, database access, listener startup, COM, staging, commit, and push were not run. Receipt replay and key-race qualification remain `NOT_RUN`; effective grants remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after source coding closes, have the database reviewer inspect the full key-material lock graph and grants, then have functional/E2E roles qualify receipt attachment against key registration/revocation and verify stable replay/refusal outcomes on the approved disposable database.
