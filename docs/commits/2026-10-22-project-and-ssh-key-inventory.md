# Change record: Inventory project and SSH key access evidence

## Change

- Extended the WP0 evidence artifact with a project path/marker inventory and a user SSH identity inventory.
- Updated the current backlog to distinguish local key-pair integrity from verified ERP authorization.
- No key, ACL, connector credential, database row, or application configuration was changed.

## Why

The operator explicitly requested checking project and SSH keys/access. Earlier evidence covered the default SSH identity and Ivan trust path but did not summarize all identities in the user SSH directory or the project key-material path inventory.

## Contracts and paths

- `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md`: records only fingerprints' match status, ACL categories, filenames, and bounded project inventory results; it omits fingerprint values and private key bytes.
- `docs/phase2/OPERATOR_BACKLOG.md`: states that client key-pair integrity does not prove server-side ERP authorization.
- No business, authorization, database schema, production, or release contract changed.

## Decisions

- Treat local key-pair matches as integrity evidence only; do not infer that any key is authorized for an ERP service from its filename.
- Keep the Ivan host key untrusted until an authenticated out-of-band source confirms it.
- Report connected-app secrets and live database key rows as not inspected because the connectors did not provide an authenticated source response and no secret-bearing store was opened.
- Do not print or persist fingerprint values or private key material.

## Verification state

- User SSH inventory: recursive filename-only enumeration found exactly three private/public pairs and no other key files. All three pairs were fingerprinted using `ssh-keygen -lf` and matched. Private-file ACLs were read as metadata and were limited to the current user, SYSTEM, and Administrators. No authentication attempt was made with the two additional identities.
- Project inventory: tracked paths and private-key markers were searched without printing file contents; common root `.env` paths were absent. The path-only ignored/untracked scan excluded dependency/cache directories and reported no credential-named candidates outside them.
- Read-only MCP `system_status` and `sources_list` were retried for both connectors: `ERP_MCP_REAL1` returned `-32603: Internal error`; `erp-mcp-chatgpt` returned `UNAUTHORIZED` requiring reauthentication. No business data was read.
- Registry generation: `node scripts/build_document_registry.mjs --exclude-local-only`; exit 0, 46 refs, 425 tracked Markdown paths, local-only `NOT_ENUMERATED`, against base HEAD `41e251e1dcd368d609645b66d990d1401ed0eace`.
- No tests, checks, build, CI, migration, remote command, or secret-bearing store read was run.
- Exact diff received read-only GPT-6 Luna `code-reviewer` review at medium effort before commit. The reviewer approved with no material findings, confirming the bounded key inventory, access distinctions, and 425-path registry snapshot. No tests/checks were run.

## Lesson

Separate local key integrity, file permissions, remote host trust, and service authorization. None alone proves the other layers.
