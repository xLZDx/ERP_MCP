# Change record 095 — reconcile G1 push report with current remote state

## What changed

- Updated the Russian and English G1 push-status reports to record that the reviewed push through `13b8ee2e067fcd70158b74dc36307d0dfb3332aa` completed and `origin/main` was confirmed at that exact HEAD.
- Removed the stale statement that a new PM decision was still pending and the completed next step to commit the earlier reconciliation as `CHANGE_RECORD_091`.
- Kept the historical PM approval and push evidence for `17900345c88237290c498d73b6f8849c265351d1` intact, while distinguishing the later pushed documentation range.
- Preserved formal G1 `NOT_PASSED`, S13 `NOT APPROVED`, Release 2 `NO-GO`, and production authorization `NONE`.

## Why

The reports described an earlier remote state and contained next-step wording that had already been completed. The remote branch is now confirmed at `13b8ee2`; current status must match that evidence without implying that the push changed formal release gates.

## Decisions and scope

- Pre-edit local HEAD and confirmed `origin/main`: `13b8ee2e067fcd70158b74dc36307d0dfb3332aa`.
- This is documentation-only. No source code, tests, database state, formal gate, release authorization, or production state changed.
- This new local documentation HEAD is beyond the already-pushed remote HEAD and must not be pushed without a fresh exact-head PM decision.
- `.claude/` remains unrelated and untouched.

## Review and verification state

- Compared the stale statements with the current report content and confirmed remote `refs/heads/main` using `git ls-remote origin refs/heads/main`.
- Applied `report_conform.py` to both bilingual HTML reports and ran its directory `--check` as required by the HTML report instructions.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- No push was performed.

## Contracts and paths

- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.html`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html`
- `docs/phase2/CHANGE_RECORD_095.md`

## Acceptance

- Both language versions state the same current pushed remote HEAD and no longer report completed PM/push steps as pending.
- Historical decision details remain available.
- Formal G1, S13, Release 2, and production statuses remain unchanged.
