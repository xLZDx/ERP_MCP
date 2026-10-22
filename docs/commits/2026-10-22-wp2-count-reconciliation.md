# Change record: Reconcile inherited WP2 test counts

## Change

- Corrected the WP2 classification heading and prose to describe all 14 failures (12 Phase 2 and 2 main-set) plus 13 errors.
- Updated the inherited-defects backlog acceptance wording to classify the same complete 14-failure / 13-error set by evidence-backed cause.

## Why

The identifier table contained 14 failure rows while its heading and acceptance text said 12. The backlog separately records 12 Phase 2 failures and two main-set failures, so the total is 14. This is a documentation count correction; it does not classify an individual test cause or establish runtime acceptance.

## Contracts and paths

- `docs/phase2/artifacts/WP2_INHERITED_TEST_CLASSIFICATION_2026-10-21.md`
- `docs/BACKLOG_INHERITED_2026-10-21.md`
- `core/LESSONS_LOG.md`
- Test authorship and execution remain assigned to `functional-test-reviewer` and `e2e-runner`.

## Decisions

- Preserve each test's cause as unverified until sanitized execution evidence supports classification.
- Do not run tests or database commands under the active restriction.
- Git staging and local commits are authorized; staging deployment remains forbidden. This commit contains the two count-correction paths, this change record, and the linked lesson entry; leave unrelated inherited backlog edits unstaged.

## Verification state

- Read the identifier-only classification artifact and inherited backlog; the artifact lists 13 error identifiers and 14 failure identifiers, and the backlog explains the 12 Phase 2 plus two main-set failures.
- No tests, checks, builds, CI, database commands, migrations, or remote calls were performed for this correction. Git staging and the local documentation commit occur only after exact-patch GPT review; no staging deployment is performed.
