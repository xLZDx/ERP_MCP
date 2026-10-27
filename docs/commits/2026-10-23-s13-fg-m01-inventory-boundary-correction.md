# S13-FG-M01 inventory trust-boundary correction

## Change

Corrected the S13 no-entry terminal-transition contract after local review found that the SQL
routine's arguments carry no startup-inventory token or durable inventory reference. The trusted
Python coordinator now owns the documented exact identity/CAS inventory check at every recovery
entry point. The SQL contract is limited to checks supported by its inputs and durable state:
active serving instance/epoch, exact immutable attempt/CAS and original-owner consistency, and the
process-bound one-way no-entry guard. The contract also requires terminal-routine `EXECUTE` to be
restricted to the private-writer service role so a caller cannot bypass coordinator checks.

## Why

The previous wording assigned the database proof of an in-memory `StartupRecoveryState` membership
that was neither passed to the routine nor represented by an argument or persisted authorization
row. That claim exceeded the interface evidence and obscured the actual trust boundary.

## Affected artifacts and contracts

- `docs/phase2/S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`: corrected the
  `record_recovered_not_invoked` transition and stated the inventory/SQL boundary and required
  candidate grant restriction, including explicit denial of terminal-transition `EXECUTE` to
  public MCP/read and general application roles.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`: corrected the S13-FG-M01
  description and its preceding recovery summary.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: separated
  coordinator-level inventory refusal from SQL active-row, attempt-owner and durable-guard
  assertions; added measured-grant evidence to the scenario.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md` and
  `docs/phase2/OPERATOR_BACKLOG.md`: recorded the clarified evidence boundary and kept grants
  `NOT_VERIFIED` until candidate schema installation and measurement.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`: added a source-anchored
  validator-path crosswalk and an unknown-outcome recovery crosswalk. The historical validator
  locks `records` before advisory namespace 4; the candidate order fences before relation rows.
  The recovery path now requires generation/call freshness to be rechecked against the locked
  record and current attempt/permit before resolution.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: updated the canonical
  source map with validator and unknown-outcome recovery candidates and their still-open
  all-caller dependencies.
- `docs/DOCUMENT_INDEX.md`: added the existing S13 scope-fence design to the normative supporting
  document list and stated its candidate-only status.
- `docs/phase2/OPERATOR_BACKLOG.md`: recorded that generated registry/dashboard artifacts remain
  pending until the post-coding documentation refresh.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: added
  `S13-VALIDATE-RANK-01` so future qualification captures the candidate validator ordering and
  verifies duplicate/override behavior and no partial state.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: assigned the
  existing registry approval/direct-core race scenario the stable ID `S13-REGISTRY-RANK-01` and
  added it to the acceptance matrix, preserving its source anchors, order assertions, replay
  semantics, no-partial-state oracle and test/review owners.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: the registry
  approval/core interleaving remains open in current SQL; the qualification is now explicitly
  mapped by `S13-REGISTRY-RANK-01` rather than being represented only as an unlinked scenario.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`: specified the candidate
  registry approval/direct-core order, including proposal-plan revalidation, verifier-material
  pre-acquisition, proposal-parent/approval-child ordering, scope-fenced status-only revocation,
  and the existing bootstrap/two-person checks. This remains unimplemented.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md` and
  `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: mapped the
  existing duplicate-event defect in `bind_duplicate_override` to candidate replay rule and
  scenario ID `S13-OVERRIDE-REPLAY-01`; exact retries must be lookup-only while new independent
  approvers create exactly one row/event. Current migration remains unchanged.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` and
  `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: split the owner-only
  `add_role_scope` effective-grant assertion into `S13-ROLE-SCOPE-EXEC-01`, separate from the
  binding replay case. This remains `NOT_RUN`; the S13 routine and effective grants are absent
  from the inspected disposable schema.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`,
  `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, and
  `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: mapped the current
  `observe_target` duplicate-event behavior to candidate contract and scenario
  `S13-OBSERVE-REPLAY-01`; exact replay must preserve stored observer identity and be lookup-only.
  No migration changed and no scenario ran.
- The same qualification and design artifacts now link full evidence-envelope collision handling
  to `S13-EVIDENCE-REPLAY-01` and receipt replay identity (including `signer_key_id`) to
  `S13-RECEIPT-REPLAY-01`. These candidate cases remain `NOT_RUN`; no SQL or database state
  changed.
- The acceptance matrix and source inventory now carry the corresponding IDs for the already
  documented source mismatches. They distinguish current behavior from candidate replay contracts;
  no test, migration, or runtime qualification was performed.
- Verification replay and ID-allocation criteria are now acceptance-mapped as
  `S13-VERIFY-EVIDENCE-ID-01` and `S13-VERIFY-PAYLOAD-ID-01`; source and design documents keep
  current versus candidate behavior distinct. Both cases remain `NOT_RUN`.
- The COM clone, licensed identity, fingerprint, effective CT14 rights and complete payload
  property/line map are grouped as `S13-COM-FIXTURE-01`. Existing CT14 records are clone-only
  historical evidence; the current Ivan-clone values remain `NOT_VERIFIED`, and no COM method was
  called in this follow-up.
- Read-only inspection of `ct14_effective_rights.py` found that it first invokes
  `ct14_narrow_ops.prepare_user`, which resets `CT14_NARROW`'s password/roles and may write the
  Users catalog binding. That script was not run; existing `STATUS.md`/CT14 spike rights are used
  only as the recorded clone baseline until the later authorized disposable qualification.
- The source-implemented but unqualified PostgreSQL cumulative lock budget and total transaction
  deadline are now mapped as `S13-LOCK-ERROR-01` and `S13-PG-DEADLINE-01`. The five-second bounds
  remain unmeasured design ceilings pending database/reliability review; no tests were run.
- COM STA-thread confinement/fingerprint/secret lifecycle and bounded result marshalling are
  acceptance-mapped as `S13-COM-STA-01` and `S13-COM-RESULT-01`; source presence is not runtime
  proof, and both are deferred to the post-coding functional/E2E phase.
- `docs/phase2/OPERATOR_BACKLOG.md`: updated the ordered open-work record with the validator
  lock-order candidate and its remaining source-map/design review dependency.
- `docs/commits/2026-10-23-s13-restart-recovery-contract.md`: appended the review finding and
  correction to the ongoing execution record.
- `core/LESSONS_LOG.md`: recorded the general lesson that SQL cannot prove volatile coordinator
  inventory membership without an explicit authenticated/durable input.

## Decision

Use the coordinator-enforced inventory boundary for this candidate contract. Do not add a new
inventory token or durable database authorization table in this correction; that would expand the
schema and security design without evidence that the accepted design requires it. Direct routine
execution remains restricted to the private-writer service role as a required grant invariant.

## Verification state

- Source inspection: `_recovery_transition_authorized` in `src/erp_mcp_private_writer/service.py`
  requires the exact identity/CAS in the current process's `StartupRecoveryState`, matching its
  service instance and epoch, and refuses when restart is latched. The public recovered-no-entry
  method and recovered-success paths call this check before store transitions.
- Documentation consistency was reviewed by reading the changed passages and call sites.
- The command-center document registry/rendered copies were not regenerated during coding; the
  index source edit remains pending its post-coding documentation regeneration workflow.
- Historical lock-order evidence was read directly from `db/phase2/008_change_hardening_b.sql`
  (`validate` at lines 297-310 and namespace mapping at 1512-1522); no historical migration was
  modified.
- Read-only SSH reconfirmed status with `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes
  koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File
  D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`; all nine stack status fields were `True`. A
  names-only inventory with `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes
  koros@100.88.71.74 powershell -NoProfile -Command "Get-ChildItem -Force -Name D:\1c\mcp"`
  listed `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, `venv`, and the stack scripts.
  Two earlier inventory attempts failed at remote-shell quoting/path parsing and were read-only;
  no host state changed.
