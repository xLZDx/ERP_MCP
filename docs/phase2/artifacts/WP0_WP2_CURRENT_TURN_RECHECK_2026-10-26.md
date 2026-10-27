# WP0/WP2 current-turn recheck — 2026-10-26

## Scope and safety

This recheck used only read-only operations in `D:\Repo\ERP_MCP` and the explicitly authorized Ivan stack path. No service was restarted. The PostgreSQL catalog session ran inside a read-only transaction. The lane configuration and token remained in process; neither the DSN nor token was printed.

The active checkout's `remote.origin.url`, sanitized without userinfo, resolved to `github.com/xLZDx/ERP_MCP.git`; this confirms the repository identity for this checkout, not the provenance of any earlier PM Bridge request.

## Ivan SSH stack

Command:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
```

Observed output: `postgres`, `redis`, `apache`, `proxy8191`, `proxy8192`, `proxy8193`, `sidecar`, `idp`, and `gateway` each returned `True`. Strict host-key checking succeeded without an interactive prompt.

Names-only listings of `D:\1c\mcp` returned `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, and `venv`; the `data` subdirectory listed `pg` and `redis`. This did not inspect or establish the existence, license, or identity of the 1C clone.

## Local ERP MCP health

Using `scripts/real1c/gateway_client.py`, `LaneEnv.load()`, and an in-process short-lived auditor token, `source_health(source_id="onec-818ha-reference")` returned `is_error=false`, `ok=true`, `status_code=200`. The token was not printed. No business rows were requested in this call.

## Named disposable COM clone probe

The named local clone directory `D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff` existed and contained `1Cv8.1CD` (4,385,914,880 bytes) when listed read-only. This directory label and file presence do not establish the database identity or a qualified property/operation crosswalk. A read-only metadata-connect attempt through `scripts.real1c.com_oracle.Oracle(base=...)` failed with the sanitized exception class `com_error` before metadata names were returned. A retry captured HRESULT `0x80020009` (`DISP_E_EXCEPTION`); the underlying 1C/COM error detail was not surfaced, so the cause remains unknown. No COM write, 1C mutation, or service restart occurred.

## Disposable PostgreSQL effective-grant recheck

The connection was constructed in process with `LaneEnv.load().dsn("admin")`; no URL or secret was printed. The read-only catalog query reported database `business_ai`, connected role `business_ai_admin`, and server port `5432` as seen inside PostgreSQL.

- `to_regnamespace('change_ledger')` returned `NULL`.
- `information_schema.tables` returned no `change_ledger` tables.
- The `public.alembic_version` and `public.schema_migrations` relations were absent.
- `information_schema.role_table_grants` returned zero rows for the queried ledger/application roles in `change_ledger` and `public`.
- The targeted `pg_proc` query returned no `operator_resolve_v1`, `check_anchor_v1`, `private_writer_open_hold_v1`, `revoke_stale_v1`, `claim_v1`, or `resolve_unknown_v2` routines.
- `pg_auth_members` returned no rows for the queried application and S13 role set. The `pg_roles` query found `business_ai_admin`, `business_ai_control_api`, and `business_ai_app`; it also found `business_ai` with superuser/role-creation/database-creation privileges. This is catalog evidence about this disposable DB only, not evidence of S13 candidate grants.

Therefore effective S13 grants remain `NOT_MEASURABLE` on this database: the candidate schema, tables, and routines are absent. No schema was installed and no privilege was changed.

## Acceptance state

| Criterion | State | Evidence and remaining work |
|---|---|---|
| WP0 service/auth reachability | Re-observed for the nine SSH stack components and the local authenticated source-health call | Does not prove 1C business-write capability or clone license. |
| Ivan writer boundary | Open | The authorized `D:\1c\mcp` listing does not establish a licensed COM clone or its type crosswalk. Continue only from authorized evidence; do not infer a mapping. |
| WP2/S13 effective grants | Not measurable | The queried disposable database has no `change_ledger` schema or candidate functions. S13 grants need a disposable database with the accepted candidate installed, followed by read-only catalog queries. |

## WP5 decoder functional evidence

