# Lessons log

- 2026-10-20 SUCCESS integrate docs-public-readme: proving a branch is a subset of BASE via git diff --numstat BASE tip (0 insertions) made the add/add conflicts trivial and safe to resolve by hand.

- 2026-10-20 SHORTCOMING integrate docs-english-only: a scripted conflict resolution on a CRLF-checked-out file wrote mixed line endings (found by counting CR/CRLF against the branch blobs). Next time: count bytes against the committed blob after any scripted write.
