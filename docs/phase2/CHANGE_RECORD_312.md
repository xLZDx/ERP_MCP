# Change Record 312 — bound Content-Length comparison before integer parsing

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP private-writer ingress.
- Acceptance: `S13-PRIVATE-INGRESS-CONTENT-LENGTH-01`.
- State: source-only improvement; no test, check, build, CI, runtime, or deployment evidence.

## Finding and change

`_read_bounded_json()` previously converted the complete caller-supplied `Content-Length` string
with `int()` before checking the 1 MiB limit. The ASGI server normally bounds header size, but the
conversion was unnecessary and allowed arbitrarily long decimal headers to consume integer-parser
work before the ingress returned its request-size refusal.

The ingress now strips leading zeroes (retaining `0` for an all-zero value) and compares decimal
length and lexical value against the decimal 1 MiB ceiling. Values above the ceiling return the
existing `REQUEST_TOO_LARGE` path before body streaming and before integer construction. Existing
ASCII-decimal validation, duplicate-header refusal, and streaming byte-count limit remain in
place. Leading zeroes do not change the represented number.

## Affected paths

- `src/erp_mcp_private_writer/private_ingress.py` — bounded `Content-Length` preflight.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — exact acceptance
  boundaries and delegated test ownership.
- `docs/phase2/OPERATOR_BACKLOG.md` and
  `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` — current source and verification state.

## Evidence and limits

- Current source SHA-256: `C7DAFF1C23EE350A5E246DC1E308859F469FB508599C1AEF3AFF6588E65BE2AD`.
- A fresh read-only `code-reviewer` review found no issue in ASCII validation, leading-zero
  normalization, the exact ceiling comparison, or the over-limit path. The review confirmed long
  nonzero values avoid integer conversion; all-zero values require only linear string scanning.
  Reviewer model and effort metadata were not exposed.
- No tests/checks/build/CI were run. The acceptance remains `NOT_RUN`; the streaming byte limit and
  runtime response path are not newly qualified by this source change.

## Required qualification

`functional-test-reviewer` must prove exact 1 MiB acceptance, 1 MiB plus one refusal before stream
read, smaller values with leading zeroes, a very long all-zero header, a very long over-limit
header, and invalid duplicate/signed/whitespace/non-ASCII forms. Confirm that understated or absent
lengths remain protected by the streaming limit and that refusal makes zero downstream calls.
