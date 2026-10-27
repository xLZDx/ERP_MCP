# WP0 Ivan stack status — 2026-10-26 read-only recheck

## Scope and ownership

- Accountable owner: operator, by explicit delegation.
- Executor: Codex.
- Technical host boundary: Ivan stack at `100.88.71.74`, reached as `koros` with strict host-key checking.
- Scope: read-only status and directory metadata under `D:\1c\mcp`. No service was started,
  stopped, restarted or reconfigured; no environment, credential, key, token or business data file
  was read.

## Commands and observed result

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
```

Exit code: `0`.

```text
postgres=True
redis=True
apache=True
proxy8191=True
proxy8192=True
proxy8193=True
sidecar=True
idp=True
gateway=True
```

The `D:\1c\mcp` root listing showed `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, and
`venv` directories plus the stack/setup scripts. Only the names and filesystem metadata were read.
`D:\1c\mcp\app` contained `gateway` and `sidecar` directories; it did not show a private-writer
application directory at that level. This directory observation alone does not establish whether a
writer exists elsewhere on the host.

## Local lane and authenticated MCP observation

Read-only `Get-NetTCPConnection -State Listen` showed listeners on `127.0.0.1` ports 8088,
8191–8193, 18432, 19379, 21000, 21080, 21200 and 21768. Anonymous GETs to
`/erp_mcp_ref/odata/standard.odata/$metadata` returned HTTP 401 on 8088 and 8191–8193. A GET to
`/` returned HTTP 200 on those ports, which is not an authorization result. The configured local
MCP URL read from the non-secret `env.json` is `http://127.0.0.1:21000/mcp`. Using the repository's
`gateway_client.py`, a short-lived `auditor` token was minted and retained in process; authenticated
`source_health(source_id="onec-818ha-reference")` returned `is_error=false`, `ok=true`,
`status_code=200`. No token, source payload or business row was printed. This does not establish
account-read parity or reconcile local and remote business data.

An authorized read-only evaluation call to `phase2_reconcile_two_bases` on the already-running
loopback test-lane MCP (`127.0.0.1:21200`) used the delegated August 2026 period and
`show_values=false`; no names, amounts, or company identifier were emitted. The partial 521.1
closing-balance section returned `PARTIAL_MISMATCH`, one differing item, with 10 rows on side A
and 11 on side B. This is a closing-only copy comparison, not the six-column reconciliation or a
native 1C pass. The six-column and purchase-document sections returned `ERROR` with the sanitized
reason `GATEWAY_TOOL_ERROR`; the underlying gateway/tool cause was not exposed by the evaluation
adapter. The output does not establish that the 521.1 delta is unexpected; the historical host
artifact records a known changed-copy negative control, but this call did not expose its row key or
amount. No negative-control tool, COM operation, database write, or ERP write was run.

## Limits and next step

This proves only that the nine named components reported `True` at the time of the command and
that strict SSH access to this host path worked. It does not prove the remote PostgreSQL schema,
effective grants, the COM license, CT14 rights on the current clone, a private writer process, or
any write behavior. Keep the existing stack unchanged. A separate metadata-only COM attempt on the
authorized clone is already recorded in `S14_COM_EPHEMERAL_VALUE_BINDING_DESIGN_2026-10-25.md` as
`LICENSE`; restore or identify a usable licensed clone client before collecting the exact
destination/type crosswalk required for the operational COM adapter.

### 2026-10-26 D9/D10b key-path metadata recheck

A read-only inventory checked the documented `D:\secrets\erp_mcp` path on both the local execution account and Ivan over strict SSH. Local identity was `RAZER\koros`; Ivan identity was `IVAN\koros`. The path is absent on Ivan. On the local host, the path contains only `admin_1c_clone_password.dpapi`, `admin_1c_clone_user.txt`, and `test_reader_password.dpapi`; no D9/D10b/signer/witness-named file is present. File contents were not opened. `governance/WAIVER_SIGNERS.json` remains a separate empty G4 waiver registry; candidate S13 verifier-key tables are not installed on the disposable database. Therefore real D9/D10b generation/registration is not complete and must not be inferred from SSH or stack health. No key was generated, copied, registered, or printed.

### 2026-10-26 bounded license-source metadata recheck

Codex repeated a read-only inventory over strict-host-key SSH to `koros@100.88.71.74`, without
opening any candidate key or license file. A filename-only search for `*.lic` under
`C:\ProgramData\1C`, `D:\1c\env\1cv8_x64\conf`, `D:\1c\mcp\env`, and the current account's
`AppData\1C` returned no files. The existing `D:\1c\env\1cv8_x64\conf\nethasp.ini` had no active
`NH_SERVER_ADDR` or `NH_PORT_NUMBER` setting. `Get-PnpDevice -PresentOnly` returned no device named
Sentinel, HASP, Aladdin, or 1C license. These bounded checks do not rule out a license source in
other directories or an external license server; they do not establish license validity. They are
consistent with the separately recorded COM diagnostic `License not found` and do not provide a
crosswalk. No service, task, configuration, or database was changed; no key or credential was
read, generated, copied, registered, or printed.

