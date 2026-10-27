# Change record 319 — S14 approved-payload COM value binding evidence

## Ownership and provenance

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor for this evidence pass: Codex.
- Technical boundary: S14 pure payload-to-COM assignment helper; no live writer boundary.
- Provenance: the implementation, design note and test file were already present in the dirty
  worktree before this turn. Their original author/session is not verified. This turn performed
  a read-only code review, delegated the focused functional test run, verified the resulting hashes,
  and recorded the evidence below; it did not implement the helper.

## Change under review

The existing `com_manifest.py` code derives ephemeral COM values from the exact approved
`DraftPayload`, requires a matching payload digest and the qualified one-line shape, checks exact
one-to-one source/destination coverage, and excludes authorization-only duplicate-override and
target-version fields. The durable `PreparedComManifest` continues to contain digest-only
assignments. This helper does not authenticate the supplied crosswalk, discover 1C metadata, invoke
COM, or authorize a write.

## Current-turn evidence

- Code-reviewer read-only review found no actionable BLOCKER, MAJOR or MINOR in the pure value
  binding source. It checked exact payload type/shape, mapping coverage and uniqueness, approved
  digest and target-preimage rejection, scalar immutability, value redaction from representation
  and equality, and the digest-only durable manifest. The review expressly treats live crosswalk
  authentication as outside this helper's contract.
- Functional-test-reviewer ran exactly:
  `uv run pytest -q tests/phase2/test_s14_com_ephemeral_value_binding.py`
- Result: **5 passed in 0.52 seconds**. This exercises pure Python only; no COM, database, lane,
  or production environment was used.
- SHA-256 after the run:
  - `src/erp_mcp_private_writer/com_manifest.py`:
    `A1F5F9356C6C573C73BE1CB59B874F42ADE5CFB92D79B8E18C7B3D52930B4F02`
  - `tests/phase2/test_s14_com_ephemeral_value_binding.py`:
    `9C6998CE4F3910D90217E8F132FA8CA7E3219D73CEE49423BD56801A7C1F310F`
  - `docs/phase2/S14_COM_EPHEMERAL_VALUE_BINDING_DESIGN_2026-10-25.md`:
    `4306CDCFA00F0BD866034D6A45DC4D79CBB1A42261A4314F0A9D03B89B9E32BA`

## Acceptance and limits

The source helper and its focused unit contract are reviewed and functionally qualified. This does
not qualify the exact `818HA_p2diff` property/type crosswalk, a concrete operational
`OneCWritePort`, COM transaction behavior, write-token isolation, or any real 1C write. Those
remain gated on a licensed authorized clone session and independently reviewed metadata mapping;
the current evidence records a sanitized COM license failure and no usable mapping. No COM call,
database operation, migration, staging-environment action, commit, or push was performed for this
record. The source file also had pre-existing staged and unstaged changes, so this evidence record
does not stage or commit them.

## Next action

The operator is accountable; Codex owns coordination and source integration. After the licensed
clone and exact destination/type crosswalk are established through the authorized read-only
metadata path, Codex can implement and review the concrete COM port. Until then, continue S13/WP5
code that does not invent the missing provider, key-custody or clone contracts; keep operational
writer activation disabled.

## Simulated protocol-consumer E2E evidence

- `e2e-runner` ran exactly:
  `uv run pytest -q tests/phase2/test_s14_simulated_write_port_protocol_e2e.py`
- Result: **4 passed in 0.49 seconds**. The journey is synthetic and in-memory; it exercises
  CREATE_DRAFT → POST → UNPOST, mismatch refusals, and unknown-outcome/no-retry behavior.
- SHA-256 values verified unchanged across the run:
  - `src/business_ai_gateway/phase2/simulation/simulated_write_port.py`:
    `78AD0EB8AFDFDB22003B884EFA6A4964BC190BF8B8EEAE1286A4D18625EE659D`
  - `src/business_ai_gateway/phase2/simulation/clone_1c.py`:
    `0E83D8939C529374D26DDD307D44DBD03B3FC38E1069B4EF92DCA97C111DB865`
  - `tests/phase2/test_s14_simulated_write_port_protocol_e2e.py`:
    `247B174B0A48AC28AFCDC30748A0A12FF6DABBFDC94F2CC8BABDD9FF5A3CE0DF`
- This qualifies local simulated protocol-consumer behavior only. It does not qualify real 1C,
  CT14, COM, a licensed clone, S13 acceptance, or the production writer boundary. No source files
  were changed by the E2E run.
