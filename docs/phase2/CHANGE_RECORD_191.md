# Change Record 191 — sanitize outcome-bundle locator failures

## What changed

PostgresOutcomeEvidenceProvider now routes both success and conditional-conflict bundle loads through one bounded-call helper. The helper preserves syncio.CancelledError so service shutdown/cancellation semantics remain intact and maps ordinary locator exceptions to the stable OUTCOME_EVIDENCE_SOURCE_UNAVAILABLE error without forwarding dependency exception text.

## Why

The provider is exported as part of the private-writer package. Its service caller already fails closed and sanitizes provider failures, but direct callers could otherwise receive arbitrary locator exception details. The provider now owns that boundary while leaving envelope shape, signature, trust, identity and registration checks unchanged in the registrar.

## Affected paths

- src/erp_mcp_private_writer/postgres_outcome_provider.py
- PostgresOutcomeEvidenceProvider.verify_success
- PostgresOutcomeEvidenceProvider.verify_conditional_conflict

## Verification state

Source inspection only. No tests, checks, build, SQL parse, database operation, migration, COM call, service restart, stage, commit or push ran. Runtime behavior remains NOT_RUN.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue S13 source closure; after code completion, the functional-test-reviewer and e2e-runner should cover locator exception sanitization, cancellation propagation and valid success/conflict bundles, followed by the relevant Python/database reviews. Current SHA-256: $h.
