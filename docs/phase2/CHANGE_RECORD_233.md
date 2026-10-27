# Change Record 233 — inspect composition methods without invoking descriptors

## What changed

- Added `dependency_shape.has_static_callable_method()` using `inspect.getattr_static()` and applied it to private writer composition, authentication/authorization, outcome/trust/build-provenance adapters, and T16 recovery dependency validation.
- Extended `S13-OPERATIONAL-WRITER-COMPOSITION-01` and added `S13-STATIC-DEPENDENCY-SHAPE-01` to require rejection of property-backed methods and dynamic `__getattr__` providers without evaluating them.

## Why

Constructors for the private writer's injected collaborators promise to validate dependency shape before doing work. Dynamic attribute access can execute arbitrary dependency code: a property named like a required method or a custom `__getattribute__`/`__getattr__` could run I/O while shape validation was still deciding whether to accept the dependency. Static lookup reads the declared member without binding its descriptor. Ordinary methods remain callable for this shape check; descriptors and dynamic-only providers are rejected without execution.

This remains a shape guard, not authentication of a dependency, deployment, host, build or key. It does not make the S13 runtime ready and does not replace database authorization or the durable COM-entry CAS.

## Baseline and provenance

The repository had extensive staged, unstaged and untracked work before this change. `runtime_composition.py` and the qualification prerequisite document were already untracked at turn start; their full contents and prior state were preserved. The observed pre-edit SHA-256 values immediately before this focused change were:

- `src/erp_mcp_private_writer/runtime_composition.py`: `222C53CD042CE599EB4AA4BD76E9C0946F40E2F3331DEC3EDAD43084142CE8A7`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `F4ACC1F3A67EC3F87D589A5A0E80FCA227018CDA2884226B3D68C1899AF83776`
- Additional source files were already dirty or untracked. Their pre-edit hashes observed in this turn were: `private_auth.py` `9784101A9E24A115FFE7789A73563FFD23D13A7D2628E9AFC8CBDDABC71777E5`; `private_authorization.py` `0F1B0A543729A36634476442D97A48917FC35DBD7FF9A30FE455D75809E9DCDA`; `postgres_outcome_provider.py` `BCD1AD395AE7F8525759B1BB726656ED9D38E31D007987A74B9AE0D49D1361FA`; `production_evidence_verifier.py` `5F6FEE98F998237274889EA3C5A9501D5BD8C7ED300BB21093ECCB8F8E4BE7F9`; `postgres_evidence_registrar.py` `CB1850C2B8ACD09C919FC6B11727BBE6A4842C4AD616102E7C5F234142A394CD`; `t16_recovery.py` `0C62015A72C838B56FB6487D79B133141CEBCBFA5F13D94FEB75E0D7A997088C`.

Only the shared static method-shape helper, its adoption by the listed constructor/composition boundaries, the candidate qualification cases, and this record are attributable to this turn.

## Verification state

- **Code:** implemented; no tests, checks, build, SQL parse, migration, or runtime composition was run.
- **Source review:** a fresh-context `code-reviewer` agent reviewed the exact scoped working-tree change based on HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`, role model GPT-6 Luna at low effort. It reported no material correctness, compatibility, or import-cycle finding. This is source review only; the requested getter-sentinel qualification remains `NOT_RUN`.
- **Qualification:** `NOT_RUN`; functional-test-reviewer owns execution after all in-scope coding closes. The required case must use getter sentinels to prove descriptor and dynamic lookup hooks are never evaluated, in addition to the existing writer-marker and no-I/O controls.
- **Runtime and grants:** remain unverified. Earlier current-turn evidence in Change Record 232 describes the read-only PostgreSQL catalog result and sanitized remote COM connection failure; this change made no additional database or remote calls.
- **PM Bridge:** exact request `6f21b048-45a3-4fd6-99bf-3767ad06622a` still cannot be reconciled: the read-only `pm_bridge_job_status` call in this turn returned `Transport closed`. Delivery/reply remains `UNKNOWN`; do not resend blindly and do not commit without a correlated approval. No staging, commit or push occurred.

## Affected contracts and ownership

- `src/erp_mcp_private_writer/runtime_composition.py`
- `src/erp_mcp_private_writer/dependency_shape.py`
- `src/erp_mcp_private_writer/private_auth.py`
- `src/erp_mcp_private_writer/private_authorization.py`
- `src/erp_mcp_private_writer/postgres_evidence_registrar.py`
- `src/erp_mcp_private_writer/postgres_outcome_provider.py`
- `src/erp_mcp_private_writer/production_evidence_verifier.py`
- `src/erp_mcp_private_writer/t16_recovery.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

Accountable owner: operator. Executor: Codex. The future qualification is owned by the designated functional/E2E roles. This guard does not remove the separate blockers for exact clone metadata, operational COM mapping, installed effective grants, trusted process/build identity, signer custody, or the writer transaction boundary.

## Next step

Continue source closure where a contract is established. After coding closes, have functional-test-reviewer and e2e-runner execute this composition case and the accepted S12/S13 matrix, then complete the applicable specialist reviews. Reconcile the existing PM Bridge request by status lookup when the transport is available; never create a duplicate request or local commit before its exact-head approval gate.
