# Change record — project-plan snapshot preservation — 2026-11-15

## Intent

Commit the three existing historical project-plan HTML snapshots requested by the operator without rewriting them or confusing them with the live program-status report.

## Included artifacts

- `reports/ERP_MCP_PROJECT_PLAN.ru.pre-S13-02-render-20261110-0426.html`
- `reports/ERP_MCP_PROJECT_PLAN_2026-11-07_pre-FIN-S1.1-closeout.html`
- `reports/ERP_MCP_PROJECT_PLAN_2026-11-07_pre-FIN-S1.1-closeout.ru.html`

These are preserved snapshots, not regenerated current reports. The current supported Russian status artifact is `reports/ERP_MCP_PROGRAM_STATUS_LIVE.ru.html`. FIN remains open in the ledger (2/10 tasks done); this documentation commit does not close FIN or authorize a later sprint. Push remains subject to the exact-head GPT-PM approval gate. No tests, checks, runtime services, or 1C business-data operations were run.
