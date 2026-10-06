# Supply-chain checks — integration candidate

## Current local closure checkpoint — 2026-10-06

- Python universal `uv.lock` and hash-checked `requirements-runtime.lock` added; lock regeneration is verified by CI workflow wiring. `pip-audit -r requirements-runtime.lock`: no known vulnerabilities.
- Gateway final runtime: pinned `cgr.dev/chainguard/python` digest, Python 3.14.8; build dependencies installed from the exact runtime lock on pinned Python 3.14.8 builder. The local final image imports the app/runtime dependencies successfully.
- OData final runtime: pinned `cgr.dev/chainguard/node` digest, Node 26.10.0; build/test source remains Node 24.18.0 and the exact pinned upstream SHA. The upstream client/metadata package lock was not modified.
- Trivy 0.75.0 local final-image scan exits 0 for both images at `UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL`, `ignore-unfixed=false`, no exceptions/suppressions. CycloneDX SBOM generation and provenance upload are wired into CI; hosted artifact confirmation still awaits CI after the batch is committed.
- Exact sidecar runtime inventory: 9 packages, 0 registry advisories; wrapper contract suite 11/11; non-root sidecar health smoke PASS. Final image uses UID/GID 65532.

The standard Debian/Alpine images initially failed strict Trivy due large base-system advisory sets; we replaced only final runtime layers with minimal pinned Chainguard images and retained the exact pinned upstream source/build chain. Those earlier failed scans are diagnostic history, not the current image result. Full source repository audit advisories remain separately visible below and are not mistaken for deployed runtime findings.

2026-10-06; source integration baseline `d05c620` plus schema-v9/runtime-audit follow-up.

Python installed environment: pip 26.2.1, `pip-audit` reports no known vulnerabilities.
The venv's initial bundled pip 25.3 failed audit; it was upgraded, no advisory was suppressed.
Historical baseline note: universal locks and image scans were pending before the current local closure checkpoint above.

Pinned upstream source remains `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`, MIT.
Client/metadata source is unchanged. Frozen upstream workspace test/build passed.
Whole workspace `pnpm audit --prod` reported 33 vulnerabilities (1 critical, 10 high,
20 moderate, 2 low) in dependency trees of upstream MCP/CLI packages. Neither upstream
MCP nor CLI is deployed or exposed by ERP_MCP; the production image copies only built
client/metadata and metadata's production deployment dependency closure.

Exact installed-image inventory audit via `scripts/audit_node_runtime.mjs` submitted installed
registry dependency versions to npm's documented bulk-advisory endpoint and returned zero advisories:

| Package | Version |
|---|---|
| @1c-odata/client (source pin, upstream tests) | 0.6.0 |
| @nodable/entities | 3.0.0 |
| anynum | 1.0.1 |
| fast-xml-builder | 1.3.0 |
| fast-xml-parser | 5.10.1 |
| is-unsafe | 2.0.0 |
| path-expression-matcher | 1.6.2 |
| strnum | 2.4.1 |
| xml-naming | 0.3.0 |

No upstream dependency pin was silently changed. CI now audits this exact runtime closure,
fails on registry errors/advisories, and retains source-pinned parity tests. The full workspace
finding remains visible here; this does not claim the entire upstream repository is vulnerability-free.

Sidecar image manifest: `e2bdcb11a366538abffe07b68983a670cc61fb4ed862d895d5fcb6c491ed2e98`.
Runtime smoke: UID 10001, read-only root FS, drop ALL capabilities, no-new-privileges,
health endpoint PASS, no published ports. OS-image scan remains pending.
