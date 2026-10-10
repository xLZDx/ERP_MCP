# Sprint S10 plan - offline closure (engineering handoff); production canary NOT_RUN

Date: 2026-10-10. Base head `414d232` (S9 APPROVED at `6ee27f1`). Rules v4: docs first, one push after GPT-PM APPROVE on the exact head, no mutation runs, no CI.

Scope: S10 in `PLAN_PHASE2_RU.md` is "Source-specific prod canary under a separate permission; exact-head R2 release bundle" (gates G6/G7; stories R2-US-042 and R2-US-048). The canary needs separate operator permission and real data and is NOT_RUN. S10 therefore delivers documentation only:

- `S10_RELEASE_HANDOFF.md`: terminal state ENGINEERING_HANDOFF, G0-G7 table, exact-head bundle recipe, operator checklist, NOT_RUN list, accepted backlog.
- Row updates in `PLAN_PHASE2_RU.md` and `TASK_LEDGER.md`, and a regenerated document registry.

Out of scope: any code, any production or real-data action, any gate closure. Status ceiling stays `IMPLEMENTED_UNVERIFIED`; Release 2 stays NO-GO; R2-US-042 and R2-US-048 stay NOT_STARTED (no exact-head acceptance proof exists).

Exit: the handoff document is reviewed against its source documents; the canary starts only after the operator grants permission with recipe, identity, window and budget.
