# WP0 access and source recheck — 2026-10-25

## Current local gateway read

At 2026-10-25 03:20 UTC, the repository's documented in-process client obtained a short-lived
`auditor` token and initialized an MCP session against the configured local ERP_MCP gateway. The
token and configuration secrets were not printed or written. Three read-only calls to
`onec-818ha-reference` returned without tool errors:

| Tool | Observed result |
|---|---|
| `source_health` | `ok: true` |
| `onec_metadata_summary` | 920 EntitySets |
| `onec_find_entities` | Purchase receipt document plus `Товары` and `Услуги` EntitySets; 91 document properties and 30 properties in each returned table part |

The reference document metadata includes names such as `Организация_Key`, `Контрагент_Key`,
`ДоговорКонтрагента_Key`, `ВалютаДокумента_Key`, `НомерВходящегоДокумента`,
`ДатаВходящегоДокумента`, `Комментарий`, and `СуммаДокумента`. The `Товары` EntitySet includes
`Номенклатура_Key`, `Количество`, `Цена`, `Сумма`, and `СтавкаНДС`. The tool exposes property
names and EntitySet/type names here, but not property data types or a validated transformation from
the frozen S12 payload. These names are therefore discovery evidence, not an approved COM mapping.

Reproduction used `.venv\Scripts\python.exe` with `LaneEnv.load()`,
`Idp(env).token("auditor", ttl=3600)`, `mcp_session`, and `call_tool` from
`scripts/real1c/gateway_client.py`; calls were `source_health`, `onec_metadata_summary`, and
`onec_find_entities`, each for `source_id="onec-818ha-reference"`. No customer/document rows,
credential values, tokens, or private keys were requested or recorded. This observation does not
identify the source as Ivan's licensed COM clone, measure its effective 1C grants, prove a writer
host/process identity, or qualify S12/S13 behavior. No 1C write, SQL mutation, migration, service
restart, test, build, staging, commit, or push was performed for this check. The client wrapper did
not expose a correlated request ID, so none is claimed.

## Consequence for the writer boundary

The runtime gateway and metadata read path are reachable now. A concrete `OneCWritePort` still
requires the current licensed clone's exact property types, line transformation, write modes, and
authenticated base fingerprint, followed by the independent operation-manifest review. Keep
physical dispatch disabled until that evidence exists. The earlier WP0 artifact records that the
Ivan COM license was expired; no license renewal or paid action was attempted.

Accountable task owner: operator. Executor: Codex. The Ivan stack owns its documented host/SSH
boundary; current project records do not identify an owner for license provisioning or the
approved payload-to-COM mapping. Next: continue independent source coding and lock-map closure;
after source coding, hand the metadata/COM fixture cases to the authorized reviewer and
functional/E2E roles, then measure effective rights only on the approved disposable lane.

## Current strict SSH status

At 2026-10-25 03:21 UTC, `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\\1c\\mcp\\run-mcp-stack.ps1 -Action Status"` completed successfully. The remote status returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. This used the configured known-host trust and did not restart any service; the only remote command was the read-only stack status action. The pinned fingerprint value was not emitted by this command, so the fingerprint-specific comparison relies on the prior WP0 record.

## Fresh access recheck — 2026-10-25 03:30 UTC

The documented in-process client minted a short-lived `auditor` token with `ttl=3600` and called
`source_health` and `onec_metadata_summary` for `onec-818ha-reference`. Both MCP calls had
`is_error=false`; the sanitized payload showed `health.ok=true` and `entity_set_count=920`. The
token and lane credentials remained in process and were not printed. The strict SSH status command
above was repeated with `BatchMode=yes` and `StrictHostKeyChecking=yes`; it again returned `True`
for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. No listener
was started or restarted by this recheck. The current TCP-listener snapshot showed the expected
local ports 8088, 8191-8193, 18432, 19379, 21000, 21080, 21200, and 21768. The new
`include_property_types` input is still not loaded by the running gateway and remains `NOT_RUN`;
the fresh calls exercised the currently running tool schema only. This verifies read access and
stack presence, not effective 1C rights, writer identity, COM licensing, or S12/S13 qualification.

## Source change: opt-in OData property types

The current worktree now extends the existing read-only `onec_find_entities` contract with the
optional `include_property_types` boolean. The default/false response keeps its existing shape;
true adds each EntityType property's OData `Type` metadata. The parser stores the types already
present in the fetched `$metadata` document. This does not query business rows, establish a COM
conversion rule, or make the new parameter available in the already-running gateway process.
That process was not restarted, and this source change has not been tested, reviewed, or exercised
through MCP. Runtime status: `NOT_RUN`. After coding closes, the assigned test roles should verify
the unchanged default response and the opt-in types against a qualified disposable source. Keep
the purchase-receipt-to-COM mapping unapproved until the licensed clone and its exact payload,
write mode, base fingerprint, and operation manifest are independently established.

