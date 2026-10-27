# Change record: correct GPT-PM project routing for ERP_MCP

Date: 2026-10-22  
Scope: explain and repair the project binding used for exact-patch GPT-PM reviews.

## Observed mismatch

The operator-provided screenshot shows a GPT review header naming `PROJECT: ERP` and
`https://github.com/xLZDx/ERP.git` at `D:\Repo\ERP`, while the attached S13 lock-protocol patch
and the requested work belong to `ERP_MCP`. The existing S13 review record also says that request
`c9b13d91-4b2c-4d4c-9d4a-98eac51fe352` was routed to PM Bridge project `erp` and is not an
ERP_MCP approval (`docs/commits/2026-10-22-s13-lock-protocol-spec.md`).

## Cause and correction

The request was explicitly sent with the wrong project selection and wrong repository identity in
its message header. The available evidence does not establish why those incorrect caller values
were chosen; it does rule out treating this as automatic repository detection or as evidence about
GitHub itself.

The inaccessible old PM Bridge conversation was left intact. The registered `erp_mcp` binding was
rotated to a new ChatGPT conversation so future reviews have a usable canonical destination. New
reviews must use both `project="erp_mcp"` and a message header naming
`https://github.com/xLZDx/ERP_MCP.git` at `D:\Repo\ERP_MCP`; verify `pm_bridge_job_status.projectId`
before relying on a response.

## Current review state at record preparation

- PM Bridge project binding: `erp_mcp`.
- New conversation ID: `6ada565a-df80-83eb-81b3-2fc6a7d89521`; the previous conversation was left
  unchanged.
- Exact-patch WP3 source-boundary review request: `8f3a2f45-6d44-4d92-9e0f-1a57c3bfde22`.
- Durable job ID: `0e4c2760-2516-414e-89bd-c15a7b43edba`; observed `projectId=erp_mcp` and
  `sendPhase=not-started` while queued. This is not yet evidence that the review was sent or
  approved. The wrong-route unsent request `596b81f9-0a41-4ad6-98da-6fc28ebb2617` was cancelled
  before execution after its status confirmed `sendPhase=not-started`.

## Lesson

Before any GPT-PM review, check the canonical project ID, exact repository URL/path in the message,
and the durable job's project binding. An attachment from the right repository does not correct a
wrong PM Bridge project or a wrong header.

## Verification state

- Read-only PM Bridge status and durable job records were inspected.
- The project rotation changed only the `erp_mcp` conversation binding; it did not change or remove
  the separate `erp` project or its chat.
- No tests, checks, builds, CI, migrations, source-data reads, push, or PR were performed for this
  routing correction.
- The exact patch review remains pending; this record is not a GPT-PM approval for any code or
  other documentation patch.
