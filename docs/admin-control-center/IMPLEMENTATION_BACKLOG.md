# Admin Control Center — implementation backlog

The backlog is ordered to avoid building UI on top of unenforced security semantics.

## ACC-00 — Governance and architecture gate

Deliver:
- accepted ADR for Admin UI/BFF/API boundary;
- accepted admin authentication and platform-role model;
- accepted DB privilege design;
- accepted SSRF/source-probe policy;
- threat-model delta;
- requirements/DoD trace.

Exit: no unresolved privilege-escalation path.

## ACC-01 — Read-only Admin API foundation

Deliver:
- admin app/service skeleton;
- OIDC session/BFF;
- /admin/v1/me;
- read-only sources/companies/grants/capabilities/profiles/audit endpoints;
- cursor pagination/filtering;
- server-side admin boundary enforcement;
- typed stable errors.

Exit: USER denied; AUDITOR can read; no secrets leaked; no mutation credentials in browser.

## ACC-02 — UI shell and read-only screens

Deliver:
- navigation and design system from index.html prototype;
- Overview;
- Sources;
- Companies;
- Users & Groups resolver;
- Access Policies;
- Capabilities & Metadata;
- Semantic Profiles;
- Audit;
- Roles & Capabilities shown as disabled until enforcement.

Exit: all loading/empty/error/forbidden states + accessibility baseline.

## ACC-03 — Admin audit + idempotency + exact grant mutation

Deliver:
- migrations for access-grant actor/reason/version;
- admin_audit_events;
- idempotency table;
- exact grant create/revoke domain service;
- Access Policy create/revoke UI.

Exit: broad-match revoke impossible; instant runtime revoke proven; append-only audit proven.

## ACC-04 — Source onboarding

Deliver:
- controlled source probe service;
- egress/SSRF policy;
- secret-ref validation;
- source create/update commands;
- capability refresh;
- source detail and connect wizard.

Exit: GET/HEAD-only; redirect blocked; secrets absent from browser/log/audit; failure atomic.

## ACC-05 — Company registration

Deliver:
- reviewed company create/update domain service;
- source-scoped company list;
- manual registration;
- optional discovery candidates when mapping evidence exists;
- company access matrix UI.

Exit: source/company identity cannot be confused; no invented organization discovery.

## ACC-06 — Drift and semantic profile admin

Deliver:
- exact-fingerprint drift acknowledgement;
- profile lifecycle API around existing domain rules;
- evidence display;
- profile UI.

Exit: ten-case validation remains mandatory; stale fingerprint rejected.

## ACC-07 — Platform role enforcement

Deliver:
- platform_role_bindings migration;
- enforcement middleware/dependency;
- bootstrap CLI command;
- assignment/revoke UI;
- delegated source admin boundaries.

Exit: complete endpoint x role matrix green; auditor read-only; source/access/profile separation proven.

## ACC-08 — Business capability enforcement

Deliver:
- operation-to-capability registry;
- built-in role/capability migrations;
- role assignments + capability overrides;
- enforcement at every relevant tool/domain entry;
- Roles & Capabilities UI enabled.

Exit: role cannot bypass data ACL; unknown capability fails closed; policy version audited.

## ACC-09 — Company-aware data-plane

This is intentionally separate from the admin UI.

Deliver only for operations that can enforce organization identity end-to-end:
- company-aware adapter/tool contract;
- positive + negative cross-company tests;
- provenance with company_id;
- no generic OData claim.

Exit: company-only grant can authorize only explicitly proven company-aware operations.

## ACC-10 — Hardening and pilot

Deliver:
- CSRF/CORS/session hardening;
- rate limits;
- observability;
- load/access-matrix performance;
- backup/restore + migration rehearsal;
- admin runbooks;
- incident/break-glass procedure;
- pilot evidence.

Exit: relevant baseline DoD gates green on exact head.

## Suggested implementation branch strategy

Keep feature/admin-control-center-design documentation-only.

After ACC-00 acceptance, create a new code branch from the then-current approved implementation baseline, e.g.:
- feature/admin-control-center-implementation

Do not merge design-only assumptions into main as if already approved architecture.

## Dependency graph

~~~text
ACC-00
  |
  +-> ACC-01 -> ACC-02
  |
  +-> ACC-03 -> ACC-04 -> ACC-05 -> ACC-06
  |
  +-> ACC-07 -> ACC-08
                   |
                   +-> ACC-09
  |
  +-----------------------> ACC-10
~~~
