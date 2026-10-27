# Change Record 209 — fence signed evidence recording against verifier-key mutation

## What changed

- `record_evidence_v1` now snapshots verifier-key material after the S13 scope/lifecycle fences and takes the matching key-material advisory lock before namespace 6 and relation-row locks.
- It then locks the verifier row, compares the complete row with the pre-fence snapshot, and only then checks signer authorization/signature and proceeds with evidence replay or insertion.
- A missing key retains `EVIDENCE_UNSIGNED`; a key that appears or changes during the plan fails closed as `LOCK_PLAN_STALE`.

## Why

Signed evidence must be checked against stable registered signer state. The source candidate now follows the same key-mutation fence used by other S13 signature-dependent entries and preserves failure-before-write behavior.

## Evidence and verification state

- Changed source: `db/phase2/027_private_writer_admission_schema.sql`, routine `record_evidence_v1`.
- Candidate migration SHA-256 after this change: `5912B20DAA735D9A78415B45DE34A616FC031B70F5403BBFB70A18F20BB51FF3`.
- This migration was untracked at the start of this turn and already contained substantial candidate SQL. This record attributes only the verifier-key snapshot, material fence, locked-row comparison, and refusal behavior above to this change.
- Manual source inspection only. SQL parsing, tests/checks/build, migration, database access, listener startup, COM, staging, commit, and push were not run. `S13-EVIDENCE-REPLAY-01` remains `NOT_RUN`; effective grants remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after source coding closes, have the database reviewer inspect the complete signer-key lock graph, then have functional/E2E roles qualify evidence replay against signer registration/revocation and verify zero-delta stale-plan refusals in the approved disposable database.
