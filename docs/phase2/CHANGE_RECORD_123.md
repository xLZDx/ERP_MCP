# Change record 123 — make writer reconciliation evidence immutable

## Finding

GPT review identified that writer reconciliation could replace a previously attached `DispatchReceipt` or `CompletionProof` before the incoming records had been fully validated. A later reconciliation result could therefore overwrite the original evidence, including with a different record identity or canonical content.

## Implementation

- Validate the complete incoming writer result, evidence types, attempt bindings, and configured signatures before mutating the ledger snapshot.
- Preserve any existing receipt and completion proof. An incoming record is accepted alongside existing evidence only when its identity and canonical serialized content are an exact match; exact repeats are idempotent.
- On conflicting evidence, retain the original snapshot and evidence, retain/reassert the base-wide hold, and reject the reconciliation with `RECONCILIATION_EVIDENCE_CONFLICT`.
- Continue to permit adding a previously absent evidence type after it has passed validation; this supports receipt-first reconciliation followed by its completion proof without replacing an existing record. A proof-only repeat is bound against the already stored receipt when one exists.
- Persist newly validated, nonconflicting partial evidence before outcome branching. A valid receipt without a completion proof therefore remains durably attached while the attempt transitions to `APPLY_UNKNOWN` and retains its hold.
- Invalid incoming evidence remains mutation-free; evidence is attached only after all supplied records pass type, binding, signature, and conflict validation.

## Affected contract

`InMemoryGovernedLedger.accept_writer_result` and its reconciliation entry point now enforce immutability for attached writer receipts and completion proofs. Conflicting or invalid evidence cannot overwrite the ledger's previous evidence. This remains an in-memory synthetic contract; it does not add persistence, a production trust registry, database enforcement, or real writer integration.

## Affected paths

- `src/business_ai_gateway/phase2/simulation/governed_write_v2.py`
- `docs/phase2/CHANGE_RECORD_123.md`
- `README.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md`
- `tests/phase2/test_s12_reconciliation_immutability.py`
- `tests/phase2/test_s12_reconciliation_immutability_e2e.py`

## Verification state

- `functional-test-reviewer` / GPT-6 Luna medium: `python tests/phase2/test_s12_reconciliation_immutability.py` — 7 passed, 0 failed, 0.494 s on the final focused test file. Includes reconstructed receipt and completion-proof objects with identical canonical fields but distinct object instances; reattachment preserves the stored originals and held `APPLY_UNKNOWN` state. Also covers new receipt identity, same identity with changed content, invalid signature, conflicting completion-proof identity/content, valid partial receipt retention, and proof-only repeat. Cases link to V2-S12-01/02/06/07.
- `e2e-runner` / GPT-6 Luna medium: `$env:PYTHONPATH='src'; python tests/phase2/test_s12_reconciliation_immutability_e2e.py` — 1 passed, 0 failed, 0.154 s. Covers consumed dispatch, held unknown, receipt retention, conflicting valid receipt rejection, exact reattachment, matching completion proof to `APPLIED`, and independent outcome to `VERIFIED`. Cases link to V2-S12-02/06/07.
- Both results are local in-memory synthetic evidence on the worktree based at HEAD `7c26c0c13999577e8840b1518229e59d52c8539c`, with the MAJOR-01 source remediation present but uncommitted. They do not establish PostgreSQL durability, 1C/COM behavior, formal S12/G8 passage, or production qualification.
- `code-reviewer` / GPT-6 Luna medium and `reliability-reviewer` / GPT-6 Luna medium independently reviewed the remediation and reported no BLOCKER/MAJOR. The code reviewer’s two MINOR notes were addressed: status text now reconciles passing results, and the test covers reconstructed equivalent evidence objects. Neither reviewer ran tests or established persistence, restart, concurrency, database, 1C/COM, S12, or G8 acceptance.
- No builds, database commands, or migrations were run for this change.

## Ownership and delivery

- Implementation: assigned implementation agent.
- Test authoring and execution: `functional-test-reviewer` and `e2e-runner` after all in-scope coding is complete.
- Independent review: code-reviewer and reliability-reviewer, GPT-6 Luna medium; no BLOCKER/MAJOR. Fresh exact-head GPT-PM approval remains required before push.
- This local change record travels with the remediation commit. Fresh exact-head GPT-PM review and approval remain required before push.
- The status reconciliation preserves G0–G8, S13 and production states from the manifest; it records the exact-head rejection and local remediation without treating either as gate passage.
