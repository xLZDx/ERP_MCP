# Change Record 314 — bound COM current-user identity before encoding

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP private-writer Windows COM lane.
- Acceptance: `S13-COM-USER-BINDING-01`.
- State: source-only hardening; functional qualification remains `NOT_RUN`.

## Finding and change

The COM startup guard validated the returned `CurrentUser().Name` with `isprintable()` and then
encoded it for constant-time comparison against the configured identity. Although the expected
identity was already capped at 256 characters, the returned value had no matching bound, so an
unexpectedly large COM value could consume unbounded scan and encoding work before refusal. The
guard now rejects names longer than 256 characters before scanning or UTF-8 encoding, while
preserving exact comparison and fail-closed handling.

## Affected paths

- `src/erp_mcp_private_writer/windows_com_lane.py` — bound returned COM identity before comparison.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — qualify the
  overlong returned-name refusal in the existing COM identity case.

## Evidence and verification

- This turn's source inspection found the returned identity was encoded without a length check;
  constructor configuration already imposed a 256-character expected-name ceiling.
- Current source SHA-256: `CAC4E5591B5A9DC51AC74E6806D2D95517A2A0748295D15A36465599B056609C`.
- No COM action, test, check, build, database operation, migration, staging, commit, or push ran.
- No external or COM-provided identity is claimed as verified by this source change.

## Remaining acceptance

Functional-test reviewer must prove exact 256-character matching behavior, overlong refusal before
fingerprint callback or any writer operation, mismatched names, missing/empty/non-printable values,
and privacy-safe errors on the disposable clone. Current user identity and effective 1C rights on
Ivan remain separate runtime evidence.
