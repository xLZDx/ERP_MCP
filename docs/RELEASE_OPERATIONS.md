# Release and operations evidence

Evidence correction (2026-10-06): previous fixed-number benchmark and constant-PASS harness
artifacts are superseded. The benchmark measures the production FanoutExecutor; missing DB pool
measurements remain null. Contract evidence comes from executed pytest/JUnit; mutation evidence
executes four fan-out guard mutations. Docker --execute now stops/restarts NEW disposable
PostgreSQL/Redis and checks production readiness responses (503 then 200). Containers are retained.
JWKS/secrets/OData/RSV/audit recovery are not covered by that Docker drill.

Run `uv run --locked python scripts/validate_prometheus.py --output <evidence.json>` for pinned
promtool rule lint, pending/firing/resolution fixtures and actual gateway metrics text validation.
The Docker checker is network-isolated, read-only, capability-free, with bounded tmpfs. Deployed
alert delivery is not claimed.

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

Registry diagnostics (FR-C1/C2), using `BAG_DATABASE_URL` from the operator environment, never a
command-line DSN. Use a least-privilege registry-reader account; every snapshot is repeatable-read
and read-only. Default output is counts/reason codes only; `--details` is PRIVATE operator output.

```powershell
python -m scripts.capability_registry_cli capability-list
python -m scripts.capability_registry_cli stale-profile
python -m scripts.capability_registry_cli unsupported-reason --source-id SOURCE_ALIAS --register AccountingRegister_EXACT_BINDING --method drCrTurnovers
python -m scripts.capability_registry_cli capability-diff --before PRIVATE_BEFORE.json --after PRIVATE_AFTER.json
python -m scripts.capability_registry_cli export-evidence-manifest --output D:\\PRIVATE_TESTBED\\capabilities-new.json
```

Exports must stay outside this repository and cannot overwrite existing files. They contain no
endpoint, username/password references or raw upstream evidence. They remain private metadata,
not publication artifacts. The diagnostic does not acknowledge drift, refresh/probe a source or
authorize an operation: runtime ACL/live capability checks remain mandatory. `SUPPORTED` requires
an exact fresh live-metadata profile/source/fingerprint and enabled OData JSON route; stale,
drifted, absent and oversized profiles cannot grant support. Diff keys include register EntitySet
so two registers with the same method never collapse. `python -m scripts.capability_registry_drill`
creates a NEW disposable PostgreSQL instance; it retains the container and reports executed tests.

- `uv run --locked python scripts/dependency_failure_matrix.py` validates the six-case fail-closed
  contract used by the deployment fault-injection harness;
- `uv run --locked python scripts/capability_report.py <export.json>` renders source capability
  evidence without inventing unsupported operations;
- `uv run --locked python scripts/release_evidence_bundle.py --output <bundle.json>` records the
  exact commit/branch and evidence file set without including secret values;
- `deploy/alerts/prometheus.rules.yml` contains bounded-cardinality alert rules for server errors,
  dependency failures, audit errors and MCP latency.
- `uv run --locked python scripts/validate_performance_evidence.py <evidence.json>` validates load
  artifacts while explicitly keeping the result as evidence, not capacity sign-off;
- `uv run --locked python scripts/check_report_references.py` prevents a release with missing or
  contradictory authoritative report artifacts.
- `uv run --locked python scripts/fault_injection_runner.py` executes readiness contracts;
  actual PostgreSQL/Redis stop/restart evidence comes from `docker_fault_runner.py --execute`.
  JWKS/secrets/OData/RSV/audit container recovery remains open, not inferred from unit tests.
- `uv run --locked python scripts/rsv_lifecycle_harness.py` executes the adapter unit contracts;
  the separate `rsv_process_harness.py` executes crash, timeout, malformed response, new-process
  recovery and between-call configuration rotation via actual official SDK MCP stdio sessions.
  Native COM/1C crash and Windows secret DACL evidence remain open.
- `uv run --locked python scripts/performance_benchmark.py --output <evidence.json>` emits the
  measured 30/50/100/150-source p50/p95/p99, tracemalloc memory and isolation evidence.
  Database pool wait is explicitly NOT_MEASURED, not a synthetic timing.
- `uv run --locked python scripts/validate_metrics.py deploy/alerts/prometheus.rules.yml` checks
  alert names and rejects source/company/query/path labels.
- `uv run --locked python scripts/capability_report.py <export.json> --diff <other.json>` provides
  capability diff, stale/unsupported views and an evidence-manifest export.
- `uv run --locked python scripts/security_regression_pack.py` executes scanner regressions;
  it does not claim full envelope fuzzing or network isolation coverage.
- `deploy/runbooks/ONBOARDING_OFFBOARDING.md`, `CREDENTIAL_ROTATION_AND_DRIFT.md` and
  `ADAPTER_CRASH_RECOVERY.md` are mandatory operator references for lifecycle changes.
- `uv run --locked python scripts/rsv_process_harness.py` executes the lifecycle cases against a
  real local fake subprocess; it never connects to 1C.
- `uv run --locked python scripts/docker_fault_runner.py` validates the Compose fault plan; use
  `--execute` only in an isolated Docker environment approved for disposable dependencies.
- `uv run --locked python scripts/scan_sensitive_artifacts.py <files...>` rejects credentials,
  authorization headers, DSNs and transport secrets in logs/evidence.
- `uv run --locked python scripts/ssrf_fuzz_matrix.py` and `mutation_negative_pack.py` run the
  deterministic SSRF/traversal/redirect and fail-closed mutation-negative matrices.
