# Change record 173 — S13 witnessed failed-verification closure

## Scope and reason

Migration 027's S13 candidate already revoked the legacy `operator_close_failed_verify` entry, but
there was no replacement candidate or opt-in adapter route. The frozen T17 contract requires a
versioned, scope-fenced path that preserves the immutable closure, two-person proof, resource and
event outcomes while refusing stale plans and foreign target ownership.

## Changes

- Added `change_ledger.operator_close_failed_verify_v1` to migration 027. It pre-reads complete
  parent/hold/cosign/reservation/target-lock/key-lock snapshots, caps the planned row set, acquires
  namespace 7 and the lifecycle fence before sorted namespace-6 record/cosign/hold identities, then
  the cause-specific namespace-3 halt arbitration lock and signed-sorted namespace-4 target/key
  identities before row locks.
- The candidate locks the current and contested target-lock owner records in UUID order, compares
  complete snapshots, then locks/revalidates the own open `FAILED_VERIFY_HALT`, cosign, optional
  reservation and affected lock rows. It preserves two-person signer checks through
  `consume_two_person_cosign`, refuses a known effect refund and a foreign target-lock owner, keeps
  the record in `FAILED_VERIFY`, and appends `FAILED_VERIFY_CLOSED` after the closure and resource
  effects.
- The exact candidate signature is explicitly revoked from `PUBLIC`, all application roles, the
  private-writer role and the evidence-ingest role. No application grant or S13 enablement was
  added.
- Added the explicit flag-gated adapter selector. Disabled mode retains the old mapping; enabled
  mode names only the candidate, which currently fails closed because its EXECUTE grant is absent.
- Updated the disposable qualification and source continuation with the candidate state and the
  remaining FK-SCC, competing-writer, trigger, caller-cutover and runtime requirements.

## Decisions and boundaries

- Kept this additive and unreachable until the complete parent/child lock graph, row-effect bounds,
  installed ACLs and disposable concurrency cases pass independent review and qualification.
- Preserved the legacy result/error semantics where the frozen candidate contract does not require
  a change. A terminal retry is still a refusal, never a replay-success result.
- This candidate does not close `operator_resolve`, grant runtime access, attest current Ivan-lane
  rights, or implement physical 1C COM writes.

## Verification state

- Source was inspected manually after editing. No SQL parser, test/check, migration, database write,
  COM operation, staging, commit or push was performed.
- A current-turn read-only `database-reviewer` pass found a MAJOR in the target-lock snapshot
  predicate: the RHS still used the old variable name, which could select unrelated same-base
  locks without planning their owner records. The predicate now uses `v_target_ref`; a focused
  reviewer recheck confirmed the target and parent sets now align and found no other concrete
  source defect in the reviewed slice. A cause-specific namespace-3 halt-arbitration lock was
  added afterward. A focused recheck confirmed rank 6 → 3 → 4, identity equality with the existing
  recovery arbitration key, and continued alignment of target rows with their planned parents; no
  additional concrete source defect was found. Reviewer model/effort metadata were not available.
  FK-SCC behavior across competing writers and runtime remain unverified.
- Current file SHA-256: migration 027
  `A8B1BC3BC839F54AA11F33EDB8350EF457308FF6F338BE7DB764451CF00C37B2`; adapter
  `CF0E2CE57AE9CE42B583F7FFF69E716EF7D98F7E9AF621E6DC12696154D7D730`.
- `S13-CLOSE-FAILED-VERIFY-01` remains `NOT_RUN`; effective installed privileges remain
  `NOT_VERIFIED`. FK-SCC order against repair/retry/cosign/hold writers and all concurrent outcomes
  remain open.
- Accountable task owner: operator; executor: Codex. Canonical technical owner for the installed
  PostgreSQL schema/grants is not established by this source-only change.

