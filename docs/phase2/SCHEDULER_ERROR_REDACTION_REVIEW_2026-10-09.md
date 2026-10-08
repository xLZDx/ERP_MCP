# ERP_MCP Phase 2 — SCH-02 adapter error redaction

Date 2026-10-09. Isolated branch `hardening/phase2-scheduler-error-redaction-20261009` based on `edc8d9d`. **Local-only fix; Release 2 remains NO-GO.**

## Finding (reproduced RED)

`SourceScheduler.run_job` previously forwarded `f"{type(exc).__name__}: {exc}"` to `_failed`. This text became `RunResult.detail`; after poison threshold, `last_error` persisted it through the job port. A connector/HTTP exception containing `Authorization: Bearer canary-secret-do-not-log` therefore leaked into result and durable job metadata. The special `LeaseLost(str(exc))` path also returned arbitrary work-controlled strings. Three negative/updated tests reproduced the issue RED.

## Fix and review

- Work callback exception text is now replaced with fixed `WORK_EXCEPTION`, for retry and poisoned states.
- The arbitrary `LeaseLost` string is no longer echoed; outcome carries fixed `LEASE_LOST`.
- This preserves retry/fence/poison decisions while eliminating raw adapter messages from these two output paths. No new connector permissions or mutation API added.
- Target tests assert **no canary secret** in result or durable `last_error`; normal retry, poison, lease loss, backend budget and recovery paths remain green.
- Full Phase 2 offline suite: **782 PASS / 180 SKIP**, Ruff PASS, compileall PASS. No PostgreSQL or customer runtime test was performed on this isolated branch.
- Security red-team caveat: other ports, logging layers and exception handlers need their own leakage review; this change does not prove an end-to-end secret-free production deployment. Synthetic secrets only, no real tokens logged.

**Residual:** production release NO-GO; independent exact-head G0–G7 evidence required. The active Phase 2 working tree is not changed by this branch.
