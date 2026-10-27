# Change Record 300 — revalidate release-claim mutation preconditions

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer.
- Acceptance: `S13-RELEASE-CLAIM-RANK-01`.
- State: source-only candidate; manual source inspection only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Finding and change

`release_claim_v1` included its repair or ordinary parent ID in the namespace-6 and record-lock plan, but did not freeze and compare the parent's full row. A concurrent parent change could therefore pass through a stale parent plan before the helper released resources or handed a target lock back. The ordinary zero-effect helper also deletes a target lock only when its owner already matches, but silently succeeds when the row is absent or owned by another change; that could otherwise let claim-token/record state advance despite failing to release the target.

Migration 027 now snapshots the selected parent row before ranked resource locks, requires it to exist in the requested tenant/company, and compares the full JSON row after the ordered parent/record locks. A changed, missing, or cross-scope parent returns `LOCK_PLAN_STALE` before mutation. For a still-`ISSUED` token, it also requires the frozen target-lock row to exist and be owned by the releasing change; an absent or differently owned target lock returns `LOCK_BUSY` before token, resource, record, or event changes. The pre-existing non-`ISSUED` lookup-only replay remains ahead of this check.

## Evidence and limits

The source acceptance is `S13-RELEASE-CLAIM-RANK-01` in `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. The implementation is `change_ledger.release_claim_v1` in `db/phase2/027_private_writer_admission_schema.sql`. The acceptance fixture now explicitly requires both parent-snapshot drift and missing/non-owned target-lock refusal before DML.

This is manual source work, not parsed or runtime-proven. Migration 027 is uninstalled and ungranted; effective privileges remain `NOT_VERIFIED` and disposable qualification remains `NOT_RUN`.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — freeze and revalidate the selected parent row in `release_claim_v1` before mutation.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — add the concurrent-parent-change stale-plan case.
