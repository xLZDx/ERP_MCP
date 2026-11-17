# S12 formal-entry evidence crosswalk — 2026-11-09

## Purpose and authority boundary

This is the Codex follow-up crosswalk requested by GPT-PM after the correlated HOLD decision `3c99a12f-7209-49a4-bec8-987c117a4a72` / reply `5b000a4f-6a61-55a8-af49-84055f87d65c`. It supersedes the earlier summary packet only for the criterion-by-criterion applicability mapping below. It is evidence correlation, not a formal S12-entry approval, task GO, code change, or operational authorization.

The prior GPT-PM ruling is preserved: **HOLD — formal S12 entry**. It adjudicated S11 exit and sequencing SATISFIED; OB-01 SATISFIED for the restricted disposable-clone scope; OB-15 SATISFIED with its named deployment deferrals; D10 candidate `igord` SATISFIED as operator input; and trusted D10 principal mapping, entitlement/separation, revision applicability, and Review A/B entry classification still open or NOT_VERIFIED. No V2-S12-06 GO is granted.

## Exact source identities

| Source | Exact identity | Use in this crosswalk |
| --- | --- | --- |
| Historical S12 interface contract revision 6 | Git object `97e82cc4f89f1cd9b8293f64106669cdfb8210b0:docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md`; SHA-256 `0aa4a766d920df8d2bfd195d894ff872793dcf8e002258338f641a5fa5131f38` | Identity derivation, role separation, and inherited control semantics. The v2 freeze says revision-6 controls remain where not in conflict and that it supersedes operation scope only (freeze §6). |
| Historical S12 test-lane entry record | `docs/phase2/S12_TEST_LANE_BINDINGS_2026-10-12.md`, SHA-256 `a65de88f1a3d26b5279ff27672b04b0b438f33d0ad1f3c17ae6fbd671bc754c8`, §§“Operator decisions” and “S12 test-lane entry record” | Records S12-G01–G05 and later dated status corrections. The old 2026-10-13 OB-01/OB-15 OPEN statements remain historical. |
| Operator backlog decisions | `docs/phase2/OPERATOR_BACKLOG.md`, SHA-256 `d6f6b8a66ec3a6a58b471067bbdf4618edf2b90970b402442febbbcc8a4423eb`, lines 320–329 | 2026-10-14 operator decisions and 2026-10-16 status: OB-01 narrow scope; OB-15 accepted with named deployment deferrals. |
| S12 v2.0 design baseline | Git object `061e921a595a9df7fc648dc9db5e19842a65ff8d:docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md`; SHA-256 `d9565ddfe115c405725cb372c08152419579bd4171a3627c1bc72b27e7a5e09f` | Current approved bounded design baseline. Its status is PRE-ENTRY; it does not itself grant formal entry or operational authority. |
| Latest GPT-PM adjudication | Request `3c99a12f-7209-49a4-bec8-987c117a4a72`; correlated reply `5b000a4f-6a61-55a8-af49-84055f87d65c` | Governing current criterion dispositions and the request for this exact crosswalk. |

## Formal entry criterion crosswalk

