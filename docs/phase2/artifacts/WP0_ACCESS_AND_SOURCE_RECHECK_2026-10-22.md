# WP0 access and source recheck — 2026-10-22

This note records current-turn runtime observations after the operator corrected the earlier
environment report. It supersedes conflicting WP0 access claims in
`WP4_WP10_DEPENDENCIES_2026-10-21.md`; it does not establish S12/S13 qualification, native
accounting evidence, or release readiness. Observed repository base before this turn's edits:
`0fe023db1ec2adcf1820356db1dd1db09d23c3ab`.

## Local and Ivan service access

| Check | Evidence | Result and limit |
|---|---|---|
| Local listeners | Read-only `Get-NetTCPConnection -State Listen` for 8088, 8191–8193, 18432, 19379, 21000, 21080, 21200 and 21768 | All ten ports were listening. Observed listener PIDs: 8088/7380, 8191/10996, 8192/31516, 8193/2704, 18432 and 19379/32540, 21000/27616, 21080/36088, 21200/32004, 21768/10988. Point-in-time only. |
| Apache configuration | Read-only process metadata for PID 7380 | Command line referenced `httpd-erp-mcp-test-ready.conf`. No restart was attempted. |
| Phase2 process identity | Read-only process metadata for PID 32004 | Executable was `C:\Python314\python.exe`; command line identified `-m testlane.phase2_mcp` and the project venv launcher argument. This is consistent with the Windows venv launcher behavior; it is not a process replacement. |
| Ivan SSH identity and stack | `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes koros@100.88.71.74 'powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status'` | Exit 0; `postgres`, `redis`, `apache`, `proxy8191`, `proxy8192`, `proxy8193`, `sidecar`, `idp` and `gateway` each returned `True`. Host-key verification remained strict. |
| Ivan stack directory | Same strict SSH identity; `cmd /c dir /b D:\1c\mcp` | Names only were listed; no file contents or credentials were read. The directory contains the stack app/data/env/runtime/scripts and the token/stack management scripts. |

The operator is the accountable owner for this delegated project task. The Ivan stack is the
technical owner of the remote connection and host boundary, as recorded in the current
continuation prompt. No human contact for deployed grant confirmation is named in the source
records inspected so far.

## Read-only source calls