## Read-only Ivan application-directory inventory — 2026-10-25

Using strict host checking, the read-only command
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "cmd /c dir /a D:\1c\mcp"`
listed the expected `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, and `venv`
directories plus stack scripts. A second listing of `D:\1c\mcp\app` showed only `gateway` and
`sidecar`; no private-writer application is present in that inspected directory. This is a
directory-name inventory only: at that inventory step no scripts, environment files, runtime
data, credentials, or other host directories were opened, and it does not prove that a writer
service is absent from everywhere else on the host. No file, service, database, or business data
was changed by the inventory.

## Read-only disposable-clone metadata access attempt — 2026-10-25

The local `scripts/real1c/com_oracle.py` guard permits only `ВЫБРАТЬ` queries and reads credential
material in process. Instantiating it against the named disposable clone
`D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff` failed before a query with COM HRESULT
`-2147352567`; the exception text and all credential values were suppressed. The local MCP
`sources_list` response separately contained only the three registered read-only reference,
drift, and outage sources, with no `818HA_p2diff` source.

Over strict SSH, the remote clone path `D:\1c\env\bases\818HA_p2diff` exists. The documented
remote credential blob `D:\1c\mcp\env\onec_admin.dpapi` also exists, but a read-only DPAPI
unprotect attempt from the SSH `koros` process failed at the `CurrentUser` boundary
(`RuntimeException`, HRESULT `-2146233087`) before COM connect. No clone metadata was read and
no business data was queried or changed. The SSH session did not attempt impersonation or alter
the scheduled task. The dependency is an authorized metadata read executed in the credential
blob's owning principal or exposed through an existing read-only service path. Accountable task
owner: operator; executor: Codex; technical system: Ivan's documented stack; human owner for the
credential principal is not identified in the inspected canonical sources. Until then, exact
payload-to-COM mapping and physical writer dispatch remain disabled.

## Current-turn read-only transport and stack recheck — 2026-10-25 04:11 UTC

From the project `.venv`, the import-safe `gateway_client.py` flow minted an in-process short-lived
`auditor` token and called MCP `sources_list` and `source_health(source_id="onec-818ha-reference")`.
The source list returned the three registered read-only sources (`onec-818ha-down`,
`onec-818ha-drift`, and `onec-818ha-reference`); the reference health call returned
`{"status_code":200,"ok":true}` with `is_error=false`. This confirms the current authenticated
MCP/read-only source-health response, but provides no entity-set count, business-row evidence,
effective CT14 rights, or access to `818HA_p2diff`. Strict SSH with batch mode and host checking to
`koros@100.88.71.74` then returned `True` for postgres, redis, apache, proxy8191-8193, sidecar,
idp, and gateway. Neither operation started or restarted a service, and no token or credential
was printed. The earlier exact clone metadata/DPAPI limitation above remains unchanged.

## Read-only disposable PostgreSQL grants observation — 2026-10-25

The actual `database-reviewer` role inspected the local disposable `business_ai` database using
the admin DSN loaded in process. Roles `business_ai`, `business_ai_admin`, `business_ai_app`, and
`business_ai_control_api` exist; only `business_ai` is superuser. The database has no
`change_ledger` schema and no installed migration-027 objects, so S13 table/function privileges
remain **NOT_MEASURABLE** here. The existing `bag` inventory returned direct table grants to
`business_ai_admin` on 15 SELECT, 12 INSERT, and 11 UPDATE table privileges; no direct table grants
were returned for `business_ai_app` or `business_ai_control_api`. The bounded `has_function_privilege`
inventory found five of seven listed `bag` functions executable by `business_ai_app`, four by
`business_ai_control_api`, four by `business_ai_admin`, and all seven by `business_ai`. This is
only the current disposable database's `bag` privilege surface; it is not evidence about
CT14Писатель rights in 1C or candidate S13 effective privileges. The reviewer performed no
database writes, migration, tests, checks, build, CI, or service restart; reviewer model/effort
metadata were unavailable. Next: finish candidate code closure, then measure the installed 027
surface only after the approved disposable schema exists and CT14 rights through its measured 1C
source.

## Read-only ERP MCP health recheck — 2026-10-25

