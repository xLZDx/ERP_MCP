# Change Record 358 — stable public host for the lane IdP through Tailscale Funnel

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Operator decisions: asked to look for the earlier Cloudflare setup; then chose Tailscale Funnel over a Cloudflare
  named tunnel.
- Covers `scripts/real1c/autostart/start_lane.ps1` and the matching local lane state. No product source changed.

## Finding

- No Cloudflare account material exists on this machine: `C:\Users\koros\.cloudflared` is empty and no task or
  service uses a named tunnel. The only `cloudflared` process was the temporary quick tunnel of the lane.
- The earlier ERP_MCP setup on Ivan's host used a different mechanism: an OpenAI Secure MCP Tunnel with a fixed
  tunnel id and the IdP published through Tailscale Funnel (`ivan.tail08f9f9.ts.net`). `cloudflared.exe` there is
  only part of the OpenAI client bundle.
- A second problem was found: `D:\Repo\ERP_MCP-chatgpt` had been moved to `D:\Repo\Trash\ERP_MCP-chatgpt`, so the
  autostart step that starts the tunnel-client for the profile `erp-mcp-local` logged `tunnel-client started: False`
  (the ChatGPT connector was therefore not served).

## Change

1. `tailscale funnel --bg 21080` on this machine: `https://razer.tail08f9f9.ts.net/` now reaches the lane IdP.
2. Lane state: the issuer host in `env.ps1` and `idp-config.json` (backups `*.bak-quicktunnel`) was changed from the
   quick-tunnel host to `razer.tail08f9f9.ts.net`; IdP and gateway were restarted with the lane's own
   `scripts/e2e/fault.ps1`. The gateway resource metadata now lists the new authorization server.
3. The quick tunnel process of the lane was stopped. The Personal_DC tunnel-client (`personal-dc` profile) was not touched.
4. tunnel-client profile `erp-mcp-local` (`%APPDATA%\tunnel-client\erp-mcp-local.yaml`, backup
   `.bak-before-funnel`): `https://razer.tail08f9f9.ts.net` added to `mcp.oauth_trusted_origins`. Without it the
   client logged "destination origin is not trusted".
5. Files copied (not moved) from the Trash folder to `D:\Repo\ERP_MCP-chatgpt\.chatgpt\`: `bin\tunnel-client.exe`,
   `start-real1c-tunnel.ps1`, `tunnel.json`. The Trash folder was left as it was.
6. `start_lane.ps1`: step 5 now ensures the Funnel and aligns the issuer host with the machine's Tailscale DNS name
   instead of starting a quick tunnel; the new script was deployed to `D:\ERP_MCP_Testbed\real1c_e2e\autostart\`
   (old copy kept as `.bak-quicktunnel`).

## Verification state

- RUN: the public funnel URL answers 200 for the realm discovery document; the gateway resource metadata lists the
  funnel host; tunnel-client `erp-mcp-local` is running and its log no longer reports the untrusted-origin warning;
  one full idempotent autostart pass finished with all ports listening; `phase2_reconcile_two_bases` still returns
  the 521.1 closing comparison PARTIAL_MATCH with equal digests.
- NOT_RUN: a real ChatGPT login against the new issuer. Because the issuer changed, the connector ERP_MCP_REAL1 must
  be deleted and created again once by the operator.
- The autostart pass also restarted Apache of the lane (port 18088), which had not been listening.
- Funnel exposes the test IdP to the internet through the tailnet node name; the IdP is the existing test IdP
  (loopback service, test realm).
