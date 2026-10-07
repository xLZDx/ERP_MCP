# Implementation plan — gated proposal

## Source branch and entry gate

The ERP_MCP instructions name `bootstrap/1c-day1-production` as the implementation baseline and require normative documents to govern changes. This design package is based on that branch. Before implementation, inspect its exact current HEAD in the local checkout and follow `docs/DOCUMENT_INDEX.md`, `docs/GOVERNANCE.md`, `docs/MASTER_PLAN.md`, `docs/DATA_MODEL.md`, `SECURITY.md` and the relevant ADRs. Web admin routes and authorization materially extend the frozen v1.0 baseline; obtain a documented governance/architecture decision before treating this proposal as approved implementation scope.

## Slice 0 — local parity and threat/contract decisions

- Confirm local checkout, branch, clean/dirty state and exact SHA against GitHub; this session has no mounted `D:\Repo\ERP_MCP` checkout.
- Map each screen operation to current schema, CLI function, DB privilege, audit event and traceability/DoD requirement.
- Decide operator identity source, authentication, delegated authorization, separation of duties and emergency access.
- Choose the control-plane API boundary and privileged DB pattern. Runtime role must remain unable to mutate sources/grants; do not pass privileged DSNs or shell to request handlers.
- Specify operator mutation audit, actor/reason, exact grant-ID revocation, idempotency and concurrency.
- Resolve whether Company-scoped data access is in scope now. Until adapter enforcement exists, UI must label it as policy configuration only and not claim it scopes generic OData reads.

**Gate:** accepted governance decision / ADR or explicit baseline amendment; endpoint contract; threat analysis; no unresolved privilege-escalation route.

## Slice 1 — read-only operator console

- Add server-authorized read endpoints/views for sources, registered companies, ACL grants, capability/drift state, semantic profiles and existing audit evidence.
- Paginate/filter on server; scope every response to the authenticated operator's authorized administrative boundary.
- Show current effective behavior and source-wide-vs-company grant semantics accurately.
- Keep role editor and unsupported company-data controls disabled.

**Gate:** unauthenticated and non-admin calls denied; no cross-source leakage; values verified against DB/API; secrets redacted.

## Slice 2 — safe source and company operations

- Provide source create/update through a domain service using secret refs; validate URLs and restrict egress/redirect behavior server-side.
- If connection test/discovery is included, bound time/response size and reuse existing capability discovery behavior.
- Preview metadata and organizations, require operator review before company upsert.
- Preserve current source/company uniqueness, read-only runtime semantics, and sticky drift lifecycle.

**Gate:** no arbitrary URL/SSRF path; no secret values in browser, logs, audit or DB; failure is atomic/safe; tests prove read-only transport.

## Slice 3 — grants and revocation

- Resolve IdP principals safely and show stable subject/group IDs.
- Add grants with source/company constraints, allow/deny, expiry and reason.
- Replace broad matching revocation with a reviewed exact-grant mutation contract; append operator actor/outcome audit and preserve records.
- Define cache invalidation/instant-revoke latency and demonstrate before any 1C adapter call.

**Gate:** tests cover no-grant deny, deny-overrides-allow, expiry, revoke, foreign company/source mismatch, invalid principal and denied-before-adapter behavior. DB least privilege remains proven.

## Slice 4 — drift and semantic-profile workflows

- Expose fingerprint-bound drift acknowledgement.
- Expose profile create/mapping/validate/retire only through reviewed domain contracts.
- Preserve exact source/company/fingerprint provenance and the ten passing native-report validation threshold.

**Gate:** stale fingerprint cannot be acknowledged; changed metadata invalidates prior state; profile cannot become validated without all evidence.

## Slice 5 — role/capability RBAC (separate decision)

- Define platform admin roles separately from business capabilities and data scope.
- Define operation-to-capability matrix and deny semantics; enforce in every backend tool/API entry point.
- Add schema/migration only after governance and least-privilege review.
- Enable UI only after server enforcement and full authorization-matrix tests pass.

**Gate:** unknown tools/roles fail closed; tests cover role × operation × source/company × allow/deny; audit identifies policy version.

## Slice 6 — hardening and closure

- Accessibility/responsive verification; CSRF/CORS/session review appropriate to chosen auth; rate limits; SSRF/egress tests; redaction review.
- CI, migration-forward/restore analysis, threat model, runbook, deployment/rollback and operator docs.
- Exact-head review with changed paths, normative trace, security impact and verification evidence before PR.

## Release acceptance

Operators can execute approved workflows without CLI; no workflow implies capability the backend does not enforce; identity remains IdP-owned; source and company remain distinct; revocation and audit meet verified contracts; runtime DB role cannot administer; baseline production read-only, fail-closed and adapter constraints remain unchanged.