Using `.venv\Scripts\python.exe`, `scripts/real1c/gateway_client.py`, and a short-lived
`auditor` token held only in process memory, the local gateway at
`http://127.0.0.1:21000/mcp` returned `source_health.ok=true` and an account 521.1 read for
`onec-818ha-reference` and the operator-specified company/cutoff. The result contained 15
rows and was labeled `VALIDATED_MACHINE_RECONCILED`,
`PROFILE_VALIDATED_MACHINE`, `MACHINE_TWO_SOURCE`, with warning
`MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. No row, amount, or name was printed or stored
in this note.

The equivalent read through Ivan's gateway used a separate short-lived token minted on Ivan
with `mint-token.ps1 -Ttl 3600`; stdout was captured in process and not printed. It also
returned `source_health.ok=true`, with the same machine-evidence labels, but returned 16
rows. An in-memory row-content digest comparison was unequal. The row contents and digest were
not printed or persisted. Therefore the two source reads are **not reconciled**; the difference
requires investigation before treating either lane as a cross-base match.

The 21200 process was reachable and listed the two Phase2 comparison tools. Its
`phase2_capabilities` reported `side_a_configured=false` and `side_b_configured=false`.
Calling comparison tools through the running server returned `GATEWAY_TOKEN_UNAVAILABLE`.
The process was not restarted or replaced. A read-only in-process invocation of the repository's `Reconciler` with separately
minted short-lived gateway tokens returned:

- Overall authority `EVALUATION_ONLY`, status ceiling `IMPLEMENTED_UNVERIFIED`, release verdict
  `NO-GO`, and `native_pass=false`.
- The 521.1 partial closing comparison was `PARTIAL_MISMATCH`, with one difference; the two
  sides exposed 10 and 11 analytical rows. No values or names were printed.
- The six-column turnover and purchase sections returned `GATEWAY_TOOL_ERROR`; the synthetic
  negative-control tool also returned `GATEWAY_TOOL_ERROR`. These are incomplete runtime
  results, not a pass or a successful negative-control demonstration.

The direct MCP client and in-process reconciler used only read operations; the requested
synthetic negative control perturbed a row only in memory and returned an error. `show_values=false`;
no source write or migration was run. A GET on the MCP root is not evidence of the
published OData anonymous-auth behavior, so that boundary remains operator-reported only.

## Current-turn outbound-token implementation update

The source cause of `GATEWAY_TOKEN_UNAVAILABLE` was that the running Phase 2 process had no
configured outbound token providers. In this turn, `testlane/phase2_mcp/config.py` now provides
the default operator-approved local `auditor` mint through `LaneEnv`/`Idp` and the remote Ivan
mint through strict SSH host-key checking to `koros@100.88.71.74`. The fixed remote command
requests a 3600-second token; alternate remote script paths and SSH targets fail closed, and a
script-path setting without its matching target is a configuration error unless a higher-priority
token source is selected. The
gateway client refreshes short-lived credentials before expiry and allows one provider re-read
after HTTP 401/403 because its exposed tools are read-only. Static legacy providers have no expiry
metadata, so their retry may return the same credential. Provider precedence and this distinction
are documented in the design record at
`artifacts/PHASE2_TESTLANE_MCP_DESIGN.md`.

This is an **implemented source change, not runtime-proven**. The 21200 server was not restarted
or replaced, so the running process still has its original configuration and its prior
`GATEWAY_TOKEN_UNAVAILABLE` result is not yet cleared. No new MCP calls, tests, checks, builds, or
migrations were run after this implementation. Owner: operator is accountable; Codex executed the
local change; Ivan stack owns the remote host boundary. Next: after all in-scope code is complete,
the test roles should start an isolated Phase 2 instance on a separate loopback port with the
verified env and exercise both token providers and read-only comparison scenarios. Leave the
operator-verified 21200 process in place; no restart or replacement is part of this work.

## Effective grants

The read-only `database-reviewer` inspected the disposable PostgreSQL endpoint configured for
host loopback port 18432. Docker showed `erpmcp-e2e-real1c-postgres-1` publishing that port to
container port 5432; the connected database was `business_ai`, with session/current role
`business_ai_admin`. The reviewer queried `pg_roles`, `pg_auth_members`,
`information_schema.role_table_grants`, and `has_function_privilege` in a read-only
transaction. No schema or functions named `change_ledger` existed, so the requested S13
effective grants could not be established from this database. No migration was applied.

The role inventory included a highly privileged `business_ai` role (superuser, role/database
creation, replication and RLS bypass) and non-superuser `business_ai_admin`,
`business_ai_app`, and `business_ai_control_api` roles without RLS bypass. No non-system role
memberships were present. This is test-database role metadata, not evidence that a runtime
application uses the elevated role. S13 database grants remain **NOT_VERIFIED** until the
approved disposable schema is bootstrapped and the same read-only grant review is repeated.

The earlier RLS scan covered 15 `bag` base tables; the later effective-grants audit covered
17 `bag` relations, so those counts describe different query scopes and the RLS coverage
must be reconciled before claiming it covers every relation. The later audit found SELECT on
14 relations and INSERT only on `audit_events` for `business_ai_app`, with no
`company_scope_mappings` grant. Its per-role details and function privileges were queried
through each role's own connection; the admin view alone did not represent every role's
effective grants. Five of seven inspected `bag` routines had effective EXECUTE for
app/admin/control; the two trigger routines
`invalidate_semantic_profiles_on_metadata_drift()` and
`invalidate_validated_profile_on_mapping_change()` did not. In particular,
`bag.record_capability_observation(...)` is
`SECURITY DEFINER` with `PUBLIC EXECUTE` in the inspected database, and performs an upsert
into `source_capabilities` without an explicit authorization check in its body; see
`db/migrations/014_capability_observation_boundary.sql:13-105`. The disposable schema has
migration versions 1–14 and lacks version 15. Migration
`db/migrations/015_capability_observation_execute_boundary.sql` revokes `EXECUTE` from
`PUBLIC`, `business_ai_admin`, and `business_ai_control_api`, leaving it for
`business_ai_app`; `scripts/verify_schema.py` checks this boundary. Current `PUBLIC EXECUTE`
is therefore environment drift from the declared contract, not proof that migration 015 is
incorrect. Post-015 privileges remain **NOT_VERIFIED** until qualification. This is an
authorization-boundary risk observation, not a demonstrated exploit. No schema/data changes
were made.

The 1C role evidence remains recorded, not reproduced in this turn:
`testlane/onec_extension/STATUS.md`,
`docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md`,
`scripts/ct14_rights_state.json`, and
`testlane/onec_extension/CT14Ext/Roles/CT14Писатель/Ext/Rights.xml`. The recorded clone
measurement reports 53 allowlisted objects, receipt read/insert/update/post/unpost, sequence
read/update, read-only support access, and no delete/interactive/admin rights. It also records
that marker attributes are not protected by role-level rights; marker integrity still needs
consumer-side enforcement. This is clone evidence, not deployed or production evidence.

## Ordered remaining work

1. After all in-scope coding is complete, have the test roles start a separate Phase 2 instance
   on another loopback port with the verified environment, then rerun the read-only comparison
   and negative control through the actual MCP endpoint. Preserve the operator-verified process
   on 21200 without restart or replacement. Owner: operator accountable; Codex executor; the
   functional-test-reviewer and e2e-runner own execution of their mapped scenarios.
2. Reconcile why local and Ivan 521.1 reads differ (15 vs 16 rows) and why turnover/purchase
   calls fail; keep values and names in private process memory only. Owner: operator accountable;
   Ivan stack owns the remote source boundary; no human contact is recorded.
3. Complete S12/S13 design and implementation on the approved disposable lane, then bootstrap
   only that disposable database and repeat effective-grant review. The S13 writer service is
   a private Ivan-lane deliverable with stable call-ID idempotency, stale-epoch rejection,
   authoritative outcome lookup and a quiescence barrier. No public tunnel write path.
4. Proceed with WP5–WP8 and WP10 in dependency order. WP9 remains optional and outside the
   critical path. Functional/E2E agents run after coding is complete; specialist reviews and
   exact-head GPT-PM approval follow their evidence.

## Follow-up read-only comparison — current executor turn

After the S13 lock-protocol commit, I repeated the Ivan check with
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`.
It exited 0 and reported all nine stack components `True`: postgres, redis, apache, proxies 8191–8193,
sidecar, idp, and gateway. `ssh-keygen -F 100.88.71.74` found the existing known-hosts entry;
strict host-key verification succeeded. A names-only listing of `D:\1c\mcp` returned the stack app/data/env/logs/runtime/tunnel/venv directories and its management scripts. No service restart or credential-file read occurred.

