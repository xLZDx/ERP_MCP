# Internal ERP_MCP ↔ pinned OData sidecar contract

**Status:** Internal, read-only, version 1  
**Pinned engine:** `hacker-cb/1c-odata` / `@1c-odata/client` + metadata at
`cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5` (MIT)

This is an authenticated private-service contract, not a public MCP tool. ERP_MCP owns the source
ID, registered base URL, resolved credentials, caller policy and audit. The sidecar accepts only
registered-source addresses whose exact authority is in `ONEC_ALLOWED_HOSTS`; it never accepts a
model-selected URL.

## Register capability discovery

`POST /v1/capabilities/registers` accepts exactly:

```json
{
  "source_id": "source-1",
  "base_url": "https://onec.example.test/odata/standard.odata",
  "username": "<server-resolved>",
  "password": "<server-resolved>"
}
```

The sidecar fetches that source's `$metadata` through pinned `fetchMetadataXml` and parses it with
pinned `parseEdmx` / `groupFunctionImportsByEntitySet`. It returns the exact source ID, sidecar/upstream
provenance and a `capability_profile` containing a metadata SHA-256, discovery timestamp, enumerated
register EntitySets, applicable method availability and evidence. A virtual-table operation is
positive only if the same EntitySet has the exact FunctionImport bound in metadata with HTTP GET.
Direct `records` / `recordsets` availability is evidenced by the exact register EntitySet in
metadata. Missing, POST-only or differently bound functions are negative evidence; no name aliases
are tried.

ERP_MCP validates source ID and pinned SHA, requires the profile fingerprint to match the capability
handshake, returns it from `onec_capabilities`, and persists it in
`bag.source_capabilities.register_capabilities_json`. A profile from live metadata is one allowed
evidence source; safe probes or validated semantic profiles may be added later with their own
provenance and validation rules.

For semantic record-set reads (not virtual methods), ERP_MCP also stores exact-source negative
evidence in `bag.source_capabilities.evidence_json.semantic_capabilities`. Entries are scoped to the
source, concept, exact EntitySet and expected property set, carry the current metadata fingerprint,
and state `UNSUPPORTED` plus a bounded reason such as `ENTITY_SET_ABSENT` or `PROPERTY_ABSENT`.
Only property names are recorded; no business rows are stored. A normal capability refresh preserves
these semantic entries, while a changed metadata fingerprint makes old evidence historical/stale.
The `onec_capabilities` result exposes the persisted semantic evidence separately from the pinned
sidecar register profile.

## Register read

`POST /v1/read` uses `operation: "register_read"`, exact `register_set`, `register_method`, bounded
arguments and paging. The internal adapter checks its per-source profile first. The sidecar then
rechecks its short-lived live-metadata profile immediately before calling the pinned upstream
register API. Only upstream-backed read methods are dispatched.

If evidence is absent, stale, bound to a different source/fingerprint, or does not confirm an exact
GET function import, the sidecar returns HTTP 422 with:

```json
{"error":{"code":"CAPABILITY_UNSUPPORTED"}}
```

ERP_MCP raises the same stable code and must audit the denial. Invalid/unrecognized methods are not
used as a probing mechanism. Transport/metadata discovery failures use a distinct sanitized error
and fail closed.

## Limits and provenance

Both endpoints require the private bearer token and exact host allowlist. Request/response/metadata
bytes, row counts, timeout, per-source concurrency and circuit state are bounded. Responses include
`source_id`, adapter kind/version, exact upstream SHA and operation. Redirects are disabled in the
Python hop, and production requires TLS between gateway and sidecar.
