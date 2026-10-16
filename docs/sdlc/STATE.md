# SDLC state
Project: ERP_MCP_R2   Sprint: Phase 2 / G1 closure   Phase: 7 Verify   Latest committed HEAD: `4b9f3b08b4e75359b549bda75d6f6ec3307f248e`   G1 code review HEAD: `17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`   Updated: 2026-10-16

## Artifacts

| Phase | Artifact path | Author agent/model | Head | Status |
|---|---|---|---|---|
| 6 Build | `tests/phase2/test_g1_crash.py`, `tests/phase2/test_g1_restore.py`, `docs/phase2/CHANGE_RECORD_057.md` | `e2e-runner` / GPT-6 Luna; implementation details in linked change record | Recorded there; subsequently revised through `17b6de7` | Source scenarios authored and committed |
| 7 Verify | `docs/phase2/G1_OPERATOR_BACKLOG.md`, `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`, `docs/phase2/CHANGE_RECORD_059.md`, `docs/phase2/CHANGE_RECORD_060.md`, `docs/phase2/CHANGE_RECORD_062.md`, `docs/phase2/CHANGE_RECORD_064.md`, `docs/phase2/CHANGE_RECORD_065.md`, `docs/phase2/CHANGE_RECORD_070.md`, `docs/phase2/CHANGE_RECORD_071.md`, `docs/phase2/CHANGE_RECORD_072.md`, `docs/phase2/CHANGE_RECORD_073.md`, `docs/phase2/CHANGE_RECORD_074.md`, `docs/phase2/CHANGE_RECORD_075.md`, `docs/phase2/CHANGE_RECORD_076.md` | `functional-test-reviewer` / GPT-6 Luna low (B04–B08 mapping and restore test correction); `e2e-runner` / GPT-6 Luna low (explicit-COMMIT and separate-cluster evidence); `database-reviewer` / GPT-6 Luna medium (role/grant, transaction and restore evidence boundaries); `silent-failure-hunter` / GPT-6 Luna low (test assertion semantics); GPT-PM static code review, request `8bcc1579-b818-4aef-98a6-eab6a2d470fb` | Code review HEAD: `17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`; latest committed repository baseline: `4b9f3b08b4e75359b549bda75d6f6ec3307f248e` | Initial focused suite on the committed baseline: 46 passed, 1 failed because the restore scenario called a reader-inaccessible internal helper. The test now checks RLS visibility before and after grant deletion, but the corrected diff has no completed rerun. Current instructions prohibit the required runner, so the corrected scenario is NOT_RUN. PostgreSQL 16 disposable container is ready on loopback; host `psql` is optional. Local push remains NOT_READY pending green exact-head functional/E2E evidence, relevant specialist review and fresh GPT approval. |
| 8 Gate | `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`, `governance/GATE_MANIFEST.json`, `docs/phase2/CHANGE_RECORD_067.md`, `docs/phase2/CHANGE_RECORD_068.md`, `docs/phase2/CHANGE_RECORD_071.md`, `docs/phase2/CHANGE_RECORD_072.md` | GPT-PM static review recorded; no G1 gate-specific approval | Repository documentation baseline: `7dadd2268490d86e8b6e8c55d63d7a4b0f9370bf`; G1 source finding reviewed at `17b6de7` | G0 is PASSED for its approved scope; formal G1 remains NOT_PASSED and production authorization is NONE. These release states are separate from local push acceptance. |

## Open questions / backlog items (owner)

- G1 local focused test results — initial run was 46 passed / 1 failed at committed HEAD `4b9f3b0`; the failure was an invalid direct call to internal `living.assert_scope`. The test-only correction now checks RLS visibility before/after revocation and retains the fresh-context `living.set_scope` denial. Its rerun is NOT_RUN because current `D:\Repo\AGENTS.md` instructions prohibit pytest. Local push remains NOT_READY. See `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`.
- G1 workload/capacity disposition and deployed effective-role/approver evidence — formal release gate work in the database/security and identity lanes; no human owner is named. These are not extra prerequisites for a local engineering push.
- R-01 production writer-boundary inventory — project design lane; no human owner is named.
- R-03 non-secret deployed-key inventory and custody evidence — key-governance lane; no human owner is named.
- G2/G3/G4/G5/G6-pre/G6/G7/G8 and formal S13 dependencies — see the gate matrix and ordered queue in `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`; no unrecorded human owners are inferred.

## Decisions (link to ADRs)

- Rosetta stays disabled per workspace instructions.
- PM Bridge static review closes G1-M01 at source level only. Formal G1 remains `NOT_PASSED`, Release 2 remains `NO-GO`, and production authorization remains `NONE`; these release states are not the local push gate.
- Local push requires green focused functional/E2E results, relevant specialist findings and fresh GPT approval for the exact final diff. The initial run had one invalid test-path failure; the test correction remains unverified because the current workspace instructions prohibit its rerun. The dedicated PostgreSQL test container is loopback-only and disposable. No deployed database is involved; host `psql` is optional.
