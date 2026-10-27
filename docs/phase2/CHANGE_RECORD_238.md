# Change Record 238 — preserve NULL validation lookup error in S13

## What changed

- Removed the S13 `validate_v1` precheck that translated a NULL `p_change_id` to `SCHEMA_INVALID`.
- The existing scoped lookup now returns `CHANGE_NOT_FOUND`, matching the retained legacy `validate` signature from migration 008.
- Added a focused source-qualification case for NULL-ID error compatibility.

## Why

Migration 027 replaces the body behind the still-granted legacy signature with a SECURITY DEFINER bridge to `validate_v1`. The candidate's precheck therefore changed the externally visible error for a NULL ID. There is no S13 acceptance requirement to change this legacy behavior; removing the check preserves compatibility and does not alter the lock order for valid IDs.

## Baseline and provenance

The migration 027 candidate was already untracked in the dirty worktree. Its SHA-256 immediately before this focused edit was `BB39B8CEF037F60D4771B83CF4D847A2A54B708F6802C2BF8688A428E37FF1FD`; this includes the separate `record_evidence_v1` work in Change Record 237 from the same turn. Repository HEAD at the time was `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`. No unrelated worktree content was intentionally rewritten.

Candidate SHA-256 after this edit: `EF35B9A75171DDE7AEEA65AD62A5359DCC8AB35C5FFCECB42AB31125A4DE430B`.

## Verification state

- A read-only local `code-reviewer` pass (GPT-6 Luna, low effort) identified the error-precedence mismatch by comparing migration 008's legacy lookup with the migration 027 bridge. A fresh recheck confirmed the NULL lookup now returns `CHANGE_NOT_FOUND` and that valid-ID lock ordering is unchanged. No SQL parsing, tests, or database operations were performed.
- No SQL parse, migration, database operation, test, check, build, or CI was run. Migration 027 remains unparsed, uninstalled, and ungranted; runtime error behavior remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: independently recheck the corrected source, then continue the S13 granted-path/lock crosswalk. Functional/E2E qualification and database review remain after coding closure.
