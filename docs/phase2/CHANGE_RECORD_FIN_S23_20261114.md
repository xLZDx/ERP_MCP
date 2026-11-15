# FIN-S2.3 change record — FastMCP schema parity

Date: 2026-11-14  
Task: FIN-S2.3 — Expose exactly the approved five model-facing tools  
Status: implementation follow-up; acceptance remains partial.

## Context

The immutable `S16_TOOL_MANIFEST` already defines the five approved tool names and JSON schemas. Source review found that the `register_tool` adapter passed those schemas explicitly, but the FastMCP adapter decorated one generic callable with `arguments`, `context`, and `_name` parameters. FastMCP derives `inputSchema` from the callable signature, so that route did not publish the manifest contract.

## Change

- Build a per-tool FastMCP handler signature from the manifest's property names.
- Preserve each property's declared JSON Schema, including nested `verify` constraints, with Pydantic `WithJsonSchema` metadata.
- Mark FastMCP `Context` as injected transport context, so it does not become a model-facing argument.
- Keep the explicit `register_tool` adapter and its supplied manifest schema unchanged.
- Extend the S16 E16-3 acceptance map with schema-parity and context-exclusion criteria.

## Verification and limits

- Read-only source inspection of the installed MCP SDK found that `FastMCP.tool` derives parameters using `inspect.signature` and Pydantic metadata; its context discovery uses a `Context` type annotation.
- No tests, checks, builds, CI, migrations, listeners, database operations, or 1C operations were run. FastMCP schema parity is `NOT_RUN` under the sprint test restriction.
- This change does not register S16 tools on the existing gateway, qualify a writer, add a production binding, or establish runtime/deployment acceptance.

## Decision

Use the same immutable manifest for both supported adapter paths. Do not silently keep a FastMCP route that advertises a different argument contract. FIN-S2.3 remains partial until the assigned functional tests and remaining sprint gates are completed.

## Follow-up implementation — normalize refusal before custom rendering

Source review found the dispatcher called an optional custom error renderer with the service's raw `Result.error` before the shared safe-error path normalized it. A malformed service error could therefore reach callback code even though its rendered output was discarded. The dispatcher now converts non-`ErrorCode` refusal values to `AUDIT_UNAVAILABLE` before invoking the callback and before constructing the response. The S16 acceptance map includes a capturing-renderer case.

This is source and contract evidence only. The focused malformed-error regression remains `NOT_RUN` under operator rule 4; FIN-S2.3 remains `PARTIAL`.

## 2026-11-15 follow-up — validate model-facing result fields

Source review found that the dispatcher checked the outer `Result` but the `propose`, `status`, and `apply` serializers could return malformed service-supplied field values without validating their public types or bounds. The serializers now require exact receipt/snapshot classes, valid identifiers and versions, bounded UTF-8/control-free public text, a well-formed preview digest and aware expiry, and typed target scope/version fields. An invalid value raises into the dispatcher's fixed `AUDIT_UNAVAILABLE` response. The acceptance map requires malformed-result fakes and verifies that no malformed field reaches the MCP response.

This is source-only evidence. No tests/checks were run under operator rule 4; FIN-S2.3 remains `IN_PROGRESS` and unaccepted.

## 2026-11-15 follow-up — type the S15 verification port result

Source review found that the S16 `ChangeServicePort.verify` protocol declared `Result[Any, ErrorCode]`, although the S16 contract's `VerifyPort` and the S15 verifier return the concrete `VerificationResult`. The adapter protocol now carries that concrete result type, aligning static implementer contracts without changing runtime behavior or the five-tool surface. The S16 plan already requires `verify` to pass through the S15 outcome unchanged.

This is source and contract evidence only. Tests/checks/build/CI remain `NOT_RUN` under operator rule 4; FIN-S2.3 remains unaccepted.

## 2026-11-15 — Add focused S16 tool-contract regressions

The functional-test-reviewer added named cases for the FastMCP `tools/list` names and schemas matching the immutable manifest with transport context excluded, preserving the full S15 `VerificationResult` including findings/unverified paths, and rejecting an argument whose encoded input fits a raw-value estimate but whose actual serialized representation exceeds the adapter budget before service dispatch. Earlier S2.3 regressions cover the separate rollback proposal and refusal/error boundaries. These tests were authored but not executed under operator rule 4; FIN-S2.3 remains unaccepted.

## 2026-11-15 follow-up — fail closed when an adapter cannot publish the manifest

The focused S2.3 run exposed a stale test dependency: the locked MCP 2.x package replaces `mcp.server.fastmcp` with `mcp.server.mcpserver.MCPServer`. The high-level MCPServer decorator has no explicit input-schema parameter; it derives a Pydantic schema that adds fields and does not preserve the manifest's closed-object rule. Removed that misleading signature-derived fallback. Registration now requires a callable `register_tool(name, handler, schema, annotations)` adapter, preflighted before any tool is registered, and publishes each immutable manifest schema verbatim. Existing exact-key dispatch validation is retained. MCPServer-only objects fail closed with `UNSUPPORTED_TOOL_SERVER`; connecting S16 to that gateway requires a separate low-level integration design with authenticated context.

The functional-test-reviewer ran `uv run --locked --extra dev python -m pytest tests/phase2/test_s16_tools.py -q` after the fix: exit 0, 15 passed in 0.83s. The regression asserts exact manifest schemas through the explicit adapter and refusal of tool-only servers. FIN-S2.3 is verified; gateway integration and later FIN gates remain open.
