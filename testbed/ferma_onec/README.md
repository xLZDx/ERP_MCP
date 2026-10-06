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

Still open: an approved Ferma package exporter with independent expected artifacts, exact native
configuration/mapping, business-document seeder, native report observer, authenticated ERP_MCP
observer and real twenty-case L2 execution. The current fixtures are contract tests only.
