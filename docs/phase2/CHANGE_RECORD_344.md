# Change Record 344 — preservation commit of the S13 private-writer candidate source and tests

## Ownership and scope

- Date: 2026-10-27.
- Accountable owner: operator; executor: Claude Code session, taking over from the previous Codex session
  after the operator said to finish the work.
- This is a preservation commit. The 76 code files below were written by earlier sessions over several
  weeks and existed only as modified or untracked files in the working tree; none had been committed. The
  per-change reasoning, ownership and evidence for them are in the already written change records and
  detail files that the companion documentation commit adds (change records 300-339 and
  `docs/commits/`). This record does not re-derive that reasoning and does not claim authorship of it.

## What is included

- `db/phase2/027_private_writer_admission_schema.sql`: the candidate private-writer admission schema
  (about 830 KB, not installed anywhere, never applied to a database).
- `src/erp_mcp_private_writer/`: the private writer service modules (authority mutex, signer and DPAPI
  adapters, evidence registrar/resolver/trust, barrier acknowledgement protocol, Postgres store and
  outcome provider, ingress, authorization, T16 recovery, COM STA lane and COM manifest).
- `src/business_ai_gateway/phase2/change/` and `change_ledger/` edits that the writer depends on, plus the
  new `uuid_contract.py`.
- `tests/phase2/` tests for those modules and the matching edits to existing tests.
- `testlane/onec_extension/` and `scripts/` edits.
- `core/DECISION_LOG.md` and `core/LESSONS_LOG.md` with the entries the earlier sessions appended.

## Why a preservation commit

Weeks of work existed only in the working tree. A checkout, clean or tool mishap would have destroyed it,
and the project rule is to commit coherent changes as development proceeds. Splitting it retroactively
into the original fine-grained commits is not possible without re-reviewing each file, so it is committed
as one checkpoint, followed by a documentation-only commit.

## Verification state

- Done before commit: every one of the 71 Python files byte-compiles; a scan of all 389 dirty text files
  found no private keys, bearer tokens, connection strings with passwords, cloud keys or API keys, and no
  real amounts beyond lines already present in `HEAD`.
- NOT_RUN: pytest, ruff over the new modules (about 240 findings are known in
  `src/erp_mcp_private_writer/`), SQL parse or install of migration 027, any COM call, any review. The
  writer is unqualified: effective database privileges are `NOT_MEASURABLE` because the schema and roles are
  not installed, and the COM boundary is unmeasured because no licensed 1C session is available.
- `MCP-RSV-Data.zip` stays untracked and untouched.
