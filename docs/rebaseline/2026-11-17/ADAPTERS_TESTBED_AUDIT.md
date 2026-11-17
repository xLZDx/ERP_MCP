# Adapter/testbed implementation audit — 2026-11-17

Static code-reviewer inspection; no tests/build/checks, source changes, live
calls, test-data mutation, runtime launch or cleanup was performed.

## AT-01 MINOR — capability refusal incorrectly contributes to circuit opening

adapters/odata-sidecar/server.mjs:509-511 throws CAPABILITY_UNSUPPORTED for
missing/stale register evidence inside the upstream try/catch. The catch at
552-559 increments the same source circuit failure counter as transport faults.
Five capability mismatches can therefore open the circuit for ten seconds,
causing valid subsequent reads to fail with CIRCUIT_OPEN/503. The adapter
contract:56-70 defines this capability denial as 422; it should not be treated
as an upstream outage. Count only transport/upstream failures or explicitly
classify semantic 4xx refusals outside the breaker. Runtime reproduction NOT_RUN.

## AT-02 MINOR — interrupted export leaves an unretryable partial destination

testbed/ferma_onec/exporter.py:149-165 validates/generates before making output,
but creates the final destination before all files/checksums/load_seed_inputs
finish. A failure can leave partial output; retrying that path immediately fails
because output.exists() is refused. Prepare a unique sibling staging directory,
validate it, publish atomically and clean only that owned staging directory on
failure. No existing output or test data was deleted by this audit.

## Reviewed implementation and contracts

- OData sidecar server.mjs/egress.mjs and ADAPTER_CONTRACT_ODATA_SIDECAR.
- Gateway adapters/onec/rsv_bridge.py and rsv_privacy.py with runtime call sites.
- testbed/ferma_onec target_guard, exporter, package_loader, reconcile,
  export_harness and README; REAL_1C_SEED_SPEC.
- testbed/fake1c sidecar_app/sidecar_recording_app; testbed/idp/app.
- testlane/phase2_mcp server/config/gateway_client; onec_extension README.
- real1c/lane_proxy.py, E2E up/_common and remote run-mcp-stack/setup-1c-odata/
  store-and-test-reader scripts; ADR-0009.

Excluded third-party vendor/node_modules/build outputs. Source inspection is not
live network isolation, licensing, accounting reconciliation or native COM
qualification. G-02 deployment composition and operational COM-port gaps are
covered by other audits, not duplicated as new findings here.