| Criterion | Exact source and v2 mapping | Current disposition | Remaining evidence / owner / next action |
| --- | --- | --- | --- |
| S12-G01 / OB-01 restricted prototype scope | Test Lane Bindings §17 and entry record §25; Operator Backlog lines 320–322 and 329. The v2 freeze §1 bounds the design to one receipt shape and `CREATE_DRAFT`, `POST`, `UNPOST`; it does not widen the operator's clone/prototype restriction. | **SATISFIED for the same restricted disposable-clone scope.** GPT-PM says no new operator decision is required. | Codex preserves the exact restriction. No R1 rebaseline, staging, production, real-money, deletion, or real-1C authority is inferred. |
| S12-G02 / OB-15 inventory and license decision | Test Lane Bindings §17 is superseded by the later operator decision in Operator Backlog lines 320, 323, 329. The v2 freeze does not turn the named deferrals into universal license clearance. | **SATISFIED WITH NAMED DEFERRALS.** R2 lock file/SBOM and host-binary license, pin, and checksum facts remain deferred to deployment qualification; `LICENSE_BOUNDARY_APPROVED` remains NO. | Codex preserves the deferrals and does not claim broader clearance. No operator action is currently required for the same bounded prototype scope. |
| S12-G03 / historical status reconciliation | Test Lane Bindings §17 explicitly supersedes its earlier 2026-10-13 OPEN wording; Operator Backlog lines 320–329 records the later operator decisions and G0 scope. | **SATISFIED for decision history.** | Codex retains dated records; do not rewrite historical OPEN text as if it were never recorded. |
| S12-G04 / TEST fixture identity boundary | Test Lane Bindings §§17, 28, 37–45 says `person:test-operator-001` is a synthetic `lane=TEST` fixture and cannot satisfy a real-identity gate. Revision 6 §§1–2 derives people from authenticated OAuth principals and the trusted registry. | **SATISFIED for offline TEST only.** The operator-attested `igord` is a candidate association; it does not convert the fixture into a real authenticated principal. | Codex must obtain or identify the trusted OAuth-subject-to-person registry record; do not promote the TEST fixture or infer an authenticated subject. |
| D10 trusted principal mapping | Revision 6 §1 defines `person_id` as registry-owned; §2 derives identity from the authenticated OAuth subject through that registry and disallows caller-supplied identity. Revision 6 §2 also requires the operator credential/session boundary. Freeze v2 §6 retains revision-6 identity controls where not in conflict; §2.0.1 is a separate service/key identity registry, not proof of a human IdP mapping. | **BLOCKING — NOT_VERIFIED.** Operator input `person_id=igord` is recorded, but no authenticated OAuth subject or trusted human-registry mapping is evidenced. | Codex owns locating the exact trusted IdP/registry record. The current connected ERP_MCP_Ivan tool inventory has no principal/person-registry lookup tool; local `src/erp_mcp_s16/registries.py` identifies its registry as in-memory fakes with “no production identity source is wired.” If the real record requires provider access or a human authentication step, Codex must name that exact access action and the operator owns it; GPT-PM adjudicates the resulting evidence. |
| Operator entitlement, epoch, and real-person separation | Revision 6 §§1–2, requester/approver/operator role matrix and T4/T16 rules; Freeze v2 §§2.0.1–2.3 and §6 preserve distinct signer/role/epoch evidence boundaries. | **BLOCKING — NOT_VERIFIED.** No authenticated principal entitlement at the applicable authorization epoch or real requester/operator independence proof is attached. | Codex correlates the trusted entitlement and identity evidence when the source is identified; operator supplies only any genuinely required access/attestation; GPT-PM adjudicates. D10b remains a TEST fixture and no real recovery witness is inferred. |
| S12-G05 / no physical-write authority from entry | Test Lane Bindings §29; Freeze v2 §§1, 6 and title/status explicitly say pre-entry design baseline and no live/production connection. | **SATISFIED as a restriction.** Entry would not authorize a 1C write, gate pass, S13 start, or release promotion. | Preserve the boundary. Runtime/physical qualification remains a separate future prerequisite; no write is authorized here. |
| Approved v2 baseline vs historical revision-6 entry criteria | Freeze v2 §6 says revision-6 identity, role separation, nonce, scope, epoch, generation, kill-switch, and state-transition rules remain in force except where conflicting; v2 supersedes the prior operation scope. Freeze §§5–6 distinguish later local-engineering acceptance from open qualification/gates. | **Partially mapped.** Identity and authority rules are inherited; operation scope is superseded by v2 §1. | Codex has mapped the known inherited controls above. GPT-PM must confirm whether any other revision-6 entry clause is pulled into formal entry; no criterion is inferred from the hash alone. |
| Review A/B finding applicability to formal entry | Freeze v2 §§5–6 and §214 state these are bounded local-engineering acceptance and open evidence/gate items; findings are tied to exact reviewed byte identities. Freeze §226–244 lists their statuses. | **NOT formal-entry blockers on current evidence unless a governing entry clause explicitly requires them.** Their acceptance/qualification remains PARTIAL/OPEN; this crosswalk does not close them. | Codex maps each to its clause and later acceptance domain below. GPT-PM confirms whether any exact clause makes a listed residual a formal-entry prerequisite. |
| Formal S12 entry | Latest GPT-PM reply `5b000a4f-6a61-55a8-af49-84055f87d65c`. | **HOLD / NOT_GRANTED.** | GPT-PM issues a separate entry verdict after reviewing this crosswalk and trusted D10 evidence status. |
| V2-S12-06 | Latest GPT-PM reply and the ordered S12 task list in the program report. | **Task-specific GO NOT_GRANTED; not started.** | Only after formal S12 entry is approved, Codex requests a separate task-specific GO. |

## Review A/B residual classification

The finding statuses below remain exactly as recorded in the approved bounded baseline. “Later qualification” is a sequencing classification, not acceptance or closure. No finding is promoted to a formal-entry blocker solely because it is PARTIAL or OPEN.

