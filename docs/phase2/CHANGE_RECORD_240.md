# Change Record 240 — preserve current permit guards on S13 replay

## What changed

- `private_writer_issue_permit_v1` now rechecks the locked scope, generation, `APPLYING` state, switch, target effect, registry effect, and repair authorization before its exact-binding replay branch.
- An existing binding is returned only while the locked dispatch permit remains `PERMITTED`. An expired permit still replays when that state remains `PERMITTED`, matching the legacy route.
- The disposable qualification prerequisite now covers replay after each current-state guard or permit state changes and requires a refusal with no row or event delta.

## Why

The first source review found that a stored binding could be returned after generation/state/authorization changed, bypassing the legacy `issue_permit` guards. A stale binding must not be presented as a current permit.

## Baseline and provenance

The candidate migration was already an untracked file in the existing dirty worktree. Immediately before this focused correction, its SHA-256 was `887462DC75D9508DCC37E6749068554E261D8DE274F9B20C73328C520A5C4E26`; the qualification prerequisite SHA-256 was `FD1BAD25948A1BC1FDC750D629E1DC7DCFEF79E0051FA55F25BCD082A4280C95`. Repository HEAD remains `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`. Unrelated worktree content was not intentionally changed.

Candidate migration SHA-256 after the correction: `D61228FFDF8068874D4E741A5AF7CC829BE092E7A63303CE8A7B439104F489BE`. Qualification prerequisite SHA-256 after the scenario update: `8CA0CBBF9F76B475FF17C42E1C82C56C48D73A4407758FB5ADA7B83219196701`.

## Review and verification state

- The actual `code-reviewer` role reported one MAJOR source finding and the exact legacy guard order (`db/phase2/008_change_hardening_b.sql:567–579`). GPT-6 Luna, low effort is the configured reviewer profile. This is a read-only source review.
- Focused source re-review confirmed the correction: all legacy current-state guards precede binding replay; replay requires `PERMITTED` but intentionally does not reject expiry by timestamp; the row-lock order and new-issuance path are unchanged. No remaining finding in the rechecked scope.
- No SQL parser, tests, checks, database operation, migration, COM call, stage, commit, or push ran. Candidate SQL remains unparsed and uninstalled; effective grants and runtime behavior remain `NOT_VERIFIED` / `NOT_RUN`.
- The corrected source has not yet had a reviewer recheck.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Technical owner of the remote writer boundary: Ivan stack. Next: obtain a focused source recheck of the exact correction, then continue source closure before the disposable qualification phase.
