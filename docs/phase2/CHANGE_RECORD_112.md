# Change record 112 — enforce Ed25519 at action evidence consumption

## What changed

- Added forward-only migration `db/phase2/021_ed25519_consumer_cutover.sql`, requiring recorded migrations 001–020.
- Required Ed25519 signer keys in the shared `evidence_ref` action helper while preserving the read-only historical `read_evidence` path.
- Validated the evidence referenced by stored witness cosigns before `operator_resolve` and `operator_close_failed_verify` consume them; scoped `operator_resolve` observation lookup.
- Scoped the internal completion refusal-evidence lookup by tenant, company, change, evidence ID, and Ed25519 signer.
- Bound permit signature lookup and update to the owning record's tenant and company.
- Updated the R-03 design note with the security finding, chosen approach, compatibility limits, and test acceptance.

## Why

Migration 019 stopped new legacy-signed evidence from being recorded, but a valid row recorded before cutover could still authorize later state transitions. The permit signature function also lacked a tenant/company relationship between the requested scope and the global permit row. Migration 021 closes both paths without changing historic evidence or making it unavailable to audit reads.

## Decisions and limits

- Preserve `signature_ok` and immutable historical rows; enforce the algorithm rule where evidence is consumed to change state.
- Resolve the evidence signer's algorithm through the scope-matched verifier key. Normal runtime key registration is immutable; privileged owner-level direct mutation is outside this local runtime prototype and remains a formal R-03 provenance/custody concern.
- Keep this migration local and non-gating. It does not establish deployed-key inventory, production writer safety, formal R-03 closure, G1–G8 passage, S13 approval, or production authorization.
- The migration is forward-only after application; a rollback to unguarded functions would reopen the finding.

## Affected paths and contracts

- `db/phase2/021_ed25519_consumer_cutover.sql`
- `docs/phase2/R03_ED25519_NEW_ACTION_DESIGN.md`
- `change_ledger.evidence_ref`: action evidence requires a scoped Ed25519 signer.
- `change_ledger.assert_ed25519_cosign_evidence`: stored witness proof must reference a same-scope Ed25519 completion proof.
- `change_ledger.operator_resolve` / `consume_two_person_cosign`: legacy evidence cannot authorize recovery transitions.
- `change_ledger.complete`: refusal evidence lookup is scoped and Ed25519-gated.
- `change_ledger.attach_permit_signature`: permit digest and mutation are bound to the scoped parent record.
- `read_evidence`: historical audit access is unchanged.

## Verification state

- Functional regression tests for migration 021 and the migration 019 write boundaries: PASS. Command: `.venv\\Scripts\\python.exe tests\\phase2\\test_r03_migration019.py` (exit 0), on worktree based at `19605848b8fb760d7aaac93395db2d13f1577a61`. A legacy row was seeded before 015; after 021, `complete_signed`, `resolve_unknown_signed`, `operator_resolve`, and `operator_close_failed_verify` refused its use without state mutation. Historical `read_evidence` remained available; cross-tenant permit attachment was rejected without mutation and the in-scope control succeeded.
- End-to-end dispatch/action journey: PASS, same focused command and worktree base. Through `SqlChangeLedger` and disposable PostgreSQL, legacy completion was rejected with `EVIDENCE_UNSIGNED`, record state and event count stayed unchanged, historical auditor read succeeded, and a fresh Ed25519 completion reached `APPLIED`.
- Runtime container: owned `postgres:16` containers, image digest `sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae`; exact-name post-run checks found no remaining containers. Harnesses verified owner labels before cleanup and removed anonymous volumes.
- Fresh database and security reviews: pending after test evidence.
- No primary-agent tests or database commands were run.

## Commit linkage

This file is the dedicated detail record for the commit containing migration 021 and its acceptance tests. The generated document registry must include this record in that commit.
