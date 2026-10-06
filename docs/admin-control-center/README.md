# ERP_MCP Admin Control Center

This directory contains the design contract, implementation plan, security model and operator material for the Admin Control Center.

The live implementation is on branch feature/admin-control-center-implementation. The standalone index.html remains a fictional interactive design prototype; the runtime UI is packaged at src/business_ai_gateway/static/admin.html and is served at /admin/ only when BAG_ADMIN_UI_ENABLED=true.

## Implemented architecture

The implementation preserves the frozen 1C read-only boundary while adding a governed browser control plane:

- OIDC Authorization Code + PKCE browser login;
- Redis-backed opaque HttpOnly admin session;
- distinct admin OAuth audience/scope from onec:read;
- CSRF protection for cookie-authenticated mutations;
- subject-level admin rate limiting;
- DB-backed platform roles with delegated source scope;
- separate business_ai_control_api DB credential for web mutations;
- append-only admin audit;
- idempotency keys and optimistic row versions;
- exact-ID grant/role revocation;
- source/company administration;
- egress-controlled safe source probe;
- metadata drift acknowledgement;
- semantic profile lifecycle;
- business role/capability assignments and overrides;
- explicit company-aware onec_company_read path backed by VALIDATED scope mappings.

Generic onec_read remains source-scoped. A company-only grant does not authorize it.

## Identity model

ERP_MCP does not own user passwords.

Users and groups are external OIDC/IdP principals. The Admin Control Center stores and resolves stable subject/group IDs plus policy references. The current implementation always supports exact-ID resolution against ERP_MCP policy state; optional IdP directory search remains deployment/provider-specific.

## Files

1. PRODUCT_AND_UX_SPEC.md — screens, workflows and current-state truth.
2. ARCHITECTURE_AND_API_CONTRACT.md — BFF/API/auth/SSRF/mutation contract.
3. RBAC_AND_POLICY_MODEL.md — platform roles vs data scope vs business capabilities.
4. DATA_MODEL_AND_MIGRATION_PLAN.md — additive schema and privilege plan.
5. SECURITY_DECISIONS.md — inherited invariants and security decisions.
6. TEST_AND_ACCEPTANCE_MATRIX.md — mandatory verification matrix.
7. IMPLEMENTATION_BACKLOG.md — ACC-00 through ACC-10 status.
8. DRAFT_ADR_ADMIN_CONTROL_CENTER.md — original proposal retained as design history.
9. AUTONOMOUS_IMPLEMENTATION_PROMPT.md — implementation-agent handoff reference.
10. IMPLEMENTATION_PLAN.md — gated rollout.
11. OPERATIONS_RUNBOOK.md — bootstrap, enablement, rollback and break-glass.
12. index.html — standalone fictional prototype.

The accepted architecture decision is docs/adr/ADR-0007-admin-control-center.md.

## Feature flags

Everything is disabled by default.

Read-only Admin API:

    BAG_ADMIN_API_ENABLED=true

Browser BFF/UI:

    BAG_ADMIN_UI_ENABLED=true

Web mutations:

    BAG_ADMIN_MUTATIONS_ENABLED=true

Business capability enforcement:

    BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED=true

Do not enable mutations without the dedicated control API database DSN and production source egress allowlist.

## Production status

Repository implementation and local integration verification are not equivalent to production approval.

Before target-environment activation, complete the real IdP login, secret-provider, network egress, 1C safe-probe, backup/restore, load/SLO and pilot gates documented in OPERATIONS_RUNBOOK.md and DEFINITION_OF_DONE.md.

See reports/ADMIN_CONTROL_CENTER_STATUS.md for the current evidence snapshot.
