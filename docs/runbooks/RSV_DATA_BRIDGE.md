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
## Local disposable native bridge crash/reconnect proof

`python -m scripts.rsv_native_lifecycle_harness --confirm-disposable-base --output <new-private-file>`
is an opt-in Windows-only engineering drill for the already established `RSVDataAudit` disposable
base. Target and audited official v1.3.0 executable digest are fixed in the test, never taken from
model input or a customer configuration. It reuses the production client, protected ephemeral
secret config, official SDK transport and unmodified upstream bridge; no COM implementation added.
Only `ping` and metadata `config` are called. After a confirmed live ping, the exact process handle
created by the SDK in that test is killed; a dead-session call must fail sanitized. Fresh processes
must reconnect/return health and metadata, terminate, and remove their temporary config directories.
No process-name search, arbitrary PID kill, native engine kill, database mutation/query or raw
metadata artifact is used. This proves bridge crash + fresh COM connection, not native engine crash,
zero-write snapshot comparison, binary/source build parity or native accounting reconciliation.
The native test is explicit opt-in and is NOT inferred from hosted Windows unit privacy evidence.

## Scoped SDK stdout resource policy

`rsv_privacy.py` installs an idempotent thin wrapper around the locked SDK's TextReceiveStream
constructor. Activation is captured per stream from the private RSV ContextVar; simultaneous
non-RSV SDK sessions are unchanged. The upstream bridge, SDK spawning/framing/JSON parser and
teardown remain reused, not forked. Limits apply after UTF-8 decoding but BEFORE SDK JSON parsing:
5,000,000 bytes per newline-delimited wire message, 10,000,000 bytes per session and 64 frames.
These are fixed server policy, not model arguments. Existing normalized response limits still apply.

Excess closes only that SDK-owned receive pipe and raises a fixed code without untrusted stdout
or cleanup diagnostics. Closing the pipe unblocks the SDK's shielded drain; the SDK then owns
process teardown. Contract tests cover fragmented/multibyte input, exact boundary/newline reset,
session total/frame flood, cleanup failure, repeated install and concurrent unrelated sessions.
Actual disposable SDK child tests send both undelimited and valid 6 MB private responses; a parser
spy must see neither, and fresh sessions/reconfigured secrets must recover. Native metadata drill
must still pass. This SDK namespace seam is intentionally coupled to the exact lock: dependency
updates require these contract tests, never a silent unsupported fallback. No generic query/reveal
or production writes are enabled by the resource policy.
