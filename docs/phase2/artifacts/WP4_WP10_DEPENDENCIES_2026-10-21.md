# Autonomous work packages WP4–WP10: dependency status — 2026-10-21

Repository revision observed before this turn's local edits: `4dfceeddb071a63e7d8f815e7c276555de6d2375`.
This note records which downstream packages can proceed from the evidence and controls
available in this turn. It does not claim qualification, a source write, a test run, or
production readiness.

| Package | Current state | Evidence | Remaining acceptance and dependency | Recommended next action / owner |
|---|---|---|---|---|
| WP4 — finish S12 and S13 | BLOCKED | `docs/phase2/OPERATOR_BACKLOG.md` current reconciliation says S12 local engineering is approved but formal qualification remains open. `docs/phase2/S13_MUTATION_AND_WRITER_PATH_INVENTORY_2026-10-17.md` says the repository inventory is complete but the operational writer inventory is `UNKNOWN / NOT_RUN`; the bundled write port raises `NotWired`, while lifecycle preflight always returns `NOT_READY`. WP0 found the local listeners live but the Ivan SSH host key failed strict verification. | S12 still needs the formal disposable PostgreSQL/COM-clone qualification. S13 needs a real writer-side stable-call-ID idempotency boundary, stale-epoch rejection, authoritative outcome lookup, quiescence barrier, complete mutation/grant and lock-order map, and recovery-to-READY evidence. The plan selects the Ivan stack as the intended service boundary; its remote state was not verified in WP0. No migration was applied and no mutation run occurred. | Obtain and verify Ivan's trusted SSH host key through an authenticated out-of-band source, then have the selected Ivan-stack service owner demonstrate the writer boundary in an authorized clone lane. Database, security, reliability and test agents own their later reviews and tests. |
| WP5 — key/signature registry and real signers | BLOCKED | WP1 recorded the operator's authorization to implement the registry; `core/DECISION_LOG.md` records that real signer and witness identities are still required before a first real write. WP0 could not establish the licensed-host connection because strict SSH host-key verification failed. | Implement mandatory trusted-boundary receipt enforcement after the WP4 writer boundary is identified. Generate D9 signer and separate D10b witness on the licensed host, protect private keys with DPAPI, and register public keys only after verified host/account identity. No key was generated or printed. | Restore trusted remote access without weakening host verification; Ivan-stack/host owner performs licensed-host provisioning, Codex implements reviewed local registry code after the writer contract is known. |
| WP6 — S14 1C write port | BLOCKED | The source inventory and CT14 evidence are limited to a measured COM purchase-receipt path on clone `818HA_p2diff`; the repo inventory says there is no operational writer/composition root. | Depends on WP4 writer fencing and WP5 signer identities. Clone tests must prove create/post/unpost, marker, stale-write refusal, expected movement effects, and no payment side effect. The autonomous prompt's process rules prohibit mutation runs in this turn; no 1C write was attempted. | Complete WP4 and WP5, then implement against the frozen CT14 contract and run the mapped tests only through the authorized functional/E2E agents. |
| WP7 — S15 verification and reconciliation | BLOCKED | Depends on WP6 in the execution plan; no operational write port or new clone effects were produced. | Clone evidence must establish effects-based MATCH/FINDING reconciliation and unknown-outcome recovery without trusting a missing marker. | Resume after WP6 clone evidence exists; Codex implements and test agents author/run acceptance scenarios. |
| WP8 — S16 approval channel and S17 workbench | BLOCKED | Depends on WP7 in the execution plan. No new approval-channel or UI code was implemented in this turn. | Per-story approval and workbench behavior, with UI and accessibility review if the UI is changed. | Resume after WP7; Codex implements, functional/E2E agents test, and product UX/accessibility reviewers cover any UI change. |
| WP9 — optional Drive/G4 | DEFERRED; delete probe is BLOCKED | The WP1 decision entry records prior create/read/list/change-feed probe claims but no delete-probe evidence. The manifest remains G4 `NOT_PASSED` with Drive intake disabled. The task authorization explicitly excludes deleting data; a delete probe is therefore not authorized by this turn. | If the operator later authorizes deletion of only newly created probe files, the Drive route and scope must still be verified; OAuth token lifetime and scope concerns remain open. No Drive call or deletion was performed. | Keep Drive outside the critical path. Operator owns any future deletion authorization; the Drive connector owner must provide a verified route and scoped token. |
| WP10 — S18 reliability, security, canary, release | BLOCKED | Depends on WP6–WP8. WP0 local liveness is not canary evidence; remote SSH and connected ERP MCP routes were unavailable for the requested source observation. Staging is forbidden and remains unused. | Requires clone reliability/capacity/recovery evidence, independent security review, operator UAT where a UI exists, the delegated read-only canary on the authorized source, exact-head test/reviewer evidence, GPT-PM approval, and operator-signed `PRODUCTION_GO` before any production authorization. None of these release conditions were created by this turn. | Resume after WP6–WP8 and verified source access. Codex coordinates; test and specialist agents provide evidence; operator retains UAT/production-signoff decisions. |

## WP3 registry generation dependency

The default `scripts/build_document_registry.mjs` mode inventories Markdown paths from
attached worktrees, including untracked files. This worktree contains protected
untracked user files, so default generation is not safe. Chosen policy: preserve the
default inventory contract and add an explicit `--exclude-local-only` mode for a
tracked-refs-only snapshot. It must not enumerate local untracked Markdown in that mode,
and the generated scope must state that local-only paths were excluded. This preserves
historical Git-ref documents without publishing protected worktree paths. Implementation
and generation have now completed. `node scripts/build_document_registry.mjs
--exclude-local-only` exited 0 at `33f76b7f4f49ae773b3f86876940c9c6234a636d`, scanned
46 Git refs, and wrote a snapshot with 422 tracked paths; local-only paths were
**NOT_ENUMERATED**. Its
scope explicitly says local-only files in attached worktrees were not inventoried; this
mode does not enumerate those files. Cyrillic in generated titles, paths, and ref names
is encoded with `\uXXXX` escapes. Functional acceptance for the new mode remains
**NOT_RUN** under the current no-tests policy. The registry is a development navigation
aid, not release evidence.

## Overall evidence state

Local listener liveness is runtime-observed. Source business reads, remote Ivan
checks, database qualification, licensed-host key provisioning, clone write tests,
Drive deletion, S15–S19 acceptance and production authorization are **NOT_RUN**.
The precise external access blocker for Ivan is the missing trusted ED25519 host key
for `ivan.tail08f9f9.ts.net`; strict verification was retained. The optional Drive
delete action is additionally blocked by the operator-only deletion boundary.
