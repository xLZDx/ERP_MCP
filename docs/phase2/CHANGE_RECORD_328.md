# Change record 328 — bind barrier acknowledgement registration to an active writer

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator by explicit delegation; executor: Codex.
- The migration and disposable-prerequisite files were already untracked in the shared worktree;
  their earlier origin is not attributed. This increment changes only the registration function
  and adds a source/SQL acceptance row.
- No configured database, remote host, COM, key, staging, commit, or push operation occurred.

## Change

`private_writer_register_barrier_ack_v1` now selects the exact enabled, non-revoked service-binding
row matching the acknowledgement's base fingerprint, writer service and host `FOR SHARE` before
the trust-revision and advisory lock plan. Missing or mismatched binding returns the existing
`NOT_ENTITLED` refusal. Holding the row lock through the transaction prevents revocation from
committing concurrently with a new registration. This also requires a still-active binding for an
exact acknowledgement replay, consistent with the existing bound lookup path.

The routine remains revoked from `PUBLIC` and runtime roles in candidate migration 027; this change
does not grant it to the evidence-ingest service or enable a production path. The binding check
does not prove that the remote COM writer is real or that its transaction boundary is qualified.

Acceptance `S13-BARRIER-ACK-SERVICE-BINDING-01` was added to the disposable prerequisite matrix:
positive exact binding, absent/mismatched/revoked refusals, zero-write checks, both revocation race
orders, lock-order assertions and the existing default-denied ACL.

## Verification state

- Candidate migration 027 SHA-256: `7C559B7B4278DFB9E63CBC8CBD045A77EF00FEAC6B5BC50B5B3A36BF54C8654E`.
- SQL parse/runtime qualification and the new race cases are `NOT_RUN` for this hash. Earlier
  tests on migration SHA-256 `6EB879C79979A441F936260072DC56D003799E96E37CC4AA5E87767E39BC42C7`
  do not qualify the changed candidate. The configured lane still lacks the candidate schema and
  roles; its privileges are `NOT_MEASURABLE` there.
- No ACL was changed and no grant/migration was applied.

## Next steps

1. Database reviewer: review this exact migration hash for lock ordering, binding-row serialization,
   replay behavior and existing ACL posture.
2. Functional-test reviewer: after remaining source coding closes, add and execute the positive,
   mismatch/refusal and two-order binding-revocation race cases on an invocation-owned PostgreSQL 16
   cluster only.
3. Codex: keep the registration routine ungranted until authenticated validator provenance and
   evidence-ingest identity isolation are established and the exact grants are independently
   reviewed.