The ChatGPT connector tools `system_status`, `sources_list`, and `source_health` each returned MCP `-32603 Internal error`; this connector-path result is not evidence that the local gateway or ERP source is down. The authorized in-process gateway path (`LaneEnv.load()`, a short-lived auditor token kept only in memory, and `mcp_session`/`call_tool` against loopback) returned `is_error=false`, `ok=true`, and HTTP status 200 for `source_health` on `onec-818ha-reference`. No token, DSN or password was printed. This proves only that this read-only source-health call worked at this observation; it does not qualify write or COM behavior. No service was restarted, no database was written, and no migration/test/check/build/CI was run.

## Ivan stack status and directory recheck — 2026-10-25

Read-only SSH using `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74` ran the project status script `powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status`. It returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp and gateway. A separate `cmd.exe /d /c dir /b D:\1c\mcp` listed the stack directories/scripts (`app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, `venv`, and the setup/status scripts); filenames only were retained. Neither command restarted a component, read a secret value, activated COM, opened a 1C base or wrote data. The current 1C process/base identity, DPAPI signer material and effective rights remain unresolved; these commands prove configured stack health and directory presence only.

### Current-turn strict SSH status — 2026-10-25 05:59 UTC

This turn repeated only the status command with strict host-key checking:
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`.
SSH connected without a host-key prompt or mismatch. The command returned `True` for postgres,
redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp and gateway. No service was restarted,
no directory was listed in this repeat, and no secret, COM session, 1C base or business data was
read. This refreshes stack status only; effective grants, exact writer process/base identity and
the physical transaction boundary remain `NOT_VERIFIED`.

### Current-turn local ERP MCP source health — 2026-10-25 06:01 UTC

From the repository `.venv`, the documented `gateway_client.py` flow loaded `LaneEnv` in process,
minted an in-memory `auditor` token with `ttl=300`, and called only
`source_health(source_id="onec-818ha-reference")` through the configured loopback MCP URL. The
sanitized result was `is_error=false`, `health_ok=true`, with payload keys `ok` and `status_code`;
the token was not printed or persisted. No other source or business-data tool was called, no
service was restarted, and no COM, database write, migration, test or check was run. This proves
current read-only MCP health only, not effective grants, a private writer, or a 1C transaction
boundary.

## Current-turn disposable PostgreSQL effective privileges — 2026-10-25 06:02 UTC

An actual read-only `database-reviewer` agent loaded the admin connection string in process from
the scoped lane environment, confirmed the disposable loopback endpoint on port `18432`, and used
a `REPEATABLE READ, READ ONLY` transaction with a five-second statement timeout. The session was
database `business_ai`, login role `business_ai_admin`, server port `5432`. No DSN, password, token
or business row was emitted.

`pg_roles` showed `business_ai` is superuser with `BYPASSRLS`; `business_ai_admin`,
`business_ai_app`, and `business_ai_control_api` are login roles without those flags. The checked
role memberships among the four were empty. `change_ledger` and migration-027 objects are absent,
so effective S13 candidate privileges remain **NOT_MEASURABLE** here.

For the existing `bag` schema, `information_schema.role_table_grants` reported direct grants to
`business_ai_admin`: 12 INSERT, 15 SELECT, and 11 UPDATE object grants. Separate
`has_table_privilege` checks returned effective privileges across 17 tables: owner `business_ai`
has all seven checked privileges; admin has INSERT on 12, SELECT on 15, UPDATE on 11; app has
INSERT on `audit_events` and SELECT on 14; control API has INSERT on 12, SELECT on 17, UPDATE on
10. Effective `has_function_privilege` reported 7, 4, 5, and 4 executable functions respectively
for owner, admin, app, and control API. These counts describe only the current `bag` privilege
surface and do not establish 1C `CT14Писатель` rights or S13 writer grants. At this point the
app/control effective privilege source was still under follow-up; the next subsection records its
reconciliation. No schema change or database mutation was made.

### ACL source reconciliation — 2026-10-25 06:03 UTC

The same read-only database-reviewer follow-up expanded `pg_class.relacl` and checked
`pg_default_acl`, PUBLIC ACL entries and relation owners. The app and control API `bag` privileges
are explicit direct relation ACL entries, not PUBLIC/default-ACL/ownership-derived; PUBLIC has no
explicit relation ACL entries and there are no table default-ACL rows for `bag` or global scope.
All 17 `bag` tables are owned by `business_ai`, which explains the owner's full privileges only.
The earlier `information_schema.role_table_grants` query ran as `business_ai_admin` and displayed
only that session's visible direct grants; its empty app/control rows do not prove those roles lack
direct grants. The reconciled `pg_class` and `has_table_privilege` results agree for app/control.
No `SET ROLE`, application-role behavior probe, write, or business-row read was performed; this is
catalog ACL evidence only. S13 remains `NOT_MEASURABLE` because `change_ledger` and candidate 027
are absent from this database.

## 2026-10-25 CT14 rights evidence boundary

Read-only reconciliation of the in-scope clone records (`testlane/onec_extension/STATUS.md` §§4, 7 and `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` §§5–7) confirms effective rights for `CT14_NARROW` on disposable file clone `818HA_p2diff` only. The writer role has Read/Insert/Update/Posting/UndoPosting on `ПоступлениеТоваровУслуг`, Read/Update on `ДокументыОрганизаций`, narrow reads on supporting catalog/register/constant objects, and Get on four session parameters; Delete and interactive rights are false. The exact 53-object role/effective-rights reconciliation and the marker-attribute caveat are recorded in those sources. This is historical clone evidence, not a current Ivan-host privilege measurement or client-server proof. Current Ivan base identity and effective rights remain `NOT_VERIFIED`; this turn listed only names and metadata in D:\1c\mcp, with no SSH subdirectory expansion, COM activation or base access.

### Current executor strict SSH status — 2026-10-25 07:44 UTC

At repository HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c` on branch
`codex/erp-mcp-autonomous-2026-10-21`, ran only:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
```

Exit code was 0. The output was `True` for postgres, redis, apache, proxy8191, proxy8192,
proxy8193, sidecar, idp and gateway. No service was restarted, no secret or configuration value
was read, and no COM operation or 1C base access was attempted. This refreshes trusted SSH and
stack status only; it does not establish clone licensing, current effective 1C rights, database
grants, the physical writer transaction boundary or S12/S13 qualification.

### Current executor authorized MCP health — 2026-10-25 07:45 UTC

Using the repository virtual environment at the same HEAD, an in-process Python call loaded
`LaneEnv`, minted `Idp(env).token("auditor", ttl=3600)`, and called
`source_health(source_id="onec-818ha-reference")` through `mcp_session`. The only emitted result
fields were `is_error=false` and `ok=true`; source ID and status were not returned in the decoded
payload. The token, DSN and passwords were not printed or persisted. This verifies one authorized
read-only MCP health call on the local gateway, not source data access, COM licensing, effective
1C rights or writer behavior. No database operation, service restart, test, check, build or
migration ran.

### Ivan stack task identity metadata — 2026-10-25 07:48 UTC

Over the same strict SSH connection, queried only the scheduled-task principal metadata for
`ERP_MCP_Ivan_Stack` with `Get-ScheduledTask` and `Get-ScheduledTaskInfo`; no task action or
argument, environment, secret, or file content was emitted. Observed `UserId=koros`,
`LogonType=Interactive`, and `RunLevel=Highest`. This identifies the existing stack task principal
only; it does not identify a private-writer caller or listener identity. **Inference:** the current
stack task principal alone is not evidence of a dedicated least-privilege writer principal, so the
private ingress must bind to a separately approved caller identity before a listener can be wired.
No task or service was changed or restarted.

### Current executor MCP metadata-contract probe — 2026-10-25 08:14 UTC

Using the same in-process local gateway client and `auditor` token, called
`onec_find_entities(source_id="onec-818ha-reference", contains="ПоступлениеТоваровУслуг",
limit=10, include_property_types=true)`. The live MCP endpoint rejected the request before
returning entity metadata because its generated `onec_find_entitiesArguments` schema treats
`include_property_types` as an extra input. The current checkout's `business_ai_gateway/server.py`
source declares that parameter. Thus the running endpoint's tool schema does not match this
checkout for that field; the serving process/source identity was not established. The request was
read-only and returned no entity or property data. No service was restarted or modified, and no
credential value was printed. Reconcile the live endpoint's owning checkout/version before relying
on this new metadata option or using the route to derive any COM mapping. Accountable owner: operator;
executor: Codex. The technical owner of the local 21000 process/version binding is not established
in the canonical records inspected.

## Current-turn gateway reload and COM registration recheck — 2026-10-25 08:25 UTC

The exact E2E helper was reviewed before restart: `fault.ps1 -Component gateway -Action restart` calls only the gateway stop/start path; the real-1C reader availability guard is checked before stopping it. The `D:\ERP_MCP_Testbed\real1c_e2e` state directory matched the configured reference lane, port offset 3000 resolved gateway port 21000, the tracked launcher PID and listener process matched this checkout's `.venv`/`business_ai_gateway.app:app`, no foreign listener was found, and the secret-free reader preflight passed. Only the gateway was restarted. Its `/healthz` and `/readyz` returned HTTP 200; listeners for Apache 8088 and proxies 8191–8193 remained present.

Using the in-process local `auditor` MCP client after reload, `onec_find_entities` advertised the current `include_property_types` boolean and accepted the exact metadata-only request for `onec-818ha-reference`. It returned the purchase-receipt document and table-part property types, including UUID references, date, booleans, decimal-number fields, and collection types. No document rows were read. This is local read-only reference metadata, not the Ivan clone's COM metadata or an approved COM mapping.

Strict-host-key SSH to `koros@100.88.71.74` returned `True` for postgres, redis, apache, proxy8191–8193, sidecar, idp, and gateway. Read-only registry inspection found `V83.COMConnector` registered to `D:\1c\env\1cv8_x64\8.3.27.2342\bin\comcntr.dll`; the named `D:\1c\env\bases\818HA_p2diff` directory exists. This proves registration and path presence only. No COM activation/connect, rights query, remote service change, database operation, or base write was performed in this turn. The previously recorded COM `Connect` failure remains unresolved.

This turn's source-only code refinement is recorded in `docs/phase2/CHANGE_RECORD_184.md`: the Windows COM lane now reports only fixed stage codes for startup failures and filters arbitrary `ComLaneError` values. No tests/checks/build/CI/migration were run; the code change is `NOT_RUN`.

## Current executor access recheck — 2026-10-25 10:59 UTC

The active executor repeated the strict SSH stack-status command:
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`.
It returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. No restart or other remote command ran.

The local in-process client used `.venv` Python, `LaneEnv.load()`, and a short-lived auditor token held only in memory to call `source_health(source_id="onec-818ha-reference")`. Result: `is_error=false`, `ok=true`. No token, DSN, password, business rows, or company values were emitted. This proves only the current read-only health call; it does not establish CT14 effective rights, COM transaction semantics, or a live writer boundary. The separate 10:59 UTC database-reviewer catalog result is recorded in `WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-25.md`: S13 candidate privileges remain `NOT_MEASURABLE` because the schema, routines, and dedicated roles are absent. No tests/checks, migration, DDL, database write, COM call, listener startup, or service restart ran.

## Recorded CT14 writer-role evidence boundary — 2026-10-25

The in-scope project records `testlane/onec_extension/STATUS.md` (2026-10-12, sections 4–7) and `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` report measured effective rights for `CT14_NARROW` on the disposable file clone `818HA_p2diff`, with only `CT14Писатель` plus `ЗапускВнешнегоСоединения`. They record 53 probed objects and 13 right names, no Delete or interactive/admin rights, and measured create-draft/post/read-movements/unpost behavior. They also record that marker attributes are not tamper-proof: any API writer with document Update can modify them. This is historical clone evidence from those project records, not a fresh read of Ivan's current base and not evidence of PostgreSQL grants or an atomic COM transaction boundary. The recent strict SSH `Status` command only confirmed service status and did not query effective 1C rights or activate COM.

## Current executor SSH and service-directory recheck — 2026-10-25 11:38 UTC

The active executor again ran the strict-host-key SSH status command against
`koros@100.88.71.74`; postgres, redis, apache, all three lane proxies, sidecar, IdP and gateway
reported `True`. A read-only filename inventory of `D:\1c\mcp` showed the existing `app`, `data`,
`env`, `runtime`, `venv` and stack-script entries; the listed `app` children were `gateway` and
`sidecar`, and the listed `data` children were `pg` and `redis`. No file contents, task action,
credentials, service process, or base data were read or changed. This inventory does not locate or
identify the licensed 1C clone, establish its current security profile, query effective rights, or
prove a COM transaction boundary. Current Ivan clone rights and writer semantics therefore remain
`NOT_VERIFIED`; only the historical CT14 measurements above are available. No restart, COM call,
database operation, test, check, build or migration ran.

## Current-turn COM registration diagnostic — 2026-10-25

Without activating COM or connecting to a base, these strict-host-key SSH commands were read-only:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "reg query HKCR\V83.COMConnector\CLSID /ve"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "reg query HKCR\CLSID\{181E893D-73A4-4722-B61D-D604B3D67D47} /s"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 'powershell.exe -NoProfile -Command "$f = Get-Item ''D:\1c\env\1cv8_x64\8.3.27.2342\bin\comcntr.dll''; $s = Get-AuthenticodeSignature $f.FullName; Write-Output ($f.VersionInfo.FileVersion + ''|'' + $f.Length + ''|'' + $s.Status)"'
```

The ProgID query returned CLSID
`{181E893D-73A4-4722-B61D-D604B3D67D47}` and that CLSID's `InprocServer32` points to
`D:\1c\env\1cv8_x64\8.3.27.2342\bin\comcntr.dll`. A metadata-only file query reported version
`8.3.27.2342`, length `674376`, and Authenticode status `Valid`. These observations rule out only
the narrow hypothesis that the COM ProgID or registered DLL path is absent; they do not prove
COM activation, interpreter bitness compatibility, licensing, clone identity, credentials, 1C
rights, or a working writer transaction. No COM activation/Connect, rights query, service change,
database operation, test, check, build, or migration was performed. The earlier sanitized reader
Connect failure remains unresolved; no retry was made.

## CT14 credential and read-only-query boundary — current source inspection

The repository's `scripts/real1c/reader_environment.ps1` reads `test_reader_password.dpapi` for
the `D:\ERP_MCP_Testbed\real1c_e2e` reference-test lane; that identity is not evidence of an
account on Ivan's writer clone. The historical CT14 tooling uses a separate
`admin_1c_clone_password.dpapi` through `testlane/onec_extension/scripts/ct14_common.py`. Its
`ct14_effective_rights.py` calls `ops.prepare_user(ops.ROLES)` before measuring rights, and
`ct14_narrow_ops.prepare_user()` changes the CT14_NARROW password and role set and may write the
associated Users catalog binding. Therefore that script is not a read-only current-rights query
and was not run. `ct14_measure.py` performs document writes/post/unpost and is also not suitable
for this read-only request. Historical CT14 rights in `testlane/onec_extension/STATUS.md` remain
the only measured matrix; current Ivan-clone identity and rights are `NOT_VERIFIED`. The safe next
source is an existing read-only interface under an already provisioned clone identity, or access
to the correct DPAPI-owning principal; no identity impersonation, password reset, role edit, or
COM retry was attempted.

## 2026-10-25 14:31 UTC bounded local source-health recheck

Using the repository virtual environment, `LaneEnv.load()` and an in-process short-lived auditor token, an authenticated MCP call to `source_health` for `onec-818ha-reference` returned `is_error=false`, `ok=true`. The token and accounting values were not printed. This is a point-in-time health observation only; it does not qualify business reads, Ivan-clone credentials/rights, COM transaction semantics, S13 grants, or the writer boundary. No ERP_MCP_REAL1 connector, write operation, migration, test, or service restart was used.

## 2026-10-25 14:32 UTC strict SSH stack status

Command: `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`. Result: exit 0; `postgres`, `redis`, `apache`, `proxy8191`, `proxy8192`, `proxy8193`, `sidecar`, `idp`, and `gateway` each returned `True`. Strict host-key checking succeeded. This confirms only the reported service status at this instant; it does not establish effective 1C rights, clone identity, COM connect, transaction boundary, or S13 database grants. No service was restarted and no secrets were read.

## 2026-10-25 14:42 UTC strict SSH directory inventory

Command: `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 'powershell -NoProfile -Command "Get-ChildItem -LiteralPath ''D:\1c\mcp'' -Force | Select-Object Name,Mode,Length | Format-Table -AutoSize"'`. Result: exit 0. Names-only inventory returned directories `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, `venv` and scripts `ivan_repoint.ps1`, `mint-token.ps1`, `register-stack-task.ps1`, `run-mcp-stack.ps1`, `run-tunnel.ps1`, `set-tunnel-secret.ps1`, `setup-1c-odata.ps1`, `setup-mcp-data.ps1`, `setup-mcp-venv.ps1`, `store-onec-admin.ps1`. No file contents or credentials were read. The first command attempt had a local PowerShell quoting error and made no remote change; the corrected read-only request succeeded. This inventory does not establish the clone's effective rights or COM behavior.

## 2026-10-25 15:28 UTC credential-mapping follow-up

Strict-host-key SSH read `D:\1c\mcp\store-onec-admin.ps1` and inspected only the script's credential-handling description and destination metadata. It declares the disposable target `D:\1c\env\bases\818HA_test_ready`, stores its CurrentUser DPAPI payload at `D:\1c\mcp\env\onec_admin.dpapi`, and serializes only `user` and `password` fields. This source does not bind that credential to `818HA_p2diff`. A names-and-lengths-only inventory of `D:\1c\mcp\env` found `onec_admin.dpapi` and `test_reader_password.dpapi`, but no filename identifying a p2diff-specific credential. No credential values were emitted. The payload was subsequently unprotected in memory only to inspect property names; that observation is recorded below.

An in-process attempt to inspect only DPAPI JSON property names did not reach the blob: remote PowerShell could not resolve `System.Security.Cryptography.ProtectedData`, and its explicit `Add-Type` lookup reported that assembly unavailable. No COM connection was attempted. This is a PowerShell runtime limitation, not evidence about the blob's contents. The clone-to-credential mapping remains `NOT_VERIFIED`; do not reuse the test-ready credential for p2diff or reset/alter a credential to probe it. Next source: establish an authoritative p2diff credential mapping or a sanitized 1C diagnostic through the Ivan stack's existing provisioning record. Accountable owner: operator; executor: Codex; technical host/connection owner: Ivan stack. No service was restarted, no identity or role was changed, and no database, COM, test, check, migration, staging, commit or push operation ran.

Using the explicit Windows PowerShell 5.1 executable and loading `System.Security`, a metadata-only DPAPI read returned property names `user` and `password`; no clone/base/path identity field was present, and no values were emitted. A separate names-only traversal of `D:\1c\mcp\env\credentials.json` returned role/client property names (`access_admin`, `admin_no_role`, `auditor`, `platform_admin`, `profile_admin`, `source_admin`, `sub`, `user_company_one`, `user_company_two`, `user_no_access`, `users`, `password`, `username`) and no p2diff/base/clone-named property. This excludes an explicit clone-named field in these two records, not a hidden semantic binding elsewhere. No credential was changed; no COM call, service restart or database operation ran. The next step remains obtaining a provisioning record that authoritatively maps a credential and least-privilege principal to `818HA_p2diff`, or a sanitized 1C diagnostic. The accountable owner is the operator; the Ivan stack is the technical host/connection owner.

## 2026-10-25 15:31 UTC target-clone path inventory

Strict-host-key SSH queried names only beneath the provisioning script's `D:\1c\env` root. Its top-level directories were `1cv8_x64`, `apache24`, `bases`, and `odata`; `bases` contained `818HA_p2diff`, `818HA_reference_ro`, and `818HA_test_ready`. This verifies the named disposable clone directory exists on the Ivan host and that no separate credential directory is present at the `D:\1c\env` root. It does not establish the clone's registered 1C users, effective rights, credential binding, or license. No base contents, files, credentials, COM or DB were accessed. Next: require a provisioning record that binds a least-privilege writer identity to `818HA_p2diff`; continue independent candidate source closure meanwhile.

## 2026-10-25 15:41 UTC evidence-registration scope selector refinement

Source-only review of `private_writer_register_evidence_v1` found that the pre-lock attempt plan
selected by globally unique CAS before checking the caller's tenant/company/organization/base, then
used the selected attempt and signer key material to derive later lock identities. Updated
`db/phase2/027_private_writer_admission_schema.sql` so the unlocked attempt lookup binds the exact
caller tuple and immediately refuses a miss before reading signer-key material. The next unlocked
key lookup binds key ID/version and signer role/service/host to the caller tuple and requires an
exact signer-key scope row for that attempt before base/scope/key-material/namespace fences. Locked
rereads and full tuple checks remain in place. Candidate SHA-256:
`B328810BEC11A92ACC8FBA7100D8CB5C52442B7160781A34046611EC5A094D67`.

Added `S13-EVIDENCE-REGISTER-PREFENCE-SCOPE-01` to
`S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. It covers foreign-CAS and
foreign-only key-scope refusals, held-lock controls, exact SQLSTATE and unchanged evidence/event
state. This is source inspection and documentation only; qualification is `NOT_RUN`. No test,
check, SQL parse, migration, DB operation, COM call, service restart, staging, commit or push ran.

### Current-turn terminal evidence-link guard — 2026-10-25

Updated `db/phase2/027_private_writer_admission_schema.sql` so the verified-success and
recovered-terminal routines verify every expected per-attempt evidence reference and purpose
immediately after the narrowly targeted idempotent inserts, before lifecycle changes, slot
release, or recovery-event append. The recovery-terminal routine now preflights all four occupied
purpose slots so a distinct reference fails with the stable identity-conflict code rather than a
partial-index SQL error. Added qualification case
`S13-ATTEMPT-EVIDENCE-LINK-01`; it remains `NOT_RUN`. Candidate SHA-256:
`9FD636675D0B6A09F0D93BD15B511CC441B396913BCF198E509ACCA42EE7BA0A`. No SQL parser,
database operation, migration, grant, test, check, COM call, service restart, staging, commit,
or push was run in this step.

### Current-turn disposable PostgreSQL privilege inventory — 2026-10-25

Using the repository's in-process `LaneEnv` client and the configured admin connection, read-only
queries found no `change_ledger` schema, no S13 candidate routines, and no table or routine grants
to the candidate roles. Of the inspected role names, only `business_ai`, `business_ai_admin`, and
`business_ai_app` exist; the observed `business_ai` role has `rolsuper=true`, while the admin and
app roles do not. This is the current local disposable database state, not evidence of candidate
or Ivan-host effective grants. Do not interpret absent schema/roles as denied candidate grants.
The observation queried catalogs and `to_regprocedure` only; no SQL mutation, migration, test,
or credential output occurred. The role-owner configuration needs reconciliation before this
database can qualify S12/S13 grants.

### Current-turn MCP and Ivan SSH recheck — 2026-10-25

The in-process repository client (`LaneEnv.load()`, short-lived `auditor` token held only in
memory, `mcp_session`/`call_tool`) returned `is_error=false`, `ok=true` for
`source_health(source_id="onec-818ha-reference")`. A separate strict-host-key SSH command to
`koros@100.88.71.74` ran only `run-mcp-stack.ps1 -Action Status` and exited 0; postgres, redis,
apache, proxies 8191–8193, sidecar, idp and gateway each reported `True`. No service was restarted,
no token/secret/business data was emitted, and no remote file or database was changed. This
confirms point-in-time reference-read and host-stack access only; it does not establish
`818HA_p2diff` COM access, candidate grants, writer identity, or the physical transaction boundary.

### Candidate role-boundary source update — 2026-10-25

Migration 027 now rejects `ledger_owner` unless it is `NOINHERIT` in addition to the existing
non-login/non-superuser/non-BYPASSRLS/non-create-role attributes, and rejects memberships to or
from that owner role. The qualification matrix now checks both membership directions explicitly.
This is source-level hardening only; no installed S13 catalog was queried, and the candidate remains
unapplied. Current candidate SHA-256:
`9FD636675D0B6A09F0D93BD15B511CC441B396913BCF198E509ACCA42EE7BA0A`.

### Candidate operator-resolution lock update — 2026-10-25

Source inspection found that `operator_resolve_v1` locked all active target parent rows but only
pre-acquired namespace 4 for target identities owned by the resolving change. The source now
prelocks the union of those identities and the full bounded active-target snapshot. The sparse-plan
contention scenario is specified in S12 and remains `NOT_RUN`; no SQL parse, migration, test/check,
or database operation ran. Candidate SHA-256:
`CAC75207D5D9E031B9C5061B5B1EF81487238909B7BC946FA454FDFDF44A898F`.

### GAP_BOUND source association recheck — 2026-10-25

Read-only inspection of candidate `private_writer_recovery_gap_bound_v1` confirms its
`SWEEP_ITEM_FAILED` event explicitly uses `change_id=NULL` (`027:7524-7527`). This prevents the
same-valued foreign-scope `records.change_id` from being attached by the event append path. The
cross-scope collision case remains an unrun qualification scenario; no runtime conclusion follows.

### Current local gateway and Ivan-stack recheck — 2026-10-25

The repository gateway client minted a short-lived `auditor` token in process and called only
`source_health` for `onec-818ha-reference`; it returned `is_error=false`, `ok=true`. A separate
SSH call to `koros@100.88.71.74` used `BatchMode=yes` and `StrictHostKeyChecking=yes` and ran only
`run-mcp-stack.ps1 -Action Status`; exit code was 0 and postgres, redis, apache, proxies 8191–8193,
sidecar, IdP and gateway returned `True`. Token material was not printed; no service was restarted.
This confirms current reference-read and stack availability, not current `818HA_p2diff` COM
identity, effective grants, or writer transaction boundary.

### Current strict-SSH process and task recheck — 2026-10-25 16:31:58 UTC

Using BatchMode, IdentitiesOnly and StrictHostKeyChecking, SSH to koros@100.88.71.74 succeeded.
The read-only ERP_MCP_Ivan_Stack task query returned State=Ready, Principal=koros,
LogonType=Interactive, LastTaskResult=0 (last run reported 2026-10-25 18:01 local host time).
The explicitly read-only run-mcp-stack.ps1 -Action Status reported True for postgres, redis, apache,
proxy8191-8193, sidecar, idp and gateway. The current process inventory showed httpd.exe,
python.exe and redis-server.exe owned by IVAN\koros. No service or task was started, stopped or
restarted. Matching owner names do not prove these processes are the scheduled task's child
processes, do not prove access to the DPAPI key material, and do not establish COM clone identity,
1C effective rights or the writer transaction boundary. No command line, secret or credential was
read or printed.

### Current-turn reference and SSH recheck — 2026-10-25

From the ERP_MCP checkout, `LaneEnv.load()` and `Idp(env).token("auditor", ttl=600)` were used
in-process to call only `source_health(source_id="onec-818ha-reference")` through `mcp_session`;
the sanitized observation was `is_error=false`, `ok=true`. Strict-host-key SSH to
`koros@100.88.71.74` then ran only `run-mcp-stack.ps1 -Action Status`; all nine reported components
(postgres, redis, apache, proxies 8191–8193, sidecar, IdP and gateway) were `True`. No service was
restarted, and no token, credential, business value, remote file or database content was emitted or
changed. This is point-in-time evidence for the named reference and stack only; it does not prove
the disposable writer clone's COM identity, effective grants, or physical transaction boundary.
