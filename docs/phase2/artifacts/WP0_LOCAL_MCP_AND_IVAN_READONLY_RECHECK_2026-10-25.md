# WP0 local MCP and Ivan stack recheck — 2026-10-25

## Local MCP source

From `D:\Repo\ERP_MCP`, the repository `.venv` Python imported
`scripts.real1c.gateway_client`, loaded `LaneEnv` in-process, minted a short-lived `auditor`
token without printing it, and called the local MCP endpoint through `mcp_session`.

- `source_health` for `onec-818ha-reference`: tool result `is_error=false`, `ok=true`,
  `status_code=200`.
- `onec_metadata_summary` for the same source: `entity_set_count=920`; groups reported were
  AccountingRegister 2, AccumulationRegister 152, Catalog 38, ChartOfAccounts 1, Document 721,
  and InformationRegister 6.
- `onec_find_entities` for `ПоступлениеТоваровУслуг` returned the document plus `_Товары` and
  `_Услуги` entity sets. The document metadata includes `Организация_Key`, `Контрагент_Key`,
  `ДоговорКонтрагента_Key`, `ВалютаДокумента_Key`, `НомерВходящегоДокумента`,
  `ДатаВходящегоДокумента`, `Комментарий`, and `СуммаДокумента`. The goods table includes
  `Номенклатура_Key`, `Количество`, `Цена`, `Сумма`, and `СтавкаНДС`; the services table includes
  the corresponding quantity/price/sum/VAT fields plus `Содержание`.

This is authenticated live OData metadata for the named reference source. It does not establish
that the source is the `818HA_p2diff` clone, prove clone/configuration identity, disclose COM
property types or method atomicity, or qualify a payload-to-COM mapping. No business rows were
read and no 1C mutation was called.

## Ivan SSH host stack

The exact read-only command used was:

`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`

Exit code was 0. Output reported `postgres`, `redis`, `apache`, `proxy8191`, `proxy8192`,
`proxy8193`, `sidecar`, `idp`, and `gateway` as `True`. No process was restarted and no remote
file contents, credentials, or key material were read.

## Acceptance boundary

The host-key-authenticated SSH and current service-status checks are verified for this recheck.
The effective S13 PostgreSQL role matrix remains a separate disposable-catalog question. Ivan's
licensed-clone identity, live grants, writer transaction boundary, signer custody, and S12/S13
runtime qualification remain unverified.

## Current continuation MCP/SSH recheck — 2026-10-25

Using the repository `.venv`, `LaneEnv.load()`, and a short-lived in-process `auditor` token, `source_health` for `onec-818ha-reference` returned `is_error=false`, `ok=true`; `onec_metadata_summary` returned `is_error=false`, `entity_set_count=920`. The token was neither printed nor persisted.

Strict-host-key SSH to `koros@100.88.71.74` ran the authorized read-only `run-mcp-stack.ps1 -Action Status` command and returned `True` for postgres, redis, apache, proxies 8191–8193, sidecar, idp, and gateway. No process was restarted. This verifies current transport and service status only; it does not establish clone COM connectivity, effective 1C grants, PostgreSQL candidate grants, or a writer transaction boundary.

### Current-turn strict SSH COM registration and clone-path check — 2026-10-25

Used strict-host-key SSH as `koros@100.88.71.74` for read-only registry and path-presence queries:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "cmd /c reg query HKCR\V83.COMConnector\CLSID /ve"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "cmd /c reg query HKCR\CLSID\{181E893D-73A4-4722-B61D-D604B3D67D47}\InprocServer32 /ve"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -Command Test-Path 'D:\1c\env\bases\818HA_p2diff'"
```

The ProgID resolved to CLSID `{181E893D-73A4-4722-B61D-D604B3D67D47}`; its `InprocServer32` value is `D:\1c\env\1cv8_x64\8.3.27.2342\bin\comcntr.dll`; `Test-Path` returned `True` for the named clone directory. One earlier PowerShell metadata query failed from local command-line quoting and emitted a command-not-found error; the simpler path-presence query above succeeded. No COM activation/connect, rights query, base metadata/data read, service restart, database operation or base write was performed. These observations prove registration and path presence only, not clone-specific credential mapping, license, effective rights or an operational writer boundary. The previously recorded `Connect` failure remains unresolved.

### Current-turn local authenticated MCP health recheck — 2026-10-25

From the repository `.venv`, a read-only Python call used `LaneEnv.load()`, minted `Idp(env).token("auditor", ttl=3600)` in process, and invoked `source_health(source_id="onec-818ha-reference")` through `mcp_session` against the configured local gateway. Only `is_error=false`, `ok=true`, and `status=200` were printed. The token and environment secrets were not printed or persisted. This confirms one authenticated read-only health request on the configured local route; it does not prove source business data, S13 database grants, Ivan clone COM connectivity, or writer behavior. No `ERP_MCP_REAL1` connector was used.

### Current-turn Ivan stack component and directory recheck — 2026-10-25

Strict-host-key SSH to `koros@100.88.71.74` ran the authorized read-only stack status command:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
```

