# S16 Code Design — Approval Channel and MCP Tool Boundary

Sprint: `beea27520b33`  
Authority: `docs/sdlc/requirements.md` REQ-007–REQ-013 and `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md` rev. 2.  
Status: implementation blueprint; this document is not implementation or runtime evidence.

## 1. Design decisions

1. Put all S16 code in a new, isolated `src/erp_mcp_s16/` package. Import S12 proposal/value contracts and S15 verification types; do not import, wire, or start the gateway or private writer. Rev. 2 requires injected ports and fakes while upstream acceptance is unresolved (§§2–4).
2. Keep decisions in `core.py`; ports and in-memory fakes only store/read state, provide time/entropy, or call a verifier. In particular, fake persistence cannot decide identity independence, token class, validity, approval binding, expiry, or whether a claim is allowed (S16 §5.1).
3. Separate the preview bytes from the final approval envelope to avoid a circular hash. `canonical_preview_bytes` is deterministic canonical UTF-8 for the visible preview object and excludes `preview_digest` and the nonce. The service computes `preview_digest = SHA256(canonical_preview_bytes)`, places it in the S12 proposal, issues the nonce, then calls S12 `approval_canonical_text(proposal, approval_nonce=...)` and `digest_of_canonical_text(...)`. The resulting `approval_digest` binds the proposal, nonce, and `preview_digest`; that digest commits to the exact visible bytes transitively through `preview_digest`. The page renders only fields parsed from the exact stored `canonical_preview_bytes` and checks that their stored `preview_digest` matches; it neither serializes a second representation nor creates an approval claim. This preserves S12-APPROVAL-2 (`src/business_ai_gateway/phase2/change/proposal.py`, `approval_canonical_text`, `digest_of_canonical_text`; S16 §5.3).
4. A store exposes an atomic `claim_once` primitive, but the core performs every authorization and freshness check before calling it. The in-memory fake uses a lock and compare-and-set for its claim only; it does not own policy. Claim and apply-port call are separate, and only the winner may call apply. Database-backed cross-process atomicity is outside S16 and remains unproven (S16 §5.2).
5. Use a typed `AuthenticatedPrincipal` supplied by an authenticator at the boundary; never build identity from model arguments, headers alone, or a session cookie without authentication. `person_id` is the human identity used for requester/approver independence; `principal_id`, roles, token class, epoch, and scope are explicit inputs.
6. Reuse the single S12 `ErrorCode`/`Refusal` registry and its constant-text `render` function for domain refusals at transport boundaries. Do not use unrelated free-text classifiers or echo exception text, secrets, approval nonce, CSRF token, session identifier, or internal record identifiers (S16 E16-3/E16-5; `change/errors.py`).
7. Approval and MCP are separate route applications/factories. The approval page has no MCP tool and the model tool registry has no approval name or alias. Ingress factory construction does not bind a socket, register a gateway route, or enable writer calls (S16 §§2, 5).
8. Recommended strict defaults for this fake-backed slice: approval nonce lifetime 5 minutes; approver session 15 minutes idle and absolute lifetime; no reauthentication prompt for each decision while that authenticated session remains valid; server-rendered HTML with no scripts; CSP `default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; script-src 'none'`; `Cache-Control: no-store`; `Referrer-Policy: no-referrer`; and a host-only `HttpOnly; Secure; SameSite=Strict` session cookie. Reject approval when a required target-registry amount threshold is absent; do not invent a permissive default. These values resolve S16 Q3/Q4's strict-value and no-script decisions, but remain design recommendations, not existing facts or production configuration. Keep them named and injectable for tests.

## 2. Package and dependency direction

```text
src/erp_mcp_s16/
  __init__.py                 # exports only constructors and public immutable types
  contracts.py                # principal, scope, preview, approval, receipt/result, ports
  core.py                     # pure decisions and orchestration over ports
  registries.py               # principal/target read contracts + in-memory fake registries
  services.py                 # ChangeService and ApprovalService; issuance and app composition
  approval_page.py            # isolated approver HTTP handlers/rendering; no business decisions
  tools.py                    # exactly five MCP tools; safe errors; no approval route
  ingress.py                  # private-only ASGI factory, auth + route checks; does not bind
  fakes.py                    # permissive persistence fakes, deterministic clock/nonce/recorder
```

