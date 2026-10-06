# Autonomous engineering execution log

## Step 21 — source-specific register capability rule

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-05

- Added migration 005 to persist register capability evidence per source.
- The Python adapter and OData sidecar require confirmation for the exact source, register entity
  set, and method. The sidecar rechecks its short-lived live-metadata profile before each operation.
- Configuration-sensitive operations, including `DrCrTurnovers`, return
  `CAPABILITY_UNSUPPORTED` when evidence is absent or stale. No alternate names are guessed and no
  speculative OData data request is issued. Positive and negative evidence is returned in the
  source capability profile.
- Added the internal ERP_MCP ↔ pinned OData sidecar contract, capability endpoint/response tests,
  migration/persistence coverage, and confirmed-positive/unsupported-negative DrCr fixtures.
- Reuse remains pinned to `hacker-cb/1c-odata` SHA
  `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`; upstream source is unchanged. No new OData protocol
  implementation, COM bridge, or GPL-derived core code was added.
- Verification: Python `67 passed, 5 skipped`; sidecar `11/11`; pinned upstream client
  `428 passed, 1 skipped`; metadata `53 passed`; PostgreSQL integration `4 passed`; Ruff,
  compileall, Bandit, and `git diff --check` pass. The rebuilt image returned `/healthz` 200 as UID
  10001 with no published ports.
- Next: publish this batch and wait for hosted CI; then continue with semantic profile/preset
  lifecycle and deterministic tests. Real-source semantic validation still requires a real 1C base.

## Step 22 — semantic profile/preset foundation

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-06

- Rechecked the pinned Aprovodka SHA `7b62c90e1fe74324605dc28d76f195200bb97252`: preset types,
  BP 3.0/UT 11/ZUP 3.1/ERP 2 data, accounting/register read-side tools, and `tests/presets.test.ts`.
  Its `verified` label refers to upstream documentation, not a concrete customer source; ERP_MCP
  therefore imports only the four preset identities as `CANDIDATE_ONLY` references.
- Added migration 006 for source/company-scoped, versioned semantic profiles and canonical mappings,
  preserving upstream repository/SHA and metadata/capability/profile fingerprints. Runtime role is
  read-only; admin role can maintain profiles/mappings but cannot delete them.
- A profile can be used only when explicitly `VALIDATED`, exact source/company and metadata match,
  metadata drift is acknowledged, and ten passing native-report reconciliation cases are present.
  Capability dependencies still require current positive source evidence and deny with
  `CAPABILITY_UNSUPPORTED` otherwise.
- Metadata-fingerprint changes automatically stale previously validated profiles via a narrow
  `SECURITY DEFINER` trigger on source capability updates; no broad runtime UPDATE privilege is
  granted.
- Verification: full Python suite `73 passed, 6 skipped`; Ruff, compileall, Bandit pass; disposable
  PostgreSQL applied migrations 001–006, privilege checker passed, PostgreSQL integration `5/5`.
  The prior capability batch CI Python job passed on `e964e32`; pinned OData job remains queued.
- Still not implemented: validated accounting mappings/tools, administrator workflows/audit, and
  actual native 1C reconciliation. No preset is promoted from candidate based solely on its name.

## Step 23 — operator profile lifecycle and audit

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-06

- Added operator-only CLI commands to create a source/company-scoped draft, add candidate mappings,
  validate, and retire profile versions. Creation requires supported live metadata and acknowledged
  stable drift state; validation compares the stored live source capability/metadata fingerprints
  and checks every mapping's exact register dependency before promotion.
- Validation normalizes evidence to ten or more distinct passing case IDs and controlled native
  report references; raw reports are not copied into PostgreSQL. Database checks enforce case count,
  uniqueness, PASS state and non-empty report references.
- Migration 007 adds an append-only profile lifecycle event table. Runtime role can only read it;
  admin can append but cannot update/delete event history. Profile administration itself is restricted
  to the admin connection.
- Added [operator workflow documentation](../docs/SEMANTIC_PROFILES.md), lifecycle and privilege
  integration coverage. Verification: Python `74 passed, 7 skipped`; disposable PostgreSQL applied
  migrations 001–007, privilege checker passed, PostgreSQL integration `6 passed`; Ruff, compileall,
  Bandit, pip-audit (`no known vulnerabilities`) and diff checks pass.
- Preset mappings remain candidate-only until a real source has been inspected and native reports
  reconciled. Canonical MCP accounting tools are still not exposed.
- Hosted CI run `37375030150` on `5f7061d` passed both the gateway/database test job and pinned
  `odata-upstream` job. A duplicate same-SHA run remains queued and is not used as acceptance
  evidence.

## Step 24 — pinned semantic preset candidate data

**Status:** implemented and verified locally and in hosted CI.
**Date:** 2026-10-06

- Re-read the exact pinned Aprovodka preset files/types/tests at SHA
  `7b62c90e1fe74324605dc28d76f195200bb97252`; imported a selected, explicitly documented subset
  of entity-set hints for BP 3.0, UT 11, ZUP 3.1 and ERP 2. The source's `verified`/`common` labels
  are retained only as upstream confidence metadata, not as evidence about an installed base.
- Semantic profile creation persists candidate entity names, kinds, upstream confidence, exact
  repository/SHA/path provenance, and `CANDIDATE_ONLY` status. Candidate names are never sent to
  OData or used to promote a profile. The per-source capability check remains the only operation
  gate; unconfirmed register calls return `CAPABILITY_UNSUPPORTED`.
- Updated third-party attribution with the Aprovodka MIT notice. Added catalog invariants and a
  PostgreSQL lifecycle assertion that candidate records remain candidate-only.
- Verification: Python `74 passed, 7 skipped`; migrations 001–007 and DB privilege policy pass;
  PostgreSQL integration `6 passed`; Ruff, compileall, Bandit, pip-audit (no known vulnerabilities)
  and `git diff --check` pass. The pinned upstream source remains unchanged.
- Hosted CI run `37375751454` on `de03524` passed both gateway/database tests and the pinned upstream
  OData build, contract tests, and non-root image smoke.
- Next software work: executable company-filtered business reads, canonical accounting tools,
  completed audit/operations proof and remaining deployment/security gates. Promoting a candidate
  or validating accounting semantics still requires a real target 1C source and native reports.
- D11 audit outcome follow-up on `phase/p1-audit-outcomes`: extended the runtime-role PostgreSQL
  round-trip to exercise success, denial and error events, assert company/provenance/result fields,
  and attempt append-only UPDATE/DELETE against each event. Local suite: `74 passed, 7 skipped`
  (the PostgreSQL integration test requires CI DB); Ruff, compileall and diff check pass. Draft PR
  and hosted verification pending.