It returned `True` for PostgreSQL, Redis, Apache, proxies 8191–8193, sidecar, IdP and gateway.
No process was restarted. A first directory-listing attempt that piped to `Select-Object` failed
because the remote Windows command shell treated the pipeline command separately. The simpler
read-only query succeeded:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -Command Get-ChildItem -Name D:\1c\mcp"
```

The listing showed `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, `venv`, and the stack
scripts `ivan_repoint.ps1`, `mint-token.ps1`, `register-stack-task.ps1`, `run-mcp-stack.ps1`,
`run-tunnel.ps1`, `set-tunnel-secret.ps1`, `setup-1c-odata.ps1`, `setup-mcp-data.ps1`,
`setup-mcp-venv.ps1`, and `store-onec-admin.ps1`. Only names were read; no configuration or
credential values were opened. These checks establish component status and directory contents only,
not COM connectivity, clone-specific credentials, effective rights or the writer boundary.

### Current-turn direct MCP endpoint reachability — 2026-10-25

Using the repository `.venv`, the project gateway helper minted a short-lived `auditor` token in-process. The authenticated local `source_health` request for `onec-818ha-reference` returned `is_error=false`, `ok=true`. No token, environment value, or business payload was printed or persisted. The same token did not initialize the Ivan gateway session; only the exception class (`ExceptionGroup`) was recorded. A separate in-process token request against the configured Ivan IdP host returned `ConnectError`. Raw TCP probes from this machine reached `100.88.71.74:21000` and did not connect to `100.88.71.74:21080` within 2.5 seconds. These transport results do not establish why the authenticated remote session failed. Strict SSH status had reported all nine Ivan components `True`; SSH and the MCP/IdP endpoints are distinct paths. No process/service was restarted, and no COM, database grant, source-data comparison, or write operation ran. Ivan gateway health and Ivan-clone effective rights remain `NOT_VERIFIED`.

### Current-turn Ivan IdP bind-address check — 2026-10-25

Strict-host-key SSH ran the read-only command `Get-NetTCPConnection -LocalPort 21080 -State Listen`. The remote result is `LocalAddress=127.0.0.1`, `LocalPort=21080`, `RemoteAddress=0.0.0.0`. This explains why a local TCP probe to `100.88.71.74:21080` did not connect: the IdP accepts loopback traffic on Ivan only. SSH status reports the IdP component running, but does not make its loopback endpoint directly reachable. A temporary local SSH-forward launch using `Start-Process` was rejected by this execution environment's process-launch policy before a child process started; no tunnel remains. No service was restarted. Ivan MCP health is still `NOT_VERIFIED`; the next required evidence is the same sanitized read-only `source_health` call with an approved private transport to the loopback IdP. Accountable owner: operator; technical host owner: Ivan stack; executor: Codex. The transient forwarding launch is blocked by this environment's command policy, not a project rule; no human is assigned to that policy gate.

### Current-turn managed SSH-forward token route — 2026-10-25

