# S4 R2-US-016 promotion evidence design

Status: candidate design for review. The historical bounded S4 acceptances stay in force. This document does not accept TC046–TC048.

## Current and retained implementation

- Current `promotion.py` checks attestation identity, approval, expiry, revocation, reviewer independence, and the expected head version before calling `promote_head`. `ports.evidence_digest` binds a revision digest and evidence reference; it does not hash the bytes at the reference.
- Retained commit `adc5ec7` adds a PostgreSQL port and Admin API wiring. The API retrieves the observed revision digest from SQL and passes it with the evidence reference. That design still needs an independently authenticated binding to immutable artifact bytes. Preserve the historical patch for comparison without importing its API, role provisioning, or settings wholesale.
- `artifact_vault.py` hashes bytes on insertion and provides scoped, access-checked `verify_evidence` against the stored digest. Verification does not hash content again on read. A provider adapter must hash the retrieved bytes, or prove an equivalent immutable read guarantee, before it can satisfy this contract.

## Proposed contract

1. Resolve the caller from authenticated context and authorize the exact tenant, source, and company before resolving any evidence. A trusted resolver maps the scoped revision and attestation to an immutable artifact version and its expected content digest. Caller-supplied references are lookup keys only.
2. Verify the bytes of the scoped immutable version against the trusted digest. Missing, revoked, ambiguous, mismatched, inaccessible, or unavailable evidence must stop a new promotion before its write call. Keep the revision/reference digest check as a separate invariant.
3. Choose one transaction authority for promotion eligibility. The bounded design pins a content-addressed artifact version and digest in a durable eligibility record. Register it only after authenticated byte verification and confirmation that the version cannot be changed, removed, or revoked independently of that record during use. Promotion and eligibility revocation must take the same scope lock, and promotion must recheck the eligibility record under the lock before updating the head. The existing SQL attestation and source-lock checks do not cover a separate provider's revocation. A provider whose pinning or revocation semantics cannot satisfy this contract is ineligible for durable promotion.
4. Persist a versioned canonical fingerprint with the scoped acceptance ID in the same transaction as the head update. It includes tenant, source, company, model, operation, requested rollback version when applicable, expected head version, target revision, authenticated requester and approver, attestation ID, evidence reference, immutable artifact version and content digest. Exact replay returns the original outcome. A changed fingerprint with the same acceptance ID is refused. Recovery uses authorized read-back of the durable fingerprint and outcome; an unknown result must not dispatch another write until it is reconciled. Preserve historical entries without a fingerprint as historical records; they cannot prove replay under this contract.
5. Keep this internal model operation separate from the read-only 1C data plane. No new public route is required for the bounded contract.

## Evidence required

| Criterion | Observable behavior |
|---|---|
| TC046 | Authorized promotion of the expected version uses verified immutable bytes. Missing, mismatched, foreign-scope, revoked, or unavailable evidence causes zero writes. If eligibility revocation wins the scope lock after byte verification and before promotion, promotion refuses without changing the head. |
| TC047 | Two concurrent approvals with one expected version produce one accepted head and one conflict. Exact replay returns the original result; a changed request with the same acceptance ID is refused. |
| TC048 | Rollback to an incompatible or unauthorized target causes zero writes. Losing the response after commit does not create a second acceptance. |

First implementation slice: an internal verifier with a scoped reference and digest contract, integrated before the write boundary in an offline adapter. A durable eligibility record, acceptance fingerprint persistence, a qualifying provider, an authenticated production caller, and runtime qualification require their own evidence. Existing test and review receipts are historical until mapped to the chosen implementation.
