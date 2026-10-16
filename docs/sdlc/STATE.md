# SDLC state
Project: ERP_MCP_R2   Sprint: Phase 2 / G1 closure   Phase: 7 Verify   HEAD: `7dadd2268490d86e8b6e8c55d63d7a4b0f9370bf` (repository HEAD when this checkpoint refresh began; this checkpoint commit is documentation-only)   G1 code review HEAD: `17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`   Updated: 2026-10-16

## Artifacts

| Phase | Artifact path | Author agent/model | Head | Status |
|---|---|---|---|---|
| 6 Build | `tests/phase2/test_g1_crash.py`, `tests/phase2/test_g1_restore.py`, `docs/phase2/CHANGE_RECORD_057.md` | `e2e-runner` / GPT-6 Luna; implementation details in linked change record | Recorded there; subsequently revised through `17b6de7` | Source scenarios authored and committed |
| 7 Verify | `docs/phase2/G1_OPERATOR_BACKLOG.md`, `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`, `docs/phase2/CHANGE_RECORD_059.md`, `docs/phase2/CHANGE_RECORD_060.md`, `docs/phase2/CHANGE_RECORD_062.md`, `docs/phase2/CHANGE_RECORD_064.md`, `docs/phase2/CHANGE_RECORD_065.md`, `docs/phase2/CHANGE_RECORD_066.md`, `docs/phase2/CHANGE_RECORD_070.md` | `functional-test-reviewer` / GPT-6 Luna (G1 static review, map review, and proposed-minimum review); GPT-PM static review, request `8bcc1579-b818-4aef-98a6-eab6a2d470fb` | Exact code review: `17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`; repository baseline at checkpoint refresh: `7dadd2268490d86e8b6e8c55d63d7a4b0f9370bf` | Code review approved, 0 BLOCKER / 0 MAJOR; runtime `NOT_RUN` because project rules prohibit pytest. Proposed minimal test set recorded; three concurrency scope cases remain for gate review; phase exit incomplete. |
| 8 Gate | `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`, `governance/GATE_MANIFEST.json`, `docs/phase2/CHANGE_RECORD_067.md`, `docs/phase2/CHANGE_RECORD_068.md` | GPT-PM static review recorded; no G1 gate-specific approval | Repository documentation baseline: `7dadd2268490d86e8b6e8c55d63d7a4b0f9370bf`; G1 source finding reviewed at `17b6de7` | G0 is PASSED only for its approved scope; G1 remains NOT_PASSED; final G1 gate approval and push are not authorized |

## Open questions / backlog items (owner)

- G1 exact-head focused runtime evidence — blocked by the project-wide prohibition on pytest; no human owner is named. Revisit only when an allowed runner or rule change exists; see `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`.
- G1 workload/capacity disposition and effective-role/approver evidence — database/security lane; no human owner is named; see `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`.
- R-01 production writer-boundary inventory — project design lane; no human owner is named.
- R-03 non-secret deployed-key inventory and custody evidence — key-governance lane; no human owner is named.
- G2/G3/G4/G5/G6-pre/G6/G7/G8 and formal S13 dependencies — see the gate matrix and ordered queue in `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`; no unrecorded human owners are inferred.

## Decisions (link to ADRs)

- Rosetta stays disabled per workspace instructions.
- PM Bridge static review closes G1-M01 at source level only; G1 remains `NOT_PASSED`, runtime is `NOT_RUN`, Release 2 remains `NO-GO`, and production authorization remains `NONE`.
- No test, check, build, migration, database or Docker operation is permitted in this pass under the active project instructions.