Using the approved in-process gateway client and short-lived `auditor` tokens, I repeated
`source_health` and `accounting_balance_by_analytics` for `onec-818ha-reference`, the operator-specified
company and cutoff, against local `http://127.0.0.1:21000/mcp` and Ivan
`http://100.88.71.74:21000/mcp`. Both health calls returned `ok=true`; both balance calls returned
without MCP error and reported `VALIDATED_MACHINE_RECONCILED`. The account payload had 15 local rows
and 16 Ivan rows. Metadata and profile fingerprints matched, and both routes were `odata`.

I compared normalized row groups in process by account key, typed analytics references, and currency.
The local payload contained 10 distinct groups (5 repeated rows); Ivan contained 11 (5 repeated rows).
All 10 common groups had matching multiplicities and matching aggregate debit/credit values; no group
was local-only, and one group was Ivan-only. Names, references, balances, and tokens were not emitted.
A first-pass full-payload digest appeared only in the agent tool output and is intentionally omitted
from this durable record. This narrows the prior mismatch to one additional normalized analytic group
on Ivan; it does not establish why that group exists or reconcile the two bases.

These were read-only source calls. The gateway's normal audit records may be written by the service;
no 1C/source mutation, migration, COM write, deployment, or process restart was performed. The prior
WP0 result and current independent comparison both remain **NOT_RECONCILED** until the Ivan-only group
is explained and an accepted cross-base rule accounts for it. The next step is a privacy-preserving
source-side diagnosis on the disposable qualification path after coding is complete; operator is the
accountable owner, the Ivan stack owns the host/connection boundary, and no individual responsible for
the data difference is established in the repository.

## Additional transport verification — current executor turn

Read-only local port inspection again found listeners on all ten expected ports; no service was
restarted. Strict SSH `-Action Status` again reported all nine Ivan stack components `True`.

Direct client calls from this machine to Ivan's gateway did not establish an MCP session. The
working authenticated path was a temporary SSH local forward to Ivan's documented Tailscale
gateway bind, with the request `Host` header set to `100.88.71.74:21000`. A short-lived auditor
token (`-Ttl 3600`, audience `http://100.88.71.74:21000/mcp`) was minted on Ivan by the existing
`D:\1c\mcp\mint-token.ps1`; stdout was piped directly into the local client process and never
printed. The MCP request itself used only `source_health` and
`accounting_balance_by_analytics`. The tunnel was closed after the reads.

The local and Ivan health results both returned `ok=true`, HTTP status 200. Both account reads
returned without MCP error and had the same `VALIDATED_MACHINE_RECONCILED` profile kind, profile
fingerprint and metadata fingerprint. The local read had 15 rows; Ivan had 16. Comparing full row
objects in memory found 15 exact common rows, zero local-only rows and one Ivan-only row. No row
content, names, amounts, references, hashes of row content, token, or credentials were emitted or
persisted. This independently confirms the one-row discrepancy but does not explain it; the
cross-base comparison remains **NOT_RECONCILED**.

## Remote MCP initialization follow-up — 2026-10-23

