# Change record: route-bound Phase 2 gateway token providers

## Summary and reason

The live `testlane.phase2_mcp` service reported both outbound gateways as unconfigured, while
read-only comparisons through its MCP tools returned `GATEWAY_TOKEN_UNAVAILABLE`. Add default
in-process token minting for the local lane and a strict SSH token mint for Ivan's gateway, then
refresh short-lived tokens before expiry.

## Affected paths

- `testlane/phase2_mcp/config.py` — default local `auditor` mint via `LaneEnv`/`Idp`, pinned Ivan
  SSH target/account, strict host-key options, fixed remote mint command and one-hour token TTL.
- `testlane/phase2_mcp/gateway_client.py` — in-memory expiry tracking and one bounded re-mint after
  an authorization rejection; the service exposes read-only tools only.
- `docs/phase2/artifacts/PHASE2_TESTLANE_MCP_DESIGN.md` — documents credential precedence, route
  binding and refresh behavior.
- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md` — separates implemented
  source changes from the still-running process configuration and pending runtime evidence.
- `core/LESSONS_LOG.md` — records the route-specific credential and runtime-provenance lesson.
- `docs/commits/2026-10-22-phase2-token-provider.md` — this change record.

## Decisions and safety boundaries

- Local gateway calls mint the `auditor` token in process using the repository lane client; the
  token is not printed, persisted, or included in object representations.
- Remote calls use only `koros@100.88.71.74`, `BatchMode=yes`,
  `StrictHostKeyChecking=yes`, and `IdentitiesOnly=yes`. The remote script path is fixed in code
  and requests a 3600-second token; alternate SSH targets and explicitly configured script paths
  are refused. A script path without its SSH target is a configuration error unless a higher-
  precedence token provider is selected. Provider precedence is explicit token, Claude JSON server,
  configured SSH mint, then the side's default provider.
- Short-lived credentials are refreshed before their expected expiry. Legacy string providers
  have no expiry metadata; after authorization rejection they are re-read once and may yield the
  same credential. The retry is bounded to one because every exposed Phase 2 MCP tool is read-only.
- No 1C source write, migration, token display, process restart, or service replacement occurred.
  The existing port-21200 process still has its pre-change environment; source behavior is
  **IMPLEMENTED / NOT_RUNTIME_PROVEN** until the test roles exercise a separate loopback instance.

## Verification state

Independent Python review found that a failed SSH mint could retain its captured bearer in an
exception cause; the cause is now suppressed at both local and remote mint boundaries. The
review also found a provider annotation mismatch; the callable type now matches the credential
types consumed by the gateway client. GPT-PM's exact-diff review returned APPROVE with one MINOR
documentation mismatch (provider precedence, unsupported script handling, and expiry behavior);
that version updated those descriptions and explicitly rejected an alternate script path. A later
read-only Python follow-up found that a script-path setting without an SSH target could be ignored
and fall through to the default provider. The current source now rejects that unpaired setting at
configuration load unless an explicit higher-precedence token source is selected. GPT-PM
request `8a0dfeb4-9739-4e61-8c18-3626b7d83b4f` approved an earlier six-file WP0 revision for a
local commit only. Follow-up request `7fa0cc6a-9a48-46f1-a43c-0f33bbba0825` (reply
`0e10e7d2-d900-57ea-acc2-cf7807510e56`) approved the supplied current file versions for a local
commit, with two MINOR documentation corrections: this record now distinguishes the WP0 lesson
from the separate S13 lesson, and the WP0 ordered work points to a separate test instance. At
that review, the working-tree lesson file also contained an unstaged S13 entry; the staged index
contains only the WP0 entry, and the S13 lesson remains reserved for its own change. The final
exact staged diff is being resubmitted for approval before commit. No tests, checks, builds, CI,
or migrations were run.
Runtime test-lane evidence remains `NOT_RUN`
until the coding phase is complete and the functional/E2E roles execute their mapped scenarios.
No push or PR is authorized by this record.
