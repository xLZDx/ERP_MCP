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
- ACC-10 local hardening: CSRF/session controls, admin rate limiting, DNS re-check, security scans, packaging and PostgreSQL privilege/integration verification.

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
- pytest with disposable PostgreSQL enabled: 336 passed, 1 skipped;
- the remaining skip is tests/test_real_1c_integration.py because ONEC_TEST_BASE_URL is not configured;
- Ruff: PASS;
- Bandit: PASS;
- pip-audit: no known vulnerabilities;
- PostgreSQL 16 migrations 001-011 applied from an empty database: PASS;
- database privilege policy for business_ai_app, business_ai_admin and business_ai_control_api: PASS;
- PostgreSQL admin mutation/integration tests: PASS;
- backup/restore rehearsal into a second clean PostgreSQL 16 instance: PASS;
- restored schema version: 11; restored BAG tables: 17; required DB roles: 3;
- wheel build: PASS; business_ai_gateway/static/admin.html is packaged;
- Admin UI JavaScript syntax check: PASS;
- headless Chrome Admin UI browser contract: PASS for navigation, mutation retry/idempotency, CSRF, untrusted-label escaping, dialog focus, narrow viewport and 200% zoom.

The two temporary verification PostgreSQL containers are retained (not deleted) to respect the no-destructive-cleanup rule and may be stopped after evidence capture.

See docs/admin-control-center/OPERATIONS_RUNBOOK.md for production enablement and rollback.