The current-turn direct read-only `source_health` request to `http://100.88.71.74:21000/mcp` did not
complete MCP initialization and returned JSON-RPC `-32603`; it did not yield a source health result.
The remote stack status still reported all nine components `True`. The remote `gateway.err.log` and
`gateway.out.log` remained zero bytes; the prior sanitized `stack.log` scan found no matching MCP,
error, auth, or `-32603` text. No restart was attempted.

To narrow deployment provenance without reading environment or secret files, read-only SSH metadata
and SHA-256 inspection compared the deployed source files with the current local files. Remote
`D:\1c\mcp\app\gateway\src\business_ai_gateway\server.py` is 107,908 bytes, last written
2026-10-11 09:17:12 UTC, SHA-256
`436AE6CF71B40875BC37DF7FD0D018B1E17ECB6BA46F6C4FA8510BFA71EB5598`; current local
`src/business_ai_gateway/server.py` is 115,078 bytes with SHA-256
`F12E09B1DBC1AB8F938D363755063A75F949A00FDCA64C7A3F6328D2AE6C78C1`. Remote and local
`app.py` both hashed to `D094084F7530297B4B397D0B27DAFD5A99236D8E24485E8F82D9DF4076E21BF8`.
After normalizing CRLF to LF, the remote `server.py` SHA-256 is
`E2F291838542A340B67845970EBEED755D62552CB18F42431CA21004DABB4BA4` and exactly matches local
Git commit `ea4defaaccbf52b7cd2fe1d9cca163408dc8ab56` (2026-10-11, “Add opt-in test-lane unreconciled
profiles for the real test source”), present only on the reported archived ref
`archive/wt-ERP_MCP-supplier-debt-runtime`. Current local HEAD is
`3e12436bc874f6aa12b33cdee1ef6111ee33b25c` (2026-10-22). Read-only process metadata identified
listener PID `14980` as Python 3.13 running `uvicorn business_ai_gateway.app:app`; command-line
secrets were not emitted. The remote `app.py` imports `build_mcp` from `.server`, making stale
deployed source a plausible cause of the protocol failure. The process working directory/import
path has not been directly read, so attribution of the loaded module to that exact file is still an
inference, and no matching server-side exception was recovered. Next safe step: correlate the
running process's import path and obtain a non-secret initialization error; prepare any deployment
only from an approved exact revision after the review and qualification gates. No source was copied,
no service was restarted, and no deployment occurred.

The explicitly configured remote virtual environment was also inspected read-only: it reports
Python `3.13.15`, `mcp==2.3.0`, and `uvicorn==0.54.0`; those dependency versions match the deployed
`requirements-runtime.lock`. This rules out a simple mismatch between those two pinned versions and
the inspected environment, but does not establish the running process's `sys.path` or explain the
initialization error.

The remote `run-mcp-stack.ps1` launch definition was then read over strict-host-key SSH without
reading `gateway.env.ps1` values. For the gateway it sets `PYTHONPATH` to
`D:\1c\mcp\app\gateway\src` followed by `D:\1c\mcp\app\gateway`, then starts the venv Python
with working directory `D:\1c\mcp\app\gateway` and module
`business_ai_gateway.app:app` (script lines 98-99; `Start-Hidden` lines 32-36 pass
`WorkingDirectory` to `Start-Process`). This is consistent with the inspected deployed source tree
and makes a basic import-root misconfiguration less likely; however the running process environment
and `sys.path` have not been directly captured, and no server-side MCP initialization exception was
found. Therefore the stale `server.py` remains a plausible but unproven explanation, not a root-cause
finding. The next diagnostic step requires a non-secret runtime error/import-path capture or an
approved deployment of a reviewed exact revision; no process was restarted and no source was
deployed.

### Current executor recheck — 2026-10-23

This executor ran read-only `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74
"powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action
Status"`. Strict host-key verification succeeded and all nine reported components returned
`True`: postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, gateway. This is a
point-in-time remote status result, not MCP health or application-level qualification. No service
was restarted and no credentials or environment values were read.

### Local authenticated MCP channel recheck — 2026-10-23

This executor minted an in-memory, one-hour `auditor` token through the repository's
`LaneEnv.load()` / `Idp.token()` helper and initialized the local MCP client using the configured
gateway URL with ambient proxy use disabled. The read-only `source_health` call completed with
`is_error=false` and payload `ok=true`; no token or credential was printed or persisted. This proves
the local authenticated MCP transport and one health tool call at this time. The returned wrapper did
not include `source_id` or `status` fields at the inspected level, so this record makes no claim about
those fields. It does not diagnose or clear the separate direct-Ivan MCP initialization failure
recorded above, and it is not S12/S13 writer qualification. No service was restarted or changed.

### Follow-up remote transport diagnostics — 2026-10-23

