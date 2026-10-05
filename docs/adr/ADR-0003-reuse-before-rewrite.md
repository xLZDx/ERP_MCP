# ADR-0003 — Reuse-before-rewrite for 1C protocol code

**Status:** Accepted  
**Date:** 2026-10-05

## Context

Public GitHub already contains mature 1C OData/register/COM/native-query implementations and tests.
Reimplementing them increases compatibility defects and maintenance cost.

## Decision

Before adding 1C transport/register behavior, implementation must inspect the pinned upstream census
and tests.

Preferred:
1. direct pinned dependency/sidecar;
2. licensed port with provenance;
3. isolated service;
4. original implementation only for a demonstrated gap.

## Consequences

- vendor intake/license review is a CI/governance concern;
- upstream tests become compatibility oracles;
- “rewrite because it is faster” is rejected for protocol code without evidence.
