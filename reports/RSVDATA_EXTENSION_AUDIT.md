# RSV Data extension audit — live Windows/COM/BSL evidence

Assessment: 2026-10-06.
This section supersedes the previous "pending platform extraction" snapshot.
Target is a disposable synthetic local infobase only; no customer/production data was used.

## Executive verdict

**P6 Windows/COM environment blocker is removed.**

The official RSV Data v1.3.0 extension was installed into a disposable 1C 8.3.27.2342 x64 file
infobase, exported to XML/BSL, statically reviewed, and exercised through the real pinned COM bridge.

Live metadata/health operations work through COM.

However, **RSV Data is NOT approved as an unrestricted production business-data route**:

1. default anonymization creates persistent records in the extension's own
   `RSVData_КартаАнонимизации` information register;
2. `reveal` reads that shared token map under privileged mode and the map is not scoped by
   ERP_MCP principal/company;
3. no immutable organization/company predicate exists in the extension;
4. `execute_query` accepts arbitrary 1C query-language text and applies the row limit after the
   query itself executes, so it is not a bounded-cost execution primitive;
5. the HTTP service handler performs no ERP_MCP authorization itself and must not be exposed
   directly to AI clients.

Current production-safe decision:
- **ALLOW candidate metadata boundary only:** ping, config, describe, get_structure, help, always
  behind ERP_MCP source ACL/policy.
- **DENY:** reveal, execute_query.
- **DENY business query by default:** query remains disabled until ERP_MCP can prove zero-write
  runtime behavior plus source/company scope for the concrete source.
- Existing ping-only P6 wrapper may remain unchanged until the metadata-only expansion is
  explicitly implemented and tested.

## Platform/runtime evidence

| Item | Evidence |
|---|---|
| Platform | 1C:Enterprise 8.3.27.2342 x64 full platform |
| Install mode | per-user, `%LOCALAPPDATA%\Programs\1cv8_x64\8.3.27.2342` |
| `1cv8.exe` SHA-256 | `2a9ef3653367b6de29000a3a51749a19e6450134347925713c9075674e9f0956` |
| `comcntr.dll` SHA-256 | `5ca7d51daba0f250f27ca3623527db3555fd23d86c5c50ea9aef260255e487d9` |
| COM ProgID | `V83.COMConnector` |
| COM CLSID | `{181E893D-73A4-4722-B61D-D604B3D67D47}` |
| TypeLib | `{98AC3B5B-5323-418F-8F07-E32F231D2393}` v1.0, Win64 |
| COM registration | per-user HKCU registration; no machine-wide install required |
| COM create | PASS |
| COM connect to disposable base | PASS |
| Community/Developer License | active enough for real COM connect and Designer batch operations |
| Disposable base | `D:\ERP_MCP_Testbed\1c\bases\RSVDataAudit` |
| Pre-patch backup | `RSVDataAudit-before-basepatch.dt`, SHA-256 `eb09a56e5ce0196bc0ba28b6a1fafe57e751e099ce995b395c85b85ce5710cff` |

The initial empty English base was intentionally patched only to make it compatible with the
extension: a Russian language object was added and `InterfaceCompatibilityMode` changed from
`Taxi` to `TaxiEnableVersion8_2`. This is synthetic-test setup, not a production migration.

## Artifact and source extraction

Official release artifact remains:

- release: v1.3.0
- `RSVData.cfe` SHA-256:
  `01055749d44d4b44f941aadb4ea132e4054aa962d6f92019b252a374797f8d4d`
- CFE internal version verified after export: `1.3.0`
- extension compatibility mode: `Version8_3_21`
- extension interface compatibility mode: `TaxiEnableVersion8_2`
- purpose: `AddOn`

Export path, deliberately outside Git:

`D:\ERP_MCP_Testbed\1c\exports\RSVDataAudit\RSVData`

The supported Designer dump produced 16 XML/BSL files.
Deterministic tree fingerprint over sorted relative-path/size/SHA-256 records:

`443a7eba7f36bff764df5439de449a5a9e49e6a30f588b5f1783dc021b98b5b7`

Reviewed BSL modules:
- `RSVData_Сервер`
- `RSVData_Ядро`
- `RSVData_Справка`
- `RSVData_Анонимизация`
- HTTP service `RSVData_MCP`

No OS command execution, external component loading, or outbound network API was found in the
exported BSL. Query execution is through the 1C Query API / data composition system.

## Live bridge evidence

The installed extension is active:

- COM bridge `diag`: PASS
- `RSVData_Сервер`: available through external connection
- `RSVData_Ядро`: available
- `RSVData_Справка`: available
- bridge `ping`: PASS
- MCP `initialize`: PASS
- MCP `tools/list`: PASS
- MCP `config`: PASS
- MCP `describe`: PASS

Raw synthetic evidence:

`D:\ERP_MCP_Testbed\1c\evidence\rsv-live-smoke.stdout.jsonl`

SHA-256:

`5537221f2a82a6b31bfdc2eba0486dc4a983e7883110418e18123f0ff4d5ad27`

