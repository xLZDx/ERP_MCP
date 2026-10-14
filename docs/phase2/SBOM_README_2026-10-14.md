# SBOM and pinned dependency lock (2026-10-14)

Operator decision of 2026-10-14: generate an SBOM and a pinned Python dependency lock now. This is a partial lifting of the OB-15 named deferral; host binary checksums and the licenses of 1C and PostgreSQL stay deferred.

## Files

- `requirements.lock.txt`: 41 exact `name==version` lines, sorted by name.
- `sbom/SBOM_2026-10-14.cdx.json`: CycloneDX 1.5 JSON, 41 components plus the project component `erp-mcp-r2` 0.1.0.

## Scope

- The 41 distributions listed in section 9a of `S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md`. `pyproject.toml` declares the runtime roots (asyncpg, defusedxml, httpx, PyYAML) and the extras `dev` and `testlane`; there is no requirements file in R2.
- Versions are those installed in the sibling R1 environment `D:\Repo\ERP_MCP\.venv`. R2 has no environment of its own, so this is NOT the result of a resolver run against R2's `pyproject.toml`.
- The transitive closure of the declared roots (including extras) in that environment is exactly the same 41 packages (checked by the generator).
- Licenses come from package metadata: `License-Expression`, else `License ::` classifiers, else the `License` field. A package with none of these would be recorded with the property `license:status = unknown` instead of a guess. No package fell into this case.

## Not covered

- Host binaries and images: Apache httpd with the 1C extension, PostgreSQL 16, Redis for Windows, Node.js, the tunnel client, the 1C platform, Docker images. Their versions, checksums and licenses are still deferred.
- Hashes: none. No network and no `pip` hash step was run.
- Vulnerability scan: none was performed.
- `License-File` texts were not read; license values are what packages declare.
- R2 has a proprietary `LICENSE` file (all rights reserved), recorded on the project component; there is still no license field in `pyproject.toml`.
- Dependencies not installed in the R1 environment (async-timeout, backports-asyncio-runner, exceptiongroup, httpx2-jsfetch) are absent.

## How it was generated

A throwaway Python script (kept outside the repository) ran with `D:\Repo\ERP_MCP\.venv\Scripts\python.exe -s`. It read the package names from the section 9a table, looked up each installed distribution with `importlib.metadata`, and wrote both files. It also walked `Requires-Dist` from the declared roots to cross-check the closure, and compared versions and license strings with the section 9a table. Nothing was installed, upgraded or downloaded.

## Cross-check result

All 41 versions and license strings match the section 9a table; no discrepancies were found.
