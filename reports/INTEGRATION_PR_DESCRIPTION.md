Integrate the existing semantic/testbed/RSV/metrics/pilot stack (#2–#8) with the independent
multi-source ACL (#9) and audit outcome (#10) follow-ups on main `8481c0e` so the complete
candidate can be tested together. Merge ancestry preserves each original branch and avoids
duplicating stacked commits. Documentation conflicts preserve historical evidence and identify
the current integrated state.

Validation on code `d05c620` plus schema guard/runtime-audit follow-up: Python/PostgreSQL
137 passed, 1 real-1C skip; migrations 001–009,
role checks, static/security/dependency checks, 12 synthetic scenarios, pinned client 428/1 skip,
metadata 53 and wrapper/image build/smoke pass. Exact installed Node runtime audit: zero advisories.
Fixed the runtime schema guard (7 → 9) and added schema mismatch regression tests.
Whole upstream workspace findings in unused MCP/CLI trees are recorded in SUPPLY_CHAIN_REPORT.md.
Hosted combined checks pending publication.

Scope: FR-A2/FR-A3, FR-C1/C2, FR-D1/D2, FR-E1, FR-F1 and D0–D18 integration evidence.
Read-only/company/capability gates remain enforced; no new COM protocol or copied GPL code.
Official RSV v1.3.0 artifact provenance is recorded, but compiled BSL/COM/company semantics
remain unapproved. Readiness stays DEV READY until combined quality and remaining implementation
gates close; production GO remains false. See reports/PR_INTEGRATION_MATRIX.md and DOD_STATUS.md.

Rollback: use the previous application/adapter version with compatible schema; no destructive
DB rollback or restoration of revoked grants is authorized. Existing PRs remain open as evidence.