The functional-test-reviewer authored `tests/phase2/test_wp5_json_decoder_contracts.py`; it remains untracked in the working tree. At repository HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`, its SHA-256 was `997BA35DA68269AC244B85368D7AC8B00FF17DF7AA1D531EF40371461659C5A6`. The E2E test role ran only:

```text
uv run pytest -q -s tests/phase2/test_wp5_json_decoder_contracts.py
```

Result: exit 0, 12 tests passed, 24 subtests passed, 19.13 seconds total. The maximum-payload measurement reported an 8 MiB trust snapshot decode at 2.345061 seconds with 3,949 bytes traced peak Python allocation, and a 2 MiB evidence-envelope parse at 0.345646 seconds with 9,444,606 bytes traced peak. Timing ran without tracing overhead; allocation was captured separately on the same prebuilt payloads. These are measurements from this local run, not a general platform guarantee. The suite was offline and made no PostgreSQL or COM calls. It does not qualify the uninstalled S13 migration or the real 1C writer.
## WP5 decoder boundary and performance recheck — updated working tree

This later run used Git HEAD 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. The source and test files below are untracked, so HEAD alone does not identify their contents. SHA-256 at measurement time:

- src/erp_mcp_private_writer/postgres_evidence_trust.py: E13EF0D8C99C3E67F4ED87C1A6AAD2869318B15EC38E81F0E71BA79CA35E9C18.
- src/erp_mcp_private_writer/production_evidence_verifier.py: 9E513570862BC118135005D294287DEC7FC927D62BA4368C48AA6A19221717E5.
- tests/phase2/test_wp5_json_decoder_contracts.py: A960458BA8097D630DB5AF388DDA7098B45C9CF87D7A486C2F45B4B2D9DB5F6A.

The E2E test role ran the updated offline file:

Command: uv run pytest -q -s tests/phase2/test_wp5_json_decoder_contracts.py

Result: exit 0; 14 tests passed, 24 subtests passed, 23.65 seconds total. Visible measurements: 8 MiB trust snapshot decode 1.291895 seconds / 4,161 bytes traced peak; 2 MiB evidence envelope 0.399802 seconds / 9,444,606 bytes traced peak.

The measurement case was then run five separate times, each with this exact command:

Command: uv run pytest -q -s tests/phase2/test_wp5_json_decoder_contracts.py -k maximum_payload_decode_duration_and_peak_allocation

Each exited 0 with one test passed and 13 deselected:

| Run | Trust snapshot, 8 MiB: duration / traced peak | Evidence envelope, 2 MiB: duration / traced peak |
|---:|---:|---:|
| 1 | 1.246540 s / 4,161 B | 0.433699 s / 9,444,614 B |
| 2 | 1.414163 s / 4,161 B | 0.498974 s / 9,444,614 B |
| 3 | 1.183709 s / 4,161 B | 0.369962 s / 9,444,614 B |
| 4 | 1.644188 s / 4,161 B | 0.538454 s / 9,444,614 B |
| 5 | 1.873672 s / 4,161 B | 0.531994 s / 9,444,614 B |

Measured medians/ranges for these five local runs: trust snapshot 1.414163 seconds (1.183709–1.873672; 0.689963-second spread), peak 4,161 bytes each run; evidence envelope 0.498974 seconds (0.369962–0.538454; 0.168492-second spread), peak 9,444,614 bytes each run. This sample is not a percentile or general platform SLO.

A separate in-process profile ran only PostgresEvidenceTrustSource._decode on a prebuilt, valid, exactly 8,388,608-byte ASCII trust payload, using the test helper. Exact PowerShell invocation:

@'
import cProfile
import io
import json
import pstats
import runpy
from erp_mcp_private_writer.postgres_evidence_trust import PostgresEvidenceTrustSource

ns = runpy.run_path('tests/phase2/test_wp5_json_decoder_contracts.py')
trust_prefix = json.dumps(ns['_trust_payload'](), separators=(',', ':'))
trust_envelope = trust_prefix + ' ' * (8 * 1024 * 1024 - len(trust_prefix))
assert len(trust_envelope.encode('utf-8')) == 8 * 1024 * 1024
profile = cProfile.Profile()
result = profile.runcall(PostgresEvidenceTrustSource._decode, trust_envelope)
print(f'profile_input_bytes={len(trust_envelope.encode("utf-8"))}; decoded_type={type(result).__name__}')
stream = io.StringIO()
pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumtime').print_stats(20)
print(stream.getvalue())
'@ | .\.venv\Scripts\python.exe -

Profile result: exit 0; decoded type EvidenceTrustSnapshot; 259 calls in 1.143 seconds. Top cumulative entries: _decode 1.143 s, _check_json_text_limits 1.126 s, json.loads 0.017 s. The inspected working-tree scanner caches payload_length; this profile recorded 47 calls to built-in len. Earlier in-thread profile output at the same Git HEAD recorded 8,388,641 len calls, but its untracked source hash was not captured. This artifact therefore does not attribute the difference to a specific source change or claim a speedup.

No DB, COM or network calls occurred. This is offline decoder testing/profiling only; it does not qualify S13 SQL, effective grants, operational COM, or the real 1C writer. The E2E test role made no source edits and created no commit.

## S14 ephemeral binding and S13 current-turn SQL acceptance runs

Git HEAD at invocation time: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Relevant working-tree files were untracked before the runs; their hashes identify the observed content and do not imply they are in HEAD.

Exact SHA-256 values observed after the runs:

- src/erp_mcp_private_writer/com_manifest.py: A1F5F9356C6C573C73BE1CB59B874F42ADE5CFB92D79B8E18C7B3D52930B4F02
- src/business_ai_gateway/phase2/change/proposal.py: B800F8CF12218598503490815502C2610044DD6CAFE14BE6CE171B5525441399
- src/business_ai_gateway/phase2/change/evidence.py: C20D7496B54777573EF7024CB26E13BA5D4FFC92BF7CD33573A834052C61FDC9
- tests/phase2/test_s14_com_ephemeral_value_binding.py: 9C6998CE4F3910D90217E8F132FA8CA7E3219D73CEE49423BD56801A7C1F310F
- tests/phase2/test_s13_current_turn_sql.py: 8AC3E7DE084B106D31D1F485FA6E7FC8901C67665BDDEAFEACD61BD02512CF06
- tests/phase2/_pg_harness.py: C3B12AB3E8C10B612824C21736308342271B0017633AB8C9C08B085785698412
- tests/phase2/test_change_ledger_sql.py: BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5
- db/phase2/027_private_writer_admission_schema.sql: A5C9F5821F96C81F2B21B0F13FA87BB9297A0B3C2EFA898CA768225BA365F854

Run 1 — S14 ephemeral value binding

Command: uv run pytest -q tests/phase2/test_s14_com_ephemeral_value_binding.py

Exit 0; stdout: 5 passed in 0.89s. Acceptance mapping: five tests in this file cover exact approved leaf values/digests, excluding control-only paths, exact source/destination coverage, refusal on changed approval digest/create preimage, and frozen scalar-only redacted COM assignments. This is pure Python manifest/payload evidence; it does not exercise COM or qualify a real writer.

Run 2 — S13 current-turn SQL

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Exit 1; output summary: 3 errors in 8.99s, all three tests failed during fixture setup before their acceptance bodies ran. The affected cases are test_s13_kill_switch_legacy_off_is_no_write_and_no_event, test_s13_renew_null_generation_precedes_later_refusals_without_delta, and test_s13_renew_mismatched_generation_precedes_locked_existing_permit. The pytest traceback represented an owned-cluster DSN; its credential-bearing line is intentionally omitted from this artifact.

Failure detail (sanitized): tests/phase2/test_s13_current_turn_sql.py:64 opens throwaway_db(..., migrate=False, seed=False), then line 66 passes db.conn to apply_files. In tests/phase2/_pg_harness.py, throwaway_db leaves Db.conn as None when migrate=False (the connect assignment is inside the migrate branch); apply_files then fails at line 257 with AttributeError: 'NoneType' object has no attribute 'execute'. The fixture error is deterministic from these call sites and classifies as a test-fixture defect, not a product SQL failure or an unavailable Docker environment. No acceptance assertion ran. Do not interpret this as a S13 pass.

S13 acceptance mapping: the three test names above target kill-switch-off no-write/no-event behavior, NULL-generation refusal ordering without ledger delta, and mismatched-generation refusal ordering against a locked permit. Current state: NOT_RUN for all three behaviors because pytest failed during fixture setup and never reached the test bodies.

No fallback to a lane database, no source/test edits, and no commit occurred. The authorized commands were run once each and no retry or additional test was run. Next action owner: Codex; correct the disposable-test fixture setup so it connects the newly created throwaway database before apply_files, then rerun only the focused S13 command. Preserve the existing assertions.

### Corrected-fixture S13 retry (single authorized run)

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Exit code: 1. Sanitized pytest output summary: `EEE [100%]`; three setup errors; `3 errors in 23.78s`. The credential-bearing owned-cluster DSN shown in pytest's fixture repr is omitted. The three affected cases remain `test_s13_kill_switch_legacy_off_is_no_write_and_no_event`, `test_s13_renew_null_generation_precedes_later_refusals_without_delta`, and `test_s13_renew_mismatched_generation_precedes_locked_existing_permit`; none reached its acceptance body, so all three behaviors remain NOT_RUN.

The prior `db.conn is None` fixture error is resolved: the changed fixture now calls `throwaway_db(owned_cluster_dsn, seed=False)`, which connects the unique throwaway DB. Setup then failed while executing migration `db/phase2/027_private_writer_admission_schema.sql`; PostgreSQL returned `asyncpg.exceptions.PostgresSyntaxError: syntax error at or near "session_user"` at `test_s13_current_turn_sql.py:68` while `_apply_migration` executed the migration text. The in-scope migration has the unquoted declaration `session_user name PRIMARY KEY` at line 58. This is a migration syntax/product defect, not a Docker availability failure. No SQL acceptance assertions ran. No retry was made.

Disposable ownership and cleanup: the harness generated a per-invocation random ownership label, binds the PostgreSQL port to `127.0.0.1`, and verifies the label before removing the uniquely named container with its anonymous volumes. The pre-run and post-run `docker ps -a --filter label=codex.g1.owner` outputs were identical: the same four historical exited containers appeared both times; no invocation-owned test container remained. The throwaway DB context uses a fresh admin connection in `finally` to `DROP DATABASE IF EXISTS ... WITH (FORCE)`; the harness then removes the verified invocation-owned container. No lane/business DB or real 1C/COM was used. No old container was changed.

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c.

Exact SHA-256 at post-run capture (these files were not changed by this E2E runner):

- tests/phase2/test_s13_current_turn_sql.py: 70DDBE43EAA153A2915926A3DEAA1DD87A53127FE85F555DF2442944CA15AF9D
- tests/phase2/_pg_harness.py: C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412
- tests/phase2/test_change_ledger_sql.py: BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5
Migration chain SHA-256 values for files 001–027 used by this disposable setup:

- db/phase2/001_living_registry.sql: D8C9D4A5A9D5F52A6E88DC31414DCA02678F262E75748D596374DDCF04E7D0CF
- db/phase2/002_job_cursor_functions.sql: 74776D7F165A25288EF6CFBFA5A4DECBC470260D671F265C2A51DD74AD36A138
- db/phase2/003_security_hardening.sql: 294D24D6C7981697C3F3336E603137EDADA46F5CAAE9E6FF672141B044854C9F
- db/phase2/004_change_ledger.sql: 6B7E1EFA11F43E39648051B8184DE2A97AD8EF2B578ABA696AF658253BED7340
- db/phase2/005_change_registry.sql: 99522E7CA803F5972C88588069E0408AF3A51A60340FD34DA26CC02EB23D1373
- db/phase2/006_change_sweeps.sql: DD147300993CA1D5DB4680AB013069B4CE59879E670120CD930A2D155AC05DE9
- db/phase2/007_change_hardening_a.sql: 91434B315E5586E656A633E101783800559E6A299BD21187FEAA5629FDB43C86
- db/phase2/008_change_hardening_b.sql: 5812A7C72AFE7DDAB9F29D1B1BA02AD3E8A1EA14F6C7C0DFEFF2CD671C70C8E9
- db/phase2/009_approval_digest_2.sql: 68AF5FD28AEC77DD14D83A108979733D14FA592AFBA7B459A7E7FF524C981EF8
- db/phase2/010_registry_session_hardening.sql: 31DD17112A22B17128CA5FA4CF77250CA864F75BF2840326B32E69A6DDC73B0F
- db/phase2/011_event_hash_v2.sql: B9E11476B8BD5119BCB4D0BEB96290A6F150FBAB4898E94D14CC396AC9F28842
- db/phase2/012_dispatch_session_hardening.sql: A6C5680B85A49B648E4FDAAD7014825441F8E59A4B0F44CA590E2D39C2A3C9C9
- db/phase2/013_dispatched_invariant.sql: 4A0C7A5CE3467809467F8CF619CEA6334C851E82503035BEB7FFD60444EC62AA
- db/phase2/014_ed25519_verify.sql: DB96004C9C6FBC7A4AB9000B84AF33A76A74EF8BDE0D18966B76005219919AFE
- db/phase2/015_ed25519_signatures.sql: 11F9EE2C887AF23C6983778B6134EDAD4C376BF0E508D5776CF69684D70036E6
- db/phase2/016_dispatch_receipt.sql: F9B0A1E9D5EC4D3F7D8365B11F226D37A6F9EAFC896C47D9FD759D8F9F8AC11E
- db/phase2/017_receipt_hardening.sql: 732BBB6D841F2CF3E5FC57504CC7925B778185B44167841986F7C6EC5B3B8F83
- db/phase2/018_wire_payload_receipt.sql: C3A081ED0E1FCC7B0B68DAC98D914070FE5CD72645D1691D66C3999C65CCD154
- db/phase2/019_ed25519_action_only.sql: 1662F8CA4D7ECC7641473D1CFDC0B27F47D3FDCDEB4FA2260D82A0885BF97904
- db/phase2/020_kill_switch_recovery_guard.sql: AB9337EC9FD8B56D612D916BE50AF4BE6A0BE1A5E8BA3B70CBB52884F7E3C9CC
- db/phase2/021_ed25519_consumer_cutover.sql: FA8DC4C8DCC14D4AACB30FAF1866D7DBE0624AF3EBA720ADC71BC3C124E7B70C
- db/phase2/022_lifecycle_epoch_fence.sql: 9AF22EC1291474A13031CD9AD928980E9AF8B81E01C806B998D5F2317C566ACC
- db/phase2/023_lifecycle_activation_cap.sql: 5CDA75ADB082EAF2E71F0ACB9F0DEF18FB2374C9245E9613186D53DDBAD19381
- db/phase2/024_restore_caller_lock_timeout.sql: 96AC22E6D207CA1D7C6069625CFA3738C0E9346907DAF95855EC6BF7C531DEA2
- db/phase2/025_lifecycle_checkpoint_suffix.sql: 8FE3EBB50AC9A27261C0D692C812A27988EDE9990BB4A4C635259FD47C1D709D
- db/phase2/026_lifecycle_checkpoint_payload_minimization.sql: 217B99DF9F13570F0F0275BC9AA4E181BA8609CCEDE77A6BF47EC252E4CDFB81
- db/phase2/027_private_writer_admission_schema.sql: A5C9F5821F96C81F2B21B0F13FA87BB9297A0B3C2EFA898CA768225BA365F854

### S13 retry after quoting the reserved identifier in candidate 027

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Exit code: 1. Sanitized stdout summary: `EEE [100%]`; three setup errors in 19.74s. Credential-bearing fixture DSNs are omitted. The affected tests are the same three listed above; no acceptance body ran, therefore each remains NOT_RUN. No further retry was made.

The previous parser error was cleared. Setup now reaches `db/phase2/027_private_writer_admission_schema.sql` and raises `asyncpg.exceptions.RaiseError: LEDGER_ROLE_UNSAFE` at migration execution from `test_s13_current_turn_sql.py:68`. Source inspection shows migration 027 lines 17–20 rejects `ledger_owner` when `rolinherit` is true. Migration 004 creates a missing `ledger_owner` with `NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`, but does not specify `NOINHERIT`; PostgreSQL therefore creates it with INHERIT, conflicting with the new 027 precondition in a fresh disposable chain. This is a migration-chain role-attribute mismatch, not a Docker availability error. No application SQL assertion ran.

The pre-run and post-run label-filtered Docker listings matched exactly: the same four historical exited containers remained; the invocation-owned cluster was cleaned up. The harness verifies its random label before removing the named container and anonymous volume. The throwaway DB is dropped from the context-manager `finally` path. No pre-existing container was modified.

HEAD and unchanged test/harness identities are recorded above. Hash of the migration content used in this retry: `db/phase2/027_private_writer_admission_schema.sql` — `95244FFA020A172B34EDFE68ED647046C4CA1B9FF321D98C43382717B594C3CB`. The prior listed SHA-256 values for migrations 001–026 remain the same; candidate 027 must use this newer hash for this run.
### S13 retry after role-attribute hardening in candidate 027

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Exit code: 1. Sanitized pytest summary: `EEE [100%]`; 3 setup errors in 19.69s. Exact exception: `asyncpg.exceptions.PostgresSyntaxError: syntax error at end of input`, raised while `_apply_migration` executes candidate 027 at `tests/phase2/test_s13_current_turn_sql.py:68`. The prior `LEDGER_ROLE_UNSAFE` error no longer occurs. All three S13 acceptance test bodies remain NOT_RUN; no retry was run. The credential-bearing disposable-cluster DSN in the pytest traceback is omitted.

Cleanup evidence: the pre-run and post-run `docker ps -a --filter label=codex.g1.owner` listings were identical, containing the same four historical exited containers and no new invocation-owned cluster. The fixture owns its random label and loopback-only port; its finally handler verifies that label before force-removing the exact created container and anonymous volumes. The throwaway database context drops its unique database in its finally path. No lane DB, business DB, or real COM was used, and no existing container was modified.

Identity: HEAD remains 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. SHA-256 of test and harness files at run time is unchanged from the previous retry: tests/phase2/test_s13_current_turn_sql.py `70DDBE43EAA153A2915926A3DEAA1DD87A53127FE85F555DF2442944CA15AF9D`; tests/phase2/_pg_harness.py `C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412`; tests/phase2/test_change_ledger_sql.py `BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5`. Candidate migration hash for this run: db/phase2/027_private_writer_admission_schema.sql `56A9CA5CF182EB652C52FA549C4A5AA6B22B81DC6410BAAB970D1986F4DD3E28`.
### S13 parser-diagnostic capture run

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

This one authorized run used the invocation-owned disposable cluster only. Exit code: 1. Sanitized summary: 3 fixture setup errors in 21.96s; no acceptance bodies ran. The fixture now emitted structured PostgresError diagnostics with DSN/password redaction. Captured values: SQLSTATE `42601`; `position` absent; `internal_position` `433480`; context `PL/pgSQL function inline_code_block line 5 at EXECUTE`. The exception message is `syntax error at end of input`.

The internal_query is the candidate migration's dynamic EXECUTE body. Its full output is very large and was truncated by the execution-output transport; the exact query is identified without duplicating it here by the source extraction: bytes between `EXECUTE $body$` and the closing `$body$;` in the migration file, 785,443 characters, SHA-256 `933D530CD9B0599833C5F4FFF36FDE81ED3DF94F2B3A8C52998DBFC52EEC63F1`. `internal_position=433480` maps to candidate file line 6916, around the `IF v_key_hash IS NOT NULL THEN key_keys:=...` block. This position is diagnostic evidence, not a confirmed root cause; Codex owns the migration fix.

Identity: HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`; tests/phase2/test_s13_current_turn_sql.py SHA-256 `BDCDC7A70BA7E20010DF0550105B298693B5BCF462254C1F91C97AA115B35DE9`; db/phase2/027_private_writer_admission_schema.sql SHA-256 `56A9CA5CF182EB652C52FA549C4A5AA6B22B81DC6410BAAB970D1986F4DD3E28`; tests/phase2/_pg_harness.py SHA-256 `C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412`; tests/phase2/test_change_ledger_sql.py SHA-256 `BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5`.