The live tool inventory exposes:
`ping`, `config`, `describe`, `get_structure`, `query`, `execute_query`, `reveal`,
`help`.

## Write-path audit

A persistent write exists in `RSVData_Анонимизация`:

`ПолучитьИлиСоздатьТокен` calls `ЗаписатьЗапись`, which creates a record set for
`RSVData_КартаАнонимизации` and calls:

`НаборЗаписей.Записать(Истина)`

The module also uses `УстановитьПривилегированныйРежим(Истина)` around anonymization-map and
PII lookup operations.

Therefore the upstream statement "read-only" must not be interpreted as "zero database writes".
It does not appear to mutate normal business objects, but its own extension register is mutated
during normal anonymization of new values.

ERP_MCP D5 requires a stronger zero-write runtime boundary, so default business-query routing is
not approved as-is.

## Query path

### `query`

The structured tool is materially safer than arbitrary query text:
- single-table semantics;
- metadata-derived objects/fields;
- object read-right checks;
- bounded returned rows;
- filters/order/period go through the structured implementation.

But returned PII can enter the anonymization path, which can persist token-map records.
The extension also does not inject an immutable ERP_MCP company predicate.

Verdict: **DENY for production business reads until wrapped with proven company scope and a
zero-write privacy design.**

### `execute_query`

Implementation creates `Новый Запрос(Текст)`, applies parameters, then calls
`Запрос.Выполнить()`.

Positive finding:
- no arbitrary BSL/OS-code execution path was found in the reviewed call path;
- 1C Query is a read-query mechanism rather than a business-object mutation API.

Remaining blockers:
- arbitrary joins/nested queries can cross organization boundaries if the technical 1C user can see
  them;
- the output row limit is enforced while consuming the result **after** query execution, so a costly
  query can still consume substantial 1C resources before the response is capped;
- no ERP_MCP company predicate is enforced;
- anonymization can write the token map.

Verdict: **DENY.**

## Privacy / reveal finding

`reveal` ultimately reads `RSVData_КартаАнонимизации` under privileged mode.

The token map is not scoped by:
- ERP_MCP principal;
- ERP_MCP company_id;
- request/session.

Tokens are sequential-category identifiers such as `[ОРГ-00001]`.

That design is not sufficient for ERP_MCP multi-company privacy isolation. A shared token map plus
privileged reveal creates an unacceptable cross-scope disclosure risk unless an additional isolation
boundary is proven.

Verdict: **HARD DENY in ERP_MCP production tools.**

## Company-scope audit

No organization/company-specific immutable filtering logic was found in the exported BSL.
Business reads rely on:
- 1C object read rights;
- caller query/filter semantics;
- the permissions of the 1C connection identity.

That is insufficient when one technical account can read multiple organizations in the same
infobase.

A P6 business route may be reconsidered only when one of the project-approved conditions is proven:
1. immutable validated company predicate injected server-side and not caller-removable;
2. source is evidenced single-company;
3. dedicated 1C identity is rights-restricted to exactly the registered company scope.

Until then: `CAPABILITY_UNSUPPORTED` for P6 business reads on multi-company sources.

## HTTP service boundary

`HTTPServices\RSVData_MCP\Ext\Module.bsl` reads request JSON and delegates it directly to
`RSVData_Сервер.ОбработатьСообщение`.

No ERP_MCP authentication/authorization exists in this handler. Any 1C publication authentication
is an upstream transport boundary, not a substitute for ERP_MCP OAuth/ACL/company policy.

Do not expose this upstream HTTP MCP endpoint directly to an AI client.

## Bridge credential handling

Pinned Go bridge configuration supports username/password fields and documents that they are stored
as ordinary text in its JSON config. ERP_MCP production must not make that config the authoritative
secret store.

Production wrapper must obtain credentials from ERP_MCP secret references and keep them out of
model-visible responses, Git, logs and process-list arguments.

## Source/release provenance caveat

The approved source reference remains:

`76fed8e6e16833fee1514969841b8d9a61c7c152`

The v1.3.0 release tag resolves to a different source commit. The CFE was audited as the actual
official release binary by supported Designer export; this does **not** prove byte-reproducibility
from the approved Go bridge source pin.

The Go bridge was also built separately from the approved source pin during local setup.

## Production policy after this audit

| Upstream capability | ERP_MCP disposition |
|---|---|
| ping | ALLOW behind source ACL |
| config | ALLOW candidate metadata operation |
| describe | ALLOW candidate metadata operation |
| get_structure | ALLOW candidate metadata operation |
| help | ALLOW candidate metadata operation |
| query | DENY by default; requires zero-write + company-scope proof |
| execute_query | DENY |
| reveal | HARD DENY |
| upstream HTTP MCP directly to AI client | DENY |

## P6 status

**Windows/COM/platform availability is no longer an external blocker.**

P6 may progress locally to:
- metadata-only adapter contract;
- bridge lifecycle/reconnect/failure injection;
- normalized metadata envelope;
- source ACL enforcement;
- live COM disconnect/restart tests.

Full P6 business-data routing remains unapproved pending the security/zero-write/company-scope
remediation described above and later real-target evidence.
