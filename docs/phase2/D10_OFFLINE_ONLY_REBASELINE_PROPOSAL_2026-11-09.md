# D10 offline-only rebaseline proposal — V2-S12-05

**Status:** Draft for GPT-PM adjudication. This proposal is not an approval, task GO, formal S12 entry, implementation, or change to the project manifest.

**Owner:** Codex (proposal and evidence package); GPT-PM (rebaseline adjudication); operator (real D10 identity evidence if/when an authenticated-human scenario is required).

## Decision requested

Approve or revise a narrow rebaseline that permits **V2-S12-05 offline synthetic engineering acceptance only** to use explicitly synthetic `lane=TEST` identities for model-level authorization fixtures while keeping the real D10 `person_id` requirement in force for authenticated-human approval, real effects, runtime qualification, and formal S12 entry.

This request does not seek a task-specific implementation GO. If the rebaseline is approved, V2-S12-05 still needs its own explicit GPT-PM GO before implementation and test work begins. Formal S12 entry remains HOLD until every applicable prerequisite is satisfied and separately adjudicated.

## Exact task boundary

The S12 story register assigns V2-S12-05: **kill switch (three modes), WRITE/POST evaluator, and READ regression**. The offline acceptance would cover only the frozen contract's model-level decision behavior:

1. Preserve the ordered modes `STOP_ADMIT < STOP_EFFECTS < REVOKE` and the contract's precedence matrix.
2. Exercise the WRITE/POST evaluator against each mode, including refusal of new admission/effect paths where required by the matrix.
3. Exercise permitted read-only observations while the switch is active, including the contract's specifically allowed recovery/verification observations.
4. Verify that a switch read failure fails closed as `STOP_EFFECTS`, and that re-enable requires the specified recovery sweep.
5. Keep all fixtures synthetic, explicitly marked `lane=TEST`, and unable to create a live dispatch permit or invoke 1C/COM.

This is acceptance of a local model/test boundary only. It does not demonstrate runtime enforcement, cross-process or durable switch behavior, authenticated real-human approval, or physical 1C effects.

## Synthetic-versus-real evidence matrix

| Evidence or identity | Proposed V2-S12-05 offline treatment | Real S12/runtime treatment |
| --- | --- | --- |
| D10 operator identity | Reuse clearly synthetic `person:test-operator-001`, explicitly `lane=TEST`, solely in model fixtures | Real operator `person_id` remains unresolved and required for authenticated-human authority |
| D10b recovery witness | Keep synthetic `person:test-witness-002` distinct from D10 and every requester | Real witness identity and separation remain NOT_VERIFIED |
| Requester identity | Use a third distinct synthetic TEST person | Real requester-to-person mapping remains NOT_VERIFIED |
| Kill-switch state and evaluator result | Local in-memory/model evidence; record exact source revision and focused test results if separately authorized | Durable/independent switch read, authenticated principal checks, runtime revalidation, and physical call behavior remain NOT_RUN |
| 1C/COM, PostgreSQL, migrations, deployment | Excluded; NOT_RUN | No authority is requested or implied |
| Formal S12 entry and G8/release state | No state change; HOLD remains | Separate evidence and formal decision required |

Synthetic identities must never be represented as the operator, as an authenticated human, or as satisfaction of real D10. No synthetic test may issue an operational permit or grant real approval/signing privileges.

## Acceptance evidence after a future GO

If GPT-PM approves the rebaseline and then separately grants V2-S12-05 GO, the task packet should bind:

- exact source revision and changed-file hashes;
- task-to-contract traceability for S12-M06 and the V2-S12-05 story boundary;
- distinct synthetic requester, operator, and recovery-witness fixtures, all labelled TEST;
- focused functional-test evidence for the three modes, WRITE/POST refusal/eligibility decisions, READ regression, fail-closed unreadable-switch behavior, and re-enable recovery ordering;
- internal review findings and a separate exact-diff GPT-PM review before any ordinary task push.

The tests must not contact a live 1C source, mutate a database, execute a migration, or claim production/runtime acceptance.

## Open conditions and requested ruling

1. Is the proposed V2-S12-05 offline-only D10 rebaseline acceptable without changing the formal real-D10 requirement for authenticated-human or runtime scenarios?
2. Does the proposed boundary preserve the existing separation-of-duties rule among operator, requester, and recovery witness?
3. If approved, confirm that this decision only permits a later, separate task-specific GO request and does not itself authorize V2-S12-05 implementation, formal S12 entry, PR #54 merge, runtime, 1C, database, migration, deployment, production, G8, or release activity.

## Source basis

- `docs/phase2/S11_TEST_DESIGN_PACKAGE_2026-10-12.md`, S12 story row: V2-S12-05 task boundary.
- `docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md`, S12-M06 kill-switch semantics and the three-mode precedence matrix; interpreted subject to `S12_CONTRACT_FREEZE_V2_2026-10-16.md`.
- `docs/phase2/S11_SCOPE_DECISIONS_AND_GATE_MANIFEST_2026-10-12.md`, D10 operator person-id requirement.
- `docs/phase2/S12_TEST_LANE_BINDINGS_2026-10-12.md`, explicit TEST-lane placeholders and D10/D10b separation.
- GPT-PM request `7d8fce77-33c0-4be8-91c8-77cc4ab2c4ea`: conditional approval for offline preparation and requirement for an explicit narrow rebaseline before synthetic D10 can support offline acceptance.
- GitHub PR #54 (`https://github.com/xLZDx/ERP_MCP/pull/54`): bounded V2-S12-01–04 scope; open/unmerged in the retrieved snapshot; no merge authorization implied here.

