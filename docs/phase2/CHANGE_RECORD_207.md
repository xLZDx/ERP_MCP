# Change Record 207 — validate private-writer caller scope elements at authorization

## What changed

- `ConfiguredPrivateWriterAuthorizer.authorize_lookup()` now validates every member of `caller.scopes` as a bounded, trimmed string without control characters before accepting the private-writer scope.
- Removed a duplicate subject-shape predicate from the same compound guard.

## Why

The normal authenticator already validates scope claims, but the authorizer is also a callable trust boundary and can receive a constructed `PrivateWriterCaller`. It must fail closed on malformed scope members even when used directly or miscomposed.

## Evidence and verification state

- Changed source: `src/erp_mcp_private_writer/private_authorization.py`, `ConfiguredPrivateWriterAuthorizer.authorize_lookup()`.
- Source SHA-256 after this change: `0F1B0A543729A36634476442D97A48917FC35DBD7FF9A30FE455D75809E9DCDA`.
- The source was untracked at the start of this turn and already contained the authorizer. This record attributes only the scope-member validation above to this change.
- Manual source inspection only. Tests/checks/build, listener startup, database, migration, COM, staging, commit, and push were not run. `S13-PRIVATE-INGRESS-AUTH-TIMEOUT-01` remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after source coding closes, assign malformed scope member and valid-scope controls to the functional/E2E roles as part of private-ingress qualification, then obtain the relevant security review.
