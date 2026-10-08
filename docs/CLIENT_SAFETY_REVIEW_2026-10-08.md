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

## Closure verification — 2026-10-09

- Full broad local regression with only stale checkpoint test deselected: **1933 passed, 343 skipped, 1 deselected** (413.21 seconds, zero failures).
- After re-pin to exact source fingerprint `9c52ddd81209c95ee99494d65d2d133e6b88b2d6e62c25d1a2e7477f12dbead2`, separate checkpoint and release-evidence tests: **41 passed**.
- `scripts/check_report_references.py`: **PASS**, five required artifacts.
- Current batch `CLIENT_SAFETY_20261009`; historic hosted PASS refers to a previous release branch commit and is not evidence for this local patch.
- New positive `appid` compatibility case and negative blank-`client_id` with valid `azp` case are included in the broad suite.
- No live IdP, customer 1C, destructive action, or production deployment was used. **Production NO-GO, DoD PARTIAL.**

## Exact implementation fingerprint — full re-run closure (2026-10-09)

- Initial full-suite execution after checkpoint change: **1933 PASS, 343 SKIP, 1 FAIL**. The failing case was `test_fault_and_rsv_harnesses_cover_recovery_without_1c`; it runs another bounded pytest subprocess. This failure is preserved, not erased.
- Diagnostic execution of `scripts/fault_injection_runner.py`: **11/11 test cases PASS**, valid Compose plan, `timed_out=false`; focused harness test: **1 PASS** in 38.10 seconds.
- Second full suite: **1934 PASS, 343 SKIP, zero failures**, 387.78 seconds (`var/full-final-retry.log`). This supports a transient/harness-load hypothesis, but does not prove the fault can never recur.
- `reports/CURRENT_ENGINEERING_CHECKPOINT.json` local count updated; the bound implementation SHA256 stays `9c52ddd81209c95ee99494d65d2d133e6b88b2d6e62c25d1a2e7477f12dbead2`. Current head's hosted pipeline and live IdP/1C are NOT_RUN.
- No production/customer readiness inferred; DoD PARTIAL, production NO-GO.
