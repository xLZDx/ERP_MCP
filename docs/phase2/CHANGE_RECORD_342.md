# Change Record 342 — record the base mapping behind the 521.1 two-base mismatch

## Ownership and scope

- Date: 2026-10-27.
- Accountable owner: operator; executor: Claude Code session.
- Covers only the follow-up section of `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-27.md`,
  this record and the matching `core/DECISION_LOG.md` and `core/LESSONS_LOG.md` entries. It does not claim
  pre-existing staged, modified or untracked work.

## Change

Documentation only. Recorded that the local `erp_mcp_ref` OData publication reads `818HA_test_ready` while
Ivan's reads `818HA_p2diff`, the write clone, so the two-base comparison is not a copy-consistency check.
The ten common 521.1 rows are identical and the metadata and profile fingerprints are equal; Ivan has one
extra credit-only counterparty. Evidence came from read-only inspection of the publication descriptors
(credentials stripped) and of both gateways' `accounting_balance_by_analytics` rows (keys hashed, no amount
or name recorded).

## Contracts and paths affected

None in product or test-lane code. No configuration, service, database or 1C change on either host.

## Verification state

Read-only inspection only; pytest NOT_RUN. The write-clone explanation of the extra row is an inference.
