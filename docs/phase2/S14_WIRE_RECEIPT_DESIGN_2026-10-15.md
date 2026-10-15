# S14 synthetic write-port design: bind clone receipt to canonical wire bytes

Date: 2026-10-15. Status: implementation design for the NON-GATING synthetic lane. Scope is the
existing `SimulatedOneC` plus disposable PostgreSQL ledger path. This is not evidence about COM,
the clone `818HA_p2diff`, identities, key custody, or production.

## Goal

Close R-02 in the synthetic writer-to-ledger path: the receipt accepted by the ledger must contain
the SHA-256 of the exact canonical JSON bytes that the simulated clone received. Keep the approved
typed-payload digest as a separate authorization value; never reinterpret it as a wire-byte digest.

## Current behavior and constraints

`ReferenceWriter` serializes a proposal with `encode_payload`, sends those bytes to `SimulatedOneC`,
and verifies the clone's receipt over their SHA-256. Migrations 012, 016 and 017 instead store and
compare the S12 typed-payload digest. The combined SQL scenario documents the gap and uses a second,
ledger-form signature to complete synthetic cases. That bridge is not a production writer protocol.

S12-APPROVAL-2 stores the approved typed payload. `canonical_json` emits sorted, compact ASCII JSON;
the simulator receives those exact bytes. Receipt requirements remain opt-in in the current ledger;
this design does not silently change that policy or claim a production safeguard.

## Options and decision

1. Keep the current bridge and preserve R-02 as an open limitation. This cannot satisfy a receipt
   acceptance criterion and does not exercise the clone's real receipt end to end.
2. Record both digests: retain `payload_digest` for approval semantics, and add a distinct immutable
   `wire_payload_sha256` to the per-generation dispatch verification. SQL parses and validates the
   payload, requires its exact canonical representation, hashes its UTF-8 bytes, and stores that
   digest before dispatch. Receipt acceptance and the APPLIED guard compare only against this stored
   wire digest. Choose option 2; it preserves existing authorization semantics and makes the ledger
   independently check the bytes claim against the approved payload representation.

## Design and ownership

- Add migration 018 after 017. Extend `change_dispatch_verifications` with nullable
  `wire_payload_sha256`; legacy rows stay NULL and are not backfilled because their sent bytes are
  unknown. Permit a new verified row for a generation only when the wire digest is present; keep
  such rows append-only and unique by (change, generation, typed digest).
- Replace `verify_dispatch_payload` with a fail-closed canonical check. It verifies the current
  approval and typed digest, normalizes JSON `null`/missing POST payload to `{}`, requires any
  supplied text to equal SQL's canonical JSON, computes SHA-256 over its UTF-8 bytes, and records
  both digests in the immutable verification row before `record_call` can dispatch.
- Update the dispatch assertion to require the current generation's typed digest and non-NULL wire
  digest. Update `record_dispatch_receipt` and the APPLIED trigger to require the clone-signed
  received digest to equal that generation's wire digest. Keep receipt text, purpose-bound key,
  dispatch binding, and exact-replay rules intact.
- Update `SqlChangeLedger` documentation only; the SQL function signature stays stable. Preserve
  old receipt and verification rows as historical evidence. An old in-flight generation lacking a
  wire digest fails closed and requires recovery; do not synthesize or backfill a digest.
- The synthetic adapter remains test-lane-only. It forwards the canonical bytes and clone-produced
  receipt unchanged; it must not sign a substitute receipt or hold the clone's private key.

## Failure modes and rollback

Non-canonical JSON, a payload substitution, an unknown old verification row, a wrong clone digest,
or a receipt from another dispatch is refused before APPLIED. A lost response remains unknown and
is never retried blindly. Migration 018 is additive and idempotent, but rollback is not an automatic
schema downgrade: old rows and events remain. A failed prototype deploy is recovered by keeping the
write path disabled and restoring a disposable database snapshot under its existing procedure.
No migration is executed as part of this implementation.

## Verification plan and unknowns

After all sprint code is complete, the functional-test-reviewer and e2e-runner will author and run
focused disposable-PostgreSQL cases for canonical ASCII/Unicode payload bytes, `{}` operations,
typed-digest versus wire-digest inequality, tampered/substituted bytes, actual clone receipt acceptance,
old NULL-hash rows, exact replay, claim generations, dump/restore, and failure before/after write.
No suite or check runs during coding. The existing S12-APPROVAL-2 field set and the synthetic
serializer are treated as the accepted test-lane contract; no real 1C authorization follows.

Open runtime limitations remain: the tests establish only synthetic SQL/clone behavior; receipt
requirement remains opt-in; the real COM adapter, unknown-call ownership, forced termination,
real signer/checkpoint host, real identities, and production ACLs are outside this change.
