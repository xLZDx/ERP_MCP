# S13 disposable PostgreSQL qualification report — 2026-10-28

Scope: work packages 3 and 4 (migration chain 001-027, effective-grants matrix, every PostgreSQL-backed S12/S13 test). This is local evidence on a disposable instance. It does not change any gate, does not make S13 entry or Release 2 decisions, and covers no 1C clone, no external anchor/provider, and no production key custody.

Suite: **PASS with qualifications** (all product tests green; 13 pytest collection errors are a runner mismatch, the same tests pass when run as their own scripts; 2 environment failures cleared on rerun with the correctly named container).

## 1. Environment identity

| Item | Value |
|---|---|
| Qualification container | `s13-qual-a9870afd`, id `a3e4935a3d55834bd5d08805fa6462de7ebe87fdab7cc2934416daa26e4f7ab5`, `--rm`, bound to 127.0.0.1 on a random port, label `s13.qual.owner` |
| Image / server | `postgres:16.14`; PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1) x86_64 |
| system_identifier | 7701773942855077926 |
| Database | `s13_qual_chain` (oid 16388) |
| Not used | `erp-pr23-e2e-*`, `erpmcp-e2e-*`, port 18432 lane, the other agent's `r2-s13-dump-4798df6df719-a` |
| Harness-owned clusters | The repo harness (`tests/phase2/_pg_harness.py`) provisions its own label-verified, `--rm --volumes` containers named `r2-s13-dump-<token>-a` for cluster-style tests (about 20 over the run, each removed by the harness). Two guards (`test_change_ledger_dump_restore.py`, `test_g1_capacity_smoke.py`) accept only a container named `r2-s13-dump-*`; for those I started two further own containers `r2-s13-dump-qa9870afd` and `r2-s13-dump-qa9870afdb` and removed them. |

Migrations were applied in order with the repo harness approach (`set_config('living.migration_checksum', sha256)` then the file text), 27 of 27 APPLIED:

| # | SHA-256 |
|---|---|
| 001 | d8c9d4a5a9d5f52a6e88dc31414dca02678f262e75748d596374ddcf04e7d0cf |
| 002 | 74776d7f165a25288ef6cfbfa5a4decbc470260d671f265c2a51dd74ad36a138 |
| 003 | 294d24d6c7981697c3f3336e603137edada46f5caae9e6ff672141b044854c9f |
| 004 | 6b7e1efa11f43e39648051b8184de2a97ad8ef2b578aba696af658253bed7340 |
| 005 | 99522e7ca803f5972c88588069e0408af3a51a60340fd34da26cc02eb23d1373 |
| 006 | dd147300993ca1d5db4680ab013069b4ce59879e670120cd930a2d155ac05de9 |
| 007 | 91434b315e5586e656a633e101783800559e6a299bd21187feaa5629fdb43c86 |
| 008 | 5812a7c72afe7ddab9f29d1b1ba02ad3e8a1ea14f6c7c0dfeff2cd671c70c8e9 |
| 009 | 68af5fd28aec77dd14d83a108979733d14fa592afba7b459a7e7ff524c981ef8 |
| 010 | 31dd17112a22b17128ca5fa4cf77250ca864f75bf2840326b32e69a6ddc73b0f |
| 011 | b9e11476b8bd5119bcb4d0beb96290a6f150fbab4898e94d14cc396ac9f28842 |
| 012 | a6c5680b85a49b648e4fdaad7014825441f8e59a4b0f44ca590e2d39c2a3c9c9 |
| 013 | 4a0c7a5ce3467809467f8cf619cea6334c851e82503035beb7ffd60444ec62aa |
| 014 | db96004c9c6fbc7a4ab9000b84af33a76a74ef8bde0d18966b76005219919afe |
| 015 | 11f9ee2c887af23c6983778b6134edad4c376bf0e508d5776cf69684d70036e6 |
| 016 | f9b0a1e9d5ec4d3f7d8365b11f226d37a6f9eafc896c47d9fd759d8f9f8ac11e |
| 017 | 732bbb6d841f2cf3e5fc57504cc7925b778185b44167841986f7c6ec5b3b8f83 |
| 018 | c3a081ed0e1fcc7b0b68dac98d914070fe5cd72645d1691d66c3999c65ccd154 |
| 019 | 1662f8ca4d7ecc7641473d1cfdc0b27f47d3fdcdeb4fa2260d82a0885bf97904 |
| 020 | ab9337ec9fd8b56d612d916be50af4be6a0be1a5e8ba3b70cbb52884f7e3c9cc |
| 021 | fa8dc4c8dcc14d4aacb30faf1866d7dbe0624af3eba720adc71bb3c124e7b70c |
| 022 | 9af22ec1291474a13031cd9ad928980e9af8b81e01c806b998d5f2317c566acc |
| 023 | 5cda75adb082eaf2e71f0acb9f0def18fb2374c9245e9613186d53ddbad19381 |
| 024 | 96ac22e6d207ca1d7c6069625cfa3738c0e9346907daf95855ec6bf7c531dea2 |
| 025 | 8fe3ebb50ac9a27261c0d692c812a27988ede9990bb4a4c635259fd47c1d709d |
| 026 | 217b99df9f13570f0f0275bc9aa4e181ba8609ccede77a6bf47ec252e4cdfb81 |
| 027 | d60423aafb89ca3f7d4c9e0b8b48e563a083550162df7c710b2fe45690a0b90b |

