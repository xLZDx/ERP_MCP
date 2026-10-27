# Change Record 308 — bound driver-decoded trust snapshots

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Acceptance: WP5 strict JSON decoder / `WP5-JSON-DECODER-01`; S13 trust-source custom-codec boundary.
- State: implemented in source; tests and runtime qualification remain `NOT_RUN`.

## Change and reason

`PostgresEvidenceTrustSource._decode()` accepts raw JSON text and driver-decoded dictionaries.
The raw-text path rejects duplicate keys while scanning and parsing the exact source bytes. The
dictionary path cannot recover duplicate keys that a driver codec has already discarded, but the
WP5 contract explicitly requires bounded support for such results. It accepts only an exact
built-in `dict`, then iteratively checks the whole object tree's JSON types, depth, node count,
scalar validity and compact encoded size before snapshot construction. It does not serialize the
object to measure it. Both paths return the stable `TRUST_SNAPSHOT_PAYLOAD_INVALID` error for
malformed or over-bound values.

The later S13 instruction to reject decoded-object codecs applies to the separate attempt-context
lookup adapter and its raw JSON byte cap; it does not supersede the trust-snapshot decoder's WP5
dictionary-path requirement. The attempt-context adapter already requires exact raw text.

## Affected paths

- `src/erp_mcp_private_writer/postgres_evidence_trust.py` — retain duplicate rejection for raw
  text and bounded iterative validation for decoded dictionaries.
- `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md` — distinguish the trust
  snapshot decoder from the separate attempt-context raw-text boundary.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` — existing WP5 decoder acceptance remains
  the follow-up test owner contract.

## Evidence and verification

- The only production caller passes the `fetchval()` result directly to `_decode()`; the WP5
  acceptance explicitly covers driver-decoded dictionaries.
- Current source SHA-256: `7A2C2AAA3B9236D105ED801B8E94554322980F0F18B5ACE10B36FD79681294DA`.
  This identifies the source bytes only; it is not test or runtime evidence.
- No test, check, build, SQL parse, database operation, migration, COM action, staging, commit, or
  push was performed for this change. Coding remains open, so test execution is deferred to the
  designated functional/E2E roles after code completion.

## Remaining acceptance

Post-coding qualification must exercise dictionary byte, depth, node, scalar and schema
boundaries, including non-JSON objects and cyclic containers, and confirm refusal before any trust
snapshot is returned. The raw-text path must retain duplicate-key detection, including
escaped-equivalent keys. The candidate S13 schema and effective grants remain
uninstalled/unmeasured, so no runtime claim is made.

Next: continue WP5/S13 source closure, then have functional-test-reviewer/e2e-runner execute the
mapped decoder cases after all in-scope coding is complete.
