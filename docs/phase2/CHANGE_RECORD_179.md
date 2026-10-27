# Change record 179 — S12 COM manifest digest primitives

## Scope and reason

S12 requires the writer receipt to bind the ordered COM property/section assignments and the exact
COM method, write mode, target and expected version. The current CT14 evidence does not establish
the canonical payload-to-property crosswalk. This change implements only the deterministic digest
primitives so a later reviewed mapping can produce those receipt fields without retaining business
values in the manifest.

## Changes made in this turn

- Added `src/erp_mcp_private_writer/com_manifest.py` with an immutable assignment record that binds
  property path, assignment kind, declared value type and SHA-256 of an S12-canonical value.
- Added an ordered property-manifest digest that also binds the write mode and property-setting
  method, and an operation-manifest digest that binds operation, method, write mode, target and
  expected version. Both use separate S12 domain prefixes and the existing canonical JSON encoder.
- Added immutable `PreparedComManifest` to calculate both receipt digests from one operation
  descriptor, preventing a caller from accidentally pairing property changes with a different
  write mode.
- Exported the manifest value objects and digest helpers from the private-writer package root for
  later adapter composition.
- The value constructor rejects noncanonical values through the existing closed S12 JSON encoder;
  only the value digest enters the manifest record.

## Decisions and boundaries

- These functions are descriptive digest builders only. They do not discover metadata, map
  `DraftPayload`, validate a signed mapping configuration, create a 1C reference, invoke COM, or
  authorize a writer operation.
- `property_path`, assignment kind/type, method and write mode are supplied by a future reviewed
  clone crosswalk. The historical CT14 copied-document spike is not used as that crosswalk.
- The module cannot establish that the digest formats or configured 1C types are accepted by a
  production trust registry. It remains candidate source pending code review and the assigned
  functional/E2E scenarios after coding closure.

## Review and verification state

- Manually inspected the source against S12 Contract Freeze v2.0 §2.1: property-manifest digest
  includes ordered assignments, write mode, property-setting method and tabular-section paths;
  operation digest includes method/write mode/target/expected version.
- No tests, checks, parser, build, database operation, migration, COM operation, service restart,
  listener startup, staging, commit or push was run. Functional behavior and runtime compatibility
  are `NOT_RUN`.
- Accountable task owner: operator. Executor: Codex. Ivan stack remains the technical owner of its
  host/connection boundary; the metadata crosswalk owner is not established by this source change.
- Next: derive the exact mapping only from current authenticated disposable-clone metadata, then
  have the functional-test-reviewer and e2e-runner cover digest binding and operation behavior after
  all source coding is complete.

## Evidence

- `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md` §2.1 — receipt fields and manifest contents.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` §§206–212 — CT14
  source trace and explicit missing canonical payload mapping.
- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md` §§300–304 — semantic payload
  shape and distinction between historical CT14 operations and a canonical mapping.
