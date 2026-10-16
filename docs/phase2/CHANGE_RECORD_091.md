# Change record 091 — record the approved G1 push

## What changed

- Updated the Russian and English G1 local-push status reports to record PM approval and successful fast-forward push of reviewed HEAD `17900345c88237290c498d73b6f8849c265351d1` to `origin/main`.
- Recorded the pre-push remote HEAD `3aba6e37af8d3e5d1d98eb4f5f308e15aec1e3ac`, the pushed range, and the observed post-push remote HEAD.
- Reconciled `G1_EVIDENCE_PACKET_PLAN.md` with the completed push while retaining formal G1 `NOT_PASSED`, production authorization `NONE`, and Release 2 `NO-GO`.
- Stated that this follow-up documentation commit is a new HEAD and is not covered by the prior PM approval; any later push requires fresh exact-head approval.

## Why

The existing report still described push as pending after the exact reviewed range had been approved and pushed. That status was stale and could mislead operators about remote state and the scope of the approval.

## Decisions and scope

- Push evidence: normal fast-forward push `3aba6e37af8d3e5d1d98eb4f5f308e15aec1e3ac..17900345c88237290c498d73b6f8849c265351d1` to `origin/main`; the task supplied the successful `main -> main` result.
- Before editing, `git ls-remote origin refs/heads/main` returned `17900345c88237290c498d73b6f8849c265351d1`, equal to the approved/pushed HEAD.
- This change updates documentation only. It does not alter code, tests, database state, formal G1 acceptance, Release 2 status, or production authorization.
- `.claude/` is unrelated and remains untouched.

## Review and verification state

- Documentation facts were reconciled against the supplied push result and a pre-edit remote-head lookup.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- This new documentation HEAD is not covered by the PM decision for `17900345c88237290c498d73b6f8849c265351d1`; do not push it without a fresh exact-head PM decision.

## Contracts and paths

- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.ru.html`
- `reports/G1_LOCAL_PUSH_STATUS_2026-10-16.html`
- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/CHANGE_RECORD_091.md`

## Acceptance

- Both language reports state the reviewed HEAD, push range, remote, and post-push remote HEAD.
- The evidence plan agrees with the reports and separates local push from formal G1/release acceptance.
- The formal gate statuses remain unchanged.
- A later push is clearly gated on fresh approval of its exact HEAD.