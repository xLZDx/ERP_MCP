# Change record 076 — correct the G1 restore scope-revocation assertion

## What changed

- Replaced the direct `living.assert_scope` call in `assert_revoked_scope_is_denied` with an observable authorization check through `living.observations` under the existing `living_reader` transaction.
- Added a pre-deletion visibility assertion (`visible_before_revoke > 0`) so the post-deletion empty result cannot pass vacuously.
- Added the post-deletion assertion (`visible_after_revoke == 0`) to prove that the already-open context no longer sees scoped observations through row-level security (RLS).
- Set the transaction isolation level to `READ COMMITTED` before the visibility queries so the post-deletion statement reads a fresh snapshot even if the disposable server uses another default.
- Preserved the separate fresh-context assertion that `living.set_scope` raises `P0001/SCOPE_NOT_GRANTED` after its grant is deleted.
- Updated the focused evidence packet, operator backlog, SDLC state and S14 status to distinguish the initial failing run from the unverified corrected test.

## Why

`living.assert_scope` is internal security plumbing and is intentionally not executable by `living_reader`. The old test invoked it directly, so PostgreSQL returned `42501` before the scope guard ran. Granting that helper to the reader would weaken least privilege. The corrected assertion observes the user-visible consequence of revocation through the allowed RLS-protected read boundary.

## Decisions and scope

- No production SQL or runtime grants changed.
- The initial focused run at committed HEAD `4b9f3b08b4e75359b549bda75d6f6ec3307f248e` reported 46 passed and 1 failed, with the restore scenario failing at the invalid direct helper call.
- The explicit-COMMIT E2E case passed at that baseline; the restore scenario failed at the same helper call.
- A first intermediate rerun caught stale result-shape assertions. The test owner corrected them; the final retry was interrupted when the current instructions prohibited the required test invocation. The corrected diff is `NOT_RUN` and no pass is claimed.
- `database-reviewer` and `silent-failure-hunter` reviewed the corrected semantics and found no remaining issue; the database reviewer confirmed the explicit transaction isolation statement is correctly placed before queries.
- The formal G1 gate remains `NOT_PASSED`; production authorization remains `NONE`. Local push readiness remains `NOT_READY` pending permitted exact-head test evidence and fresh exact-head GPT approval.
- The correction is committed as `69857fd`; this commit identity does not change the missing runtime evidence.

## Review and verification state

- Implementation owner: `functional-test-reviewer` (GPT-6 Luna, low effort), test file only.
- Database review: `database-reviewer` (GPT-6 Luna, medium effort), read-only SQL/RLS semantics.
- Failure-path review: `silent-failure-hunter` (GPT-6 Luna, low effort), read-only assertion validity.
- Runtime verification of the corrected test: `NOT_RUN` because the current workspace instruction prohibits the focused pytest invocation.
- No schema migrations, database grants, production data, or production systems changed.

## Contracts and paths

- `tests/phase2/test_g1_restore.py`
- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`

## Acceptance

- The regression assertion first proves the reader can see fixture rows, then proves the same open context sees none after its grant is removed.
- The fresh-context `set_scope` denial remains separately asserted.
- A test-agent rerun and independent review are still needed before this change can be called verified or pushed.
