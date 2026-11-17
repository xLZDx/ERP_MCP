# S12 entry-prerequisite correlation packet — 2026-11-09

## Purpose and decision boundary

This packet is the next ordered Codex deliverable requested by GPT-PM. It correlates the current S12 entry prerequisites to exact evidence and separates operator-attested facts from trusted identity evidence. It does not itself approve S12 entry or authorize runtime, database, migration, live 1C, deployment, production, writes, or V2-S12-06.

## Current decision

GPT-PM reply to request `1c8f754d-6057-45ac-b102-632e7a216c13` (correlated reply `31de86e4-a0b9-5696-8af1-da1c93eebca2`) is **HOLD — formal S12 entry**. GPT-PM disposition for D10 is **PARTIALLY SATISFIED — registry identity NOT_VERIFIED**. The operator attested `person:test-operator-001` exists with `person_id=igord`; record this as an operator-declared candidate only.

## Ordered prerequisite matrix

| Prerequisite | Evidence and status | Owner | Next action |
| --- | --- | --- | --- |
| S11 documentation/planning exit | SATISFIED. `docs/phase2/S11_EXIT_DECISION_2026-11-09.md`; GPT-PM request `4b573c76-8de5-4a8c-b929-7ad9aa6da35c`. Main manifest blob `3187c5fc3cf5a97ce6a38d40af306767b8815dd0` records S11 `DONE`, package SHA-256 `8d6b4a7fb5094a88f34b2358e329b1912d4d30ced863615f4aff7a6598c3bb4c`. PR #57 is merged as `7c1f69cf51b16d3849772fdb1e32015b17cb1aa7`. | Codex | No reopening; keep the S11 status at sprint level and do not invent a child-task denominator. |
| S10/S11 sequencing | SATISFIED per GPT-PM decision `e41b6d73-cd4d-44f9-a600-5a9e67a0ecbc` and S11 receipt. | Codex | No further action. |
| D10 candidate identity | Operator statement recorded: `person:test-operator-001` → candidate `igord`. This satisfies the “concrete operator-supplied candidate” component only. `S12_TEST_LANE_BINDINGS_2026-10-12.md` classifies `person:test-operator-001` as a synthetic `lane=TEST` fixture (local SHA-256 `a65de88f1a3d26b5279ff27672b04b0b438f33d0ad1f3c17ae6fbd671bc754c8`). GPT-PM states the candidate must not be promoted to a real authenticated principal on this evidence. | Codex | Correlate exact trusted evidence needed; do not infer real identity from the test fixture. |
| Trusted OAuth subject → registry person mapping | NOT_VERIFIED. Contract §1–2 says `person_id` is registry-owned and an authenticated OAuth subject maps through the trusted registry, never through caller arguments (`S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md`, local SHA-256 `4628b76759c01e1cf3fd964f9457f104c6870cd5181e7151d275d68da061937c`). No registry/OAuth lookup result is attached to the correlated PM decision. | Codex | Identify the exact trusted registry/IdP record and authorization epoch evidence; do not fabricate or request a guessed ID. |
| Operator entitlement and separation of duties | NOT_VERIFIED by GPT-PM. The operator statement alone does not authenticate a principal, prove entitlement at the applicable epoch, or establish requester/operator separation for real approvals. | Codex | Bind applicable principal and entitlement evidence to D10; preserve this as a formal entry dependency until evidenced. |
| OB-01 scope | Preserve the 2026-10-14 operator decision: isolated disposable-clone prototype, no R1 rebaseline. Historical OPEN wording is not a reason to reopen the operator decision. Current binding record §17 says formal entry discharge was not yet correlated. | Codex; GPT-PM adjudicates applicability | Correlate the exact operator decision to the applicable S12 entry clause; GPT-PM decides whether the clause is satisfied. |
| OB-15 inventory/license deferral | Preserve `ACCEPTED_WITH_NAMED_DEFERRAL` from the 2026-10-14 decision. Inventory/license items deferred to deployment qualification remain deferred; no broad license clearance is implied. Current binding record §17 says formal entry discharge was not yet correlated. | Codex; GPT-PM adjudicates applicability | Correlate the named deferral to the S12 entry clause; GPT-PM decides whether that deferral satisfies entry. |
| Approved S12 contract baseline | Exact design-document baseline SHA-256 `d9565ddfe115c405725cb372c08152419579bd4171a3627c1bc72b27e7a5e09f` was approved in bounded design scope. GPT-PM says applicability of historical revision-6 entry criteria to this baseline is NOT_YET_ADJUDICATED. | Codex; GPT-PM adjudicates | Bind the approved exact revision to the historical entry criteria; request a ruling on applicability. |
| Review A/B residuals | Existing PARTIAL/OPEN findings retain their stated qualification. They are not automatically formal-entry blockers unless the governing entry contract makes their discharge a prerequisite. | Codex; GPT-PM adjudicates | Map each finding to an entry criterion and mark applicable/not applicable with evidence. |
| Formal S12 entry | HOLD / NOT_GRANTED in GPT-PM reply `31de86e4-a0b9-5696-8af1-da1c93eebca2`. | GPT-PM | Issue a separate formal-entry verdict after this correlation packet is reviewed. |
| V2-S12-06 | Task-specific GO NOT_GRANTED; work has not started. Entry approval alone would not transfer V2-S12-05 approval. | Codex, after GPT-PM | Only after formal S12 entry, request a separate task-specific GO for V2-S12-06; do not code it before then. |

## Explicit non-claims

