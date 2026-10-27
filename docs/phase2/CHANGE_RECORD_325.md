# Change record 325 — S13 barrier acknowledgement production trust and replay path

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator by explicit delegation; executor: Codex.
- The checkout contained extensive staged, unstaged, and untracked work before this increment. Candidate migration 027 and several S13 modules were already present and dirty; this record describes only the barrier acknowledgement verifier/adapter increment and the current-turn trust-revision amendment.
- The ERP-MCP lane and Ivan stack were not contacted. No live business database, COM call, local or remote key access, service restart, stage, commit, or push occurred.

## Change

- Added `ProductionBarrierAcknowledgementVerifier` and typed trust-source/registrar ports. It validates canonical acknowledgement data, loads one authoritative non-cached PostgreSQL trust snapshot, checks the writer-receipt signer and independently attested completion supervisor over every organization represented by the barrier, verifies the exact Ed25519 acknowledgement and process-attestation messages, and persists only after those checks.
- Added PostgreSQL trust-snapshot and immutable acknowledgement-registry adapters with bounded transactions, identity checks, duplicate-key-safe bounded JSON decoding, rollback/connection termination on uncertain cleanup, exact record replay validation, and bounded registration. Runtime composition requires these concrete adapters to share a dedicated evidence pool distinct from the admission pool; it grants no SQL privileges.
- Added canonical composite-record JSON serialization and scoped trust-snapshot handling for up to 4,096 represented organizations.
- Candidate migration 027 now accepts the snapshot revision as a registration argument, takes the registry revision row `FOR SHARE` before its other locks, and compares that revision only after the exact prior tuple lookup. A changed/new record against a stale snapshot is refused; an exact prior immutable tuple remains replayable after later revocation/rotation. The candidate routine is still revoked by default.
- Fixed missing process-row and supervisor-key-row declarations in the candidate registration routine, found during source inspection and independent database review.
- The registrar now surfaces the definite stale-revision refusal separately. The verifier rechecks durable exact replay before at most one bounded refresh-and-retry, so a concurrent exact winner can still be observed after a trust change.
- Added the source-level design addendum in `S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`.

## Source identity and verification state

Current SHA-256 values:

| File | SHA-256 |
|---|---|
| `src/erp_mcp_private_writer/barrier_ack_verifier.py` | `C0D959405ACB272207ECA2545BF1B17760CF69D77FB59E455D4272579DD13757` |
| `src/erp_mcp_private_writer/postgres_barrier_ack_registrar.py` | `48902B845BEA047D9922129A81ECEDB89BF4B6268D8544F3929898AC3020C17D` |
| `src/erp_mcp_private_writer/postgres_barrier_ack_trust.py` | `01BB825A4A02986DF71B8C0C9FEC2BFF0B6F893CCCACEC5603BF26D04BC8E142` |
| `src/erp_mcp_private_writer/barrier_ack_protocol.py` | `41E48AAB4C15D8BBA25AED736F80036E9935215C0B8BA58A92FC4AAB05781A26` |
| `src/erp_mcp_private_writer/postgres_evidence_trust.py` | `88B6DB6772C49D31CF1686678A9FD6448A8644AD5C94BB96DBC442356BB1379C` |
| `src/erp_mcp_private_writer/runtime_composition.py` | `E2CB00CE9F07720BAF0FB69F9935A623D9E8E903D905F491A3C2B120EEB0A0F1` |
| `src/erp_mcp_private_writer/__init__.py` | `CD7F3690D3E31675F3F0C2D515CCA0815F20397A676129B834957250AB571F18` |
| `db/phase2/027_private_writer_admission_schema.sql` | `6EB879C79979A441F936260072DC56D003799E96E37CC4AA5E87767E39BC42C7` |

Read-only database and Python role reviews of the focused acknowledgement slice found one
compile-blocking missing SQL row declarations; Codex added them, and the database review confirmed
the supervisor-key declaration by source inspection. Both reviews found no further actionable issue
after the stale-revision retry change. Review model/effort details were not exposed by the agent launch
metadata. These reviews did not parse or execute the SQL and do not qualify installed grants or
runtime behavior.