Cleanup: pre-run and post-run label-filtered Docker listings were identical (same four historical exited containers; no invocation-owned container remained). The invocation fixture's ownership verification and forced container/anonymous-volume cleanup and the throwaway DB finally-drop path were observed in the authorized in-repo harness. No old container or lane database was used or changed. No test retry followed this parser error.
### S13 retry after claim_v1 key-lock snapshot correction

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Exit code: 1; pytest reported three setup errors in 17.81s for the same three test cases. The fixture emitted structured, DSN/password-redacted diagnostics and the migration step was `027_private_writer_admission_schema.sql`. Captured fields: SQLSTATE `42601`; `position` absent; `internal_position` `474360`; context `PL/pgSQL function inline_code_block line 5 at EXECUTE`. The fixture diagnostic formatter does not include the original exception message, so that message for this run is UNKNOWN. All three acceptance bodies remain NOT_RUN.

The full `internal_query` field was captured by the diagnostic formatter but is too large for the tool transcript. Its exact contents match the dynamic SQL body extracted from candidate 027: 785,665 characters, SHA-256 `938AD75007ED3EAAFAD667F2B486A993D1FC257600815349384A02030FDBD109`. `internal_position=474360` maps to candidate migration file line 7594, near the planned-record key-lock validation/loop. This mapping localizes the parser input but does not establish a root cause.

