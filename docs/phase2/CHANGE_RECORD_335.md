# Change record 335 — resolve barrier ACK replay state semantics

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; implementation/evidence owner: Codex.
- The migration and qualification document were already present as untracked shared-worktree artifacts before this edit. This record attributes only the narrow source/document edits below to the current turn.
- The code area is S13 migration 027, routine `private_writer_register_barrier_ack_v1`, acceptance `S13-BARRIER-ACK-REF-01`.

## Investigation and decision

An initial source-only reading conflated `writer_barriers.progress='QUIESCED'` with `lifecycle_fences.state`. A tentative change and a stronger qualification sentence were made, then source tracing showed that `private_writer_finish_barrier_v1` changes only the barrier progress and leaves the lifecycle fence in `RECOVERING` at the same epoch. The registration routine's existing pre-replay lifecycle-state/epoch check is therefore compatible with the acceptance for exact replay after a barrier reaches `QUIESCED`.

The tentative source and acceptance edits were reverted in this turn. No intended migration behavior change remains. The migration was already an untracked shared-worktree file; its current whole-file hash differs from the preceding record-330 hash. The full-file delta provenance is not verified, so this audit attributes only the tentative/reverted local lines and does not claim the entire candidate is unchanged. The exact relevant routine currently still shows the lifecycle-state/epoch guard before the durable ACK lookup.

Evidence locations: `private_writer_finish_barrier_v1` updates `writer_barriers.progress` to `QUIESCED` at migration lines 4655–4666; `private_writer_register_barrier_ack_v1` checks lifecycle state/epoch at lines 1444–1448 and performs exact stored-row comparison at lines 1486–1505. The existing `S13-BARRIER-ACK-REF-01` acceptance already names replay after `QUIESCED`.

## Verification state and limits

- This turn did not run tests, SQL parsing, a database operation, a migration, a check, or a build.
- A read-only `database-reviewer` pass inspected the tentative diff and the existing acceptance row. It found no actionable BLOCKER/MAJOR in the proposed movement, but its review did not establish runtime semantics. Codex's subsequent source trace showed the intended barrier-progress/lifecycle-state distinction, so the candidate code edit was reverted rather than retained without a behavioral defect.
- A separate read-only `code-reviewer` pass found no actionable BLOCKER/MAJOR in the ACK protocol/verifier/registrar/trust sources or the reviewed migration paths against the REF/ACL/SERVICE-BINDING criteria. It confirmed that exact durable lookup precedes trust loading, registration preserves ambiguous outcomes, SQL registration is still revoked from runtime roles, and finalization changes barrier progress while retaining the lifecycle state. This is source review only; it did not parse SQL, run tests, or establish runtime behavior.
- No tests, SQL parsing, database operation, migration, check, or build was run.
- Prior test/reviewer results for earlier migration hashes do not qualify this change.
- Service-binding authorization remains required before the routine can be called. This change does not add a grant, install the candidate schema, or enable production.
- The COM writer boundary, valid licensed clone, effective installed grants, validator build trust root, and full S12/S13 qualification remain open.

## Current hashes

- `db/phase2/027_private_writer_admission_schema.sql`: current read-only observation `94B34F0FAAEEC4E3F71172A061ED74F972C5B0DB17F320E88B5F5061DD99D5AA`; this differs from record 330's `29CA6DB680C29707682B922CFA83823D4A53A1A8D79B90E18FB93272BD210FD7`, and the whole-file delta provenance is not verified.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `E48729D208B36EEE05891743D437857F172B8638D662B661C55C98631301AC97` (original qualification text preserved).

## Ordered next work

1. Retain the existing `S13-BARRIER-ACK-REF-01` acceptance and qualify exact replay after barrier progress `QUIESCED` in the post-coding disposable SQL phase.
2. Codex continues independent in-scope source work; later `functional-test-reviewer`, `database-reviewer`, and `security-reviewer` own their mapped runtime and exact-source reviews.
3. Operator remains accountable for authorized host/build/trust inputs. Do not add evidence-ingest grants or invoke the COM writer until their recorded prerequisites are satisfied.
