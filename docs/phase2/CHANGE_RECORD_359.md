# Change Record 359 — tests for the validation-path error mapping and the trust snapshot size

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers two tests added to `tests/phase2/test_s13_evidence_provider_composition.py`, the new
  `tests/phase2/test_s13_trust_snapshot_realistic_size.py` and the log entries. No source change.
- Closes two coverage gaps named by the GPT-PM push review and the security review.

## Tests

- `verify_and_store` with a real `CallIdentity`: an `OSError` raised while loading the attempt is reported as
  `EVIDENCE_REGISTER_UNAVAILABLE`; an `EvidenceAttemptSourceError` is still `EVIDENCE_REGISTER_VALIDATION_FAILED`
  (covers the transport-error mapping added in Change Record 349). The collaborators are immutable instances, so the
  test patches their methods on the classes.
- A snapshot with the maximum signer count (4200), four scopes and a rotation entry per signer decodes, and its
  compact JSON stays below 75% of the 8 MiB ceiling (about 4.4 MB measured). The synthetic data had to satisfy the
  snapshot invariants (valid signer role, rotation history referencing signers of the same snapshot, last entry equal
  to the current key), which also shows those invariants are enforced.

## Limits

- The snapshot shape is synthetic. A snapshot with many more scopes per signer can still exceed 8 MiB and then fails
  closed as `TRUST_SNAPSHOT_PAYLOAD_INVALID`; the per-signer scope cap of 4096 allows shapes far above the ceiling.
  The real expected scope count per signer is not known from the repository.

## Verification state

- RUN: composition file 16 passed; the new size test 1 passed; ruff F,E9 clean on both files.
- NOT_RUN: wider suite after this change, review.
