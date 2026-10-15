# Change record 030 — document registry refresh

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after the S14-R02 test evidence and change record were committed.
- Included the current S14-R02 evidence record in the tracked-document inventory.

## Why

The repository's generated document index should reflect the newly committed design and evidence records so later work can locate the current S14 checkpoint and acceptance evidence.

## Contracts and paths

This is documentation maintenance only. It does not change source, test behavior, runtime configuration, or any project gate.

Affected paths: `governance/DOCUMENT_REGISTRY.md`.

## Verification state

The registry generator scanned four branch refs after commit `5cd812a0d02372614c6412cb6ab7ba19a51f963c` and reported 87 tracked Markdown paths with no local-only Markdown files. This record is added to the same next commit as the registry update, so the post-commit inventory contains 88 tracked paths. The generator is run again after commit to confirm the generated file matches that committed inventory.
