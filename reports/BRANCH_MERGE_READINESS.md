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

Current merge blocker: human manual User and Admin acceptance has not yet been run. Admin
browser acceptance additionally needs a configured non-production OIDC provider and
test identities. Real 1C/native-report, deployed DR/retention and customer-pilot gates stay
external and are not satisfied by the local manual suites.
