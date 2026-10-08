# Phase 2 client safety — physical-backend budget validation

**Scope:** isolated worktree `D:\Repo\ERP_MCP-phase2-safety-review`, branch `hardening/phase2-budget-validation`, base `9cb66343456c37e914fb473dc5aa0f03cf0ea325`.

**Release verdict: NO-GO unchanged.** This change protects an in-process reference capacity budget; it does **not** add a distributed production rate limiter, authorize a release, run a live connector, or advance G0–G7.

## Finding — P2 capacity bound could be silently disabled

`PhysicalBackendBudget.__init__` relied on chained numeric comparisons. Python allows booleans and floating-point values in these comparisons, so `total_limit=float('inf')`, `per_backend_limit=1.5`, and boolean limits were accepted. An accidentally unbounded limit breaks the intended safety ceiling for source workload. The constructor now requires strictly positive built-in integers and `per_backend_limit <= total_limit`, rejecting all other values as `INVALID_BUDGET` before any reservation.

## Verification and review

- Reproduction **RED** before code change: 6 failing negative cases (`test_capacity_configuration_rejects_noninteger_or_unbounded_limits`), 33 deselected.
- Targeted test file after change: 39 PASS (`test_backend_budget.py`), preserving concurrency and backend-alias tests.
- Entire isolated Phase 2 offline suite after change: **333 PASS / 65 SKIP** (PostgreSQL integration tests unavailable without a configured isolated DSN), 10.11 seconds.
- Ruff on `src/business_ai_gateway/phase2` and `tests/phase2`: **PASS**.
- Security review: type-identity check excludes `bool`, `float('inf')`, fractional floats and arbitrary numeric proxies. Invalid input fails before state allocation.
- Architecture review: no new product functionality and no changes to OAuth, 1C, registry, SQL, or R1. Production needs a distributed atomic budget (`R2-US-019` is not delivered here).
- Test review: negative cases were demonstrated RED and GREEN; no test was skipped to turn red into green.

## Open / operator-gated

See `IMPLEMENTATION_STATUS.md`, `EVIDENCE_MATRIX.md` and `OPERATOR_BACKLOG.md`. G0 scope, real source credentials, native report attestation, Drive OAuth, real UAT and production release approval remain blocked/unverified as before. A successful local suite is not release evidence. No merge, production deployment or permission expansion is authorized by this review.
