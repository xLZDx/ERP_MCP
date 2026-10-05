# 1C compatibility and capability negotiation

ERP_MCP does not assume that every 1C installation has the same platform version,
configuration or OData feature set.

## Principle

Compatibility is detected from **behavior first**, version second.

For every source the gateway can probe:

1. `$metadata` availability;
2. live EntitySets and fields;
3. JSON read support;
4. Atom/XML read support;
5. `$expand` support when a navigation property is available;
6. configured read-only fallback bridge.

The result is persisted as a capability profile with a metadata SHA-256 fingerprint.

When a refreshed metadata fingerprint changes, the gateway preserves the prior fingerprint and
marks the source `DRIFTED`. This state is sticky across identical probes so an operator cannot miss
the change; a later metadata change invalidates any acknowledgement. `onec_capabilities` reports
the drift state. `onec_read` fails closed until the current fingerprint is explicitly acknowledged.
Capability/read audit records use `METADATA_DRIFTED` while the drift is active.
Acknowledgement is an explicit administrative action bound to the observed fingerprint:

```bash
python scripts/admin.py capability-ack-drift \
  --source-id company-001 \
  --expected-fingerprint <current-sha256>
```

An outdated fingerprint is rejected. Acknowledging a fingerprint records operator acceptance; it
does not imply that business semantics or accounting results have been reconciled.

## Adapter profiles

| Profile | Meaning |
|---|---|
| `ODATA_JSON_V3` | Preferred profile for modern 1C OData endpoints |
| `ODATA_ATOM_V3` | Compatibility profile for older OData endpoints without JSON |
| `HTTP_QUERY_FALLBACK` | Explicitly configured read-only bridge when standard OData is insufficient/unavailable |
| `UNSUPPORTED` | No safe compatible transport detected |

The public status is one of `SUPPORTED`, `SUPPORTED_WITH_FALLBACK`, or
`UNSUPPORTED`.

## Platform versions

The initial target is the 1C 8.3 family. A configured `platform_version_hint` is recorded as
evidence, but the gateway does not select a transport merely because a version number says a
feature *should* exist.

8.2 and older installations require a separate fallback bridge and are not silently treated as
OData-compatible.

## Configuration versions

Configuration names/versions (БП, УТ, ERP, ЗУП, КА, industry/custom builds) do not determine the
low-level transport. The live metadata determines available objects.

Business semantics are a separate layer and must be reconciled against the actual configuration:
accounts, registers, dimensions, VAT logic, extensions and custom objects are not assumed globally.
