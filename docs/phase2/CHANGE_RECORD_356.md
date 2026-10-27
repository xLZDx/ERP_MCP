# Change Record 356 — ingress body-level tests

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers four additional tests in `tests/phase2/test_s13_private_ingress_boundary.py` and log entries. No source change.

## Tests

- Malformed JSON, an unknown field and a duplicate JSON key: 400 `INVALID_REQUEST` on both `/v1/calls/dispatch` and `/v1/calls/lookup`.
- Body of 1 MiB + 1 byte: 413 `REQUEST_TOO_LARGE`.

## Verification state

- RUN: 7 passed in the file. NOT_RUN: authorizer branches and a full valid dispatch (need real ticket and permit values), review.
