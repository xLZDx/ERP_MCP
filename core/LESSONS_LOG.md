# Lessons log

- 2026-10-21 FAILURE scope-safe search: a broad search across historical docs/reports emitted a matching decision-log excerpt containing customer data. Root cause: output scope was not limited to test identifiers before searching. The project-data boundary did not prevent the output. Next time, query only named test-result files and restrict output to test IDs or sanitized structural fields; do not search historical business evidence for unrelated task terms. No customer values were added to repository changes.

- 2026-10-21 G3 operator disposition: an unsigned waiver statement must be stored as a separate note and must never enter gate closure, predecessor satisfaction, or production authorization logic. Preserve the actual gate status and require the independent evidence for any later PASS; do not reuse G4's cryptographic waiver path for accountant attestation.

- 2026-10-21 FAILURE inherited-test classification: the first hand-over summary omitted two names from the offline-simulation failure set. Root cause: a grouped count was carried forward without reconciling every identifier against the named result files. The correction used an identifier-only filter and emitted no tracebacks or fixture data. Next time, reconcile each recorded test name and aggregate before publishing a classification; label source-based categories as preliminary until authorized execution evidence establishes cause.

- 2026-10-21 SHORTCOMING English-policy scanner: the first scanner version silently skipped NUL bytes even in tracked text-suffix files, which could hide Cyrillic from the policy scan. Root cause: binary-file handling was applied by content rather than the already-selected tracked text-file contract. The local code review caught it before verification. Next time, fail closed on malformed bytes in policy-scanned text files; only exclude paths outside the declared text inventory.

- 2026-10-21 FAILURE remote SSH attempt: a nested PowerShell command string was quoted incorrectly while trying the Tailscale SSH wrapper; the shell reported a local parse/command error after the SSH host-key rejection. Root cause: embedding escaped double quotes inside a PowerShell double-quoted argument. No remote command ran and strict host-key checking remained enabled. Next time, use a simple no-argument identity probe first or pass a script file path with PowerShell's native argument handling; never work around the host-key failure.

- 2026-10-21 SUCCESS autonomous sequencing: after the operator delegated technical decisions, the project instruction reconciled clone-write authority with the no-manual-mutation and test-owner rules: only authorized test agents may perform mapped mutations on named disposable clones after coding. Keep delegation separate from external proof, identity, and formal gate closure.

- 2026-10-21 SHORTCOMING ERP source connector: repeated safe status, source-list and source-health calls all failed at the MCP layer with `-32603: Internal error`, so the connection yielded no source-health evidence. The failing layer is the connected tool/connector path; the underlying cause is unknown. Do not infer that a reachable local gateway or Tailscale peer makes this business connector healthy; retain `NOT_RUN` and escalate through connector service recovery when available.

- 2026-10-20 SUCCESS integrate docs-public-readme: proving a branch is a subset of BASE via git diff --numstat BASE tip (0 insertions) made the add/add conflicts trivial and safe to resolve by hand.

- 2026-10-20 SHORTCOMING integrate docs-english-only: a scripted conflict resolution on a CRLF-checked-out file wrote mixed line endings (found by counting CR/CRLF against the branch blobs). Next time: count bytes against the committed blob after any scripted write.

- 2026-10-20 SHORTCOMING integrate phase2: two parallel branches edited the same docs (one translated, one extended) so text conflicts were unavoidable; status notes were appended untranslated rather than translated. Rule: land translation work after content branches, or translate in the same pass.

- 2026-10-20 FAILURE (caught by tests) integrate: the combined tree failed one phase2 test because two branches changed the same invariant independently (validator vs forged-value test). Rule: after combining hardening and tests, run the whole new test directory, and rewrite the forging helper rather than relax the validator.

- 2026-10-20 NEUTRAL integrate: unused-noqa count is a cheap mechanical post-merge check; ruff --fix handled it.

- 2026-10-20 SHORTCOMING integrate: the phase2 merge first appended Russian text verbatim, which broke the English-only git rule and needed a separate translation commit. Rule: translate carried-over text in the same merge commit and run a Cyrillic-in-added-lines check before committing.

- 2026-10-20 SUCCESS merge ERP_MCP_R2 into ERP_MCP: for an extraction with no merge-base, comparing each conflicting file against the common ancestor-in-spirit (the phase2 branch tip both lines descend from) decided 58 of 64 conflicts mechanically without guessing; the merged failing-test set equals R2's own tip run. Rule: for unrelated-history merges, find the shared source commit and diff both sides against it per file. SHORTCOMING: R2-only code brings about 250 ruff findings and new Russian prose docs; a lint pass and a translation pass are left as separate follow-ups (lint was never a gate on the R2 line).
- 2026-10-20 FAILURE english-policy registry: a generated file carried 33 Cyrillic lines through the merge and was caught only by GPT-PM review (author and gates missed it: no mechanical Cyrillic scan of tracked files). Root cause: generator output depends on all refs, not on the checked-out tree. Rule: scan generated artifacts for policy violations after regeneration; add a Cyrillic checker with an allowlist (inventory next step).

- 2026-10-21 FAILURE merge ERP_MCP_R2 lock drift: the merge changed pyproject.toml dependencies but left uv.lock and requirements-runtime.lock stale; found by GPT-PM review, missed by the author and by the merge checklist (no `uv lock --check` step). Rule: after any merge touching pyproject.toml run `uv lock --check` before committing.

## 2026-10-21 - Commit: record inherited defects backlog

Kind: SUCCESS. Facts: inherited failures and open items were collected from the integration state file and change records into one backlog file instead of being fixed inside the integration. Root cause of the approach: the operator rule that integration must not fix bugs. Layer: operator decision. Rule next time: record each inherited defect with evidence and an acceptance test at integration time.
