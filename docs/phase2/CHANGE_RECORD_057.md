# Change record 057 — author invocation-owned G1 crash and restore scenarios

## What changed

- Added a G1 scenario that observes an explicit PostgreSQL `COMMIT` waiting inside a test-only deferred trigger before terminating its backend; the scenario checks rollback, committed baseline survival and safe replay.
- Added a restore scenario across separately provisioned PostgreSQL clusters with recorded container/system identities and data, schema, security and continued-operation comparisons.
- Migrated the existing crash and restore scenarios in these files to invocation-owned disposable clusters, with ownership-checked operations and cleanup of owned containers and anonymous data volumes.
- Reconciled the G1 backlog, gate closure packet and simulation plan to distinguish authored source coverage from runtime evidence.
- Regenerated the Markdown document registry.

## Why

The existing crash tests killed a backend before the explicit `tx.commit()` call, while existing restore coverage targeted another database in the same cluster. Neither met G1's documented boundaries. The former shared-container harness could also affect a container not owned by the current test invocation.

## Contracts and paths

- `tests/phase2/_pg_harness.py`
- `tests/phase2/test_g1_crash.py`
- `tests/phase2/test_g1_restore.py`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`
- `docs/phase2/CHANGE_RECORD_057.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`

No migration, production path, external identity, key, source data, or gate state changed. G0 remains PASSED for its narrow prototype scope; G1–G8 remain NOT_PASSED; formal S13 entry remains NOT_APPROVED; Release 2 remains NO-GO; production authorization remains NONE.

## Verification state

- `e2e-runner` authored the scenarios. A read-only functional-test review found no remaining BLOCKER or MAJOR in the final reviewed changes.
- Runtime tests are `NOT_RUN`: `D:\Repo\AGENTS.md` explicitly prohibits pytest. No PostgreSQL container or database was started or changed.
- During the independent review, `git diff --check` was inadvertently invoked before coding was complete; it reported an LF-to-CRLF warning for `_pg_harness.py`. No tests, Docker operations, or database operations were performed by that reviewer.
- PM review and push are pending; exact-head runtime evidence is still required by the repository workflow before final GPT approval and push.
