# Change Record 385 - S15 sprint plan revised after two agent reviews

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; revised by the technical-writer agent after reviews by the functional-test-reviewer and architect agents
  (0 BLOCKER, 6 MAJOR, several MINOR). Documentation only; no code, no tests run. Changes `docs/phase2/S15_SPRINT_PLAN_2026-10-27.md` (rev 2).

## Changes

- The conflict between PLAN_V2 (contract update in scope, scenarios E2, E10, E26, E37, E1 post step) and the 2026-10-17 exclusion is stated; the v2.0 write
  catalogue governs pending an explicit operator or GPT-PM decision; those scenarios are DEFERRED with the operator as decision owner.
- Acceptance criteria that could not fail were rewritten as testable assertions with open questions split out; the non-convertibility scenario was added;
  a fixture-provisioning prerequisite, epic dependency order and a fake-interface fallback were added; oracle independence and a divergence test were specified.
- Movement-level controls are stated as oracle/multiset-only on synthetic fixtures (no real-1C movement read, NOT_RUN); new UNKNOWNs and coverage rows were added;
  assumptions now carry their real source; a compatible-migration and rollback note and the extra reviewer roles were added.

## Not established

- Who resolves the PLAN_V2 versus 2026-10-17 conflict; the ledger schema impact (depends on S13); fixture ownership. NOT_RUN: GPT-PM review of the plan.
  Committed locally; it travels with the next sprint pull request (no branch for housekeeping).
