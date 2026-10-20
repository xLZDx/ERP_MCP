# Change record 168 — correct singular document-registry path counts

Date: 2026-10-17. Status: documentation-generator output correction; no product behavior or gate state changed.

## What changed and why

- Corrected the generated inventory and generator summary so a count of one uses “path” and all other counts use “paths”. The registry generator previously emitted the grammatical mismatch “1 local-only paths”.
- Regenerated the point-in-time registry from the exact refs recorded in `governance/DOCUMENT_REGISTRY.md`; the tracked/local-only counts and ref hashes are recorded there.

## Affected paths

- `scripts/build_document_registry.mjs`
- `governance/DOCUMENT_REGISTRY.md` (generated)
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_168.md`

## Evidence and limits

- Generator command: `node scripts/build_document_registry.mjs`; exit 0. It recorded four refs, local `main` at `06d1f1c08a79f9814e7746acddef1df451e54745`, 241 tracked Markdown paths and one local-only path (`docs/phase2/CHANGE_RECORD_168.md`).
- Functional verification: `functional-test-reviewer` / GPT-6 Luna / low used Node v24.13.1 and an isolated fixture. On the singular case, generator output and persisted registry both said `1 local-only path`; `node scripts/build_document_registry.mjs --check` exited 0. Adding a second path made `--check` exit 1 as stale; regenerating produced `2 local-only paths` in output and file, followed by `--check` exit 0. Adding a third path again made `--check` exit 1. The agent reported the bounded initial harness timeout separately; the valid direct sequential runs passed. Fixture path: `D:\Temp\registry-cr168-functional-final-af6d5ae70b8e4d80b420f34ed014b1c8`.
- Functional tracked-path verification: the same role/model/effort ran a separate isolated Git fixture on a generator copy from the same source HEAD. With one tracked Markdown file, stdout and persisted inventory both said `1 tracked path`; after adding a second, both said `2 tracked paths`; each generator run exited 0. Fixture path: `D:\Temp\registry-cr168-tracked-count-1bf7182f8fa64759ab9f9ebd535f9c25`.
- E2E verification: `e2e-runner` / GPT-6 Luna / low ran `node scripts/build_document_registry.mjs --check` at the same HEAD; exit 0 after about 2 minutes. Node v24.13.1, Windows 10.0.26300, PowerShell 7. The isolated Git fixture had `main` and `feature`, two tracked Markdown files, and one local-only file; `--check` and assertions passed with `2 tracked paths, 1 local-only path`. The agent corrected an initial assertion that looked in the wrong output directory and reran successfully. Fixture path: `D:\Temp\cr168-registry-e2e-20261017`.
- Exact generator source blob verified by both agents: `d6e01074f22a9219633f632a47c9ccd3e2b3231f`, based on repository HEAD `06d1f1c08a79f9814e7746acddef1df451e54745`.
- All three isolated scratch fixtures remain in `D:\Temp`: `registry-cr168-functional-final-af6d5ae70b8e4d80b420f34ed014b1c8`, `registry-cr168-tracked-count-1bf7182f8fa64759ab9f9ebd535f9c25`, and `cr168-registry-e2e-20261017`. Cleanup attempts were rejected by the execution policy; no project files were modified by the agents and no deletion bypass was attempted.
- This change affects only generated wording and does not alter project behavior, gate evidence, database state, or authorization.
- No product behavior tests, builds, database operations, migrations, CI, production operations, or release actions were run for this documentation-generator change.
