# Draft ADR — Admin Control Center boundary and authorization

**Status:** DRAFT / NOT ACCEPTED
**Change class:** C3

## Context

ERP_MCP already has source/company registry, OIDC principals, access grants, capability drift state, semantic profiles and operator CLI. It does not have a browser admin API, delegated platform-admin authorization, or completed business capability RBAC.

Directly exposing scripts/admin.py, business_ai_admin credentials, or frontend-only guards would violate the control/data-plane and least-privilege model.

## Decision proposal

1. Add a same-origin Admin Control Center using OIDC Authorization Code + PKCE and a server-side BFF session.
2. Add a narrow /admin/v1 control-plane API. It calls domain services, not CLI subprocesses.
3. Add fixed platform roles: PLATFORM_ADMIN, SOURCE_ADMIN, ACCESS_ADMIN, PROFILE_ADMIN, AUDITOR.
4. Keep identity provisioning in the external IdP; ERP_MCP stores principal references and policy bindings only.
5. Keep source/company ACL independent from business capability roles.
6. Add append-only admin mutation audit and idempotency.
7. Use exact-ID revocation for grants/role assignments.
8. Use a dedicated least-privilege database role for the control API; do not give the browser or HTTP worker migration-owner privileges.
9. Source connection tests run through a bounded egress-controlled probe service with redirects disabled and secret refs resolved server-side.
10. Roles/capabilities remain disabled in UI until server-side enforcement is complete.
11. Company-only grants do not authorize generic OData reads; company-aware data-plane work is a separate gate.

## Consequences

Positive:
- normal employees can administer approved workflows without terminal access;
- admin actions become attributable and auditable;
- source/company/identity/capability concepts stay separate;
- least privilege can be proven by endpoint and DB-role tests.

Costs:
- new web/session attack surface;
- new C3 migrations and authorization matrix;
- optional IdP directory integration if user/group search is desired;
- source probe creates SSRF/egress risk that must be controlled.

## Rejected alternatives

### Expose CLI over HTTP
Rejected: shell/argument boundary, broad DB privilege and audit attribution are unsuitable.

### Use frontend-only admin groups
Rejected: client-side checks are not authorization.

### Reuse onec:read as admin permission
Rejected: business data read scope must not grant control-plane administration.

### Store local ERP_MCP users/passwords
Rejected: duplicates identity lifecycle and increases credential risk.

### Treat company grant as complete company isolation immediately
Rejected: current generic onec_read is source-scoped and cannot prove company filtering.

## Acceptance evidence

Before this ADR can be accepted:
- threat-model delta reviewed;
- admin auth/session model reviewed;
- DB privilege design reviewed;
- source-probe egress policy reviewed;
- migration/restore plan reviewed;
- endpoint x platform-role matrix complete;
- implementation backlog/DoD trace accepted.
