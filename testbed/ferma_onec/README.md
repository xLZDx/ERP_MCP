# Ferma / 1C test boundary

Frozen requirement: TEST-FERMA-1; DoD D5/D9. This directory is excluded from production packaging.

The package verifier consumes the `ferma-1c-scenario/v1` artifact contract documented in the
frozen blueprint. It verifies file checksums, bounded JSON/JSONL, canonical envelope scope and
trade fact constraints. It does not implement a Ferma generator or verify Ferma's own semantic
digest algorithm. Existing Ferma runtime exports contain observed positions; they must never be
relabeled as independent expected/oracle positions.

Run `uv run --locked python -m testbed.ferma_onec verify --package <private-scenario-directory>`.
The output contains identifiers, fingerprints and counts, not business facts or credentials.

The seed-facing `SeedInputs` contains immutable manifest/master-data/events only. Expected files
are verified at intake and never returned to a seed consumer. `validate_target` requires a
synthetic marker bound to the exact allowlisted directory/source/metadata and separate write/read
secret references. No native document seeder is enabled by this foundation.

The comparator accepts independently captured native, gateway and optional Ferma observations.
It requires identical scope, declared per-measurement tolerance, distinct origin references,
finite decimals and complete nontruncated measurements. Missing observations return
EVIDENCE_REQUIRED; incompatible/incomplete observations return INCONCLUSIVE; discrepancies remain
FINDING. Output preserves the input test level and never grants production approval.

## Actual pinned Ferma exporter

`python -B -m testbed.ferma_onec.exporter --ferma-snapshot <private-pinned-snapshot> --output
<new-private-directory> --created-at <aware-ISO-timestamp> [--scenario three-company-chain]`
uses the exact Ferma source commit `d361fab0c3b251ff3c55f681bd2e192bb36c0019`, never the modified
working tree. Prepare a NEW private git-archive snapshot of `src/ferma`,
`architecture/independence_policy.toml` and `tests/archcheck.py`. 132 files / tree SHA-256
`b96e4cde74427e3bbf54ac6f6dd453b8c120ff0e23285c05f9cfc050ceeef4be` are verified before/after execution;
symlinks, cached bytecode, oversized/extra/changed files and outside-loaded Ferma modules fail.
No source/generator/oracle code is copied into ERP_MCP; this isolated test-plane module calls
Ferma's `prepare_canonical`, actual integrity/usage-policy gate and independent `OracleProjector`.
The pinned transitive oracle architecture check must PASS. Output refuses any Git worktree or
existing directory. Only operator-private INTERNAL_TEST_ONLY packages are produced.

Events/master data come directly from Ferma; expected positions come only from its oracle at
each event tick. ActualProjector mutations cannot affect exports; unavailable oracle creates no
package. Wall clock does not alter economic outputs. Seed inputs still exclude expected data.
The pinned generator's bakery/cafe and three-company chain are reused, not new scenario families.

Ferma's native identities are 32-hex truncated BLAKE2b with `SEMANTIC_V3`, retained separately as
`ferma_*_digest`. They are NOT SHA-256. Package/profile SHA-256 uses a named
`ERP_MCP_EXPORT_SHA256_JSON_V1` serialization envelope; no Ferma digest grammar is reimplemented.
Naive Ferma logical time is explicitly attached to the synthetic UTC axis via
`NAIVE_LOGICAL_AS_UTC_V1`; this does NOT infer any native company's timezone or semantic mapping.
Native observers must confirm their own company/configuration period/timezone profile.

Still open: full frozen scenario matrix, exact native configuration/mapping, business-document
seeder, native report observer, authenticated ERP_MCP observer and real twenty-case L2 execution.
Actual exporter evidence is L1 only; packages/source snapshots stay private, not public CI artifacts.
