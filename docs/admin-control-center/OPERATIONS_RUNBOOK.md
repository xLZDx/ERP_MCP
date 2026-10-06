# Admin Control Center — Operations Runbook

Status: implementation runbook for the feature branch. Production enablement still requires target IdP, secret-store, network and pilot evidence.

## 1. Safety model

Admin Control Center does not replace the existing 1C read-only boundary.

- 1C remains GET/HEAD-only.
- Browser never receives PostgreSQL credentials or 1C secret values.
- Local user/password provisioning is not supported.
- Admin authentication uses a distinct OAuth audience and scope from onec:read.
- Browser authentication uses Authorization Code + PKCE and an opaque Redis-backed HttpOnly session.
- Cookie-authenticated mutations require a CSRF token.
- Web mutations use business_ai_control_api, not business_ai_admin.
- Grants and role assignments are revoked by exact IDs with optimistic concurrency.
- Company-only grants authorize only company-aware operations with a validated scope mapping.

## 2. Database preparation

Create these PostgreSQL roles before migrations in the target environment:

- business_ai_app
- business_ai_admin
- business_ai_control_api

Run migrations through the migration-owner DSN. Schema 11 is expected after this feature:

- 008 platform role bindings
- 009 admin mutation audit/idempotency/provenance
- 010 business capability policy
- 011 company-scope mappings

Run:

    $env:PYTHONPATH = 'src'
    python scripts/migrate.py
    python scripts/check_db_privileges.py

The control API role may INSERT/UPDATE only governed control-plane tables, INSERT append-only admin/profile events and may not DELETE control-plane rows.

## 3. Bootstrap the first administrator

Keep Admin UI/API mutations disabled during bootstrap.

Use the operator CLI with BAG_ADMIN_DATABASE_URL:

    python scripts/admin.py platform-role-add --kind subject --principal "<OIDC subject>" --role PLATFORM_ADMIN --created-by "<owner/operator identity>" --reason "Initial Admin Control Center bootstrap"

Capture the returned binding_id. Never hard-code a permanent administrator in source.

For emergency revocation:

    python scripts/admin.py platform-role-revoke --binding-id "<UUID>"

The CLI is the break-glass path and must use protected operator access.

## 4. OIDC configuration

Required for Admin API:

    BAG_OAUTH_ENABLED=true
    BAG_ADMIN_API_ENABLED=true
    BAG_ADMIN_OAUTH_AUDIENCE=https://mcp.example.com/admin
    BAG_ADMIN_OAUTH_REQUIRED_SCOPE=erp_mcp:admin

Required for browser UI:

    BAG_ADMIN_UI_ENABLED=true
    BAG_ADMIN_OIDC_AUTHORIZATION_URL=https://id.example.com/.../authorize
    BAG_ADMIN_OIDC_TOKEN_URL=https://id.example.com/.../token
    BAG_ADMIN_OIDC_CLIENT_ID=erp-mcp-admin
    BAG_ADMIN_OIDC_REDIRECT_URI=https://mcp.example.com/admin/callback

If the IdP uses a confidential web client, inject BAG_ADMIN_OIDC_CLIENT_SECRET from the deployment secret mechanism. Do not commit it.

The IdP must issue the admin access token for BAG_ADMIN_OAUTH_AUDIENCE with BAG_ADMIN_OAUTH_REQUIRED_SCOPE. The ID token must contain the same subject and callback nonce.

Configure BAG_ADMIN_STEP_UP_ACR_VALUES with the IdP ACR values accepted for sensitive platform-role assignment/revocation. Platform-role mutations fail closed until step-up is configured and require auth_time within five minutes.

## 5. Browser session

The browser stores only an opaque HttpOnly cookie scoped to /admin.

Session state is in Redis and contains the admin access token plus CSRF secret. The session expires on the earlier of:

- configured admin session TTL;
- admin access-token expiration;
- 30-minute idle timeout.

