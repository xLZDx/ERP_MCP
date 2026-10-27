# Change record 181 — fail-closed private writer caller authentication

## Changes made in this turn

- Added `src/erp_mcp_private_writer/private_auth.py`, an ingress-independent authentication
  primitive that accepts exactly one bearer JWT header, delegates signature/issuer/expiry
  verification to an injected verifier, independently requires the fixed
  `urn:erp-mcp:private-writer` audience and `erp_mcp:private_writer` scope, and checks the explicit
  allowed client IDs.
- Added a verifier factory that binds the repository JWT verifier to that fixed audience, scope,
  issuer, and configured JWKS endpoint; missing issuer/JWKS settings refuse construction.
- Added a safe caller identity containing only subject, client ID, and scopes for later audit
  correlation. Credential text and verifier error details are never included in refusal messages.
- Exported the authentication contract from `src/erp_mcp_private_writer/__init__.py` and indexed
  this change record.

## Why

ADR-0009 and the S13 Ivan-lane design require the writer boundary to remain separate from the public
read-only MCP gateway and to authenticate callers against an explicit allowlist. Reusing the
gateway's local-development `Principal` fallback would make an unauthenticated writer path possible.
The new primitive therefore requires a verified token, a fixed writer-specific audience and scope,
and a non-empty client allowlist. Those values are local contract candidates; IdP client provisioning
and the actual caller identity have not been established.

## Security and operational boundary

- The verifier factory requires a configured trusted issuer/JWKS; it does not load settings,
  secrets, keys, or network clients.
- A listener must still bind only to loopback or a separately ACL-restricted Tailscale interface.
  No listener, dispatch endpoint, COM writer, runtime composition, or service process is created.
- This policy authenticates the caller only. It does not verify an S12 ticket/permit, approve a
  change, grant PostgreSQL/1C rights, admit a dispatch, or authorize a COM operation.
- The permission-unavailable result is distinct internally from an invalid credential and carries
  no dependency details. Callers must map both to a deny response without logging the bearer token.

## Verification and remaining work

- Manually reviewed the current `JWTTokenVerifier` signature/issuer/audience/scope behavior in
  `src/business_ai_gateway/auth.py` and confirmed that `current_principal()` can create a
  development identity without OAuth; that fallback is not reused here.
- No tests, checks, build, listener, service, database, COM operation, staging, commit, or push ran.
  Auth-policy behavior and integration are `NOT_RUN`.
- After all coding is complete, `functional-test-reviewer` and `e2e-runner` must qualify malformed
  and duplicate authorization headers, invalid/expired/wrong-audience tokens, missing scope,
  disallowed clients, verifier outage, and the allowed private client against a disposable harness.
- Accountable task owner: operator. Executor: Codex. The Ivan stack owns the host connection
  boundary; no human identity for the future writer client or IdP provisioning owner is established
  by the sources inspected in this turn.

## Evidence

- `src/business_ai_gateway/auth.py` — JWT signature, issuer, audience, expiry, and scope checks.
- `src/business_ai_gateway/principal.py` — local-development fallback that is unsuitable for a
  writer boundary.
- `docs/adr/ADR-0009-private-test-writer.md` — private-only ingress and caller-authentication
  requirement.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` — separate private writer
  process and prohibition on public MCP exposure.
