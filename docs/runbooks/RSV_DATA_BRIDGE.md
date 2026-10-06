# RSV Data bridge operations (P6)

The bridge is the pinned `prepod2003/mcp-rsv-data` upstream process. ERP_MCP does not
implement COM, 1C native queries, or MCP stdio framing. The integration verifies the reviewed
upstream tool inventory and supports the source-ACL-protected metadata-only operations `ping`,
`config`, `describe`, `get_structure`, and `help`. Each call runs in a fresh process/COM connection
and returns a bounded normalized envelope. It never proxies `query`, `execute_query`, or `reveal`.
Production requires `BAG_RSV_BRIDGE_CONFIG_SECRET_REF` in addition to executable SHA pinning. The
secret provider returns a bounded JSON config which is materialized only in a short-lived temporary
directory and removed after the bridge operation. The upstream persisted customer config is never
used as production secret management.

## Install and bind a source (Windows)

1. Install the pinned upstream `rsvdata-bridge.exe` and 1C platform on a dedicated Windows host
   with the required COM registration. Verify the release against the approved upstream release
   process before deployment; do not build or patch another bridge in ERP_MCP.
2. Run the upstream setup under the dedicated service identity only for local/test discovery. Use
   the exact ERP_MCP source ID as the connection name so the `<source-id>.json` target descriptor is
   unambiguous. Production must provide the reviewed JSON config through the configured secret
   provider; do not persist customer credentials in the upstream config directory.
3. Place per-source config files in a dedicated directory outside the repository. Restrict the
   directory and files to the service identity using Windows ACLs; do not rely on POSIX `0600`
   semantics on Windows. If production bridge operation is later approved, set
   `BAG_RSV_BRIDGE_EXECUTABLE_SHA256` to the separately approved executable digest.
4. Configure `BAG_RSV_BRIDGE_EXECUTABLE` to the absolute bridge executable path and
   `BAG_RSV_BRIDGE_CONFIG_ROOT` to the absolute config directory. They must be set together. Never
   put a connection string, password, or config contents in environment variables, source records,
   MCP arguments, logs, or audit events.
5. Restart ERP_MCP and run `rsv_metadata` only for an ACL-authorized source. The safe initial
   sequence is `ping`, `config`, `describe`, `get_structure`, `help`. The result is structural
   metadata, not a business-data capability or accounting semantic profile.

## Failure and recovery

- A missing executable/config, unsafe source ID, startup error, unexpected tool, or failed `ping`
  fails closed. Errors returned by ERP_MCP are sanitized; inspect Windows service and upstream
  stderr logs under restricted access for diagnosis.
- To recover a disconnected COM session, verify 1C availability and the service identity's
  platform/COM registration, then run the upstream `ping` and `diag`. The next metadata call starts
  a fresh process/session; no bridge process is reused across calls.
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
