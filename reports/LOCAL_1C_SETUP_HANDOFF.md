# Local 1C live handoff

Updated: 2026-10-06

The local P6 environment is now operational.

## Live environment

- 1C:Enterprise 8.3.27.2342 x64 full platform installed per-user.
- Community/Developer License activated.
- V83.COMConnector creates and connects successfully.
- COM was registered per-user under HKCU using exact CLSID/TypeLib from the signed official MSI;
  no machine-wide admin registration was required.
- Disposable base:
  `D:\ERP_MCP_Testbed\1c\bases\RSVDataAudit`
- Official RSV Data v1.3.0 extension installed and active.
- RSV bridge diag PASS.
- RSV bridge ping PASS.
- MCP initialize/tools/list/config/describe PASS.

## Source export

RSVData.cfe was dumped through supported Designer functionality to:

`D:\ERP_MCP_Testbed\1c\exports\RSVDataAudit\RSVData`

16 XML/BSL files; tree fingerprint:
`443a7eba7f36bff764df5439de449a5a9e49e6a30f588b5f1783dc021b98b5b7`

See `reports/RSVDATA_EXTENSION_AUDIT.md` for the security verdict.

## Critical implementation instruction

Do not continue treating "no local Windows/COM/1C" as a blocker.

Safe next P6 work is locally actionable now:
- metadata-only contract for ping/config/describe/get_structure/help;
- source ACL and normalized envelope;
- bridge lifecycle/reconnect/timeout/failure tests;
- COM process restart evidence.

### Executed native lifecycle follow-up — 2026-10-06

Production client + official SDK + unmodified digest-pinned RSV v1.3.0 bridge now exercised against
the established disposable base: confirmed native ping, test-owned bridge crash, dead-session
sanitized failure, fresh process/COM reconnect and metadata config. Three newly spawned processes
terminated and protected temporary configurations removed. Opt-in test 1/1 PASS, zero skips;
sanitized evidence scanner PASS. Repeat using `python -m scripts.rsv_native_lifecycle_harness
--confirm-disposable-base --output <new-private-file>`. No arbitrary PID/native engine kill,
business query, raw metadata publication or production-source change. Initial test iteration failed
on the fixture's wrong envelope-key expectation after recovery; corrected to the actual adapter
contract and rerun through the evidence harness. Native engine crash, zero-write snapshots,
binary/source build parity and native accounting reconciliation are NOT claimed.

Do NOT enable:
- reveal;
- execute_query;
- generic business query.

The audit found:
- anonymization persists token records to the extension information register;
- reveal reads a shared token map under privileged mode;
- no immutable ERP_MCP company predicate;
- execute_query output limiting does not bound upstream query execution cost.

Business P6 routing stays CAPABILITY_UNSUPPORTED until those constraints are remediated/proven.
