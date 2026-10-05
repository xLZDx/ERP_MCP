# ADR-0001 — 1C MVP is read-only by construction

**Status:** Accepted  
**Date:** 2026-10-05

## Context

Upstream 1C projects often include document creation/update/posting. The first ERP_MCP production
requirement is analytical/read access across many companies. A model-visible mutation path creates
material accounting and security risk.

## Decision

The 1C production MVP exposes no mutation operation.

This applies to:
- public MCP tools;
- internal adapter contract;
- OData wrappers;
- extension/COM/native-query fallback.

Read-only is enforced structurally, not only by a configuration flag.

## Consequences

- write-capable upstreams require a read-only wrapper/allowlist;
- negative mutation tests are mandatory;
- future write support, if ever requested, requires a new ADR/product/security design and is not an
  incremental toggle.