File identities: tests/phase2/test_s13_current_turn_sql.py SHA-256 `BDCDC7A70BA7E20010DF0550105B298693B5BCF462254C1F91C97AA115B35DE9`; db/phase2/027_private_writer_admission_schema.sql SHA-256 `DAA7A6ADB7E7AC05B919512A9C4792602508570C9F81587CB566CA8A2564D54F`; tests/phase2/_pg_harness.py SHA-256 `C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412`; tests/phase2/test_change_ledger_sql.py SHA-256 `BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5`.

Cleanup evidence: pre-run and post-run label-filtered Docker listings were identical (same four historical exited containers, no invocation-owned container remaining); the exact owned container and its anonymous volume are removed by the harness after ownership verification, and the throwaway database is dropped in its finally path. No lane DB or real COM was used, and no pre-existing container was touched. No further run followed this parser error.
### S13 retry after revoke_stale_v1 predicate correction

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Exit code: 1; pytest reported three fixture setup errors in 13.84s for the same tests. Setup step: `027_private_writer_admission_schema.sql`. All three acceptance bodies remain NOT_RUN. Safe structured PostgreSQL diagnostics: SQLSTATE `42601`; `position` absent; `internal_position` `617219`; context `PL/pgSQL function inline_code_block line 5 at EXECUTE`. The diagnostic formatter did not capture the original exception message; it is UNKNOWN for this run. No further retry was made.

