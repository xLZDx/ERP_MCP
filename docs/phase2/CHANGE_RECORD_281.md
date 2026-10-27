# Change Record 281 — prevent cross-base call-ID lookup disclosure

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP private-writer admission and lookup boundary.
- State: source-only candidate; SQL parse, migration, database operation, tests, checks, build, CI, staging, commit and push were not run.

## Baseline and change

Migration 027, the S12/S13 qualification prerequisites and `evidence_key_resolver.py` were already untracked before this turn. Their pre-edit SHA-256 values were migration 027 `473C507119CCB5771F1890B1FC25A4C076E5C1B99AD3516A76A224BE8098A64C`, qualification prerequisites `478E58882FFE24A0E944177C7E1054BE720A10567EA31F95BFC51A03FB334A1C`, and `evidence_key_resolver.py` `0ED69A00402828923172EB6CDFEE48FF075E364010738B8624ECC3F18F8B4D46`.

`private_writer_lookup_v1` authenticated the requested base, searched for the call ID within that base, then performed a global existence query when the scoped lookup missed. It returned `CALL_IDENTITY_CONFLICT` if the ID belonged to another base, allowing a caller with a valid binding on base A to distinguish a call ID that exists on base B from an ID absent everywhere. The scoped lookup now returns `NOT_ACCEPTED` on every miss, without querying other bases. A changed immutable tuple for an attempt found on the caller's base still returns `CALL_IDENTITY_CONFLICT`. Admission remains fail-closed: it cannot create a duplicate because the globally unique `dispatch_attempts.call_id` constraint remains authoritative.

`private_writer_lookup_barrier_v1` similarly returned `NOT_ENTITLED` when an existing barrier belonged to another base, but `NULL` for an unknown ID. With a valid base-A binding, a caller could therefore confirm that a probed barrier ID existed on base B. Foreign-base barriers now return the same `NULL` result as unknown IDs; an exact barrier remains visible only when the caller has an active binding for that base.

The evidence-key acceptance path also required deterministic revocation ordering. `private_writer_resolve_signer_key_v1` now obtains the exact public-key-material advisory lock and then repeats its scoped validity/revocation query; `private_writer_key_revocation_guard_v1` takes the same lock before locking the key-version row. The resolver samples trusted database validation time after the lock, so a revocation that commits during lock wait cannot be compared to stale pre-wait time. It rejects non-READ-COMMITTED or non-READ-ONLY SQL transactions with the mapped `EVIDENCE_KEY_TRANSACTION_INVALID` code, so an authorized direct caller cannot use a repeatable-read snapshot to bypass the post-fence refresh.

## Affected paths and evidence

- `db/phase2/027_private_writer_admission_schema.sql`: `private_writer_lookup_v1` scoped call lookup/miss handling around lines 1814–1818, `private_writer_lookup_barrier_v1` binding check around lines 1853–1858, `private_writer_resolve_signer_key_v1`, and `private_writer_key_revocation_guard_v1`.
- `src/erp_mcp_private_writer/evidence_key_resolver.py`: maps SQLSTATE `P0001` plus `EVIDENCE_KEY_TRANSACTION_INVALID` to a stable resolver error.
- Read-only COM prerequisite evidence collected this turn: the guarded local metadata inventory failed with `CT14_METADATA_COM_CONNECT_FAILED` / HRESULT `0x80020009` / automation code `0x80004005` and classifier `LICENSE`; strict-host-key SSH invocation of `store-onec-admin.ps1 -TestOnly -BasePath D:\1c\env\bases\818HA_p2diff` reported `COM connect ok: False` and sanitized `License not found. Software protection key or acquired software license not found!`. No credential, metadata, business row, COM mutation, database write or service restart occurred. This is an external qualification prerequisite, not proof that the source changes are valid.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: adds focused cross-base non-disclosure cases adjacent to admission crash/replay cases.
- Contract: `docs/phase2/S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md` defines `NOT_ACCEPTED` for an absent exact lookup, exact immutable replay as lookup-only, and global unique call identity. The source inspection identified the difference between scoped miss and global ID probing.
- SHA-256 at this record snapshot: migration 027 `A99638E2B907919D11A63A6E8EBDD3D745CC83CFA12FBD54FA5E1D103DBA4DC2`; qualification prerequisites `C8EAD91C37A6DDC849E78E4DAB773FB3C1ADCA2249E1EE3A25F2D5833984D2F5`; admission design `59883DDD62ACE6ECD45D6D5FED25C94B1CE8BA447642E837CB2E5DDCECF7C1C4`; COM binding design `4306CDCFA00F0BD866034D6A45DC4D79CBB1A42261A4314F0A9D03B89B9E32BA`; document index `C2809851378523A0C2D36000C53116092E34130FBF7267C7D88D0486A07F255C`; evidence-key resolver `358333C02EB23DCA65CFD782E54470E9A29E850E5D71EB8F4FF04EDFB0B78DEF`.
- No SQL parse, migration, database query, test, check, build, CI, staging, commit or push was run.

## Limits and next action

This closes a source-level cross-base existence oracle only. It does not prove SQL validity, ACLs, transaction behavior, effective grants or disposable runtime qualification. Continue the S13 source closure; after coding closes, `functional-test-reviewer` owns the focused non-disclosure, exact replay, and same-base conflict scenarios, with the E2E qualification performed by `e2e-runner` on the approved disposable environment.