Mutating browser requests require X-CSRF-Token. Bearer-token API callers do not use cookie CSRF.

Redis carrying admin sessions must be private, authenticated/encrypted as required by the deployment and excluded from general application-user access.

## 6. Enable read-only Admin Control Center

Start with:

    BAG_ADMIN_API_ENABLED=true
    BAG_ADMIN_UI_ENABLED=true
    BAG_ADMIN_MUTATIONS_ENABLED=false
    BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED=false

Verify:

- /admin/ loads;
- OIDC login completes;
- /admin/v1/me returns the expected platform binding;
- delegated SOURCE_ADMIN sees only its source boundary;
- USER/no binding gets 403;
- AUDITOR cannot mutate;
- secrets do not appear in browser/network responses.

## 7. Enable mutations

Create a login/credential for the existing business_ai_control_api role using the deployment's normal PostgreSQL credential process, then set:

    BAG_ADMIN_CONTROL_DATABASE_URL=postgresql://business_ai_control_api:...@postgres:5432/business_ai
    BAG_ADMIN_SOURCE_ALLOWED_HOSTS=onec.internal.example,another-onec.internal.example
    BAG_ADMIN_SOURCE_ALLOWED_CIDRS=10.0.0.0/8
    BAG_ADMIN_MUTATIONS_ENABLED=true

In production, source mutations refuse to enable without an explicit host allowlist.

Validate exact-ID revoke, idempotency replay, stale expected_version conflict and append-only admin audit before pilot.

## 8. Source onboarding

The web wizard follows:

    candidate URL + secret refs
      -> exact host allowlist
      -> DNS/CIDR validation
      -> numeric-IP-pinned GET/HEAD probe (original Host and TLS name)
      -> capability summary
      -> operator review
      -> audited source registration

Redirects remain disabled in the underlying 1C client.

Network egress policy is still mandatory in production. Application DNS validation is defense-in-depth and cannot replace firewall/service-mesh/VPC egress restrictions.

Organization discovery is advisory. If the configuration cannot prove an organization catalog mapping, register companies manually by stable source_id + external_ref.

## 9. Business capabilities

Leave BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED=false until role assignments and capability overrides are configured for pilot users.

When enabled, every protected MCP operation requires:

1. normal source/company ACL;
2. required business capability;
3. metadata/profile/capability gates;
4. rate/query budget;
5. adapter call.

Unknown/unassigned capabilities fail closed. Explicit capability deny overrides role/direct allow.

## 10. Company-aware reads

Generic onec_read stays source-wide.

onec_company_read is the company-aware path. It requires:

- authorized company via source/company ACL;
- accounting.read capability when capability enforcement is enabled;
- acknowledged metadata;
- VALIDATED semantic profile;
- company-scope mapping for the exact EntitySet;
- mapped company property present in current live metadata.

The server injects the company filter and combines it with any caller filter. A company grant alone cannot authorize generic OData reads.

## 11. Rollback

Application rollback is preferred. Migrations 008–011 are additive.

Safe rollback:

1. set BAG_ADMIN_MUTATIONS_ENABLED=false;
2. set BAG_ADMIN_UI_ENABLED=false and/or BAG_ADMIN_API_ENABLED=false;
3. roll application back to the prior release;
4. leave additive tables/columns in place.

Do not drop tables/columns as part of routine rollback. Cleanup is destructive C4 work and needs explicit approval.

## 12. Break-glass

If browser/OIDC control-plane access is unavailable:

- disable Admin UI/API at deployment config;
- use protected operator CLI with business_ai_admin;
- use exact platform-role binding IDs;
- record incident/request evidence;
- restore normal OIDC path before returning to routine operation.

Do not expose business_ai_admin to the browser or HTTP worker.

## 13. Pre-pilot checklist

Required before a production pilot:

