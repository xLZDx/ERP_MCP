# ChatGPT ↔ ERP_MCP integration

Status: implementation branch `feature/chatgpt-mcp-integration`.

This integration exposes the existing ERP_MCP data plane to ChatGPT through OpenAI Secure MCP Tunnel.
It does **not** expose Admin Control Center mutations through the ChatGPT MCP surface.

## Architecture

```text
ChatGPT
  |
  | OpenAI-hosted MCP tunnel endpoint
  v
Secure MCP Tunnel
  |
  | outbound HTTPS from the customer machine
  v
tunnel-client
  |
  | loopback/private HTTP
  v
ERP_MCP /mcp
  |
  +-- ACL / company scope
  +-- business capability policy
  +-- semantic profile gates
  +-- rate/row/byte/time limits
  +-- audit
  |
  v
1C / OData sidecar / approved adapters
```

Admin remains separate:

```text
Browser -> /admin/ -> governed control plane
```

## Machine-readable MCP safety contract

Every public ERP_MCP tool is published with standard MCP annotations:

- `readOnlyHint = true`
- `destructiveHint = false`
- `openWorldHint = true`

The server instructions tell the client not to invent source/company identifiers, broaden scope, expose
credentials, or represent synthetic evidence as native 1C reconciliation.

No Admin mutation tool is added to the public MCP tool catalog by this integration.

## Local ChatGPT demo — synthetic Fake1C only

The local ChatGPT path is deliberately separate from the normal authenticated E2E gateway.

It uses:

- dedicated E2E compose project suffix `-chatgpt`;
- dedicated E2E port offset `5000`;
- ChatGPT-facing gateway on `127.0.0.1:18100`;
- OAuth disabled only on that extra loopback gateway;
- Admin API/UI/mutations disabled;
- fixed principal `development-local`;
- source `fake1c-e2e` only;
- source must carry the `synthetic-fixture` tag and remain read-only/enabled.

`local_prepare.py` refuses any non-test or non-synthetic environment.

### Start the local endpoint

```powershell
Set-Location D:\Repo\ERP_MCP-chatgpt
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\up.ps1
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\doctor.ps1
```

Expected MCP endpoint:

```text
http://127.0.0.1:18100/mcp
```

### Stop it

```powershell
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\down.ps1
```

Use `-DownE2E` only when the dedicated synthetic dependencies should also stop.

## Install official tunnel-client

The installer defaults to the verified official `openai/tunnel-client` release `v0.0.16` (current on
2026-10-07), downloads the matching Windows archive and `SHA256SUMS.txt`, verifies the archive
SHA-256, and stores the executable only under git-ignored `.chatgpt/bin`. Upgrade the `-Version`
parameter deliberately when a newer release is reviewed.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\install-tunnel-client.ps1
```

No tunnel-client binary is committed to this repository.

Official source of truth:

- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://github.com/openai/tunnel-client/releases/latest

## External account step: create/select the tunnel

This repository cannot create a tunnel inside an operator OpenAI account without that account authorization.

Create or select a tunnel in:

```text
https://platform.openai.com/settings/organization/tunnels
```

Required OpenAI permissions:

- create/edit tunnel: Tunnels Read + Manage;
- run/select tunnel: Tunnels Read + Use.

Create a runtime API key for `tunnel-client`. Do not put that key in Git, `.env`, this document,
or any ChatGPT message.

## Configure tunnel profile

Start the local MCP first, then:

```powershell
$env:CONTROL_PLANE_API_KEY = "<runtime key in this shell only>"
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\configure-tunnel.ps1 `
  -TunnelId "tunnel_..." `
  -Profile "erp-mcp-local"
```

If `CONTROL_PLANE_API_KEY` is absent, the script requests it using hidden PowerShell input and does
not persist it.

The generated tunnel profile uses OpenAI `sample_mcp_remote_no_auth` and forwards only to:

```text
http://127.0.0.1:18100/mcp
```

## Run the tunnel

Foreground:

```powershell
$env:CONTROL_PLANE_API_KEY = "<runtime key>"
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\start-tunnel.ps1
```

Background:

```powershell
$env:CONTROL_PLANE_API_KEY = "<runtime key>"
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\start-tunnel.ps1 -Background
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\doctor.ps1
```

Stop:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\stop-tunnel.ps1
```

## Add ERP_MCP in ChatGPT

Current OpenAI flow:

1. Open ChatGPT on web.
2. Open Plugins / Apps and choose **Add custom MCP server**.
3. Name: `ERP_MCP`.
4. Connection: **Tunnel**.
5. Select or paste the same `tunnel_id`.
6. For this synthetic local profile choose no MCP-server authentication: access is controlled by the
   OpenAI tunnel plus the fixed synthetic principal.
7. Scan tools.
8. Review that every ERP_MCP action is read-only/non-destructive.
9. Create/enable the plugin/app.
10. Keep `tunnel-client run` healthy while using the app.

Example prompts:

```text
@ERP_MCP show my available sources and companies
@ERP_MCP show sales documents in the synthetic company
@ERP_MCP show receivables aging as of 2026-04-30
@ERP_MCP find duplicate-counterparty candidates
```

## Production / real 1C path

Do **not** use the local no-OAuth profile with real or customer 1C data.

Production keeps the existing ERP_MCP security contract:

- `BAG_ENVIRONMENT=production`;
- OAuth/OIDC enabled;
- public MCP resource identifier uses HTTPS;
- real issuer/audience/JWKS;
- `onec:read` scope;
- PostgreSQL/Redis privilege split;
- non-env secret provider;
- exact 1C host allowlist and egress CIDRs;
- private HTTPS OData sidecar;
- existing source/company ACL;
- validated semantic profiles;
- audit and operational gates.

Secure MCP Tunnel can keep the MCP server private, but the browser-facing authorization server must
be reachable for the OAuth flow. The tunnel does not automatically make a private IdP public.

For production ChatGPT app configuration, select the tunnel and configure the OAuth flow backed by
the real deployment IdP. Do not use the disposable test IdP on `127.0.0.1`.

## Verification

Local:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\chatgpt\doctor.ps1
```

The black-box smoke checks:

- Streamable HTTP initialization;
- tool discovery;
- required tool presence;
- `readOnlyHint=true`;
- `destructiveHint=false`;
- `system_status`;
- `sources_list`.

Repository contract test:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_chatgpt_mcp_contract.py -q
```

## Stop conditions

Stop and investigate if any of these occur:

- ChatGPT discovers a write/mutation tool;
- Admin mutation routes become reachable through the ChatGPT-facing local gateway;
- a credential/token appears in tool output or logs;
- a non-synthetic source is accepted by the local no-OAuth setup;
- cross-company data is returned without the caller grant;
- a synthetic L1 result is presented as native 1C reconciliation;
- tunnel-client is configured with an admin key instead of a runtime key.

## Current OpenAI product note

Custom MCP/app availability and write support depend on the ChatGPT plan/workspace and administrator
permissions. ERP_MCP ChatGPT surface in this branch remains read-only, which is the intended first
deployment boundary.
