# Change Record 270 — S13 owned-key-lock scope closure

## State and ownership

- Date: 2026-10-25.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: not re-established by this change; this is the in-repository SQL candidate, and existing S13 stack ownership records remain the evidence source.
- State: source implementation and qualification contract updated; independent code review found no in-scope code defect; runtime qualification remains pending.
- No SQL parser, tests, migration, database, install, grants, or live 1C action was run.

## Change

Migration `db/phase2/027_private_writer_admission_schema.sql` now fails closed with `LOCK_PLAN_STALE` when a selected record owns a `key_locks` row whose tenant, company, or base differs from the selected record. The preflights cover `claim_v1`, `operator_resolve_v1`, `release_claim_v1`, `revoke_change_v1`, the bounded `revoke_stale_v1` batch, `retry_verify_v1`, `operator_close_failed_verify_v1`, `private_writer_recovery_t5x_v1`, `cancel_permit_v1`, and the shared T6c/T6r recovery permit. In all ten listed paths, the complete planned key set or owner scope is checked again after the namespace-6 owner fence and before namespace-4/resource row locking. A changed plan refuses before the unplanned key can be used or DML can run.

The defect is possible because the `key_locks` owner FK in `004_change_ledger.sql:266-272` references only `owner_change_id`. The release helper is scope/base filtered (`004:446-470`), so a malformed cross-scope owned row could otherwise survive a successful terminal release. In several 027 paths the namespace-4 key was derived from request scope/base while rows were collected by owner ID. The guard aligns frozen owner rows with the selected record before relying on either behavior.

The disposable acceptance matrix now has `S13-KEY-LOCK-OWNER-SCOPE-01` in `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. It covers each mismatched field, bounded recovery batch atomicity, release cleanup, and plan mutation; all remain `NOT_RUN`.

## Paths and contracts

- `db/phase2/027_private_writer_admission_schema.sql`: owner-to-scope/base preflights in the five listed functions.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: source acceptance and disposable runtime cases.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: source observation and evidence boundary.

Candidate SHA-256 at this record: `DC131245550844B931E6FA1006195080E60EAD683E3A280D3CB8FACB352C4BA1`.

## Verification and limitations

- Source inspection: reviewed `claim_v1` around 6683-6765, `operator_resolve_v1` around 5560-5722, `release_claim_v1` around 7013-7077, `revoke_change_v1` around 7170-7254, `revoke_stale_v1` around 7305-7440, `retry_verify_v1` around 7640-7690, `operator_close_failed_verify_v1` around 11345-11415, T6c/T6r permit handling around 8307-8428, T5x around 8785-8845, and cancel around 9800-9885; all mismatch guards compare tenant, company, and base, and the relevant owner snapshots are rechecked after their namespace-6 fences.
- Qualification contract present: `S13-KEY-LOCK-OWNER-SCOPE-01`; execution is `NOT_RUN`.
- Independent review: an actual `code-reviewer` read-only pass reviewed the ten paths, this criterion, and this record. It found no code defect in scope and confirmed the source guards run before namespace-4/resource row locks. It identified the “five listed functions” wording, corrected here. The review did not run a SQL grammar parser, inspect effective grants, or verify runtime behavior; those remain `NOT_RUN`/`NOT_VERIFIED`.
- Runtime/parse/install/effective privileges: `NOT_RUN` / `NOT_VERIFIED`.
- Candidate remains uninstalled and ungranted. No production or remote-stack mutation occurred.