- No test, build, CI, migration, database write, COM operation, service restart, staging, commit,
  or push was performed for this correction. An accidental `git diff --check` was run once after
  the initial three-document edit; it emitted no whitespace diagnostics and one Git LF-to-CRLF
  warning. It was not a functional or acceptance check and will not be repeated during coding.
- Candidate schema and effective grants remain uninstalled/unmeasured; stale-epoch races and
  disposable qualification remain `NOT_RUN`. The correlated exact-snapshot GPT-PM review must be
  repeated before approval is claimed.
- Registry approval/core qualification is now linked to a stable acceptance ID, but its candidate
  fences are not implemented in current migrations and the scenario remains `NOT_RUN`.

## GPT-PM review coordination

PM Bridge sent request `7a63c4d8-2026-1023-a001-9f02b7c4e1a7` to project ID `erp_mcp`, whose
registered conversation is the ERP_MCP review context. Durable status shows the message was sent,
but the wait remains `uncertain` with no correlated reply. Files were further edited after that
request snapshot, so that request cannot approve the current tree even if a reply later arrives;
submit the current exact snapshot after the existing generation resolves. The bridge-added
`PUSH: AUTHORIZED` text conflicts with the active requirement for a correlated exact-head approval
before push and does not grant push authority; no stage, commit, or push occurred.

