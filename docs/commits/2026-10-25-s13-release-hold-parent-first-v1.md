# S13 parent-first hold-release candidate

## Change

Added `change_ledger.release_hold_v1` to the uninstalled migration 027 candidate and routed
`SqlChangeLedger.release_hold` through an opt-in `release_hold_s13` adapter entry. The candidate
pre-reads the scoped hold, parses an optional canonical cosign UUID only for the open two-person
`ANCHOR_GAP` branch, then acquires the switch and scope fences, lifecycle row, namespace-6 hold and
cosign identities, and the exact legacy namespace-3 hold arbitration key. It locks a change-bound
record before the hold and selected cosign, revalidates their planned snapshots, preserves the
source cause/replay/proof semantics, and appends the event after the mutation. The exact signature
is revoked from `PUBLIC` and all named application/private roles.

The same adapter change restricts candidate mode to registered v1 candidates and a documented
read-only legacy allowlist. Every other registered legacy mutation/recovery entry fails closed
with `S13_ENTRY_NOT_IMPLEMENTED`; this includes `recover_sweep` and `revoke_stale`. The later `kill_switch_v1` route preserves stop modes and refuses reopening until recovery is qualified.
The ordinary legacy routes remain unchanged with the flag off.

## Why

The legacy implementation locks the hold before reading its optional cosign ID, and may then
consume the cosign through a trigger that checks signer independence. The candidate freezes the
cross-row identity before relation locks and keeps the record parent ahead of hold/cosign children.
It stays opt-in because same-scope legacy writers and effective database grants have not been
qualified for a coordinated cutover.

Also added `revoke_change_v1` and its operator-only no-fallback route. It freezes the scoped record,
related record IDs, token set and zero-effect resources, acquires their namespace-6 and namespace-4
identities, locks target/record parents before token/resource children, revalidates, then invokes
the existing internal cause/state transition core. The candidate caps its planned closure at 200
rows and explicitly revokes direct application/private execution.

Added `revoke_stale_v1` as an ungranted worker candidate and routed `SqlChangeLedger.revoke_stale`
to it only when the private-writer schema flag is enabled. The candidate takes the S13 scope fence and early lifecycle row before namespace-5 sweep serialization, plans at most 20 eligible records with previously failed rows
ordered after never-attempted rows, snapshots records/tokens/targets/resources/failure rows, and
revalidates the complete plan before per-item revoke or committed failure accounting. It locks only
the resource relations changed by `revoke_core`; dispatch permits are not changed by this path. A
manual review corrected the initial fence inversion and large-batch starvation risk. Per-item
event append still needs full cross-path lock-graph review; this candidate is not approved for
installation or grant.

## Affected contracts and files

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Verification and limitations

Manual source comparison only. No SQL parse, tests/checks/build/CI, migration, database operation,
COM call, staging, commit or push ran. The adapter candidate is not a runtime proof; the SQL
candidate remains uninstalled/ungranted, effective grants are `NOT_VERIFIED`, source review is
outstanding, and `S13-RELEASE-HOLD-RANK-01`, `S13-REVOKE-CHANGE-PARENT-RANK-01`,
`S13-REVOKE-STALE-BATCH-RANK-01`, `S13-KILL-SWITCH-STOP-RANK-01`, and
`S13-RETRY-VERIFY-RANK-01` remain `NOT_RUN`. The bounded 20-record sweep behavior and
failure-row fairness were inspected manually but not runtime-qualified. Candidate-mode refusal for
unimplemented legacy mutations is temporary fail-closed behavior, not a replacement for the
missing versioned implementations. The change does not close the full S13 lock map or prove a
source-wide cutover.

Added ungranted `kill_switch_v1` and its opt-in operator route. It retains the legacy exclusive
namespace-2 identity before namespace 7 and the early lifecycle-row lock, permits emergency stop modes, and allows `OFF` only when
the scope is already off; reopening a stopped scope returns `RECOVERY_NOT_READY` until qualified
recovery can prove it safe. `S13-KILL-SWITCH-STOP-RANK-01` remains `NOT_RUN`.

Added ungranted `retry_verify_v1` and its opt-in worker route. It plans and revalidates the record,
target, exact target-owner check row and the full target-lock delete set, all owned key locks for the
record base, open failed-verification holds, retry counter and supplied
evidence IDs before applying the legacy evidence-derived verdict and three-attempt retry state
machine. The candidate caps affected rows and global-ID fences before locking, then takes the hold
cause and target/key conflict identities before rows. It remains a source candidate only; event,
trigger and helper lock closure require independent review and disposable qualification.

Manual source comparison found that the pass path deletes all target locks owned by the record
within its base, while the first candidate plan froze only the expected `target_ref`. Expanded the
plan, namespace-4 set and locked revalidation to cover every target-lock row that the delete can
touch; narrowed key-lock planning to the exact base-scoped delete predicate; added a disposable
case for multiple owned target references. No SQL parse or execution was run. Added an ungranted
`recover_sweep_v1` route. It checks the current eligibility families, including expired approval
nonces, and records a zero-work report only when the scope is quiescent. The adapter-preallocated
run ID is fenced in namespace 6 and explicitly inserted. A populated but quiescent scope preserves
its unresolved/failure counts; eligible work still returns `RECOVERY_NOT_READY` without a run row
eligible work now processes bounded T3 expiry, REVOKE-only VOID approval cleanup, and expired approval-nonce transitions after fencing and revalidating the record/failure/nonce plan; unsupported eligible stages still return `RECOVERY_NOT_READY`. The quiet-run/T3/VOID/nonce candidates and target-lock correction remain unqualified.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later focused qualification: functional-test-reviewer and e2e-runner after coding closes.
- Push/PR requires a fresh GPT-PM approval correlated to the exact final code head.
