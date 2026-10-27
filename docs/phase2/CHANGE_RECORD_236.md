# Change Record 236 — fence owner role-scope provisioning

## What changed

- Updated the existing owner-only `change_ledger.add_role_scope(text,text,text)` definition in the uninstalled S13 migration candidate `027_private_writer_admission_schema.sql`.
- Preserved the owner check, argument/role validation, and idempotent `ON CONFLICT DO NOTHING` behavior, then added the first-lock transaction guard and namespace-7 scope fence before the `role_scope` insert.
- Explicitly revoked `EXECUTE` from `PUBLIC` and all application roles. The function remains available only to its database owner/authorized owner path; no application grant was added.
- Reconciled the source-final lock inventory so it distinguishes this implemented-but-uninstalled candidate from installed grants and runtime qualification.

## Why

The legacy function inserts a key covered by `role_scope_uniq` without joining the common S13 scope order. The source inventory classifies this function as owner-only provisioning rather than a runtime mutation, but requires the scope fence if it remains an online operation. The candidate can now serialize that unique-key path without widening runtime reachability.

## Baseline and provenance

`db/phase2/027_private_writer_admission_schema.sql`, `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`, and `core/LESSONS_LOG.md` were already untracked/modified in the dirty worktree before this turn. Their exact pre-edit file hashes were not captured in this turn. This record and its corresponding lesson were added in this turn; no unrelated worktree content was intentionally rewritten.

## Verification state

- Source compared with the legacy definition in `db/phase2/004_change_ledger.sql` and the namespace-7 requirement in `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md` and `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`.
- One read-only local `code-reviewer` pass (GPT-6 Luna, low effort) reviewed the candidate function and the x64 COM guard against HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c` plus their working-tree contents; it found no material issue. Reviewed SHA-256 values: migration 027 `B256C45734FD6DFA6151B2EB28A92C669C66F884C30F7DC196C6009F69C127FA`, `windows_com_lane.py` `1C737F09FED6B1389D7B3A6253153F3ADCF013BA90FF72A697C2A6619660F04C`, and `com_sta_lane.py` `D57788D6EAD00C053DE026C79D01FF47B6665E6E135B9793425C2369CB8750CD`.
- No SQL parse, migration, database call, test, check, build, or CI run was performed. The candidate remains uninstalled and ungranted; effective owner/runtime privileges and concurrent unique-arbitration behavior remain `NOT_RUN`.
- This does not close the all-path source lock graph or qualify the private writer.

## Ownership and next step

Accountable owner: operator. Executor: Codex. The existing Ivan stack owns its host/connection boundary; no separate technical owner for database role administration is established in the canonical records. Next: continue the source lock/conflict and granted-routine crosswalk, then complete all coding before the designated functional/E2E phase and database review.
