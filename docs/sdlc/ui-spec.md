# S16 Approval Page UI Specification

Sprint: beea27520b33  
Scope: V2-S16-01 approval page only; fake-backed, not deployed. This specification follows docs/sdlc/requirements.md REQ-007–REQ-013 and docs/phase2/S16_SPRINT_PLAN_2026-10-28.md rev. 2 §§5.1–5.3, E16-1, E16-4, and Q3–Q6. S16 remains an unqualified, disabled writer; this page does not authorize production binding, deployment, or real 1C writes.

## Journey

1. A requester proposes a change through the model-facing tools. The model gets a status/reference response only; approval is not an available tool or action in chat.
2. An independent approver opens the private approval origin and authenticates through the lane's test identity provider. A requester, chat/model principal, read token, or write-audience token cannot establish an approver session.
3. The server resolves the pending change and renders a read-only preview from the exact canonical_preview_bytes returned by ApprovalService/ChangeService. SHA-256 of those bytes is preview_digest. Separately, internal S12 approval_canonical_text binds preview_digest and the raw approval nonce; its approval digest is not the SHA-256 of displayed preview bytes. The page creates or alters neither value.
4. The approver reviews the version/scope/amount and chooses Approve or Reject. A valid isolated approver session remains authenticated until its idle or absolute expiry; no extra per-decision re-authentication is required within that lifetime. After expiry, authenticate again. For POST or an amount above the configured threshold, type the exact change kind and displayed amount before submitting. The threshold is read from policy, never hard-coded in page logic.
5. The server validates person independence, live session, origin/referer, the opaque session-bound single-use decision reference, internal nonce binding, digest, version, scope and expiry. It atomically consumes the decision reference and nonce with recording the decision. A successful decision produces an audit event; later apply independently revalidates all required facts. Rejection ends in lifecycle REJECTED.

## Screen and component inventory

| Component | Content and contract | Events / behavior |
|---|---|---|
| Approval shell | Plain server-rendered HTML; heading “Review change”; change reference, immutable version, status, requester identity label, created/expiry times. No scripts. | Every request is authenticated and authorized server-side. The form may carry only an unpredictable opaque decision reference; internal session id, raw approval nonce, and CSRF secret never appear in markup, URL, logs, audit, errors, or tool response. |
| Scope summary | Tenant/company/organization and target/base fingerprint; proposed change kind and amount; explicit “Preview only — no change has been applied.” | Values come from authorized service records, never request/chat text. Render all untrusted values using context-correct HTML escaping. |
| Canonical preview | Readable text rendered directly from canonical_preview_bytes; display preview_digest (SHA-256 of those exact bytes), version, and immutable-preview notice. Internal approval_canonical_text and approval digest are not presented as a hash of the displayed bytes. | No second serialization, client formatting, or caller-supplied preview fields. HTML encoding must preserve the canonical text content. |
| Decision form | Separate POST forms/buttons for Approve and Reject; carries one opaque decision reference bound server-side to this page/session, person, change, scope, digest, version, and expiry. Confirmation input appears when policy says required. | POST only; require exact same-origin Origin or Referer and the opaque reference. The core resolves its server-side binding and atomically consumes reference and raw nonce; duplicate, stale, or cross-session submission cannot decide. |
| Status/result panel | Fixed success copy (“Decision recorded.” / “Rejection recorded.”) or safe refusal title and next action from the shared ErrorCode registry. | Never include exception strings, stack traces, secrets, raw identifiers or internal diagnostics. Unknown failures map to a fixed generic safe response. |

### Proposed UI contracts