Allowed imports point from `contracts`/`core` toward existing S12 immutable values and S15 verifier types. `services`, `approval_page`, `tools`, and `ingress` may depend on `core` and contracts. `core` must not import HTTP/MCP frameworks, SQL, gateway app composition, or the COM writer. `approval_page` and `tools` may share the service API but not call each other's handlers. Existing ingress code is a behavior reference only: `src/erp_mcp_private_writer/private_ingress.py` validates loopback peer/host and forwarded headers, but S16 ingress must add positive authentication and must not import/start that writer app.

## 3. Typed contracts (`contracts.py`)

The following are Python typing-level contracts (prefer frozen, slotted dataclasses and `Protocol`; validate untrusted construction at boundaries). Exact imports from S12/S15 are named to make the integration seam reviewable.

```python
@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    principal_id: str
    person_id: str
    roles: frozenset[PrincipalRole]  # REQUESTER | APPROVER | READ_ONLY
    token_class: TokenClass          # CHAT_WRITE | APPROVER_SESSION | READ_ONLY | OTHER
    epoch: int
    scope: ScopeGrant                # tenant/company/org/base fingerprint
    session_id: str | None           # internal only; never serialize or log
    expires_at: datetime             # timezone-aware UTC

@dataclass(frozen=True, slots=True)
class TargetScope:
    tenant: str
    company: str
    organization: str
    base_fingerprint: str
    target_class: str

@dataclass(frozen=True, slots=True)
class TargetVersion:
    value: str
    observed_at: datetime
    source_revision: str

@dataclass(frozen=True, slots=True)
class PreviewSnapshot:
    change_id: UUID
    version: int
    scope: TargetScope
    target_version: TargetVersion
    canonical_preview_bytes: bytes  # bytes rendered by page; no separately rebuilt preview model
    preview_digest: str             # lowercase SHA-256 of canonical_preview_bytes
    approval_canonical_text: str    # exact S12 approval_canonical_text bytes, UTF-8
    approval_digest: str             # digest_of_canonical_text(approval_canonical_text)
    nonce_digest: str                # raw nonce exists only inside approval_canonical_text
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    change_id: UUID
    version: int
    scope: TargetScope
    requester_person_id: str
    approver_person_id: str
    approver_principal_id: str
    approver_epoch: int
    session_id: str
    nonce_digest: str                # raw nonce never leaves service or approval store
    decision_ref_digest: str         # browser receives only the unguessable opaque ref
    preview_digest: str
    approval_digest: str
    decision: Literal["APPROVE", "REJECT"]
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class DecisionPage:
    decision_ref: str                # unguessable opaque value; the only submitted capability
    canonical_preview_bytes: bytes   # render this exact service-issued byte string
    preview_digest: str
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class DecisionBinding:
    change_id: UUID
    version: int
    scope: TargetScope
    principal_id: str
    person_id: str
    session_id: str
    nonce_digest: str
    decision_ref_digest: str
    csrf_binding_digest: str         # internal verifier bound to ref + session; never sent
    preview_digest: str
    approval_digest: str
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class DomainReceipt:
    change_id: UUID
    status: ChangeStatus
    version: int
    scope: TargetScope
    proposal: ChangeProposal        # existing S12 value, not reconstructed from client fields
    requester_person_id: str
    approval: ApprovalDecision | None
    target_version: TargetVersion

class ChangeStore(Protocol):
    def get(self, change_id: UUID) -> DomainReceipt | None: ...
    def insert_proposal(self, receipt: DomainReceipt) -> None: ...
    def save_approval(self, decision: ApprovalDecision) -> None: ...
    def claim_once(self, change_id: UUID, *, expected_version: int,
                   expected_approval_digest: str, claimant_id: str) -> ClaimResult: ...

class ApprovalStatePort(Protocol):
    def issue_decision_ref(self, binding: DecisionBinding) -> str: ...
    def consume_decision_ref_and_nonce(self, decision_ref: str, *, session_id: str,
            principal_id: str, person_id: str, origin: str, referer: str,
            decision: Literal["APPROVE", "REJECT"], now: datetime) -> DecisionBinding | ErrorCode: ...

class PrincipalRegistryPort(Protocol):
    def current(self, principal_id: str) -> PrincipalRecord | None: ...
    def epochs_current(self, dependencies: tuple[tuple[str, int], ...]) -> bool: ...
    def are_independent(self, requester_person_id: str, approver_person_id: str) -> bool: ...

class TargetRegistryPort(Protocol):
    def current(self, scope: TargetScope) -> TargetRecord | None: ...
    def resolve_fingerprint(self, scope: TargetScope) -> str | None: ...

class KillSwitchPort(Protocol):
    def reading(self, subject: KillSubject, scope: TargetScope) -> KillReading: ...

class ApplyPort(Protocol):
    def apply(self, receipt: DomainReceipt, claim: ClaimToken) -> ApplyResult: ...

class VerifyPort(Protocol):
    def verify(self, document_ref: str, expected: ExpectedReceipt,
               shape: OperationShape, *, writer_declared_types: Mapping[str, str] | None = None,
               writer_unverified_paths: tuple[str, ...] = ()) -> VerificationResult: ...

class Clock(Protocol):
    def now(self) -> datetime: ...

class NonceSource(Protocol):
    def issue(self) -> str: ...

class SecretStorePort(Protocol):
    def get(self, key: SecretRef) -> SecretValue: ...
    def put(self, key: SecretRef, value: SecretValue) -> None: ...
    def revoke(self, key: SecretRef) -> None: ...

class RouteProbePort(Protocol):
    def inspect(self, host: str, port: int) -> RouteAssessment: ...
```

