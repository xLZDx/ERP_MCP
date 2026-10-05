# ERP_MCP Claude project guidance

Read `AGENTS.md` first, then `docs/DOCUMENT_INDEX.md` before implementation or architectural work.

This repository is a read-only 1C MCP gateway. Preserve the following boundaries:

1. No mutation tools or write-capable transport paths in the production artifact.
2. No arbitrary target URLs, direct 1C SQL, secrets in source/logs/results, or caller-supplied identity.
3. Authorization and audit happen through the control plane before a data-plane call.
4. Capability routing is based on observed source behavior and metadata, not configuration names alone.
5. MIT-compatible upstream behavior should be reused with provenance; copyleft code stays isolated.

For implementation status and known gaps, inspect the current code and the normative documents rather
than assuming that the full future architecture has already been implemented.
