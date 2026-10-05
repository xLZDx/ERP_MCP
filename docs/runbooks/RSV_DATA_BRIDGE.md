# RSV Data bridge operations (P6)

The bridge is the pinned `prepod2003/mcp-rsv-data` upstream process. ERP_MCP does not
implement COM, 1C native queries, or MCP stdio framing. Its current integration boundary launches
the configured executable for a source-specific health handshake, verifies the known upstream
tool inventory, calls only `ping`, then exits. Process-per-check provides crash isolation and a
fresh COM connection on the next check.

## Install and bind a source (Windows)

1. Install the pinned upstream `rsvdata-bridge.exe` and 1C platform on a dedicated Windows host
   with the required COM registration. Verify the release against the approved upstream release
   process before deployment; do not build or patch another bridge in ERP_MCP.
2. Run the upstream `rsvdata-bridge.exe setup` under the dedicated service identity. Use the exact
   ERP_MCP source ID as the connection name so the resulting `<source-id>.json` is unambiguous.
   Configure a read-only 1C user and verify with the upstream `ping`/`diag` commands.
3. Place per-source config files in a dedicated directory outside the repository. The upstream
   config contains the 1C username/password as plaintext JSON. Restrict the directory and files to
   the service identity using Windows ACLs; do not rely on POSIX `0600` semantics on Windows.
4. Configure `BAG_RSV_BRIDGE_EXECUTABLE` to the absolute bridge executable path and
   `BAG_RSV_BRIDGE_CONFIG_ROOT` to the absolute config directory. They must be set together. Never
   put a connection string, password, or config contents in environment variables, source records,
   MCP arguments, logs, or audit events.
5. Restart ERP_MCP and perform the source-specific bridge health check from an administrative
   operational context. The health result is operational evidence only; it is not a business-data
   capability profile.

## Failure and recovery

- A missing executable/config, unsafe source ID, startup error, unexpected tool, or failed `ping`
  fails closed. Errors returned by ERP_MCP are sanitized; inspect Windows service and upstream
  stderr logs under restricted access for diagnosis.
- To recover a disconnected COM session, verify 1C availability and the service identity's
  platform/COM registration, then run the upstream `ping` and `diag`. The next ERP_MCP health
  attempt starts a fresh process/session; no credential or connection string is replayed by ERP_MCP.
- Rotate credentials in the upstream source config through the approved secret-handling procedure,
  restrict access, and rerun `ping`. Do not copy config contents into incident tickets.
- Disable the source route in ERP_MCP while the bridge is unhealthy. A healthy process alone does
  not authorize reads.

## Explicit P6 safety boundary / remaining gate

The upstream exposes `query` and `execute_query`, including caller-supplied native query text.
ERP_MCP does not proxy these generic tools. A successful `ping` or presence of a query tool does
not prove per-company isolation, semantic correctness, or virtual-table availability. Until a
validated source/company profile and a constrained query mapping exist, data operations must return
`CAPABILITY_UNSUPPORTED`; no guessed table names or alternate names may be tried. The bridge's
own 1C account must remain read-only as defense in depth.
