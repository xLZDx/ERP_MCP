# Phase 2 operator backlog

Date: 2026-10-08. Branch: `phase2/living-model-connectors-reconciliation`. Release 2 status: **NO-GO**.
Only items that engineering cannot close without the operator. G1-specific blockers stay in `G1_OPERATOR_BACKLOG.md`.

Evidence source: six read-only local reviews of HEAD `9b4fc0c` (database, security, Python, test adequacy, reliability, architecture) on 2026-10-08. Findings are static; nothing was executed on PostgreSQL.

## P0 — block G0/G1 and any merge

| ID | Blocker | Evidence | Minimal operator action | Blocks |
| --- | --- | --- | --- | --- |
| OB-01 | No G0 / scope rebaseline recorded for R2 code inside the R1 repository | `docs/DOCUMENT_INDEX.md` says FROZEN / NO NEW SCOPE; `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md` §7 requires frozen IDs; no `phase2` mention in R1 normative docs | Record a decision: rebaseline, or explicit permission for an isolated prototype until G0 | Any merge to main, G0 |
| OB-02 | No dedicated ChatGPT conversation bound to this worktree in PM Bridge | `pm_rosetta_plan` refused: no project to conversation binding for `D:\Repo\ERP_MCP-phase2`; `config/projects.json` has only `erp_mcp-integration-candidate` and `erp_mcp-native-reports` | Provide an exact `https://chatgpt.com/c/<id>` link for a Phase 2 chat (do not reuse the R1 chat) | GPT-PM review, Rosetta governed work, push approval |
| OB-03 | RESOLVED 2026-10-08: operator ordered a disposable instance; docker container `erp-phase2-test-pg` created and used (20/20 integration tests green). Earlier text: No authorized disposable PostgreSQL | No docker/psql/pg_ctl on PATH, no PostgreSQL service on this machine | Authorize/create a disposable R2 test database with separate credentials, isolated from R1; supply DSN via `ERP_PHASE2_TEST_DSN` | G1-08/09, all integration/security/concurrency/backup tests |
| OB-04 | Source registry decision: `living.sources` (own) vs reuse of R1 `bag.sources` | `CONTRACTS_AND_API_RU.md` says existing sources are reused; `001_living_registry.sql` defines its own table | Choose: same DB with FK, or separate DB with sync | Final shape of RLS and FKs |
| OB-05 | ANSWERED 2026-10-08: no CI, R2 not mixed with R1, R1 updates pulled by merge. Earlier text: R1 fingerprint gate and CI include Phase 2 directories | `scripts/engineering_checkpoint.py` hashes `src`, `tests`, `scripts`; `pyproject.toml` `testpaths=["tests"]`; CI runs full `pytest` | Approve excluding `*/phase2` from R1 fingerprint/CI, or moving R2 code out of R1 trees | R1 gate health, merge |
| OB-06 | Earlier remote tool policy refused a hardening-SQL write | Recorded in `G1_IMPLEMENTATION_NOTE_2026-10-08.md`; local authoring path is separate and no bypass was used | Only if the remote route is still needed: resolve policy with the provider | Remote-tool authoring only |

## P1 — external access needed for later sprints

| ID | Blocker | Minimal operator action | Blocks |
| --- | --- | --- | --- |
| OB-10 | Real 1C source access and source-specific capture permit for `onec-818ha-reference` | Provide scoped read access and permit | S3 qualification, S5 |
| OB-11 | Independent accountant attestation for 818 HA SRL, account 521.1, 2026-08-01..2026-08-31 | Accountant exports native report and attests | S5/S6, G3/G4 |
| OB-12 | ERP_MCP-owned Google Drive OAuth client and narrow folder grant | Create OAuth client, grant narrow folder/new-child access | S7 |
| OB-13 | Secret provider and rotation procedure for production | Name provider and owner | S1 secret rotation, S9 |
| OB-14 | R1 shadow-compatibility and production canary approval | Approve canary window and rollback owner | S9/S10 |
| OB-15 | Donor code/license inventory approvals | Review inventory; approve any GPL/AGPL boundary | S0/S1 |

## P2

| ID | Item |
| --- | --- |
| OB-20 | R2-US-047 (FOLLOW_ON/P2): confirm in or out of Release 2 scope |
| OB-21 | Final release-owner approval for `PRODUCTION_GO` (only after G0–G7 actual PASS) |

## Unblock criteria

- OB-03 resolved: `pytest -m integration` with `ERP_PHASE2_REQUIRE_PG=1` runs and is green on the exact head; roles, RLS, immutability, CAS, fencing, outbox crash and backup/restore evidence recorded.
- OB-02 resolved: plan recorded and approved, one broad GPT-PM sweep on the exact head, correlated APPROVE before push.
- OB-01/04/05 resolved: decision recorded in `docs/phase2/DECISION_LOG.md`.
