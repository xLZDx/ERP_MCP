# Change Record 355 — request-level tests of the private ingress

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers the new `tests/phase2/test_s13_private_ingress_boundary.py` and log entries. No source change.

## Tests

- Authenticator raises an unexpected error: dispatch and lookup return 503 `AUTHENTICATION_UNAVAILABLE`; the log names the class and not the message.
- Authenticator rejects the credential: 401.
- Non-loopback peer: 403 `PRIVATE_LOOPBACK_REQUIRED`, authenticator never called.

## Method note

The factory requires exact types, so bare instances stand in for the service, authenticator, authorizer and runtime, with the called methods patched on the classes. A small ASGI wrapper turns the TestClient `scope[server]` list into the tuple that uvicorn sends.

## Verification state

- RUN: 4 passed; ruff F,E9 clean.
- Open: dispatch and lookup request bodies, authorizer branches, a test that builds a `CallIdentity`, a maximum-size trust snapshot test, review.
