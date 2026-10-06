# Supply-chain checks — integration candidate

2026-10-06; source integration baseline `d05c620` plus schema-v9/runtime-audit follow-up.

Python installed environment: pip 26.2.1, `pip-audit` reports no known vulnerabilities.
The venv's initial bundled pip 25.3 failed audit; it was upgraded, no advisory was suppressed.
Universal runtime/development lock generation and SBOM/image OS scan remain pending.

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
