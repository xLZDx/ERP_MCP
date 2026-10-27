# Autonomous ERP_MCP WP0–WP3 local work — 2026-10-21

## Scope and revision

- Repository: `D:\Repo\ERP_MCP`
- Base revision observed: `4dfceeddb071a63e7d8f815e7c276555de6d2375`
- Working branch: `codex/erp-mcp-autonomous-2026-10-21`
- Packages covered: WP0 read-only liveness, WP1 operator decisions/G3 note mechanics,
  WP2 inherited test-name triage, WP3 English-policy cleanup.
- Protected untracked user files (`MCP-RSV-Data.zip` and the two autonomous prompt/plan
  Markdown files) were not modified or staged.

## What changed and why

- WP0: added `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md` with observed
  local listener/HTTP/Docker state, connected-tool errors, and the strict SSH host-key
  blocker. Updated `scripts/real1c/autostart/start_lane.ps1` to derive the active repo
  root, use its `.venv`, accept the actual Apache port, select the matching config,
  pass the upstream URL to new lane proxies, and report the configured port. The
  start script was not run because it controls Docker, IdP, tunnel and gateway
  processes.
- WP1: recorded decisions A1–A7 in `core/DECISION_LOG.md`. G3 uses a structured,
  unsigned `WAIVED_BY_OPERATOR` note while the gate remains `NOT_PASSED`, external
  evidence remains open, and production authorization remains none. The validator
  limits the note to G3, validates the exact fields/date, rejects evidence/signature
  fields, and does not consume the note in gate-closure logic. The decision quote is
  rendered in English.
- WP2: added `docs/phase2/artifacts/WP2_INHERITED_TEST_CLASSIFICATION_2026-10-21.md`
  and updated `docs/BACKLOG_INHERITED_2026-10-21.md`. The two named result files were
  filtered to emit only test identifiers. The artifact reconciles 13 errors and 14
  failures and labels source-based classes as preliminary; it does not infer exact
  causes from old aggregate counts. No tests were executed.
- WP3: added a tracked-text Cyrillic policy scanner and exact line-hash allowlist;
  removed Cyrillic escaping from the registry generator; translated genuine prose in
  the Phase 2 bundle index and one backlog quote; corrected the inventory's tracked
  Russian report count from seven to eight. The registry generator was not run
  because it inventories untracked Markdown paths and historical refs; the output
  policy conflict is documented in
  `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md`.
- Downstream work: recorded WP4–WP10 dependencies and exact blockers in the same
  artifact. No licensed-host keys, clone mutations, Drive deletion, staging, or
  production actions were performed.

## Contracts and paths affected

- G3 waiver note is not accountant attestation and cannot satisfy a gate, predecessor,
  or production authorization.
- Local liveness is not business-source health; a 401/200 health response is not an
  accounting read or qualification result.
- English-policy allowlist exceptions are tied to exact line hashes where practical;
  semantic test inputs, localized artifacts, and literal 1C identifiers remain
  unchanged.
- The S13 operational writer boundary, key identity/custody, COM clone writes, S15–S19
  acceptance and production authorization remain outside completed evidence.

## Decisions and lessons

- Strict SSH host-key checking remains enabled; the Ivan host requires a trusted key
  before remote commands.
- Do not weaken the all-ref document registry or publish protected local user-file
  paths to force registry regeneration.
- Search incident, scanner NUL-byte shortcoming, G3 note handling, and WP2 identifier
  count reconciliation are recorded in `core/LESSONS_LOG.md`.

## Verification state

- Runtime-observed: WP0 local port listeners, anonymous denial/health responses, and
  Docker container status, recorded in the WP0 artifact.
- Manually reviewed: current source diff and task artifacts. One actual `code-reviewer`
  agent pass (GPT-6 Luna, medium effort) reviewed WP0–WP3 changes. Its MINOR finding
  that NUL-bearing text-suffix files were silently skipped was fixed by making the
  scanner report a read error.
- NOT_RUN: test suites, English-policy scan, registry generation, spec-bundle
  generation, startup script, remote Ivan commands, business read, S12/S13 database
  qualification, licensed-host key generation, clone writes, Drive probe and
  downstream package acceptance. Required functional/E2E tests remain owned by the
  named test agents after all reachable coding is complete.

## Commit guidance

This file must be linked from the local commit message that contains the changes. Any
new code change after the later test/review phase requires fresh exact-head review and
verification. This record is not a merge, push, release, gate PASS, or production
approval.
