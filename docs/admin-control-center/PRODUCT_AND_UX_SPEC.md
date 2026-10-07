# Product and UX specification — proposal

**Status:** supplemental design proposal; not an amendment to the frozen ERP_MCP v1.0 baseline.

## Purpose

Provide operators a browser surface for the control-plane workflows that currently use CLI commands, while preserving the baseline's trust boundaries. First release should make existing source, company, grant, drift and semantic-profile operations inspectable and auditable. It must not make new authorization claims until a governed backend design implements them.

## Verified current state

| Area | Current baseline |
|---|---|
| Sources | `bag.sources`; source-upsert CLI; server-side secret references; runtime resolves registered `source_id`; read-only transport |
| Companies | `bag.companies`; unique `(source_id, external_ref)`; company-upsert CLI |
| Identity | OAuth/OIDC subject, client, groups, scopes; no local password/user provisioning |
| ACL | `bag.access_grants`; subject/group; source or optional company scope; allow/deny; expiry/revocation; deny overrides allow; no grant denies |
| Generic OData | Requires an active source-wide grant; company-only grant cannot authorize unscoped source reads |
| Company scope | Company list and grant evaluation exist; company data operations remain unavailable until adapter enforcement is end-to-end tested |
| Audit | Append-only access audit and provenance fields exist; operator-admin workflow audit attribution must be designed before replacing CLI |
| Metadata drift | Sticky drift state; current fingerprint acknowledgement through CLI |
| Semantic profiles | Draft/validate/retire lifecycle and mapping commands exist; validation requires ten passing native-report reconciliation cases |
| Web admin | No web Admin UI or web admin API in current baseline |
| Admin roles / business RBAC | No delegated control-plane role system or completed role-to-capability enforcement in the current baseline |

## Users and jobs

- **Platform operator:** inspect overall health and administer existing workflows.
- **Source operator:** register/update a source with secret references, inspect source/capability state and acknowledge drift.
- **Access operator:** inspect principals and effective grants; add or revoke a grant with clear source/company boundaries.
- **Profile operator:** inspect profile provenance and lifecycle; create/validate/retire profiles only if existing CLI operations can be safely exposed through an audited API.
- **Auditor:** read configuration and history without mutation.

The exact operator authorization mechanism is a design gate. Do not infer these roles from a JWT group name or present them as effective before server-side enforcement exists.

## Navigation and screens

1. **Overview** — live source health and sync/drift summary, registered companies, grant-change activity. Every value comes from an API; remove fictional counts outside the mock.
2. **1C sources** — list/detail, registered configuration and capability profile, health state, metadata fingerprint/drift. Create/update with secret references only. Test connectivity and preview organizations only after a safe server-side probe contract is approved.
3. **Companies** — browse by source, stable external reference, display name, enabled/default state. Explain that company visibility does not automatically mean company-scoped data reads are currently available.
4. **Users & groups** — search/resolve IdP subjects and groups through a trusted server-side directory integration or supplied identity claims. No local password or identity provisioning.
5. **Access grants** — show principal, scope, effect, expiry/revocation state and provenance. Source-wide grants must be visually distinguished from company-scoped grants. Warn that generic OData requires source-wide grants; company-scope data access is gated on adapter support.
6. **Capabilities & metadata** — show discovered capability evidence, metadata fingerprint, sticky drift state, prior fingerprint and acknowledgement state. Acknowledge only the currently displayed fingerprint.
7. **Semantic profiles** — show profile lifecycle, source/company applicability, fingerprints, validation cases and profile events. Preserve the ten-case native-report validation gate.
8. **Audit** — show access audit and, after the admin mutation contract exists, attributable configuration changes. Redact secrets and sensitive request data.
9. **Roles & capabilities** — informational/disabled until a separate approved design and backend enforcement are complete.

## Key flows

### Register or update a source

Collect source ID, display name, approved base URL and username/password secret references → validate inputs server-side → execute a bounded server-side connectivity/capability check if approved → show safe metadata and discovered organizations → operator reviews → upsert/register. Never accept or return secret values. URL validation must be enforced at the server egress boundary, not trusted to the form.

### Add/revoke a grant

Resolve the IdP principal → select source → optionally select a registered company only where supported → choose allow/deny, expiry and reason → show effective impact and precedence → confirm → server writes via a least-privilege, attributable admin service. Revoke by a precisely identified grant ID, retaining history; do not recreate the CLI's broad matching revocation behavior without a reviewed contract.

### Acknowledge drift

Display source ID, current and previous fingerprints, detection time, and material metadata change → require operator acknowledgement tied to the exact current fingerprint → submit → refresh state. A subsequent fingerprint change must invalidate the acknowledgement as in the existing sticky-drift policy.

### Validate a semantic profile

Show exact source/company and capability/metadata/profile fingerprints, case count and reconciliation evidence → invoke the existing validation contract → display pass/fail/ineligible reasons. UI must not override the ten passing native-report cases.

## API direction — requires architecture decision

No route names are assumed. Prefer a narrow control-plane API service with explicit operator authentication/authorization and audited commands. Reuse domain validation and SQL semantics where safe; do not call CLI subprocesses or expose the admin database DSN to HTTP handlers. Keep `business_ai_app` runtime permissions separate from `business_ai_admin` mutation privileges. Decide whether a dedicated admin service/role or an approved API boundary is appropriate before implementation.

Required resource operations: read sources/companies/principals/grants/capabilities/profiles/audit; create/update source via secret refs; register companies; add/revoke exactly identified grants; acknowledge drift by expected fingerprint; existing profile lifecycle commands. Every mutation needs actor, reason, outcome and correlation data in durable audit, idempotency/retry behavior, concurrency rules and stable errors.

## UI states and accessibility

Provide loading, empty, error, stale, forbidden and success states. Make `healthy`, `drifted`, `disabled` and `untested` distinct text states, not color-only. Keyboard navigation, visible focus, accessible table labels, responsive layout and 200% zoom are required. Show timestamps with timezone. Confirm broad source grants and group grants with impact details.

## Visual direction

Dark operations console, restrained teal for healthy/enabled states, amber for drift, red for denial/error. Compact but legible tables, clear boundary warnings, keyboard-accessible interactions. The sample rows in `index.html` are explicitly mock data, not current ERP_MCP state.
