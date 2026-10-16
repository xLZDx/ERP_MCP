# Change record 101 — require Ed25519 for new signed actions

## What changed

- Added additive migration `db/phase2/019_ed25519_action_only.sql`.
- Replaced the final function bodies for `record_evidence`, `record_checkpoint`, `attach_permit_signature`, and `record_dispatch_receipt`, based on their existing definitions in migrations 015 and 018.
- Each write path rejects a verifier key unless `key_algorithm` is exactly `ED25519`, after the existing key identification and authorization checks and before shared signature verification.
- Preserved each existing failure code, function signature, scope and state/replay behavior, security-definer/search-path/owner policy, and public-function revocation. The shared `signature_ok` function and its legacy branch are unchanged.

## Why

The approved R-03 prototype design closes the legacy-key write path at all four mutating boundaries without changing internal legacy verification behavior or inventing a public historical verifier API. This is a non-gating prototype migration only.

## Approval and scope

- Design approval correlation: `c2e4586d-7c34-4637-8247-9f6f8bb0d61a`.
- The migration requires recorded versions 001 through 018 and records version 019 transactionally.
- No verifier key rows or stored signatures are changed.
- This record makes no claim that deployed legacy keys, production writers, or a production exposure exist, and does not close formal R-03 or promote any gate.

## Affected contracts and paths

- `db/phase2/019_ed25519_action_only.sql`
- `change_ledger.record_evidence`: legacy or NULL algorithm fails with `EVIDENCE_UNSIGNED`.
- `change_ledger.record_checkpoint` and `change_ledger.attach_permit_signature`: legacy or NULL algorithm fails with `CHECKPOINT_UNAVAILABLE`.
- `change_ledger.record_dispatch_receipt`: legacy or NULL algorithm fails with `EVIDENCE_UNSIGNED`, including keys assigned `receipt_role`.
- `change_ledger.signature_ok`: unchanged; its internal legacy verifier branch remains available under existing ACLs.

## Verification state

- Tests: `NOT_RUN`.
- SQL checks or static verification: `NOT_RUN`.
- Database commands and migration execution: `NOT_RUN`.
- Production/deployed-key evidence: not collected and outside this prototype change.
