# WP5 strict trust-snapshot JSON decoding

## Change

Updated `PostgresEvidenceTrustSource` so string payloads reject duplicate keys at every object
nested level and reject the non-standard JSON constants `NaN`, `Infinity`, and `-Infinity`.
Added pre-parse O(input-size) scans for the 8 MiB UTF-8 byte ceiling, a 32-level depth ceiling,
and a 1,000,000-value ceiling; an iterative post-decode structure/size check; a
20-digit/signed-32-bit integer limit; rejection of all floating values (including `1e999`); and
invalid Unicode scalar rejection. Driver-decoded dictionaries receive an iterative size/shape
preflight before any serialization. All invalid payloads map to
`TRUST_SNAPSHOT_PAYLOAD_INVALID` without returning payload or parser details. Updated the S13
disposable acceptance row and evidence-registration design note with the exact bounds and
remaining worst-case resource qualification; added the lesson to `core/LESSONS_LOG.md`.

## Why

The default Python JSON parser silently uses the last value for duplicate object keys, accepts
non-standard numeric constants and can parse non-finite results from large exponents. The first
pre-commit source review also confirmed that an `asyncio.timeout` context cannot interrupt
synchronous parsing and identified unbounded nesting/shape work and escaped unpaired surrogates.
This change limits synchronous input and structure but does not claim a measured wall-clock bound;
functional qualification must measure the worst case against the source budget.

## Affected contracts and paths

- `src/erp_mcp_private_writer/postgres_evidence_trust.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md`
- `core/LESSONS_LOG.md`

## Decisions and limits

- Use one stable invalid-payload error for duplicate keys, non-finite constants, malformed JSON,
  oversized payloads and invalid typed snapshots. Do not expose database or parser internals.
- Reject floating JSON numbers because the trust snapshot contract contains only integer numeric
  fields; do not rely on `parse_constant` to reject exponent overflow.
- Keep `asyncio.timeout` claims separate from synchronous parser resource limits. The 8 MiB, depth,
  node and integer bounds are source constraints; measured duration/allocation remains `NOT_RUN`.
- This is local source hardening only. It does not prove the candidate SQL output, trusted DB
  identity, installed grants, validator provenance, snapshot freshness, or registration authority.
- `S13-PRODUCTION-TRUST-SNAPSHOT-01` remains `NOT_RUN` until functional/E2E qualification on a
  confirmed disposable database after all coding closes.

## Verification

The actual `code-reviewer` (GPT-6 Luna, low effort) returned no finding on the initial parser
change, then found one direct M-01 gap because the node ceiling was only checked after
`json.loads`. The current scanner now counts values before parsing; the agent's focused follow-up
found no scanner bypass or off-by-one issue. No tests ran. GPT-PM's correlated pre-commit review
returned `MODIFY` with one MAJOR (synchronous parsing not preempted by asyncio timeout), three
MINOR findings (Unicode scalar validation, exponent-overflow precision, and omitted attached
lesson-log evidence). The current source adds byte/depth/node preflight and typed limits; measured
worst-case time/memory remains open because synchronous parsing is not preemptible. The lesson
file is included in this record's affected paths and was attached in the focused re-review.
GPT-PM's focused re-review returned `ACCEPT` on that attached intermediate snapshot and closed
its M-01/N-01/N-02/N-03 findings at source level; it did not claim tests or runtime proof. A
subsequent local code-review pass identified that the 1,000,000-value ceiling still ran only
after `json.loads`. The current raw-text lexer now counts values before parsing as well as
rechecking the decoded tree. GPT-PM direct re-review request
`6504b5ea-6793-4a56-9670-219510f0183f` accepted the exact latest scanner snapshot, with no
confirmed direct regression. The correlated source reviews were request
`ac057b38-ed70-4d78-bb09-90dc43f10c89` (`MODIFY`),
`ae75b0a3-649d-46f1-8ead-5c41e265b951` (`ACCEPT` for the findings remediation), and the final
scanner review above (`ACCEPT`). These verdicts do not replace tests or runtime proof.
`NOT_RUN`: tests, checks, build, CI, SQL parsing, migration,
direct database access, COM and registration. No staging, commit or push was performed. The
pre-edit source file SHA-256 recorded before the first edit was
`0D228F571D33E249AB8D83B55CADE56CBEAD0BBEBBCD3F6B8777EDC25A45C0B6`.

## WP5 canonical evidence envelope single-pass decoder

`ProductionEvidenceVerifier._parse` previously called each of seven envelope `from_json` parsers
in sequence, potentially decoding and canonicalizing one 2 MiB input repeatedly. It now performs
one strict UTF-8 JSON decode with recursive duplicate-key rejection, selects exactly one envelope
class by exact field-set equality, verifies byte-for-byte canonical serialization, and constructs
only that record. All malformed cases map to `EVIDENCE_ENVELOPE_INVALID` before any trust-source
lookup. This is source-only hardening; the change has not been tested, measured, or runtime-qualified.
`WP5-VERIFIER-DECODE-01` owns the per-schema and zero-source-call acceptance scenarios.

Source-review checkpoint, 2026-10-24: before the resource-bound follow-up, the
`production_evidence_verifier.py` SHA-256 was
`1CF2BB16576B08D609C3240C0061CD4F3692B0691FB38A2B3DC5CA2ACFE0567A`. The actual `code-reviewer`
(GPT-6 Luna, low effort) found no source-level issue in that one-pass decoder: strict UTF-8,
recursive duplicate-key rejection, constant rejection, exact one-of-seven schema selection,
canonical-byte comparison and stable `EVIDENCE_ENVELOPE_INVALID` mapping were confirmed. A later
source-only delta adds a pre-parse depth limit of 32 and a 1,000,000-value limit under the existing
2 MiB input ceiling. That scanner delta is unreviewed and untested; its current source hash is
`DD1BEA6D2982EC8ECCF5700FDB427BD579A364705E9CA8D6025C59BDCAE3800E`. CPU/allocation qualification
remains open. The prior review did not run tests, checks, benchmark, runtime or trust-source calls;
no composition or registration is authorized by it.

Focused source re-review of the scanner SHA above by the actual `code-reviewer` (GPT-6 Luna, low
effort) reported no finding: the 2 MiB input check is in `_parse`, the scanner bounds nesting to 32
containers and counts root/nested values up to 1,000,000, and `json.loads` remains the full grammar
validator. This is static review only. Tests, runtime calls and parser resource measurements remain
`NOT_RUN`; the source review does not establish latency or peak-memory compliance.
