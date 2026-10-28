# Change Record 399 - GPT-PM fixes for the S12/S13 qualification batch

## Ownership and scope

- Date: 2026-10-28. GPT-PM rejected head a0393a4 (0 BLOCKER, 3 MAJOR, 4 MINOR). Fixes by the e2e-runner agent (tests and reports only; no source change); the coordinator ran no tests.

## Changes

- M-01 clone safety: `ct14_narrow_ops.prepare_user` persistently resets the password (random, in memory only) and role set of the disposable infobase user CT14_NARROW; this is now recorded as ONE authorized persistent mutation, not hidden behind "rolled-back transactions". A principal snapshot (names, flags, role names; never secrets) is taken before it and verified in a module finalizer: 78 infobase users before and after, none added or removed, every other user identical, CT14_NARROW holds exactly the two reviewed roles before and after, Users catalog 30 items before and after (the CT14_NARROW item pre-existed).
- M-02: E4 and E25 are PARTIAL at exit-scenario level (PASS only for the measured component/live-clone subset); PostgreSQL ledger integration, production content-hash/evidence derivation and production glue stay NOT_RUN/UNKNOWN. Scenario maps carry a status_note; no assertion weakened.
- M-03: a Contract status table in the amendment states PERIOD_CLOSED and GRANT_EXHAUSTED exist in the Python model only (SQL ledger still raises BUDGET_EXCEEDED; no parity test; no real period producer); no end-to-end claim.
- Minors: E41 wording (injected reply loss, real session loss NOT_RUN); period_closed/period_observed_open independence note; clone snapshot called a selected-field regression snapshot; slow SQL/e2e and S15 suites not rerun at this head, combined regression not claimed green.

## Evidence (agent-run, no mutation runs)

- 387 passed, 0 failed, 0 skipped (370 offline scenario file, 17 clone file incl. the principal-snapshot tests); ruff clean.