Applying 027 a second time on the finished chain: CLEAN (no error); a before/after catalog snapshot (function count 331, relation count 235, function ACL digest, table ACL digest, role attribute digest) was identical. Limit: this proves idempotent re-application on an empty-data chain, not on a populated ledger.

## 2. Effective grants (artifact)

`docs/phase2/artifacts/S13_PG_GRANTS_MATRIX_2026-10-28.json` (no secrets). Each role was assumed with `SET LOCAL ROLE` and checked via `has_function_privilege/has_table_privilege/has_schema_privilege(current_user, ...)`, so the values are the role's effective rights (inherited memberships and PUBLIC included), never the owner's. Login roles were not connected with their own credentials (no passwords provisioned in the disposable instance); `SET ROLE` is the stated method.

Facts from the artifact:
- 331 functions (295 `change_ledger`, 36 `living`); 57 `private_writer_*` functions, all `SECURITY DEFINER`, all owned by `ledger_owner`, all with a pinned `search_path`.
- PUBLIC EXECUTE: 0 functions. PUBLIC USAGE on `change_ledger` and `living`: none. PUBLIC table/sequence privileges: none.
- No assumed role is `rolsuper` or `rolbypassrls`; none holds direct INSERT/UPDATE/DELETE/TRUNCATE on any `change_ledger` or `living` table. Direct role memberships among the 14 checked roles: none.
- `add_role_scope` (both schemas): not executable by any checked runtime role.
- `business_ai_private_writer` (login): 13 private-writer entry points executable (admit, mark_invoking, begin_com_entry, record_terminal, record_verified_success, attach_recovered_receipt, record_recovered_not_invoked, record_recovered_terminal, close_and_advance, finish_barrier, lookup, lookup_barrier, startup_recovery_state); no table privileges.
- `private_writer_evidence_ingest` (login): zero EXECUTE on any function and zero table privileges. Observation, not asserted as a defect: it cannot call `private_writer_register_evidence_v1` either, consistent with the design statement that the production validator identity does not exist yet. Evidence registration is therefore not exercisable through this role.
- `worker_role`: `private_writer_issue_permit_v1`, `..._permit_binding_for_intent_v1`, `..._dispatch_intent_for_call_v1`; requester and writer roles: `..._dispatch_intent_for_call_v1`. Others: none.
- RLS: 71 relations with row security enabled, 118 policies.
- Not captured: row-level checks as the real login roles over a network connection, client-certificate to `session_user` binding (needs the certificate configuration), column-level ACLs.

## 3. Test runs

Environment variables used: `ERP_PHASE2_REQUIRE_PG=1` (a missing database fails instead of skipping), `ERP_PHASE2_TEST_DSN` (batch A, my container), `ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1`, `ERP_PHASE2_TEST_IMAGE=postgres:16.14`, `ERP_PHASE2_DOCKER` (batches B and scripts). Repo head: `7ccfee8` plus working-tree docs; the working tree was not modified by the tests. Skips: 0 in every run.

Batch A, DSN-backed, one pytest process (`.venv\Scripts\python.exe -m pytest <23 files> -rA -q`, 1220.7 s): 957 passed, 2 failed.

| File | Result |
|---|---|
| test_change_approval_digest2 | 23 pass |
| test_change_hardening_b / b2 / b3 | 14 / 13 / 26 pass |
| test_change_hardening_c / d / e / f / g / h / i | 16 / 17 / 17 / 11 / 9 / 7 / 4 pass |
| test_change_ledger_sql | 69 pass |
| test_change_ledger_port | 18 pass |
| test_change_registry_sql | 62 pass |
| test_change_sweeps_sql | 26 pass |
| test_change_offline | 538 pass |
| test_ed25519_sql | 20 pass |
| test_g1_postgres_integration / _hardening / _review2 | 10 / 10 / 29 pass |
| test_g1_guard_mutations | 10 pass |
| test_g1_concurrency_mp | 4 pass |
| test_g1_capacity_smoke | 4 pass, 2 fail (environment, below) |

