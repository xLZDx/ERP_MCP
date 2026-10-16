# R-03 design: Ed25519 cutover for writes and action evidence

Date: 2026-10-16. Status: non-gating local prototype; production cutover and formal R-03 closure remain unauthorized and unproven.

## Goal

Require Ed25519 for newly written signed actions and prevent legacy-signed evidence already stored before migration 019 from authorizing state changes after cutover. Preserve historical evidence reads. Ensure permit signatures can only be attached to a change in the caller's tenant and company.

## Current behavior and constraints

Migration 015 retains `KEYED_HASH_STANDIN` in the internal `signature_ok` dispatcher. Migration 019 guards four new-write boundaries (`record_evidence`, `record_checkpoint`, `attach_permit_signature`, and `record_dispatch_receipt`) against non-Ed25519 keys. Existing records are immutable and retain `signer_key_id`; migration 017 prevents normal runtime changes to key material, algorithm, and role. However, state-changing consumers can still read pre-019 evidence through `evidence_ref`; `operator_resolve` directly selects observations and consumes a stored cosign proof; and `operator_close_failed_verify` consumes cosigns through `consume_two_person_cosign`. `dispatch_permits` has no tenant/company columns, so permit lookup/update must join its owning `records` row to the requested scope.

Migrations 015–020 are checksum-recorded and must not be edited in place. No live key inventory, deployed signer custody, production writer, or signing-time fingerprint evidence has been collected. `read_evidence` is an audit read path and should continue returning historical rows.

The algorithm check resolves `signer_key_id` against the scope-matched verifier key. Normal runtime roles cannot mutate key algorithm/material, and key registration prevents re-keying an existing ID. This prototype does not protect historical classification against privileged owner-level direct mutation; formal R-03 evidence must establish custody/provenance or address immutable key-version snapshots separately.

## Options and decision

1. **Guard evidence at every action-consumption boundary (chosen):** add an additive migration 021 that makes the common `evidence_ref` helper reject non-Ed25519 signer keys, guards direct action reads such as `operator_resolve`, and validates the evidence reference embedded in any consumed witness cosign. Scope permit signature lookup and update through the owning record. This is backward-compatible for historical reads and blocks legacy evidence as action authority.
2. **Rewrite or delete historical rows / disable the legacy verifier globally:** this mutates audit history or breaks unrelated internal behavior and is not required to close the identified consumer path.

The first option preserves the existing audit record and shared verifier while enforcing the cutover at the point where evidence changes state.

## Design

- Add transaction-wrapped migration `021_ed25519_consumer_cutover.sql`, requiring recorded migrations 001–020 and using `living.record_migration`.
- In `evidence_ref`, join `evidence_records.signer_key_id` to the scope-matched verifier key and require `key_algorithm = 'ED25519'`; retain the existing `EVIDENCE_UNSIGNED` failure for absent, malformed, or legacy evidence. Signed write and action APIs that use this helper inherit the check.
- In `operator_resolve`, restrict its direct observation query to evidence signed by an Ed25519 key. Require stored witness cosign completion proofs consumed by `operator_resolve` or `operator_close_failed_verify` to reference same-scope Ed25519 `COMPLETION_PROOF` records. Historical `read_evidence` remains unchanged.
- Scope `complete`'s direct refusal evidence lookup by tenant, company, change, and evidence ID as defense in depth; runtime callers still enter through the signed wrapper.
- In `attach_permit_signature`, require an owning `records` row in `(t,c)` for permit digest selection and update. Preserve role, signature, and error behavior.
- Preserve SECURITY DEFINER, fixed `search_path`, `ledger_owner`, and non-PUBLIC execute policy for replaced functions. Do not alter `signature_ok` or historic data.

## Failure modes and compatibility

After migration 021, legacy-signed evidence remains visible through authorized audit reads but cannot be used by a state-changing signed API or operator resolution. Existing legacy evidence that operators previously used for a transition will fail closed with `EVIDENCE_UNSIGNED` / `COMPLETION_PROOF_MISSING`; a new, correctly scoped Ed25519 evidence record is required. Cross-tenant permit IDs fail as `PERMIT_MISSING` and produce no update. Any migration failure rolls back transactionally. After successful application, correction is forward-only; reverting to unguarded function bodies would reopen the security finding.

## Rollout and rollback

Apply only on disposable local PostgreSQL for this prototype. Migration 021 depends on 019 and 020. Formal rollout remains blocked on deployed key inventory, custody/provenance, signer migration compatibility, production writer/path inventory, backup/restore rehearsal, and explicit deployment authorization. Do not change production or claim formal R-03 closure.

## Verification plan

After all in-scope coding is complete, `functional-test-reviewer` and `e2e-runner` own focused disposable-PostgreSQL scenarios:

1. Seed valid legacy-signed evidence before 019, apply through 021, and prove every state-changing consumer rejects it without changing the record; confirm authorized historical `read_evidence` still returns it.
2. Cover the direct `operator_resolve` observation and stored witness-cosign reference paths in both `operator_resolve` and `operator_close_failed_verify` with pre-cutover rows.
3. Prove equivalent valid Ed25519 action flows still pass and retain existing scope, role, replay, and state-transition guards.
4. Attempt permit signature attachment using a change ID from another tenant/company; require no update and the existing missing-permit failure. Confirm an in-scope permit succeeds.
5. Re-run the migration 019 write-boundary and end-to-end dispatch receipt cases against the final migrations.

Then fresh `database-reviewer` and `security-reviewer` reviews assess the exact final head. The primary agent checks test-to-acceptance mapping and exact outputs. No pytest, CI, lint, typecheck, build, or migration/legal verification scripts are permitted by the workspace rules.

## Remaining unknowns

Formal R-03 remains OPEN. No deployed legacy key, affected signature reference, custody chain, production writer, or exploit has been established. G1–G8, S13 formal approval, Release 2, and production authorization do not change from this local prototype work.
