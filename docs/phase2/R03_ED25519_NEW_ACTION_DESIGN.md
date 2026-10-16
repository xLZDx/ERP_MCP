# R-03 design: Ed25519 for new signed actions

Date: 2026-10-16. Status: proposed for the non-gating S13 prototype; no implementation or deployed cutover is authorized by this design note.

## Goal

Prevent a `KEYED_HASH_STANDIN` verifier key from authorizing a newly written evidence record, checkpoint, permit signature, or dispatch receipt. Preserve the shared verifier's legacy branch for existing internal verification behavior. Do not claim that deployed legacy keys exist or that this proposal closes formal R-03.

## Current behavior and constraints

At HEAD `ec6379e`, migration 015 retains `KEYED_HASH_STANDIN` in `signature_ok` and calls that verifier from `record_evidence`, `record_checkpoint`, and `attach_permit_signature`. Migration 018 is the final implementation of `record_dispatch_receipt`; it checks an active key and `receipt_role`, then calls the same verifier without requiring Ed25519. Migration 017's receipt-purpose uniqueness guard applies to Ed25519 rows only. Migrations 015–018 are checksum-recorded and must not be edited in place. No explicit runtime-accessible historical read-only verifier API was found; `signature_ok` is internal and not granted to runtime roles.

## Options and decision

1. **Guard the four mutating entrypoints (recommended):** add a new migration 019 that requires `key_algorithm = 'ED25519'` at each new-action boundary, while leaving `signature_ok` unchanged. This is the smallest change and does not invent a public historical API.
2. **Disable legacy verification globally and add a historical verifier API:** this changes more callers and creates a new interface without an identified consumer; defer unless a concrete audit read path requires it.

Choose option 1 for the isolated prototype. Keep any future historical verification explicitly read-only and separately designed if a real consumer is identified.

## Design and failure behavior

- Add transaction-wrapped migration `019_ed25519_action_only.sql`, requiring versions 001–018 and replacing only the final function bodies for `record_evidence`, `record_checkpoint`, `attach_permit_signature`, and `record_dispatch_receipt`.
- After existing scope, key existence, active/role, and entitlement checks but before signature verification, reject `key_algorithm IS DISTINCT FROM 'ED25519'`.
- Preserve existing error families: `EVIDENCE_UNSIGNED` for evidence and receipt; `CHECKPOINT_UNAVAILABLE` for checkpoint and permit. Do not mutate key rows or stored signatures.
- Preserve the generic verifier's legacy branch for existing internal/historical verification. Do not expose the generic verifier to runtime roles or claim an operator-accessible historical verification feature exists.
- Retain the current owner/superuser trust boundary. The migration is an additive prototype change; it does not remove the legacy registration exception or prove deployed key custody.

## Compatibility, rollout, and rollback

The change intentionally rejects legacy keys for new writes after migration 019. Existing rows, key material, signatures, and legacy verification code remain untouched. Apply only to disposable test databases in this prototype. Migration failure before commit rolls back the function replacements and migration record. After commit, use a forward correction only; restoring the old function bodies would reopen legacy authorization and requires a separate security decision. Production rollout remains blocked on the non-secret deployed inventory, custody evidence, signer migration/compatibility plan, backup/restore rehearsal, and an explicit deployment approval.

## Acceptance and verification plan

After implementation is complete, `functional-test-reviewer` and `e2e-runner` author and execute focused disposable-PostgreSQL coverage:

1. Each of the four mutating entrypoints rejects a validly signed `KEYED_HASH_STANDIN` key with its existing failure code.
2. Each entrypoint accepts a valid Ed25519 signature and preserves its existing scope, role, replay, and state-transition guards.
3. Include a legacy key assigned `receipt_role` to prove the 017 guard gap is closed at the receipt write boundary.
4. Preserve the direct `signature_ok` stand-in verification unit assertion, while verifying runtime roles still cannot invoke the generic verifier directly.
5. Cover the synthetic end-to-end dispatch receipt flow after harnesses apply migration 019.

Then a fresh `database-reviewer` checks the final migration and tests. No live keys, database, production identity, or formal gate status are used as evidence.

## Remaining unknowns

No deployed key inventory, key custody/provenance, live signature-reference set, or operational production writer was inspected. Schema history does not capture signing-time algorithm/fingerprint for every signature reference. Those facts require separate non-secret deployed evidence and remain open under R-03; G1–G8, S13, Release 2, and production authorization are unchanged.