This executor repeated the strict-host SSH status command and again received `True` for the same
nine components. A names-only listing of `D:\1c\mcp\logs` showed zero-byte stdout/stderr files for
Apache, gateway, IdP, all three lane proxies, sidecar, and tunnel; it did not expose configuration
or credential files. A bounded scan of the last 300 lines in `stack.log`, filtered to
`error|exception|traceback|initialize|mcp|gateway` and with token-like fields redacted, returned
only historical component-health summaries and gateway up/down transitions. It contained no
MCP-initialization exception or `-32603` diagnostic. Consequently this read-only probe supplies no
root-cause evidence for the direct Ivan MCP initialization failure; the previously recorded stale
deployed `server.py` remains a plausible but unproven explanation. The next unblocker is an
application-side non-secret error/import-path capture correlated to a fresh failed initialize, or a
separately authorized deployment of an exact reviewed revision. No service was restarted, no
remote file was changed, and no source or secret configuration was read.

### Current-turn strict-SSH status recheck — 2026-10-23

Using `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74`, the read-only
`run-mcp-stack.ps1 -Action Status` command exited 0 and reported all nine components `True`:
PostgreSQL, Redis, Apache, proxies 8191–8193, sidecar, IdP, and gateway. A separate names-only
listing of `D:\1c\mcp` showed the app/data/dl/env/logs/runtime/tunnel/venv directories and stack
management scripts. Strict host-key checking succeeded. No process was restarted, no file contents
were read, and no credentials or environment values were printed. This is evidence of SSH trust and
component process status only; it does not resolve the documented direct-Ivan MCP initialization
failure or prove writer qualification.

### Current-turn S13 effective-grants recheck — 2026-10-23

A read-only `database-reviewer` rechecked the disposable PostgreSQL endpoint before inspecting
catalog details: Docker published `127.0.0.1:18432` to port 5432, the in-process lane configuration
matched loopback port 18432, and the session was `business_ai_admin` on `business_ai`, PostgreSQL
16.15, with `transaction_read_only=on`. The reviewer queried role attributes and memberships,
`information_schema.role_table_grants`, and effective schema/relation/sequence/function privileges
inside one read-only transaction, then rolled it back. The `change_ledger` schema, relations, and
functions were absent; consequently there were no S13 grants to measure. `business_ai` has
SUPERUSER/CREATEROLE/CREATEDB/REPLICATION/BYPASSRLS attributes; `business_ai_admin`,
`business_ai_app`, and `business_ai_control_api` do not, and no membership edges among those roles
were found. This is evidence about the disposable database only, not Ivan or production. The
`CT14Писатель` grant record remains limited to the documented clone/source evidence and does not
establish Ivan's deployed rights. S13 effective grants remain **NOT_VERIFIED** until the approved
candidate schema and roles exist after coding completion; no migration or write was performed.

## Current-turn local gateway and Ivan SSH confirmation — 2026-10-23

The local gateway was reached at the configured `http://127.0.0.1:21000/mcp` target with the repository `.venv` client. A short-lived `auditor` token was minted in-process and used for `mcp.initialize` plus one read-only `source_health` call for `onec-818ha-reference`; the command emitted only `mcp_initialized=true source_health_ok=true`. The bearer token and returned payload were not printed or persisted. This proves the local authenticated MCP path and source-health response at this point in time; it does not qualify the private writer or 1C COM mutation path.

The Ivan stack status was queried over `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74` using `run-mcp-stack.ps1 -Action Status`; SSH completed successfully and all nine reported stack-component status fields were `True`. A separate read-only directory listing of `D:\1c\mcp` completed over the same strict SSH route and returned the stack scripts and expected service directories. No restart, write, secret read, or host-key bypass was performed. A successful strict-host-key SSH handshake proves the configured known-host key matched for this connection; it does not independently attest the key file's provenance beyond the operator's recorded fingerprint check.

Commands used for the remote read-only observations:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "cmd /c dir D:\1c\mcp"
```

The local MCP call was performed by piping an inline Python script to `.\.venv\Scripts\python.exe -`; its material calls were `LaneEnv.load()`, `Idp(env).token("auditor", ttl=3600)`, `mcp_session(env, token)`, and `call_tool(session, "source_health", {"source_id": "onec-818ha-reference"})`. The script asserted the configured MCP URL was exactly `http://127.0.0.1:21000/mcp` and emitted only the initialization/health booleans.

No private writer process, COM method, schema migration, database write, test, or check was performed in this observation. During the later continuation, two read-only COM connection attempts to the guarded disposable clone failed before any method call; see the qualification-prerequisite artifact below for their HRESULTs and limits.

The later continuation used `ct14_common.connect_admin()` twice against guarded clone `818HA_p2diff`. Both connections failed with HRESULT `-2147352567`; the second also exposed `scode=-2147467259`. No COM method, database operation, or write followed. The reason is `NOT_VERIFIED`; this is an unsuccessful connection diagnostic, not a writer or transaction-boundary qualification.

