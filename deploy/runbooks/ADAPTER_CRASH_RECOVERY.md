# Adapter crash recovery

The gateway must fail closed on adapter crash, timeout, malformed envelope, or unexpected tool
contract. Return a sanitized error and append a bounded audit event. Restart/reconnect is allowed
only after the process health handshake and executable digest check pass. Query, write, reveal, and
speculative fallback calls are forbidden during recovery.

Local contract evidence: `python scripts/rsv_process_harness.py` launches official SDK MCP
stdio fixture processes through the production RSVDataBridgeClient. It checks an actual ping
crash, tool deadline and malformed response, then a new session with freshly resolved configuration.
Temporary secret config paths must disappear on both failure and recovery. This proves neither
native COM/1C restart nor deployment audit-event persistence; those retain separate gates.

Secret-backed RSV configs are materialized only in a new empty protected task directory.
Windows uses a protected DACL for the runtime identity, SYSTEM and Administrators, verified by
read-back; new config files inherit that restricted ACL and are exclusive-created. POSIX requires
runtime ownership/0700 directory and 0600 file creation. Failure prevents launching the bridge.
Raw subprocess stderr is discarded; SDK diagnostics inside the RSV operation are reduced to a
fixed code with no payload, exception details, paths or structured extras. Concurrent non-RSV
logging remains unchanged. Investigate using bounded error/audit codes, never publish raw config.
Implementation API reference: [SetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow).