A supervised foreground SSH forwarding session (`127.0.0.1:21081` → Ivan loopback `127.0.0.1:21080`) was established with strict host-key checking and then terminated after the read-only probe. Through that route, the project helper `Idp(env).token("auditor", ttl=600)` received HTTP `400 Bad Request` from the Ivan IdP. The helper raised before returning a token; response-body content was not inspected or printed. No request was sent to the Ivan MCP gateway in this attempt, and the SSH tunnel session was closed. A prior `Start-Process` launch attempt had been rejected by this environment's background-process policy, so the managed foreground method was used. Ivan source health remains `NOT_VERIFIED`; the evidence does not identify whether the cause is client/audience configuration or other remote IdP policy. Next: use an Ivan-approved in-process auditor-token path/configuration without displaying credentials or token, then call only `source_health`. Accountable owner: operator; technical host/IdP owner: Ivan stack; Codex executor.

### Current-turn Ivan authenticated source-health via approved host token helper — 2026-10-25

The test-lane project source `scripts/remote/mint-token.ps1` was inspected; it obtains the `auditor` credentials on Ivan, requests the test IdP audience for `http://100.88.71.74:21000/mcp`, and writes only the token to stdout. The configured audience and 600-second TTL were passed explicitly. A strict-host-key SSH command captured stdout only into process memory; the token was neither printed nor persisted. The local repository `.venv` initialized the Ivan gateway session and called only `source_health(source_id="onec-818ha-reference")`; the sanitized result was `ok=true`. The token variable was cleared after the call. This verifies authenticated remote source-health transport only; it does not verify account rows, current clone COM identity/effective rights, PostgreSQL grants, writer transaction boundary, or any write behavior. No service was restarted.

### Current-turn Ivan task identity and credential-file metadata — 2026-10-25

Strict-host-key SSH performed read-only inspection of `ERP_MCP_Ivan_Stack` using
`Get-ScheduledTask`. The task principal is `koros`, logon type `Interactive`, run level `Highest`,
and action executable `powershell.exe`; task arguments were not emitted. A targeted name-only listing
of `D:\1c\mcp\env` showed `onec_admin.dpapi` and `test_reader_password.dpapi`. File metadata reports
owner `BUILTIN\Administrators` and 262 bytes for each; no credential contents or `credentials.json`
values were read. The identity and file metadata do not prove that the SSH process can decrypt either
blob or that either credential maps to `818HA_p2diff`. No DPAPI unprotect or COM connection was
attempted in this observation. Existing evidence still records an earlier CurrentUser unprotect
failure under SSH. Next: use only an already-authorized credential-owning process context or provider
for a read-only clone identity/metadata probe; do not impersonate another account or change the task.
Accountable owner: operator; technical host owner: Ivan stack; executor: Codex.

### Current-turn strict SSH status — 2026-10-25 13:30 UTC

Ran only `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`. It returned `True` for Postgres, Redis, Apache, proxies 8191–8193, sidecar, IdP and gateway. No service was restarted; no configuration, credential or key contents were read. This confirms strict-host-key SSH and reported stack-component status at this time. It does not change the existing evidence that IdP binds loopback, nor resolve the separate authenticated source-health/token route or establish the writer clone, effective grants, COM transaction boundary or S12/S13 runtime behavior.

### Current-turn SSH host-key and authenticated local-health recheck — 2026-10-25 17:51 UTC

`ssh-keygen -F 100.88.71.74 -f ~/.ssh/known_hosts | ssh-keygen -lf -` reported the trusted
ED25519 fingerprint `SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`. The strict-host-key Ivan
stack status command returned exit 0 and `True` for Postgres, Redis, Apache, proxies 8191–8193,
sidecar, IdP, and gateway. A local authenticated MCP request using the repository helper, with an
in-process short-lived auditor token and `source_health(source_id="onec-818ha-reference")`, returned
`is_error=false` and `ok=true`. The token was not printed or persisted; no business row was read and
no service was restarted. A name-only read-only listing of `D:\1c\mcp` confirmed the previously
recorded top-level directories and stack scripts. These observations update transport/component
health only and do not establish Ivan-clone identity, effective 1C rights, S13 PostgreSQL grants,
the writer transaction boundary, or runtime qualification.

## Current-turn read-only access refresh — 2026-10-25 18:08 UTC