## Additional authenticated local MCP health probe — 2026-10-23

In this continuation, the repository venv loaded `LaneEnv`, minted an in-memory 15-minute `auditor`
token, initialized `mcp_session`, and called `source_health` for `onec-818ha-reference`. The sanitized
result was `is_error=false`, `ok=true`; the wrapper did not expose `source_id`, `status`, or an error
code at the inspected level. The token and response payload were not printed or persisted. This is a
fresh successful local authenticated MCP health probe; it does not prove read-tool authorization for
other identities, Ivan-host MCP initialization, effective S13 grants, or any writer/COM behavior.
No service was restarted and no database, COM, test, or check operation was performed.

## Current-turn remote application inventory — 2026-10-23

Using strict SSH to `koros@100.88.71.74`, names-only directory listings showed `D:\1c\mcp\app` contains `gateway` and `sidecar`, while `D:\1c\env\bases` lists `818HA_p2diff`, `818HA_reference_ro`, and `818HA_test_ready`. A read-only source inspection of remote `app\gateway\scripts\real1c\com_fingerprint.py` found that its fingerprint helpers accept an already-open COM connection and execute `ВЫБРАТЬ КОЛИЧЕСТВО(*)` queries; the module neither opens the connection nor implements a write port. This supports the recorded absence of an established S13 writer boundary, but does not prove that no other process or private service exists outside these listed application directories. No database was opened and no service or process was changed.

## Current-turn Ivan scheduled-task definition — 2026-10-23

Read-only strict-host-key query: `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "schtasks /Query /TN ERP_MCP_Ivan_Stack /V /FO LIST"`. Windows returned `\ERP_MCP_Ivan_Stack`, state `Enabled`/`Ready`, logon mode `Interactive only`, run-as user `koros`, task command `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\1c\mcp\run-mcp-stack.ps1"`, and last result `0`. This is scheduled-task configuration evidence only; it does not prove a currently open COM session, the live process identity, or a writer transaction boundary. No restart or other service/process action was taken.

## Additional authenticated local MCP probe — 2026-10-23 current turn

Using the repository `.venv\Scripts\python.exe` with `LaneEnv.load()`, an in-process
`Idp(env).token("auditor", ttl=3600)`, and `mcp_session(env, token)` against the configured
`http://127.0.0.1:21000/mcp`, token minting and MCP initialization both returned. The subsequent
read-only `source_health` call for `onec-818ha-reference` did not return within an 8-second
client bound. A preceding overall 18-second bound also returned without a tool result. No token,
source payload, row, or error-body text was printed or persisted. This proves local auth and MCP
initialization only for this attempt; current source-health status is **NOT_VERIFIED**. It does not
invalidate the earlier recorded successful call, but the two observations are distinct. No service
was restarted and no database, COM, test, or check operation was performed.

## Additional strict-SSH and remote MCP probe — 2026-10-23 current turn

Using `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74`, the read-only command `powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status` returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. A separate read-only `cmd /c dir /a D:\1c\mcp` listed the stack scripts and directories. No service was restarted.

A fresh short-lived `auditor` token was minted in-process from the local lane IdP and not printed. The MCP client connected to `http://100.88.71.74:21000/mcp`, but initialization returned MCP error `-32603` (`Server returned an error response`, no error data). No MCP tool, including `source_health`, ran on the remote endpoint. This does not establish whether the gateway, token issuer/audience, or route configuration caused the error; the exact cause is **NOT_VERIFIED**. Do not treat the remote source as healthy from the SSH component status. Operator remains accountable; Ivan stack is the technical owner of the remote host/connection. Next: inspect the documented remote MCP issuer/audience configuration without exposing credentials, then make one bounded read-only authenticated health call only after its token contract is confirmed.

## Short-lived read-token handling incident — 2026-10-23 current turn

A remote `mint-token.ps1 -Ttl 3600` invocation was piped to `python -` instead of to a Python process that reads stdin as token data. Python therefore parsed the token as source and emitted its input in a `SyntaxError` diagnostic. The token value, claims beyond the configured `auditor` / `onec:read` / 3600-second request, and any credential are intentionally not copied into this record. The interpreter failed before opening the MCP client, so no remote MCP request was made with this token. The token was not persisted by this command and was not revoked through an IdP administrative action; it must be treated as exposed until its one-hour expiry. No shared IdP session or service was invalidated. Owner: operator accountable; Codex caused and recorded the handling error; Ivan stack is technical owner of the host IdP. Next: do not reuse the token or repeat the mint call; let the bounded token expire. A later authenticated remote probe must use a client that consumes token input as data, with only a safe result summary emitted.

## Remote MCP issuer correction and bounded health probe — 2026-10-24