`ScopeGrant` and `TargetScope` must include the authenticated target's immutable base fingerprint and compare exact tuple equality; do not accept source URLs or caller-selected hosts. `PrincipalRecord` carries the current person mapping, role grants, revocation state and epoch dependencies. `TargetRecord` carries target class, allowlisted address/network policy and configured confirmation threshold; it contains no credential. SecretStore is an unused injectable boundary for this slice unless a target credential is required by an existing read-only probe; never return a secret value in a public receipt. The S16 fake secret store records only key identifiers and access counts.

`ClaimResult` is a closed union: `Claimed(ClaimToken)` or `Refused(ErrorCode)`. `ApplyResult` and every operation return typed domain outcomes/refusals; framework handlers translate them. Fakes may be permissive about policy reads/writes, but `claim_once` itself must be a thread-safe atomic compare-and-set so the concurrency contract is meaningful. The actual database claim stays NOT_RUN until S13 acceptance and evidence.

## 4. Core decisions (`core.py`)

Expose a small synchronous, I/O-free orchestrator over injected protocols (individual port operations may be synchronous in this fake-backed slice). Public operations:

```python
class S16Core:
    def propose(self, requester: AuthenticatedPrincipal, raw_request: Mapping[str, object]) -> Result[PreviewSnapshot, ErrorCode]: ...
    def decide(self, approver: AuthenticatedPrincipal, session: ApproverSession,
               submission: DecisionSubmission) -> Result[ApprovalDecision, ErrorCode]: ...
    def apply(self, requester: AuthenticatedPrincipal, change_id: UUID) -> Result[ApplyReceipt, ErrorCode]: ...
    def status(self, requester: AuthenticatedPrincipal, change_id: UUID) -> Result[DomainReceipt, ErrorCode]: ...
    def verify(self, requester: AuthenticatedPrincipal, request: VerifyRequest) -> Result[VerificationResult, ErrorCode]: ...
    def rollback_propose(self, requester: AuthenticatedPrincipal, change_id: UUID) -> Result[PreviewSnapshot, ErrorCode]: ...
```

### Approval issue / decide

`ChangeService.propose(requester, raw_request, *, now)` validates the S12 parser and derives requester/person/scope/target/version server-side. It generates canonical preview bytes once and computes `preview_digest`; it then issues a raw nonce transiently from `NonceSource`, calls S12 `approval_canonical_text` and `digest_of_canonical_text`, and stores the nonce only as a digest plus inside the exact canonical approval envelope. `ApprovalService.open_preview(approver, session, ticket, *, now) -> DecisionPage` validates the active approver session, creates a random opaque `decision_ref`, and binds that ref and its internal CSRF verifier to the change, approver principal/person/session, scope, version, preview and approval digests, nonce digest, and expiry. The browser gets the decision ref and canonical preview bytes only; raw nonce and CSRF material stay server-side. Do not accept nonce/digest/version from `raw_request`.

