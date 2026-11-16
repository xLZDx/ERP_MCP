# FIN-S2.4 — Preserve downstream failure semantics at private ingress

Task: FIN-S2.4 — Require positive authentication and private-only ingress

## Finding and change

The private ingress request-validation `try` block also enclosed downstream dispatch. A downstream exception could therefore be rewritten as HTTP 400 `SCHEMA_INVALID`; if the downstream had already sent `http.response.start`, the wrapper could try to send a second response start.

The ingress now marks the boundary before dispatch. Exceptions raised after downstream invocation propagate to the ASGI server instead of being mapped to ingress validation, authorization, or body-limit responses. This preserves the server-side error/unknown outcome and avoids a duplicate response start.

## Verification and limits

The assigned functional-test-reviewer ran the named `test_s16_approval_core.py` and `test_s16_private_ingress.py` modules at source HEAD `20b2833f78316f51f1096402a3ff35ba3ae9a26b`; 65 passed with 2 warnings in 0.96 seconds. The ingress cases cover downstream exceptions before response start and after a response start has been emitted. The scoped run used `--confcutdir=tests/phase2` because the root conftest could not import `MCPServer` from the installed MCP SDK.

This is synthetic/current-tree evidence only; no listener or production binding was enabled. It does not establish live authentication, deployment exposure, or a 1C write. Formal FIN acceptance remains pending the ledger's exact-head review and verification records.
