## Current autonomous recovery snapshot — 2026-10-06

Supersedes historical validation counts and blanket closure claims below. PR #11 remains Draft;
Production GO is NO-GO, DoD PARTIAL, frozen scope unchanged.

Verified hosted baseline: c59f07096a1b08c27c33554c29638d4922fe8621 / run 37459728181, BOTH jobs PASS.
Local current suite: 319 passed, 9 external skips; Ruff/Bandit/documentation gates PASS.
Actual SDK subprocess crash/timeout/malformed/recovery/rotation, measured fan-out, Docker
PostgreSQL/Redis outages, pinned promtool assertions and socket-time egress tests replace declared
PASS constants. Four production fan-out mutations are executed/killed. Runtime dispatcher is
MIT undici 8.10.2 with lock/provenance; exact pinned 1C engine remains unchanged.

Current EVID-1 foundation: bounded normalized CSV input, exact confirmed scope/profile, hashes,
private retention references and missing-evidence gate. Native evidence formats, public upload
ACL/storage/audit and DAD rule execution remain OPEN. Ferma/native seeding/observer/L2,
production firewall/capacity/DR/alert receiver, native COM lifecycle and Windows secret DACL remain
separate gates. The document-content fingerprint portability fix awaits a fresh hosted run after
the previous fingerprint failure: exact failed run is 37460339973 at 871ea20.

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
