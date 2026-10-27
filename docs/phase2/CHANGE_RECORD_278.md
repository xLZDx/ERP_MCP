# Change Record 278 — allocate one bounded aggregate recovery batch

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP change-ledger recovery boundary; reviewers/test roles are execution roles.
- State: source-only implementation; no SQL parse, migration, database operation, test, check, build, CI, staging, commit, or push was run.

## Baseline and change

Before editing, both SQL migration 027 and the disposable-qualification prerequisite file were already untracked in the worktree. Their initial SHA-256 values were respectively `9DF1535F38F6FF9AD8C4FD62DD9DAA639232FFEC7433ABC5520F6811325C645A` and `9608A5EE41635A07C0BD4F8D23845350E266DFBED684B91C95427F63EC0169AD`. This turn changed only the combined recovery selector in the pre-existing SQL candidate and added one qualification scenario; the rest of each untracked file remains inherited work.

The combined T3, T9, REVOKE-only VOID, and expired-nonce selectors previously each used the configured `batch_size`, then rejected an aggregate exceeding 66 items or 200 weighted row effects. A persistent queue with enough work in multiple stages could therefore select the same oversized set and refuse before DML on every run. The selectors now consume a shared 66-item budget and a shared effect budget initialized to `200 - 1` for the run row, minus the existing two-row reserve for deferred kill-switch recovery. Each stage decrements the remaining budget using its established upper bound: three row effects for T3/VOID, four for T9, and one for a nonce. Stage order is unchanged, and the existing pre-DML count assertions remain as fail-closed guards.

The acceptance prerequisite `S13-RECOVERY-AGGREGATE-BUDGET-01` requires an over-cap mixed-stage fixture to make bounded progress and drain across repeated direct recovery runs. While work remains, deferred `kill_switch(OFF)` must atomically refuse with `RECOVERY_NOT_READY` and no state/event/run-row delta; it may turn OFF only after direct recovery drains eligible and unresolved work. This preserves the separate stop contract. It remains `NOT_RUN`.

## Affected paths and evidence

- `db/phase2/027_private_writer_admission_schema.sql`: shared item/effect budgets and per-stage limits at lines 9081, 9257–9364.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: new aggregate-budget acceptance at line 318.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: source-state correction for aggregate selection progress.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` and `docs/phase2/OPERATOR_BACKLOG.md`: append this source change and the deferred qualification queue.
- Source basis: existing selectors at migration 027 lines 9256–9364 and the prior per-stage limits/effect assertion; acceptance map `S13-RECOVERY-ROWS-01` and `S13-RECOVERY-QUIESCENT-RUN-01`.
- Snapshot SHA-256 after Change Record 278's acceptance-contract correction: migration 027 `D52C7497A5AB07B51E66FBF7AF2291627C507A6ECAD3918BEE011CA86F208BCB`; qualification prerequisites `794A6D03B40957422EB84C1FEE49908D4D644BDC180D8909C4EC5F958E4D9ECF`. Later edits to both files are recorded separately in `CHANGE_RECORD_279.md`.

## Limits and next action

This closes only the no-progress defect caused by independently applying per-stage caps before enforcing aggregate item/effect limits. T9 hold fan-out and the actual frozen write-set still retain their separate row-count and stale-plan guards; oversized or ambiguous plans continue to fail closed. The candidate migration remains unparsed, uninstalled, and ungranted, and no effective privilege or PostgreSQL behavior is established. Next, finish the remaining source lock/FK/trigger/effect closure, then have the designated database reviewer and functional/E2E roles qualify the exact aggregate-budget and recovery cases on the approved disposable database.
