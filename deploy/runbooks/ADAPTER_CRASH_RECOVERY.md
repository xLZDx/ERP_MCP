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