Batch B, harness-owned clusters, one pytest process (`-m pytest <33 files>`): 212 passed, 13 errors (below), 0 failed.

| Group | Result |
|---|---|
| test_g1_crash 6, test_g1_restore 2, test_g1_migration_contract 6, test_g1_safety_requirements 3 | pass |
| test_s12_evidence_v2 6, test_s12_governed_write_v2_e2e 20, test_s12_reconciliation_immutability 7, test_s12_reconciliation_immutability_e2e 1 | pass |
| test_s13_barrier_ack_protocol 10, _verifier 7, _service_e2e 4, _sql 6 | pass |
| test_s13_current_turn_sql 38, test_s13_universal_fence_matrix 11 | pass |
| test_s13_checkpoint_runtime_authority 19, test_s13_evidence_provider_composition 16, test_s13_lifecycle_preflight 14, _preflight_e2e 10 | pass |
| test_s13_global_id_contention_e2e 1, test_s13_release_claim_fence 9, test_s13_adapter_claim_release_bridge_e2e 2 | pass |
| test_s13_private_ingress_boundary 7, test_s13_t16_recovery_error_mapping 3, test_s13_trust_snapshot_realistic_size 1, test_s13_trust_source_error_mapping 2 | pass |
| test_s13_checkpoint_suffix_functional | 1 pass, 1 error (`test_migration_026`) |
| test_s13_migration020 (5), test_s13_migration022_e2e (2), test_s13_migration023 (5) | 12 errors |

Batch C, script entry points (`python <file>` with the same environment): all 8 exit 0 with PASS lines: `test_s13_checkpoint_suffix_functional.py` (47 Python assertions, 14 PostgreSQL groups), `test_s13_migration020.py` (5 groups), `test_s13_migration022.py`, `test_s13_migration022_e2e.py` (2 journeys), `test_s13_migration023.py` (3 groups), `test_s13_migration023_e2e.py`, `test_s13_checkpoint_suffix_e2e.py`, `s13_migration020_e2e.py`.

Batch D: `test_change_ledger_dump_restore.py` on own container `r2-s13-dump-qa9870afd` (`ERP_PHASE2_TEST_CONTAINER`): 6 passed in 74.5 s. Batch E: `test_g1_capacity_smoke.py` on `r2-s13-dump-qa9870afdb`: 6 passed.

### Failure classification

| Journey | Location | Class | Evidence | Action |
|---|---|---|---|---|
| Capacity drill, small run and cluster identity | `tests/phase2/test_g1_capacity_smoke.py::test_capacity_drill_small_run_recounts_clean`, `::test_verify_cluster_real_dsn_matches_the_test_container` | Environment | drill error `TEST_CONTAINER_NOT_RUNNING`; the drill resolves the container by name prefix `r2-s13-dump-`, mine was `s13-qual-*`. Rerun on a correctly named own container: 6 of 6 pass. | None in code. Future runs need a `r2-s13-dump-*` container for this file. |
| Script-style helpers collected as tests | `test_s13_checkpoint_suffix_functional.py::test_migration_026`; `test_s13_migration020.py` 5 tests; `test_s13_migration022_e2e.py` 2 tests; `test_s13_migration023.py` 5 tests | Test defect (runner/naming), not a product bug | `fixture 'db' not found` (8) / `fixture 'led' not found` (5): these `async def test_*(db, led)` functions are called by each file's own `run()/main()` which supplies the arguments. All eight files pass when run as scripts (Batch C). | Not changed: renaming the helpers (for example leading underscore) or adding a `conftest` guard would silence pytest collection but touches files in the S13 test set that other owners rely on. Recommended: rename to non-`test_` names or mark with `pytest.mark.skip(reason="script entry point")` so a plain `pytest tests/phase2` is not red. Until then these 13 items are verified only through the script entry points, not through pytest node ids. |

No product bugs found. No src or migration file was modified. No test was quarantined, skipped or weakened.

## 4. Exit-ID mapping

Exit-ID wording is from the S11 test design package. "Verified here" means executed on PostgreSQL 16.14 in this run. Every item that needs a 1C clone, the operator-owned external checkpoint store, or a production signer is NOT_RUN.

