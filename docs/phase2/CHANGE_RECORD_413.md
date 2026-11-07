# Change Record 413 - Integrate the complete specialist remediation batch

Sprint: beea27520b33

## Scope and provenance

This commit integrates the source fixes from actual implementation-engineer agents
for all four deduplicated MAJOR findings discovered at source `499baa9` by actual
code-reviewer, security-reviewer and a11y-architect agents. Database-reviewer found
no valid BLOCKER/MAJOR in its independent scope. See `docs/sdlc/specialist-review.md`
for discovery identity; CR411 and CR412 describe exact source and UI contracts.

## Changes and rationale

- CODE-1: use the real S12 BEGIN_APPLY/T6 gate under the core lock before any
  ApplyPort call. The evidence port is optional only to fail closed; successful
  fake tests must explicitly supply observations. A missing real period reader,
  lock/ownership evidence or source proof is not replaced by default positive flags.
- CODE-2: authenticate and authorize a live requester independently of the proposal
  builder, reparse returned proposals against server-owned context, and do not pass
  raw approval nonce to an untrusted builder. The same live-authority rule applies
  to rollback, which remains a separately approved new scoped proposal.
- SEC-1: derive preview and S12 approval bytes from the actual proposal and keep
  immutable issuance/decision/state anchors in the core instance. Store consistency
  alone cannot authenticate a substituted snapshot. Restart without anchors refuses;
  durable recovery and production qualification are explicitly not claimed.
- UI-1: render service-authoritative lifecycle/authorization, immutable version,
  creation time and current approver identity outside immutable canonical bytes.
  Invalid identity/context or an already-decided change yields no decision forms.

## Affected paths and verification

`src/erp_mcp_s16/{__init__,contracts,core,services,fakes,approval_page}.py` plus
CR411/412 and this record. No gateway, listener, production binding, COM writer,
existing migration, or operator data is modified. Baseline dirty ct14_measure.py,
framework state/view and concurrent uncommitted tests are excluded.

Coding is complete for this remediation handoff. No tests, import probes, checks,
builds or live operations ran in this source batch. Regressions and targeted
reviewer verification are pending and owned by their actual roles; this source
commit is not a PASS, consensus verdict, formal acceptance or GPT-PM approval.
