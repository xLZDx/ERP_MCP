# FIN-S2.2 — Validate ASGI routing fields before approval handling

Date: 2026-11-15
Task: FIN-S2.2 — Implement the protected approval page and session boundary
Scope: the inert, fake-backed S16 approval ASGI page. No listener is created or enabled.

## Finding

The approval app compared `scope["type"]` and later the HTTP `method` value with string literals before validating their types. A malformed method object with a raising equality implementation could escape the handler before a fixed refusal was sent; authentication also ran before routing-field validation.

## Change

The app now requires an exact string scope type before comparison, preserves the existing ignore behavior for valid non-HTTP scopes, and requires exact string method and path fields for HTTP scopes. Malformed values return the registered `SCHEMA_INVALID` response with HTTP 400 before authentication, body reads, or service calls.

## Acceptance evidence

Added `test_malformed_http_scope_fields_return_schema_error_before_auth_or_service`. It covers a non-string scope type and a method whose equality comparison raises, then asserts a fixed 400 response and zero authenticator/service calls. The separate bounded-form test also remains in the pending FIN-S2.2 regression set.

The focused regressions and all other tests/checks are `NOT_RUN` under the operator's rule 4. This is source/contract evidence only; browser, IdP, listener, and runtime acceptance remain open.