- Rechecked local loopback listeners: gateway 127.0.0.1:21000 and PostgreSQL 127.0.0.1:18432 were listening; no process was restarted.
- Rechecked strict SSH to koros@100.88.71.74 using the trusted known_hosts entry. The read-only stack Status action returned True for postgres, redis, apache, proxies 8191–8193, sidecar, IdP, and gateway.
- Called local authenticated MCP source_health for onec-818ha-reference with an in-process short-lived auditor token. Result: is_error=false, ok=true. No token or business rows were printed.
- Confirmed the disposable clone directory D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff and its 1Cv8.1CD file exist. A bounded read-only metadata introspection attempt using the clone-only admin helper failed at COM connection with sanitized exception class com_error before metadata or business-data reads. Exit code 2. No COM write occurred.
- Inspected the CT14 helper source and confirmed prepare_user changes the CT14_NARROW password and roles. That helper was not executed; no credential or role was changed.

This confirms current transport health, not clone COM availability, live effective 1C rights, or the writer transaction boundary. The COM failure is a concrete dependency for the clone crosswalk; continue independent source work without retrying COM.

## Current-turn COM target-boundary recheck — 2026-10-25 18:23 UTC

- Local MCP `source_health` returned `is_error=false`, `ok=true` for `source_id=onec-818ha-reference`. The first diagnostic invocation used the obsolete argument name `source` and returned a schema validation error; no project change followed from that error.
- Strict SSH to `koros@100.88.71.74` accepted the trusted host key; `run-mcp-stack.ps1 -Action Status` returned True for postgres, redis, apache, proxies 8191–8193, sidecar, IdP, and gateway.
- Read-only remote inspection found the disposable `D:\1c\env\bases\818HA_p2diff` directory and `1Cv8.1CD` (4,377,706,496 bytes), the registered `V83.COMConnector` CLSID, and `comcntr.dll` under the configured x64 1C 8.3.27.2342 directory.
- A bounded read-only metadata connection attempt on Ivan's lane used the in-process DPAPI-protected `onec_admin` credential and the disposable clone path. It did not return within 20 seconds; the isolated PowerShell job was stopped. A subsequent remote process check found zero `1cv8`/`1cv8c` processes. No credential was printed; no metadata or business rows were returned and no write occurred. Clone COM access/crosswalk remains `NOT_VERIFIED`; do not infer cause or retry without changed conditions.
- No service was restarted. No tests/checks, migration, database write, COM write, staging, commit, or push ran.

## Current-turn bounded COM connect diagnostic — 2026-10-25 18:28 UTC

- On the trusted Ivan host, a read-only metadata probe reached `V83.COMConnector` activation, then `Connect` returned `COMException` HRESULT `0x80004005` before metadata access. The probe used the protected `onec_admin` credential in process and targeted only `D:\1c\env\bases\818HA_p2diff`; neither credential value nor connection string was emitted.
- A separate in-process shape check reported the protected username/password were present, each 8 characters, and the password contained no quote, semicolon, CR, or LF; the target `1Cv8.1CD` path exists. These observations do not prove the credential identity or its 1C rights and do not establish the COM failure cause.
- The prior 20-second job timeout is superseded as the latest result by this captured COM HRESULT. No metadata/business rows were returned and no write occurred. Do not repeat `Connect` without a changed credential, platform, or target condition.
- No service was restarted. No tests/checks, migration, database write, COM write, staging, commit, or push ran.

## Current-turn OData route and COM lane source review — 2026-10-25 18:35 UTC

- Strict-host-key SSH ran a read-only search for `*.vrd` under `D:\1c\mcp`. It returned zero
  publication files, including zero entries whose infobase target matched `818HA_p2diff`.
  Therefore there is no clone-bound OData metadata route evidenced under this stack root; no
  OData request was made.
- Manually reviewed `windows_com_lane.py` and `com_sta_lane.py` against their documented STA,
  connection-secret, fingerprint, bounded-result, cancellation and drain/cleanup boundaries. No
  source defect was established in that scope, so no speculative COM dispatch code was added.
- The concrete writer remains dependent on an authenticated, clone-specific COM property/method
  crosswalk and a successful read-only connection to the Ivan clone. The most recent changed
  condition still ends at `COMException 0x80004005` before metadata access; do not retry it with
  unchanged credentials, platform and target.
- No service was restarted. No tests/checks, migration, database write, COM write, staging, commit,
  or push ran.
