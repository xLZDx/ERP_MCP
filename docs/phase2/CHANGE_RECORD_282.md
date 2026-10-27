# Change Record 282 — bound S12 envelope decoder structure

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP S12 evidence parsing boundary.
- State: source-only candidate; tests, checks, build, CI, parser benchmark, migration, database operation, COM operation, staging, commit and push were not run.

## Baseline and change

The verifier and qualification document were existing untracked candidates before this change. Their pre-edit SHA-256 values were verifier `A320C95C4EB71455B2F4BA251C28172F72226C42B104F8C82B5F3953841DCF0D` and qualification prerequisites `C8EAD91C37A6DDC849E78E4DAB773FB3C1ADCA2249E1EE3A25F2D5833984D2F5`. The evidence-registration design was also pre-existing in the dirty worktree; its pre-edit SHA-256 was `A45832A08AE295D8BC07D5ED29C0CAABB9016262B43296D08E39BA42E5ACF20E`.

`ProductionEvidenceVerifier._check_json_envelope_limits` lexically counted JSON values and limited nesting before `json.loads`, but did not count object keys. The standard decoder materializes object pairs before `object_pairs_hook` rejects duplicate keys, so an attacker could spend the preflight budget on a wide object while the decoder allocates both its keys and values. The preflight now counts every object key as a structural node and reduces the total node limit from 1,000,000 values to 100,000 keys-plus-values. The outer 2 MiB byte ceiling and 32-container depth limit remain unchanged; full JSON syntax and canonical representation still belong to `json.loads` and the canonical byte comparison.

The fixed-schema evidence records and nested movement data remain subject to the same 2 MiB envelope limit. The new 100,000-node cap is a defensive resource policy, not a measured runtime threshold; maximum valid movement cardinality and parse cost remain to be established in the focused qualification phase.

The same parser now uses a bounded integer callback for JSON numeric tokens. It accepts only signed 64-bit values, matching PostgreSQL `BIGINT`, and rejects longer tokens before constructing a Python integer. This prevents a large numeric token from reaching typed-record validation as an unbounded Python integer and keeps overflow failures on the stable envelope-invalid path.

Floating-point tokens are rejected by the JSON decoder callback before constructing a Python float. This matches `canonical_json_bytes`, which rejects floats; non-finite constants, `1e999`, and otherwise finite decimal/exponent tokens therefore share the stable `EVIDENCE_ENVELOPE_INVALID` path before trust-source lookup.

## Affected paths and acceptance

- `src/erp_mcp_private_writer/production_evidence_verifier.py`: count object keys before skipping each key string; reject the first node above 100,000 before building the decoded tree.
- `src/erp_mcp_private_writer/production_evidence_verifier.py`: parse integer tokens only within the signed 64-bit range.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `WP5-VERIFIER-DECODE-01` now requires the 100,000/100,001 structural-node boundary, signed BIGINT minimum/maximum acceptance, and out-of-range refusal; invalid envelopes must refuse before trust lookup.
- `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md`: records the allocation reason, exact bound, and still-unverified CPU/peak-memory evidence.
- Preserve accepted behavior for all envelope types, duplicate/escaped-equivalent keys, strict UTF-8, non-standard constants, canonical bytes, and exact schema selection.
- `docs/DOCUMENT_INDEX.md` links this record; the continuation prompt records the next WP5 qualification contract.

Post-change SHA-256 snapshot after the structural, integer and float-token bounds: verifier `3BE181FEC2A14B14106EE91074D78D50CF6C2A082BDF3CD2508EAEE90C258D1A`; prerequisites `58E4981E37C072B226B9B8E6D17CD26FC6500604E08880C44BC5DA81FF93E099`; evidence-registration design `F6ADC1560C6B23D03A9017E034F50A06F52F972C5A93FE1F808CA042E9CC562C`; continuation prompt `BEB47195BB5FDD1DCA3AF26B1C4C398846F55F149B781CEF79C846BEA780B114`.

## Verification state and next action

No test, check, build, CI, parser benchmark, migration, database operation or COM operation ran. This change is not runtime-proven or independently reviewed. After the remaining coding work closes, `functional-test-reviewer` owns exact parser boundaries and zero-trust-source-call cases; `e2e-runner` owns the production verifier boundary and allocation/timing evidence. Review the 100,000-node bound against the largest valid movement envelope before calling WP5 complete.
