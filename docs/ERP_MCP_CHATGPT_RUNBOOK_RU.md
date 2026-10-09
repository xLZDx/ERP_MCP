# ERP_MCP ↔ ChatGPT — Secure Tunnel Runbook

**Historical checkpoint:** Updated October 7, 2026. The endpoint IDs and local topology below describe a configuration at that date; they are **not proof of the current live deployment**. Always re-check the actual connection, identity and authorization before operational use.

## 1. Recorded Local Topology

| Item | Historical value |
| --- | --- |
| Repository | \`D:\Repo\ERP_MCP-chatgpt\` |
| Git branch | \`feature/chatgpt-mcp-integration\` |
| OpenAI tunnel | \`tunnel_6ac64553de90819188eaf83bc540eb7a\` |
| Tunnel profile | \`erp-mcp-local\` |
| MCP target in \`.chatgpt\tunnel.json\` | \`http://127.0.0.1:21000/mcp\` |

**Stale evidence warning:** \`.chatgpt\tunnel-health.json\` contained a health snapshot for an **older endpoint, \`18100/mcp\`**. It cannot confirm availability of \`21000/mcp\`. Validate the target independently on the current exact configuration.

Use DC_MCP as a separate workstation/repository administration channel, **not** as a required proxy for normal ERP business queries.

Intended read-only data path:

\`\`\`text
ChatGPT -> OpenAI Secure MCP Tunnel -> tunnel-client -> ERP_MCP -> authorized 1C
\`\`\`

## 2. Minimum Infrastructure Requirements

ERP_MCP does **not** need to run on the same physical server as 1C.

1. The \`tunnel-client\` host needs authorized connectivity to ERP_MCP.
2. ERP_MCP needs separately authorized read access to the 1C source.
3. The Secure MCP Tunnel connects ChatGPT to the private network path.
4. Neither 1C nor ERP_MCP needs to be directly exposed to the public internet.
5. Production financial data must remain protected by OAuth, source ACL and company ACL.
6. The ChatGPT MCP business-data tool surface must be read-only.

## 3. Deployment Topologies

### Option A — Single Windows Host

Components on one host: 1C, ERP_MCP and \`tunnel-client\`.

\`\`\`text
ChatGPT -> Secure MCP Tunnel -> tunnel-client -> localhost ERP_MCP -> 1C
\`\`\`

**Advantages:** Minimal topology and firewall rules; straightforward diagnostics.

**Trade-offs:** Greater component coupling and shared upgrade/load impact.

### Option B — Two Servers (Preferred Design)

**Server A:** 1C.  
**Server B:** ERP_MCP plus \`tunnel-client\`.

\`\`\`text
ChatGPT -> Secure MCP Tunnel -> Server B: tunnel-client
        -> ERP_MCP -> private LAN -> Server A: 1C
\`\`\`

**Advantages:** Cleaner security boundary; ERP_MCP can be upgraded independently; 1C stays private; the tunnel client is close to the MCP endpoint.

This was the preferred architecture for the original deployment design, **not a claim that it has already been installed**.

### Option C — Three Separate Servers

**Server A:** 1C.  
**Server B:** ERP_MCP.  
**Server C:** \`tunnel-client\`.

\`\`\`text
ChatGPT -> Secure MCP Tunnel -> Server C
        -> private MCP -> Server B
        -> private 1C -> Server A
\`\`\`

Use only when infrastructure policies require a separate edge/connector host. The extra network, DNS, firewall and TLS boundaries increase failure and diagnostic complexity.

## 4. OpenAI Tunnel Prerequisites

A Secure MCP Tunnel requires:
- A valid \`tunnel_id\` and securely provisioned runtime API key.
- The required Tunnels Read and Use permissions for runtime/operator identities.
- A tunnel bound to the intended ChatGPT workspace.
- Outbound HTTPS connectivity from \`tunnel-client\` to OpenAI.
- Network reachability from \`tunnel-client\` to the authorized private MCP endpoint.

Creating or editing the tunnel separately requires Tunnels Read and Manage permissions.

Historical reference links (verify current platform UI and availability):
- [Tunnels](https://platform.openai.com/settings/organization/tunnels)
- [API Keys](https://platform.openai.com/settings/organization/api-keys)
- [Roles](https://platform.openai.com/settings/organization/people/roles)
- [Secure MCP Tunnel Documentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Custom MCP Server](https://developers.openai.com/api/docs/guides/custom-mcp-server)

## 5. OAuth for Real 1C

The Secure MCP Tunnel protects a private transport path. **It does not replace ERP_MCP authorization.**

\`\`\`text
ChatGPT -> Tunnel -> ERP_MCP -> validated OAuth identity
        -> source ACL -> company ACL -> 1C
\`\`\`

OAuth discovery may traverse the tunnel, but the browser-facing authorization server does **not** automatically become publicly accessible merely because the MCP endpoint is tunneled.

Where ERP_MCP uses OAuth:
- The authorization server must be reachable by the participant in the browser authorization flow.
- Alternatively, use a qualified, browser-accessible OAuth identity provider.
- **Never disable OAuth on a production financial endpoint as a convenience workaround.**

## 6. Read-Only MCP Surface

ChatGPT should access only the approved, scope-validated read-only operations. Historical catalog examples:

\`\`\`text
sources_list
companies_list
source_health
onec_capabilities
onec_metadata_summary
onec_find_entities
onec_read
accounting_balance_and_turnovers
accounting_posting_rows
payable_balance
receivable_balance
payable_aging
receivable_aging
inventory_balance
inventory_movements
bank_balance
cash_movements
sales_documents
purchase_documents
\`\`\`

The presence of a tool name does **not** prove authorization or that a real company's semantic profile is validated. Unqualified financial operations must remain denied.

The Admin Control Center must remain separate from the public ChatGPT data plane.

## 7. Acceptance Checklist

Before declaring integration usable, verify all of the following on a pinned current configuration:

1. ERP_MCP \`GET /healthz\` returns HTTP 200.
2. ERP_MCP \`GET /readyz\` returns HTTP 200.
3. MCP \`initialize\` succeeds.
4. \`tools/list\` contains the expected read-only catalog.
5. \`sources_list\` includes the intended **real** 1C source rather than only synthetic fixtures.
6. \`companies_list\` includes **only** currently authorized organizations.
7. A permitted accounting read returns genuine scoped data under a qualified semantic profile.
8. Tunnel \`/healthz\` is healthy.
9. Tunnel \`/readyz\` is ready.
10. The ChatGPT custom MCP connection points to the approved tunnel.
11. The intended \`@ERP_MCP\` tool connection is available in ChatGPT.
12. The test request appears in the ERP_MCP audit log.
13. Write and delete operations are absent from the public tool catalog.
14. Real 1C credentials are not sent to ChatGPT or stored in tunnel profiles.

**HTTP health or availability alone does not establish accurate accounting values, a native report attestation, or production release approval.**

## 8. Separate Business and Administration Paths

**Business data:**
\`\`\`text
ChatGPT -> OpenAI Secure MCP Tunnel -> tunnel-client
        -> ERP_MCP -> authorized private 1C source
\`\`\`

**Workstation operations:**
\`\`\`text
ChatGPT -> approved DC_MCP or successor tools
        -> Windows, Git, local files, diagnostics and maintenance
\`\`\`

Keep these channels separate, with their own permissions, audit and revocation boundaries.

## 9. Historically Pending Verification

The October 7 tunnel profile pointed to \`http://127.0.0.1:21000/mcp\`. The following were open checks:

- Verify that endpoint is truly the intended real-1C ERP_MCP gateway.
- Confirm its actual OAuth/ACL mode, not a synthetic no-OAuth development configuration.
- Confirm \`sources_list\` returns the authorized real source.
- Confirm ChatGPT's MCP connection uses the intended approved tunnel rather than a stale profile.
- Only after these pass, test a scoped accounting question such as: **"How much is owed to suppliers on account 521.1 as of August 31, 2026?"**

That financial answer additionally requires a verified source-specific accounting profile and independent native evidence. **This historical checklist must not be treated as a currently passing test run.**
