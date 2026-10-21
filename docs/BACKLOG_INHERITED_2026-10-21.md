# Inherited defects backlog (ERP_MCP), 2026-10-21

Scope: defects and open items inherited by the 2026-10-20 manual branch integration (including the merge of the former ERP_MCP_R2 repository). By operator decision the integration did NOT fix any of them; each item below is "not fixed by integration by operator decision". Evidence source: `D:\Repo\Trash\_integrate\STATE_ERPMCP.md`, `docs/commits/2026-10-20-english-policy-inventory.md`, `docs/commits/2026-10-20-merge-erp-mcp-r2-into-one-project.md` and `docs/commits/2026-10-20-english-policy-registry-fix.md`.

Severity values are guesses made at recording time, not reviewed ratings.

## ERPMCP-INH-001: Cyrillic prose inherited from both parents violates the English-only policy

- Severity guess: MAJOR (policy violation across 128 tracked files; translation is broad but mechanical).
- Evidence: `docs/commits/2026-10-20-english-policy-inventory.md` counts 128 tracked files and 2459 lines with Cyrillic: PROSE-TO-TRANSLATE 38 files / 856 lines, LOCALIZATION 11 / 538, LITERAL-1C-NAMES 8 / 117, SEMANTIC-TEST-DATA 71 / 948. Seven intentionally Russian `reports/PHASE2_S*_SPRINT_*.ru.html` reports are outside the scanned extension set.
- Origin: both parents (ERP_MCP and ERP_MCP_R2 / branch `phase2/living-model-connectors-reconciliation`); integration origin: merge commit e82022a.
- Suggested acceptance test: a tracked-file Cyrillic scan with an allowlist file (test data, semantic profiles, LITERAL-1C-NAMES, and the 7 paired `*.ru.html` reports if the operator keeps them) reports zero violations; behavior tests that depend on Russian data still pass unchanged.
- Status: not fixed by integration by operator decision (translate in a separate sprint; keep the allowlist for test data, semantic profiles and the 7 paired `*.ru.html` reports).

## ERPMCP-INH-002: document registry generator escapes Cyrillic instead of translating

- Severity guess: MINOR (workaround in a generated file).
- Evidence: `scripts/build_document_registry.mjs` escapes Cyrillic in generated cells to `\uXXXX` (commit ffbfb60, `docs/commits/2026-10-20-english-policy-registry-fix.md`), because the registry quotes headings from all refs, including Russian variants on archive, rescue and snapshot refs.
- Origin: integration fix ffbfb60.
- Suggested acceptance test: after the translation sprint, the generator is run without escaping and `governance/DOCUMENT_REGISTRY.md` contains no `\u04..` sequences and no Cyrillic; the escape code path is removed.
- Status: not fixed by integration by operator decision (replace the escape with real translation).

## ERPMCP-INH-003: inherited test failures to classify

- Severity guess: MAJOR (unclassified red tests; mostly environment-dependent per the record).
- Evidence: the merged `tests/phase2` + `tests/gate_manifest` + `tests/testlane` run gave 12 failed and 13 errors (6847 passed); the failing name set is identical to the ERP_MCP_R2 tip run in a detached worktree (12 failed, 13 errors, 6824 passed); causes are mainly disposable-PostgreSQL and other environment dependencies. The main test set has 2 pre-existing failures: `tests/test_chatgpt_mcp_contract.py::test_all_public_mcp_tools_are_explicitly_read_only_for_chatgpt` and `tests/test_operations_artifacts.py::test_fault_injection_and_runbook_artifacts_are_present`. A third main-set failure (`test_script_gate_guards::test_acl_guard...`, jwks timeout) was a load-sensitive flake that passes alone. Name lists: `D:\Repo\Trash\_integrate\out_ERPMCP_r2m.p2.fail.txt` and `out_ERPMCP_base.main.fail.txt`. Also 249 ruff findings in R2 code (subset of 282 on the R2 tip).
- Origin: ERP_MCP_R2 tip `7d9a01d`; integration origin: `STATE_ERPMCP.md` R2 merge entries.
- Suggested acceptance test: a table classifies every one of the 12 failures and 13 errors (needs PostgreSQL, needs 1C, flake, real defect); with the declared environment available every environment-class test passes; the 2 main-set failures each get a fix or a documented waiver.
- Status (2026-10-21): preliminary identifier-only classification recorded in `docs/phase2/artifacts/WP2_INHERITED_TEST_CLASSIFICATION_2026-10-21.md`. The exact 13-error / 14-failure identifier set is reconciled; per-test causes and runtime acceptance remain NOT_RUN. The previous historical aggregate describes causes mainly as environment dependencies, but that does not establish individual causes.

## ERPMCP-INH-004: locked install not yet proven after the R2 merge (lock files reconciled)

- Severity guess: MINOR (the lock-file mismatch is fixed; only the clean locked install is unproven).
- Evidence: the R2 merge unioned `pyproject.toml` (adds PyYAML, jsonschema, the `testlane` extra) but `uv.lock` was not regenerated at that time (`docs/commits/2026-10-20-merge-erp-mcp-r2-into-one-project.md`, "Not run: ... uv lock"). This part is CLOSED by commit db9512f1 (`docs/commits/2026-10-21-erp-mcp-lock-reconcile.md`): `uv lock --check` passes and the CI export equals the committed `requirements-runtime.lock`. Still open: `uv sync --locked` and an isolated clean install were not run, and the reconciliation used uv 0.12.9 while CI pins uv 0.12.23.
- Origin: ERP_MCP_R2 merge e82022a.
- Suggested acceptance test: `uv lock --check` with the CI-pinned uv 0.12.23 passes; an isolated install from the locked files in a clean environment (`uv sync --locked --all-groups --extra dev`) succeeds and the offline test set runs.
- Status: not fixed by integration by operator decision.

## ERPMCP-INH-005: phase2 directory layout and retirement of the ERP_MCP_R2 repository

- Severity guess: MINOR (structure and housekeeping; needs an operator decision first).
- Evidence: the R2 merge kept the existing `docs/phase2` layout and merged R2 files into it; the inherited "phase2" directory naming was not renamed. The old repository `D:\Repo\ERP_MCP_R2` still exists after the merge into one project.
- Origin: operator instruction of 2026-10-20 (merge ERP_MCP_R2 into ERP_MCP, one project); integration origin: e82022a.
- Suggested acceptance test: operator decision recorded in `core/DECISION_LOG.md` for (a) the rename of the phase2 directories, with every reference and test path updated and tests green, and (b) retirement of `D:\Repo\ERP_MCP_R2` (archive plus verification that nothing is unique there); retirement is a deletion and remains operator-only.
- Status: not fixed by integration by operator decision (operator decision pending).
