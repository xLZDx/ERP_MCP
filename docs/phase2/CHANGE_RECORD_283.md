# Change Record 283 — bound private-writer JSON structure before decoding

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP private-writer ingress and S12 evidence-parsing boundary.
- Frozen acceptance closed: `WP5-VERIFIER-DECODE-01` and the S13 private-writer ingress boundary in `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.
- State: implementation candidate; functional/E2E tests, checks, build, CI, runtime qualification, benchmark, database/COM operation, staging, commit and push were not run.

## Baseline and change

The sources were already present as untracked candidates in the dirty worktree before this turn; this record does not attribute their original implementation to the current executor. At the start of this change, SHA-256 was:

- `src/erp_mcp_private_writer/production_evidence_verifier.py`: `3BE181FEC2A14B14106EE91074D78D50CF6C2A082BDF3CD2508EAEE90C258D1A`.
- `src/erp_mcp_private_writer/private_ingress.py`: `C688B13F9F108C13E4B73A8145B5714C2A57E627693E838B1AC2EBE0817C786F`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `58E4981E37C072B226B9B8E6D17CD26FC6500604E08880C44BC5DA81FF93E099`.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`: `BEB47195BB5FDD1DCA3AF26B1C4C398846F55F149B781CEF79C846BEA780B114`.
- `docs/DOCUMENT_INDEX.md`: `CCAAF666F234D59F10B8ED1E187067A97AE9A3A5FBE12816850861A6872B65D8`.
- `src/erp_mcp_private_writer/json_preflight.py` and this record: absent.

The S12 evidence verifier already applied a lexical depth and structural-node bound before
`json.loads`, while the authenticated private ingress only bounded request bytes. Its decoder could
therefore allocate a large or deeply nested object tree within the 1 MiB body limit. This change
extracts the non-recursive lexical scanner to `json_preflight.py` and applies it to both boundaries.
It counts the root and each JSON value, plus each object key, and uses shared limits of 32 nested
containers and 100,000 structural nodes so the verifier and ingress cannot drift independently.
`json.loads` remains responsible for full JSON grammar,
duplicate-key handling, numeric policy and typed validation. The ingress byte ceiling remains 1
MiB; the S12 evidence envelope ceiling remains 2 MiB.

Private ingress maps preflight failures through its existing `INVALID_REQUEST`/400 path, after the
existing caller authentication step. Dispatch and lookup do not reach their ticket/permit
authorization verifier or service method until body decoding and schema validation succeeds. The
source design is intentionally bounded but is not runtime or
allocation evidence; qualification must prove exact boundaries and zero downstream calls.

## Affected paths and acceptance

- `src/erp_mcp_private_writer/json_preflight.py`: shared iterative lexical scanner and shared limit
  constants; counts object keys and values and checks depth before tree allocation.
- `src/erp_mcp_private_writer/production_evidence_verifier.py`: uses the shared helper with its
  existing 32-container/100,000-node contract.
- `src/erp_mcp_private_writer/private_ingress.py`: preflights strict-UTF-8 request text before
  `json.loads`, using 32 containers and 100,000 nodes under the existing 1 MiB body ceiling.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: adds
  `S13-PRIVATE-INGRESS-JSON-STRUCTURE-01` with exact boundary and no-downstream-call criteria;
  runtime state is `NOT_RUN`.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`: records the source-only implementation
  and deferred qualification work for the next continuation.
- `docs/DOCUMENT_INDEX.md`: links this change record.

Post-change SHA-256 snapshot: `json_preflight.py`
`C88EA5922637F6DFBC45C4F55746AF71FFB7A85A929DDFA4A9383E49F775E774`;
`production_evidence_verifier.py`
`9E513570862BC118135005D294287DEC7FC927D62BA4368C48AA6A19221717E5`;
`private_ingress.py` `EF1C3F3957B230694C87F4BD8E116E4796D769B79883042B0311BB9F3140FEE5`;
qualification prerequisites `454B333777AEA44A1859231C8CCAE4CCE7BE74E39AE48AC7998E2998B258E1FD`;
continuation prompt `9A7A5C291923285F966112F1B1651D6882175C7D0D5860F13B8379E964D96B52`;
document index `5598E6BF99CF8AAD8595C7FA86A1F8371DBA0CEFFC920D1C7429D2C3E21DD92B`.

## Verification and next action

No tests or checks were run in the coding phase. The implementation has not been manually reviewed,
runtime-proven or independently reviewed. After all coding for this scope closes,
`functional-test-reviewer` owns exact depth/node and malformed-input unit boundaries; `e2e-runner`
owns both ASGI endpoints, exact `INVALID_REQUEST` responses and zero verifier/service calls. They
must also prove that accepted bodies preserve current behavior and that S12 evidence verification
still uses the same limits. Record exact commands and results; leave runtime acceptance `NOT_RUN`
until those scenarios run.