The full internal_query field was captured by the formatter and identified as the candidate migration dynamic body: 785,664 characters, SHA-256 `DA33BE25035705A780676262AFDF30EB4E2C732382D489B3E27BDCA1F1E9D330`. `internal_position=617219` maps to file line 9641, within `private_writer_recover_sweep_core_v1` (definition begins at line 9327), near the loop building global sweep-failure keys. This is a localization only; no root cause is asserted.

Run identity: tests/phase2/test_s13_current_turn_sql.py SHA-256 `BDCDC7A70BA7E20010DF0550105B298693B5BCF462254C1F91C97AA115B35DE9`; db/phase2/027_private_writer_admission_schema.sql SHA-256 `BFF7E4D1B8012926C563782047F2E42E4CDA224EA0B1F93CA1B10D9D150FE32D`; tests/phase2/_pg_harness.py SHA-256 `C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412`; tests/phase2/test_change_ledger_sql.py SHA-256 `BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5`.

Cleanup: pre-run and post-run `docker ps -a --filter label=codex.g1.owner` listings matched (same four historical exited containers; no invocation-owned cluster remained). The harness verifies ownership before removing its exact container and anonymous volume; the throwaway database context drops its unique database in `finally`. No lane/business DB, real COM, or pre-existing container was touched.
### S13 retry with complete safe PostgreSQL diagnostic formatter

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Exit code: 1; three setup errors in 17.47s. The three acceptance bodies remain NOT_RUN. Setup failed in `027_private_writer_admission_schema.sql`. Complete redacted diagnostic fields: severity `ERROR`; SQLSTATE `42601`; message_primary `syntax error at end of input`; `position` absent; `internal_position` `617219`; context `PL/pgSQL function inline_code_block line 5 at EXECUTE`.

The formatter reported internal_query length 785,664 characters and SHA-256 `da33be25035705a780676262afdf30eb4e2c732382d489b3e27bdca1f1e9d330` (same dynamic-body identity as the prior run). Safe snippet centered on internal_position: `c_void||c_t9||nonce_record_ids) AS u(x);\n  global_keys:=pg_catalog.array_append(global_keys,'sweep-run-id:v1:'||pg_catalog.lower(p_run_id::text));\n  FOREACH cid IN ARRAY ids LOOP\n   global_keys:=pg_catalog.array_append(global_keys,'record-change-id:v1:'||pg_catalog.lower(cid::text));\n  END LOOP;\n   FOREACH cid IN ARRAY c_t3 LOOP\n    global_keys:=pg_catalog.array_append(global_keys,'sweep-failure:v1:'||pg_cat...`. The diagnostic maps to candidate migration line 9641, within `private_writer_recover_sweep_core_v1`. DSN and password fields are redacted. This pinpoints the parser input but does not establish the SQL correction.

Run identities: `db/phase2/027_private_writer_admission_schema.sql` SHA-256 `BFF7E4D1B8012926C563782047F2E42E4CDA224EA0B1F93CA1B10D9D150FE32D`; `tests/phase2/test_s13_current_turn_sql.py` SHA-256 `98A4519BB7C9E1E4B17AF13661EEA4CC14CCB585B3BDCAEB65C0DDF63689841B`; `tests/phase2/_pg_harness.py` SHA-256 `C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412`; `tests/phase2/test_change_ledger_sql.py` SHA-256 `BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5`.

Cleanup: pre-run and post-run label-filtered Docker listings matched; the same four historical exited containers remained and no invocation-owned container remained. The disposable DB is dropped by its finally path and the harness removes only the verified invocation-owned container and anonymous volume. No lane/business database or real COM was used, no pre-existing container was changed, and no retry followed this parser error.
### S13 current-turn SQL acceptance after parser-robustness source correction

Command: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py

Git HEAD: 3e12436bc874f6aa12b33cdee1ef6111ee33b25c. Exit code: 0; stdout summary `3 passed in 20.51s`. All three acceptance cases executed and passed:

- `test_s13_kill_switch_legacy_off_is_no_write_and_no_event`: legacy-off kill switch performs no write and emits no event.
- `test_s13_renew_null_generation_precedes_later_refusals_without_delta`: NULL generation refusal ordering is preserved without ledger delta.
- `test_s13_renew_mismatched_generation_precedes_locked_existing_permit`: mismatched generation refusal precedes the locked-existing-permit path.

The run used the invocation-owned loopback disposable PostgreSQL cluster and per-test throwaway databases only. No lane/business DB, live 1C, or COM was used. No PostgreSQL error diagnostic was emitted. Cleanup evidence: pre-run and post-run `docker ps -a --filter label=codex.g1.owner` listings were identical (the same four historical exited containers, no invocation-owned container left); the harness drops the throwaway database in its finally path and removes only the verified invocation-owned container and anonymous volume.