`ApprovalService.submit_decision(approver, session, decision_ref, decision, *, origin, referer, now) -> Result[ApprovalDecision, ErrorCode]` first validates principal/session liveness, role/revocation/current epoch, exact same-origin `Origin` and `Referer`, nonce/approval expiry, snapshot version/scope, preview digest from stored bytes, S12 approval digest, human independence, and registry independence. It then calls `S16Core.decide(...)`. Core resolves the opaque ref to server-held binding, verifies internal CSRF binding plus exact principal/person/session and nonce/digests/expiry, and invokes `consume_decision_ref_and_nonce` once. That primitive is atomic under the in-memory store lock: validate-and-consume the decision ref and nonce together, then persist the decision. A repeated ref or nonce returns `APPROVAL_NONCE_INVALID`; no page field can replace the stored binding. Self or same-person alias returns `APPROVER_NOT_INDEPENDENT`.

### Apply and atomic claim

Apply re-loads receipt and current trust/target data; fail closed in this exact order before any `ApplyPort.apply` call: kill switch through S12 `KillSubject`/`evaluate`; authenticated current base fingerprint equals approved scope (`SCOPE_MISMATCH`); requester token class and principal/current epoch plus `epoch_dependencies` (`EPOCH_CHANGED`); approver remains active and authorized (`APPROVAL_VOIDED`); approval/nonce has not expired (`APPROVAL_EXPIRED`); recomputed digest over stored canonical approval text matches receipt and stored preview bytes match `preview_digest` (`DIGEST_MISMATCH`); target version still equals approved version (`STALE_VERSION`); receipt is approved and not already claimed. Then call atomic `ChangeStore.claim_once` with expected change version and approval digest. Only `Claimed` reaches `ApplyPort.apply`; every other contender returns its typed existing-state/refusal outcome. No exception or refusal can be translated into success. The in-memory lock protects claim mutation, not the preceding policy checks; S16 does not claim database transaction/isolation equivalence.

### Verify and rollback

`VerifyPort` is a narrow adapter over `erp_mcp_s15.verifier.verify_receipt` and the S15 `ExpectedReceipt`, `OperationShape`, `VerificationResult`, `VerificationStatus` types (`src/erp_mcp_s15/verifier.py`). Its S12 operation mapping is a read through this port plus `READ_STATUS`; it does not invoke the recovery-worker-only VERIFY operation or perform a lifecycle transition (S16 Q13). It receives the authenticated scope-resolved document reference and server-loaded expected receipt, never a client-selected reader or arbitrary base. Supported shape is exactly S15 `SUPPORTED_SHAPE` (`CREATE_DRAFT`, `RECEIPT`, one line). POST and UNPOST return a `VerificationResult` with `UNSUPPORTED_SHAPE` and do not transition the change to `VERIFIED`. For supported shape, return the S15 result unchanged; no status is upgraded or persisted as success by this tool.

`rollback_propose` maps to S12 `PROPOSE` for an admitted new operation (S16 Q13). It reads the original verified operation and current target version through its injected reader/service. Verified POST creates a distinct UNPOST proposal with `parent_change_id`, exact target scope/ref/version and observed state; it issues its own preview digest and approval nonce through the same services. CREATE_DRAFT and UNPOST rollback return `ROLLBACK_REFUSED` (Q14). The endpoint never approves, claims, or applies the new proposal.

## 5. Service, registries, and fakes

`ChangeService` owns proposal parse/context, snapshot generation, digest/nonce issuance, status lookup and rollback proposal construction. `ApprovalService` owns approval-page use cases and calls core decisions; it does not implement policy itself. The service contracts should be injectable dataclass dependencies, not a new container framework.

`registries.py` defines `PrincipalRegistryPort`, `TargetRegistryPort`, `SecretStorePort`, and `TestIdPPort` plus in-memory fakes. Model-facing principal records and approver-browser sessions are disjoint; no session can be minted from a chat principal. Fake TestIdP issues short-lived approver sessions, rotates/revokes them, and gives the core an `AuthenticatedPrincipal` with `APPROVER_SESSION` class. Registry fixtures must support revoke, role removal, person alias, epoch bump, target fingerprint/version change, and per-target amount threshold.

