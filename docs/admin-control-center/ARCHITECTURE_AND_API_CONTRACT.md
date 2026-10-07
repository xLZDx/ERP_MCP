# Admin Control Center — architecture and API contract

**Status:** implementation-ready proposal. It does not amend the frozen ERP_MCP v1.0 baseline until the required C3 decision/ADR is accepted.

## 1. Recommended deployment shape

Use a same-origin Admin Control Center with a browser UI and a narrow control-plane API/BFF. Do not expose the MCP runtime server or the existing CLI as the web administration surface.

~~~text
Browser
  |
  | OIDC authorization-code + PKCE
  v
Admin UI / BFF
  |
  | server-side session + CSRF protection
  v
Admin API/domain services
  |
  +--> PostgreSQL control-plane policy/registry
  +--> Secret provider references only
  +--> bounded source probe/discovery service
  +--> optional IdP directory resolver
  |
  +--> append-only admin audit

MCP runtime remains separate:
AI client -> MCP OAuth -> runtime ACL/capability enforcement -> adapter -> 1C
~~~

The browser never receives database credentials, 1C secret values, or unrestricted bearer tokens. The admin service must not shell out to scripts/admin.py.

## 2. Authentication

Recommended browser flow:
- OIDC Authorization Code + PKCE, with state and nonce validation;
- same-origin BFF session using Secure + HttpOnly + SameSite cookie;
- short idle timeout and absolute session lifetime;
- CSRF token on every mutation;
- step-up authentication for platform-role assignment, source registration, broad grants, and emergency actions;
- distinct admin audience/scope from the MCP data-plane scope. Do not treat onec:read as an admin permission.

Principal identity is still external. ERP_MCP stores only principal references and policy bindings.

## 3. Authorization layers

Every admin request must pass, in order:

1. valid admin session;
2. required platform admin capability;
3. optional source boundary for delegated source administrators;
4. command-specific validation;
5. optimistic concurrency/idempotency guard;
6. durable admin audit;
7. mutation/read.

Frontend visibility is convenience only. The server is authoritative.

## 4. Proposed API namespace

Recommended namespace: /admin/v1. Route names can change during ADR acceptance, but semantics below are the contract.

### Read resources

- GET /admin/v1/me
- GET /admin/v1/overview
- GET /admin/v1/sources
- GET /admin/v1/sources/{source_id}
- GET /admin/v1/sources/{source_id}/companies
- GET /admin/v1/sources/{source_id}/capabilities
- GET /admin/v1/companies
- GET /admin/v1/principals/resolve
- GET /admin/v1/grants
- GET /admin/v1/grants/{grant_id}
- GET /admin/v1/roles
- GET /admin/v1/role-assignments
- GET /admin/v1/semantic-profiles
- GET /admin/v1/audit

All list endpoints use cursor pagination, stable sorting, bounded page sizes, and server-side filtering. No endpoint may enumerate objects outside the operator's administrative boundary.

### Source commands

- POST /admin/v1/source-probes
- POST /admin/v1/sources
- PATCH /admin/v1/sources/{source_id}
- POST /admin/v1/sources/{source_id}/capability-refresh
- POST /admin/v1/sources/{source_id}/drift-acknowledgements

A source probe accepts a candidate endpoint only after server-side egress policy validation. It returns safe capability/metadata information and optional organization candidates. Organization discovery is advisory: custom 1C configurations may not expose a universally identifiable organization catalog, so the UI must support reviewed/manual company registration.

### Company commands

- POST /admin/v1/companies
- PATCH /admin/v1/companies/{company_id}

Company registration requires an existing source and stable external_ref. A company is never inferred to be a source.

### Grant commands

- POST /admin/v1/grants
- POST /admin/v1/grants/{grant_id}/revoke

Revocation is by exact grant_id. The current CLI broad-match revoke semantics must not be copied into the web API.

Create-grant request:
~~~json
{
  "principal_kind": "subject",
  "principal_id": "user-847293",
  "source_id": "source-01",
  "company_id": "optional-uuid",
  "effect": "allow",
  "expires_at": null,
  "reason": "Quarterly accounting access",
  "idempotency_key": "client-generated-uuid"
}
~~~

