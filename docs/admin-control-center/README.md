# ERP_MCP Admin Control Center — design handoff

This branch is a design and implementation-preparation package for a browser-based ERP_MCP control plane. It intentionally does not change the frozen v1.0 runtime or claim the Admin Control Center already exists.

## Preview

Open index.html in a browser. It is a self-contained dark operations-console prototype using fictional data only. No backend, IdP directory or 1C system is connected.

## Verified baseline

Verified against bootstrap/1c-day1-production at 5bbed48705f5ca84def8c992ba63a3e1870cde43.

Already implemented in the baseline:
- PostgreSQL source registry;
- separate company records;
- OIDC subjects/groups;
- source/company access grants with allow/deny, expiry and revocation;
- runtime deny-before-adapter behavior;
- append-only data access audit;
- metadata drift lifecycle;
- semantic profiles/events;
- operator CLI;
- split runtime/admin DB privileges.

Not implemented in the baseline:
- web Admin UI/API;
- OIDC browser session/BFF;
- delegated platform admin roles;
- IdP directory search;
- safe web source-probe contract;
- admin mutation audit/idempotency;
- exact grant-id revoke API;
- business role-to-capability enforcement;
- company-aware generic OData reads.

Critical boundary: current generic onec_read requires a source-wide grant. Company-only grants do not authorize it.

## Design package

1. PRODUCT_AND_UX_SPEC.md — screens, flows, UX and current-state truth.
2. ARCHITECTURE_AND_API_CONTRACT.md — recommended BFF/API boundary, auth/session, endpoints, SSRF and mutation semantics.
3. RBAC_AND_POLICY_MODEL.md — platform roles vs data scope vs business capabilities.
4. DATA_MODEL_AND_MIGRATION_PLAN.md — additive C3 schema/privilege plan.
5. SECURITY_DECISIONS.md — inherited invariants and open security decisions.
6. TEST_AND_ACCEPTANCE_MATRIX.md — mandatory negative/security/functional evidence.
7. IMPLEMENTATION_BACKLOG.md — ACC-00..ACC-10 delivery sequence.
8. DRAFT_ADR_ADMIN_CONTROL_CENTER.md — decision record ready for governance review.
9. AUTONOMOUS_IMPLEMENTATION_PROMPT.md — implementation-agent handoff after ACC-00 approval.
10. IMPLEMENTATION_PLAN.md — high-level gated rollout.
11. index.html — interactive design prototype.

## Recommended next step

Review/accept the draft ADR as ACC-00. Then create a separate code branch from the then-current approved implementation baseline, for example feature/admin-control-center-implementation.

Do not implement web mutations by exposing scripts/admin.py or business_ai_admin directly to request handlers.

## Implementation branch status

The design package has now been implemented on feature/admin-control-center-implementation.

The original docs/admin-control-center/index.html remains a standalone fictional prototype for design review. The live runtime UI is packaged at src/business_ai_gateway/static/admin.html and is served at /admin/ only when BAG_ADMIN_UI_ENABLED=true.

The live implementation includes OIDC PKCE BFF sessions, server-side admin authorization, source/company/grant administration, platform roles, business capabilities, semantic profile/drift workflows, audit, source egress controls and an explicit validated company-aware read path. All Admin Control Center feature flags remain disabled by default.

See ADR-0007, deploy/PRODUCTION.md and the implementation status appended to IMPLEMENTATION_BACKLOG.md before enabling it in any environment.
