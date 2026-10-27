# Change record 246 — reject future-dated signed evidence

Date: 2026-10-25  
Scope: source-only S13 production evidence-verifier correction; runtime remains unqualified.

## What changed

- The shared signer check now rejects `signed_at` later than the trusted `EvidenceTrustSnapshot.loaded_at`, using stable refusal `EVIDENCE_SIGNED_TIME_FUTURE`.
- This check is shared by single-envelope and evidence-set verification, so every signed record must be no later than the one trusted snapshot time used for that verification.
- Updated `S13-PRODUCTION-EVIDENCE-VERIFY-01` to require refusal one time unit after snapshot time and acceptance at the exact-time boundary. Both remain `NOT_RUN` until the post-coding functional/E2E phase.
- Current source SHA-256: `A320C95C4EB71455B2F4BA251C28172F72226C42B104F8C82B5F3953841DCF0D`.

## Why

The design requires non-future signed times and treats the trust snapshot's database-derived time as authoritative. Before this change, the verifier checked signer validity at the signed and snapshot times but did not require the signed event itself to have happened by the snapshot time. A valid key window therefore could accept a future-dated envelope.

## Scope and verification state

- The change does not establish production crypto-provider provenance, trusted snapshot ownership/freshness, installed effective grants, signer provisioning, COM behavior, or database registration safety.
- Static source inspection only. No tests/checks/build/CI, SQL parse, migration, database operation, COM call, listener, stage, commit, or push ran. `S13-PRODUCTION-EVIDENCE-VERIFY-01` remains `NOT_RUN`.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- Later scenario owners: `functional-test-reviewer` and `e2e-runner`; relevant independent reviewers after coding closure.
- Next: continue source closure. After coding completes, qualify future-time rejection and exact-time acceptance alongside signer validity, revocation, and shared-snapshot evidence-set checks.
