# Requirements Traceability Matrix

**Version:** 1.1
**Date:** 2026-10-06

This matrix connects requirements to architecture, implementation areas and release gates.

| Req | Requirement | Primary design | Evidence / DoD |
|---|---|---|---|
| FR-A1 | OAuth identity validated | TDD §6, Architecture TB-1 | D2 |
| FR-A2 | Subject/group source and company authorization; deny takes precedence | Data Model §5, Integration §9 | D3, D10 |
| FR-A3 | Revocation without restart | PostgreSQL grants/runtime lookup | D3, D10 |
| FR-B1 | Server-side source registry | Data Model §3 | D3, D10 |
| FR-B2 | Secrets are references only | Data Model §3, Security | D4 |
| FR-C1 | Behavior-first capability discovery | ADR-0004, Compatibility | D7 |
| FR-C2 | Metadata fingerprint/drift | Data Model §7–8 | D7, Test Strategy §6 |
| FR-D1 | Bounded entity/query reads | Integration §3 | D8 |
| FR-D2 | Register virtual-table reads | Integration §3.2 | D8 |
| FR-D3 | Native query fallback read-only | Integration §3.3 | D5, D8 |
| FR-E1 | Semantic tools are transport-independent | Architecture §7 | D9 |
| FR-E2 | No universal chart-of-accounts assumption | Data Model §9 | D9 |
| FR-F1 | Append-only audit with request/company/adapter provenance | Data Model §11, Security | D11 |
| NFR-S1 | Production fail-closed | TDD §5 | D2–D6, D16 |
| NFR-S2 | No arbitrary target URL | ADR-0001/Architecture TB-1/5 | D6 |
| NFR-S3 | No 1C mutations | ADR-0001 | D5 |
| NFR-S4 | No direct internal 1C SQL | ADR-0005 | architecture review |
| NFR-L1 | Reuse-before-rewrite | ADR-0003, Adapter Intake | D0/D1 vendor evidence |
| NFR-L2 | Copyleft isolation | ADR-0006 | vendor policy CI |
| NFR-R1 | Source failure isolated | Architecture §9 | D10, D14 |
| NFR-R2 | Safe timeout/retry/circuit behavior | Integration/Architecture | D8, D14 |
| NFR-O1 | Structured logs/metrics/traces | Observability | D12 |
| NFR-O2 | Backup/restore/rollback | Observability §9–10 | D15 |
| NFR-O3 | Bounded DNS resolution and deployment egress | Network policy / Production contract | D6, D16 |
| NFR-P1 | Bounded multi-company fan-out | Architecture §8 | D10, D13 |
| NFR-P2 | Measured performance before GO | Test Strategy §8 | D13 |
| COR-1 | Accounting reconciliation with native 1C | TDD §3 G-05 | D9 |
| COR-2 | Drift invalidates affected semantics | Test Strategy §6 | D7/D9 |
| OPS-1 | Source onboarding handshake | Integration §9 | D10/D17 |
| OPS-2 | Source offboarding safe | Integration §10 | D17 |
| OPS-3 | Deterministic release preflight and non-destructive rollback manifest | Release Operations / Rollback runbook | D15–D18 |
| SCOPE-1 | No new product scope while operator freeze is active | Scope Freeze Baseline, Governance §2A | D0 + freeze closure |
| DAD-1 | Six accountant-selected read-only checks | DAD Requirements Coverage §8, DAD rule engine | D9 + DAD acceptance |
| DAD-2 | Invoice/e-factura read-only reconciliation | DAD Requirements Coverage §11/§27, External Evidence Plane | D9/D11 |
| DAD-3 | Versioned applicability-aware month-close rule packs | TDD FR-G, Data Model §10B | D9/D11 |
| DAD-4 | P&L / Cash Flow / Balance Sheet semantic reports | TDD G-07, semantic profiles | D9 |
| DAD-5 | Bank/Z/terminal/customs/CCAC reconciliation | TDD FR-H, Integration §13–14 | D9/D11 |
| DAD-6 | VAT/IPC/VEN and payroll prechecks require external evidence + human review | TDD G-07/FR-H | D9/D11 |
| EVID-1 | Missing external evidence never becomes guessed PASS | TDD FR-G/FR-H | D9/D11 |
| TEST-REF-1 | Private real-reference base used via immutable golden + disposable clones | Scope Freeze §3.6, DAD Coverage §22–34 | D5/D7/D8/D9 |
| TEST-FERMA-1 | Ferma synthetic scenario/oracle remains independent from 1C/ERP_MCP actual | TDD G-08, Ferma→1C Blueprint | D9 |
| P6-SEC-1 | RSV business query/reveal remain denied unless audited conditions are proven | RSV audit, Master Plan P6 | D5/D7 |
| FUT-ERP | Preserve ERP tenant/org RLS | Architecture §11 | future adapter DoD |
| FUT-FERMA | Preserve oracle independence | Architecture §11 | future adapter DoD |

## PR usage

Every feature PR should cite one or more requirement IDs and the DoD gate it advances. If a new
requirement has no row here, update this matrix as part of the same change.