- ApprovalPage(change_record, canonical_preview_bytes, preview_digest, version, expiry, policy) -> HTML response; preview_digest is SHA-256 over the exact displayed canonical_preview_bytes. The renderer cannot issue nonce/digest or mutate state. The internal approval_canonical_text separately binds preview_digest and raw approval nonce under the S12 approval digest.
- DecisionForm(opaque_decision_ref, decision, confirmation_text) -> POST; the only capability in the browser is an unpredictable, single-use reference bound server-side to the session/page, person, change, scope, preview_digest, version, and expiry. Server-side state retains the raw approval nonce and CSRF secret. The core resolves and validates bindings and atomically consumes reference/nonce with the decision.
- SafeError(code, next_action) -> fixed title/body/action; text is selected from the shared registry and escaped. No dynamic exception detail is rendered.
- Actions: Approve, Reject, Sign in, Re-authenticate, Return to pending changes, and Try again only where the registry's next action permits retry. No generic “continue anyway” action.

## States and copy

| State | User sees | Available action / transition |
|---|---|---|
| Empty | “No pending changes require your review.” | Return to private workbench. Do not show requester-controlled content. |
| Loading | Native page navigation with “Loading review…” only if server response is delayed; no client spinner required. | Wait; repeated navigation is safe and does not consume the decision nonce. |
| Ready | Complete immutable preview, scope, requester, expiry, policy confirmation requirement, Approve and Reject. | Review then submit one decision using the page's opaque decision reference. |
| Confirmation required | “Confirm this {kind} for {amount}” and a text field requiring the exact displayed phrase; explain policy requires extra confirmation. | Submit enabled only on exact match; server repeats comparison against policy and canonical proposal. Applies to POST and amount above configured threshold. |
| Session expired | “Your approval session has expired. Sign in again.” | Authenticate again; return to the same change only after server rechecks its current status/version and issues a new decision reference. |
| Decision recorded | Fixed success message and recorded lifecycle outcome. | Return to pending list. Refresh does not repeat the decision. |
| Rejected | “This change was rejected.” | Return to pending list. Do not offer retry against the rejected version. |
| Stale / superseded | “This review is out of date. Reopen the current version.” | Discard old form and fetch current service state. Old reference and server-side nonce remain unusable. |
| Expired | “This approval request has expired.” | Return to pending list; requester must create a new proposal if needed. |
| Refused / invalid | Safe registry message, e.g. approval no longer valid, digest mismatch, invalid/replayed approval token, or requester not independent. | Follow only registry next action; never silently retry a decision. Authorization state remains unchanged for invalid decisions. |
| Session revoked | “Your approval session is no longer valid. Sign in again.” | Re-authenticate; server checks current revocation and approver liveness. |
| Permission denied | “You cannot review this change.” | Return to private workbench; do not reveal whether another change exists. |
| Offline / service unavailable | “The review service is unavailable. No decision was recorded.” | Retry by reloading after service recovery. Never present a false success; server must establish the recorded outcome before success copy. |
| Error | Fixed generic “We could not load this review.” with safe retry action where permitted. | Correlation support, if provided, uses a non-sensitive random reference; diagnostics stay server-side. |

## Identity, token and replay boundaries

- Independence is by stable person identity, not account name: requester and approver person_id must differ; two accounts belonging to the same person are the same person. The registry must positively establish this relation. Unknown, revoked, or unavailable identity state fails closed.
- Separate the approver session store and cookie scope from chat, model, admin, and workbench sessions. A chat principal cannot create or exchange into an approver session. A session is checked for revocation and approver liveness on every request.
- Token classes are not interchangeable: model/author principal, read-scope token, write-audience token, approver session cookie, internal CSRF secret, raw approval nonce, and browser-visible opaque decision reference. Only the typed authenticated approver session may enter the decision flow. The browser reference is a narrowly bound single-use capability, not the raw nonce/session id/CSRF secret; it is never logged or disclosed in errors/tool responses. Wrong class/audience is refused before any apply-capable call.
- Raw CSRF secret and service nonce remain server-side. One unpredictable opaque reference is issued for a page/session and bound to person, change, scope, preview_digest, version, and expiry. The core resolves the reference, validates the hidden secret bindings, and atomically consumes reference and nonce while recording the decision. Replay, cross-session use, cross-person use, stale versions, and concurrent replacement fail closed.
- Every decision POST requires exact same-origin Origin or Referer (missing or foreign is refused) and the opaque single-use decision reference. GET never changes state. Host, forwarding-header, private-route and redirect checks remain mandatory at the private ingress boundary.

