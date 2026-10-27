# Change Record 235 — reject COM lane architecture mismatch before activation

## What changed

- Added an x64 process guard in `windows_com_sta_lane()`'s worker-side connector callback before `win32com.client` import or COM activation.
- Added fixed startup error `COM_LANE_ARCHITECTURE_UNSUPPORTED` to the safe COM startup taxonomy.
- Added candidate qualification `S13-COM-ARCHITECTURE-01` for x86 refusal and x64 continuation to the existing activation/fingerprint checks.

## Why

Current strict-SSH evidence shows Ivan's registered `V83.COMConnector` resolves to
`D:\1c\env\1cv8_x64\8.3.27.2342\bin\comcntr.dll`. A 32-bit process cannot safely assume it can activate that registered in-process server. Refusing before pywin32 import/COM activation gives a stable compatibility error rather than an opaque class-registration or connector error. This does not prove a 64-bit connection succeeds and does not add any 1C operation mapping.

## Baseline and provenance

`windows_com_lane.py` and the qualification prerequisite file were already untracked in the pre-existing dirty worktree. Their observed pre-edit hashes were:

- `src/erp_mcp_private_writer/windows_com_lane.py`: `2280263D85B280D71B04B8407420C4063B39FB8E0AD91C1174FBD82CCDFB3D67`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `D643AD265D0B27767073663EECA0F0969008A7054FDA774C962FBC38142087A1`

`com_sta_lane.py` was also pre-existing untracked; its pre-edit hash was not captured before adding the stable error code. No unrelated worktree state was changed intentionally.

## Verification state

- The current-turn host registry/file inspection was read-only: ProgID `V83.COMConnector` resolves to CLSID `{181E893D-73A4-4722-B61D-D604B3D67D47}`; `InprocServer32` is the x64 DLL above; file version `8.3.27.2342`, length `674376`, Authenticode `Valid`.
- Code is implemented and received one read-only local `code-reviewer` pass (GPT-6 Luna, low effort) against HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c` plus the working-tree files below; no material findings. `S13-COM-ARCHITECTURE-01` remains `NOT_RUN`.
- Reviewed working-tree SHA-256: `windows_com_lane.py` `1C737F09FED6B1389D7B3A6253153F3ADCF013BA90FF72A697C2A6619660F04C`; `com_sta_lane.py` `D57788D6EAD00C053DE026C79D01FF47B6665E6E135B9793425C2369CB8750CD`.
- No COM activation/Connect, rights query, database operation, service restart, test, check, build, SQL parse, migration, staging, commit, or push ran for this change.
- Current clone identity and rights, interpreter architecture on the live private service, licensing, payload mapping, and the prior sanitized COM `Connect` failure cause remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator; executor: Codex. Ivan stack is the technical host owner. After code closure, functional/E2E roles own the x86/x64 guard qualification. Continue the source lock/ACL closure and obtain a supported read-only clone identity before implementing the operational COM port.
