# Change Record 286 — close lifecycle-fence and scope revalidation gaps

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 candidate lifecycle-fence admission in migration 027.
- Acceptance: `S13-LIFECYCLE-ROW-PRESENCE-01`, `S13-CHECK-ANCHOR-SCOPE-RECHECK-01`,
  `S13-SCOPE-RECHECK-AFTER-LIFECYCLE-LOCK-01`, and `S13-WRITER-RESOURCE-LEGACY-BRIDGE-01`.
- State: SQL source candidate only. No SQL parse, test/check, migration, database operation, build, CI, staging, commit or push ran.

## Baseline and finding

Migration 027 and the disposable-qualification prerequisite file were already untracked project
artifacts when this turn began. Their pre-edit file hashes were not captured in this turn, so this
record does not claim authorship of their inherited contents.

Nine S13 candidates took a `FOR SHARE` lock on `lifecycle_fences` and then continued without
checking that the scoped row existed: `private_writer_open_hold_v1`, `check_anchor_v1`,
`release_claim_v1`, `revoke_change_v1`, `revoke_stale_v1`, `retry_verify_v1`, `release_hold_v1`,
`cancel_permit_v1`, and `renew_writer_lease_v1`. This left the shared lifecycle boundary absent on
those paths when the fence row was missing. In addition, `renew_writer_lease_v1` declared an
unused `lf_found` and did not reject `NOT_READY` or `RECOVERING` states, even though it extends the
active writer lease and appends an event. Existing candidate paths such as
`bind_duplicate_override_v1` already reject absent, `NOT_READY`, and `RECOVERING` lifecycle state.

A second source pass compared every `assert_scope` route in migration 027 with the post-first-row
lock contract in migration 004. Fourteen mutation bodies held the scoped lifecycle row but did not
recheck authorization after waiting for it: `bump_epoch_v1`, `register_principal_v1`,
`register_target_v1`, `approve_registry_change_v1`, `register_verifier_key_v1`,
`revoke_verifier_key_v1`, `enforce_registry_v1`, `propose_registry_change_v1`,
`set_sweep_policy_v1`, `budget_admin_v1`, `budget_revoke_v1`, `private_writer_open_hold_v1`,
`kill_switch_v1`, and `private_writer_recover_sweep_core_v1`. The two service-binding read APIs and
queued-event helper do not authorize mutation through a role-scope grant and were not changed.
The candidate now calls `recheck_scope_locked(t,c)` immediately after the scoped lifecycle-row
check in each listed mutation body. Disposable qualification must revoke role scope during that
wait and assert `SCOPE_NOT_GRANTED` plus no row/event effects for every reachable installed route.

Each of the nine code paths now raises `LIFECYCLE_NOT_READY` if the locked lifecycle row is absent.
`renew_writer_lease_v1` additionally selects the row into `lifecycle_fences%ROWTYPE` and rejects
`NOT_READY`/`RECOVERING`; the other paths retain their documented transitional-state behavior. The
qualification prerequisite exercises the eight public versioned entries and both callers of the
shared private hold helper without granting the helper directly, plus renewal's recovery-state and
lease/event no-change assertions.

The same source pass found that `check_anchor_v1` did not call `recheck_scope_locked` after waiting
for the scope fence. The original `004_change_ledger.sql:106-112` contract says every mutating API
rechecks authorization after its first row lock so a grant revocation committed during lock wait
is honored. The candidate now rechecks immediately after taking scope and lifecycle fences, before
reading the event head or target/hold rows. A dedicated disposable scenario requires scope
revocation during that wait to refuse with `SCOPE_NOT_GRANTED` and no target/hold/event effects.

## Affected paths and evidence

- `db/phase2/027_private_writer_admission_schema.sql`: missing-row refusals in the nine listed
  candidate paths; `renew_writer_lease_v1` around lines 10110–10128 also rejects recovery states;
  `check_anchor_v1` rechecks scope after fences; the fourteen scoped mutation routes now recheck
  after their lifecycle-row lock.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`,
  `S13-LIFECYCLE-ROW-PRESENCE-01`, `S13-CHECK-ANCHOR-SCOPE-RECHECK-01`,
  `S13-SCOPE-RECHECK-AFTER-LIFECYCLE-LOCK-01`, and `S13-WRITER-RESOURCE-LEGACY-BRIDGE-01`: add
  lifecycle absence, scope-revocation, and lease-renewal recovery-state cases.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: record the 14 additional
  post-lifecycle-lock scope rechecks and their unrun qualification criterion.
- Comparison source: `db/phase2/004_change_ledger.sql:106-112` documents post-lock scope recheck.
- Comparison source: `bind_duplicate_override_v1` in migration 027 around lines 10179–10193
  already rejects absent, `NOT_READY`, and `RECOVERING` lifecycle state.
- Current migration and qualification-prerequisite SHA-256 values are recorded after the complete
  source edit in the final verification section below.

## Review, qualification and rollout

This is source inspection only. The candidate migration remains unparsed, uninstalled and
ungranted; effective privileges are `NOT_VERIFIED`; qualification is `NOT_RUN`. After all in-scope
coding closes, `database-reviewer` should review the complete lock/FK/trigger/effect path,
`functional-test-reviewer` should own the lifecycle-state, scope-revocation and no-partial-effects
assertions, and `e2e-runner` should exercise the old-name/flag-on route and reachable scoped
mutation journey. Do not enable the candidate or infer runtime behavior from this change alone.

## Current source fingerprints

- `db/phase2/027_private_writer_admission_schema.sql` SHA-256:
  `FE726965FBBA6A0EE2B6F34E497D3E21BD5F8B041E6904CFDAC840A9908AED82`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` SHA-256:
  `96F1BA9B6D08C2082814E3A7177141BD4431E4809F86A34B2C6D6ACE2DD5872B`.
- Fingerprints were captured with `Get-FileHash -Algorithm SHA256`; they identify the current
  candidate bytes, not a parsed, installed or runtime-verified migration.
