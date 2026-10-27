# Change Record 353 — fixes from the python and security review of 6ef051b

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `postgres_evidence_registrar.py`, `t16_recovery.py`, `private_ingress.py`, two new tests in `test_s13_evidence_provider_composition.py`, log entries.

## Changes

- `_log_unexpected` logs the exception class and innermost frame (file:line), never the message (security-reviewer LOW 1).
- T16 lookup and preparation failures are logged by class (python-reviewer MINOR 1).
- `authenticator.authenticate` unexpected errors return 503 `AUTHENTICATION_UNAVAILABLE` and are logged (security-reviewer LOW 4).
- The registration deadline is computed after the build re-read (python-reviewer MINOR 2); a timeout before a connection exists reports `outcome_unknown` false (MINOR 3).

## Open

- Retry policy of consumers of `EVIDENCE_REGISTER_UNAVAILABLE` is not in this repository scope and was not traced.
- No test of a maximum-size trust snapshot against the 8 MiB ceiling.
- No request-level test for the authenticator guard (the ingress has no tests).

## Verification state

- RUN: composition and T16 test files, 17 passed.
- NOT_RUN: full suite on this head (the full run in progress was started on 6ef051b), re-review.
