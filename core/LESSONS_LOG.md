# Lessons log

- 2026-10-20 SUCCESS integrate docs-public-readme: proving a branch is a subset of BASE via git diff --numstat BASE tip (0 insertions) made the add/add conflicts trivial and safe to resolve by hand.

- 2026-10-20 SHORTCOMING integrate docs-english-only: a scripted conflict resolution on a CRLF-checked-out file wrote mixed line endings (found by counting CR/CRLF against the branch blobs). Next time: count bytes against the committed blob after any scripted write.

- 2026-10-20 SHORTCOMING integrate phase2: two parallel branches edited the same docs (one translated, one extended) so text conflicts were unavoidable; status notes were appended untranslated rather than translated. Rule: land translation work after content branches, or translate in the same pass.

- 2026-10-20 FAILURE (caught by tests) integrate: the combined tree failed one phase2 test because two branches changed the same invariant independently (validator vs forged-value test). Rule: after combining hardening and tests, run the whole new test directory, and rewrite the forging helper rather than relax the validator.

- 2026-10-20 NEUTRAL integrate: unused-noqa count is a cheap mechanical post-merge check; ruff --fix handled it.

- 2026-10-20 SHORTCOMING integrate: the phase2 merge first appended Russian text verbatim, which broke the English-only git rule and needed a separate translation commit. Rule: translate carried-over text in the same merge commit and run a Cyrillic-in-added-lines check before committing.

- 2026-10-20 SUCCESS merge ERP_MCP_R2 into ERP_MCP: for an extraction with no merge-base, comparing each conflicting file against the common ancestor-in-spirit (the phase2 branch tip both lines descend from) decided 58 of 64 conflicts mechanically without guessing; the merged failing-test set equals R2's own tip run. Rule: for unrelated-history merges, find the shared source commit and diff both sides against it per file. SHORTCOMING: R2-only code brings about 250 ruff findings and new Russian prose docs; a lint pass and a translation pass are left as separate follow-ups (lint was never a gate on the R2 line).
