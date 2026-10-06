# Source onboarding/offboarding

## Onboarding

1. Create a source record with `read_only=true`, exact host allowlist and secret references.
2. Run metadata-only health and capability probes; do not infer virtual-table names.
3. Store the evidence manifest and operator approval reference.
4. Run the synthetic contract suite, then a controlled pilot before enabling a tool.

## Offboarding

1. Disable the source and revoke its secret references.
2. Mark all source/company profiles stale and verify capability calls return `CAPABILITY_UNSUPPORTED`.
3. Preserve audit provenance and evidence references; do not delete them as part of offboarding.
4. Confirm no cached fan-out work remains before removing the source configuration.
