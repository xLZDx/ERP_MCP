# Phase 2 — Isolation and Windows checkout handoff (2026-10-08)

## Verified completed

- GitHub: `xLZDx/ERP_MCP`, branch `phase2/living-model-connectors-reconciliation`.
- Branch original base: main `94f4cee5842776d0b8810cf3f38e2682a701002a`.
- Separate Windows checkout **created using Remote Desktop Commander**: `D:\Repo\ERP_MCP-phase2`.
- The new checkout uses its OWN `.venv` built from `uv.lock`. The prior R1 worktree `D:\Repo\ERP_MCP-integration-candidate` was not switched, reset, stashed, committed, or used to run Phase 2 tests.
- Phase 2 documentation, OBSERVED-only EDMX structural hash candidate, test suite, catalogues and rebuilt archive are committed and pushed in the Phase 2 branch.
- Branch archive: `docs/phase2/artifacts/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08.zip`.
- Archive SHA-256 is computed by the deterministic builder and verified with `Get-FileHash`; the hash is intentionally not embedded here to avoid a circular package checksum.
- Generator: `scripts/phase2/build_spec_bundle.py`. Generated directory: `docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/`.
- Windows tests: **23 PASS** for Phase 2 isolated code/specifications; Ruff lint **PASS**. These are NOT live ERP/1C acceptance.
- Current pushed change: `719ee83` followed by this documentation status update.

## Important difference between archives

The exact ORIGINAL ZIP attached to the earlier ChatGPT conversation contains 38 files, 180452 bytes and SHA-256
`e1ab5e1d8e96307a57536c82ce132a7591b41b2e3adf71e8b7c1e7adc2703963`.
That exact binary was *not* transferred to the Windows workstation. Desktop Commander provides no direct binary transfer from the ChatGPT sandbox. Never claim the rebuilt ZIP is byte-for-byte identical to it.

Instead, the new isolated checkout contains a **reproducibly rebuilt** spec archive from the actual reviewed Phase 2 docs, with 28 requirements, 48 stories, 144 Gherkin cases, machine-readable catalogs, four schemas, examples and SHA manifest. The rebuilt archive has a distinct file name and checksum.

If the exact original attachment is required, it can be imported later as a separately labeled artifact after downloading it through the ChatGPT interface and verifying its expected SHA; do not overwrite this rebuilt archive.

## Current limits and gates

- R1 remains scoped/frozen and production GO cannot be inferred from R2 work.
- No Phase 2 migration was run against R1, no additional grant issued, no 1C base modified, no existing gateway/IdP/tunnel process stopped.
- The Phase 2 code is an isolated development slice, NOT the completed full Release 2.
- The 144 scenarios in the project catalog are `NOT_RUN`; G0–G7 remain pending.
- No arbitrary 1C COM/SQL or Windows executor is exposed to MCP data readers.
- Future merge direction: finish R1; review R1 main -> R2; test R2 staging on isolated DB/services; canary with approval; switch by deployment routing/feature flags, NOT simply switching a branch under the live gateway.

## Next work

1. Qualify real OData v3 EDMX canonicalization and handle known ordering/namespace/collision cases.
2. Approve Phase 2 scope/ADR before introducing DB changes; implement OBSERVED append-only time/event registry behind default-off flag.
3. Add verified dependency graph and ACCEPTED promotion policy; independent accounting evidence is required.
4. Build a native report UI recipe on an authorized disposable 1C copy and independent 521.1 comparison; never fabricate PASS.
5. Evaluate Drive least-privilege auth/new-files/revisions, port only audited PDCC connector contracts.
6. Add real source + PostgreSQL security/functional/load tests and a controlled R2 canary before any migration or switch.
