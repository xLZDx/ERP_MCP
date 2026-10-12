# Local 1C / RSVData environment handoff

Date: 2026-10-06
Device: Razer / Windows x64
Repo: D:\Repo\ERP_MCP
Observed working branch: phase/p6-rsv-bridge-boundary

## Completed by Desktop Commander
- Standard/full 1C platform search: NOT FOUND yet.
- Training Edition is intentionally NOT installed because it cannot validate the P6 COM route.
- Official MCP:RSV Data v1.3.0 ZIP verified: SHA256 11de9a47cc4d0fc38d0e93e032b3cc69c5641774cb51fd529f930699f12c8a12.
- RSVData.cfe staged at D:\ERP_MCP_Testbed\rsvdata\v1.3.0\release\MCP-RSV-Data\RSVData.cfe.
- RSVData.cfe SHA256: 01055749d44d4b44f941aadb4ea132e4054aa962d6f92019b252a374797f8d4d.
- Release bridge SHA256: 5c14b7db16e5dbf8cd20e2619255fe849edc75ac514bd6a21dedb1599710d728.
- Pinned upstream source cloned outside Git at D:\ERP_MCP_Testbed\vendor\mcp-rsv-data-src.
- Pinned source HEAD: 76fed8e6e16833fee1514969841b8d9a61c7c152.
- Go 1.27.0 x64 installed user-space at D:\Tools\go1.27.0-full\go\bin\go.exe and added to user PATH.
- Go ZIP SHA256 verified against go.dev metadata: f0c0a0d33ba94f4d2c5dbc887334ce678b21813504ddb3aafcb06e60a5a667c4.
- Bridge built successfully from pinned source; build SHA256: 9718dfa06c9f1f7014d1003a7f1c957600a6330f4d7a98190e8adf24eb7b3405.
- VC++ runtime present (vcruntime140/msvcp140 14.51.36247.0).
- COM smoke currently fails exactly at V83.COMConnector creation with "Invalid class string", proving platform/COM registration is the missing runtime component.

## Testbed paths
- Official 1C installer drop: D:\ERP_MCP_Testbed\1c\installer
- Disposable base: D:\ERP_MCP_Testbed\1c\bases\RSVDataAudit
- Extension dump/export: D:\ERP_MCP_Testbed\1c\exports\RSVDataAudit
- Evidence: D:\ERP_MCP_Testbed\1c\evidence

## One unavoidable operator/account step
Official standard 1C x64 distribution requires authenticated developer.1c.ru / 1c-dn.com access.
The official updates and Community License pages were opened in the browser.
Download standard Windows x64 platform >= 8.3.24.1528 (8.3.27 preferred), NOT Training Edition, into the installer drop above.
Community/Developer License activation also requires the operator portal login/verification.

## Continue automatically after the distribution appears
1. Run: powershell -ExecutionPolicy Bypass -File scripts\install_local_1c_after_download.ps1
2. Review valid Authenticode signer output.
3. Run same script with -Install.
4. Run scripts\verify_local_1c_environment.ps1.
5. Verify V83.COMConnector; if platform exists but COM class is absent, locate matching x64 comcntr.dll and register it using the vendor-supported/admin path (may require one UAC approval).
6. Create disposable synthetic file base only; never use a production/customer base.
7. Install staged RSVData.cfe in that base; run bridge diag/ping/tools/list.
8. Dump extension to XML/BSL and complete reports/RSVDATA_EXTENSION_AUDIT.md.
9. Keep execute_query and reveal DENIED until read-only + company-scope audit passes.
10. Reuse existing bridge; do not implement another COM/native bridge.

## 2026-10-06 update — first 1C download inspected
- Downloaded artifact: D:\ERP_MCP_Testbed\1c\installer\windows64_8_3_27_2342.rar
- Archive extracted successfully with 7-Zip.
- setup.exe Authenticode: VALID.
- Signer: LLC 1C-Soft; issuer: GlobalSign GCC R45 EV CodeSigning CA 2020.
- setup.exe SHA256: 301e88416bef85dfb17d87f7e19806672b3001144dc74f9e7f548b832c670c13.
- MSI product is `1C:Enterprise 8 Server (x86-64)`.
- MSI contains COMConnector, but File table does NOT contain 1cv8.exe / Designer.
- Direct MSI user-mode attempt was rejected because server package requires authorized/admin install.
- setup.exe `/S ALLUSERS=3` also surfaced an Error dialog and did not register V83.COMConnector.
- Do not spend more time on this server-only package for the P6 file-base path.
- Required next official artifact: windows64full_8_3_27_2342.rar (full x64 Windows distribution, same version).
- Once full archive is present, inventory its MSI/features before install; require client_full/Designer and COM registration.
- Preferred install mode: per-user x64 under %LOCALAPPDATA%\Programs\1cv8_x64, avoiding machine-wide changes unless unavoidable.
