# Change Record 350 — T16 recovery error mapping (review finding F4)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `t16_recovery.py`, the new `test_s13_t16_recovery_error_mapping.py` and log entries.

## Change

- `UUID(identity.change_id)` is computed before the gate try block; failure raises `T16_CHANGE_ID_INVALID` with outcome_unknown false and the gate is not called.
- `ServiceError` from the gate and from S13 terminalization propagates its code and flag. Other errors keep the conservative OUTCOME_UNKNOWN codes and are logged by class name only.

## Verification state

- RUN: 3 new tests passed. NOT_RUN: wider suite after this change, review.
- Open from Change Record 348: F5 (ingress) and F6 (trust and barrier-ack lookup).
