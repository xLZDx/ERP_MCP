# Change Record 351 — private ingress diagnostics (review finding F5)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `private_ingress.py` and log entries.

## Change

The four broad `except Exception` handlers now log the exception class name (no message, no payload) before returning the unchanged 503 responses. A serialization failure after a successful dispatch still returns `WRITER_OPERATION_UNAVAILABLE` with `outcome_unknown` true; that is the correct contract because the client never saw the outcome.

## Verification state

- RUN: import check and ruff F,E9.
- NOT_RUN: request-level tests (none exist for the ingress; building one needs real service, authenticator, authorizer and runtime), review.
- Open: F6 (trust snapshot and barrier-ack lookup).