No live/runtime/1C/COM, PostgreSQL, migrations, deployment, production, write, physical-effect, or G8/Release 2 authority is granted or inferred. Such evidence remains NOT_RUN/NOT_VERIFIED or NOT_AUTHORIZED.

## Ordered next steps

1. Codex: attach the exact trusted identity/entitlement evidence if available in the authorized project sources; otherwise name the missing record and authorized source without guessing.
2. Codex: bind OB-01/OB-15 decisions and each Review A/B residual to the exact formal-entry clauses of the approved contract revision.
3. Codex: submit this exact-revision packet to GPT-PM for the separate formal S12-entry decision.
4. GPT-PM: return APPROVE/HOLD with criterion-level dispositions.
5. Only after entry approval, Codex requests a separate V2-S12-06 task-specific GO.


## Follow-up adjudication and identified IdP path — 2026-11-09

The criterion-level follow-up supersedes the earlier “not yet adjudicated” statements above while preserving their chronology. GPT-PM request `71ff3f3f-7c50-496a-9fb1-d181f00f9a3c`, correlated reply `68a05b11-12e4-59e1-976c-6a7c1027f917`, returns **HOLD — formal S12 entry**. S11 exit/sequencing, the revision-6-to-v2 applicability mapping, and all 17 Review A/B residual classifications are satisfied for their stated bounded domains. The sole remaining entry blocker is D10: authenticated OAuth subject → trusted registry `person_id=igord`, applicable-epoch entitlement, and real-person requester/operator separation remain NOT_VERIFIED.

Read-only OIDC discovery for issuer `https://ivan.tail08f9f9.ts.net/realms/erp-mcp-test` exposes userinfo at `https://ivan.tail08f9f9.ts.net/realms/erp-mcp-test/protocol/openid-connect/userinfo`; an unauthenticated GET returned HTTP 401. No credential or token was sent. This identifies an authentication route but does not establish the authenticated subject or a trusted registry mapping. Repository search found only the S16 in-memory principal registry and no wired production identity source; the connected ERP_MCP_Ivan tool names contain no identity/OAuth/userinfo/principal/registry lookup.

**Exact next action:** the operator performs only any necessary IdP authentication/read-only registry access; Codex correlates a protected/redacted subject reference to the trusted person mapping, current entitlement/epoch, and separation evidence; GPT-PM then re-adjudicates formal S12 entry. V2-S12-06 remains NOT_STARTED without a separate task-specific GO. No PR #54 merge authority, runtime, database/migration, live 1C/write, deployment, production, G8, or release authority is granted.


## Operator clarification: current test environment has no auth/IAM — 2026-11-09

The operator clarified in chat that this is a test environment with no OAuth/authentication or IAM service and directed Codex to proceed without asking the operator to supply real IdP evidence. The operator's earlier statement `person:test-operator-001` → `person_id=igord` is retained as a TEST-lane fixture/alias only; it is not represented as a real authenticated identity.

### Bounded rebaseline proposed for GPT-PM

- Permit ordered S12 development/acceptance only in the local offline synthetic TEST lane.
- Model authentication through a test-only principal adapter and the in-memory fake registry; use explicit `lane=TEST` records, synthetic epoch-bound entitlements, and distinct synthetic requester/operator/witness identities to test authorization and separation logic.
- Keep real OAuth/IAM wiring, real-person identity, production registry/entitlement provenance, runtime qualification, PostgreSQL/migrations, live 1C/COM, deployment, and production authorization NOT_RUN/NOT_AUTHORIZED. No test fixture can satisfy those later requirements.
- Do not change the gate manifest, merge PR #54, or start V2-S12-06 from this proposal alone. If GPT-PM grants bounded formal S12 entry, request a separate task-specific GO for the next ordered task before implementation.

### Decision requested

GPT-PM: approve or revise this test-only formal-entry rebaseline in light of the operator's explicit environment clarification. State whether D10 real-human evidence is deferred to the non-test/runtime gate while the synthetic identities above suffice for bounded local engineering, and whether formal S12 entry may be granted for that bounded scope. Do not grant V2-S12-06 GO or PR #54 merge authority in this decision.


### Superseding GPT-PM ruling — 2026-11-09

GPT-PM request `9f9d197a-c24c-42a6-abac-a40025e9801d`, correlated reply `78957058-94fb-5aa4-b37e-b7cb443b1715`, returns **APPROVE — BOUNDED TEST-ONLY FORMAL S12 ENTRY**. This supersedes the earlier real-identity HOLD only for local offline synthetic `lane=TEST` engineering and acceptance. No OAuth/IAM evidence is required from the operator for this lane.

D10 real OAuth subject mapping, real entitlement/epoch, and real-person separation remain DEFERRED / NOT_VERIFIED; synthetic fixtures are not real identity evidence. `person:test-operator-001` / `person_id=igord` is allowed only as an isolated TEST alias. V2-S12-01–05 bounded acceptance is preserved. This entry ruling does **not** grant task-specific GO for V2-S12-06, PR #54 merge, manifest change, runtime, DB/migration, live 1C/COM, deployment, production, G8, or release authority.

### Current ordered task

V2-S12-06 remains the next ordered task. Codex submitted task-specific GO request `3d5c0fe9-2ce3-45e8-b709-81a1b061df51`; GPT-PM returned **GO — OFFLINE_SYNTHETIC_ONLY**, correlated reply `55a674ef-b301-502d-9473-58e32a30f2ef`. Owner: Codex for implementation and evidence; the operator has no required action. This is prospective authorization, not acceptance of the existing source/tests.
