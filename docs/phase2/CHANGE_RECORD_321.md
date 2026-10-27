# Change record 321 — S13 universal-fence qualification slice

## Ownership and scope

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex; functional qualification owner: `functional-test-reviewer`; contention qualification owner: `e2e-runner`.
- Technical boundary: candidate PostgreSQL S13 migration 027 and its disposable qualification only.
- Scope excludes the configured database, COM/1C, migration installation outside fresh invocation-owned disposable PostgreSQL, service restart, Git staging/commit/push, and production readiness.
- No migration or production-source bytes were changed in this turn. Migration 027 was already untracked at the initial worktree snapshot; its exact SHA-256 remained `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`.

## Test implementation and execution

The functional-test reviewer created `tests/phase2/test_s13_universal_fence_matrix.py` and ran:

```text
uv run pytest -q -s tests/phase2/test_s13_universal_fence_matrix.py
```

The initial result after the tenth behavioral slice and exact-lock review was **11 passed in 58.80 seconds** on PostgreSQL 16 (module SHA-256 `A4EFDADD4EFD1C5C316B97EA1657B3D70726D334CAA316B89694A9B08647B227`). A later same-PID review finding and its corrective re-run are recorded below; that re-run is the current evidence.

- `UF54-CATALOG-01` resolves all 54 mutation API names / 55 exact signatures, checks that `PUBLIC` has no `EXECUTE`, and compares effective `EXECUTE` against the candidate allowlist for nine runtime/private roles.
- `S13-UF54-SET-SWEEP-POLICY-ENTRY-01` holds the namespace-7 scope advisory lock, observes the candidate call waiting on that lock, verifies a zero row/event snapshot delta while blocked, then checks the resulting policy row and exactly one event after release.
- `S13-UF54-BUMP-EPOCH-ENTRY-01` invokes the operator route while the matching namespace-7 scope lock is held, observes the advisory wait and unchanged ledger snapshot, then checks the returned and persisted epoch value `1` and exactly one `EPOCH_BUMPED` event after release.
- `S13-UF54-DECLARE-TARGET-CLASS-ENTRY-01` creates a proposed change, invokes the requester route while the matching namespace-7 lock is held, verifies the exact waiting lock and unchanged pre-release snapshot, then checks the normalized `DISPOSABLE_CLONE` value, updated record, and exactly one `TARGET_CLASS_DECLARED` event.
- `S13-UF54-BUDGET-ADMIN-ENTRY-01` invokes the operator route while the exact namespace-7 scope lock is held, verifies the waiting PID's ungranted lock tuple and unchanged full snapshot, then checks the returned grant UUID, persisted grant fields, and exactly one `BUDGET_GRANT_SET` event.
- `S13-UF54-BUDGET-REVOKE-ENTRY-01` seeds an active grant, invokes the operator route while the exact scope lock is held, verifies the waiting PID and ungranted tuple plus unchanged snapshot, then checks the `REVOKED` result/state and one `BUDGET_GRANT_REVOKED` event.
- `S13-UF54-ISSUE-APPROVAL-NONCE-ENTRY-01` seeds a proposed change from `clt_alice`, then issues a nonce as independent approver `clt_bob` while the exact namespace-7 lock is held. After release it verifies the nonce shape, change/approver/state binding and the ten-minute expiry contract within a documented ±5-second fixture tolerance; it also confirms issuance appends no event.
- `S13-UF54-APPROVE-ENTRY-01` seeds a validated change, nonce and approval envelope, then invokes approval as the independent approver while the exact namespace-7 lock is held. After release it verifies the approval row, `APPROVED` record, consumed nonce and exactly one `APPROVED` event.
- `S13-UF54-REJECT-ENTRY-01` seeds a validated proposal and independent approver nonce, then calls rejection while the exact namespace-7 lock is held. After release it verifies the rejection decision row, rejected record/auth state, consumed nonce and exactly one scoped `REJECTED` event.
- `S13-UF54-VALIDATE-ENTRY-01` seeds the minimum proposed change with business key, target class and budget, then validates as requester while the exact namespace-7 lock is held. It verifies the exact waiter and unchanged snapshot before release, one `VALIDATED` transition/event afterward, and an inert replay that changes neither the snapshot nor event count.
- `S13-UF54-CLAIM-ENTRY-01` seeds an approved change with its budget and business key, then proves one contender PID waits in namespace-2 shared, namespace-7 exclusive, and ascending namespace-4 resource-lock order. The snapshot remains unchanged at every wait; after release it verifies the token, claim, reservation, target/key locks, writer lease and one event. Exact live-token replay is inert.
- A read-only `code-reviewer` found one MINOR finding: the generated scenario ID differed from its failure messages and docstring. The test owner corrected the ID everywhere and reran the focused module; the exact final hash/result above are post-fix. The reviewer confirmed the correction.
- Independent code and database reviewers then noted that checking an advisory wait alone did not identify the exact lock tuple. The test owner strengthened the helper to bind the waiting PID and verify `pg_locks` `classid=7`, `objid=hashtext(scope_key)` in unsigned representation, `objsubid=2`, and `granted=false` for both namespace-7 scenarios. Both reviewers rechecked the current hash and found the exact-lock evidence supported.

