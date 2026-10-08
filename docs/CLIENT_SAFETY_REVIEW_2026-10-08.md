# ERP_MCP Client Safety Review — 2026-10-08

## Decision
Production release remains **NO-GO**. This review is limited to OAuth client identity hardening at base HEAD `40317f0` on isolated branch `hardening/client-safety-20261008`.

## Change CS-001 — OAuth client identity fail-closed
- Replaced the permissive `unknown-client` fallback in `JWTTokenVerifier` with explicit refusal for missing, blank, or non-string client identity.
- Preserved existing precedence of `client_id`, `azp`, and `appid` for compatibility.
- Added negative and positive regression cases to `tests/test_auth.py`.

## Independent review checks
- Safety: requests without a usable OAuth client identifier must not inherit a shared audit/client identity.
- Compatibility: an explicit valid `client_id` still works without `azp`; standard `azp` tokens stay supported.
- Limitations: no real IdP or live 1C validation was performed; this is synthetic/unit evidence only.
- Test evidence: targeted `tests/test_auth.py` 15 passed; combined suite `tests/test_auth.py tests/test_admin_capability_refusal_chain.py tests/test_analytics_balance_routing.py` 103 passed, 1 skipped.
- Static diff check: `git diff --check` returned no whitespace errors; local CRLF normalization warning noted.

## Client promises gate
ERP_MCP Phase P2 is the capability router, not the proposed workflow/copilot ERP_MCP v2 product. Do not advertise autonomous execution, production write access, completed native reconciliation, or general production readiness without exact-head, real-source, independently reviewed evidence.

## Remaining release blockers
Follow `docs/PILOT_EVIDENCE_GATE.md`, `docs/DEFINITION_OF_DONE.md`, and frozen scope in `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md`. Real 1C reference checks, native reports, IdP negative tests, secret rotation, load/failure/restore drills, and release authorization remain mandatory.
