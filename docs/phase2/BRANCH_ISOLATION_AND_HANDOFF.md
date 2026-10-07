# Phase 2 isolated branch: handoff and precise status

## Source of truth

Branch: phase2/living-model-connectors-reconciliation
Based on GitHub main commit 94f4cee5842776d0b8810cf3f38e2682a701002a. A Git branch includes the entire committed repository tree; it does NOT include staged or unstaged changes in another worktree.
Do not merge R2 into main/Release 1 or run Phase 2 migrations against R1.
Do not edit Phase 1 worktree, running gateway, 1C source, tunnel, IdP, PostgreSQL or services as part of this setup.

## Windows separate clone

A non-destructive clone helper is at scripts/phase2/bootstrap-local.ps1 in this branch and D:\Repo\ERP_MCP_PHASE2_SETUP.ps1 on the operator workstation.
Desired isolated checkout: D:\Repo\ERP_MCP-phase2.
An already existing destination is checked; no deletion, reset, force-push or overwrite is allowed.

**Current execution limitation:** the connected DC_MCP exposes file access and selected Git operations but NOT arbitrary git clone/PowerShell process execution. Remote Phase 2 branch was created and populated through the GitHub connector. The Windows isolated clone must be executed with the supplied helper in a PowerShell session; do not claim it exists until checked.

From Windows PowerShell:
    & 'D:\Repo\ERP_MCP_PHASE2_SETUP.ps1'

The full original 38-file ZIP exists as an attachment to the ChatGPT conversation, NOT on the Windows workstation or in this Git branch yet. The separate setup script accepts a locally downloaded, SHA-256-verified copy:
    & 'D:\Repo\ERP_MCP_PHASE2_SETUP.ps1' -BundleZip 'D:\Downloads\ERP_MCP_PHASE2_SPEC_v0.1_2026-10-08.zip' -PublishBundle

Expected SHA-256: e1ab5e1d8e96307a57536c82ce132a7591b41b2e3adf71e8b7c1e7adc2703963.
The script refuses inconsistent archive bytes and existing destinations.

## Implemented on the isolated branch (S1 candidate only)

- src/business_ai_gateway/phase2/structural_hash.py: pure bounded, defensive EDMX OBSERVED fingerprinting, raw and normalized structural digests, per-object digests. No R1 import / no runtime hook / no DB migration / no approved model promotion.
- tests/phase2/test_structural_hash.py: 10 focused unit checks for formatting stability, meaningful property changes and malformed XML.
- Existing Phase 2 TDD, S0-S10 plan, stories, tests and native report protocol under docs/phase2/.
- Product acceptance scenarios remain NOT_RUN. Passing 10 isolated unit checks is not acceptance of real 1C metadata or production connectivity.

## Next implementation tasks, in order

1. S0 governance/ADR and exact-base donor/license/security inventory; decide R1 gate separation.
2. Run these Phase 2 tests on isolated checkout and fix any environment-specific issues, without touching R1:
   PYTHONPATH=src python -m pytest -q tests/phase2/test_structural_hash.py
3. Expand canonicalizer to real OData v3 fixtures with structural parity and proper exact namespace coverage. Store only OBSERVED, not accepted.
4. Add append-only bitemporal registry in new additive migration behind disabled feature flag; real Postgres roles/FK/RLS/transaction tests.
5. Add impact dependency graph and staged acceptance after explicit governance authorization.
6. Qualify one real 1C native report from an approved disposable copy; no production write probes or arbitrary COM.
7. Add 1C/Drive connectors and reconciliation workflow with independent accounting evidence; run separately scoped load and security tests.

## Explicitly still pending

- Independent Windows clone (helper prepared, not executed).
- Exact original ZIP copied into Windows and committed in branch (requires obtaining the conversation attachment on the Windows machine).
- Real Phase 2 product tests, real native evidence, deployment, operations and production qualification.
- No Phase 2 changes have been merged into main.