The final functional fixture used container `r2-s13-dump-e8564a54a12c-a` and disposable databases `g1x_e5760352`, `g1x_0c71f47e`, `g1x_5201d2cd`, `g1x_8b57ada8`, `g1x_acd27a7d`, `g1x_c41790f8`, `g1x_ea9bb6f2`, `g1x_c2d8a740`, `g1x_29b33988`, `g1x_13527a00`, and `g1x_cb473257`. The post-run container-name query returned no rows. The shared harness checks the generated container name and random owner label before removal and refuses cleanup on mismatch (`tests/phase2/_pg_harness.py:111-132`); disposable databases are removed in `finally` with `DROP DATABASE ... WITH (FORCE)` (`:277-305`).

The E2E runner separately created `tests/phase2/test_s13_global_id_contention_e2e.py` (SHA-256 `C00D669AE71F9A6FCDD8227402356E3C81CE4EC97BC0801B03842DB8D6499481`) and ran:

```text
uv run pytest -q tests/phase2/test_s13_global_id_contention_e2e.py -s
```

Result: **1 passed in 21.40 seconds** on PostgreSQL 16, container `r2-s13-dump-f1b82f90e641-a`. The exact-name `docker inspect` after the run returned no object (exit 1), confirming the invocation-owned container had been removed. The scenario blocks two cross-scope `propose` calls on the same namespace-6 `record-change-id:v1:<uuid>` key, asserts no pre-release row/event effect, then verifies one committed record/event and one stable `CHANGE_ID_CONFLICT` result. A read-only database-reviewer inspected this scenario against the exact migration hash and found no BLOCKER/MAJOR.

## Same-PID review remediation re-run

A read-only `code-reviewer` found a MINOR evidence gap in `S13-UF54-CLAIM-ENTRY-01`: the scenario checked the expected advisory-lock tuple at each wait, but did not retain and compare the observed backend PID across namespace 2, namespace 7, and the two namespace-4 waits. The functional-test reviewer changed `_wait_for_exact_lock_tuple` to return the observed `pg_stat_activity.pid` and added an explicit equality assertion across all four observations.

The owner reran only the focused module on a fresh PostgreSQL 16 fixture:

```text
uv run pytest -q -s tests/phase2/test_s13_universal_fence_matrix.py
```

Result: **11 passed in 64.99 seconds**. Final test-module SHA-256: `0FEEBEF7B443AFE481C8115A013A23018D259A1E71A1DEF4AEE56027C6AC98F4`; migration 027 SHA-256 remained `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`. The invocation-owned container `r2-s13-dump-75ff8b606c74-a` used disposable databases `g1x_0dbacc0e`, `g1x_5a6afa19`, `g1x_dda29a9d`, `g1x_79be70e7`, `g1x_dc7cf356`, `g1x_cebc8b8a`, `g1x_1f1b9144`, `g1x_f1fc9b2b`, `g1x_69c863c9`, `g1x_c412831f`, and `g1x_d129e200`. A post-run Docker name filter returned no matching container; the harness validates container name and owner label before cleanup and drops each database in `finally` (`tests/phase2/_pg_harness.py:111-132,277-305`). Independent read-only re-review of this exact hash is pending.

Independent read-only `code-reviewer` re-review of the remediated test hash `0FEEBEF7B443AFE481C8115A013A23018D259A1E71A1DEF4AEE56027C6AC98F4` against migration 027 found no actionable issues. It confirmed the returned observed PID and same-PID assertion across all four lock stages, exact ungranted tuples, unchanged snapshots, release effects, inert replay, and harness cleanup. The reviewer did not run tests or edit files.

## Bounded `release_claim` qualification

The functional-test reviewer added a separate module `tests/phase2/test_s13_release_claim_fence.py` (SHA-256 `B6606B1AED3FD2BFBCBAAD543C5639AEAE516B4089300A8EA5FE5376B593A4C2`) and ran only:

```text
uv run pytest -q -s tests/phase2/test_s13_release_claim_fence.py
```

Result: **3 passed in 26.03 seconds** against migration 027 at the unchanged SHA-256 above, on disposable PostgreSQL 16. `S13-UF54-RELEASE-CLAIM-ENTRY-01` ties the observed contender PID to the exact namespace-7 advisory wait, verifies unchanged full state/event snapshot until release, then checks `SUPERSEDED`, resource cleanup, one `CLAIM_RELEASED` event and inert non-`ISSUED` replay. `S13-UF54-RELEASE-CLAIM-MISSING-TARGET-01` and `S13-UF54-RELEASE-CLAIM-WRONG-OWNER-01` assert `LOCK_BUSY`, unchanged snapshot/events, and an `ISSUED` token.

