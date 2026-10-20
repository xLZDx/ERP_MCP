# Change record 142 — cap unsafe S13 lifecycle activation

## Goal and scope

Implement the CR141 interim safety cap as an additive migration. Migration 022 must remain unchanged because it may already have been recorded in environments; migration 023 prevents the current preparatory API from activating recovery before a reviewed READY-producing coordinator and real writer admission path exist.

## Changes and affected paths

- Added `db/phase2/023_lifecycle_activation_cap.sql`, requiring the complete 001–022 predecessor chain.
- Replaced `lifecycle_begin_recovery` with an unconditional `LIFECYCLE_COORDINATOR_UNAVAILABLE` refusal and revoked execution from all application roles. The migration does not grant access to a new role.
- Added an internal lock-timeout helper that caps lifecycle row-lock waits at five seconds while preserving a shorter caller timeout. Applied it to the event guard, dispatch-permit guard, and writer-epoch row lock.
- Left existing lifecycle rows unchanged. The migration does not clear a `RECOVERING` scope, infer completion, activate a scope, or provide a READY transition.
- Updated the S13 lifecycle design, acceptance map, operator backlog, and S14 packet to distinguish source implementation from pending runtime/review evidence and to retain the physical-writer overlap as open.
- Regenerated `governance/DOCUMENT_REGISTRY.md` with `node scripts/build_document_registry.mjs`; the generator scanned four refs and reported 209 tracked paths and one local-only Markdown path before this commit.

## Evidence and limitations

- Migration SHA-256: `73C30BB18301B0CDFAA7D36C53870E7316E6A3EFAC7078E402368BA496799F09`.
- Source implementation is present locally. The registry generator completed with exit code 0. PostgreSQL application, disposable DB tests, and DB/reliability/security review are `NOT_RUN` pending the post-coding agent phase.
- No shared/live database or production data was accessed; no migration was applied.
- The physical call can still outlive its admission transaction because no operational writer/service boundary is wired here. Migration 023 only disables the currently exposed recovery action and bounds relevant row locks; it is not a physical dispatch fence.
- Formal S13 remains `NOT_STARTED / NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`.

## Ownership and next action

- The operator remains accountable for delegated project closure; GPT/Codex implements the local safety cap.
- `functional-test-reviewer` and `e2e-runner` own focused disposable PostgreSQL scenarios for role denial, structured refusal, unchanged lifecycle state, and bounded lock waits. `database-reviewer`, `reliability-reviewer`, and `security-reviewer` own their corresponding source/evidence reviews after test execution.
- No shared/live migration activation is authorized. Fresh exact-head GPT-PM approval remains the push gate.
