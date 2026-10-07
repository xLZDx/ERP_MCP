# ADR-0007 — Admin Control Center boundary and authorization

**Status:** ACCEPTED
**Date:** 2026-10-06
**Change class:** C3

## Context

ERP_MCP already has a source/company registry, OIDC principals, access grants, capability drift
state, semantic profiles and operator CLI. It did not have a browser admin API, delegated
platform-admin authorization, or business capability RBAC.

The operator approved implementation in a separate feature branch intended for later merge to
`main`. The existing read-only 1C and least-privilege invariants remain non-negotiable.

## Decision

1. Add an Admin Control Center with a narrow `/admin/v1` control-plane API.
2. Admin API authorization uses the same trusted OIDC issuer/JWKS but a distinct audience and
   required admin scope from the MCP `onec:read` data-plane authorization.
3. Platform administration is DB-backed with fixed roles:
   `PLATFORM_ADMIN`, `SOURCE_ADMIN`, `ACCESS_ADMIN`, `PROFILE_ADMIN`, `AUDITOR`.
4. Identity provisioning remains external to ERP_MCP; only stable subject/group references are
   stored.
5. Platform roles, source/company data scope and business capabilities remain separate.
6. The initial Admin API slice is read-only and may reuse the runtime read-only DB connection.
   Any web mutation slice requires a dedicated least-privilege control-API credential/role.
7. Grant and role revocation exposed to the web must use exact IDs, never broad matching.
8. Source connection tests require an egress-controlled GET/HEAD-only probe with redirects
   disabled and server-side secret resolution.
9. Company-only grants do not authorize generic `onec_read`; company-aware data-plane
   enforcement is a separate gate.
10. Business capability UI remains disabled until every mapped operation enforces capabilities
    server-side.

## Consequences

The first implementation slice can safely expose read-only control-plane state while keeping
mutations behind existing operator tooling. Later C3 slices add attributable admin audit,
idempotency, exact-ID mutations, a dedicated control API DB role and browser session/BFF
hardening.

## Evidence required

- negative auth tests for admin audience/scope;
- platform-role authorization matrix;
- DB privilege tests;
- migration forward/restore analysis;
- SSRF/source-probe tests before source onboarding mutation;
- existing ERP_MCP test suite remains green.
