# Change Record 348 — evidence registrar cancellation safety and error logging

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `postgres_evidence_registrar.py`, `test_s13_evidence_provider_composition.py`, log entries.

## Source: silent-failure review of HEAD f06fa2d (6 findings)

- F1 MAJOR (fixed): outer cancellation during INSERT/COMMIT skipped rollback and outcome reporting. `_register_on_connection` now terminates the connection and re-raises on `CancelledError`.
- F3 MINOR (partly fixed): unexpected errors are logged by class (message only for NameError/AttributeError/TypeError) before translation; the error codes are unchanged.
- OPEN backlog, needs a contract decision because error codes change: F2 MAJOR (validation path maps infrastructure or programming errors to `EVIDENCE_REGISTER_VALIDATION_FAILED`, `postgres_evidence_registrar.py` ~171 and ~226), F4 (T16 recovery coordinator maps all errors to outcome unknown), F5 (ingress 503 after successful dispatch on serialization failure), F6 (trust snapshot and barrier-ack lookup collapse programming errors into transport or payload codes).

## Verification state

- RUN: composition file 12 passed, including the new cancellation test.
- NOT_RUN: full suite, review of this change.