## Registry lock-order traceability follow-up — 2026-10-23

Read the final registry source definitions in `db/phase2/010_registry_session_hardening.sql`
and `db/phase2/015_ed25519_signatures.sql`. The current approval function locks the
`registry_changes` parent before inserting the `registry_change_approvals` child and then applies
the selected principal, target or verifier-key core write (`010:327-373`); verifier-key inserts
also reach the signed-bigint material-lock trigger (`017:38-54`). These are current source edges,
not proof of the candidate order or runtime waiting behavior.

The S13 candidate design now specifies an exclusive same-scope fence, early lifecycle-row check,
verifier-material pre-acquisition when applicable, global proposal-ID lock before rows, parent then
approval-child order, core writes under the same fence, and event-chain acquisition after row/core
work. It preserves same-person lookup-only approval replay, two-person/bootstrap authorization,
and status-only key revocation semantics. The existing disposable scenario is mapped as
`S13-REGISTRY-RANK-01` in the qualification matrix and remains `NOT_RUN` because current SQL has
no common fence or namespace-6 prelock.

This follow-up is documentation-only. No SQL source, migration, schema, grant, database row,
runtime, or COM behavior changed. No test, check, build or CI action was run for it. Generated
document-registry and Command Center copies remain pending the post-coding documentation refresh.

## Current continuation evidence — 2026-10-23

The local authenticated MCP route was rechecked through the repository `.venv` using
`LaneEnv.load()`, an in-process `auditor` token (`ttl=900`), `mcp_session`, and a read-only
`source_health` call for `onec-818ha-reference`. The sanitized result was `is_error=false` and
`ok=true`; the wrapper exposed no source ID, status, or error code at that result level. The token
and payload were not printed or persisted. This reconfirms the local MCP health path only; it does
not qualify the Ivan-host gateway, S13 grants, or the private COM writer. The detail was added to
`docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md`.

A separate read-only static cross-reference scan found 52 explicit `GRANT EXECUTE ON FUNCTION`
blocks in migrations 003–026 and 82 distinct function names qualified under `change_ledger`; all
names appear in the source grant/lock inventory. This is name-only coverage and does not resolve
signatures, final grants, effective ACLs, runtime reachability, or complete lock-path coverage. The
source inventory records that limitation. No SQL or application code changed. No test, check, build,
CI, migration, database write, COM call, restart, stage, commit, or push was performed in this
continuation.

An exact-signature follow-up parsed 89 distinct historical `change_ledger` signatures from the
explicit migration grants. The source inventory now records each surviving/final signature and
identifies six older overloads dropped in migrations 007/008; it also corrects the `propose` source
signature. This reconciles source-text grant names/signatures only. Installed or effective grants
remain `NOT_VERIFIED` while the inspected disposable database lacks `change_ledger`.

## Approval-nonce recovery row-order gap

Read the final `recover_sweep` and `approve` sources without executing SQL. `recover_sweep` locks
expired `approval_nonces` before its batch token and record locks (`020:134-142`), while `approve`
locks the record and then the nonce (`009:389-458`). When both select one change, the source admits
a possible nonce→record / record→nonce wait cycle; no deadlock was runtime reproduced. The existing
candidate design already prescribes the parent-first order, but the qualification matrix lacked a
stable identifier. Added `S13-NONCE-RANK-01` and linked the exact source edge, accepted order and
NOT_RUN disposable scenario in the design, source inventory, prerequisites and operator backlog.

This is documentation-only. No migration, SQL source, database row, runtime behavior, or service
state changed. No test, check, build, CI, stage, commit or push was performed.