After the prior 3600-second token's lifetime had elapsed, strict-host-key SSH was used to inspect
only non-secret fields from `D:\1c\mcp\env\idp-config.json`. The remote issuer was
`https://ivan.tail08f9f9.ts.net/realms/erp-mcp-test`; its configured MCP audience was
`http://100.88.71.74:21000/mcp`, matching the direct remote MCP URL. No credential, signing key,
client secret, or raw configuration was read or emitted.

The remote `D:\1c\mcp\mint-token.ps1` script was invoked over strict SSH with `-Ttl 900` and that
audience. Its token output was captured in process memory and piped to the repository `.venv`
Python client as stdin data (the client used `-c`, not stdin as source); only sanitized booleans
and the health status code were emitted. `mcp.initialize` succeeded and the read-only
`source_health` call for `onec-818ha-reference` returned `status_code=200` with no tool error.
The token and source payload were not printed or persisted. No service was restarted, no database
or COM method was invoked, and no business rows were read. This closes the prior remote MCP
initialization failure for this issuer/audience and health call at this observation time only; it
does not prove readiness, other tool authorization, S13 grants, or a writer/COM transaction
boundary.

## Read-only S13 effective-grants recheck — 2026-10-24

The `database-reviewer` used the repository venv `LaneEnv` configuration in process and confirmed the disposable PostgreSQL endpoint by loopback/port `18432` plus server metadata (`business_ai`, current role `business_ai_admin`, server port `5432`). In a read-only repeatable-read transaction the reviewer inspected `pg_roles`, schema existence, `information_schema.role_table_grants`, `has_table_privilege`, and `has_function_privilege`; no business rows were queried. `change_ledger` does not exist in this database, so S13 table/function grants and effective S13 privileges are **NOT_VERIFIED**, not zero or denied. The observed roles were `business_ai` (superuser and `BYPASSRLS`) and `business_ai_admin`, `business_ai_control_api`, `business_ai_app` (login roles without superuser or `BYPASSRLS`). No schema, file, process, or data was modified. This is disposable-database metadata only and says nothing about the post-migration schema or Ivan's licensed clone. Owner: operator accountable; Codex executor; `database-reviewer` performed the independent read-only inspection. Next: after coding/design closure, qualify the approved candidate schema in a disposable database and repeat object-specific role grants/effective privilege queries there.

## Current-turn Ivan stack status and bounded names listing — 2026-10-24

Commands used with strict host checking:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "cmd /c dir /b D:\1c\mcp"
```

The status command returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. The names-only listing returned `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, `venv`, and stack/setup scripts including `mint-token.ps1` and `run-mcp-stack.ps1`. No file contents or credentials were read. This confirms those status fields and directory names at observation time; it does not establish a private writer listener, open COM connection, effective S13 grants, or transaction boundary. No service was restarted. Owner: operator accountable; Ivan stack technical host owner; Codex executor. Next: qualify the writer only after the approved S13/S14 boundary is implemented on the licensed disposable clone.

## Current-turn local MCP route attempt — 2026-10-24

Using `.venv\Scripts\python.exe` and the in-process `LaneEnv`/`Idp`/`mcp_session` client, an attempt to mint a short-lived `auditor` token and call read-only `source_health` for `onec-818ha-reference` failed during token issuance with `httpx.ConnectError: [WinError 10061]` before `mcp_session` or the MCP tool call. A sanitized TCP probe of the configured local IdP (`127.0.0.1:21080`) and gateway/MCP (`127.0.0.1:21000`) timed out; `Get-NetTCPConnection -State Listen -LocalPort 21000,21080` returned no listeners. No token or response payload was emitted. The strict-host-key SSH stack status above still returned `True` for all nine remote components. Therefore remote host status and this local configured route are distinct evidence: the remote stack status is confirmed, while this turn could not mint a local-route token or repeat the health call. No service was started/restarted, no connector tunnel was used, and no database, COM or business operation ran. Owner: operator accountable; Ivan stack is technical remote-host owner; local service owner is not established. Next: restore or route the local lane to its approved endpoint without restarting Apache/proxies, then repeat the sanitized read-only health call. S13 remains `NOT_READY`.

## Current-turn direct remote MCP health — 2026-10-24

To distinguish the local loopback route from the verified Ivan host, strict-host-key SSH invoked `D:\1c\mcp\mint-token.ps1 -Ttl 900 -Audience http://100.88.71.74:21000/mcp`; its output was held in PowerShell memory and passed through a task-scoped process environment variable to the repository `.venv` MCP client. The client targeted the direct remote MCP URL, initialized the MCP session, and made only `source_health(source_id="onec-818ha-reference")`. Sanitized output was `is_error=false`, `ok=true`, `status_code=200`. The token, payload and credentials were not printed or persisted. No ERP_MCP_REAL1 ChatGPT connector was used; no business rows, database mutation or COM operation occurred. This verifies the SSH-hosted MCP route at this observation time; the configured local loopback route remains unavailable as recorded above. Owner: operator accountable; Ivan stack technical host owner; Codex executor. Next: use the confirmed direct remote path for permitted reads while separately resolving local loopback routing without restarting Apache/proxies.

