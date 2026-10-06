# ERP_MCP Admin Control Center — design handoff

Supplemental design package for the real ERP_MCP repository. This is a proposal/prototype only: it does not change the frozen v1.0 baseline or claim that a web admin surface exists.

## Preview

Open `index.html` in a browser. The page is self-contained and uses fictional sample rows. No backend or identity provider is connected. Source connection forms accept secret references only.

## Verified against `bootstrap/1c-day1-production`

- Implemented: PostgreSQL source registry; separate company records; OIDC subject/group ACL; source and optional company grants; allow/deny; expiration and revocation; append-only audit; metadata drift lifecycle; semantic profiles and profile events; operator CLI.
- Not implemented: web Admin UI/API; delegated control-plane admin roles; business role-to-capability enforcement.
- Important runtime boundary: current generic unscoped OData source access requires a source-wide grant; company-only grants do not authorize it. Company-scoped data access must wait until an adapter operation enforces and tests the company boundary end-to-end.
- Existing DB roles separate runtime and admin privileges. The web app must not simply expose the privileged CLI/database path to an HTTP request.

See `docs/PRODUCT_AND_UX_SPEC.md`, `docs/IMPLEMENTATION_PLAN.md` and `docs/SECURITY_DECISIONS.md` for current-state distinctions, decision gates and acceptance criteria.
