## Release-candidate snapshot — 2026-10-07 (code evidence `0f0c031`)

Local/automated E2E: GO. Code release candidate: GO. Owner manual User and Admin acceptance: PENDING.
External production gates: listed in `reports/ERP_MCP_FINAL_MVP_CLOSURE_LEDGER.md`. Production
deployment: NO-GO. PR #11 stays Draft and is the only merge path to `main`. The exact final head SHA
and hosted CI run ID are in the PR #11 body/comment (not tracked, so no commit follows a green run).

Local evidence on the exact code: 31/31 verification-matrix steps exit 0; full pytest 1224 passed /
232 skipped (dispositions in the ledger); E2E smoke 29; User U01-U18 52 passed, 0 skipped (U18 = 10 of 12 scenarios PASS + SC06/SC08 declared in Amendment A1, not 12/12); Admin
A01-A54 87 passed + 1 declared EXTERNAL-GATE skip; Functional Tester SC01-SC12 73 passed / 3 skipped /
2 xfailed (SC06 external gate, SC08 needs operator rebaseline). All E2E/FT evidence is synthetic L1
(Fake1C, fake OData sidecar, test-only IdP); it is not native 1C or production evidence. Manual packs:
`docs/MANUAL_ACCEPTANCE_USER.md`, `docs/MANUAL_ACCEPTANCE_ADMIN.md`.

## Previous autonomous recovery snapshot — 2026-10-06

Supersedes historical validation counts and blanket closure claims below. PR #11 remains Draft;
Production GO is NO-GO, DoD PARTIAL, frozen scope unchanged.

Verified hosted baseline: e7898f2166f79aaf829618aab93429d7d3004590 / run 37461088241, BOTH jobs PASS.
Local current suite: 371 passed, 10 environment skips; separate real PostgreSQL capability contract 1/1 PASS.
Privacy boundary: Windows DACL and inherited child permissions, exclusive config creation,
sanitized SDK diagnostics/structured extras and discarded raw stderr. Local focused 29/29 PASS.
729273e hosted run 37465948528 had gateway/OData PASS and Windows FAIL on textual SDDL alias
comparison; binary ACE/SID validation fixes the identity representation issue without widening ACL.
The new 4-job workflow must confirm Windows fix and actual assembled release evidence.
Release assembly validates two SBOM/image provenance pairs, same-revision locks and five executed
JUnit summaries (hashed case IDs/outcomes, no raw test names/payloads). Tested merge revision and
PR head remain distinct; Docker config digest is not claimed as published registry digest.
Actual upstream JUnit produced locally: 429 client cases / 1 skip, metadata 53, wrapper 14.
Ruff/Bandit/documentation gates PASS. DB-backed five-command capability CLI is bounded, read-only,
default aggregate/private export only, never grants authorization or probes OData/COM.
Actual SDK subprocess crash/timeout/malformed/recovery/rotation, measured fan-out, Docker
PostgreSQL/Redis outages, pinned promtool assertions and socket-time egress tests replace declared
PASS constants. Four production fan-out mutations are executed/killed. Runtime dispatcher is
MIT undici 8.10.2 with lock/provenance; exact pinned 1C engine remains unchanged.

Current EVID-1 foundation: bounded normalized CSV input, exact confirmed scope/profile, hashes,
private retention references and missing-evidence gate. Native evidence formats, public upload
ACL/storage/audit and DAD rule execution remain OPEN. Ferma/native seeding/observer/L2,
production firewall/capacity/DR/alert receiver, native COM lifecycle and Windows secret DACL remain
separate gates. The document-content fingerprint portability fix passed hosted verification on
e7898f2 after the historical failure at 871ea20 / 37460339973; the newer CLI batch awaits its own run.

Historical integration narrative:

Integrate the existing semantic/testbed/RSV/metrics/pilot stack (#2–#8) with the independent
multi-source ACL (#9) and audit outcome (#10) follow-ups on main `8481c0e` so the complete
candidate can be tested together. Merge ancestry preserves each original branch and avoids
duplicating stacked commits. Documentation conflicts preserve historical evidence and identify
the current integrated state.

Validation on candidate head `4683586` plus current follow-up: Python/PostgreSQL
138 passed, 1 real-1C skip; migrations 001–009,
role checks, static/security/dependency checks, 12 synthetic scenarios, pinned client 428/1 skip,
metadata 53 and wrapper/image build/smoke pass. Exact installed Node runtime audit: zero advisories.
Fixed the runtime schema guard (7 → 9) and added schema mismatch regression tests.
Whole upstream workspace findings in unused MCP/CLI trees are recorded in SUPPLY_CHAIN_REPORT.md.
Hosted integrated Python/PostgreSQL and pinned OData checks passed on `fa86398` (run `37424817213`),
including the ACL load and PostgreSQL restore drills.

PostgreSQL restore drill on PostgreSQL 16.15: empty→v7→v9 plus synthetic source/company/grant/
capability/profile/audit seed; backup restored into a separate fresh instance; all 9 table row
fingerprints matched; role policy/runtime readiness and 7 PG integration tests passed.
CI now repeats the drill. Production PITR remains external.

File secret rotation/revocation without restart is unit-tested. Synthetic ACL load correctness passed
at 30/50/100/150 sources; local latency is noisy and not a capacity claim. CI repeats this drill.
Business-data fan-out, deployed provider rotation, real 1C and production capacity remain open.

Scope: FR-A2/FR-A3, FR-C1/C2, FR-D1/D2, FR-E1, FR-F1 and D0–D18 integration evidence.
Read-only/company/capability gates remain enforced; no new COM protocol or copied GPL code.
Official RSV v1.3.0 artifact provenance is recorded, but compiled BSL/COM/company semantics
remain unapproved. Readiness stays DEV READY until combined quality and remaining implementation
gates close; production GO remains false. See reports/PR_INTEGRATION_MATRIX.md and DOD_STATUS.md.

Rollback: use the previous application/adapter version with compatible schema; no destructive
DB rollback or restoration of revoked grants is authorized. Existing PRs remain open as evidence.
