# ADR-0002 — Separate control plane from 1C data planes

**Status:** Accepted  
**Date:** 2026-10-05

## Context

1C compatibility requires heterogeneous transports (OData, extension/HTTP, COM, legacy isolation).
Identity/ACL/audit must remain consistent regardless of transport.

## Decision

ERP_MCP core is the control plane. 1C protocol implementations are data planes behind a normalized
read contract.

Control plane owns:
- identity;
- authorization;
- registry/company scope;
- secrets references;
- limits;
- routing;
- semantic orchestration;
- audit/provenance.

Data plane owns:
- source-specific read protocol behavior.

## Consequences

- mature non-Python engines can be reused without porting;
- adapter replacement does not redefine public auth/policy;
- legacy/copyleft services can remain isolated;
- Python lightweight probes may coexist without becoming a second full protocol engine.
