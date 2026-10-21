# WP0 source liveness check — 2026-10-21

Scope: read-only liveness verification for the local 1C lane and the named Ivan remote lane.
Repository revision observed: `4dfceeddb071a63e7d8f815e7c276555de6d2375` on `main`.

## Local lane

Exact PowerShell listener command:

```powershell
$ports = 18088,8191,8192,8193,21768,21080,21000,21200,18432,19379
foreach ($port in $ports) {
  if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1) {
    "PORT $port LISTEN"
  } else {
    "PORT $port DOWN"
  }
}
```

Unauthenticated GETs used `Invoke-WebRequest -Method Get -MaximumRedirection 0 -TimeoutSec 2
-SkipHttpErrorCheck` against each listed URL (the realm JWKS request used `-TimeoutSec 3`).
Exact Docker command: `docker ps --filter 'name=erpmcp-e2e-real1c' --format 'CONTAINER {{.Names}}
{{.Status}}'`.

Observed listener output:

```text
PORT 18088 LISTEN
PORT 8191 LISTEN
PORT 8192 LISTEN
PORT 8193 LISTEN
PORT 21768 LISTEN
PORT 21080 LISTEN
PORT 21000 LISTEN
PORT 21200 LISTEN
PORT 18432 LISTEN
PORT 19379 LISTEN
```

Observed HTTP output:

```text
HTTP 401 http://127.0.0.1:18088/erp_mcp_ref/odata/standard.odata/$metadata
HTTP 401 http://127.0.0.1:18088/erp_mcp_probe/odata/standard.odata/$metadata
HTTP 401 http://127.0.0.1:8191/erp_mcp_ref/odata/standard.odata/$metadata
HTTP 401 http://127.0.0.1:8192/erp_mcp_ref/odata/standard.odata/$metadata
HTTP 401 http://127.0.0.1:8193/erp_mcp_ref/odata/standard.odata/$metadata
HTTP 200 http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/certs
HTTP 200 http://127.0.0.1:21000/readyz
HTTP 200 http://127.0.0.1:21000/healthz
HTTP 401 http://127.0.0.1:21000/mcp
HTTP 406 http://127.0.0.1:21200/mcp
```

Observed Docker output:

```text
CONTAINER erpmcp-e2e-real1c-postgres-1 Up 9 hours (healthy)
CONTAINER erpmcp-e2e-real1c-redis-1 Up 9 hours (healthy)
```

The plain GET to the phase-2 MCP endpoint returns 406; its expected event-stream negotiation
was not exercised in this liveness check. A first request to the IdP root discovery URL returned
404; the configured realm JWKS URL above returned 200. No service needed restarting.
`Get-ScheduledTask -TaskName 'ERP_MCP_Lane_Autostart'` returned state `Ready`; its action was not
invoked or inspected during this check.

The in-repository autostart script `scripts/real1c/autostart/start_lane.ps1` was updated to resolve
the current repository root, use its `.venv`, accept an Apache port argument (default `18088`),
select the corresponding `httpd-erp-mcp-test-ready-<port>.conf`, and pass the matching upstream to
new lane proxies. The script was **not run**: it also controls Docker, tunnel, IdP and gateway
processes, and this liveness check did not require a restart. Syntax/runtime behavior remains
unverified.

## Business-read evidence

`accounting_balance_by_analytics` was **NOT_RUN**. Calls to the connected `ERP_MCP_REAL1` status
and source-list tools returned MCP internal errors. Calls to the connected `erp-mcp-chatgpt`
status and source-list tools returned `UNAUTHORIZED`: “This app connection requires
reauthentication. Reconnect the app and try again.” No business data was read. The local MCP
endpoint returned 401 without a bearer token; this check did not inspect, print, or retrieve any
token or secret.

Repeat read-only checks later in this turn called `ERP_MCP_REAL1.system_status`,
`ERP_MCP_REAL1.sources_list`, and `ERP_MCP_REAL1.source_health(source_id="onec-818ha-reference")`.
All three again returned MCP `-32603: Internal error`; no business-read tool was called and no
business data was received.

## Ivan remote lane

`Test-NetConnection -ComputerName 100.88.71.74 -Port 21000 -InformationLevel Quiet` returned
`True`. The requested read-only SSH commands (`run-mcp-stack.ps1 -Action Status` and
`verify-1c-env.ps1`) were **NOT_RUN**. OpenSSH rejected the host before authentication:

```text
No ED25519 host key is known for ivan.tail08f9f9.ts.net and you have requested strict checking.
Host key verification failed.
```

Follow-up after the initial check: `tailscale ping --c 1 ivan.tail08f9f9.ts.net` returned
`pong from ivan (100.88.71.74)` over the direct Tailscale path. `tailscale status --json`
showed the Ivan peer online; the peer's `SSHEnabled` field was blank/absent. Both
`tailscale ssh ivan.tail08f9f9.ts.net whoami` and an attempted remote PowerShell command
failed before authentication with the same strict host-key error. No remote command was
executed. Strict checking was retained; no host-key checking option was weakened and no
key was written to `known_hosts`.

No remote status, 1C environment verification, MCP read, task start, or token mint was
performed. Exact dependency: the host key must be trusted by the OpenSSH/Tailscale SSH
path. A live Tailscale peer and open TCP port are network reachability evidence only.

## WP0 result

Local listener and anonymous-denial checks: observed as above. Local business read and the Ivan
remote checks: **NOT_RUN** for the exact dependencies recorded above. This artifact does not claim
source health, business-read success, or production readiness from liveness alone.
