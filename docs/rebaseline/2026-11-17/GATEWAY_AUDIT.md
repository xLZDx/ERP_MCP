# Gateway source audit — 2026-11-17

## Scope and method

Static inspection of the dirty checkout at `240070b029ac020e895e9f84eb4bd02dd36b2e03`,
compared with `origin/main` at `7c1f69cf51b16d3849772fdb1e32015b17cb1aa7`.
This review focused on the public gateway, authentication/principal construction, source
and company ACL resolution, semantic evidence gating, admin mutation flow, and the newly
added capability observer/acceptor path. No tests, checks, builds, SQL execution, service
startup, or 1C/runtime operations were performed.

## Findings

### G-01 — MAJOR availability: concurrent capability refreshes can invalidate each other

The new migration keeps only one observation row per source (`db/migrations/016_capability_observation_writer_acceptor.sql:24-27`).
`record_capability_observation` obtains a per-source advisory lock at lines 129-130,
reuses an observation only for the same request ID at lines 138-145, and otherwise deletes
the existing source observation before inserting the new one at lines 151-172. That lock
ends with the writer database call. The observer then calls the separate acceptor over HTTP
at `src/business_ai_gateway/capability_observer_service.py:228-260`; `accept_capability_observation`
requires the exact source/request/observation tuple at migration lines 202-209.

This permits the interleaving A-record, B-record (deleting A), A-accept. A then fails with
missing/stale provenance. It is reachable on normal concurrent requests: the public server
refreshes capabilities before many read tools, for example `src/business_ai_gateway/server.py:194-201`
and `:734-739`. The flow fails closed, but a concurrent ordinary read can fail despite a
successful probe and another request may accept the replacement observation.

Required change: retain pending observations by source plus request/observation identity,
or provide a reservation/lease that spans recording through acceptance. Add a named
concurrency test when test execution is permitted. Severity reflects availability, not
unauthorized acceptance.

### G-02 — MAJOR deployment gap: production capability service composition is not established

The working tree contains new untracked source files for the observer and acceptor and an
untracked migration 016; their existence is not evidence that production runs them.
The Dockerfile command starts only `business_ai_gateway.app:app` (`Dockerfile:23`), and
`scripts/remote/run-mcp-stack.ps1:127` likewise starts only the gateway. The inspected
launches for the observer and acceptor are in the disposable E2E harness
(`scripts/e2e/_common.ps1:311-327`). The production example has writer/acceptor database
DSNs at `.env.production.example:32-33`, but no gateway observer URL/token or observer-to-
acceptor service URL/API tokens. Meanwhile `src/business_ai_gateway/runtime.py:38-49`
requires the observer URL/token in production, and `:181-185` makes readiness depend on
that service. Therefore production startup and deployment of this new boundary are
**NOT ESTABLISHED** by the inspected configuration; do not claim the capability service
is deployed or operational.

Required change: define separate production process/container compositions and per-process
secret injection for gateway, observer, and acceptor, then qualify the deployed topology.
This audit did not inspect an external deployment platform or its live process inventory.

## Confirmed fail-closed behavior and deliberate limitations

- `src/business_ai_gateway/company_scope.py:41-57` forces the native company-scope mapping
  query to return no mapping (`AND FALSE`). This prevents unverified native evidence from
  authorizing company filters, but it also means company-scope-backed semantic reads remain
  unavailable until a trusted verifier path is implemented. This is a deliberate fail-closed
  restriction, not an authorization bypass.
- `src/business_ai_gateway/semantic.py:272-307` rejects native report evidence unless the
  separate machine-validation path is explicitly selected. This is consistent with the
  missing native authenticity verifier, but does not establish functional availability of
  native semantic profiles.
- The observer accepts only a registered `source_id`; it does not accept caller-supplied
  endpoint/capability data (`capability_observer_service.py:43-48,144-216`). In OAuth mode it
  verifies the bearer token and resolves source access before probing (`:162-216`). The
  acceptor accepts only bounded identifiers and uses the database acceptance function
  (`capability_acceptor_service.py:27-33,61-85,101-140`). The migration separates writer,
  acceptor, and runtime read authorities (`016_capability_observation_writer_acceptor.sql:71-76,369-415`).
- The read-only MCP entrypoint exposes status/source/company/capability and business-read
  tools in `src/business_ai_gateway/server.py:307-2407`, all registered with read-only
  annotations. The administrative API is separately gated by `admin_api_enabled` and
  registers read and mutation routes in `src/business_ai_gateway/admin_api.py:1731-1825`.
  This source inspection does not prove effective grants, deployed flags, or runtime access.

## Inherited risk (not introduced by this dirty diff)

`AdminMutationService._execute` opens an outer database transaction at
`src/business_ai_gateway/admin_mutations.py:257-282`; `refresh_capabilities` invokes its
callback inside that transaction at `:384-392`. The admin refresh callback performs the
observer HTTP request at `src/business_ai_gateway/admin_api.py:1234-1247`. This holds the
transaction/connection and idempotency reservation across network work, so a slow observer
can increase contention. This structure predates the current dirty change: at origin/main,
the callback already performed the adapter probe and database capability write inside the
same mutation callback. It is therefore an inherited operational risk, not a regression
attributed to the observer refactor. The observer client has a configured HTTP timeout
(`runtime.py:45-47`, `capability_client.py:45-53`); no runtime contention or pool exhaustion
was measured.

## API and composition map

| Boundary | Entry point | Responsibility | Evidence limit |
|---|---|---|---|
| Public MCP gateway | `business_ai_gateway.app:app` → `app.py:15-18,66-75` | Composes runtime and read-only MCP tools | Static source only |
| Principal and source ACL | `principal.py:18-62`; `registry.py:133-172,174-255` | Turns verified request context into principal and enforces source/company grants | No live IdP, DB grants, or runtime requests checked |
| Capability observer client | `capability_client.py:14-111`; invoked from `server.py:194-201` | Sends source ID plus bearer to independent observer and validates response identity | Client source is present; production service not established |
| Capability observer | `capability_observer_service.py:65-278,333-361` | Verifies user/service identity, resolves registered source, probes 1C, records observation, asks acceptor to commit it | No deployed process evidence |
| Capability acceptor | `capability_acceptor_service.py:39-85,133-161` | Accepts an observation by opaque identity using the acceptor DB role | No deployed process evidence |
| Admin API | `admin_api.py:1731-1825` | Optional control-plane routes; capability refresh uses the observer | Effective production feature flags/roles not checked |
| COM integration | `settings.py:81-85`; phase-2 composition is separately audited in `ARCHITECTURE_AUDIT.md` | Optional adapter/bridge settings | Does not prove an operational write path or 1C deployment |

## Review boundary

No additional confirmed authorization bypass was found in the inspected principal, source,
company, observer, and acceptor paths. This is not a whole-repository security, database,
deployment, or accounting-correctness certification. Effective PostgreSQL grants, OAuth/IdP
configuration, service-to-service secret custody, live process topology, network controls,
and concurrent runtime behavior remain unverified. The current dirty branch contains
substantial unrelated work; this report makes no merge/readiness claim.
