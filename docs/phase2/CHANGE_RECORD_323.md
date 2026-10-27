# Change record 323 — S13 barrier acknowledgement replay and adapter bridge reachability

## Ownership and baseline

- Date: 2026-10-26.
- Accountable owner: operator, by explicit delegation; executor: Codex.
- The checkout already contained dirty `service.py`, `sql_ledger.py`, and an untracked candidate
  migration 027 before this turn. This record describes only the current-turn changes listed below;
  it does not claim ownership of their earlier contents.
- Codex changed the barrier acknowledgement result contract in `service.py`, added the narrow
  `claim_with_id_v1` bridge and grant to the pre-existing candidate migration, and routed selected
  flag-on adapter methods through existing granted candidate bridges.
- The functional-test-reviewer authored the in-memory service test module; the e2e-runner authored
  the disposable adapter test. Neither agent edited product source. No Git staging, commit, or push
  was performed. No configured database, COM session, business record, secret, key, or service was
  accessed or changed.

## Changes and rationale

1. `src/erp_mcp_private_writer/service.py` now distinguishes an explicit
   `BarrierAcknowledgementRejected` (proven invalid before durable acknowledgement storage) from
   ambiguous verifier outcomes. Timeout, cancellation, other exceptions, and malformed returned
   references produce `BARRIER_ACK_VERIFY_UNKNOWN` with `outcome_unknown=True`; the barrier stays
   closed until a retry by the same barrier ID resolves the immutable stored reference.
2. Candidate migration `db/phase2/027_private_writer_admission_schema.sql` adds
   `claim_with_id_v1`, a `ledger_owner`-owned `SECURITY DEFINER` bridge with fixed
   `pg_catalog,pg_temp` search path. It passes the adapter's preallocated token UUID to `claim_v1`.
   The final ACL explicitly revokes `PUBLIC`, all seven application roles, and both private service
   roles before granting only `requester_role` EXECUTE on this bridge; candidate `claim_v1` and
   `release_claim_v1` remain directly revoked. Existing `claim`/`release_claim` bridges retain
   their established runtime ACL boundaries.
3. `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py` routes flag-on `propose` and
   `validate` through their preserved candidate SECURITY DEFINER bridges, claim through
   `claim_with_id_v1`, and release through the preserved `release_claim` bridge. This avoids an
   adapter permission failure before the authorized body while keeping direct versioned entry
   points unavailable to runtime roles.

## Verification evidence

- Functional-test-reviewer ran
  `uv run pytest -q tests/phase2/test_private_writer_barrier_ack.py` — **5 passed in 1.61 s**.
  Test SHA-256: `EC0457A892B50CE4C5B9E3011ABE91EC4A190DBE318579E4C4E00ACC98F57A6B`; service SHA-256:
  `ACA2364F4F2F9C9D3017ECD46A4FDC94EE5ACEC4804E7062C061263F12DDECB7`. The tests use in-memory
  fakes and cover definitive typed rejection, lost response after durable store and exact retry,
  malformed returned reference, timeout after persistence, and cancellation after persistence.
  They do not exercise PostgreSQL or COM.
- E2E-runner ran
  `uv run pytest -q -s tests/phase2/test_s13_adapter_claim_release_bridge_e2e.py` — **1 passed in
  48.52 s**. Test SHA-256: `71F3A0BE062EE7CB0FC46C3D99DE4EA8C083AAE6C5F6609121D6098F1FAA7793`; current
  migration SHA-256: `DF9FA08F6583022251428BFBA226AFDE698ED88B184666798FE0FC418EA1D893`; adapter SHA-256:
  `024C910860853CB8B5A588D23F15528563CE0335D2343E70BDE44A83ABDAA74B`. It verifies the
  preallocated token UUID, flag-on claim/release path, and direct-versioned-function denial for the
  requester role on an invocation-owned disposable PostgreSQL 16 cluster. Container
  `r2-s13-dump-3bd3680af1c0-a` had its ownership label verified and exact-name inspection confirmed
  absence after teardown. Monitoring also observed `r2-s13-dump-09c465698c0f-a`; its owner and
  purpose were not established, it was not touched, and it is not attributed to this run. An earlier
  attempt stopped at fixture collection (`owned_cluster_dsn` unavailable) before creating a
  container; the fixture wiring was corrected, and only successful reruns are runtime evidence.
- A fresh reliability-reviewer inspected the exact service/test hashes above and found no actionable
  finding in the touched behavior. It notes that the concrete `BarrierAcknowledgementVerifier`
  implementation is absent from `src/`; therefore the typed “proven pre-durable rejection” guarantee
  still needs an implementation/runtime provider before service enablement.
- A fresh code-reviewer found no actionable issue in adapter routing or the claim/release E2E test.
  It confirmed there is no fallback when flag-on and identified that proposal/validation bridge
  mapping has source evidence but is not behaviorally exercised by the current E2E module.
- The database-reviewer initially found one MINOR: the new bridge depended on default ACL cleanup
  rather than explicitly revoking every named role. Codex added the all-role `REVOKE` before the
  sole requester grant. A read-only exact-hash follow-up on migration SHA-256
  `DF9FA08F6583022251428BFBA226AFDE698ED88B184666798FE0FC418EA1D893` confirmed the finding closed
  and found no other grant-path issue in the reviewed wrapper. The review did not query a database,
  parse/apply the migration, or run tests; installed effective grants remain unverified.

## Remaining acceptance

- The in-memory verifier fake does not prove durable PostgreSQL registry behavior or production
  certificate verification. The adapter E2E proves only the bounded claim/release bridge path on a
  disposable schema; it does not qualify all 54 S13 mutation APIs, races, stale-plan cases, installed
  database grants, restore/dump skew, or the actual 1C writer transaction boundary.
- Owner: Codex for source reconciliation and disposable qualification; the functional-test-reviewer
  and e2e-runner own required tests; GPT-PM owns independent contract adjudication when requested.
- Next: reconcile the exact bridge routes and grants against the complete S13 API matrix, then
  continue mapped disposable scenarios and specialist reviews. Do not infer configured-lane or
  Ivan COM acceptance from these tests.
- Add a focused disposable case for flag-on proposal and validation through the preserved bridges;
  this is recommended by the code review and remains NOT_RUN. Also implement and qualify the
  concrete acknowledgement verifier rather than relying indefinitely on the injectable protocol.
