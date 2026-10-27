# Change record 175 — T16 witness cosign for entered conditional conflict

## Scope and reason

The accepted S13 operator-resolution design allows `APPLY_UNKNOWN` to reach T16 only after an
entered conditional-conflict receipt and a matching CompletionProof are established. The existing
`witness_cosign_signed_v1` candidate accepted only `TRIAGE_REQUIRED`, so the conditional-conflict
branch had no way to collect its independent witness cosign before the later evidence-bound
`operator_resolve_v1` transition.

## Changes

- Extended `witness_cosign_signed_v1` for a new `APPLY_UNKNOWN` cosign only when the current
  generation has a `DISPATCHED` permit, its unique call/dispatch-CAS attempt is still
  `POSSIBLY_EXECUTING`, a same-attempt receipt proves `ENTERED` and
  `CONDITIONAL_VERSION_CONFLICT`, and the attempt-linked private CompletionProof projection points
  to the exact public completion-evidence ID.
- Added namespace-6 identities for call, dispatch CAS, receipt reference and completion reference.
  After ranked fences, the path locks and revalidates the complete record, permit, attempt and open
  call-hold snapshots in parent-first order before inserting only the cosign row.
- Preserved lookup-only exact replay after cosign consumption. The conditional branch does not
  append an event, terminalize the record, consume the cosign, or change reservations, holds or
  physical resources.
- Updated the S13 implementation design and disposable qualification prerequisites with the
  witness-admission contract and race cases. The route remains ungranted.

## Decisions and boundaries

- The witness signature alone proves neither absence of an effect nor permission to release the
  writer slot. Only the future `operator_resolve_v1` path may terminalize, after independently
  validating OutcomeEvidenceV3, post-completion challenge, process-attested read attestation and
  T16 signer constraints.
- Public CompletionProof classes (`a`/`b`) and the private-writer projection classes are distinct
  enums; the immutable evidence ID and same-attempt/CAS links provide their cross-boundary binding.

## Verification state

- Actual read-only `database-reviewer` review of this source slice found no concrete BLOCKER/MAJOR.
  The reviewer also confirmed that removing a comparison between the two unrelated class enums
  leaves the immutable ID and same-attempt/CAS checks intact. Model: GPT-6 Luna; effort: medium.
- Source review only. No SQL parser, test/check, migration, database operation, COM call, staging,
  commit or push was performed. `S13-WITNESS-COSIGN-REPLAY-01` remains `NOT_RUN`; deployed grants,
  lock races and the later `operator_resolve_v1` path remain `NOT_VERIFIED` / incomplete.
- Current full-file SHA-256 values (migration and adapter include pre-existing changes from prior
  turns): migration 027 `98E7EF08A574B06AAD19FCF028D1D19A9792873ACCECE2E2E9AC597B6C866631`;
  `sql_ledger.py` `80090397096F7085A88C09C9CF2ABA49BCF6D4B164EF3F5E9BE60E8C8A5AF509`;
  S13 design `D8C215FE3E0CA270A009F33C6C1645D5B67EC3448903531FFF93FCD9C823F1BA`;
  qualification prerequisites `D9F6E8B905342024EB9A8B215B1782E05181C2AAC88A6836E5466B5CF709DB0D`.
- Accountable task owner: operator; executor: Codex. The canonical technical owner for installed
  PostgreSQL grants is not established by this source-only change.