Exact identities at run: `db/phase2/027_private_writer_admission_schema.sql` SHA-256 `D5F22EAF09DA1B2A0ED4CC6D29F70860EF6D55459FF2EA1F381B932FA4C46525`; `tests/phase2/test_s13_current_turn_sql.py` SHA-256 `98A4519BB7C9E1E4B17AF13661EEA4CC14CCB585B3BDCAEB65C0DDF63689841B`; `tests/phase2/_pg_harness.py` SHA-256 `C3B12AB3E8C10B612824C217ED22B14F697BFCD60AC8452AD958B085785698412`; `tests/phase2/test_change_ledger_sql.py` SHA-256 `BE3A126C864B4111A1617DCED22B14F697BFCD60AC8452AD958FA27913890DC5`.

### 2026-10-26 candidate ACL source review and correction

The database-reviewer read-only audit found a conditional privilege gap in migration 027: existing
private roles could retain direct grants omitted from its fixed S13 table list. The local lane DB
was queried through the repository `.venv` with `LaneEnv.load()` and `env.dsn("owner")`; the DSN
was not printed. A read-only transaction returned database `business_ai`, configured port `18432`,
server port `5432`, and `change_ledger exists=false`. Per the task boundary, the reviewer stopped
without querying role grants, default ACLs, or installing the candidate.

Candidate 027 now normalizes current table/sequence/routine and schema-`CREATE` grants for `PUBLIC`
and both private roles, closes global defaults for `ledger_owner`, revokes database `CREATE` from
the private roles, and raises `PRIVATE_WRITER_DATABASE_CREATE_UNSAFE` if either role still has that
effective privilege. A further source review identified that ACL revokes do not remove implicit
ownership privileges. The candidate now fails with `PRIVATE_WRITER_ROLE_OWNS_OBJECT` if either
private login role owns the current database, any schema, relation, routine, type, extension or
large object in that database. Candidate hash after this ownership check:
`EA9C04087A4D452CCCD4AB4C91321A2C97549C280AF3C510CA028ACE1AB9A942`. Final source re-review of
the ownership catalog query is pending.

No test, parser, migration, or database write was run after these source edits. Effective grants
remain `NOT_MEASURABLE` for this configured database because the candidate schema and roles are
absent. Acceptance is expanded under `S13-ACL-SOURCE-ROLE-MAP-01` to seed pre-existing role grants
and ownership, and verify direct/default ACL cleanup or fail-closed rollback on an
invocation-owned disposable database. Detail:
`docs/phase2/CHANGE_RECORD_307.md`.

## Latest S13 candidate ACL correction — 2026-10-26

After the reviewer flagged `living.record_migration(text,text[])` as a possible false positive, source inspection showed migration 003 revokes schema `living` access from `PUBLIC` and grants no `USAGE` to the new private roles. Candidate 027's current table/column, sequence and routine effective-right predicates now require schema `USAGE`; direct private-role grants remain revoked across application schemas, and reachable residual rights remain fail-closed. Candidate SHA-256: `76A191BE062AF74CB3556D674D38CC366D4E82EAF5775A84BC1F721A21384D40`. A source-only re-review of this exact predicate is pending. No parser, test, migration, DB write, or COM was run after this source edit. Current configured DB still lacks `change_ledger`, so current effective candidate grants are `NOT_MEASURABLE`. Owner: Codex. Next: reconcile review; finish remaining code before functional/E2E qualification. Detail: `docs/phase2/CHANGE_RECORD_307.md`.

### Source-review evidence for ACL candidate — 2026-10-26

Database-reviewer source-only review of migration 027 SHA-256 `76A191BE062AF74CB3556D674D38CC366D4E82EAF5775A84BC1F721A21384D40` found no SQL syntax issue or privilege bypass in the stated persistent data/routine boundary. The schema-`USAGE` gates correctly model effective reachability; table/column, sequence, routine and large-object checks are coherent. PUBLIC EXECUTE that remains reachable in an application schema causes a fail-closed refusal rather than a broad PUBLIC revoke. This is not parser/runtime evidence. Effective grants remain `NOT_MEASURABLE` because the configured disposable DB has no candidate schema. No tests, parser, migration or database mutation was performed after this source edit. Current owner: Codex. Next: continue remaining S13 code, then post-coding functional/E2E and database qualification. Detail: `docs/phase2/CHANGE_RECORD_307.md`.

### Schema-local default ACL correction — 2026-10-26

Candidate 027 now normalizes both global and `change_ledger`-local default ACLs for `ledger_owner` (tables, sequences, routines), since schema-local entries add to global defaults. Disposable acceptance was updated to exercise both layers. Candidate SHA-256 `DD7A1F1F63F0ED0935D685051885DF24E43F3C6B1A1D0E5ED62F55402B2F2EF2`; exact current-hash source review pending. No parser, tests, migration or database operation occurred after the edit. See `docs/phase2/CHANGE_RECORD_307.md`.

### Type-ACL hardening — 2026-10-26

Candidate 027 now normalizes global and `change_ledger`-local `ledger_owner` defaults for user-defined types, revokes direct type USAGE from both private roles across non-system schemas, revokes current `change_ledger` PUBLIC/private-role type USAGE before explicit per-type grants, and checks effective type USAGE where schema USAGE makes it reachable. Disposable acceptance now exercises current and default type ACLs. Candidate SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33`; exact-delta source review pending. This closes a least-privilege gap, not a proven writer bypass. No tests/parser/migration/database operation occurred. See `CHANGE_RECORD_307.md`.

### Final type-ACL source review — 2026-10-26

The database-reviewer re-reviewed exact SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33` and found no actionable issue in the type-ACL delta. Global/schema-local defaults, current type revokes including generated row/array types, effective `has_type_privilege` with schema USAGE, and later intended type grants are coherent. This is source review only; no parser, migration, tests, or database query ran. Effective grants remain `NOT_MEASURABLE` until approved disposable installation. Detail: `CHANGE_RECORD_307.md`.

### 2026-10-26 remote DPAPI path/account ACL check

Using strict SSH (`BatchMode=yes`, `StrictHostKeyChecking=yes`) to `koros@100.88.71.74`, a read-only PowerShell query found scheduled task `ERP_MCP_Ivan_Stack` in `Ready` state with principal `koros`, interactive logon, highest run level. No task was run or changed. The previously named `D:\secrets\erp_mcp` path is absent on this host; it was not created. Existing `D:\1c\mcp\env` is owned by `BUILTIN\Administrators` and has explicit, non-inherited `FullControl` ACEs for `BUILTIN\Administrators` and `IVAN\koros`; no file names or contents were read. This establishes directory ACL for `koros`, not a dedicated writer service identity or real DPAPI round-trip. No key was created or registered. Next WP5 step remains after the approved S13 registry identity/scope/validity path is ready: Codex to perform controlled DPAPI round-trip and provision D9/D10b there, then register public keys through S13.

