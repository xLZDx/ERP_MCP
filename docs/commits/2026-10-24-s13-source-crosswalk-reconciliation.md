# Change record: Reconcile S13 source lock and replay crosswalks

## What changed

- Corrected the S13 source inventory's `begin_apply`/`record_call` row to distinguish current SQL from the additive intent/attempt candidate: legacy token-before-record locking, consumed-token replay without full identity comparison, `(change_id,generation)` permit/deadline keys, and the `PERMITTED → DISPATCHED` deadline trigger edge.
- Added qualification scenario `S13-BEGIN-APPLY-LOCK-CALL-ID-01` for candidate parent-before-token ordering, immutable call identity, abandoned-intent ID reservation, cross-scope reuse, and one linked attempt owning the existing S12 CAS.
- Mapped current `observe_target` and `record_evidence` replay behavior to the existing `S13-OBSERVE-REPLAY-01` and `S13-EVIDENCE-REPLAY-01` scenarios. Corrected the qualification matrix so it does not claim the current `observe_target` rejects changed stored tuples; it records the current conflict-skipped duplicate event and candidate-only refusal contract.
- Reconciled the grouped terminal/recovery source-map status with the per-function traces and recovery qualification, retaining the unresolved all-path competitor/trigger graph and `NOT_RUN` status.
- Updated the document index and lessons/backlog records, then regenerated the document registry.

## Why

The source inventory had summaries that no longer reflected its later detailed traces, and one
qualification row blurred current behavior with candidate expectations. S12/S13 qualification
needs exact source-derived negatives and must not describe an unobserved deadlock or an unimplemented
candidate behavior as current evidence.

## Affected contracts and paths

- `db/phase2/004_change_ledger.sql`, `005_change_registry.sql`, `006_change_sweeps.sql`, `007_change_hardening_a.sql`, `008_change_hardening_b.sql`, `019_ed25519_action_only.sql`, and candidate `027_private_writer_admission_schema.sql` were inspected read-only; no SQL file changed.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/DOCUMENT_INDEX.md`, `core/LESSONS_LOG.md`, `docs/phase2/OPERATOR_BACKLOG.md`, `governance/DOCUMENT_REGISTRY.md`

## Decisions and limits

- Namespace-6 advisory locks order conflicting plans; they do not establish uniqueness. The
  candidate durable call identity is reserved by the unique immutable dispatch intent and copied
  into its linked attempt.
- Current-source ordering and replay findings are static observations only. No runtime deadlock is
  claimed. Candidate behavior, S13 grants, database effects, and physical writer boundaries remain
  unqualified.
- No tests, checks, build, CI, migration, database write, COM call, stage, commit, or push ran.
  `node scripts/build_document_registry.mjs` regenerated the derived registry successfully
  (`459 tracked paths; 30 local-only paths`).

## Verification state

Source anchors were read directly from the named migration files and the resulting contract IDs were
checked in the qualification document index. The generated registry completed. Functional/E2E
qualification and independent database/runtime review remain `NOT_RUN` pending code completion.

The call-ID collision scenario was then strengthened from source review of the additive candidate:
`private_writer_assert_transaction_v1` requires `READ COMMITTED` (`027:1295-1304`), and
`change_ledger_begin_apply_v1` takes the namespace-6 call-ID lock before its collision queries and
before business-row DML (`027:2372-2407`). The scenario now forces a contender to wait behind a
committed intent and checks that its later statement sees the owner. No database execution was
performed; this remains a disposable qualification requirement.

## Independent source review

A fresh `database-reviewer` pass (GPT-6 Luna, low effort) found no source-level issue in the
cross-scope call-ID race contract. It confirmed the transaction guard, pre-query namespace-6
acquisition, READ COMMITTED post-fence statement snapshot, and `UNIQUE(call_id)` backstop in the
candidate source. The reviewer did not run SQL, database queries, tests, or checks; the behavior
remains unqualified at runtime.
