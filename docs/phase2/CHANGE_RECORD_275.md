# Change Record 275 — fail closed on legacy writer-epoch checks in S13 mode

## Ownership and state

- Date: 2026-10-25.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: S13 private-writer/ledger boundary; no individual maintainer is established.
- State: source guard implemented and manually reviewed; functional/runtime qualification is
  `NOT_RUN`.

## Change and reason

`SqlChangeLedger.lifecycle_writer_epoch()` now raises `S13_COM_ENTRY_GUARD_REQUIRED` before
`invoke()` whenever `private_writer_schema_enabled` is true. Its separate transaction cannot fence
a subsequent physical COM entry. S13 callers must use the process-bound one-way
`begin_com_entry` authorization path. When the S13 schema flag is false, the legacy query route and
its existing arguments are unchanged.

This is a source-level safety boundary. It does not prove installed PostgreSQL grants, an actual
COM entry, or the lifecycle/epoch race behavior.

## Evidence and limits

- Source: `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py:561-572`.
- Acceptance: `S13-LIFECYCLE-TRIGGER-CUTOVER-01` in
  `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.
- Actual focused `code-reviewer` follow-up: `/root/s14_value_binding_review`; it found no issue
  and confirmed refusal precedes `invoke()` while legacy behavior is retained. The collaboration
  result did not expose model/effort metadata; both are `NOT_EXPOSED`, not inferred.
- No test, check, build, CI, SQL operation, migration, database query, COM operation, stage,
  commit, or push was run for this change.

## Remaining acceptance and next step

The adapter change is reviewed at source level only. After S13 coding closes, the functional-test
owner must prove zero SQL/invoke calls in S13 mode and unchanged legacy routing, then the database
reviewer must qualify effective privileges and lifecycle serialization on the approved disposable
schema. Accountable owner: operator; executor: Codex; functional-test and database-reviewer roles
own their later evidence. No individual owner is assigned in canonical records.
