# PR integration matrix — 2026-10-06

Verified main: `8481c0e7c794fc2474efb1b56044363043608698`.
Original local HEAD: `319a12ce6d09b5117021a461af47bed28397d403`.
Original workspace has preserved uncommitted command-center edits and an untracked
`MCP-RSV-Data.zip`; integration uses a separate worktree.

All PRs below are OPEN/Draft and GitHub reports MERGEABLE against their own bases.
Both latest `test` and `odata-upstream` checks are SUCCESS for every head.
The repository's Protect ruleset is disabled and contains deletion/non-fast-forward rules;
it does not enforce required checks. Our full integration checks remain mandatory.

| PR | Base / head SHA | Unique commits / changed files vs PR base | Dependencies / ancestor duplication | Latest CI run | Value / conflict risk |
|---|---|---|---|---|---|
| #2 | main `8481c0e` / `17571de` | 5 / 19 | merged bootstrap already ancestor | 37383219137 | semantic tools, migrations 008–009; registry/audit overlap with follow-ups |
| #3 | #2 `17571de` / `7b9b31e` | 1 / 15 | #2 included | 37383877277 | deterministic seed/scenarios; docs/CI overlap |
| #4 | #3 `7b9b31e` / `319a12c` | 1 / 15 | #2–#3 included | 37384482140 | isolated RSV health boundary; no data route |
| #5 | #4 `319a12c` / `c0ea0c6` | 1 / 5 | #2–#4 included | 37384584340 | legacy demand gate; report overlap |
| #6 | #5 `c0ea0c6` / `1bfde65` | 1 / 12 | #2–#5 included | 37384949997 | protected metrics; observability/settings overlap |
| #7 | #6 `1bfde65` / `ad02e6c` | 2 / 14 | #2–#6 included | 37385454985 | fail-closed pilot manifest; report overlap |
| #8 | #7 `ad02e6c` / `1c01640` | 9 / 31 | #2–#7 included | 37415638873 | movement/posting/cash tools, negative capability evidence, TTL; integration-test/report overlap |
| #9 | main `8481c0e` / `8a7cad2` | 4 / 4 | independent of #2–#8 | 37416049964 | multi-source ACL lifecycle; registry API assumptions and report conflicts require review |
| #10 | main `8481c0e` / `81e8b70` | 2 / 4 | independent of #2–#9 | 37416244057 | audit outcomes/append-only checks; report and integration-test append conflicts |

## Integration strategy

Create `integration/1c-mvp-production-candidate` from verified main.
Merge #8 once: it already contains all unique work from #2–#7. Merge #9, then #10.
Preserve both sides of meaningful test/evidence changes; reconcile status claims against the
integrated code rather than selecting an entire old report. Existing PR branches/history stay intact.
No GitHub approval, merge, or closure is implied by local integration.

## Verification

Integrated merge code SHA: `d05c620` (parents preserve all three delivery lines).
PASS: Python/PostgreSQL 132 passed/1 real-1C skip, migrations 001–009/privileges,
Ruff/compileall/Bandit/pip-audit, 12 synthetic scenarios, docs/vendor tests (within pytest),
pinned client 428 passed/1 skipped, metadata 53 passed, wrapper tests and sidecar image build.
Pilot validator returns NOT_READY as intended; no synthetic production GO.
Initial checks began before environment installation/migrations completed and failed on missing
tables; corrected ordered setup and full rerun passed. Initial pip 25.3 audit failed; upgrading
the disposable venv to pip 26.2.1 cleared the audit without ignoring vulnerabilities.
Follow-up review found runtime schema guard still expected v7 despite migrations through v9.
Fixed the guard and added old/missing/future-schema rejection coverage. Combined rerun:
137 passed/1 real-1C skip. Runtime image smoke PASS: healthy, UID 10001, read-only filesystem,
all capabilities dropped, no-new-privileges, no published ports.
Exact deployed Node dependency audit PASS: 9 package identities, zero advisories.
Whole upstream workspace audit reports 33 vulnerabilities in unused MCP/CLI dependency trees;
those packages are not included in the deployed sidecar. See SUPPLY_CHAIN_REPORT.md.
PENDING: hosted integrated candidate checks.
Individual PR green checks do not establish a green integrated candidate.
