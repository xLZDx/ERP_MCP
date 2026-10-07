# Autonomous assignment for Functional Tester

You are the Functional Tester for ERP_MCP. Work on a dedicated branch from the approved
integration candidate. Read `AGENTS.md`, `SKILLS.md`, `docs/DOCUMENT_INDEX.md`,
`docs/QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md`, `testbed/README.md`, and
`testbed/scenarios/accounting_scenarios.json` before authoring tests.

## Assignment

Create executable black-box functional tests for all twelve `SC01..SC12` scenarios in
the scenario guide. Exercise the gateway as an MCP client against the deterministic
Fake1C seed. Do not couple tests to internal Python functions when a public MCP tool
can exercise the behavior. Use separate identities/fixtures for data-plane user and
Admin where the behavior is in scope. Keep Admin functional cases in their own module
and report if an OIDC test provider is required.

For each scenario:

1. Define the user-visible input/question and expected output or explicit unsupported
   response.
2. Run it against `testbed/fake1c/fixtures/seed.json` and verify the invariant declared
   in `testbed/scenarios/accounting_scenarios.json`.
3. Add at least one relevant negative case (missing grant, wrong company, unsupported
   capability, unposted document, or other scenario-specific denial).
4. Verify no 1C write method is sent, result rows remain bounded, and sensitive data is
   absent from logs/audit.
5. Link the result to a stable case ID and state whether it is implemented, unsupported,
   or externally blocked.

Required scenarios: receivables overdue threshold, partial settlement, unapplied
overpayment, unposted document, return/inventory, mixed VAT, backdated period,
duplicate counterparty without merge, cash/bank separation, opening/debit/credit/closing
turnovers, inventory receipt/expense signs, and cash receipt/expense signs.

## Required deliverables

- Executable tests and only the smallest necessary synthetic fixture changes.
- A test report with one row per `SC01..SC12`: command, result, evidence, public tool
  exercised, and gaps. Never label fixture arithmetic as live 1C reconciliation.
- Separate User and Admin coverage summaries; never conflate the two identities.
- Any scenario that cannot run through an existing public tool must be marked
  `NOT IMPLEMENTED` or `EXTERNAL-GATE` with the missing interface/environment stated.
- Include setup, run, teardown and rerun commands for a clean workstation.
- Run relevant tests, full suite, lint and repository-required checks; report exact
  commit SHA and output summary. Do not change migration history or frozen security
  boundaries to make a test pass.

## Constraints

- Fake1C is synthetic L1 only. Never create evidence labeled native 1C.
- Never guess 1C EntitySet, virtual table or method names. Unsupported capability must
  fail closed with evidence.
- Never add mutation/write operations to the 1C adapter.
- Never use production/customer secrets or data.
- Preserve pinned upstream implementations and licenses; inspect upstream tests before
  proposing protocol behavior.
- Do not commit tokens, local env files, reports containing raw accounting rows, or
  generated private snapshots.
- If a scenario demonstrates a security boundary violation, stop test execution, keep
  a minimal sanitized reproducer, and report it as a blocker before continuing.

Finish with a concise handoff: tests added, scenario coverage, commands/results, gaps,
branch/commit, and whether human User/Admin browser acceptance is still required.
