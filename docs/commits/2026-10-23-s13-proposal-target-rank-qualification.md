# S13 Proposal and Target Parent-Rank Qualification Mapping

## Change

Mapped the `propose` target-parent and caller-ID conflict path to disposable scenario
`S13-PROPOSE-RANK-01`. Coverage includes target registration/status contention, logical-request
replay, cross-scope global `change_id` reuse, entry-fence and namespace-6 ordering, target-parent
validation, and no-partial-record/event assertions.

## Why

The current `propose` path reads/locks the scoped target before looking up a logical request and
inserting a record using a caller-provided global ID. Candidate source-wide ordering requires the
common scope fence and relevant ID key before business-row/conflict work, while the target remains
the FK parent of the new record. The qualification contract must verify both replay semantics and
parent-first ordering; the current path has no common entry fence.

## Affected contracts and paths

- `db/phase2/008_change_hardening_b.sql:220-285` — current `propose` implementation.
- `db/phase2/004_change_ledger.sql:213-255` — record and target key/FK definitions.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md` — source map and candidate.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — scenario mapping.

## Verification state

Static source/document inspection only. No tests, checks, builds, migrations, database mutations,
service restarts, or runtime contention scenarios were run. The candidate is not implemented or
qualified; S13 remains open.

## Ownership and next action

Operator: accountable task owner. Codex: executor. Functional/E2E roles own future scenario authoring
and execution after all coding is complete; the database reviewer owns later independent review.
Next: continue closing every granted entry, trigger and unique-conflict path against the FK-derived
rank, then freeze the candidate before the assigned test phase.
