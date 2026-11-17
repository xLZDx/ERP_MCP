# FIN-S2.4 implementation record — bound Content-Length parsing

## Scope

This record covers a bounded input-parsing hardening change in the fake-backed S16 private ingress. It does not start a listener, add a production binding, or authorize a 1C write.

## Finding and change

The ingress converted caller-controlled `Content-Length` text to an integer before checking it against the configured body limit. The parser now rejects non-ASCII or non-decimal lengths as malformed and compares normalized decimal text with the configured maximum before any integer conversion. Oversized valid lengths retain the fixed HTTP 413 refusal. Chunked requests remain protected by the existing incremental body cap before downstream dispatch.

## Evidence and remaining acceptance

- Source inspection: `src/erp_mcp_s16/ingress.py` validates the configured limit at app construction and now compares a normalized decimal length without converting arbitrary attacker-controlled digits to an integer.
- The S16 acceptance map includes malformed and oversized `Content-Length` inputs and requires refusal before downstream dispatch.
- Tests, checks, builds, CI, migrations, listener startup, database operations, and 1C operations are `NOT_RUN` under the sprint rules. FIN-S2.4 remains `PARTIAL` and unaccepted.

## Follow-up implementation — reject an explicit zero origin port

Source review found that `origin.port or 443` treated an explicitly configured port `0` as though no port had been supplied. The ingress now uses 443 only when the URL has no port; an explicit zero reaches the existing valid-port check and is rejected. The S16 acceptance map adds the malformed configuration case.

This is source and contract evidence only. The config-construction regression remains `NOT_RUN` under operator rule 4; FIN-S2.4 remains `PARTIAL`.

## 2026-11-15 follow-up — positive CHAT_WRITE identity boundary

Source review found that private ingress accepted a typed `CHAT_WRITE` principal based on token class and role membership without requiring nonempty principal/person IDs, a valid nonnegative epoch, a boolean MFA field, a TEST lane, or a well-formed TEST scope. The ingress now rejects those structurally incomplete identities before invoking the downstream MCP app. The S16 acceptance map adds exact malformed identity cases and the zero-downstream-call expectation.

This is source-only evidence. No tests/checks or listener were run; FIN-S2.4 remains `PARTIAL`.

## 2026-11-15 — Reject malformed ASGI scope containers at private ingress

Source review found the private ingress called `scope.get()` before validating the ASGI scope object. Non-dict input could therefore escape the fixed refusal boundary instead of failing before authentication or downstream dispatch. The wrapper now returns `SCHEMA_INVALID` with HTTP 400 before reading scope fields; the S16 acceptance map includes this zero-downstream-call case.

Source-only progress. Regression remains `NOT_RUN` under operator rule 4. No listener, gateway, database, or 1C action was performed, and production bindings remain empty.

## 2026-11-15 — Focused regressions authored, execution prohibited

The functional-test-reviewer added raw-ASGI regression cases in `tests/phase2/test_s16_private_ingress.py` for 1024-digit Content-Length refusal before route probing, explicit `:0` origin rejection, incremental body overflow, malformed `more_body`, and an 8193-message empty-body flood. The tests assert refusal before downstream dispatch where applicable. They were not run: operator rule 4 prohibits pytest and automatic checks. Accordingly, task verification is `NOT_RUN`; source and regression authoring do not establish runtime acceptance.

## 2026-11-15 — Validate ASGI scope type before comparison

Source review found `scope["type"]` was compared with string literals before checking its exact type. A malformed object with a raising equality method could escape the wrapper before a fixed refusal was sent. The ingress now rejects non-string scope types with `SCHEMA_INVALID` HTTP 400 before comparison, while preserving the existing no-op behavior for valid non-HTTP scopes. A raw-ASGI regression asserts no authenticator, route-probe, or downstream call. This regression was not run under operator rule 4; FIN-S2.4 remains unaccepted pending its acceptance evidence.
