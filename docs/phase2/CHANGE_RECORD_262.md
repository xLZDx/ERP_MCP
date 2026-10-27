# Change Record 262 — reuse verified T16 checkpoint on recovery

## What changed

- `checkpoint_operator_resolution` now reads the provider's record for the exact immutable event sequence before using the currently configured signer.
- It reuses a record only when its scope, sequence, event hash and timestamp, sink identity and signature encoding match; it then submits the exact tuple to SQL, whose already-verified-row replay remains authoritative after key revocation.
- If no record exists, the existing sign, write, exact-read-back and Python/SQL verification path remains. Any malformed or mismatched record fails closed before database registration or hold release.
- The candidate SQL routine now restricts new checkpoint rows to active `checkpoint_role` Ed25519 keys and limits exact replay to previously verified rows tied to an Ed25519 `checkpoint_role` key, regardless of that key's current active/revoked status.
- The S13 design note and disposable qualification prerequisites now specify recovery after checkpoint persistence and partial hold release, including key revocation.

## Why

The S13 SQL routine deliberately returns an exact already-verified Ed25519 checkpoint row before checking whether its signing key remains active for new writes. The Python retry path previously always asked the current signer for a new record first. After the original checkpoint had been persisted and the key revoked, a retry could not reproduce the exact provider record and therefore could not resume a partially completed hold-release batch. Reusing the provider record and letting SQL prove exact Ed25519 verified-row identity preserves the database replay contract without requiring the Python key snapshot to retain a revoked public key. The source review also found that candidate SQL did not yet restore migration 019's Ed25519-only guard; both candidate replay and new-write branches now enforce that algorithm boundary.

## Evidence and limits

- `src/business_ai_gateway/phase2/change_ledger/checkpoint.py`: `DispatchGate.checkpoint_operator_resolution` validates the read-back binding and routes exact existing records to SQL before signing a new one; only new records require the current Python verifier.
- `db/phase2/027_private_writer_admission_schema.sql`: candidate `change_ledger.record_checkpoint` returns an exact verified same-scope checkpoint before checking active key status (candidate source only).
- `db/phase2/019_ed25519_action_only.sql`: historical new-checkpoint contract requires `key_algorithm='ED25519'` before signature verification and insertion.
- Candidate migration SHA-256 after the Ed25519 replay/new-write correction: `B239A157BA77793C0BF254AB7B0C4BFDED4223990891A5FC57A933B1039D24C5`.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`: T16 checkpoint continuation contract.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `S13-OPERATOR-RESOLVE-CHECKPOINT-REPLAY-01`.
- An actual read-only `code-reviewer` pass identified a key-retention dependency; the follow-up review found the legacy keyed-hash replay gap. After both corrections, the final review reported no remaining source blocker: SQL checks exact Ed25519 identity on replay and active Ed25519 status for new rows. Review was source-only; exact model/effort was not recorded. No tests, checks, build, CI, parser, candidate-function call, candidate migration, database mutation, staging, commit or push was run. Separate read-only catalog queries against the installed disposable database are recorded in `artifacts/WP2_EFFECTIVE_GRANTS_CURRENT_TURN_2026-10-25.md`. The new replay and failure scenarios remain `NOT_RUN`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. The functional-test reviewer owns the mapped replay scenarios after coding closes; the database reviewer owns effective privilege and SQL replay review. The candidate schema remains uninstalled and ungranted.