- target IdP client/audience/scope configured;
- initial PLATFORM_ADMIN binding reviewed;
- control API DB credential created and privilege checker green;
- source host/CIDR allowlist approved;
- network-level egress policy verified;
- secret provider configured;
- migration backup/restore rehearsal complete;
- OIDC state/nonce/PKCE and CSRF tests green;
- exact revoke/idempotency/concurrency tests green;
- 1C probe against designated test source green;
- company-aware negative cross-company tests green;
- full test/security/dependency suite green;
- business capability enforcement enabled only after assignments are reviewed.

Do not label the feature PRODUCTION GO until target-environment pilot evidence exists.


## Admin request logging

OIDC authorization codes, state and other callback query parameters must never be written to standard access logs. The gateway image disables Uvicorn access logging; ingress/OTel request telemetry must log a redacted path without the admin callback query string.

## Browser lifecycle and investigation

Sources supports connect/probe, edit/disable, refresh and exact-fingerprint drift acknowledgement.
Companies uses source ID + external reference; editing cannot move a company between sources.
Delegated SOURCE_ADMIN may edit labels/tags/enabled state but cannot change connection URL or
secret references. These changes require global source administration, preventing source A
from being repointed to source B's connection/credentials.

Access Policies creates subject/group allow/deny grants and revokes exact IDs. Review group
and source-wide impact, supply a reason, and use the displayed row version. An unchanged retry
keeps its key. On conflict, review current policy before starting a new operation; do not blindly
replace an uncertain outcome with a new key.

Roles & Capabilities distinguishes active, expired and revoked policies. Business controls
require enforcement ON; bootstrap initial assignments through the reviewed Bearer Admin API
before enabling enforcement for users. Platform-role changes require configured approved ACR
values and signed `acr`/`auth_time` in the access token from within five minutes.
`/admin/login?step_up=1` requests fresh authentication. If the IdP cannot provide this evidence,
web role changes remain denied; use the controlled exact-ID CLI path. Browser confirmation
does not replace IdP evidence.

Semantic Profiles supports create, mapping, evidence inspection, validate, retire and explicit
company-scope mappings. Validation needs ten unique PASS native-report cases and current
fingerprints. Drift acknowledgement does not revalidate a stale profile. Company-aware reads
refresh live metadata, reject unbalanced filters and reject navigation/expand until separately
proven. A company-specific profile takes precedence over a source-wide profile.

Users & Groups resolves exact IDs and explains one selected principal/source through
`/admin/v1/effective-access`, with effect/direct/inherited filters and pagination. Another
subject's memberships remain unknown without a trusted directory. At most 50 evidence grants
are returned per company, prioritizing denies; all matching grants determine the result.
Capability authorization and live mapping eligibility remain separate runtime gates.

Lists default to 50 rows (maximum 200) with offset/next_offset and optional source_id. Audit
records `admin-v1`, actor/client, reason, request/key and safe outcomes. Source/company edits
include before/after fingerprints. Correlate request IDs with `admin_request` logs; probe
metrics include outcome/duration, without URLs or credentials.

Native Python 1C and token exchange require identity response encoding, rejecting encoded
responses before decompression. Token JSON is capped at 256 KB; probes at 5 MB and 45 seconds
including queue time, with four dedicated slots and a separate HTTP pool. Successful source
mutation retries replay without fresh source I/O. Production startup rejects owner/operator or
elevated control credentials, including privileged membership.

Runtime credentials must inherit only the app contract, without control/operator/owner rights.
JWKS keys have a five-minute set TTL and ten-second fetch timeout. Configure complete string
group IDs: malformed/distributed-overage claims deny until a trusted resolver exists; remote
claim URLs are never followed. Callback completion is capped at 30 seconds. Connection/ref
changes mark drift and stale validated profiles even with identical XML. Acknowledge the current
fingerprint and create/revalidate a suitable profile with native evidence afterward. Admin
refresh preserves register evidence only for stable matching metadata; new/drifted register
support stays unknown until the existing data-plane discovery supplies evidence.
