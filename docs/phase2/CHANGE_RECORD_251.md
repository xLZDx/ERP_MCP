# Change Record 251 — S13 versioned nonterminal unknown-outcome route

Date: 2026-10-25  
Status: source candidate only; not qualified, installed, granted, staged, or committed.

## Why

The accepted S13 scope-fence design and `S13-RESOLVE-UNKNOWN-01` require an additive,
versioned replacement for the legacy worker route. Migration 027 revoked the legacy route but did
not define `resolve_unknown_v2`, and `SqlChangeLedger` had no versioned opt-in route. Leaving this
gap means candidate mode correctly fails closed but cannot record a safe nonterminal observation.

## Changes

- Added `change_ledger.resolve_unknown_v2` to candidate migration 027. It accepts a scoped change,
  exact dispatch compare-and-set identity, and immutable receipt/completion/outcome references.
  The typed validator-produced outcome projection is the observation; callers provide no effect or
  attribution booleans.
- The candidate takes namespace 2 and namespace 7 fences, holds the lifecycle row, then takes
  sorted namespace-6 IDs before locking the current record, permit, attempt, and evidence rows. It
  revalidates the complete selected rows and all three attempt-purpose bindings before decisions.
- The first source pass allowed `resolve_unknown_v2` to set `TRIAGE_REQUIRED` while leaving the
  dispatch attempt `POSSIBLY_EXECUTING`. Manual path tracing showed T16 Path A requires a terminal
  attempt, while Path B accepts only the exact conditional-conflict branch. This was a dead-end
  transition, so the route now accepts only a returned-success receipt, class
  `WRITER_CALL_RETURNED` completion proof, and a complete/healthy/determinate V1/V2 outcome. In one
  transaction it terminalizes the exact attempt and clears only its matching private physical-base
  slot, sets `call_ownership=PROVEN_FINISHED`, enters `TRIAGE_REQUIRED`, and appends the linked
  event. The call-ownership hold and business reservation/target/key/lease resources remain held
  for witnessed T16 resolution. `UNKNOWN`, independent-closure proof and entered conditional
  conflict now return `T16_RESOLUTION_REQUIRED` without state/resource/event delta; conditional
  conflict remains `APPLY_UNKNOWN` for Path B.
- The attempt terminal guard now allows a complete determinate returned-call observation whose
  present effect attribution is `PROVEN` or `UNATTRIBUTED`, or whose absent effect is
  `NO_GOVERNED_EFFECT`/`COMPETING_WRITER`. It still requires the signed return, receipt linkage,
  operation-specific scope/target/version consistency, healthy observation, zero uncertainty, and
  matching completion class. Present-only target/version/digest checks no longer reject the valid
  absent-effect branch. T16 Path A is limited to the returned-call proof; Path B continues to
  validate either class-specific proof only for its exact conditional-conflict V3 evidence path.
- The physical-slot release uses the switch, base, scope and namespace-6 identity fences before
  relation-row locks, then retains the lifecycle row before locking record/permit/attempt. It
  refuses a closed/open-barrier slot unless the exact dispatch CAS is in that barrier's immutable
  call set, mirroring the existing terminal writer path. A stale slot, missing call hold, or failed
  attempt/slot CAS aborts the whole transaction.
- Applied the same exact completion/outcome binding in both `operator_resolve_v1` T16 branches,
  before cosign consumption or resource changes. This prevents terminal resolution from relying on
  a completion projection whose class/session/process does not match the attached signed outcome
  and active dispatch attempt.
- Added a pre-DML target-owner assertion to `operator_resolve_v1` for every failed-apply
  (proven-absent) branch. After ranked target-lock rows are locked and the frozen target plan is
  revalidated, the function now requires the exact active-change target tuple to remain owned by
  the resolving change before it consumes the witness cosign or performs terminal/resource updates.
  A missing/changed owner returns `LOCK_PLAN_STALE`; the existing transactional delete/repair
  handback helper remains the final mutation guard.
- Bound `private_writer_record_recovered_terminal_v1` to the exact immutable T16 event tuple. Before
  it registers evidence links or terminalizes the attempt, it now compares the dispatch CAS and
  receipt/completion/outcome/challenge/read-attestation references against the exact
  `OPERATOR_RESOLVE` payload. This prevents a different otherwise valid evidence reference for the
  same attempt from being substituted during post-checkpoint physical-call finalization.
- Restored exact finalizer replay by allowing the attempt-state precondition to reach its existing
  `TERMINAL_WITH_EVIDENCE` lookup-only branch after a successful prior call. Other states remain
  rejected, and the replay still requires a clear physical slot, exact finalized-event identity and
  all immutable evidence links.
- Tightened the recovered-terminal event gate to require the exact T16 `FAILED_APPLY` disposition
  and `checkpoint_required=true` before any evidence-link or attempt/slot mutation. The event's
  `cosign_id` must now use canonical UUID grouping before the subsequent cast, so malformed
  immutable payload text follows the stable T16 refusal path instead of leaking a raw UUID-cast
  error.