A follow-up names-only query of remote `D:\1c\mcp\env` found no filenames matching `D9`, `D10b`, `signer`, or `witness`. This establishes only that no matching filename is present in that one directory; it does not prove the entire host has no such files. No file contents were opened.

A read-only remote service/process inventory on 2026-10-26 found no service name/display name matching 1C/1cv8/Sentinel/license and no `1cv8`, Sentinel, or HASP process. Windows `LicenseManager` was Running and `ClipSVC` was Stopped/Manual. These generic Windows states do not establish a 1C software/hardware license. No service was started or restarted; the known COM diagnostic remains `License not found`, so no retry was made.

### 2026-10-26 PM Bridge route and project-local license-name check

A read-only PM Bridge status query scoped to canonical project id `erp_mcp` with limit 2 returned request `c6c7dc4f-11f6-4810-9cad-326f3d1e6a67` and correlated response `e8866c5f-24c2-5fd8-b3ee-0026449439b0`. The request and reply both identify `PROJECT: ERP_MCP`, repository `https://github.com/xLZDx/ERP_MCP.git`, and local path `D:\Repo\ERP_MCP`; the recorded verdict is `MODIFY`, source-only, not push/PR/deployment/production approval. The same scoped status query for `ERP_MCP` (uppercase) returned no exchanges; `pm_gate_status(project="erp_mcp")` reports no gates. Therefore use the lowercase canonical Bridge id `erp_mcp`; do not treat this as a review routed to `ERP.git` or as a fresh approval.

A bounded names-only search in the active non-ignored repository tree for `*.lic`, `*license*`, and `*licence*` returned zero filename matches. This is not a host-wide absence claim and no file contents or secrets were read.

Next: Codex continues source-only S13/WP5/WP6 closure where contracts are complete; the operational COM writer remains gated on the trusted licensed-clone field/type crosswalk and authenticated transaction boundary. After all code closes, route mapped functional/E2E qualification to their required roles, reconcile the exact S13 ACL candidate on an approved disposable database, obtain a fresh exact-source PM review, and only then consider local commits with their dedicated change records. No PM message was sent in this check; no gate was approved, no code/test/migration/runtime action occurred, and nothing was staged, committed, or pushed.

### 2026-10-26 strict-SSH license filename search

A names-only, read-only search over `D:\1c\env`, `D:\1c\mcp`, `C:\ProgramData\1C`, and the Ivan account's Local/Roaming `1C` AppData directories found no `*.lic` files. SSH used `BatchMode=yes` and `StrictHostKeyChecking=yes` to `koros@100.88.71.74`. The search returned no paths; it did not read file contents and does not exclude an external license server, machine-bound license store, hardware key, or licensing service outside those roots. A preceding attempt failed at remote PowerShell quoting before any file action; the corrected EncodedCommand completed the same read-only search. No COM retry, service change, key generation or copy occurred. Codex next: continue only source work whose contract is independent of the licensed clone; recheck license/COM only after a verified licensing source becomes available. The operator remains accountable for the delegated task; Ivan stack owns the host boundary; Codex owns evidence collection and code closure.

### 2026-10-26 names-only 1C registry branch check

A read-only names-only query on both the local machine and Ivan host enumerated immediate subkey names under `HKLM\SOFTWARE\1C`, `HKLM\SOFTWARE\WOW6432Node\1C`, and `HKCU\SOFTWARE\1C`. No child names were returned. Registry value data was not queried or printed. This does not rule out 1C activation state in other registry branches, a machine-bound license store, hardware licensing, or an external license server. No service, registry, configuration, or credential was changed. The previous strict-SSH COM result remains `LICENSE` / `License not found`; no retry was made.

### 2026-10-26 current-turn MCP and SSH liveness

Fresh read-only checks on this turn: strict-host-key SSH to `koros@100.88.71.74` ran `D:\1c\mcp\run-mcp-stack.ps1 -Action Status` and returned `True` for postgres, redis, apache, proxies 8191-8193, sidecar, IdP and gateway. Local loopback listeners were present on 8088, 8191-8193, 18432, 19379, 21000, 21080, 21200 and 21768; no process was started or restarted. Using the repository `.venv`, `LaneEnv.load()`, and a short-lived in-process auditor token (not printed), `source_health(source_id="onec-818ha-reference")` returned `is_error=false`, `ok=true`, HTTP 200. No business rows were requested. This proves current authorized transport and source-health response only; it does not prove effective S13 grants, licensed clone metadata, or a physical writer.

### 2026-10-26 repository identity and operational writer source audit

Current read-only Git identity: root `D:/Repo/ERP_MCP`, HEAD `3e12436bc874f6aa12b33cdee1f6111ee33b25c`, origin `https://github.com/xLZDx/ERP_MCP.git`. A scoped source search found the real `OneCWritePort` protocol and `NonOperationalWritePort` skeleton only; no concrete class declares `operational = True`. The only `create_draft`/`post`/`unpost` implementation found outside that skeleton is the evaluation-only simulated writer. Runtime composition correctly refuses a non-operational writer. This verifies that S13 physical writer code remains absent; the simulated port is not accepted as a substitute. Next implementation step remains the concrete licensed-clone adapter after its exact property/type crosswalk and transaction boundary are read-only authenticated. No source code, test, migration, service, Git ref or database was changed by this audit.

### 2026-10-26 in-repository crosswalk search and TestOnly probe output

A scoped `rg` search across in-scope `docs`, `src`, and `testlane` found references to clone `818HA_p2diff`, CT14 marker/rights evidence, and the S14 manifest builder, but no authoritative complete canonical payload-to-COM property/type crosswalk. The search excluded change-record files and did not inspect `MCP-RSV-Data.zip`. Current Git identity remains root `D:/Repo/ERP_MCP`, HEAD `3e12436bc874f6aa12b33cdee1f6111ee33b25c`, origin `https://github.com/xLZDx/ERP_MCP.git`.

