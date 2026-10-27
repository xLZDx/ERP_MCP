# Change Record 295 — require runtime ownership for every private ingress factory

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

`create_private_writer_app()` accepted `runtime=None`. That path skipped both the prepared-runtime ASGI startup gate and the lifespan drain/close call. Although `create_private_writer_runtime_app()` used the safe path, callers of the exported lower-level factory could construct an app without any runtime lifecycle owner. No in-repository source caller used the lower-level factory.

The runtime dataclass could also be constructed with the service's identity but a different writer or authority mutex. Its shutdown would then close unrelated dependencies while the service retained the active ones.

## Change

Made `PrivateWriterRuntime` a required keyword argument for `create_private_writer_app()` and require that its service is the exact service routed by the app. The factory now always checks readiness during ASGI startup and always drains/closes the runtime in lifespan finalization. The convenience `create_private_writer_runtime_app()` remains the supported compact entry point. No factory path can now create the ingress app without runtime ownership.

`PrivateWriterRuntime.__post_init__()` now also requires its service, Windows authority mutex, and writer to be the exact expected objects and requires the service to hold those same writer/mutex references. Inconsistent resource ownership refuses construction with `WRITER_RUNTIME_DEPENDENCIES_MISMATCH`.

## Affected paths and contracts

- `src/erp_mcp_private_writer/private_ingress.py` — eliminate lifecycle-free app construction.
- `src/erp_mcp_private_writer/runtime_composition.py` — bind close ownership to the service's exact writer and mutex.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — require rejection of missing/mismatched runtime and lifecycle coverage for both factories.

## Verification state

Source inspection confirmed there are no other in-repository `create_private_writer_app()` callers. Runtime factory construction, pre-start refusal, lifespan close order, and listener shutdown behavior remain `NOT_RUN`; no tests/checks, build, SQL parse, migration, database action, COM call, stage, commit, or push occurred. This source change does not establish an operational writer, qualified identity providers, approved listener binding, or runtime behavior.
