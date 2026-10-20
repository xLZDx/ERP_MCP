# Merge ERP_MCP_R2 into ERP_MCP (one project)

Date: 2026-10-20. Branch: integrate/2026-10-20. First parent 97e6ef8, second parent 7d9a01d (r2local/main, local main of github xLZDx/ERP_MCP_R2, 493 commits).

## Why
Operator decision: ERP_MCP_R2 and ERP_MCP are one project; there is no separate Release 1 / Release 2 or Phase 1 / Phase 2. ERP_MCP_R2 was extracted from ERP_MCP (git filter-branch of the phase2 branch, see docs/phase2/EXTRACTION_NOTE.md), so the histories share no merge-base and `--allow-unrelated-histories` is justified. No `-X ours/theirs` was used.

## Conflict resolution (64 add/add files)
Both lines descend from the phase2 branch tip 88753c2. Each conflicting file was diffed against it:
- Kept the ERP_MCP version (R2 == 88753c2; ERP_MCP carries today's English translation and hardening): 28 src/tests files (backend_budget, onec_discovery, purchase_reconciliation, reconciliation, structural_diff, structural_hash, 23 tests incl. noqa clean-up and the forged-authority test fix), docs/phase2 CONTRACTS_AND_API_RU, DECISIONS_AND_SOURCES_RU, NATIVE_REPORT_PROTOCOL_RU, PACKAGE_COMPLETION_RU, PLAN_PHASE2_RU, README, SPRINT_S6B..S9, STORIES, TDD, TEST_PLAN, and the two PHASE2 S6B/S9 html reports.
- Took the R2 version (ERP_MCP == 88753c2, R2 newer, S10-S13 / CR up to 170): docs/phase2 G1_IMPLEMENTATION_NOTE, G1_OPERATOR_BACKLOG, IMPLEMENTATION_STATUS, OPERATOR_BACKLOG, S10_RELEASE_HANDOFF; scripts/build_document_registry.mjs, scripts/phase2/bootstrap-local.ps1; tests/phase2/_pg_harness.py, test_g1_crash.py, test_g1_postgres_integration_review2.py, test_g1_restore.py.
- Merged by hand: README.md (one project; ERP_MCP content kept, R2 status/layout/verification added, Release 1/2 split removed); CLAUDE.md (gateway boundaries plus living-model rules); .gitignore (union); pyproject.toml (union: adds PyYAML, jsonschema, `testlane` extra; name/description stay erp-mcp; uv.lock NOT regenerated); core/DECISION_LOG.md (union of both sides, 18 exact duplicate lines dropped); governance/DOCUMENT_REGISTRY.md (regenerated with scripts/build_document_registry.mjs, 408 paths; the registry depends on the refs present when it is generated).

## Not done (recommended next steps)
- Rename phase2 directories and packages (separate refactor).
- Regenerate uv.lock (needs network); verify requirements-runtime.lock needs PyYAML.
- Ruff: R2-only code has 249 findings (subset of the 282 on r2local/main itself); baseline ERP_MCP was clean. Needs a lint pass.
- Translate new Russian prose from R2 (reports/*.ru.html siblings, docs/phase2/artifacts/G3_ENGINEERING_RECONCILIATION_INDEX.md, CT14_FEASIBILITY_SPIKE, S11_* documents, OPERATOR_BACKLOG fragments, S12_CONTRACT_FREEZE_V2).

## Verification (interpreter: ERPMCP .venv, PYTHONPATH=src)
- Deleted-files audit vs 97e6ef8: empty. Conflict markers: none. AST parse of 107 changed .py, pyproject.toml and changed JSON: OK. No duplicate test basenames.
- tests/phase2 + tests/gate_manifest + tests/testlane: merged 12 failed, 13 errors, 6847 passed; R2 tip own run in detached worktree D:\Repo\Trash\_test\R2tip: 12 failed, 13 errors, 6824 passed; failing name sets identical (pre-existing on R2 tip, mainly disposable-PostgreSQL / environment-dependent tests).
- ERP_MCP main set: 2 failed (same two pre-existing), 1851 passed, 192 skipped.
- Not run: PostgreSQL integration tests, e2e, real 1C, Docker, uv lock.