`fakes.py` defines thread-safe deterministic `FakeClock`, injected deterministic `FakeNonceSource`, permissive policy-read/store fakes, lock-backed one-shot claim store, fixed `FakeApplyPort`, fixed `FakeVerifyPort`, `FakeRouteProbe`, `FakeSecretStore`, and `ToolCallRecorder`. These are test seams only, not production defaults. Fake time is UTC-aware; fake nonce/secret material must never leak from logs or outputs. Recorder stores sanitized tool name, bounded arguments by allowlist, safe result and correlation id; exclude session IDs, nonce, CSRF, credential values and raw exceptions.

## 6. Approval page (`approval_page.py`)

Provide `create_approval_app(service: ApprovalService, authenticator: ApproverSessionAuthenticator, *, origin: str, clock: Clock) -> ASGIApp`. Factory creation is inert and performs no network binding. Routes: GET `/approval/{opaque_ticket}` (authenticate isolated approver session, authorize exact person/scope, call `open_preview`, render the resulting `DecisionPage`); POST `/approval/{opaque_ticket}/decision` accepts exactly `{decision_ref, decision}` (same session, exact Origin/Referer, and atomic one-use decision). The opaque ref is a single-use CSRF capability bound to server-held CSRF state; there is no raw CSRF token field. There is no public API accepting approval claims and no GET mutation.

Render server HTML from escaped text decoded from `canonical_preview_bytes`; reject invalid UTF-8, invalid canonical form, digest mismatch, or non-object schema before rendering. Do not include transcript/chat content. The form carries only the unguessable opaque `decision_ref` and the `APPROVE`/`REJECT` choice: raw nonce and CSRF material never enter browser-visible HTML, request parameters, logs, tool responses, or audit records. Session cookie is isolated from chat/admin cookie. Apply the named strict headers/defaults in §1; require HTTPS semantics for session cookies. Any cross-session, wrong-person, stale, tampered, revoked, expired, or replayed request returns a generic safe response and leaves authorization state unchanged. Audit an allowlisted decision/refusal code and digests only.

## 7. MCP tools (`tools.py`)

Provide `register_s16_tools(server, service, principal_resolver, error_renderer)`. Registration is explicit and does not modify the existing gateway. Expose exactly these names: `propose`, `status`, `apply`, `verify`, `rollback_propose`. Each requires a resolved positive `AuthenticatedPrincipal`; reject unknown names and any attempted `approve`, `approval`, `authorize`, or `confirm` call without state change. Model arguments are strict schemas and contain no principal/person/role/token class, approval/digest/nonce claims, URL/host, target fingerprint, or approval decision fields. All five carry the plan-required not-read-only annotation.

Tool handlers only parse bounded arguments, resolve the principal, call `ChangeService`/core, and serialize allowlisted response fields. Refusals and unexpected exceptions go through the S12 `ErrorCode` registry and constant-text renderer; map unknown failures to a fixed internal refusal and correlation id. Never reuse `business_ai_gateway/tool_errors.py`'s free-text classifier as the S16 domain registry; its contract differs. `tools/list` derives from one immutable five-entry manifest to prevent drift.

## 8. Private ingress (`ingress.py`)

Provide `create_private_s16_app(tool_app, approval_app, authenticator, route_probe, config) -> ASGIApp`; return a composed ASGI object only. Bind-time configuration remains outside scope and no process manager or gateway references it. Default permitted listener addresses are loopback only; additional explicitly configured private ranges are accepted only after a `RouteProbePort` assessment. For every request, reject forwarded headers (`Forwarded`, `X-Real-IP`, `X-Forwarded-*`), multiple/mismatched Host, foreign Origin/Referer for state changes, public/non-private target, redirects, proxy route, unresolved/rebinding host, then require positive authentication appropriate to the route (approver session for approval, write-audience authenticated principal for tools). Network origin alone is never authentication. Ingress rejects before handler/apply-port invocation and maps details to safe errors. Reuse the validation behavior in `private_ingress.py` as a reference; implement the minimal S16 adapter independently so the writer remains unimported and untouched.

## 9. Implementation sequence and ownership split

Independent workers can proceed against `contracts.py` after its API is frozen. Keep S16 code isolated from E1 SQL/S12/S13 work.

