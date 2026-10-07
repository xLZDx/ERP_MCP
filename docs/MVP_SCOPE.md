# 1C Day-1 / DAD Read-Only MVP Acceptance

**Baseline:** frozen 2026-10-06.
**Authority:** `SCOPE_FREEZE_BASELINE_2026-10-06.md`.

The MVP is production-ready only when the frozen committed scope and mandatory DoD gates pass.

- G1 Auth: unauthenticated/wrong issuer/audience/scope requests are denied.
- G2 Registry/ACL: add/revoke source/company access without code change or restart; 30–150+ company
  workflow remains bounded and auditable.
- G3 Secrets: no production credential stored in repository/env/model-visible payloads.
- G4 Read-only: production MCP/data planes expose no 1C mutation surface; test-only seed/write
  helpers are unreachable.
- G5 Compatibility: each source has persisted capability/metadata evidence and deterministic
  SUPPORTED / SUPPORTED_WITH_FALLBACK / UNSUPPORTED behavior.
- G6 Metadata: live metadata discovers actual published objects; drift invalidates affected semantics.
- G7 Limits: rows, bytes, timeout, filter/query complexity, per-source/global concurrency and rate
  limits are enforced.
- G8 Audit/provenance: principal/client/tool/source/company/outcome/duration/adapter/profile/evidence
  fingerprints are append-only without secret/raw-payload leakage.
- G9 Multi-company: ACL, same-source multi-company isolation, revoke and partial-failure behavior are
  proven; failed/denied companies are never silently omitted from totals.
- G10 Semantic accounting: account turnovers/postings, sales/purchases, inventory, cash/bank,
  receivable/payable/aging and other frozen semantic claims use exact validated profiles.
- G11 DAD assurance: six accountant-selected checks, invoice reconciliation, month-close rule packs,
  P&L/CF/BS and the accepted tax/payroll/bank/Z/terminal/customs/CCAC read-only precheck families
  reach their declared acceptance level.
- G12 External Evidence: already accepted external evidence classes are fingerprinted/provenanced;
  missing evidence returns EVIDENCE_REQUIRED/INCONCLUSIVE rather than guessed PASS.
- G13 Real-reference testbed: private REFERENCE_TEST_BASE_A is preserved as immutable golden source;
  disposable RO clone supplies exact configuration/native-report/known-error evidence.
- G14 Ferma synthetic assurance: deterministic scenario/oracle remains independent; test-only seeder
  posts normal 1C business documents only in marked disposable bases.
- G15 Accounting reconciliation: at least ten representative native-report cases pass per production
  semantic profile, with broader frozen DAD scenario coverage at its declared level.
- G16 Operations: health/readiness, migrations, least-privilege DB roles, supply-chain evidence,
  observability, failure injection, backup/restore/rollback and runbooks are complete.
- G17 Pilot/deployment: controlled target evidence, production identity/network/secrets and release
  approval satisfy D0–D18.

Recorded deferred lanes (legacy without a concrete target, future write product, production ERP/Ferma
adapters) remain frozen but are not silently promoted into this completion barrier.

No gate may be waived by switching production into a development profile.
No new product scope is admitted until the operator explicitly rebaselines the freeze.
