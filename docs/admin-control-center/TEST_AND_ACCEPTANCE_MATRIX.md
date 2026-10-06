# Admin Control Center — test and acceptance matrix

This matrix is mandatory evidence for implementation. UI success alone is insufficient.

## A. Authentication/session

- missing/invalid admin session -> 401;
- wrong issuer/audience -> denied;
- expired session -> denied;
- missing admin scope -> denied;
- OIDC state/nonce/PKCE failures -> denied;
- CSRF missing/invalid on mutation -> denied;
- session fixation prevented;
- sign-out invalidates server session;
- no token/secret stored in localStorage.

## B. Platform RBAC

For every admin endpoint, test all roles:
- PLATFORM_ADMIN;
- SOURCE_ADMIN;
- ACCESS_ADMIN;
- PROFILE_ADMIN;
- AUDITOR;
- USER/no role.

Also test:
- group-inherited role;
- subject + group combination;
- expired binding;
- revoked binding;
- delegated source boundary;
- unknown role;
- stale policy version.

## C. Data scope

Existing mandatory cases plus UI/API coverage:
- missing grant deny;
- subject allow;
- group allow;
- source-wide allow;
- company allow;
- subject deny overrides group allow;
- source deny overrides narrower allow where policy matches;
- expiry;
- exact grant revocation;
- company/source FK mismatch rejected;
- inaccessible source ID is not enumerable.

Explicit regression: company-only grant must not authorize generic onec_read.

## D. Business capabilities

When enabled:
- role allow;
- no role/capability deny;
- explicit capability deny overrides role;
- group role inherited;
- subject deny override;
- source/company scoped role assignment;
- expired/revoked assignment;
- unknown capability fail closed;
- role assignment alone never widens source/company ACL;
- every protected operation maps to exactly one reviewed capability requirement.

## E. Source onboarding and SSRF

Test:
- HTTPS valid allowed endpoint;
- malformed URL;
- URL userinfo;
- redirect;
- disallowed host/domain/CIDR;
- DNS result changes between validation/connect;
- loopback/link-local/metadata endpoint where not explicitly allowed;
- non-approved port;
- oversized metadata response;
- slow connect/read;
- secret ref not found;
- secret provider error;
- credentials never returned/logged/audited;
- source remains read_only=true.

No POST/PUT/PATCH/DELETE to 1C in any probe path.

## F. Company registration/discovery

- one source with multiple companies;
- duplicate external_ref rejected/upsert semantics explicit;
- same external_ref allowed in different source;
- manual registration path works;
- discovery candidates are advisory;
- custom config with no recognizable organization catalog does not invent companies;
- disabled company excluded from effective runtime visibility.

## G. Grant lifecycle

- create with idempotency key;
- retry returns same logical result;
- conflicting retry payload rejected;
- revoke exact grant_id;
- revoke already revoked is safe/idempotent;
- stale expected_version -> 409;
- broad-match accidental revoke impossible;
- actor/reason stored;
- runtime deny takes effect without restart.

## H. Drift/profile workflows

- acknowledge exact current metadata fingerprint;
- stale fingerprint ack rejected;
- new fingerprint invalidates prior state;
- profile cannot validate below ten passing native-report cases;
- profile source/company/fingerprint mismatch rejected;
- retired profile not used.

## I. Audit

For success/deny/error/conflict:
- admin audit row exists;
- actor/client/action/target/request ID recorded;
- reason recorded for mutation;
- before/after fingerprint or safe diff recorded;
- no secret/token/raw accounting payload;
- DB role cannot UPDATE/DELETE admin audit;
- correlation joins admin action to subsequent runtime evidence where applicable.

## J. UI/accessibility

- keyboard-only navigation;
- visible focus;
- semantic labels/tables/dialogs;
- 200% zoom;
- narrow mobile/tablet layout;
- loading/empty/error/forbidden/conflict/stale states;
- status not conveyed by color alone;
- destructive-looking actions use revoke/disable language, not delete;
- impact preview for source-wide/group grants and platform admin;
- unsupported feature is visibly disabled with reason.

## K. Performance/resilience

- bounded pagination;
- principal/grant search under representative 30–150 company scale;
- no unbounded company/principal matrix response;
- source probe isolated from main admin request pool;
- one slow source does not block control center;
- Postgres unavailable -> safe error;
- IdP directory unavailable -> exact-ID fallback or explicit degraded state;
- secret provider unavailable -> source probe denied safely.

## L. Release gate

Implementation can be called Admin Control Center MVP only when:
- C3 ADR/governance accepted;
- schema migrations + restore analysis green;
- least-privilege DB test green;
- authorization matrix green;
- SSRF suite green;
- existing ERP_MCP full test suite green;
- no baseline read-only/security invariant weakened;
- exact-head evidence captured.
