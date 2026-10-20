# Integrate origin/docs/public-readme-install-guide-20261009 (2026-10-20)

## What
Hand merge of tip 26324d4 (5 commits: README rewrite, installation guide, lessons learned, trailing-whitespace cleanup) into the integration branch started from 48884a2c.

## Finding
BASE already contains the branch's content in newer form (squash-merged PR #25 plus later edits). `git diff --numstat 48884a2c 26324d4 -- README.md docs/INSTALLATION_GUIDE_RU.md docs/LESSONS_LEARNED_RU.md` shows 0 insertions and only 4/22/6 deletions, i.e. every branch line is already on BASE; the branch is a strict subset of BASE for the only three files it changed.

## Conflicts and resolution
Three add/add conflicts (README.md, docs/INSTALLATION_GUIDE_RU.md, docs/LESSONS_LEARNED_RU.md). Resolved by keeping the BASE version of each: the branch side has no line that BASE lacks, and the BASE-only lines are later accurate additions (real-1C L2 bootstrap, Unix production boundaries, ComSpec lesson). The merge commit records the ancestry so the branch is no longer listed as unmerged.

## Checks
- Deleted-files audit vs HEAD: empty. No conflict markers. Tree content equals BASE (only ancestry added).
- Tests not re-run (docs-only, tree identical to BASE).
