# Specialist review and remediation record

Sprint: beea27520b33

## Discovery identity

Reviewed source range: `9454d904d60d371920608088cb326b688895f0cf..499baa96a55cbd8b0df518372ddf6ca58966148a`.
Actual independent roles: code-reviewer, database-reviewer, security-reviewer,
and a11y-architect, each launched with the configured gpt-6-luna role and medium
reasoning effort. Reviews were read-only and ran no tests. Reported test outcomes
were inherited from the dedicated test agents, not independently reproduced by
reviewers.

## Deduplicated findings

| ID / meaning | Severity | Discovery evidence | Current state | Remaining acceptance | Dependency / owner / next action |
|---|---|---|---|---|---|
| CODE-1 / preserve S12 begin-apply gate | MAJOR | `core.py` called CLAIM then ApplyPort without Event.BEGIN_APPLY; T6 guards live in S12 transitions | Fix in progress, not verified | Actual T6 transition before port; missing or refusing evidence gives zero apply calls | Codex implements CR411; test owners falsify guards; code-reviewer rechecks |
| CODE-2 / independently validate proposal authority | MAJOR | `services.py:ChangeService.propose` trusted builder results and asserted requester entitlement without independent live epoch/expiry/scope validation | Fix in progress, not verified | Current authenticated identity and all server-owned returned proposal bindings checked before insertion | Codex implements CR411; functional-test-reviewer tests malicious builder/identity cases; code-reviewer rechecks |
| SEC-1 / bind approved preview to actual proposal | MAJOR | Snapshot digest self-consistency was checked without proving preview/approval text derived from the proposal delivered to ApplyPort | Fix in progress, not verified | Regenerated canonical binding and store-substitution defense at issue/decision/apply; zero apply on substitution | Codex implements CR411; functional-test-reviewer tests self-consistent store tampering; security-reviewer rechecks |
| UI-1 / show complete approval context | MAJOR | Page lacked service-authoritative lifecycle/authorization, created time, explicit snapshot version and current approver label | Fix in progress, not verified | Accessible semantic context from service; no decision form on invalid context/already-decided state | Codex implements CR412; e2e-runner asserts rendered fields and refusal; a11y-architect rechecks |

Database review found no valid BLOCKER/MAJOR in migration 028, ledger wrappers
or the period observation boundary. It made no runtime or query-performance claim.
The security reviewer also noted a conditional same-scope rollback ownership
question. It was not rated MAJOR because the accepted policy permits a new scoped
proposal with separate human approval and does not establish an original-owner-only
rule. Independent live requester authentication still applies to that operation.

## Verification state

This discovery record is not consensus on the fixed source. CR411/CR412 source
work, regression results and targeted reviewer rechecks must be recorded before
the findings can be closed. Final GPT-PM approval has not been requested.
