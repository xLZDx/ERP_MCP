# Contributing to ERP_MCP

## Before a change

Read `AGENTS.md`, `docs/DOCUMENT_INDEX.md`, and the relevant normative documents. Check the working
tree and identify the applicable governance class in `docs/GOVERNANCE.md`.

## Pull-request expectations

Describe:

- exact scope and affected requirements/DoD gates;
- security, data-model, deployment, and licensing impact;
- tests and evidence, including exact commit/configuration where relevant;
- rollback or recovery approach;
- known limitations and deferred work.

Adapter work must also document upstreams searched, pinned SHA, license, and whether the code is a
dependency, port, sidecar, isolated service, or reference-only.

## Local checks

```powershell
$env:PYTHONPATH = 'src'
python -m compileall -q src tests scripts testbed
python -m pytest -q
python -m ruff check .
```

Do not include real 1C data, credentials, licensed 1C binaries, or customer information.
