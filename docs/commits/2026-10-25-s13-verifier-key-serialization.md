# S13 candidate verifier-key serialization correction

## Change

In the additive, ungranted routines in `db/phase2/027_private_writer_admission_schema.sql`:

- Kept the accepted S13 order: namespace 7, the early lifecycle-row exception, the exact legacy verifier-material advisory lock, then sorted namespace-6 `verifier-key-id:v1:` before verifier row/index work.
- Added that namespace-6 key-ID identity to direct registration, verifier-key approval, and direct revocation after material locking.
- Direct revocation resolves immutable key material without a row lock and updates only the matching observed material, so a concurrent key insertion after a missing-key observation remains ordered as a later registration rather than being revoked accidentally.
- Direct revocation preserves the legacy `NULL` key-ID behavior: after transaction/scope/operator checks, it returns successfully without fences, row access, mutation, or event.

## Why

Manual source inspection found that direct registration/approval did not serialize on a namespace-6 key-ID identity, while revocation did not share the verifier-material lock. The implementation follows the current design's lifecycle-first exception and then aligns registration, approval and revocation on one material/key-ID order before verifier row/index work.

## Scope and compatibility

- Only additive, explicitly ungranted migration-027 candidate functions changed.
- Legacy routines, default adapter routes, existing grants, data, COM behavior and public MCP/API contracts are unchanged.
- Candidate routing remains controlled by the explicit S13 schema flag and is not enabled by this change.

## Verification state

- An actual read-only `database-reviewer` pass found one MINOR mismatch: a NULL key ID reached the global-fence helper and failed where legacy returned a no-op. Added the authenticated early return; focused follow-up found no remaining issue. No BLOCKER/MAJOR was reported. Reviewer model/effort unavailable.
- Manual source inspection only; no SQL parse, tests, checks, build, CI, migration, database query/write or COM call ran.
- Current whole-file migration 027 SHA-256: `3BF87F1989953A0124AC6FA2CC4263CA991C1FDA6788FE85B4851F9B1844A7D0`.
- Key registration/approval/revocation races remain `NOT_RUN`.
- Effective PostgreSQL grants remain `NOT_VERIFIED`.

## Ownership and next gate

- Accountable task owner: operator.
- Executor: Codex.
- Later database grant/lock review: `database-reviewer` role.
- Later behavior qualification: `functional-test-reviewer` and `e2e-runner` roles after coding is complete.
- Push/PR still requires a fresh GPT-PM approval for the exact final code head.
