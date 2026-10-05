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
