# Change Record 341 — Phase 2 test lane: named refusal codes and correct purchase call shape

## Ownership and scope

- Date: 2026-10-27.
- Accountable owner: operator; executor: Claude Code session.
- Covers only `testlane/phase2_mcp/gateway_client.py`, `testlane/phase2_mcp/reconcile.py`,
  `testlane/phase2_mcp/config.py`, `tests/testlane/test_gateway_detail_code.py`,
  `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-27.md` and the matching
  `core/LESSONS_LOG.md` entry. It does not claim any pre-existing staged, modified or untracked work.

## Why

The two-base reconciliation reported every gateway refusal as the generic `GATEWAY_TOOL_ERROR`, which
hid that the gateway had refused for a capability reason (`SEMANTIC_PROFILE_UNVALIDATED`). The lane also
sent period arguments to `purchase_documents`, which the gateway tool does not accept.

## Change

- `GatewayError(code, detail_code=None)`; `_safe_detail_code` reads the refusal code from structured
  content or from the JSON text of the first content item and accepts only `[A-Z][A-Z0-9_]{2,63}`;
  free text, validation messages and malformed JSON yield no detail.
- Reports add `detail_code` beside the unchanged `reason_code` through one helper `_error_entry`, so
  existing consumers of `reason_code` are unaffected.
- `purchase_documents` is requested with `source_id` and `company_id` only.
- `config.py`: parenthesised an implicit string concatenation (ruff `ISC004`); the pinned SSH command is
  byte-for-byte the same string.

## Contracts and paths affected

- Phase 2 test-lane MCP output gains an optional `detail_code` field. No gateway, product, database, 1C,
  credential or service change. No secrets are read or printed.

## Verification state

- Live: a fresh in-process `Reconciler` over both real gateways returned `detail_code:
  SEMANTIC_PROFILE_UNVALIDATED` for six-column, purchases and the negative control; the 521.1 section
  result is unchanged (`PARTIAL_MISMATCH`, one difference).
- Static: ruff over `testlane/phase2_mcp` passes.
- NOT_RUN: pytest. The new unit test `tests/testlane/test_gateway_detail_code.py` and the existing
  testlane suite are left to the test agents. The running 21200 server was not restarted.
