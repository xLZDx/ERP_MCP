# ADR-0006 — Copyleft/unknown-license adapters are isolated or reference-only

**Status:** Accepted  
**Date:** 2026-10-05

## Context

Useful legacy 1C adapters exist under GPL/AGPL/LGPL or without a verified license.

## Decision

Default policy:
- GPL/AGPL source is not copied/linked into ERP_MCP core;
- LGPL is reference-only unless distribution/linking review explicitly approves another mode;
- unlicensed source is reference-only;
- a business-critical GPL adapter may run as a separately deployed service behind a narrow protocol
  boundary, subject to license compliance.

## Consequences

- 8.2 support can use an isolated legacy service without contaminating core code;
- vendor intake manifest/CI enforces reuse mode;
- license status must be rechecked on upstream updates.
