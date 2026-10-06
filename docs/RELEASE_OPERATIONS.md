# Release and operations evidence

The release preflight is deterministic and local: `uv run --locked python scripts/release_preflight.py`.
It verifies the pinned dependency locks, mandatory upstream reuse documents, ADR-0003, production
and rollback runbooks. It does not claim production readiness.

The non-destructive rollback manifest validator is:

```text
uv run --locked python scripts/rollback_rehearsal.py <restricted-manifest.json>
```

The manifest contains immutable gateway/sidecar image digests, current/previous release references,
database recovery point, migration version, secret version identifiers and named authorization. It
rejects secret values and never performs restore, cutover, deletion or credential rollback. The
actual isolated restore and traffic rehearsal requires an operator-approved production-like target.

Required operational evidence before GO:

- dependency failure matrix and sanitized failure responses;
- protected metrics, correlation IDs and privacy-safe spans;
- DNS resolution/egress evidence for gateway, sidecar and 1C destinations;
- secret-provider rotation and ephemeral RSV config evidence;
- isolated database restore and immutable image rollback rehearsal;
- synthetic scenario validation plus ten real native 1C reconciliations;
- release artifact/SBOM/provenance and named operator approval.

Additional local automation:

- `uv run --locked python scripts/dependency_failure_matrix.py` validates the six-case fail-closed
  contract used by the deployment fault-injection harness;
- `uv run --locked python scripts/capability_report.py <export.json>` renders source capability
  evidence without inventing unsupported operations;
- `uv run --locked python scripts/release_evidence_bundle.py --output <bundle.json>` records the
  exact commit/branch and evidence file set without including secret values;
- `deploy/alerts/prometheus.rules.yml` contains bounded-cardinality alert rules for server errors,
  dependency failures, audit errors and MCP latency.
