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

### SSH identity and trust recheck — 2026-10-22

- Project inventory found no repository-local SSH key or `known_hosts` file. The default
  local identity at `~/.ssh/id_ed25519` and its public companion have matching SHA-256
  fingerprints (the client fingerprint is omitted from this project record). Its ACL grants
  FullControl to the current user, SYSTEM, and Administrators; all three entries are inherited.
  The SSH agent is unavailable (`ssh-add -l` exited 2 with “Error connecting to agent: No such
  file or directory”). This establishes local file readability, not that the key is authorized
  for the ERP host; that association remains **NOT_VERIFIED**.
- Read-only trust-store commands were `ssh-keygen -F ivan.tail08f9f9.ts.net -f
  "$env:USERPROFILE/.ssh/known_hosts"` and the same command with `known_hosts.old`. Both
  exited 1 without a match. `Test-Path C:\ProgramData\ssh\ssh_known_hosts` returned `False`.
- `ssh-keyscan -T 5 -t ed25519 ivan.tail08f9f9.ts.net` observed host fingerprint
  `SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`. This is network-observed key
  material only; no authenticated out-of-band record in the project matches it, so it
  was not trusted or written to a known-hosts file.
- A fresh `tailscale ping --timeout=8s ivan.tail08f9f9.ts.net` returned a pong from
  `100.88.71.74` in 2 ms. Strict OpenSSH used `ssh -T -o BatchMode=yes
  -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE/.ssh/id_ed25519"
  -o "UserKnownHostsFile=$env:USERPROFILE/.ssh/known_hosts" -o ConnectTimeout=8
  koros@ivan.tail08f9f9.ts.net exit`; it exited 255 with “No ED25519 host key is known” and
  “Host key verification failed.” `IdentitiesOnly=yes` and the explicit identity limit this
  attempt to that one identity. `tailscale ssh ivan.tail08f9f9.ts.net whoami` also exited 255
  with the same host-key error. Both stopped before authentication. No remote command ran.
- The exact access blocker remains an authenticated out-of-band source for the Ivan
  host key. A live Tailscale peer, a scanned key, and a matching client key do not
  establish remote identity or SSH authorization.

Essential command/output summary (PowerShell; no key blobs or credentials recorded):

```text
ssh-keygen -lf "$env:USERPROFILE/.ssh/id_ed25519"       -> SHA256 fingerprint A
ssh-keygen -lf "$env:USERPROFILE/.ssh/id_ed25519.pub"   -> same SHA256 fingerprint A
(Get-Acl "$env:USERPROFILE/.ssh/id_ed25519").Access      -> owner, SYSTEM, Administrators; FullControl; inherited
ssh-add -l                                                -> exit 2, agent unavailable
ssh-keygen -F <Ivan-host> -f <known_hosts file>           -> exit 1, no match (both files)
Test-Path C:\ProgramData\ssh\ssh_known_hosts            -> False
ssh-keyscan -T 5 -t ed25519 <Ivan-host> | ssh-keygen -lf -
                                                         -> SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ (untrusted)
tailscale ping --timeout=8s <Ivan-host>                    -> pong from 100.88.71.74, 2 ms
strict OpenSSH command above                              -> exit 255, unknown host key
tailscale ssh <Ivan-host> whoami                           -> exit 255, unknown host key
```

No remote status, 1C environment verification, MCP read, task start, or token mint was
performed. Exact dependency: the host key must be trusted by the OpenSSH/Tailscale SSH
path. A live Tailscale peer and open TCP port are network reachability evidence only.

## WP0 result

Local listener and anonymous-denial checks: observed as above. Local business read and the Ivan
remote checks: **NOT_RUN** for the exact dependencies recorded above. This artifact does not claim
source health, business-read success, or production readiness from liveness alone.

## Local database container binding recheck — 2026-10-22

Read-only command `docker ps --filter "name=erpmcp-e2e-real1c-postgres-1" --filter
"name=erpmcp-e2e-real1c-redis-1" --format "{{.Names}} {{.Status}} {{.Ports}}"` exited 0 and
returned:

```text
erpmcp-e2e-real1c-postgres-1 Up 58 minutes (healthy) 127.0.0.1:18432->5432/tcp
erpmcp-e2e-real1c-redis-1 Up 58 minutes (healthy) 127.0.0.1:19379->6379/tcp
```

This records the observed container status and host bindings at that time only. Container
ownership/origin and later runtime state are not established by this command. No database
connection, migration, or business read was attempted.

## Local project and SSH key inventory — 2026-10-22

- A path-only inventory of tracked project files found no tracked private-key material
  file; `git grep -Il -E 'BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY|BEGIN PRIVATE KEY'`
  returned no matching tracked paths. The repository `.gitignore` excludes `.env` and
  common private-key extensions such as `.pem`, `.key`, and `.pfx`, while permitting only
  the tracked `.env.*.example` files. The conventional root `.env`, `.env.development`,
  `.env.production`, and `.env.local` paths were absent. A path-only ignored/untracked
  filename inventory found no credential-named candidates outside dependency/cache
  directories. These path-only inventories did not read file contents. SSH key files were
  parsed only by `ssh-keygen -lf` to obtain fingerprints; private bytes were not displayed
  or recorded.
- A recursive filename-only inventory of the user SSH directory found three private/public
  identity pairs and no other key files (`id_ed25519`,
  `trading_bot`, and `vmc_collector_vps`). For each pair, `ssh-keygen -lf` reported matching
  fingerprints. Private-file ACLs grant access to the current user, SYSTEM, and
  Administrators; `trading_bot` uses explicit entries and the other two use inherited
  entries. The public `trading_bot.pub` grants Everyone read access, which is public-key
  material. Key purpose and authorization to any ERP service remain **NOT_VERIFIED**;
  filenames do not establish their service association. Fingerprint values are omitted.
- This inventory does not inspect connected-app OAuth secrets, secret-provider contents,
  or live database key rows. The existing application connectors did not provide an
  authenticated ERP source response, and no secret-bearing store was opened.

These checks supplement, but do not change, the Ivan host-trust finding above: no trusted
Ivan host key was found, and the matching client identity alone does not prove server-side
authorization.
