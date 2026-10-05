# ERP_MCP skills and operating playbook

## Required skills for changes

- **Repository reconnaissance:** inspect `docs/DOCUMENT_INDEX.md`, the relevant ADRs, current git
  status, and existing tests before editing.
- **Security review:** check auth, ACL, SSRF, secret handling, read-only guarantees, audit, and
  fail-closed behavior for every request-path change.
- **1C compatibility:** use behavior-first capability discovery and live metadata; do not infer
  business semantics from platform/configuration names.
- **Upstream reuse:** consult `vendor/UPSTREAMS.md` and `docs/ADAPTER_INTAKE_PLAN.md` before adding
  OData, register, COM, or native-query behavior.
- **Evidence-driven testing:** distinguish Fake1C tests, real file-mode 1C evidence, and server-mode
  production-parity evidence.

## Change checklist

- Identify change class C0-C4 in `docs/GOVERNANCE.md`.
- Link the change to requirements in `docs/REQUIREMENTS_TRACEABILITY.md`.
- Add tests and stable error behavior.
- Update normative documentation when an invariant, contract, schema, or deployment rule changes.
- Record upstream repository, pinned SHA, license, and reuse mode for imported behavior.
- Verify no credentials or raw customer data entered the repository.

## Release language

Use `DEV READY`, `INTEGRATION READY`, `PILOT READY`, or `PRODUCTION GO` only according to
`docs/DEFINITION_OF_DONE.md`. Unit tests alone never justify a production claim.
