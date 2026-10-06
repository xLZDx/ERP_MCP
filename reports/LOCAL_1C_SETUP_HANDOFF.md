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
