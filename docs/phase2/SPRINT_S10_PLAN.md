# Sprint S10 plan - offline closure (engineering handoff); production canary NOT_RUN

Date: 2026-10-10. Base head `414d232` (S9 APPROVED at `6ee27f1`). Rules v4: docs first, one push after GPT-PM APPROVE on the exact head, no mutation runs, no CI.

Scope: S10 in `PLAN_PHASE2_RU.md` is "Source-specific prod canary under a separate permission; exact-head R2 release bundle" (gates G6/G7; stories R2-US-042 and R2-US-048). The canary needs separate operator permission and real data and is NOT_RUN. S10 therefore delivers documentation only:

- `S10_RELEASE_HANDOFF.md`: terminal state ENGINEERING_HANDOFF, G0-G7 table, exact-head bundle recipe, operator checklist, NOT_RUN list, accepted backlog.
- Row updates in `PLAN_PHASE2_RU.md` and `TASK_LEDGER.md`, and a regenerated document registry.

Out of scope: any code, any production or real-data action, any gate closure. Status ceiling stays `IMPLEMENTED_UNVERIFIED`; Release 2 stays NO-GO; R2-US-042 and R2-US-048 stay NOT_STARTED (no exact-head acceptance proof exists).

Exit: the handoff document is reviewed against its source documents; the canary starts only after the operator grants permission with recipe, identity, window and budget.

## 2026-11-18 retained bounded engineering verification

The original plan below describes the October handoff. PR #53 later recorded bounded development/test capture and manifest assembly acceptance on the historical integration branch. Its merge 900a3d0 is not an ancestor of main. Current main retains the scoped capture runtime and both named runtime test files byte-for-byte at that merge. Capture-loop and runtime composition changed in subsequent integration, and the manifest implementation and tests have additional head-binding and bounded Git-read changes. Historical runtime and manifest reports are not exact-current evidence.

1. R2-US-042: verify retained development/test capture scope, denial of production binding, and cancellation/drain ownership on the current commit. Use existing named test_capture_runtime.py, test_capture_runtime_e2e.py and test_capture_loop.py. Tests use in-memory inputs. Native capture/comparison and live canary permission are outside the bounded verification.
2. R2-US-048: verify the current manifest and CLI on a disposable Git fixture only, including exact source/test/PR head binding, complete case IDs, and strict handling of skipped results and separate user/admin/production UAT. Use test_s10_release_manifest.py and test_s10_release_manifest_cli_e2e.py.
3. Record the two results separately. Retain product canary, actual signed release evidence, independent UAT and release-owner acceptance as backlog. A synthetic example manifest never grants production approval.