Revoke request:
~~~json
{
  "expected_version": 3,
  "reason": "Role changed",
  "idempotency_key": "client-generated-uuid"
}
~~~

### Platform-role and capability commands

- POST /admin/v1/platform-role-bindings
- POST /admin/v1/platform-role-bindings/{binding_id}/revoke
- POST /admin/v1/business-role-assignments
- POST /admin/v1/business-role-assignments/{assignment_id}/revoke
- POST /admin/v1/capability-overrides
- POST /admin/v1/capability-overrides/{override_id}/revoke

These routes remain disabled until the corresponding server-side enforcement is implemented and authorization-matrix tests are green.

## 5. API safety contract

Every mutation carries:
- request_id/correlation ID;
- authenticated actor subject/client;
- reason;
- idempotency key;
- expected row/policy version where applicable;
- server timestamp;
- outcome and stable error code.

Recommended stable errors:
- AUTH_REQUIRED
- ADMIN_SCOPE_REQUIRED
- PLATFORM_ROLE_DENIED
- SOURCE_NOT_FOUND
- COMPANY_NOT_FOUND
- PRINCIPAL_NOT_RESOLVED
- GRANT_CONFLICT
- GRANT_ALREADY_REVOKED
- POLICY_VERSION_CONFLICT
- INVALID_SOURCE_ENDPOINT
- SOURCE_EGRESS_DENIED
- SOURCE_PROBE_FAILED
- METADATA_FINGERPRINT_MISMATCH
- METADATA_DRIFTED
- CAPABILITY_UNSUPPORTED
- ROLE_ENFORCEMENT_DISABLED
- RATE_LIMITED

Do not expose SQL errors, secret provider values, upstream credentials, raw tokens, or internal stack traces.

## 6. Source probe / SSRF boundary

The source-probe service is the highest-risk new endpoint.

Production requirements:
- HTTPS unless an explicit deployment policy allows otherwise;
- no URL userinfo;
- redirects disabled;
- host resolution checked against deployment-approved DNS/domain/CIDR policy;
- re-resolve on connect to reduce DNS rebinding risk;
- fixed ports or explicit allowlist;
- bounded connect/read timeouts and response bytes;
- GET/HEAD only;
- no arbitrary headers supplied by browser;
- credentials referenced by secret_ref and resolved server-side only;
- no raw response body returned to the browser.

Internal/private 1C networks are legitimate, so private IPs cannot simply be banned globally. The deployment must declare approved network zones; everything else fails closed.

## 7. Principal resolution

The existing runtime knows the current token subject/groups, but it does not provide a directory of all users/groups. Therefore Users & Groups has two supported modes:

1. trusted directory provider configured server-side: search and resolve stable IdP IDs;
2. exact-ID mode: operator enters a subject/group ID and optional display alias, then the server validates the format/provider contract.

Never create local passwords or claim that ERP_MCP owns user lifecycle.

## 8. Concurrency and idempotency

- mutation records use a monotonically increasing row_version or equivalent compare-and-swap token;
- stale writes return 409 POLICY_VERSION_CONFLICT;
- idempotency keys are persisted for mutation outcome replay for a bounded retention window;
- retries may return the prior successful result but must never duplicate grants/role bindings;
- grant revocation is idempotent for the same grant_id + idempotency key.

## 9. Audit

Admin mutation audit is separate from ordinary data-plane access audit, though both share request/correlation conventions.

Each admin event records:
- event_id;
- occurred_at;
- actor subject/client;
- action;
- target type/id;
- source/company when applicable;
- before/after fingerprints or safe field diffs;
- reason;
- request_id;
- idempotency key;
- policy version;
- outcome/detail code.

No secrets, tokens, or raw accounting payloads.

## 10. Frontend contract

The UI must render server capability flags and not infer backend support. A disabled feature explains why it is unavailable.

Mandatory states:
- loading;
- empty;
- stale;
- forbidden;
- conflict;
- partial dependency failure;
- success;
- read-only/degraded mode.

Broad source-wide grants, group grants, platform-admin assignment and capability overrides require impact preview + explicit confirmation.
