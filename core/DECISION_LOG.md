# Decision log (functional-tester branch qa/functional-tester-sc01-sc12)

## 2026-10-07 - Black-box functional suite for SC01-SC12

- Decision: author tests/functional (real MCP Streamable-HTTP client, env-parametrised FT_*) and a
  private disposable stack (scripts/ft, ports 25432/26379/28766/28000). No src/, migration or
  security-boundary change.
- Decision: statuses are observed at run time. A scenario is PASS only if a public tool answered and
  the invariant held; otherwise EXTERNAL-GATE (tool fails closed: no VALIDATED semantic profile, and
  bag.semantic_profiles requires ten native-report cases by DB check constraint) or NOT IMPLEMENTED
  (no public tool/data). No synthetic profile or native evidence was fabricated.
- Evidence: Fake1C is synthetic L1 only; never native 1C reconciliation.
- Commit: see git log on this branch.
