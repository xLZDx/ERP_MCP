# S13 fenced epoch-writer candidates

## Change

Added source-only candidates in migration 027 for `bump_epoch_v1`, `register_principal_v1`, `register_target_v1`, `approve_registry_change_v1`, `register_verifier_key_v1`, `revoke_verifier_key_v1`, `enforce_registry_v1`, and `propose_registry_change_v1`. Existing adapter methods route these candidates only under the explicit private-writer schema flag; proposal v1 receives an adapter-preallocated UUID before the SQL call. The candidates have no application `EXECUTE` grants and are explicitly revoked from all named application/private roles. Verifier-key registration prelocks the trigger-compatible material key; revocation retains status-only semantics; enforcement retains one-way replay behavior.

## Why

`add_epoch_dependency_v1` reads an epoch after namespace 7. Independent source reviews established that its result could race legacy epoch changes through `bump_epoch`, direct principal/target registration, and approval-applied registry cores. The dependency routine remains ungranted until every conflicting writer is fenced and cut over.

## Contract and limits

- Candidate epoch writers take namespace 2 shared, namespace 7, and the lifecycle row before registry/epoch relation work; `bump_epoch_v1` preserves operator entitlement, key bound, bigint result, and existing `EPOCH_BUMPED` append semantics.
- Principal and target registration retain normalization, two-person bootstrap checks, source core writes, and caller identity while fencing before table reads/writes.
- Approval pre-reads a proposal only to derive a frozen plan, acquires namespace 2/7/lifecycle, the verifier material lock when applicable, and the namespace-6 registry-change ID before locking/revalidating the proposal and approval child. Replay and first-application authorization behavior follow the source contract.
- All new entries are ungranted; historical named-role grants remain. `private_writer_schema_enabled=True` is not a cutover proof and must remain disabled until all conflicting paths are fenced, effective ACLs are measured, and disposable races pass.
- Focused read-only code review found no material issue in the candidate source/routes, including proposal, verifier registration/revocation and enforcement; a separate ACL review confirmed no application grants. This source has not been SQL-parsed, installed, or runtime-qualified. No tests, migration, DB operation, COM, stage, commit, or push ran. Adapter runtime and disposable evidence remain `NOT_RUN`; effective privileges remain `NOT_VERIFIED`.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`