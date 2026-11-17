# Normative design and whole-program planning audit — 2026-11-17

The technical-writer slice confirmed index/control precedence but was blocked
by a command-classification hook before completing the remaining reads. The
coordinator then directly read TDD, DATA_MODEL, MASTER_PLAN, GOVERNANCE and
SECURITY; architecture/ADR/integration/DoD were covered in the architecture audit.
No verification suite or runtime operation was performed.

## Authority and actual scope

The TDD is v1.2 dated 2026-10-23; MASTER_PLAN/GOVERNANCE/DATA_MODEL are dated
2026-10-06. They define a production read-only gateway and a separate explicitly
authorized disposable private writer (TDD FR-K/ADR-0009/D19). The operator's
2026-11-17 full program evidence rebaseline replaces stale execution summaries;
it does not by itself enable production writes, bypass ACLs or deploy candidates.

Old normative references to mandatory automatic CI/lint/full suites conflict
with the newer operator development rules. Those execution-policy sentences
are superseded by the newer explicit rules: no automatic CI, named test-role
qualification at the permitted phase, and exact-head review before publishing.
Do not reopen automatic CI or make a documentation-only rule an operator blocker.
Observed GitHub workflow state was already disabled_manually; attempting to
disable it again returned HTTP403 because it was inactive, and read-back still
showed disabled_manually. No workflow run was started. Main's workflow source
still has push/PR triggers, so I-02 must preserve the committed manual-only change.

## R1 foundation is existing work, not a new project

R1 release merge 94f4cee is an ancestor of current origin/main (Git exit0).
reports/IMPLEMENTATION_STATUS.md and DOD_STATUS.md record substantial historical
source/test closure, including a dated 1934-pass/343-skip local snapshot, while
explicitly keeping DoD PARTIAL and production NO_GO. These are historical
results, not fresh execution. Preserve the integrated foundation and qualified
subsets; do not reset them because the Phase2 task registry lacks R1 task IDs.

The 104 original task positions describe the canonical Phase2/FIN registry;
three explicit rebaseline tasks are separate audit work. P0-P10 are master-plan
milestones and S0-S19/FIN are task-delivery views. Do not add both as duplicate
task counts or label either denominator as an exhaustive inventory of every R1
requirement. S11 is a sprint-level accepted milestone without invented stories.

## Crosswalk for the rebuilt program

| Master milestone | Current program/task view | Existing implementation / remaining scope |
|---|---|---|
| P0 normative baseline | S0, S11, REBASELINE | Existing documents/ADRs and S11 exit; resolve current evidence/plan conflicts |
| P1 identity/control | S1/S2, gateway foundation | Existing OAuth/registry/audit/limits; candidate observer and current effective grants need qualified integration |
| P2 capability routing | S1/S3, capability-service candidate | Existing discovery/router; fix G-01 and define G-02 composition |
| P3 OData data plane | S1/S3, pinned sidecar | Existing bounded read protocol; AT-01 circuit classification fix |
| P4 semantic accounting/DAD | S4/S6/S8 | Existing profile/semantic and normalized logic; retain native-profile qualification limits |
| P5 assurance/evidence | S5/S6/S7/S14/S15 and later S17 | Existing capture, COM executor, synthetic oracle and comparison; preserve accepted subsets and qualify real ports |
| P5-C disposable writer | S12/S13/S14 | Implemented admission/anchor/lifecycle candidates; integrate operational COM port, fence, authority and exact candidate qualification |
| P6 read-only RSV/COM route | Gateway bridge + assurance records | Existing separate read bridge; not permission to expose private writer through public MCP |
| P7 legacy8.2 | Explicitly deferred | No current target; not a blocker for modern runtime |
| P8 operational hardening | S9/S13/S16 and later S18 | Existing source/partial tests; durability, actual topology, recovery and current-candidate evidence remain separate |
| P9 release acceptance | S10 and later S19 | Handoff/source exists; bounded handoff is not release GO |
| P10 ERP/Ferma production expansion | FOLLOW_ON | Deferred production expansion; Ferma assurance work already exists under P5 and must not be reset |

## Data-model interpretation

DATA_MODEL separates control state, capability/schema, semantic mapping, audit,
external evidence and business rules. Secret values/raw private documents stay
outside Git. Native profile validation needs real attributable evidence; fake
comparison passes do not establish it. The current gateway intentionally blocks
unverified native/company mappings. Persist these as implementation versus
qualification distinctions, not missing-code claims. Migration016 adds a new
observation/acceptance authority boundary and migration017 strengthens native
profile evidence; both are candidate untracked work and require integration
disposition rather than silent deployment.

## Remaining review limits

All-ref document versions are enumerated; not every obsolete historical paragraph
was semantically rereviewed. Current authoritative documents, dated acceptance
records, major implementation boundaries and contradictory summaries were
prioritized. Historical reports remain recoverable through Git/external backups;
do not republish thousands of stale copies into the canonical report navigation.
Current program order is preservation/reconciliation, candidate integration,
affected qualification/review, approved merge, then proven-safe cleanup.