## Security headers and responsive/accessibility behavior

Proposed restrictive response headers: Content-Security-Policy: default-src 'none'; script-src 'none'; style-src 'self'; img-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; Cache-Control: no-store; Referrer-Policy: no-referrer; and X-Content-Type-Options: nosniff. Approver cookie proposal: host-only, Secure, HttpOnly, SameSite=Strict, narrowly scoped Path=/approval, no Domain. Exact CSP/session values below are selected design values for architecture alignment and later test assertions.

Use semantic headings, definition lists for scope facts, a pre or equivalent text-only canonical preview, explicit labels, and field-level error text associated with the confirmation input. Native buttons and forms work without JavaScript. Focus follows document order; after a server error, focus the error heading via normal page navigation and identify the affected field in text. Do not convey status by color alone. Ensure readable contrast, text zoom/reflow without horizontal page scrolling at phone widths, and touch targets at least 44×44 CSS pixels. At desktop widths, constrain preview line length and retain the same single-column reading order. Motion is absent, satisfying reduced-motion preferences automatically. Mark timestamps with timezone and identify monetary currency/units from canonical data.

## Numeric assumptions and open questions

| Item | Proposed default | Status / owner |
|---|---|---|
| Approver session lifetime | 15-minute idle and absolute expiry; no per-decision re-authentication while valid; authenticate again after expiry | Selected design value; isolated approver authentication still required. |
| Approval nonce lifetime | 5 minutes, independently expiring and single-use | Selected design value; server-side only. |
| CSRF/reference | Raw CSRF secret remains server-side; browser receives only an unpredictable opaque, session/page-bound, single-use decision reference | Selected design boundary; bind person, change, scope, preview_digest, version, and expiry; never log or disclose reference. |
| Large-amount threshold | Named policy/registry value; no UI constant or invented amount | Concrete value UNKNOWN in Q3; keep open for policy owner/GPT-PM. |
| Typed confirmation phrase | Exact canonical change kind plus displayed amount/currency for every POST and any amount above threshold | Proposed interaction; architect confirms policy mapping and tests assert it. |
| Human approver identities / production IdP | Not selected in S16; test IdP only | Explicitly deferred; operator owns production identity decision after current scope. |
| Session storage | Separate in-memory fake for S16 | Persistence choice after S13 acceptance (Q5); GPT-PM owns later architecture decision. |

## Acceptance mapping

| Acceptance | UI evidence required | State |
|---|---|---|
| REQ-008: preview integrity | Displayed text derives from exact canonical bytes; service owns digest/version/nonce; tampered or stale submission is refused. | Specified; implementation and tests not part of this document task. |
| REQ-009: private approval access | Positive authentication each request; origin/referer, host, proxy, redirect and route protections; no origin-only trust. | Specified; runtime not claimed. |
| REQ-013: safe refusal | Fixed registry copy and next action; no exception details or secret output. | Specified; runtime not claimed. |
| S16 E16-1 | Immutable preview, independent approver, isolated/revocable session, CSRF/CSP/framing, confirmation, append-only audit on decisions, no secret/token leakage. | Specified; no UAT or production IdP claim. |
| Accessibility | Keyboard-operable native forms, semantic labels/headings, errors in text, responsive reflow, contrast, touch targets, no motion. | Design specification only; independent a11y review/UAT remains separate. |

## Open questions

1. What numeric policy threshold triggers extra confirmation? Keep it in the policy registry; do not choose an amount in the UI layer.
2. Which stable person-identity source guarantees that multiple accounts resolve to the same person_id? S16 uses the test registry/IdP only; production identity is deferred.
3. Confirm selected 15-minute session and 5-minute nonce lifetimes against the core expiry contract during architecture review.
4. Confirm whether confirmation is exact kind plus amount/currency for every POST and threshold-exceeding non-POST operation; the UI must not infer an amount for non-monetary kinds.
5. The approver application's final private origin and TLS/cookie deployment values remain unconfigured because deployment is out of scope.