## Current-turn strict SSH and Ivan stack inspection — 2026-10-25

The remote host was accessed read-only with strict host-key checking; no host-key bypass or credential output was used. The status command returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, and gateway. A separate read-only listing of `D:\1c\mcp` returned the `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, and `venv` directories plus the stack scripts, including `run-mcp-stack.ps1` and `mint-token.ps1`. No service was restarted and no files or secret values were read.

Commands executed:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -Command Get-ChildItem -LiteralPath D:\1c\mcp -Force ^| Select-Object Mode,Length,Name"
```

The successful strict SSH connection establishes that this client accepted its configured `known_hosts` entry for this endpoint; it does not independently establish the out-of-band provenance of that key. The operator separately recorded the trusted fingerprint and its confirmation. Stack liveness is a point-in-time read-only observation, not evidence of an open COM session, a transaction boundary, or S13 qualification. Accountable owner: operator; technical host owner: Ivan stack (`ERP_MCP_Ivan_Stack`); executor: Codex. Next: continue only read-only inspection until source/lock-map coding is complete; later perform bounded disposable qualification under the functional/E2E roles.

## Current-turn local gateway health call — 2026-10-25

A read-only `source_health` request was sent through the repository venv using `scripts/real1c/gateway_client.py` (`LaneEnv.load`, `Idp.token('auditor', ttl=900)`, `mcp_session`, `call_tool`) to the configured local MCP endpoint for `onec-818ha-reference`. The exact returned envelope was `{"is_error": false, "payload": {"ok": true, "status_code": 200}}`. The token remained in process memory and was not printed. No accounting/business-data tool or database query was called. An earlier inline invocation returned no captured result; its outcome is `NOT_VERIFIED`, so this record relies only on the completed invocation above. No service was restarted. This proves the authenticated local source-health path answered successfully at this time; it does not qualify business reads, remote MCP, writer behavior or S12/S13. Accountable owner: operator; executor: Codex; technical owner of the local MCP health route: UNKNOWN in current-turn evidence.

## Current-turn Ivan writer-key path and scheduled-task identity — 2026-10-27

Using `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74`, a read-only remote
PowerShell query listed only filenames in `D:\1c\mcp`, `D:\1c\mcp\env`, and
`D:\secrets\erp_mcp`, then inspected the `ERP_MCP_Ivan_Stack` task's principal/state/action
metadata. `D:\1c\mcp\env` exists and contains `credentials.json`, `gateway.env.ps1`,
`idp-config.json`, `idp-signing-key.pem`, `onec_admin.dpapi`, `test_reader_password.dpapi`, and
other named files; it contains no filename matching signer, D9 or D10b. `D:\secrets\erp_mcp` is
absent. The task metadata reports principal `koros`, task state `Ready`, executable `powershell.exe`,
and arguments pointing to `D:\1c\mcp\run-mcp-stack.ps1`. No file contents or credential/key bytes
were read, no service was restarted, and no database/COM operation occurred. This bounded inventory
does not prove host-wide absence, effective `CT14Писатель` rights, or that `koros` is the approved
private-writer service identity. D9/D10b provisioning and registry scope/validity remain
`NOT_VERIFIED`. Accountable owner: operator; Codex owns next read-only source/policy reconciliation;
Ivan stack is the technical host boundary. Next: establish the approved service identity and trusted
registry metadata from in-scope deployment records before generating or registering any key.

## 2026-10-27 current-turn connectivity refresh

Strict-key SSH to `koros@100.88.71.74` ran the read-only command
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status`.
All nine reported components were `True`: PostgreSQL, Redis, Apache, proxies 8191–8193, sidecar,
IdP and gateway. No component was restarted. From the repository venv, `LaneEnv.load()` and a
short-lived auditor token were used in-process with `mcp_session` and `call_tool` against the
configured local MCP endpoint for `source_health(onec-818ha-reference)`; the bounded result was
`is_error=false`, `ok=true`, `status_code=200`. No token, connection secret or business row was
printed/read. These are point-in-time connectivity checks only: they do not prove the remote COM
writer, 1C transaction boundary, effective PostgreSQL grants, or S12/S13 qualification. Owner:
Codex for read-only collection; operator accountable; Ivan stack is the remote host boundary.
The local `known_hosts` entry resolved with `ssh-keygen -F 100.88.71.74 | ssh-keygen -lf -` to
`SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ` (ED25519); strict-key SSH accepted that entry.
