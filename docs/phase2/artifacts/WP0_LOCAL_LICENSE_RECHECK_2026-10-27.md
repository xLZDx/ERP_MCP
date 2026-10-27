# Local 1C License Recheck — 2026-10-27

## Scope and result

The operator directed Codex to use the 1C license on this machine for the authorized disposable
clone `818HA_p2diff`. This check used the in-scope ERP_MCP checkout and only read local path,
registration, and sanitized COM outcome metadata. It did not read license contents, credentials,
business rows, or modify a license or service.

The metadata-only inventory command was run once:

```powershell
.\.venv\Scripts\python.exe testlane\onec_extension\scripts\ct14_metadata_inventory_readonly.py
```

It exited `1` before opening a COM session and returned:

```json
{"error":"CT14_METADATA_COM_CONNECT_FAILED","exception_type":"com_error","hresult":"0x80020009","automation_codes":["0x00000000","0x80004005"],"diagnostic_class":"LICENSE"}
```

The clone path, DPAPI credential paths, project virtual environment, inventory script, and local
`V83.COMConnector` registration were present. A names-only check of the documented local 1C
license search locations found one file, `C:\ProgramData\1C\licenses\20261012103255.lic`
(5,698 bytes; last-write time 2026-10-12 07:32:56 UTC). No other `*.lic` files were found in the
platform-version configuration, current-user configuration, and all-users license locations
enumerated by that check. This is limited to those checked locations and does not rule out other
license mechanisms or sources. The file was not opened. The earlier read-only COM diagnostic
recorded this exact path as expired at `2026-10-19 07:32:58 UTC` (see
[WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md, “2026-10-25 read-only COM license follow-up,”
local disposable clone bullet](WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md#2026-10-25-read-only-com-license-follow-up)).
That prior observation binds the expiration to the same full path and filename; the present check
did not independently decode the file or re-verify its expiration.

On Ivan, the separately run `store-onec-admin.ps1 -TestOnly -BasePath
D:\1c\env\bases\818HA_p2diff` returned `License not found. Software protection key or acquired
software license not found!`; no COM session or metadata read was established. No license file was
copied or activated, and no service was restarted.

## Acceptance and ownership

The tested local connection attempt did not establish a usable COM session for the disposable
clone. `V83.COMConnector` registration and clone credentials do not establish a current license.
The live metadata/property-type crosswalk therefore remains `NOT_VERIFIED`; the operational
`OneCWritePort` must remain uncomposed and cannot dispatch writes.

The vendor's [1C:Enterprise 8.3 Administrator Guide, File Mode, §§ 10.3.1.4, 10.3.7.1, and
10.3.8.1–10.3.8.2](https://1c-dn.com/library/tutorials/1c_enterprise_administrator_guide_file_mode_8_3_27/)
describes hardware/HASP binding, reacquisition via the original activation method, moving an
existing license file outside active search locations during reacquisition, and Windows search
locations. These are references only; no license reactivation, account sign-in, license-term
acceptance, purchase, or transfer was attempted.

Accountable owner: operator. Executor and coordinator: Codex. Technical host boundary: Ivan stack.
The operator owns identifying or restoring an authorized, valid license source; Codex continues
independent repository coding and retries the read-only clone inventory only after that source is
available.
