# Change record: bind repeated synthetic policy lines separately

Date: 2026-10-22  
Scope: WP3 exact-line exception precision for synthetic profile fields.

## What changed

- Added occurrence-bound `(path, line, normalized-line SHA-256)` exceptions for the six repeated 1C metadata field lines at lines 84, 85, 103, 163, 164, and 172 of `scripts/synthetic_fixture_profiles.py`.
- Updated the scanner-policy record and lesson log to distinguish the reviewed synthetic occurrences from 15 withheld duplicate-hash exceptions in two source-evidence paths.

## Why

The scanner requires exact occurrence identity. Identical semantic fields in repeated synthetic schema blocks should remain unchanged, but a digest-only exception would also authorize any duplicate at another line.

## Review and verification

- The six lines were inspected as synthetic schema field names; no source/customer values were involved or emitted into this record.
- GPT-PM previously approved the scanner's tuple-enforcement mechanism for exact patch SHA-256 `D787DA7D451CB8155B0A9353B74BD902875283680B53A44297216E47F3CF1CB3`; this follow-up changes the allowlist and is not covered by that approval.
- No tests, checks, builds, CI, or migrations were run. Scanner behavior and full WP3 acceptance remain unverified/open.

## Ownership and next step

- Accountable owner: operator. Executor: Codex.
- Next: obtain a fresh exact-diff GPT-PM review before local commit; keep the remaining source-evidence duplicates unexcepted until their exact occurrences can be safely reviewed.
