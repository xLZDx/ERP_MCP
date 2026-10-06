# Security invariants and open decisions

## Invariants inherited from ERP_MCP baseline

1. A source is a registered technical endpoint; a company is a separate business scope within a source.
2. Login and group membership are OIDC/IdP-owned; never add local password storage/provisioning.
3. Store secret references only. Secret values stay in the configured provider and are never returned to browser/API/log/audit.
4. Runtime resolves only server-registered `source_id`; never accept model- or browser-selected arbitrary routing URLs.
5. Production 1C access remains read-only, GET/HEAD-only, bounded and fail-closed.
6. Missing grant denies; matching active deny overrides allow; expired/revoked grant is ineffective.
7. Current generic unscoped OData reads require a source-wide grant. Do not represent company-only grants as effective company-level data isolation until adapter enforcement is end-to-end implemented and tested.
8. Runtime DB role cannot modify registry/grants; audit stays append-only.
9. Metadata drift stays sticky and must be acknowledged against the exact current fingerprint.
10. A profile is not validated without the required ten passing native-report reconciliation cases.

## Decisions required before web mutations

- Which authenticated actor may administer, and how is that role issued/revoked and checked server-side?
- Is the UI/API a separate control-plane service or a distinct route/service in the existing deployment? What database role and network boundary does it use?
- How are source/company/profile mutations attributed in audit with actor, reason, outcome and request ID?
- What exact mutation is revocable: one grant ID, with what optimistic concurrency and idempotency semantics?
- Does browser auth require CSRF-safe sessions, or a different explicit token flow? Define CORS, cookie and step-up policy.
- What server egress policy prevents SSRF, redirects, DNS rebinding and private-network access when testing registered 1C endpoints?
- Which company-scoped operations can enforce company identity in their adapter query/response, and what negative tests prove no cross-company leakage?
- What capability vocabulary and role semantics are accepted, and where is every protected operation enforced?

Do not resolve these questions by adding frontend-only guards or by exposing `business_ai_admin` credentials to the browser/request process. Any data-model, auth, ACL or audit change is a C3 governance change; production/destructive effects follow the stricter C4 approval rule.
