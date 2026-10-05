# Adapter intake plan — reuse, do not rewrite

Status: ACTIVE  
Date: 2026-10-05

This plan turns the GitHub adapter census into concrete implementation work.

## Architectural decision

ERP_MCP owns **identity, policy, source routing, audit and semantic tools**.

It must not become a second full implementation of the 1C OData protocol. Mature upstream
implementations already cover the difficult protocol/register behavior.

### Production route

```text
MCP client
   |
ERP_MCP control plane
   |
   +-- modern OData ----------> read-only OData engine
   |                            based on @1c-odata/client behavior
   |
   +-- 8.3 extension/COM -----> RSV Data bridge / compatible adapter
   |
   +-- 8.2.13+ --------------> isolated legacy bridge service
   |                            (GPL boundary; no code copied)
   |
   +-- 7.7 -------------------> optional isolated legacy bridge
                                only after license/need decision
```

The existing Python OData client remains useful for lightweight capability probing and test
fixtures. It is **not** the target place to independently re-create the entire upstream protocol.

## Intake A — OData v3 protocol

Upstream: `hacker-cb/1c-odata`  
Pinned: `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`  
License: MIT.

### Reuse first

| Upstream path | Why |
|---|---|
| `packages/client/src/register.ts` | Balance, Turnovers, BalanceAndTurnovers, SliceFirst/Last, DrCrTurnovers, ExtDimensions, RecordsWithExtDimensions |
| `packages/client/src/query/builder.ts` | validated top/skip/select/expand/order state |
| `packages/client/src/query/filter-internal.ts` | typed and escaped OData filter compiler |
| `packages/client/src/functions.ts` | virtual-table/function-import URL construction |
| `packages/client/src/parser.ts` | OData v3 collection/value conversion |
| `packages/client/src/connection.ts` | connection/data-shape contract |
| `packages/metadata/src/parser/` | EDMX parsing |
| `packages/metadata/src/index-builder.ts` | metadata index/classification |
| `packages/metadata/src/fetch.ts` | live metadata validation/fetch |
| `packages/metadata/src/dynamic-client.ts` | dynamic-any-base workflow |

### Tests to treat as compatibility oracle

- `packages/client/test/unit/register.test.ts`
- `packages/client/test/unit/functions.test.ts`
- `packages/client/test/unit/filter.test.ts`
- `packages/client/test/unit/filter/`
- `packages/client/test/unit/builder.test.ts`
- `packages/client/test/unit/builder-validation.test.ts`
- `packages/client/test/integration/live/register.test.ts`
- metadata parser/index parity tests.

### Rule

Do not manually add a register virtual table or OData literal rule until the corresponding upstream
implementation/test has been checked.

### Mandatory source capability rule

An operation existing in `@1c-odata/client` is not evidence that a concrete 1C base publishes or
supports it. Configuration/platform-sensitive virtual tables (including `DrCrTurnovers`) are
available only when confirmed for the exact source by live metadata, a safe capability probe, or a
validated semantic/configuration profile. Never guess the function-import name or try alternate
names. Without positive source evidence, return `CAPABILITY_UNSUPPORTED` and record the positive or
negative evidence, source ID, metadata fingerprint and discovery time in that source's capability
profile. The sidecar rechecks the exact GET binding before dispatch as a second fail-closed gate.

## Intake B — accounting semantics

Upstream: `theYahia/WWmcp/servers/aprovodka`  
Pinned: `7b62c90e1fe74324605dc28d76f195200bb97252`  
License: MIT.

Priority files:

- `src/tools/accounting.ts`
- `src/tools/registers.ts`
- `src/tools/metadata.ts`
- `src/tools/odata-query.ts`
- `src/client.ts`
- `src/validation.ts`
- `src/presets/common.ts`
- `src/presets/bp30.ts`
- `src/presets/ut11.ts`
- `src/presets/zup31.ts`
- `src/presets/erp2.ts`.

Use read-side logic only. Ignore/remove write tools.

Important upstream safety lesson: do not guess unconfirmed virtual-table names. Capabilities must be
confirmed from the actual base metadata/behavior.

## Intake C — local/unpublished 8.3 and query fallback

Upstream: `prepod2003/mcp-rsv-data`  
Pinned: `76fed8e6e16833fee1514969841b8d9a61c7c152`  
License: MIT.

Important files:

- `bridge/onec.go` — V83.COMConnector, dedicated COM thread, persistent connection;
- `bridge/serve.go` — stdin/stdout MCP JSON-RPC framing;
- `bridge/config.go` — file/server 1C connection-string handling;
- `bridge/diag.go` — diagnostics;
- `bridge/setup.go` — installation/setup lifecycle;
- extension dispatcher and query handlers from the upstream release/source.

### Key consequence

The COM bridge already forwards MCP JSON-RPC to
`RSVData_Сервер.ОбработатьСообщение`. ERP_MCP should integrate the bridge as an isolated adapter
process/service rather than reproduce COM automation in Python.

## Intake D — 8.2.13+

Upstream: `ROCTUP/1c-mcp-toolkit`  
Pinned: `fe12903af7a367a9d67dd055c13f4b59bb59d83c`  
License: GPL-3.0.

The project explicitly advertises 8.2.13+ compatibility and contains old-platform JSON
compatibility code.

### License boundary

- no source copied into ERP_MCP;
- no linking into the ERP_MCP package;
- if needed, deploy as an isolated service/process;
- ERP_MCP talks to a narrow read-only protocol boundary;
- security policy still lives in ERP_MCP.

This gives old-platform support without GPL contamination of the core.

## Intake E — 7.7

Upstream evidence: `umanets/1c77-rest-api` @
`6bad0859b35128cd706355211d23581edbba53aa`.

It demonstrates 32-bit Windows COM → REST for 1C 7.7, but no verified license is present.

Decision: reference-only. Do nothing until a real 7.7 customer exists.

## What we still write ourselves

Only the parts that are unique to this product:

1. adapter routing and capability policy;
2. normalized read-only internal contract;
3. OAuth/ACL/secrets/audit;
4. per-company policy;
5. semantic accounting API independent of transport;
6. reconciliation/evidence against the actual customer's reports;
7. ERP/Ferma adapters.

### Current implementation evidence (2026-10-05)

The repository now contains an isolated Node sidecar built from the exact pinned MIT
`hacker-cb/1c-odata` submodule. Its wrapper exposes bounded read-only entity query, keyed entity get,
count, and type/method-allowlisted register reads through the upstream API. It validates exact
host:port allowlists and an internal bearer token, caps request/response bytes, rows, concurrency and
time, and returns source/upstream provenance. Register operations are gated against live
per-EntitySet GET FunctionImports parsed by the pinned metadata package; absent or unconfirmed
methods fail closed before a data request. Python routes detected JSON OData calls to it when paired
credentials are configured and verifies the returned source id and exact upstream SHA; Atom and
anonymous OData retain the existing GET-only Python transport. The accounting-upstream audit removed
unconfirmed Dr/Cr turnover names and requires bounded, explicitly zoned periods. Sidecar tests
(9/9), pinned client tests (428/1 skipped), metadata tests (53/53), and image smoke checks pass
locally; hosted CI, Aprovodka preset semantics, image/dependency
security evidence, deployment wiring, and real-source compatibility remain open. This is partial P3,
not a production-ready adapter release.

## Definition of “reuse checked”

A new 1C adapter feature may be implemented only after its PR states:

- upstreams searched;
- chosen upstream path/test or “no implementation found”;
- license decision;
- why reuse is direct, ported, isolated, or impossible;
- regression test added.

No “rewrite because it is faster” exception for protocol code.
