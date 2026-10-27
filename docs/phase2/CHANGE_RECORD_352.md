# Change Record 352 — trust snapshot source error mapping (review finding F6)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `postgres_evidence_trust.py`, the new `test_s13_trust_source_error_mapping.py` and log entries.

## Change

- P0001 errors are matched by exact `message` equality instead of a substring of `str(exc)`.
- Unexpected lookup errors and non-payload decoder exceptions are logged by class name.

## Verification state

- RUN: 2 new tests passed together with the WP5, composition and T16 test files.
- The near-miss test would fail on the old substring logic by inspection; no mutation run was made (operator rule).
- NOT_RUN: the barrier-ack lookup collapse noted in the review (its registrar already compares exactly; its trust module was not changed), review.
