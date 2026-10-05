# ADR-0004 — Behavior-first capability routing

**Status:** Accepted  
**Date:** 2026-10-05

## Context

1C platform/configuration version names do not guarantee that OData or a specific virtual table is
published/usable in a particular base.

## Decision

Route adapters from observed capability evidence:
- metadata/service behavior;
- read format;
- register/function availability;
- approved fallback configuration;
- adapter health.

Platform/configuration version is a hint/evidence field, not the routing authority.

## Consequences

- new source onboarding includes a capability handshake;
- drift is fingerprinted;
- unsupported operations fail explicitly;
- semantic profiles can be invalidated/revalidated after incompatible drift.