The invocation-owned container `r2-s13-dump-d819cf672adc-a` used disposable databases `g1x_993bc05a`, `g1x_53b77898`, and `g1x_47b89ca6`; the exact-name post-run Docker query returned no rows. The harness drops each generated DB with `DROP DATABASE ... WITH (FORCE)` in `finally` and removes only the exact container after checking its owner label (`tests/phase2/_pg_harness.py:67-125,292-303`). Independent database-reviewer and code-reviewer reviews of this exact test hash found no actionable issues and ran no tests or DB actions. This slice does not cover missing token, wrong scope, worker authorization, expiry, repair handoff, stale-plan mutation, complete sorted row-lock order, multiple generations, or serialization with `begin_apply`/parallel releases.

## `release_claim` refusal and expiry follow-up

The functional-test reviewer extended only `tests/phase2/test_s13_release_claim_fence.py` with four scenarios and reran only that focused module:

```text
uv run pytest -q -s tests/phase2/test_s13_release_claim_fence.py
```

Result: **7 passed in 52.95 seconds** on fresh disposable PostgreSQL 16. Final test-module SHA-256: `B4E8AC253558C186F4DBD726F9BBF2B88DD589F64D399EE4011C978CFEB2547E`; migration 027 remained `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`. New cases assert: missing token returns `TICKET_SUPERSEDED` without snapshot delta; foreign-scope token returns `CHANGE_NOT_FOUND` without delta; authorized `clt_wrk` worker releases with one `CLAIM_RELEASED` event and resource cleanup; and expired record release yields `EXPIRED / NOT_STARTED / RELEASED`, clears resources, and appends exactly one event. The schema has no token-level `expires_at`; this verifies the record-expiry branch.

The successful fixture used container `r2-s13-dump-1ab01bc38863-a` and seven disposable databases. Exact-name checks confirmed the successful and prior failed-run containers were absent after teardown; the harness removes each DB in `finally` and validates the random owner label before container removal. One earlier setup attempt failed the schema CHECK `expires_at > created_at`; the test owner corrected fixture timestamps only and the complete focused module then passed. Independent database-reviewer and code-reviewer reviews of final hash `B4E8AC253558C186F4DBD726F9BBF2B88DD589F64D399EE4011C978CFEB2547E` found no actionable issues and ran no tests or DB actions.

Remaining `release_claim` acceptance includes repair handoff, stale-plan/parent mutation, complete ordered lock trace, and serial-history races with `begin_apply` and concurrent release. The module invokes the granted legacy wrapper, which delegates to the v1 body; it does not prove direct EXECUTE on v1, whose grant remains revoked.

## Evidence limits and remaining acceptance

These tests close a **bounded slice** of `S13-UNIVERSAL-FENCE-54-01`, not the full gate. The catalog/ACL matrix covers all 55 signatures. Behavioral contention/effect evidence now covers twelve of 54 API names: `set_sweep_policy`, `bump_epoch`, `declare_target_class`, `budget_admin`, `budget_revoke`, `issue_approval_nonce`, `approve`, `reject`, `validate`, and `claim` at namespaces 2/7/4; cross-scope `propose` at namespace 6; and a bounded `release_claim` slice. The other 42 API names / 43 signature-specific behavior scenarios, complete sorted/deduplicated lock sets, remaining stale-plan refusals, rollback/no-event branches, and inter-API contention remain `NOT_RUN`.

The prerequisite document's S12/S13 exit set is not yet mapped to a complete stable executable-scenario catalog. The existing full candidate SQL suite's 38-pass result is recorded separately in `CHANGE_RECORD_317.md`; the measured disposable grants are recorded in `CHANGE_RECORD_320.md`. Neither result proves all 54 behaviors or installed grants in the configured database.

Current configured-database S13 grants remain `NOT_VERIFIED`; migration 027 remains candidate-only. The WP4/S13 acceptance remains open pending completion of the behavior matrix and applicable S12/S13 exit-scenario mapping. WP5 real D9/D10b keys, WP6 operational COM writer, and WP7/WP8/WP10 remain dependent on the recorded identity, license, crosswalk, provider, and trust-source evidence; this test slice supplies none of those external proofs.

## Ordered next work

1. Extend the disposable behavior matrix in small API groups, preserving stable scenario IDs and exact candidate/source hashes; `functional-test-reviewer` and `e2e-runner` own authored/executed tests.
2. Map each S12/S13 exit gate (`E4`, `E5`, `E6`, `E11`, `E13`, `E14`, `E15`, `E20`, `E23`, `E24`, `E29`, `E32`, `E38`, `E41`, `E45`; S13 `E18`, `E25`, `E36`, and parallel-reservation `E38`) to executable scenarios and falsifying oracles after the relevant code slice is complete.
3. Keep migration 027 uninstalled on the configured database until the disposable qualification and authorization gates permit that separate action; then collect configured effective-grant evidence read-only.
4. Resume WP5 key provisioning only through the approved writer-service identity and registration path; resume WP6 only after licensed read-only COM access and a reviewed destination/type crosswalk are evidenced.

No configured database, COM/1C instance, business data, or production service was accessed by these tests. No staging, commit, or push occurred for this record or the two test modules.
