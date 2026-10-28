# Change Record 388 - S15 source fixes from three specialist reviews

## Ownership and scope

- Date: 2026-10-28. Source fixed by the implementation-engineer agent; committed by the coordinator. Follows CR-386 and CR-387.
- Reviews: silent-failure-hunter (2 MAJOR, 8 MINOR), reliability-reviewer (4 MAJOR, 2 MINOR), code-reviewer (1 MAJOR, 6 MINOR); no BLOCKER.

## Changes (src/erp_mcp_s15/)

- reconcile: closed ledger status set; unknown status, PENDING with a marked document, duplicate ledger ids, empty hashes and
  found-by-marker without ledger resolution are DIRTY; malformed elements and any internal failure are INCONCLUSIVE with a reason.
- Apply gate: restore epoch so a stale report cannot unblock, CLEAN expires after a required max age, strict-bool writer flag
  (anything but False means enabled), serialized runs, injected monotonic clock, retry interval, start(), status accessor, lookup cap.
- verifier/oracle: empty expected markers and identity text are red, strict own-date validation, strict bool reference lookups,
  READ_ERROR code with per-check isolation, typing check recorded and incomplete declaration gives PARTIAL_UNVERIFIED.
- ab_compare: item validation; balance items documented as deltas. negative_controls: required-set coverage in all_detected.

## Verification state

- Agent: ruff clean and a smoke run only. Existing tests that pin the old behaviour are expected to fail until the test agent adapts them
  (CR-389). Re-review and GPT-PM review: NOT_RUN. Writer stays UNQUALIFIED and disabled; nothing wired.
