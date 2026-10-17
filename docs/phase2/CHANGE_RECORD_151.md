# Change record 151 — freeze S13 checkpoint-tail classification rules

## Goal and changes

Resolve the known S12 checkpoint-tail ambiguities before implementing the S13 event reader/classifier.

- Updated `S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md` with the distinction between the inherited checkpoint schedule in S12 revision 6 §6 and superseding unknown-outcome behavior in Contract Freeze v2.0 §3.
- Recorded fail-closed interpretations for `RESOLVE_UNKNOWN`: `found=false` is T11 and requires a checkpoint; `found=true` is T12 under the frozen behavior and remains unready while triage/hold is active.
- Limited uncheckpointed T13 candidacy to `VERIFY_VERIFIED`, contingent on linked durable record and evidence validation. External observation reads are not ledger events; `EVIDENCE_RECORDED` and unspecified or inconsistent events remain unready.
- Updated the S13 acceptance map with the same rule so implementation and test acceptance use one interpretation.

## Evidence and limits

- Contract anchors: `S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md` revision 6 §6 and T10/T11/T12/T13 transitions; `S12_CONTRACT_FREEZE_V2_2026-10-16.md` §§3, 5–6; current event behavior in `db/phase2/004_change_ledger.sql`.
- This resolves local planning interpretation for a fail-closed classifier. It does not claim S13 runtime implementation, operational service integration, or formal gate acceptance.
- No source code, tests, migrations, database, or gate manifest changed. No tests or checks were run.
- The generated document registry was not refreshed because the S10 release handoff marks it as a machine-dependent navigation artifact, not release evidence.

## Acceptance and next action

- The accepted classification semantics and failure behavior are now explicit in both the lifecycle design and the story-to-evidence map.
- Next local code work: add a read-only scope-bound ordered event-suffix query and classifier that reconciles each eligible event with durable state/evidence; keep lifecycle status `NOT_READY` until the separate shared-fence, recovery and operational writer contracts are complete.
- After local coding is complete, functional-test-reviewer/e2e-runner own the mapped S13 tests; relevant database/security/reliability reviewers inspect the exact final code.

## Ownership

- The operator is accountable for delegated project closure; GPT/Codex executes the local interpretation and documentation work.
- The actual deployed writer/provider owner remains unidentified in canonical records.
