# Change record 326 — bind S13 production evidence composition

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator by explicit delegation; executor: Codex.
- `runtime_composition.py` already existed in the shared working tree before this increment; its
  earlier origin is not attributed here. This record covers only the current composition checks.
  The checkout also contains extensive pre-existing staged, unstaged, and untracked work.
- No database, COM, key, remote host, test, check, stage, commit, or push operation was performed.

## Change

`compose_private_writer_runtime()` previously accepted any objects implementing the receipt-verifier
and outcome-provider protocols. It now requires the concrete PostgreSQL receipt registrar and
outcome provider. The outcome provider must reference that exact registrar; the registrar's
attempt source and the evidence resolver must share the same pool, attempt-source object, and
production verifier; and this evidence pool must differ from the admission pool. This prevents a
composition from pairing unrelated evidence providers or using in-memory/duck-typed substitutes at
the production runtime boundary. The provider's bundle source remains a locator for signed bytes,
not a trust authority; the registrar/verifier graph validates and persists those bytes. This narrows
but does not close GPT-PM finding M-04: the repository still has no authenticated
`ValidatorBuildProvenanceSource` implementation, so operational build provenance and private-writer
service identity remain unbound and runtime activation is unavailable.

Added acceptance `S13-EVIDENCE-PROVIDER-COMPOSITION-01` to
`S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. It requires the exact-type and
dependency-identity matrix to refuse before any pool acquisition, with effective session identity
and role checks owned by database review. Runtime credentials, host build provenance and live
database identity remain outside this composition check.

## Verification state

- Source review only: imports and immutable adapter attributes were checked against the concrete
  constructors. No tests/checks were run during this coding increment.
- Source SHA-256 for `src/erp_mcp_private_writer/runtime_composition.py` after this increment:
  `955EBA2B93CF6AD4BEA2C2A22C133D14F38E228C3A1186865F591776B4E4F6A8`. This identifies dirty
  worktree bytes, not a committed revision.
- `functional-test-reviewer` added `tests/phase2/test_s13_evidence_provider_composition.py` and
  ran `uv run pytest -q tests/phase2/test_s13_evidence_provider_composition.py`: **9 passed in
  1.03 s**. It covers accepted graph traversal to the later operational-writer guard, fake provider
  refusals, mismatched registrar/pool/attempt-source/verifier links, shared admission/evidence pool
  refusal, and zero pool acquisitions. Test SHA-256:
  `F17463E3B1130FEB7DCE52C8D51232DC6A176AF19C4D965209690CDCA5D58246`.
  Its first run had 9 fixture failures because spy-pool instrumentation fields were forwarded as
  composition keyword arguments. The second had 2 fixture failures because invalid graphs violated
  adapter-constructor invariants before reaching the composition checks. The test owner corrected
  both fixtures to isolate the intended composition conditions; no product-source defect was
  reported.
- `e2e-runner` ran `uv run pytest -q tests/phase2/test_s13_barrier_ack_service_e2e.py`:
  **4 passed in 0.45 s**. Test SHA-256:
  `90D6B61566365A17D0AE5336963C755CCD458FD39EA0A2A3E6B2115B9CB36337`. This is an in-memory
  service journey, not PostgreSQL/COM/1C integration.
- Runtime composition acceptance has only focused unit-level functional evidence; no production
  runtime was constructed.
- Focused read-only Python review found no actionable correctness issue. Database and security
  reviewers found no pool-graph bypass, but both confirmed the existing MAJOR M-04 dependency:
  `PostgresWriterReceiptRegistrar` still accepts a duck-typed
  `ValidatorBuildProvenanceSource`, and no authenticated implementation exists in the repository.
  Security review also confirmed `writer.operational=True` is only an accidental-misconfiguration
  marker, not proof of a real COM implementation. No effective grants, trusted build identity, or
  physical writer boundary are established by this source increment.
- Authenticated build-attestation source, service identity binding, real registry material and
  effective grants remain `NOT_VERIFIED`/`NOT_RUN` and are not supplied by this composition change.
- No GPT-PM approval, effective grants, operational writer, production boundary, or commit is
  claimed.

## Next steps

1. Codex: finish remaining source-backed S13/WP5 work without removing the legacy fail-closed
   guards.
2. Functional-test reviewer: after code closure, execute the composition acceptance matrix and
   linked regressions.
3. Database reviewer: inspect exact pool identity/session-role assumptions against the disposable
   candidate; measure effective grants only after applying it to an approved disposable database.
4. GPT-PM: review the exact final code and evidence before any push/PR gate.
