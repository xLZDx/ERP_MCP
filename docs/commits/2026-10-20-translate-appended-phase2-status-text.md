# Translate appended phase2 status text to English (2026-10-20)

## What
Operator rule: all text committed to git is English. The phase2 merge appended Russian status text (carried over from origin/phase2/living-model-connectors-reconciliation) to English-translated documents. This commit translates every line that the integration added (88 lines in docs/phase2 plus 5 table labels in two English HTML reports) and leaves everything that was already on BASE untouched.

## Files
- docs/phase2/CONTRACTS_AND_API_RU.md (sections 7-10), STORIES_PHASE2_RU.md (annotated rows), TEST_PLAN_PHASE2_RU.md (S6b-S9 paragraphs), PLAN_PHASE2_RU.md (S7-S10 rows), SPRINT_S6B/S7/S8/S9_PLAN.md (quoted story titles and section names).
- reports/PHASE2_S6B_SPRINT_2026-10-10.html, reports/PHASE2_S9_SPRINT_2026-10-10.html: five bilingual table labels reduced to their English part.
- The "carried over, not translated" HTML comment markers were reworded in English.
Meaning, identifiers, code, table layout and line endings are preserved (byte-preserving script; no whole-file EOL changes).

## Deliberately NOT translated
- Cyrillic inside tests and source that is functional test data: 1C register and analytics names (tests/phase2/test_ap_account_strategy.py), homoglyph/mixed-script fixtures (src/business_ai_gateway/phase2/_identity.py confusables table, test_identity.py, test_validation_coverage.py, test_posted_receipts.py, test_release_*.py, test_jobs_api*.py, test_evidence_attestation.py) and a Cyrillic annotation sample (test_workbench_review.py). Translating them would change what the tests assert.
- reports/PHASE2_S*_SPRINT_*.ru.html: seven intentionally Russian sibling reports that pair with the English reports of the same name. Needs an operator decision (keep as localized deliverables or drop).

## Verification
Script check that `git diff 48884a2c HEAD` has no added Cyrillic line in docs/ or English reports; ruff and tests/phase2 re-run, results in STATE_ERPMCP.md.
