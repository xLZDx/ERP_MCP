# Branch and merge readiness

Snapshot: 2026-10-06. Primary integration candidate: `integration/1c-mvp-production-candidate`.
The candidate is not merged to `main`; PR #11 remains Draft until the owner runs the two
manual suites in `docs/QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md`.

| Branch / PR | Current relation to candidate | Disposition |
|---|---|---|
| `bootstrap/1c-day1-production` / #1 | Already on `main`; ancestor of candidate | No action. |
| `feature/admin-control-center-implementation` / #12 | Merged into candidate; PR #12 is MERGED | No second merge. |
| `phase/p1-audit-outcomes` / #10 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; preserve until #11 is accepted, then close as included. |
| `phase/p1-multisource-contract` / #9 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p4-inventory-movements` / #8 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p4-semantic-accounting` / #2 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p5-real1c-testbed` / #3 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p6-rsv-bridge-boundary` / #4 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p7-legacy-demand-gate` / #5 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p8-protected-http-metrics` / #6 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `phase/p9-pilot-evidence-gate` / #7 | Branch HEAD is an ancestor of candidate; zero unique commits/files | Duplicate stacked PR; same disposition. |
| `feature/admin-control-center-design` (no open PR listed) | Diverged from the shared bootstrap base before integration; its tree differs from candidate across 267 files and omits current migrations, runtime, CI and tests | Do not merge this branch head: that would reintroduce the older tree. Its pre-implementation design material was superseded by the implementation branch; keep it as historical design evidence. |

## E2E / Functional Tester lane branches (2026-10-07)

Every lane branch is an ancestor of the candidate (verified with `git merge-base --is-ancestor`); each
was merged with a merge commit, full history kept, nothing squashed. Their Draft PRs into the candidate
close automatically once the candidate is pushed.

| Branch | PR | Content | Disposition |
|---|---|---|---|
| `e2e/local-environment` | #13 | `scripts/e2e/*`, test IdP, compose, Fake1C/sidecar wiring | Included in candidate. |
| `feature/sc-public-coverage` | #14 | fixture-profile provider, aging tools, Fake1C seed data | Included in candidate. |
| `e2e/user-flows` | #15 | User E2E U01-U18 | Included in candidate. |
| `qa/functional-tester-sc01-sc12` | #16 | independent black-box SC01-SC12 | Included in candidate. |
| `e2e/admin-flows` | #17 | Admin E2E A01-A54 | Included in candidate. |
| `fix/review-product` | #18 | security / silent-failure review remediation | Included in candidate. |
| `fix/review-e2e` | none (branch pushed for history; no diff against candidate) | test-adequacy review remediation | Included in candidate. |
| `fix/admin-defects` | none (branch pushed for history; no diff against candidate) | Admin defect fixes P1-P8 | Included in candidate. |

Not merged and not to be merged into the candidate: `main`, PRs #2-#10 (already ancestors), and
`feature/admin-control-center-design`. No historical branch was deleted. PR #11 is the only merge path
and stays Draft.

## Merge sequence after manual acceptance

1. Record User Suite A and Admin Suite B results against exact candidate SHA. Resolve every
   failure; mark any unconfigured IdP/live 1C case BLOCKED with its external dependency.
2. Functional Tester authors and reports SC01–SC12 executable tests using the adjacent
   autonomous assignment. Review their branch and run its CI before inclusion.
3. Update PR #11 body/checkpoint to the tested exact SHA and promote its Draft state only
   when the owner is ready for review. PR #11 is the sole merge path to `main`.
4. Merge PR #11 using repository policy after owner approval. Then close PR #2–#10 as
   already included in the merged candidate; do not merge their stacked heads separately.
5. Keep PR #12 recorded as already merged into the candidate. No action against #12.
6. Keep Admin design-only branch separate unless a specific still-current artifact is
   requested. Its stale pre-implementation claims must not enter the final product docs.

Current merge blocker: human manual User and Admin acceptance has not yet been run
(`docs/MANUAL_ACCEPTANCE_USER.md`, `docs/MANUAL_ACCEPTANCE_ADMIN.md`; the disposable environment
with the test IdP is started by `scripts/e2e/up.ps1`). Automated local E2E (smoke 16, User 52,
Admin 87 + 1 declared EXTERNAL-GATE skip) and the Functional Tester rerun (73 passed / 3 skipped /
2 xfailed) pass on code evidence `8283403`; hosted CI and the exact final head are recorded in the
PR #11 body. Real 1C/native-report, deployed DR/retention and customer-pilot gates stay external
and are not satisfied by the local suites. Production deployment: NO-GO.
