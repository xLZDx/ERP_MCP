# Phase 2 workstation isolation verification — 2026-10-08

Status: setup completed using Remote Desktop Commander on authorized Razer workstation.

- Isolated checkout: `D:\Repo\ERP_MCP-phase2`.
- Active branch: `phase2/living-model-connectors-reconciliation` tracking `origin/phase2/living-model-connectors-reconciliation`.
- Main branch base at creation: `94f4cee5842776d0b8810cf3f38e2682a701002a`. GitHub main remained there at last GitHub check.
- Last verified pushed Phase 2 commit before this evidence note: `4cf5f743c1d33c6f60ab09de63838d268c330a70`.
- Full source checkout completed with `git submodule update --init --recursive`, at pinned SHAs:
  - `vendor/reference/1c-odata-mcp`: `dc6b6a1358c7e65e3cfb45c22e8157d1479ab71e`.
  - `vendor/reference/1c-odata-v3`: `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`.
  - `vendor/reference/mcp-rsv-data`: `76fed8e6e16833fee1514969841b8d9a61c7c152`.
- Independent `.venv` installed from `uv.lock`; no Phase 1 virtualenv reused.
- Offline tests: `python -m pytest -q tests/phase2` -> **23 passed**.
- Ruff: `ruff check scripts/phase2/build_spec_bundle.py tests/phase2 src/business_ai_gateway/phase2` -> **All checks passed**.
- Rebuilt archive: `docs/phase2/artifacts/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08.zip`, expected SHA256 from last final build `4746946a6d51f47aeb37229ff6d69bdfdbfe99008caecaceece42db4a59ae3fa`. Deterministic ZipFile writer uses fixed metadata timestamps and manifest.
- Derived spec package contains 28 requirements, 48 stories, 144 specification-only Gherkin cases and four JSON schemas. Product tests remain NOT_RUN.
- Original conversation ZIP (38 files, SHA256 `e1ab5e1d8e96307a57536c82ce132a7591b41b2e3adf71e8b7c1e7adc2703963`) is **not the rebuilt archive** and is not claimed present on workstation.
- Phase 1 directory `D:\Repo\ERP_MCP-integration-candidate` remains a separate dirty worktree. No resets/stashes/switches or service restarts were executed on it by this Phase 2 setup.
- No real 1C, IdP, cloud tunnel or production DB was modified and no Phase 2 schema migration applied.
- Switching into production is not a git checkout action: R1 freeze completion, R2 gates G0–G7, audited migration, rollback and operator sign-off are still required.

This is a handoff receipt and not a production/reconciliation attestation.
