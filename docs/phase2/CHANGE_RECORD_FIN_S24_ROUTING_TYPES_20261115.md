# FIN-S2.4 change record — validate private ingress routing field types

Date: 2026-11-15
Task: FIN-S2.4 — Require positive authentication and private-only ingress

## Finding

Manual source review found that the private ingress compared the ASGI `scheme` and `method`
fields without first requiring exact string values. A caller-controlled object with custom
comparison behavior could influence endpoint and POST checks before authentication.

## Decision

For recognized approval/tool routes, require `scheme` and `method` to be exact strings before
comparing either value. Use only those validated local values for HTTPS, host, origin, body
limit, and downstream routing decisions. Preserve valid request behavior and keep malformed
requests before authentication and dispatch.

## Verification and limits

This is source-level hardening. The named malformed-field regression remains to be authored by
the test role and is `NOT_RUN`; operator rule 4 prohibits pytest and automatic checks. No
listener or production binding was enabled. FIN-S2.4 remains unaccepted pending the verification
gate.
