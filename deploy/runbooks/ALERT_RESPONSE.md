# Alert response quick reference

These actions are non-destructive and apply to the bounded alerts in
`deploy/alerts/prometheus.rules.yml`.

| Alert | First checks | Safe response |
|---|---|---|
| `ErpMcpHighServerErrorRate` | correlation IDs, error code distribution, readiness | disable affected source route; preserve logs; do not bypass ACL |
| `ErpMcpDependencyErrors` | dependency metric and readiness state | isolate failed dependency/source; verify recovery before traffic |
| `ErpMcpAuditAppendErrors` | audit DB connectivity and pool health | fail closed; stop data calls until audit writes recover |
| `ErpMcpHighLatency` | p95 route histogram, pool wait, source timeout counts | reduce fan-out/concurrency; keep explicit deadlines |

Never place tokens, credentials, query values or native report contents in incident records. Use
the rollback runbook only with named operator authorization.
