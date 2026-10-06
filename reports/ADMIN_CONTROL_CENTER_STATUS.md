# Admin Control Center — implementation status

Branch: feature/admin-control-center-implementation
Baseline: origin/main at branch creation
Status: local implementation complete through the testable ACC scope; external pilot/deployment gates remain.

## Implemented

- ACC-00: accepted ADR-0007 and C3 architecture boundary.
- ACC-01: distinct admin OAuth audience/scope and role-aware read API.
- ACC-02: packaged live same-origin Admin UI with OIDC BFF session.
- ACC-03: append-only admin audit, idempotency, row versions, exact grant revoke.
- ACC-04: safe source probe, egress host/CIDR policy, source create/update, capability refresh.
- ACC-05: company create/update and source/company-separated UI.
- ACC-06: drift acknowledgement and semantic profile create/mapping/validate/retire APIs.
- ACC-07: DB-backed platform roles, bootstrap/revoke CLI and delegated source boundaries.
- ACC-08: built-in business role/capability model, assignments, overrides and runtime enforcement flag.
- ACC-09: validated company-scope mappings and onec_company_read server-injected organization filter.
- ACC-10: testable hardening complete — session/CSRF, DNS pinning, bounded access explanation, rate limits, credential checks, scans, browser/DB/Redis integration and restore. Pilot remains external.

## Deliberately not claimed

The following require the target environment and cannot be truthfully closed locally:

- real corporate IdP client/login evidence;
- real secret-store integration for target deployment;
- approved production network egress/firewall evidence;
- real 1C source onboarding/pilot evidence;
- backup/PITR restore rehearsal for target production database;
- measured target-environment load/SLO evidence;
- production pilot and PRODUCTION GO.

## Local evidence

Final local verification on the implementation working tree:

- compileall: PASS;
- pytest with disposable PostgreSQL and Redis: 420 passed, 1 skipped in 27.60s;
- the remaining skip is tests/test_real_1c_integration.py because ONEC_TEST_BASE_URL is not configured;
- Ruff: PASS;
- Bandit: PASS;
- pip-audit: no known vulnerabilities;
- PostgreSQL 16 migrations 001-011 applied from an empty database: PASS;
- database privilege policy for business_ai_app, business_ai_admin and business_ai_control_api: PASS;
- PostgreSQL admin mutation/integration tests: PASS;
- schema 7→11 upgrade in a clean disposable database: PASS;
- dump/restore into a separate disposable database: PASS; restored schema 11 and privileges PASS;
- wheel build: PASS; business_ai_gateway/static/admin.html is packaged;
- Admin UI JavaScript syntax check: PASS;
- headless Chrome Admin UI browser contract: PASS for navigation, mutation retry/idempotency, CSRF, untrusted-label escaping, dialog focus, narrow viewport and 200% zoom.

Fixtures created by this continuation: erpmcp-acc-final-20261006 (PostgreSQL),
erpmcp-acc-redis-final-20261006 (Redis) and erpmcp-acc-browser-final-20261006 (completed
Linux browser run). Existing worktrees/containers were not removed/reset. No customer action
or main merge was performed.

## Adversarial review

No unresolved BLOCKER/MAJOR findings in the testable ACC implementation. Resolved: login-state
race; logout resurrection/CSRF bypass; step-up; delegated connection repointing; stale semantic
reuse after connection changes; filter escape/navigation expansion; idempotency races/failed
keys; replay requiring fresh source I/O; numeric company-ID widening; malformed/overage groups;
indefinite signing-key cache; elevated DB credentials; unbounded grant evidence; oversized/
encoded responses; raw callback access logs and arbitrary probe evidence strings.

Minor limitation: compact UI inline scripts/styles under same-origin CSP. Labels are escaped
and browser-tested; external assets and stricter CSP can be a later frontend change. Target
accessibility/load/pilot evidence remains external.

## Branch / readiness

Continuation base: 6a645bb002deeb1ef14e24dec7d7b7532ea74b36.
Published milestones 68faa8994e4fafdb3940adad8ce9207319858163 and
cda66a6b7c0cbc6ac2eb6896d774972b0f96c822 have observed green runs 37478797188 / 37481848809.
Final closure SHA/CI is recorded in the final review handoff/PR, avoiding a self-referential
commit hash in this document.

Readiness: CODE COMPLETE / INTEGRATION READY for human review; not PRODUCTION GO. Flags stay
default-off. Main is an ancestor; merging to main is not authorized or performed.

See docs/admin-control-center/OPERATIONS_RUNBOOK.md for production enablement and rollback.
