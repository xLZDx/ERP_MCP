# Change Record 280 — pre-fence the VERIFY counter identity

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP change-ledger verification/recovery boundary.
- State: source-only candidate; SQL parse, migration, database operation, tests, checks, build, CI, staging, commit and push were not run.

## Baseline and change

Migration 027 and the S12/S13 prerequisite file were already untracked before this turn. At the start of this slice their SHA-256 values were migration 027 `139A7120F64FE97C44BEA112A27255A0B672D6604DFC54622318DAD845084686` and qualification prerequisites `B78DB301B4A2F4092F2D6C04A2F79F7AC5BC60A63AB0C138515FE8E83CA07713`.

`verify_inconclusive_v1` already checked global evidence ownership before locking the record, but its namespace-6 plan omitted the global `(subject_id, kind='VERIFY')` counter identity even though it later inserts/locks/updates that unique counter row. Both the new-attempt and exact-replay branches now precompute and include `sweep-counter:v1:<lowercase-change-uuid>:VERIFY` alongside the record/evidence/hold identities before any relation-row lock. The shared helper retains sorted/deduplicated acquisition of actual signed hash keys. The qualification prerequisite now explicitly requires observing this counter fence before the record lock in both branches.

## Affected paths and evidence

- `db/phase2/027_private_writer_admission_schema.sql`: `verify_inconclusive_v1`, namespace-6 set near lines 10445–10465.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `S13-COUNTER-RANK-01` names the candidate and both branches.
- Source contract: the same acceptance maps `sweep-counter:v1:<uuid>:<kind>` as a namespace-6 identity that must precede business-row locking.
- A focused read-only `database-reviewer` pass found no BLOCKER/MAJOR: both new-attempt and exact-replay paths include the VERIFY counter key before `records FOR UPDATE`, matching existing VERIFY recovery key spelling. Model/effort metadata: `UNKNOWN`. This is source ordering only.
- SHA-256 at this record snapshot: migration 027 `473C507119CCB5771F1890B1FC25A4C076E5C1B99AD3516A76A224BE8098A64C`; qualification prerequisites `478E58882FFE24A0E944177C7E1054BE720A10567EA31F95BFC51A03FB334A1C`.

## Limits and next action

This closes only the source-level omission in this candidate's VERIFY counter fence. It does not prove installed ACLs, SQL validity, lock behavior, event order or runtime semantics. Next, continue source-level lock/trigger/FK/effect closure; after coding closes, functional/E2E roles must qualify the new attempt and exact-replay lock order on the approved disposable schema.
