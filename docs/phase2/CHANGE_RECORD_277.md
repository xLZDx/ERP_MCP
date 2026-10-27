# Change Record 277 — bind the Windows COM lane to its expected 1C user

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and technical closure owner: Codex.
- Technical host owner: Ivan stack (`ERP_MCP_Ivan_Stack`); test roles are execution roles, not project owners.
- State: source-only implementation; a focused actual `code-reviewer` pass found no source-level blocker. No tests, checks, COM calls, database operations, or external deployment were run. Disposable qualification remains `NOT_RUN`.

## Change and reason

`windows_com_sta_lane()` now requires an explicit expected 1C user name. On the dedicated STA worker, immediately after COM connection and before the base fingerprint callback or lane opening, it reads `InfoBaseUsers.CurrentUser().Name` and compares the exact string with the configured expected user. A missing/unreadable identity or mismatch fails with a stable sanitized `ComLaneError`; the lane never exposes the connected session to operations. `com_sta_lane` includes both errors in its safe startup-error allowlist.

This prevents an accidentally supplied administrator or other account from being treated as the intended least-privilege writer merely because the base fingerprint matches. The check is only a process identity binding: it does not establish effective `CT14Писатель` rights, authenticate the expected-user configuration, prove the connected base identity, or establish any S12 ticket/permit or physical-write property. These still require independent qualification. The existing COM lane has no in-repository caller, so the required argument does not change an active runtime composition.

## Affected contracts and paths

- `src/erp_mcp_private_writer/windows_com_lane.py`: required expected username, shape validation, exact current-user check, sanitized refusal.
- `src/erp_mcp_private_writer/com_sta_lane.py`: safe startup error classification.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `S13-COM-USER-BINDING-01` acceptance scenario.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`: current implementation/evidence checkpoint.
- Current SHA-256: `windows_com_lane.py` `D73E5F4D6858422008E209F64445D12154E1BEDE488A1DB1A5464E878D33B5F4`; `com_sta_lane.py` `2400799249C3FE1A94C807BFB12D46FAA57E4DD2737011C78B9149B0CC7FDE7A`; qualification prerequisites `9608A5EE41635A07C0BD4F8D23845350E266DFBED684B91C95427F63EC0169AD`.

## Verification and limitations

- Source inspection: `InfoBaseUsers.CurrentUser().Name` is already used in the repository's guarded credential-proof script `scripts/remote/store-onec-admin.ps1` to compare the returned user name; that prior use was for a disposable base and does not prove the new lane behavior.
- Static call-site search: `rg -n "windows_com_sta_lane\\(" --glob '*.py' .` found only the definition, so no production composition currently needs the new argument.
- Focused actual `code-reviewer` pass (`/root/com_user_binding_review`) found no material source defect and confirmed STA ordering, sanitized refusal, UTF-8 byte comparison, and no in-repository call-site break. Model/effort metadata were not exposed.
- No test, check, build, CI, SQL parse, migration, database mutation, or writer COM operation was run. The read-only metadata inventory command `.venv\Scripts\python.exe .\testlane\onec_extension\scripts\ct14_metadata_inventory_readonly.py` exited `1` before a COM session was established, returning sanitized JSON `CT14_METADATA_COM_CONNECT_FAILED`, exception class `com_error`, HRESULT `0x80020009`, automation codes `0x00000000` / `0x80004005`, diagnostic class `LICENSE`. Its guarded helper loaded the DPAPI credential in process and emitted no credential value or business data. Do not retry the same COM path without a changed license/connection condition.
- Exact expected-user provenance and effective role membership remain `NOT_VERIFIED`; the local secret-store filename inventory shows an admin clone credential and a test-reader credential but no file named for CT14. The remote `D:\1c\mcp\env` inventory shows `onec_admin.dpapi`, `test_reader_password.dpapi`, and `credentials.json`; only the JSON top-level key `users` and in-memory substring booleans were inspected, with no text naming `818HA_p2diff` or `CT14`. No credential values were emitted. Do not substitute the administrator account.
- Strict SSH directory inventory (`D:\1c\env\bases`, names/timestamps only) found the `818HA_p2diff` directory on Ivan's host. Its presence does not prove that the current license is available or that either listed credential maps to that base. The local clone metadata probe failed with `diagnostic_class=LICENSE`, and the remote host's `onec_admin.dpapi` default target is documented as `818HA_test_ready`; no connection attempt was made with that credential against `818HA_p2diff`.

## Next steps

1. Codex obtains or creates, through the approved disposable-clone preparation path, a secret-safe credential binding for the exact least-privilege writer user; do not expose its password.
2. Functional-test reviewer qualifies matching, mismatching, unavailable, and malformed current-user outcomes before any COM write scenario.
3. Database-reviewer independently measures effective CT14 rights on the approved installed clone/configuration.
4. Only after the mapped payload/property contract and identity evidence are accepted, implement the physical `OneCWritePort`; then complete all coding before starting the functional/E2E phase.

