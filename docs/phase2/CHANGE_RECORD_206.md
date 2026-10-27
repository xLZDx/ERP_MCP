# Change Record 206 — fence checkpoint signature attachment against verifier-key mutation

## What changed

- `attach_permit_signature_v1` now pre-reads the checkpoint verifier-key snapshot after the S13 scope/lifecycle fences and acquires the same key-material advisory lock used by verifier-key registration, approval, and revocation when material exists.
- The key-material lock is acquired before namespace 6 and before record/permit relation locks.
- After locking the record parent and permit child, the routine locks and compares the complete verifier-key row with the pre-fence snapshot before checking the signature and updating the permit. A key that appears or changes during plan construction fails closed as `LOCK_PLAN_STALE`.

## Why

Without the shared key-material fence, signature attachment could validate against key material while a concurrent key mutation changed or revoked that key. The revised ordering serializes those paths and rejects a changed snapshot before permit mutation.

## Evidence and verification state

- Changed source: `db/phase2/027_private_writer_admission_schema.sql`, routine `attach_permit_signature_v1`.
- Candidate migration source SHA-256 after this change: `33799D25B391C861C9708081D1E29EF208D1470BABE97165A4799848045F1005`.
- The candidate SQL file was untracked at the start of this turn and already contained substantial source. This record attributes only the key-material pre-read/fence and post-row-lock snapshot comparison above to this change.
- Manual source inspection only. SQL parsing, tests/checks/build, migration, database access, listener startup, COM, staging, commit, and push were not run. `S13-ATTACH-PERMIT-SIGNATURE-01` remains `NOT_RUN`; effective grants remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after source coding closes, have the database reviewer inspect the exact key-lock/rank and grant posture, then have the functional/E2E roles qualify attachment against lifecycle transition, same-key revocation, stale snapshots, and zero-delta refusals on the approved disposable database.
