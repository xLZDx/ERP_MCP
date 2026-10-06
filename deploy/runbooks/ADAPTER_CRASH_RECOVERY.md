# Adapter crash recovery

The gateway must fail closed on adapter crash, timeout, malformed envelope, or unexpected tool
contract. Return a sanitized error and append a bounded audit event. Restart/reconnect is allowed
only after the process health handshake and executable digest check pass. Query, write, reveal, and
speculative fallback calls are forbidden during recovery.
