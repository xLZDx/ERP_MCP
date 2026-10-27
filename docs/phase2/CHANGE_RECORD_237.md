# Change Record 237 — preserve exact S13 evidence replay identity

## What changed

- Tightened `record_evidence_v1` in candidate migration 027 to reject zero change/evidence UUIDs and non-positive generation or zero call UUID for generation-bound evidence.
- Moved identity-shape refusals ahead of scope and transaction fences so nil identities and invalid generation-bound call tuples fail before any database fence or row access.
- Moved evidence-row identity lookups after locking the `records` parent, preserving the required parent-before-child order.
- Exact immutable-envelope replay now accepts the persisted evidence ID itself or a fresh unused preallocated ID, and returns the original evidence ID without an event. An ID owned by a different row or a changed immutable tuple refuses as `EVIDENCE_IDENTITY_CONFLICT` / `P0001`.
- The insert now handles a concurrent natural-key replay with `ON CONFLICT(change_id,kind,content_hash) DO NOTHING`; it re-reads and compares the complete envelope before returning success. A primary-key collision maps to the existing stable identity-conflict code.
- Preserved legacy missing-parent error precedence after ranked identity fences with a non-locking existence preflight, then revalidated and locked the parent before child lookup or mutation.
- Updated the source inventory and disposable qualification criterion to reflect the candidate behavior and cover same-ID replay and ID reuse.

## Why

The pre-existing candidate rejected every already-present `p_evidence_id` before checking whether it was the exact natural-key replay, so replay with the original stored ID could not succeed. It also queried the evidence child before acquiring its record parent and evaluated invalid identity shapes only after database access. The accepted S13 contract requires pre-fence validation for invalid IDs/generation, full immutable-tuple comparison, parent-first ordering, lookup-only exact replay, no duplicate event, and no disclosure of a conflicting stored ID. Source review also reconciled validation precedence: scope is checked before an invalid kind; zero identities and invalid generation-bound call IDs fail before DB access; after ranked fences a scope-authorized missing parent preserves legacy `CHANGE_NOT_FOUND` over canonical-content, binding and signature validation, while those signature checks remain ahead of replay-conflict handling for an existing parent.

## Baseline and provenance

`db/phase2/027_private_writer_admission_schema.sql` was already an untracked candidate in the dirty worktree. Its pre-edit SHA-256 observed at the start of this turn was `B256C45734FD6DFA6151B2EB28A92C669C66F884C30F7DC196C6009F69C127FA`. The source inventory, qualification prerequisite and lesson log were already dirty; their exact pre-edit hashes were not captured in this turn. No unrelated worktree content was intentionally rewritten.

Candidate SHA-256 at the end of this change-record scope, before the subsequent Change Record 238 edit: `BB39B8CEF037F60D4771B83CF4D847A2A54B708F6802C2BF8688A428E37FF1FD`.
The reviewed source was the uncommitted worktree at HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`; the repository HEAD did not change during this work.

## Verification state

- Source reconciled against the legacy `record_evidence` in `db/phase2/019_ed25519_action_only.sql` and the S13 replay/lock requirements in the source inventory and disposable qualification prerequisites. Local `code-reviewer` passes (GPT-6 Luna, low effort) found one BLOCKER and three P2 ordering findings over successive revisions; all four were corrected. The final read-only pass confirmed pre-fence identity validation, scope-before-kind precedence, ranked-fence missing-parent precedence, and parent-before-child access, with no further implementation finding. Reviewer did not parse SQL, run tests, or access the database.
- No SQL parse, migration, database operation, test, check, build or CI was run. Candidate 027 remains unparsed, uninstalled and ungranted; effective privileges and runtime replay/lock behavior remain `NOT_VERIFIED` / `NOT_RUN`.
- Source-reviewed only. No SQL parse, migration, database operation, test, check, build or CI was run. Candidate 027 remains unparsed, uninstalled and ungranted; effective privileges and runtime replay/lock behavior remain `NOT_VERIFIED` / `NOT_RUN`. This change does not complete the all-path lock graph or S12/S13 qualification.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue the remaining granted-path/lock crosswalk and code closure before functional/E2E qualification. The database-reviewer and test-owner roles are reserved for their later qualification phase.
