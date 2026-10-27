# Change Record 315 — cap Authorization input before ASCII decoding

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP private-writer authentication boundary.
- Acceptance: `S13-PRIVATE-AUTH-HEADER-BOUND-01`.
- State: source-only hardening; tests and runtime qualification remain `NOT_RUN`.

## Finding and change

The bearer matcher already limited each JWT segment to 8,192 characters, but bytes-valued
Authorization headers were decoded to a new string before those segment limits were applied. A
large header could therefore allocate an unnecessarily large copy before failing the matcher. The
authenticator now derives the largest supported complete header length from the scheme prefix,
three segment limits and separators, rejects oversized bytes before ASCII decoding, and rejects
oversized strings before regex matching. Authentication error behavior and the verifier boundary
remain unchanged.

## Affected paths

- `src/erp_mcp_private_writer/private_auth.py` — bound complete Authorization value before decode.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — exact header-size
  acceptance and zero-verifier refusal.

## Evidence and verification

- This turn's source inspection found `bytes.decode("ascii")` preceded the existing bounded JWT
  regex; the regex limits were 8,192 characters per each of three segments.
- Current source SHA-256: `B5B2A4C51061AB4FC695FE5A39A1BB4431EBE74B29FBD9BF1B2C4BA1C8FE0B38`.
- No tests, checks, build, runtime, database, COM, migration, staging, commit or push ran.

## Remaining acceptance

Functional-test reviewer must exercise the exact maximum, maximum plus one for both bytes and str,
very large bytes refusal before decoding, invalid ASCII and verifier-call counts. This source change
does not establish any client grant, deployed header limit, token validity, or writer authority.
