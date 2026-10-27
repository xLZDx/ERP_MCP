# Change Record 313 — bound attempt-context UTF-8 sizing allocations

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP evidence-ingest attempt-context decoder.
- Acceptance: `S13-ATTEMPT-CONTEXT-JSON-BOUND-01`.
- State: source-only correction; tests and database/runtime qualification remain `NOT_RUN`.

## Finding and change

`PostgresEvidenceAttemptSource._decode()` checked its 128 KiB UTF-8 limit by encoding the entire
driver-returned string into a second bytes object. An oversized result could therefore allocate
memory proportional to the complete payload before the decoder rejected it. The new preflight first
rejects strings whose character count alone exceeds the byte ceiling, then encodes bounded 16 KiB
character chunks with strict UTF-8 handling and stops as soon as the cumulative size exceeds the
ceiling. Only accepted bounded text reaches `json.loads()`.

## Affected paths

- `src/erp_mcp_private_writer/postgres_attempt_source.py` — bounded UTF-8 sizing before JSON parse.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — exact byte,
  multibyte and malformed-input acceptance.

## Evidence and verification

- This turn's source inspection found the previous `len(payload.encode("utf-8"))` call before
  `json.loads()`; the 128 KiB limit was defined at module scope.
- Current source SHA-256: `D0C7183B2A9AB267936C368C18E863597F35464C52EB56464E511C881E667575`.
- No tests, checks, build, SQL parsing, DB query, migration, runtime or network action was run.
- The implementation preserves strict UTF-8 rejection and guarantees at most one 16 KiB chunk
  encoding allocation at a time; JSON parsing remains bounded by the 128 KiB accepted payload.

## Remaining acceptance

Functional-test reviewer must verify exact and adjacent byte boundaries for ASCII and multibyte
input, oversized ASCII early rejection, malformed surrogate refusal, stable error translation and
that parsing is not entered for rejected input. Runtime database identity and candidate SQL grants
remain separate, unqualified gates.
