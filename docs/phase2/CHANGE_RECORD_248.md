# Change record 248 — enforce signer-role service separation

Date: 2026-10-25  
Scope: source-only WP5 trust-snapshot policy correction; no trust registry or signature runtime was exercised.

## What changed

- `EvidenceTrustSnapshot` now requires service IDs to be disjoint across all five independent signer roles: `writer_receipt`, `verification_worker`, `completion_supervisor`, `read_attestor`, and `checkpoint_signer`.
- Candidate `private_writer_load_trust_snapshot_v1` now applies the same global role/service collision query before returning snapshot data.
- Empty role sets remain valid. Existing within-role rotation chains and globally distinct public-key enforcement remain unchanged.
- Added `S13-TRUST-ROLE-SERVICE-SEPARATION-01`, requiring positive distinct-role and all pairwise-collision cases; it remains `NOT_RUN`.
- Current source SHA-256: `B681641BCB4208C4BE47911D6ECB5BDCA23230C1D27FC46C81F5E47FBE6B188C`.
- Candidate migration SHA-256: `7259EF8F98C1CEA591540A91BD088261599C8A2543C40AC51F67C740E1543516`.

## Why

The S12 contract assigns these signer purposes separate keys and authorities. The Python snapshot and candidate SQL source previously checked collisions only among writer receipt, verification worker, and read-attestor services; they could accept a shared service ID for the completion supervisor or checkpoint signer. That left a source-level gap before signature verification and allowed the provider and model to disagree about the global invariant.

## Scope and verification state

- This is a trust-model validation only. It does not establish actual service/host identity, key custody, supervisor independence, production build provenance, database grants, or runtime authority.
- Static source inspection only. No tests/checks/build/CI, SQL parsing, migration, database, COM, listener, stage, commit, or push ran. `S13-TRUST-ROLE-SERVICE-SEPARATION-01` remains `NOT_RUN`; migration 027 remains unparsed, uninstalled and ungranted.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- Scenario owner after code closure: `functional-test-reviewer`; security/Python reviewers own the later independent review.
- Next: qualify every role-pair collision and the valid separated case after all in-scope coding completes.
