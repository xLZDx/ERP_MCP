# Change Record 239 — validate approval nonce before ranked fences

## What changed

- `store_approval_text_v1`, `approve_v1`, and `reject_v1` now require a lowercase 64-character hexadecimal nonce in request-shape validation before their first ranked fence (namespace 2 for store/approve; namespace 7 for reject) and before every namespace-6 nonce key.
- The S13 nonce qualification row now asserts that NULL, malformed, uppercase, and wrong-length nonce inputs refuse before ranked fences on all three routes.

## Why

`issue_approval_nonce_v1` and the adapter establish the nonce as exactly 64 lowercase hexadecimal characters. The approval-text, approval, and rejection routines previously accepted arbitrary nonempty caller strings until they used those values to form namespace-6 lock keys. Early validation keeps malformed values out of the ranked lock plan and makes its bounds explicit.

## Baseline and provenance

The migration 027 candidate was already untracked in the dirty worktree. Its SHA-256 immediately before this focused edit was `EF35B9A75171DDE7AEEA65AD62A5359DCC8AB35C5FFCECB42AB31125A4DE430B`; this includes the separate changes recorded in Change Records 237 and 238. Repository HEAD remained `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`. No unrelated worktree content was intentionally rewritten.

Candidate SHA-256 after this edit: `887462DC75D9508DCC37E6749068554E261D8DE274F9B20C73328C520A5C4E26`.

## Verification state

- Local `code-reviewer` passes (GPT-6 Luna, low effort) identified missing pre-fence nonce validation on store, approve and reject. The final source recheck confirmed the guards precede each route's first ranked lock and namespace-6 key derivation, with no collateral lock-order change. No SQL parsing, tests, or database operations were performed.
- No SQL parse, migration, database operation, test, check, build, or CI was run. Candidate 027 remains unparsed, uninstalled, and ungranted; runtime behavior remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: independently recheck the corrected source, then continue the candidate S13 lock and grant crosswalk. Functional/E2E qualification and database review remain after coding closure.