- Closed nullable-`CHECK` gaps in the typed outcome projection: V3 completion-proof and read-
  attestation digests must be explicitly non-null before format checks; all outcome versions must
  carry their dispatch receipt ID; and V1/V2 rows must leave V3-only digest/challenge/attestation
  fields null while retaining their matched completion-proof class. The disposable qualification
  prerequisite now includes schema-owner negative fixtures for these row invariants.
- Reconciled the immutability inventory against migration 027's existing `$immut$` and
  `$no_truncate$` trigger-installation blocks. They already cover append-only evidence, history,
  intent, permit, acknowledgement, barrier-call and evidence-link relations plus truncation of
  mutable state/trust-registry tables. No duplicate guards remain in the candidate source; the
  qualification prerequisite now captures these existing predicates and state-preservation cases.
- Corrected the V1/V2 typed row shape after a broader source trace found those versions also compare
  `outcome_dispatch_receipt_id` against the linked writer receipt in terminalization and T16 replay
  paths. All outcome versions now require a non-null dispatch receipt ID; only V3-specific digests,
  challenge, sequence, observation and read-attestation fields are excluded from V1/V2.
- Reconciled the source inventory's earlier deferred-proposal note with migration 027's final
  legacy bridge block: preserved legacy epoch and registry signatures route atomically through the
  namespace-fenced v1 bodies while direct v1 calls remain revoked. Effective grants and bridge race
  behavior remain unmeasured; only the stale source-level dependency was corrected.
- Updated the qualification prerequisite to force a missing/changed active target owner after the
  frozen-plan snapshot and assert the pre-DML `LOCK_PLAN_STALE` result plus unchanged
  current/repair-parent/resource/event snapshots for ordinary and repair paths.
- Updated T16 qualification to mutate each post-commit finalizer reference independently and require
  immutable-event mismatch refusal before evidence-link, attempt, slot, or event changes.
- Added a flag-gated adapter entry and method. The old boolean/UUID method explicitly refuses in
  S13 mode, avoiding legacy fallback. Candidate `EXECUTE` remains revoked from all named roles.
- Updated the scope-fence design, qualification prerequisites, continuation prompt, and backlog to
  identify the candidate's use of typed outcome evidence, the reachable Path A terminalization,
  the pre-DML repair-target owner assertion, and the exact pending qualification.

## Affected contracts and paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Decisions and limits

- The candidate treats `OUTCOME_EVIDENCE_V1/V2/V3` as the immutable observation because migration
  027's private-writer evidence type has no separate `OBSERVATION` record type. Extending the
  trusted record model would be required to pass another observation type.
- The candidate remains ungranted and feature-gated until source review and disposable
  qualification. No runtime, effective-ACL, or installed-schema claim is made.
- No test/check, SQL parser, migration, database operation, COM call, service restart, staging,
  commit, or push was performed for this change.

## Verification state

- Implementation: present in working tree; inherited candidate migration is untracked at baseline.
- Manual review: source tracing found and corrected the T16 target-owner preflight and finalizer
  event-shape gaps described above. An earlier read-only code-reviewer pass found no BLOCKER/MAJOR
  in the operator-resolve/finalizer subset then present; it did not cover the later evidence-row
  constraint and immutability-trigger additions. The broader S13 lock/FK/trigger/effect inventory
  and post-test specialist consensus remain pending; the database-reviewer privilege audit was
  read-only and did not review this code change.
- Runtime: `NOT_RUN`; `S13-RESOLVE-UNKNOWN-01` remains `NOT_RUN`.
- Effective privileges: `NOT_MEASURABLE` until the candidate schema exists in the authorized
  disposable database.
- Commit and push: none.

## Current artifact fingerprints

- Candidate migration 027 (current working-tree fingerprint): `BD6253BA0F3AECE86C98455B05A2F8118F74C828B1FC714BFF357516FE1AD5AC`
- Adapter `sql_ledger.py`: `FE08B6642306AA937BEBD907DF3383002EBEA5A2FEBA4A365E590320D93C0181`
- Scope-fence design: `075E1FE4B1CC1027AE08AA4FC0349952DD5B176C50412C1EE9BC6BE79E5485C4`
- S13 source-final inventory (current working-tree fingerprint): `4C7BA718CF1D7A0F784733AF343F18973412CECD358D1EE50D4515D259F4F7A4`
- S12/S13 qualification prerequisites: `CD4F0572FBA4407917FA54C33D26A8C0F3F6259C7D12AB211168720D9B40EC54`
- Qualification prerequisites (current working-tree fingerprint): `F6E52044DB6055703CDB4F79BBE637986B1AC3E491393A8FD557061E4C72B51B`
- Continuation prompt (current working-tree fingerprint): `2B3A1382069BC0CBD38B82A05F94702227AD249E11810BCACB3DA03442D45C20`
- Operator backlog (current working-tree fingerprint): `27065A6D35780D6020154B326873F86DE2A309DDE353C8872AF81B756AE5A619`