**Next step / ownership:** the operator is accountable and Codex owns coordination; the Ivan stack
is the technical host boundary. Identify or restore a usable licensed 1C client/license source on
the authorized host, then repeat only the read-only metadata inventory and record the exact clone
identity and property/type crosswalk before implementing the operational `OneCWritePort`.
### 2026-10-26 current continuation access and catalog recheck

In this continuation, read-only local listener inspection found ports 8088, 8191–8193, 18432,
19379, and 21000 listening on loopback. An in-process auditor token (not printed) through the
repository `gateway_client.py` returned `source_health` for `onec-818ha-reference` with `is_error=false` and
`{status_code: 200, ok: true}`. Strict-host-key SSH to `koros@100.88.71.74` succeeded, and
`run-mcp-stack.ps1 -Action Status` again reported all nine named stack components `True`.
These are transport/source-health observations; they do not prove writer availability or COM rights.

A database-reviewer catalog-only session used the documented local `LaneEnv.load()` loader and
`business_ai_admin` against the disposable test lane on port 18432. It verified a
`REPEATABLE READ READ ONLY` transaction (`transaction_read_only=on`), with
`session_user=current_user=business_ai_admin` and PostgreSQL server port 5432. The
`change_ledger` schema and S13 roles are absent; candidate S13 effective grants remain
`NOT_MEASURABLE`, not denied or zero. No business rows were queried and no database changed.

A separate read-only SSH review of the Ivan stack found PostgreSQL on loopback port 18432 and the
gateway on `100.88.71.74:21000`. No `*.lic` file was found under `D:\1c\env`, and the earlier bounded
checks found no configured NetHASP server or present HASP/Sentinel device. The project `LaneEnv.load()`
requires `env.json` and `secrets.json`, which are absent from Ivan's `D:\1c\mcp\env`; that
host-side attempt therefore stopped without loading credentials or querying grants. No named
`private_writer` or `phase2_mcp` process matched the bounded process query. No service, task,
credential, database, or file was changed by these inspections.

**Remaining order:** operator accountable / Ivan stack technical boundary: restore or identify a
licensed clone client and provide the exact read-only clone identity and property/type crosswalk.
Then Codex implements the operational `OneCWritePort`, completes code, and the functional/E2E
and database-review roles qualify the exact candidate on an invocation-owned disposable database.
**Additional user-scope license metadata check — 2026-10-26:** a second strict-SSH filename-only
search found no `*.lic` files in `C:\Users\koros\AppData\Local\1C` or
`C:\Users\koros\AppData\Roaming\1C`; `C:\ProgramData\1C\licenses` was absent. A read-only
service-name query found only generic Windows `LicenseManager` (Running, Manual) and
`ClipSVC` (Stopped, Manual) among names matching 1C/HASP/Sentinel/license; neither result proves
an installed or usable 1C license. The COM `License not found` condition remains unresolved.
### 2026-10-26 16:20 UTC strict SSH status recheck

A current read-only call used `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74`. `powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status` returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. A names/metadata-only `dir /a D:\1c\mcp` confirmed the stack scripts and `env`, `app`, `data`, `runtime`, and `venv` directories. No services were restarted and no environment or credential files were opened. This confirms current SSH and stack availability only; it does not change the recorded missing licensed COM session, crosswalk, or effective S13 grants. Owner: operator accountable; Codex executor; Ivan stack technical host boundary.

The same read-only recheck listed filenames and sizes under `D:\1c\mcp\env` only: `credentials.json`, `gateway.env.ps1`, `idp-config.json`, `idp-signing-key.pem`, `onec_admin.dpapi`, `test_reader_password.dpapi`, and tunnel/profile files are present; no `env.json` or `secrets.json` was listed. No file contents were opened. The presence of `onec_admin.dpapi` is not authorization to use that administrator credential for COM writer access and does not establish the `CT14Писатель` identity, clone-specific access, or license. The earlier restriction against substituting admin credentials remains in force.

### 2026-10-26 17:55 UTC current-turn strict SSH status/list recheck

This turn independently repeated strict-host-key SSH to `koros@100.88.71.74`. The command
`powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status`
returned `True` for postgres, redis, apache, proxy8191–8193, sidecar, idp, and gateway. A
names-only listing of `D:\1c\mcp` showed `app`, `data`, `dl`, `env`, `logs`, `runtime`, `venv`,
and the stack/tunnel scripts. No process or service was restarted; no environment/credential
contents or clone business data were read. This confirms the SSH route and named stack status at
the time of this call only. It does not establish a licensed 1C COM client, the CT14 clone
crosswalk, current effective S13 grants, or writer readiness. Owner: operator accountable; Codex
executor; Ivan stack technical host boundary.
