# RSV metadata-only adapter contract

## Scope and reuse

The adapter launches the pinned `prepod2003/mcp-rsv-data` Go stdio bridge; ERP_MCP does not
implement COM, JSON-RPC, MCP framing, or an alternate COM bridge. The approved source contract pin
is `76fed8e6e16833fee1514969841b8d9a61c7c152` (MIT). Runtime responses report that source pin
separately from the SHA-256 of the configured executable. A source commit is not binary provenance:
release-tag/source parity must not be inferred.

## Allowed upstream calls

`rsv_metadata(source_id, operation, arguments)` is available only for a registered `onec_auto`
source after source ACL and rate-limit checks. Each operation runs through a fresh pinned stdio/COM
process. The adapter requires the reviewed upstream inventory and calls exactly one of:

| Operation | Accepted arguments |
|---|---|
| `ping` | none |
| `config` | none |
| `describe` | one or more of `type`, `filter`, `find`, `subsystem`, `object`, `table` |
| `get_structure` | exactly `object` |
| `help` | optional topic from `config`, `describe`, `get_structure`, `help`, `ping`, `workflow`, `about` |

String selectors are non-empty and at most 256 characters. Responses are text-only, normalized to
`{source_id, adapter, operation, data}`, and bounded by `BAG_MAX_RESPONSE_BYTES`. The adapter stamp
includes the approved upstream source SHA and the observed executable SHA-256. Failures are
sanitized and fail closed.

`query`, `execute_query`, and `reveal` are not callable through this contract. They are rejected
before process launch and their names/arguments are not forwarded. The installed extension audit
found a persistent anonymization-token register write, privileged reveal, no immutable company
predicate, and unbounded upstream query execution cost; therefore P6 business reads remain denied.

## Credential and environment boundary

The upstream JSON configuration format stores credentials as plaintext. The current metadata tool
is therefore disabled when `BAG_ENVIRONMENT=production`; it is a local/test capability only until
the bridge obtains credentials from ERP_MCP secret references without persistent plaintext config.
Do not use customer data or production credentials in this local route. Production configuration,
when the isolated bridge is enabled, must pin `BAG_RSV_BRIDGE_EXECUTABLE_SHA256`; the digest is
verified before launching the executable. The config root must be outside Git and ACL-restricted to
the service identity. The artifact digest does not establish source/build parity.

## Evidence

`tests/test_rsv_bridge.py` and `tests/test_rsv_metadata_tool.py` cover the operation and argument
allowlists, source ACL-before-dispatch, normalized provenance, response bounds, production deny,
and sanitized failures. `tests/test_live_rsv_metadata.py` is an opt-in integration check for a
disposable synthetic base. It exercises the five metadata operations only; no business-data tool is
called. Live evidence and exact disposable artifact details are kept in the local handoff rather
than committed as customer/environment secrets.
