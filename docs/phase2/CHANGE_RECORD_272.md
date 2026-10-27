# Change Record 272 — ephemeral approved-payload values for COM

## Ownership and state

- Date: 2026-10-25.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical host owner: Ivan stack (`ERP_MCP_Ivan_Stack`); individual maintainer of this source path is not established in this record.
- State: source helper and qualification contract updated; one independent read-only code review found no actionable finding; tests and runtime qualification remain pending.

## Change and reason

The digest-only `MappedPropertyAssignment` in `src/erp_mcp_private_writer/com_manifest.py` proves
payload-to-destination coverage but cannot itself supply property values to a future COM call. The
new `ComValueAssignment` and `com_values_from_approved_payload` provide a separate ephemeral value
tuple after validating the exact approved payload digest and reusing the manifest's shared one-to-one
source/destination validation. Both an external target version and the payload's embedded
`expected_target_version` must be absent for CREATE_DRAFT. Values are excluded from `repr` and equality; the existing
`PreparedComManifest` continues to contain value digests only. The function refuses a non-payload,
non-CREATE_DRAFT target preimage, changed approved digest, noncanonical value, or unqualified shape
before any COM code is involved. `ComValueAssignment` also rejects mutable containers on direct
construction, so its captured digest cannot diverge from an ephemeral value before the call.

This does not authenticate or invent the missing `818HA_p2diff` crosswalk, connect to COM, implement
`OneCWritePort`, alter runtime composition, sign a receipt, or enable writes. Callers must keep the
returned values local to the COM invocation and must not log or persist them.

## Design and acceptance

- Design note: `S14_COM_EPHEMERAL_VALUE_BINDING_DESIGN_2026-10-25.md` records the alternatives,
  chosen boundary, failure behavior, rollback, test plan, and unresolved crosswalk dependency.
- Qualification: `S14-COM-EPHEMERAL-PAYLOAD-VALUE-01` in
  `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`; execution is `NOT_RUN`.
- `src/erp_mcp_private_writer/com_manifest.py` SHA-256:
  `A1F5F9356C6C573C73BE1CB59B874F42ADE5CFB92D79B8E18C7B3D52930B4F02`.
- `src/erp_mcp_private_writer/__init__.py` SHA-256:
  `26EF30D1B1D2EAE43FBB08012E3DAC49900DD87BE7DB1073CFBB7AEE0A9A6F3A`.

## Verification and limits

Source was inspected for shared mapping validation, approved-digest comparison, value redaction, and
the unchanged digest-only manifest. No test, check, build, CI, SQL parse, migration, database query,
COM operation, staging deployment, commit, or push was run. Exact clone metadata/crosswalk,
effective current Ivan rights, and COM transaction behavior remain `NOT_VERIFIED`.

An actual `code-reviewer` agent pass reviewed the helper, immutable scalar constraint, exports, design,
and qualification criterion; it found no actionable BLOCKER, MAJOR, or MINOR finding. The agent result
did not expose exact model/effort metadata, so those are not claimed. The review was source-only and
does not establish runtime qualification.

After coding closes, `functional-test-reviewer` owns the helper's digest/mapping/redaction tests and
`e2e-runner` owns the physical writer scenarios once a concrete reviewed crosswalk and complete
operational port exist.