1. **Contract/API owner (Codex):** add package skeleton and `contracts.py`; settle enum/result field names and S12/S15 imports. No cross-package wiring.
2. **Core owner (Codex):** implement `core.py` policy, validation order, issuance and atomic claim call against protocols; include no HTTP/MCP code.
3. **Registry/service owner (Codex):** implement `registries.py`, `fakes.py`, `services.py`; provide permissive policy store and one-shot atomic fake claim; compose approval/proposal use cases.
4. **Approval page owner (Codex):** implement `approval_page.py` against `ApprovalService` and session authenticator; isolated route factory only.
5. **Tool owner (Codex):** implement `tools.py` using frozen tool manifest and shared safe error mapper; exactly five names.
6. **Ingress owner (Codex):** implement `ingress.py` after page/tool factories exist; auth and private-route guards, no listener start.
7. **Replay owner (Codex):** implement deterministic transcript replay through registered tool surface after tools and recorder exist; record only sanitized artifacts.

The sprint backlog assigns all implementation to Codex; these are implementation seams, not unassigned project owners. Files are independent after `contracts.py`; do not split core policy ownership across page/tool handlers.

## 10. Narrow verification map (run only in the post-code test phase)

`functional-test-reviewer`/`e2e-runner` own authoring and execution under the workspace test-ownership rule. Map the cases below to REQ-007–REQ-013 and S2.1–S2.4; no tests are asserted run by this design artifact.

| Boundary | Required falsifying cases | Acceptance trace |
|---|---|---|
| Core and permissive store | self/same-person approval; wrong token class; nonce replay or wrong session/person; mismatched digest/version/scope/expiry; approver revoked; epoch change; kill switch; changed base/target version; N parallel apply calls produce one claim and at most one ApplyPort call | REQ-007–008; S2.1 AC-1–4 |
| Digest and preview bytes | no hash cycle; exact preview bytes render; altered canonical bytes fail digest; S12 approval digest recomputes from stored canonical text and includes issued nonce + preview digest | REQ-008; S2.1 AC-4; S2.2 AC-3 |
| Approval HTTP | chat principal denied; CSRF/Origin mismatch; cross-session/person nonce; stale/revoked/expired session; duplicate submit; XSS payload is inert; required headers/cookie; secrets/session identifiers absent from body/log/audit | REQ-008–009; S2.2 AC-1–3 |
| Tools and safe errors | tools/list exact five and annotations; no approval aliases; forged approval claims ignored/refused; structured safe error on refusal and exception; no raw details | REQ-010, REQ-013; S2.3 AC-1–2, AC-5 |
| Verify and rollback | S15 `VerificationResult` passthrough unchanged; POST/UNPOST `UNSUPPORTED_SHAPE`, never VERIFIED; verified POST creates separate UNPOST approval proposal; CREATE_DRAFT/UNPOST rollback refused; rollback never applies | REQ-011–012; S2.3 AC-3–4 |
| Ingress and wiring | missing/invalid auth, forwarded headers, host mismatch, public address, redirect/proxy/rebinding all denied before ApplyPort; app factories inert; no gateway registration or production binding | REQ-009, REQ-016; S2.4 AC-1–3 |
| Replay | same fake clock/nonce seed/state yields deterministic safe transcript; artifacts omit nonce, CSRF, session, secrets and raw exception | S16 E16-5; REQ-013 |

## 11. Explicit limits and unresolved technical facts

- No durable S16 persistence, schema, migration, deployment, listener binding, real IdP, real client replay, UAT, COM write, or gateway registration is designed or authorized; those remain outside this slice (S16 §§2, 5 and REQ-016).
- The typed contracts above are proposed interfaces, not current repository APIs. S12/S13/S15 acceptance remains as recorded in the rev. 2 source until separately reconciled with current gate evidence.
- Atomic in-memory claim proves same-process fake behavior only. It does not establish cross-process correctness or production transaction guarantees.
- Existing S15 verifier is restricted to the one-line CREATE_DRAFT receipt shape and documents unsupported shapes in `src/erp_mcp_s15/verifier.py`; no POST/UNPOST verifier is proposed.
- Recommended expiry/security-header constants in §1 resolve an implementation detail from S16 Q3. They remain code constants for this fake-backed slice; production session, key, secret-provider and network policy decisions require a later authorized design.
