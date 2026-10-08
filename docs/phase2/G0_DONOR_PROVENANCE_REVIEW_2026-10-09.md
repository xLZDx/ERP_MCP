# ERP_MCP Phase 2 — G0 donor/license intake checkpoint (2026-10-09)

Status: **INVENTORY_PREPARED / OWNER_LEGAL_SIGNOFF_NOT_RUN**; no product/release GO granted. Evidence: `vendor/intake.json`, `vendor/UPSTREAMS.md`, `THIRD_PARTY_NOTICES.md`, and read-only submodule inspection on branch `hardening/phase2-client-safety-combined-20261009`.

## Observed inventory

- The Git tree defines reference submodules for `evilbruce666/1c-odata-mcp`, `hacker-cb/1c-odata`, and `prepod2003/mcp-rsv-data` at pinned commits. Their worktrees are not initialized in this isolated checkout (git submodule status begins `-`); no claim about actual upstream LICENSE files was made from these absent worktrees.
- `vendor/intake.json` records candidate origins and declared license strings: MIT sources for OData, accounting and bridge patterns; `ROCTUP/1c-mcp-toolkit` GPL-3.0 permitted only as a separately isolated service/reference; `1c-neurofish/onec-client-mcp-devkit` LGPL-3.0 and `1c-neurofish/v8-session-manager` AGPL-3.0 reference-only; `umanets/1c77-rest-api` and `tarasov46/1c-accounting-mcp` as UNVERIFIED/reference-only. These strings are *manifest claims*, not legal verification.
- `vendor/UPSTREAMS.md` additionally lists ten MIT-pattern donors and a vladimir-kharin upstream with an unverified license file; the two inventories are not fully synchronized. Do not infer every listed reference is a code dependency or redistributed binary.
- `THIRD_PARTY_NOTICES.md` attributes selected candidate presets from `theYahia/WWmcp` under MIT, and Undici runtime dispatch separately. This is specific provenance evidence, not a full third-party license audit.

## G0 controls pending before release

1. Generate a build-artifact SBOM, dependency/license scanner output, source-vs-shipped comparison and reproducible SHA-bound notice package for the exact release head. These are **NOT_RUN** for the combined Phase 2 branch.
2. Independently review all copied/adapted files and linked components for compatibility; unverified-license and AGPL/GPL references must not be silently pulled into the shipped runtime. Reference-only and separate-service labels do not themselves establish legal compliance.
3. Resolve `OB-04` authority: same DB with FK into R1 source registry versus an isolated DB with authenticated sync; define owner, ACLs, lifecycle and rollback. Don't wire an unresolved model into production.
4. Obtain explicit product-owner/security/legal G0 scope/ADR/license signoff on the exact candidate; previous approval to develop offline slices is not final product acceptance.

**Decision:** subtask *candidate provenance inventory* prepared; **G0 BLOCKED** until ownership/architecture and independent license approval. No user files or reference code deleted; R1 and 1C untouched.