| Review finding | Recorded status | Entry applicability / remaining acceptance |
| --- | --- | --- |
| Review A B-01 receipt/pre-image/read-back binding | PARTIAL | Later implementation/evidence qualification; exact predicates and trusted provenance remain open. |
| Review A M-01 pre-version freshness | PARTIAL | Later physical-write qualification; atomic conditional write or qualified serialization remains NOT_RUN. |
| Review A M-02 expectation/oracle provenance | PARTIAL | Later design/qualification evidence; exact oracle/config and signed binding remain unqualified. |
| Review A M-03 disposable PostgreSQL prerequisites | PARTIAL | Later database qualification; migrations, grants/RLS and disposable DB evidence remain NOT_RUN/NOT_VERIFIED. |
| Review A M-04 COM fixture/topology identity | PARTIAL | Later host/runtime qualification; authenticated clone/host/process/session topology remains NOT_VERIFIED. |
| Review A M-05 scenario traceability/accountable ownership | PARTIAL | Later executable-inventory/qualification prerequisite; not an independent formal-entry clause in the cited S12-G01–G05 record. |
| Review B B-01 barrier closes admission before timeout | PARTIAL | Later implementation/physical qualification; exact cross-component interface and DB/physical behavior remain open. |
| Review B B-02 Python/PostgreSQL epoch compatibility | PARTIAL | Later API/SQL implementation qualification; exact correspondence is not demonstrated. |
| Review B B-03 restartable barrier coordination | PARTIAL | Later recovery qualification; restart/resume remains NOT_RUN. |
| Review B B-04 successful-call terminal/base-slot release | PARTIAL | Later implementation/recovery qualification; no slot-release runtime proof. |
| Review B M-01 final COM-entry authority interface | PARTIAL | Later private-writer/physical qualification; candidate design is not runtime-proven. |
| Review B M-02 indeterminate barrier finalization | PARTIAL | Later implementation/runtime qualification; exact ambiguity classification is not proven in execution. |
| Review B M-03 signed no-entry recovery | PARTIAL | Later physical-write qualification; guard and durable transition remain unimplemented/unqualified. |
| Review B M-04 barrier acknowledgement signing/ownership | PARTIAL | Later identity/key custody/runtime qualification; no trusted ingest or runtime evidence. |
| Review B M-05 source-wide fence and lock order | OPEN | Later source-wide implementation review; complete path map is not accepted or runtime-proven. |
| Review B M-06 original JSON bytes versus `jsonb` | PARTIAL | Later implementation qualification; original-byte verification remains unimplemented/unqualified. |
| Review B M-07 stable error provenance | OPEN | Later source/code review; Appendix C source is missing from the reviewed candidate and mapping remains open. |

## Identity evidence audit and exact dependency

Evidence currently present: the operator's chat attestation naming candidate `igord`; the S12 TEST fixture records; the historical interface-contract rules; and in-memory implementation/test fakes. Evidence not present: (1) authenticated OAuth subject for the real operator, (2) trusted registry record mapping that subject to `igord`, (3) epoch-bound operator entitlement, and (4) evidence that the real requester and operator are distinct principals/people where the entry rule requires it. The connected ERP_MCP_Ivan tool inventory exposes business-data, source/health, company and OData operations but no human identity registry lookup. The repository S16 registry implementation is explicitly an in-memory fake and has no production identity source wired; it is not runtime proof.

**Exact dependency:** access to a trusted identity-provider/principal-registry record for the authenticated OAuth subject and its current entitlement/epoch. **Owner:** Codex owns source discovery and evidence correlation; the operator owns any provider access or authentication step that genuinely requires their authority; GPT-PM owns the formal-entry adjudication. **Next action:** Codex identifies whether the authorized IdP/registry can expose this record. If unavailable in the connected/project sources, record the exact missing endpoint/record and request the specific operator-controlled access step; do not substitute the TEST fixture or a guessed identity.

## Ordered next steps

1. Codex: locate and correlate the authenticated OAuth subject, trusted mapping to `igord`, applicable entitlement/epoch, and required requester/operator separation evidence.
2. If source access requires an operator action, Codex names the exact access/attestation step; the operator supplies only that missing authorization/evidence.
3. GPT-PM: review this crosswalk and issue criterion-level formal S12-entry APPROVE/HOLD.
4. Only after an APPROVE, Codex requests a separate task-specific GO for V2-S12-06.

## Historical records deliberately retained

The superseded 2026-10-13 OPEN wording in `S12_TEST_LANE_BINDINGS_2026-10-12.md` and earlier intake/status paragraphs in `OPERATOR_BACKLOG.md` remain as dated provenance. The later operator decisions and GPT-PM dispositions above govern current status; historical source text was not rewritten.
