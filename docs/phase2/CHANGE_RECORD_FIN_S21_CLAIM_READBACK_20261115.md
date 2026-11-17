# FIN-S2.1 — Bind the post-claim receipt read-back

Date: 2026-11-15
Task: FIN-S2.1 — Put approval decisions in the S16 core
Scope: synthetic, fake-backed S16 approval/apply core only. No real 1C write path is enabled.

## Finding

After `claim_once`, `S16Core.apply()` read the receipt back from the store but checked only its change ID, approval, and S12 record. A store returning the same outer receipt type with altered version, scope, proposal, requester, target version, snapshot, or document reference could therefore send a receipt different from the one validated and approved into begin-apply evidence collection.

## Change

The post-claim read-back now has to preserve the original receipt's immutable identity: change ID, version, scope, proposal, requester person ID, target version, snapshot, document reference, and approval. The claim transition may change `status` and `s12_record`. Comparison exceptions are treated as mismatches. Any mismatch uses the existing pre-`BEGIN_APPLY` claim-release path before the evidence port or apply port is called; a release/read-back uncertainty remains a fixed failure and is not reported as success.

## Acceptance evidence

Added `test_claimed_receipt_identity_mismatch_refuses_before_evidence_and_releases_claim`, parameterized across version, scope, proposal, requester person ID, target version, snapshot, and document reference. Each case asserts refusal, zero evidence/apply-port calls, and release of the known pre-`BEGIN_APPLY` claim.

The focused regression and all other tests/checks are `NOT_RUN` under the operator's rule 4. This record is source and contract evidence only; it does not establish runtime or production acceptance.
