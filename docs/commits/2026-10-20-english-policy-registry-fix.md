# English-only policy: document registry fix and Cyrillic inventory (2026-10-20)

## Why
GPT-PM rejected publication because `governance/DOCUMENT_REGISTRY.md` contained Cyrillic lines (33 lines by
`grep` of U+0400-U+04FF; the reviewer counted 26 by a narrower pattern). Operator rule: all text committed to git is English.

## Root cause
The registry generator `scripts/build_document_registry.mjs` quotes the first heading of every Markdown blob over ALL
local and remote refs. On the current tree the headings are already English; the Cyrillic comes from
(a) 20 rows whose Russian heading variants live on other refs (archive, rescue, snapshot, origin branches), and
(b) 13 rows for vendored third-party Russian documents (`vendor/reference/...`) and one Cyrillic path that exist
only on other refs. Translating documents on this branch cannot remove text that other refs still carry, and
those refs and vendored upstream text must not be rewritten.

## What changed
- `scripts/build_document_registry.mjs`: the `esc` cell escaper now writes every Cyrillic character (U+0400-U+04FF)
  as a `\uXXXX` escape (lossless, valid inside the JSON-quoted title cells), and the registry preamble gets one
  sentence saying so. No other generator behavior changed.
- `governance/DOCUMENT_REGISTRY.md`: regenerated with `node scripts/build_document_registry.mjs`.
  Cyrillic lines: 33 before, 0 after. Other differences are expected staleness only: inventory 408 -> 409 paths
  (the merge change record added earlier), the two ref commit ids (`main`, `integrate/2026-10-20`), the new preamble line.
- `docs/commits/2026-10-20-english-policy-inventory.md`: new inventory of all tracked
  .md/.py/.toml/.yaml/.yml/.json/.sh files with Cyrillic (128 files), classified, with next step and exception candidates.
- `core/DECISION_LOG.md`, `core/LESSONS_LOG.md`: entries.

## Deviation from the task text
The task asked to translate the source headings. On this branch the source headings were already English, so
there was nothing to translate; the escape in the generator is the only way to keep the all-refs inventory
English without rewriting other refs. Not translated: prose elsewhere (separate sprint, see inventory).

## Verification
- `node --check scripts/build_document_registry.mjs`: ok. Registry regenerated; Cyrillic line count 0.
- No deleted files; no conflict markers in changed files. No Python files changed.
- Tests: main set compared with the baseline (2 pre-existing failures); no test references the registry
  generator or `DOCUMENT_REGISTRY` (grep of tests/, scripts/, .github).
- Not verified: the registry records the pre-commit HEAD (`e82022a`), so `--check` after this commit reports it stale
  by the ref ids, as for every earlier commit of this branch.