| Exit ID | Meaning | Status | Evidence (node ids / files) | Unmeasured |
|---|---|---|---|---|
| E18 crash windows | Crash/restart consistency | PARTIAL | `test_g1_crash.py::test_terminate_backend_after_partial_work`, `::test_terminate_backend_blocked_inside_commit_cursor_page`, `::test_sigkill_backend_crash_recovery`, `::test_terminate_backend_during_observed_explicit_commit` (living registry, backend kill/SIGKILL); `test_s13_migration022_e2e.py` (script) unresolved dispatch holds recovery; `test_change_ledger_sql.py` claim/begin_apply flows | Crash after write before ledger / after post against a real 1C snapshot; two executor processes on the change ledger; physical writer |
| E25 restore skew | Restore from dump, skew detection | PARTIAL | `test_change_ledger_dump_restore.py` (6 tests: chain and head survive, row-for-row restore, hardening catalog identical, guards in restored DB, chaining continues); `test_g1_restore.py` (2); `test_change_ledger_sql.py::test_check_anchor_detects_a_restored_older_ledger_with_an_anchor_gap_hold` | Ledger-vs-1C skew (older/newer than 1C), valid-but-old chain with receipts for nonexistent documents |
| E36 external anchor | Tamper/rollback detection by external checkpoint | PARTIAL | Anchor-gap test above; `test_s13_checkpoint_suffix_e2e.py` and `test_s13_checkpoint_suffix_functional.py` (suffix reader, payload/hash minimization, NOT_READY, grants) | External operator-owned checkpoint store outside the DB trust boundary, key rotation with real custody, unavailable-store behavior at a real provider; sink and signer are test doubles |
| E38-parallel | Parallel budget races | NOT_RUN | Only the living-registry multi-process tests ran (`test_g1_concurrency_mp.py`: six processes one job, killed lease holder, two processes same cursor) | Parallel multi-process reservation at the budget boundary on the change ledger (`budget`/grant paths are covered single-connection in `test_change_*_sql`); mixed currencies across processes |
| E11 kill switch | STOP/OFF, store unavailable | PARTIAL | `test_s13_migration020.py` and `s13_migration020_e2e.py` (scripts); `test_change_ledger_sql.py::test_kill_switch_modes_refuse_admission_and_effect_steps_but_not_observation` | In-flight apply with a real port counter and 1C; real kill-switch store outage |
| E13 audit/checkpoint failure | Zero port calls on audit sink failure | PARTIAL | `test_change_ledger_sql.py::test_begin_apply_then_permit_needs_a_real_readback_checkpoint_covering_the_head` and migration 023/024 refusal tests (scripts) | Raising audit sink at the service layer and independent 1C snapshot |
| E20 approval races | Approve/edit/revoke/role-change interleavings | PARTIAL | `test_s13_universal_fence_matrix.py` (11 pass, includes the namespace-7 wait/no-partial-write scenario); `test_s13_migration022_e2e.py` cross-connection fence; `test_s13_migration023_e2e.py` bounded waits (script); `test_s13_global_id_contention_e2e.py` | Most of the 54-route fence matrix is still NOT_RUN by the file's own docstring; "while running" half needs 1C |

## 5. What remains unmeasured

- Everything needing a 1C clone or real COM writer: physical dispatch, ledger-vs-1C skew, independent snapshot confirmation, the S13 universal fence for the physical writer.
- External anchor/checkpoint provider, anti-rollback guarantee, production signer custody; test doubles and synthetic keys only.
- Production-approved evidence validator identity: `private_writer_evidence_ingest` has no EXECUTE rights on anything in the current schema.
- Network login as the real login roles, client-certificate to `(service, host, base)` binding, and `pg_hba` configuration.
- Dump/restore of a populated S13-027 schema (the dump/restore test pins the ledger journey, not private-writer tables with data).
- Multi-process parallel budget reservation on the change ledger (E38 parallel).
- 027 idempotency on a populated database.
- Pytest node-id evidence for the 13 script-style helpers (they are verified through their script entry points).
- No performance, capacity, or long-soak numbers beyond the capacity smoke.

## 6. Artifacts and cleanup

- Grants matrix: `D:\Repo\ERP_MCP\docs\phase2\artifacts\S13_PG_GRANTS_MATRIX_2026-10-28.json`.
- This report: `D:\Repo\ERP_MCP\docs\phase2\S13_PG_QUALIFICATION_REPORT_2026-10-28.md`.
- Container removal and `docker ps` confirmation: see the closing section below.

Cleanup: `s13-qual-a9870afd` and both `r2-s13-dump-qa9870afd*` containers were removed with `docker rm -f -v`; `docker ps -a` afterwards lists only pre-existing containers (the other agent's `r2-s13-dump-4798df6df719-a`, `erp-pr23-e2e-*`, `erpmcp-e2e-real1c-*`) and none of mine.
