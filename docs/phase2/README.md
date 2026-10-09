# ERP_MCP Phase 2 — Design Package v0.1

**October 8, 2026 — Draft for review.** This document describes the initial design-package checkpoint, **not the current implementation status**. Release 1 remained frozen at the time. The package did not change R1 runtime behavior, migrations, grants, native validation policy, or the release decision. For current results, consult the implementation, evidence, and decision logs.

## Core Project Documents

- **TDD_PHASE2_RU.md** — 28 requirements covering architecture, connectors, PDM/LDM, taxonomy, temporal database, native capture, reconciliation, and security.
- **PLAN_PHASE2_RU.md** — 11 sprints (S0–S10), gates G0–G7, dependencies, technical spikes, deployment, and rollback.
- **STORIES_PHASE2_RU.md** — 48 stories linked to 144 acceptance scenarios.
- **TEST_PLAN_PHASE2_RU.md** — test levels, concrete assertions, the capacity/failure matrix, and independent user/admin acceptance testing.
- **NATIVE_REPORT_PROTOCOL_RU.md** — manual native UI capture, qualified automation, an optional qualified standard engine, development/production permissions, and 12 qualification cases.
- **DECISIONS_AND_SOURCES_RU.md** — proposed architecture decisions, risks, references, and unresolved decisions.
- **CONTRACTS_AND_API_RU.md** — data dictionary, APIs, scope/time/transaction boundaries, and four JSON contracts.
- **PACKAGE_COMPLETION_RU.md** — precise package preparation results, placement, and verification limits.
- **SPEC_VALIDATION_SUMMARY.json** — measured specification/L0 results and package SHA-256.

The existing filenames are retained to avoid breaking references. Their language suffixes are historical, not proof of English-language completion.

## Portable Specification Package

The original chat supplied **ERP_MCP_PHASE2_SPEC_v0.1_2026-10-08.zip**: 38 files containing expanded documentation, offline HTML, requirements/stories/test-case YAML, traceability.csv, 144 Gherkin scenarios, four JSON Schemas, synthetic examples, and executable specification/L0 tests.

At the time of preparation, the archive had **not** been copied or extracted on Windows. Until extracted, companion YAML files, schemas, and tests could not be assumed to exist in this directory. A suitable location was a new **docs/phase2/spec-v0.1/** subdirectory without overwriting existing files. Later work must be verified against actual repository contents rather than this historical note.

## Verification of the Initial Package

The packaging environment executed **35 specification/L0 checks: all passed, none skipped**. The 144 product test scenarios, real 1C/Drive/PostgreSQL/UI/COM/native/production checks, and Gherkin step implementations were **not run or implemented as part of this design checkpoint**. JSON Schema validation alone does not establish genuine artifact provenance, actual permissions, or independent attestation.

The offline HTML passed static checks of structure, links, and absence of external rendering dependencies. A visual browser run was not performed because managed Chromium blocked local-file navigation; no restriction was bypassed. Details are in **PACKAGE_COMPLETION_RU.md**.

## Primary Accounting Evidence Decision

A genuine standard 1C report can serve as an **independent native accounting oracle**, whether generated manually or through qualified automation. A file reconstructed from MCP-reported amounts cannot independently validate those same amounts.

Validation requires qualified source/capture procedure provenance, consistent source identity, all six relevant report columns and underlying rows, and independent accountant approval. Production native-capture capability remains **disabled by default** until a target-specific permit is granted.

No actual user financial amounts were added to the new Git or package test fixtures. A private arithmetic note remained in the chat and is not native-report evidence.

## Historical Status of This Design Checkpoint

The design package was complete for review, but Phase 2 implementation had **not begun as part of this preparation step**. R1 code, configuration, migrations, and permissions were unchanged. At the time, there had been no local commit, push, merge, restart, load test, or deletion; unrelated changes were untouched.

The package was subsequently published only as **draft documentation**, on a separate documentation branch and pull request. Publication did not constitute design acceptance or authorization to implement Phase 2.

**Current Phase 2 progress must be established from exact Git HEAD, tests, the evidence matrix, and approved gate decisions. This historical document must not be used to infer a current release GO.**
