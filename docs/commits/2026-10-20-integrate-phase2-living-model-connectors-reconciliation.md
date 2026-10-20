# Integrate origin/phase2/living-model-connectors-reconciliation (2026-10-20)

## What
Hand merge of tip 88753c2 (59 commits, 165 files: Phase 2 S5-S10 offline reference modules, tests, docs, reports) into the integration branch (BASE 48884a2c + two docs merges).

## Conflicts and resolution (5 files)
- core/DECISION_LOG.md (2 hunks): both sides only appended entries; kept the union (the branch's Phase 2 entries and BASE's entries).
- docs/phase2/PLAN_PHASE2_RU.md, STORIES_PHASE2_RU.md, TEST_PLAN_PHASE2_RU.md, CONTRACTS_AND_API_RU.md: the English-translation branch rewrote these files, while this branch added Russian implementation-status text (annotated S7-S10 sprint rows, annotated story rows, S6b/S7/S8/S9 paragraphs, contract sections 7-10). Kept the English text and appended every branch-only status text verbatim at the end of each file under a marked section. These appended blocks are NOT translated (follow-up). One changed sentence in TEST_PLAN was rendered as an English note.
- The 143 files added and the 22 modified files merged cleanly. A line-level check (`scripts_ERPMCP/lost.py`) confirms every line the branch added is present in the result except the one TEST_PLAN sentence above (translated).

## Checks
- Deleted-files audit vs HEAD: empty. No conflict markers. All 125 changed .py/.json files parse. Top-level duplicate definitions: only `_LyingStr` twice in tests/phase2/test_posted_receipts.py, which is identical to the branch tip (pre-existing in the branch, harmless in a test module). No same-name test files across directories.
- Focused offline tests (main set): 2 failed, 1851 passed, 192 skipped = baseline (same two pre-existing failures).
- tests/phase2: 1 failed, 6148 passed, 229 skipped. The single failure is tests/phase2/test_evaluation_runner.py::test_compare_returning_wrong_type_or_foreign_authority_is_rejected (known trap: BASE hardened reconciliation dataclasses reject forged authority in __post_init__). It is fixed in the following commit.
- ruff: 35 RUF100 vs baseline 5 (branch files carry unused noqa); cleaned in a later commit.
