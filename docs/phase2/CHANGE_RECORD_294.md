# Change Record 294 — bind private ingress to prepared runtime lifecycle

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-PHYSICAL-AUTHORITY-DISPATCH-01`.
- State: source implementation only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

`create_private_writer_app()` exposed dispatch and lookup routes but did not tie its ASGI lifecycle to `PrivateWriterRuntime`. A caller could start the server without first completing `prepare_to_serve()`, and application shutdown did not guarantee runtime drain/close after the server stopped accepting requests.

## Change

The ingress factory now accepts an optional exact `PrivateWriterRuntime` whose service must match the routed service. The exported `create_private_writer_runtime_app()` uses that path. Its ASGI lifespan refuses startup unless recovery has already made the service ready, and its `finally` always invokes `runtime.close()`, including failed startup, to avoid leaving non-daemon authority/COM workers behind. The factory does not start a listener, perform recovery, or claim that release gates passed; deployment remains responsible for preparing the service and verifying gates before ASGI startup, and binding the server only to the authorized private interface.

## Affected paths and contracts

- `src/erp_mcp_private_writer/private_ingress.py` — runtime-aware ASGI lifespan factory.
- `src/erp_mcp_private_writer/__init__.py` — public factory export.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — unprepared startup and listener-stop lifecycle acceptance.

## Verification state

An actual read-only `code-reviewer` pass checked startup-failure cleanup, listener shutdown order, imports and runtime-close sequencing; it found no concrete source-level finding. The agent launch did not expose exact model/effort metadata (`NOT_VERIFIED`). No tests, checks, build, SQL parse, migration, database operation, COM call, or runtime qualification ran. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; an operational writer, qualified auth providers, ASGI host binding and two-process Windows execution remain absent or unverified.