Read-only inspection of the host's `store-onec-admin.ps1` confirmed that `-TestOnly` only unprotects the existing admin credential in process, connects to the specified disposable file base, reads the current-user name, disconnects, and prints booleans/sanitized failure text. One invocation for `818HA_p2diff` returned only the SSH PowerShell CLIXML progress header to this caller, not the script's result; therefore its connection outcome is `NOT_VERIFIED`. No COM method, database query/write, service change, credential input, or second retry was issued. The prior documented sanitized probe still reports `License not found` and remains the last usable COM outcome.

The immediate post-probe process check found no local `ssh.exe` and no remote process whose command line matched `store-onec-admin.ps1`; the TestOnly invocation is therefore no longer running. The follow-up was process-name/ID only and exposed no command-line values. This does not convert its missing output into a successful connection result.

### 2026-10-26 Ivan secret-directory license-name check

The read-only top-level listing of `D:\1c` showed only `env`, `mcp`, and `secrets`. A recursive names-only search inside `D:\1c\secrets` for license/licence, `.lic`, HASP, activation, or protection markers returned no paths. No secret file was opened or copied. This closes a previously unsearched project-host directory for those filename patterns; it does not exclude a key under an opaque filename, external license server, or machine-bound activation store.

### 2026-10-26 WP5 bounded driver-dictionary compatibility correction

The current-turn source review reconciled the WP5 decoder contract with the narrower S13 attempt-context adapter rule. `WP5-JSON-DECODER-01` and the trust-snapshot design explicitly require bounded support for driver-decoded dictionaries; the later exact-raw-string rule is scoped to `PostgresEvidenceAttemptSource`, whose result has a separate 128 KiB byte contract. The trust decoder therefore accepts an exact built-in dict only after its existing iterative `_measure_json_value` check enforces compact encoded size, depth, node count, JSON scalar types, and valid Unicode without first serializing the object. Raw text still uses the pre-scan and duplicate-key rejecting parser. Source SHA-256: `7A2C2AAA3B9236D105ED801B8E94554322980F0F18B5ACE10B36FD79681294DA`. No test/check/build, parser, database, migration, COM, stage, commit, or push ran; qualification remains `NOT_RUN` and belongs to the designated functional/E2E roles after coding closure. Detail: `docs/phase2/CHANGE_RECORD_308.md`.

### 2026-10-26 fresh MCP and strict-SSH recheck (continuation)

Current-turn read-only recheck: `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"` returned `True` for postgres, redis, apache, proxies 8191-8193, sidecar, IdP and gateway. A 300-second in-process `auditor` token from the active repository `.venv` authenticated to the local MCP; `source_health(source_id="onec-818ha-reference")` returned `is_error=false`, `ok=true`, HTTP 200. The token was not printed, no business rows were read, and no service was started or restarted. This re-verifies transport and source health only, not S13 grants or a physical writer.

### 2026-10-26 fresh read-only PostgreSQL grant-state recheck

The database-reviewer repeated the bounded catalog audit through `LaneEnv.load()` and the in-process admin DSN. Connection identity was `session_user=current_user=business_ai_admin`, database `business_ai` on loopback port 18432 (server port 5432), in `REPEATABLE READ READ ONLY`. Present inspected roles were `business_ai_admin`, `business_ai_app`, and `business_ai_control_api`; each was non-superuser, had no `BYPASSRLS`, `CREATEDB`, `CREATEROLE`, or replication privilege, and no memberships among the queried roles were found. `change_ledger` and candidate S13 roles/routines are absent. Therefore S13 table grants and `has_function_privilege` results remain `NOT_MEASURABLE`; absence is not proof of denial. No business rows or secrets were read, and there were no database/file writes, tests, migrations or role changes. Database-reviewer performed the read-only query.

### 2026-10-26 current-turn S13 effective-grant check

The database-reviewer repeated the candidate-object query from the repository `.venv`, loading
`LaneEnv` and `env.dsn("admin")` in-process and connecting to disposable PostgreSQL on port
18432. The transaction was `REPEATABLE READ READ ONLY`; observed database was `business_ai`, server
PostgreSQL 16.15, and current/session role was `business_ai_admin`. `to_regnamespace('change_ledger')`
returned NULL. `pg_roles` returned no rows for `business_ai_private_writer`,
`private_writer_evidence_ingest`, `ledger_owner`, `requester_role`, `approver_role`, `operator_role`,
`writer_role`, `worker_role`, `auditor_role`, or `checkpoint_role`; `information_schema.role_table_grants`
returned zero rows for `change_ledger`; the routine/role join and `has_function_privilege` query had
no candidate pairs because the schema and routines do not exist. An earlier broad role query
confirmed `business_ai_admin` and the separate `business_ai` role are not equivalent; `business_ai`
is superuser and is not app-role evidence. S13 effective grants are therefore `NOT_MEASURABLE`,
not denied or passed. No credentials or business rows were printed/read, and no writes, migration,
tests/checks/build or files were performed by the reviewer. Next: Codex continues source closure;
repeat the effective-privilege checks only after an approved disposable installation in the
qualification phase.

### 2026-10-26 16:35 UTC strict-SSH stack status

From `D:\Repo\ERP_MCP`, strict SSH to `koros@100.88.71.74` used
`BatchMode=yes`, `StrictHostKeyChecking=yes`, and a 10-second connect timeout. The read-only
`D:\1c\mcp\run-mcp-stack.ps1 -Action Status` command returned `True` for postgres, redis, apache,
proxy8191, proxy8192, proxy8193, sidecar, idp and gateway. No process was started, stopped, or
restarted; no credentials or business data were read. This confirms SSH trust and service status at
the observed time only, not COM licensing, S13 grants, or a writer transaction boundary.

### 2026-10-26 retained-dispatch queue refusal source correction

A source-only comparison against `S13-WRITER-QUEUE-REFUSAL-01` found an uncovered path: after a requester is cancelled, the shielded physical dispatch keeps its serving-authority lease while the caller's local lock is released. A second request could then pass the lock-only fast refusal and receive `SERVING_AUTHORITY_BUSY` only after attempting the OS mutex. `PrivateWriterService.dispatch()` now checks both the retained `_active_dispatch` and local lock and returns `WRITER_BUSY` before any await, lock acquisition, precheck, durable admission, or writer selection. Source file SHA-256 after this edit: `87F971ED737CFBF84FF032DF285082ED56E6833A7CD06F477B1CC7CB9B592970`; the file already had pre-existing worktree modifications before this turn, and the hash identifies the full file. Detail: `docs/phase2/CHANGE_RECORD_309.md`. The contract row now states source implemented/runtime `NOT_RUN`. No tests or runtime checks were run; functional/E2E roles own qualification after code closure.
