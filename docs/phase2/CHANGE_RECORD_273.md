# Change Record 273 — guarded CT14 metadata-only inventory

## Ownership and state

- Date: 2026-10-25.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical host owner: Ivan stack (`ERP_MCP_Ivan_Stack`); individual maintainer of this utility is not established.
- State: read-only inventory utility and fail-closed CT14 path/process/argument guards implemented; metadata collection is `NOT_RUN` because local COM connection failed at license activation; source review is complete for the scoped guard changes, tests remain pending.

## Change and reason

`testlane/onec_extension/scripts/ct14_metadata_inventory_readonly.py` uses the CT14 helper's exact `818HA_p2diff` clone guard and in-process DPAPI credential loader. The guard now compares resolved full paths and refuses explicitly, including under optimized Python. The Designer helper now refuses unless `tasklist` successfully and positively confirms that both 1C executables are absent; active, failed, or unrecognized process-state results stop it. The inventory's only COM reads are configuration/platform identity plus the `ПоступлениеТоваровУслуг` document's requisites, tabular sections, and section requisite names. It does not execute a 1C query, read business rows, change rights/users, write files, alter 1C data, or print credentials. The output is a metadata inventory input for a separately reviewed payload-to-property crosswalk; the tool deliberately does not infer that mapping.

`run_designer` snapshots its caller-supplied arguments and rejects selectors that could replace the
guarded `/F` base, switch to `/S` or an alternate infobase connection string, override `/N` or `/P`
credentials, or replace `/Out`. The exact documented `-Files` and `-partial` selectors remain
available. This is source-level protection; no Designer process was started.

## Evidence and limits

- Source: `testlane/onec_extension/scripts/ct14_metadata_inventory_readonly.py`; design boundary: `S14_COM_EPHEMERAL_VALUE_BINDING_DESIGN_2026-10-25.md`.
- Inventory script SHA-256: `50E9B4915CF53E8E9B560835096CE699A707DDE0732254359C0B1AA65CD89734`.
- CT14 common-helper SHA-256: `53625350C82E2CEB901AAA6C492DAC0410F1104F891EA240E6ABA578C7166721`.
- The local disposable path and user-secret file were present by path check; `admin_creds()` then returned successfully, so its protected password blob was readable/decryptable in-process. Neither file content nor credential value was displayed.
- Read-only SSH using strict host-key checking to `koros@100.88.71.74` found no local-style `D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff` path, but did list the remote `D:\1c\env\bases\818HA_p2diff` directory by name. A sanitized name-only extraction from `D:\1c\env\odata\erp_mcp_ref\default.vrd` returned `818HA_p2diff`; these establish a remote path and configured database name, not lineage, loaded route state, or a COM connection.
- Filtered host-script evidence shows `setup-1c-odata.ps1` defaults to `818HA_reference_ro`, while `store-onec-admin.ps1` defaults to `D:\1c\env\bases\818HA_test_ready`; the DPAPI credential is therefore not assumed to authorize `818HA_p2diff`. No repoint or setup script was run.
- A `code-reviewer` found the old helper used optimizable `assert` and only a basename suffix; both weaknesses were removed, and the clone-only qualification now covers normal and optimized Python. The reviewer then found tasklist mixed-output and missing-`stderr` fail-open cases, which were fixed. For the argument filter, the reviewer caught and helped close an incompatibility with `-partial`; the final follow-up found no bypass of the protected connection/output selectors and confirmed compatibility with repository calls. No test or Designer run occurred. A separate time-of-check/time-of-use interval remains between the `tasklist` observation and process creation; this guard does not serialize arbitrary external 1C launches.
- The current-turn focused follow-up was the actual agent `/root/s14_value_binding_review`, assigned the `code-reviewer` role. The collaboration result did not expose its model or reasoning-effort metadata; those values are `NOT_EXPOSED`, not inferred. The reviewed final helper locations are `ct14_common.py:75-106`.
- The local utility was invoked with `.venv\Scripts\python.exe`. Credential loading succeeded without outputting the username or password. COM `Connect` failed before metadata reads; sanitized output was `CT14_METADATA_COM_CONNECT_FAILED`, exception type `com_error`, HRESULT `0x80020009`, automation code `0x80004005`, diagnostic class `LICENSE`. No raw COM description was emitted.
- A direct local-gateway `source_health` call for `onec-818ha-reference` returned an MCP tool error; only the sanitized class `UNCLASSIFIED_TOOL_ERROR` was retained, and the dependent metadata call was skipped. No ChatGPT ERP connector was used.
- No 1C process or service was restarted. No 1C business query or write, PostgreSQL operation, test, check, build, CI, migration, staging-environment deployment, commit, or push was run for this change.

## Remaining acceptance and owner

The current verified source `CT14Писатель` rights remain the historical measured rights in `testlane/onec_extension/STATUS.md` and `CT14_FEASIBILITY_SPIKE_2026-10-12.md`; this inventory does not remeasure rights. The exact COM destination/type crosswalk remains `NOT_VERIFIED`. The technical dependency is a licensed COM session against the authorized `818HA_p2diff` clone. The Ivan stack is the technical owner of the licensed host boundary; the operator remains accountable; Codex continues the local implementation. Once a permitted COM session is available, rerun this metadata-only utility, reconcile names/types against the approved payload, and then complete the concrete `OneCWritePort` before test phase.
