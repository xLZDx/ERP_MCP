# ADR-0005 — No direct integration with internal 1C SQL tables

**Status:** Accepted  
**Date:** 2026-10-05

## Context

1C may use file mode or supported DBMS backends, but its internal SQL representation is not the
stable business-object contract and can bypass platform rights/semantics.

## Decision

ERP_MCP accesses 1C through supported platform integration boundaries:
- OData;
- approved HTTP/extension;
- COM/native-query bridge;
- isolated legacy adapter.

Direct reads of internal `_Reference*`, `_Document*` or similar tables are prohibited.

## Consequences

- the same semantic layer can work across file/server deployments;
- platform security/object behavior is preserved;
- DBMS choice is deployment detail, not our business API.
