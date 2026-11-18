# S12 retained contract reconciliation

Status: GPT-PM approved bounded synthetic TEST-lane implementation at 1ac5bdf (request 974f286e-724a-4e02-ac17-bacd68839510). Continuation base 5f9a824.
S12 test-only entry is approved under GPT-PM request 9f9d197a-c24c-42a6-abac-a40025e9801d. It covers synthetic engineering. G8, real identity/runtime qualification, deployment and production remain separate.

PR #54 is open to main at 2629aa2a20f6e40641a5ece7de42a1587a2748a1. Main and the PR diverge. Prior snapshots accept seven bounded S12 stories in that line. The current main retains most code, but these historical receipts do not establish equivalent behavior for every fixture and boundary.

## First ordered task: S12-01 model and digest

The normative freeze admits only CREATE_DRAFT, POST and UNPOST into the governed v2.0 write scope. Current proposal.py retains exact TEST-lane enforcement and the writer payload parser rejects UPDATE_DRAFT. However, the shared historical proposal parser on main deliberately accepts UPDATE_DRAFT, including for simulation and legacy fixtures. The governed proposal facade in erp_mcp_s16 uses that same parser, and its default target qualification vocabulary also includes UPDATE_DRAFT. The historical PR's hard rejection in the shared parser would disrupt previous prototype model callers if copied indiscriminately.

Proposed minimum compatibility boundary: keep the historical typed vocabulary and digest behavior for existing in-memory model/simulation callers. Add an explicit frozen v2.0 proposal admission path for the three in-scope kinds, and use it consistently at the governed proposal facade and proposal port. Reject an out-of-contract kind before issuing a nonce, advancing state or storing a preview. The existing writer payload and predispatch refusal remain independent. Source data or user inputs must not select a compatibility mode. Do not change old proposal bytes, hashes, prototype behavior, live tool registration or the admitted set of physical writer operations.

Verification: test frozen rejection before provider/nonce/storage interaction and verify known in-scope kinds under TEST. Preserve legacy prototype parsing and exact canonical/payload/approval digests. Use existing named S12 parser/digest and S16 in-memory service files. No connection to actual 1C or real test identity is required.

The recovery witness/approver gate and retained crash-window deltas are separate subsequent S12 reconciliation items. Inspect them in sprint order; do not infer either acceptance from the proposal checks. PR #54 remains the historical delivery branch until an exact main-based integration and review disposition is established. No merge, production, migration or gate-manifest update is authorized by this design candidate.

## Second ordered task: retained transition taxonomy

After isolated S12-01 verification, reconcile the two failed assertions in test_change_offline.py without changing the reducer. T9 holds incomplete evidence, including a returned reply without bound receipt/result or durable evidence. Require a fully bound success fixture for the negative explicit-T9 case, and preserve the incomplete-evidence hold assertion. T16 requires different operator and witness, neither the requester, and the witness cannot be the approving person. Keep the approved operator-as-co-signer case with a different witness. Restore the historical independent-witness expectation from PR #54. Re-run the named module and preserve initial failures separately. No real witness, provider, recovery execution or release approval.

## Remaining bounded tasks and PR history integration

The source for S12-03 principal/approval records, S12-04 policy, S12-05 kill switch and S12-07 CT14 qualification, and the named S12-05/S12-07 test files and CT14 record bytes, match PR #54 at 2629aa2. Preserve the historic acceptance and verify named current test inputs. S12-06 has a later main crash-window test expansion; retain that coverage and restore the two historical TEST-lane refusal tests absent from it.

Integrate the current PR #54 head in the local continuation to retain its ancestry. Three merge conflicts are isolated to transitions.py, _change_helpers.py and the crash-window test file. Direct source comparison shows only reorder/format/documentation differences in the first two. Keep their tested main forms. Keep the already reconciled prototype parser and current model fixtures despite Git's automatic historical merge of those paths. Retain the reviewed CT10 Appendix C from the merged documentation. Update the existing PR branch only when its head is still 2629aa2 and exact final approval is recorded; use a normal fast-forward push. No gate-manifest change or real execution.