The S13 candidate migration was applied only in the fresh disposable PostgreSQL 16 qualification below; that exact dirty-worktree SQL parsed and the listed SQL assertions passed. Configured lane grants, full S13 disposable acceptance, real multi-transaction concurrent trust-writer serialization, Ivan clone behavior, and an operational 1C writer remain `NOT_VERIFIED` / `NOT_RUN`. No production boundary is enabled by this code.

## Focused qualification on the current dirty candidate

- `e2e-runner` added `tests/phase2/test_s13_barrier_ack_service_e2e.py`; `uv run pytest -q tests/phase2/test_s13_barrier_ack_service_e2e.py` returned **4 passed in 0.90 s**. It covers admission closure, production verifier signature/process-attestation checks, exact lost-response replay, stale epoch, and changed-tuple refusal through `PrivateWriterService`, with in-memory store/writer/trust/registry ports. It does not exercise a real COM, PostgreSQL, 1C, or production service.
- `functional-test-reviewer` added `tests/phase2/test_s13_barrier_ack_verifier.py` and `tests/phase2/test_s13_barrier_ack_sql.py`. `uv run pytest -q tests/phase2/test_s13_barrier_ack_verifier.py` returned **7 passed with 7 parameter subtests in 1.37 s**. It covers valid signature and independent supervisor attestation, scope/process/signature negatives before registration, exact replay after simulated revocation, one lookup-before-refresh stale-revision retry, concurrent exact-winner replay, bounded second-stale refusal, and timeout/cancellation after durable registration.
- `uv run pytest -q tests/phase2/test_s13_barrier_ack_sql.py` returned **2 passed in 20.29 s**. The module applied the candidate SQL in fresh invocation-owned `postgres:16` container/database resources and checked candidate routine existence, source lock order, exact-replay-before-stale-refusal order, and no effective `EXECUTE` privilege for `PUBLIC`, `private_writer_evidence_ingest`, or `business_ai_private_writer` on the acknowledgement register/lookup/trust-loader routines. The fixture verified its own container/database ownership and completed cleanup without error.
- The first Python attempt exposed a fixture signer-key mismatch and the first SQL attempt exposed spacing-sensitive assertions; the test owners corrected their test code, and the final exact commands above passed. No product-source defect was reported by the final runs.

| Test file | SHA-256 |
|---|---|
| `tests/phase2/test_s13_barrier_ack_service_e2e.py` | `90D6B61566365A17D0AE5336963C755CCD458FD39EA0A2A3E6B2115B9CB36337` |
| `tests/phase2/test_s13_barrier_ack_verifier.py` | `401974BF3366D425E215E5E852B240E1252C50D9C849035A99EF2A4908934E86` |
| `tests/phase2/test_s13_barrier_ack_sql.py` | `82C1A7342DA417F290A10AA9336BF114D0A77294F256074AA53907005183392A` |

These focused results prove only the named behavior and SQL candidate checks on the exact dirty worktree contents identified above. They do not measure configured lane grants, qualify the full S12/S13 case matrix or every S13 mutation route, prove inter-transaction concurrency/deadlock outcomes, or establish Ivan clone COM access or a production writer boundary. Files remain unstaged and uncommitted.

## Remaining acceptance and next action

- Codex: finish the accepted S13 source-closure queue, then assign the exact acknowledgement/registry cases to `functional-test-reviewer` and `e2e-runner` for disposable qualification and launch relevant independent database, security, and Python reviews.
- Operator: provide or authorize the licensed Ivan clone identity, registry scope, and trust material path before any real COM writer/key provisioning. This code does not supply that evidence.
- GPT-PM: adjudicate the final exact-head architecture/contract after code, mapped test evidence, and specialist findings are ready. No approval or push is claimed here.
- The repo remains dirty; this change was not staged, committed, pushed, or merged.
