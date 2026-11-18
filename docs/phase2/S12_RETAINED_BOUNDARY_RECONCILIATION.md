# S12 retained contract reconciliation

Status: bounded TEST-lane design candidate. Continuation base 5f9a824.
S12 test-only entry is approved under GPT-PM request 9f9d197a-c24c-42a6-abac-a40025e9801d. It covers synthetic engineering. G8, real identity/runtime qualification, deployment and production remain separate.

PR #54 is open to main at 2629aa2a20f6e40641a5ece7de42a1587a2748a1. Main and the PR diverge. Prior snapshots accept seven bounded S12 stories in that line. The current main retains most code, but these historical receipts do not establish equivalent behavior for every fixture and boundary.

## First ordered task: S12-01 model and digest

The normative freeze admits only CREATE_DRAFT, POST and UNPOST into the governed v2.0 write scope. Current proposal.py retains exact TEST-lane enforcement and the writer payload parser rejects UPDATE_DRAFT. However, the shared historical proposal parser on main deliberately accepts UPDATE_DRAFT, including for simulation and legacy fixtures. The governed proposal facade in erp_mcp_s16 uses that same parser, and its default target qualification vocabulary also includes UPDATE_DRAFT. The historical PR's hard rejection in the shared parser would disrupt previous prototype model callers if copied indiscriminately.

Proposed minimum compatibility boundary: keep the historical typed vocabulary and digest behavior for existing in-memory model/simulation callers. Add an explicit frozen v2.0 proposal admission path for the three in-scope kinds, and use it consistently at the governed proposal facade and proposal port. Reject an out-of-contract kind before issuing a nonce, advancing state or storing a preview. The existing writer payload and predispatch refusal remain independent. Source data or user inputs must not select a compatibility mode. Do not change old proposal bytes, hashes, prototype behavior, live tool registration or the admitted set of physical writer operations.

Verification: test frozen rejection before provider/nonce/storage interaction and verify known in-scope kinds under TEST. Preserve legacy prototype parsing and exact canonical/payload/approval digests. Use existing named S12 parser/digest and S16 in-memory service files. No connection to actual 1C or real test identity is required.

The recovery witness/approver gate and retained crash-window deltas are separate subsequent S12 reconciliation items. Inspect them in sprint order; do not infer either acceptance from the proposal checks. PR #54 remains the historical delivery branch until an exact main-based integration and review disposition is established. No merge, production, migration or gate-manifest update is authorized by this design candidate.
