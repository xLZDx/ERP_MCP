# Remote 1C host (Ivan): independent test environment and MCP stack (2026-10-11)

Operator request: set up a stable, real-life-style connection to a second Windows machine (the 1C host, called "Ivan"), copy the test base there, configure a 1C environment for independent testing, and install the MCP gateway so it can be reached from Claude (now) and from ChatGPT through an OpenAI tunnel (operator connects the tunnel later).

This is test infrastructure for the Release 1 gateway lane. No Release 2 code runs on it. Nothing here is production, staging, or a gate pass.

## Channel

- Tailscale (`100.88.71.74`, MagicDNS `ivan.tail08f9f9.ts.net`) plus key-only OpenSSH (`BatchMode=yes`); the existing trading-assistant project already uses the same host and account.
- The OpenSSH session is elevated; long-lived processes are therefore started by a scheduled task (`ERP_MCP_Ivan_Stack`, logon + 1 min, repeated hourly, idempotent), not from the SSH session, because child processes of an SSH session die with it.

## Layout on the host (all under `D:\1c`; no services, no PATH or registry changes except the COM registration below)

| Path | Content |
| --- | --- |
| `env\1cv8_x64\8.3.27.2342` | copy of the local per-user 1C platform; `comcntr.dll` registered with `regsvr32` (the only machine-wide change) |
| `env\bases\818HA_test_ready` | copy of the lane test base clone (main file size equals the source) |
| `env\apache24`, `env\odata\erp_mcp_ref` | Apache with the 1C web extension; OData publication on `127.0.0.1:8088` |
| `mcp\runtime` | portable Node 24, PostgreSQL 16.9, Redis 5.0.14.1 |
| `mcp\app\gateway`, `mcp\app\sidecar`, `mcp\venv` | gateway source (committed Release 1 HEAD `ea4defa`), OData sidecar, Python 3.13 venv from the hash-locked runtime requirements |
| `mcp\env` | secrets and config (ACL: current user + Administrators): gateway env, IdP config and key, redis.conf, DPAPI blob of the 1C read-only reader |
| `mcp\logs` | component logs |

Ports: PostgreSQL 18432 and Redis 19379 (loopback), Apache 8088, lane proxies 8191-8193, sidecar 21768, IdP 21080 (loopback), gateway 21000 on the Tailscale address only.

## State transfer

The lane database (source registry with secret references, capabilities, grants, profiles) was moved with `pg_dumpall --roles-only` and `pg_dump` from the local lane container and restored into the portable PostgreSQL. Dump files carry no 1C passwords (only secret reference names); role password hashes are the lane's test-lane hashes. `\restrict` meta-commands emitted by a newer pg_dump were stripped because psql 16.9 rejects them. The 1C reader password is decrypted from the lane DPAPI blob on the operator machine and re-protected with DPAPI on the host (CurrentUser); it is never written to a log or a command line.

## Verified (observed this session)

- OData `$metadata` on the host under the reader: HTTP 200, 4 618 301 bytes (same size as the local lane).
- Gateway on the host, called through Tailscale with a token minted by the host IdP: `system_status`, `sources_list`, `source_health`, `companies_list` succeed; `accounting_balance_by_analytics` returns 15 rows (`VALIDATED_MACHINE_RECONCILED`); `accounting_balance_and_turnovers`, `accounting_posting_rows`, `sales_documents`, `purchase_documents` succeed under `TEST_LANE_UNRECONCILED`; `counterparty_duplicate_candidates` succeeds after the allow-list gap was closed in both databases. `payable_balance` returns a tool error (see below).
- Claude Code registration `erp-mcp-ivan` (user scope) points at `http://100.88.71.74:21000/mcp` with a long-lived test token (token never printed).

## Not verified / known limits

- The same nine tools work on the local lane after it was restarted with the new profile settings (`env.ps1` of the lane gained three variables; backup kept in the session scratchpad).
- Not supported by this base's live metadata (no register exists, so no honest mapping): `payable_balance`, `receivable_balance`, `bank_balance`, `cash_movements`, `inventory_balance`, `inventory_movements`, aging tools. Supplier balances on account 521.1 are served by `accounting_balance_by_analytics`.
- The `TEST_LANE_UNRECONCILED` responses are labelled `native_reconciliation=NOT_RUN`; they are not accountant-reconciled evidence and do not move any gate.
- Not done: the ChatGPT tunnel. It needs a new OpenAI tunnel id and runtime API key from the operator, the tunnel audience in `BAG_OAUTH_ADDITIONAL_AUDIENCES`, and a public HTTPS IdP issuer. Tailscale HTTPS certificates/Funnel are not enabled on the tailnet (`CertDomains` is empty), so a stable public issuer needs either that setting or a named Cloudflare tunnel on an operator domain.
- The long-lived Claude token is bound to the issuer string `http://100.88.71.74:21080/...`; changing the issuer invalidates it (re-run `scripts/remote/mint-token.ps1`).
