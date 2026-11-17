# Change Record 405 — isolated S16 approval page, tools, and private ingress

## Scope and authority

Implements the S16 rev. 2 fake-backed transport slice authorized by `docs/sdlc/requirements.md`
REQ-007–REQ-013 and `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, sections 2, 5, 6 and 9. The
implementation is limited to `src/erp_mcp_s16/approval_page.py`, `tools.py`, and `ingress.py`.
No existing gateway, private-writer, listener, process manager, test, or database path is modified.

## Decisions and contracts

- `tools.py` publishes one immutable manifest containing exactly `propose`, `status`, `apply`,
  `verify`, and `rollback_propose`. It has no approval entry or alias. Model arguments use closed
  top-level schemas; identity is resolved through an injected resolver and must be an
  `AuthenticatedPrincipal`. Caller-supplied identity, scope, approval, digest, nonce, decision,
  target, URL, and host claims are rejected, including in nested proposal data. Response objects
  are serialized from explicit allowlists. Refusals use the shared S12 `ErrorCode`/`render`
  registry and a random correlation reference; exception text is suppressed.
- `verify` constructs the S15 typed request and returns the verifier's status, label, findings,
  and unverified paths without promoting a result. `rollback_propose` delegates to the service;
  the tool does not approve or apply a rollback.
- `approval_page.py` is a separately constructed, standard-library ASGI app. Each request must
  authenticate to an `ApproverSession`; GET calls `ApprovalService.open_preview`, and only POST
  calls `submit_decision`. The page renders the exact service-provided canonical preview bytes,
  verifies their SHA-256 `preview_digest`, validates the canonical UTF-8 JSON object, and HTML
  escapes it. The internal S12 approval digest and nonce are never rendered. The only browser
  capability is the service-issued `decision_ref`; the confirmation phrase and requirement are
  service-provided and passed to the service for core enforcement. Missing required policy data
is refused. POST requires an exact same-origin Origin and same-origin Referer, strict form
  content type, bounded body, and unique allowlisted fields. A required confirmation applies to
  approval submission; rejection remains independently available without that confirmation.
  GET cannot decide, consume, or apply.
- The page sends a script-free CSP (`default-src 'none'`, `script-src 'none'`, and
  `frame-ancestors 'none'`), no-store/no-referrer/nosniff and frame-denial headers. Its markup is
  server-rendered, uses semantic headings, a labelled and described confirmation input when
  required, native decision buttons, and text status/error messages. The isolated session cookie
  remains the authenticator's responsibility; this module defines the host-only cookie name and
  required Secure/HttpOnly/SameSite=Strict/Path=/approval attributes, and never mints or exposes
  session credentials.
- `ingress.py` returns a composed ASGI callable only. It starts no listener and accepts only
  HTTPS requests whose peer and server addresses fall within loopback by default; additional
  private CIDRs must be explicitly configured. The configured origin must be an HTTPS private IP
  literal and match the request server address/port. Every request rejects forwarded headers,
  duplicate headers, mismatched/multiple Host values, invalid Origin/Referer, public endpoints,
  and unresolved, redirecting, or proxy-routed route-probe results before delegating. It requires
  a positive typed writer principal for the tool route and a separate typed approver session for
  the approval route. A downstream redirect is replaced by a safe refusal. The listener binding
  set remains empty.
- Current core service contracts use a UUID proposal ticket for `open_preview`; the approval
  route therefore accepts a canonical UUID reference and converts it to the typed UUID before
  service invocation. This retains service-side authentication, scope, requester-independence,
  expiry, digest, and nonce checks. A distinct opaque ticket-issuance endpoint is not added in
  this transport-only scope.
- GET may issue and persist the short-lived, one-use `decision_ref`/CSRF binding needed to render
  the form. This is transient anti-replay capability state only: it does not consume the approval
  nonce, save an approval decision, alter lifecycle/authorization, or call apply. A repeated GET
  may issue another unused page capability; a consumed reference remains unusable. “GET never
  mutates” therefore means no business decision or lifecycle mutation, consistent with the
  service-owned capability issuance contract.

## Files and affected contracts

| File | Change |
|---|---|
| `src/erp_mcp_s16/tools.py` | Five-tool immutable manifest, strict boundary parsing, injected principal resolution, safe allowlisted responses/errors. |
| `src/erp_mcp_s16/approval_page.py` | Inert server-rendered approval ASGI app, canonical preview validation, isolated session authentication, origin/referrer and one-use decision submission. |
| `src/erp_mcp_s16/ingress.py` | Inert private ASGI composition, per-request endpoint/Host/forwarding/origin/route/authentication checks, redirect refusal. |
| `docs/phase2/CHANGE_RECORD_405.md` | Implementation decisions, boundaries, and evidence state for this change. |

The modules use the typed contracts in `src/erp_mcp_s16/contracts.py` and the corresponding
`ChangeService`/`ApprovalService` APIs. Core policy remains in `S16Core` and services, including
approval independence, confirmation policy, digest/version/session checks, apply revalidation,
claim-once behavior, verification outcomes, and rollback rules.

## Safety and evidence state

- Implemented in source: separate model and approver boundaries; exactly five model tool names;
  principal resolution outside request bodies; service-owned preview/digest/decision references;
  positive authentication; strict private ingress checks; safe refusal text; inert factories.
- Not implemented or enabled here: gateway registration, listener startup, production binding,
  real IdP, real connector/target access, database persistence, COM writer calls, deployment,
  production use, or real 1C POST/UNPOST. The private writer remains unqualified and disabled.
- `NOT_RUN`: tests, checks, lint, build, runtime probes, listener startup, migration, and
  production verification. They are deferred until all sprint coding is complete and assigned
  to the repository's designated test/review owners. No test or runtime pass is claimed.
- Residual boundary: ingress requires the configured `RouteProbePort` to return the declared
  `RouteAssessment` fields with an exact literal-address match for each request; deployment-specific
  proxy/network topology and TLS termination are not established by these source-only adapters.

## Acceptance and next action

| Requirement | State | Evidence / remaining acceptance |
|---|---|---|
| REQ-008 — preview integrity | Implemented in source; runtime `NOT_RUN` | Approval page checks the service digest against the exact canonical bytes and renders those bytes; assigned test owners must exercise tamper and replay cases. |
| REQ-009 — positive private authentication | Implemented in source; runtime `NOT_RUN` | Ingress checks typed principal/session and private route facts on each request; test owners must run negative Host/proxy/origin/authentication cases. |
| REQ-010 — exact model tool surface | Implemented in source; runtime `NOT_RUN` | `S16_TOOL_MANIFEST` has five entries and no approval name/alias; test owners must verify enumeration and unknown direct calls. |
| REQ-011 — unchanged verifier outcome | Implemented in source; runtime `NOT_RUN` | Tool serializes S15 status without upgrade; test owners must assert POST/UNPOST remain unsupported. |
| REQ-012 — separate rollback proposal | Delegated to service/core; tool boundary implemented; runtime `NOT_RUN` | Core/service owns rollback semantics; test owners must verify no approval/apply and the specified refusal/proposal outcomes. |
| REQ-013 — safe errors and no claims | Implemented in source; runtime `NOT_RUN` | Tool/page render constant registry text and suppress exception details; test owners must inspect responses and captured output. |

Next, the primary Codex coordinator should finish all in-scope code, then assign the mapped
functional/E2E evidence and relevant independent security/accessibility reviews. Owner for this
implementation and handoff is Codex; no production or external action is claimed.
