# ERP_MCP — Secure, Read-Only AI Gateway for 1C

[**Overview**](#overview) · [**Installation**](docs/INSTALLATION_GUIDE_RU.md) · [**Lessons Learned**](docs/LESSONS_LEARNED_RU.md) · [**Phase 2**](docs/phase2/README.md)

> **One project.** ERP_MCP is a single repository: the read-only 1C gateway and the living-model, connector and reconciliation work (formerly tracked as "Release 1" and "Release 2 / Phase 2") were merged on 2026-10-20. Some directories and packages still carry the historical `phase2` name; renaming them is a planned separate refactor.
>
> **Status: NO-GO for general production use.** The gateway is implemented and acceptance is still in progress. The living-model, connector and reconciliation modules are a local, non-production prototype (see "Status" below).

ERP_MCP provides governed, auditable access to 1C systems through the [Model Context Protocol](https://modelcontextprotocol.io/). Its goal is **reliable accounting answers within explicit access boundaries**, not unrestricted AI access to databases. The public read-only MCP data plane is separate from administrator operations. A shared connector/control architecture for additional systems is planned.

## Overview

**ERP_MCP** is an MCP gateway for secure, read-only access to multiple **1C:Enterprise** databases. Users and AI clients can access only authorized sources and organizations. The gateway enforces identity, access control lists (ACLs), capability checks, query limits, and audit requirements. Specific accounting answers are available only when the semantic profile is confirmed and independently reconciled against native 1C reports.

The **living-model track** (code under `phase2` paths) adds a continuously updated model of connected sources, change history, additional connectors, governed automated reconciliation, and a workbench for investigating discrepancies. **These capabilities are under development** and must not be presented as released features.

### Capability Status

| Capability | Gateway (read-only 1C MCP) | Living-model track |
| --- | --- | --- |
| Authorized 1C sources, organizations, and grants | Core control-plane mechanisms implemented; acceptance is environment-specific | Inherits the gateway access boundaries and must not bypass them |
| Read-only OData v3, metadata, and capability routing | Routes and protective contracts implemented; actual profiles require validation | Fine-grained observations and per-object capability changes **WIP** |
| MCP tools and semantic accounting | Tools with exact-profile gates; support depends on configuration and native evidence | Extended validated operations planned **WIP** |
| Admin Control Center, audit, and limits | Gateway components are being implemented and verified; the overall release gate is open | Job, connector, and workbench administration **WIP** |
| Real 1C, COM, and RSV fallback | Limited, validated, metadata-first path; dangerous business queries are blocked | Qualified native-report capture **WIP** |
| Independent reconciliation with native 1C reports | Mandatory for trustworthy amounts and release approval; L1 does not substitute for it | Governed capture, comparison, and independent attestation **WIP** |
| Living Model Registry, PDM/LDM, taxonomy | Not shipped in the gateway runtime | **In design and development; not production-ready** |
| Bitemporal history, diff/impact graph, adaptive jobs | Not claimed as gateway features | **WIP**, with separate validation gates |
| Additional sources (for example, Drive) | Adapter boundaries reserved only; not connected out of the box | Connector framework and provider-specific qualification **WIP** |
| Overall production approval | **NO-GO until required gates close** | **NO-GO / WIP** |

**P0–P10** in the [Master Plan](docs/MASTER_PLAN.md) are engineering stages of the gateway. **S0–S10** (and later S11+) in `docs/phase2/` are the sprint roadmap of the living-model track. These are different progress scales and must not be conflated.

## Quick Start: Install from GitHub

**Recommended first run: the fully synthetic Fake1C environment, without a real accounting database.**

Prerequisites: Windows, Git, Python **3.12+**, [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker Desktop using Linux containers, and PowerShell 5.1 or 7.

```powershell
git clone https://github.com/xLZDx/ERP_MCP.git
Set-Location .\ERP_MCP
uv sync --locked --all-groups --extra dev
.\scripts\e2e\up.ps1 -Seed baseline
.\scripts\e2e\status.ps1
.\scripts\e2e\test.ps1 -Suite smoke
```

After successfully starting the synthetic environment:

- Gateway health: [http://127.0.0.1:18000/healthz](http://127.0.0.1:18000/healthz)
- Admin UI: [http://127.0.0.1:18000/admin/](http://127.0.0.1:18000/admin/) (test identity provider)
- MCP endpoint: `http://127.0.0.1:18000/mcp` (not an HTML website)

To stop **only your own** disposable environment, run `.\scripts\e2e\down.ps1`. Do not use `-Purge` unless you understand that it removes disposable data and volumes.

**Complete step-by-step guide:** [Installation Guide](docs/INSTALLATION_GUIDE_RU.md), including prerequisites, Python and infrastructure setup, a real test 1C instance, ACLs, OData, ChatGPT integration, troubleshooting, and production checklists.

**Past issues and documented limitations:** [Lessons Learned](docs/LESSONS_LEARNED_RU.md).

### Development-Only Gateway (without the full E2E environment)

```powershell
Copy-Item .env.development.example .env
uv sync --locked --all-groups --extra dev
docker compose -f compose.development.yml up -d postgres redis
uv run --locked python scripts/migrate.py
uv run --locked python scripts/doctor.py
uv run --locked uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
```

This development profile can contain demonstration secrets and exposes local development ports. It is **not** a production deployment. Connect real sources only according to the [installation guide](docs/INSTALLATION_GUIDE_RU.md) and the [production security contract](deploy/PRODUCTION.md).

## What the Gateway Provides

### Read-Only MCP Data Plane

- Governed list of sources and companies, source/company ACLs, and strict OAuth/OIDC verification in a secured environment.
- Metadata and capability negotiation based on actual 1C behavior; OData v3 and a private pinned adapter/sidecar.
- Limits on rows, responses, filters, execution time, queries, and network addresses. Requests target only pre-registered sources.
- Read-only tools: `system_status`, `sources_list`, `companies_list`, `source_health`, `onec_capabilities`, `onec_metadata_summary`, `onec_find_entities`, and `onec_read`.
- Semantic accounting operations (including balances and turnovers, sales and purchases, cash and inventory, receivables and payables) **only where exact mappings, capabilities, and native evidence are confirmed**. A tool's presence in source code does not imply it is enabled for every database.

### Security, Administration, and Operations

- Separate Admin Control Center and role/grant management. Administrator mutation APIs are **not** exposed as public MCP tools.
- PostgreSQL source registry, grants, mandatory audit, Redis rate limits, secret providers, and separate database roles.
- Testing ladder: **Fake1C synthetic environment (L1) → authorized disposable real 1C test instance (L2) → production-parity environment (L3)**.
- Restricted private Windows/COM fallback for supported use cases; never an unrestricted AI SQL/COM execution channel.
- Observability, fault/restore, and release-evidence procedures. Production approval depends on closing security, accounting accuracy, and operations gates.

See [Security](SECURITY.md), [Architecture](docs/ARCHITECTURE.md), [Master Plan](docs/MASTER_PLAN.md), [Test Strategy](docs/TEST_STRATEGY.md), and [Release Operations](docs/RELEASE_OPERATIONS.md).

## Living-Model Track (`phase2` paths) — Work in Progress

- Connector SDK and secure source integrations with separate permissions and secret references.
- **Living Model Registry:** observed and accepted schema, PDM/LDM, taxonomy, and canonical fingerprints.
- PostgreSQL temporal/event history, compare-and-swap, leases, cursors, and conservative change impact analysis.
- Adaptive metadata monitoring that distinguishes *source unavailable* from *schema drift*.
- Genuine native 1C report capture with verified provenance, independent attestation, and automated comparisons within approved scopes.
- A workbench for history, discrepancy explanations, authorized reruns, and exception handling.
- Incremental support for external providers, only after provider-specific permission, revocation, and load gates.

**This is a roadmap and experimental engineering work, not a promise that these features are available after cloning `main`.** Production native capture requires separate approval for the exact 1C database, company, capture procedure, and execution window.

References: [Living-model track README](docs/phase2/README.md), [Technical Design](docs/phase2/TDD_PHASE2_RU.md), [S0–S10 Roadmap](docs/phase2/PLAN_PHASE2_RU.md), and [Acceptance/Test Plan](docs/phase2/TEST_PLAN_PHASE2_RU.md).

## ChatGPT / Secure MCP Tunnel

Windows launchers are provided for connecting an isolated **Fake1C** demonstration to ChatGPT:

```powershell
.\scripts\chatgpt\up.ps1
.\scripts\chatgpt\doctor.ps1
.\scripts\chatgpt\install-tunnel-client.ps1
```

This endpoint is deliberately **test-only**. OAuth is disabled **only** for synthetic data. A real database requires production OAuth, private networking, genuine grants, and approved native evidence. See [ChatGPT ↔ ERP_MCP Integration](docs/CHATGPT_MCP_INTEGRATION.md) and the [ChatGPT Runbook](docs/ERP_MCP_CHATGPT_RUNBOOK_RU.md).

## Verified Fresh Installation (October 9, 2026)

On an existing Windows 11 engineering workstation, a fresh `git clone main` was executed, dependencies installed, and separate PostgreSQL/Redis and test-only gateway instances started. A real 1C instance responded to an authorized `$metadata` request. After the correct test bootstrap role and source grant were configured, **7/7 MCP ACL/metadata smoke checks passed**.

**This is not L3/production approval and not proof of installation on a new physical computer.** See the [actual L2 verification report](reports/FRESH_INSTALL_REAL1C_VERIFICATION_2026-10-09.md).

## Additional Documentation

| Topic | Link |
| --- | --- |
| Normative document index and requirement precedence | [docs/DOCUMENT_INDEX.md](docs/DOCUMENT_INDEX.md) |
| Detailed installation instructions | [docs/INSTALLATION_GUIDE_RU.md](docs/INSTALLATION_GUIDE_RU.md) |
| Historical issues and lessons learned | [docs/LESSONS_LEARNED_RU.md](docs/LESSONS_LEARNED_RU.md) |
| Real test environment and L1/L2 | [docs/E2E_ENVIRONMENT.md](docs/E2E_ENVIRONMENT.md) |
| ChatGPT integration | [docs/CHATGPT_MCP_INTEGRATION.md](docs/CHATGPT_MCP_INTEGRATION.md) |
| Windows 1C/COM bridge | [docs/runbooks/RSV_DATA_BRIDGE.md](docs/runbooks/RSV_DATA_BRIDGE.md) |
| Production deployment and rollback | [deploy/PRODUCTION.md](deploy/PRODUCTION.md) / [deploy/ROLLBACK.md](deploy/ROLLBACK.md) |
| Living-model track, formerly Phase 2 (WIP) | [docs/phase2/README.md](docs/phase2/README.md) |
| Engineering Command Center | [docs/ERP_MCP_ENGINEERING_COMMAND_CENTER.html](docs/ERP_MCP_ENGINEERING_COMMAND_CENTER.html) |
| Upstream reuse and third-party licensing | [vendor/UPSTREAMS.md](vendor/UPSTREAMS.md) / [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

**Release rule:** Working code does not equal a tested deployment, accounting evidence, or formally approved production release.

## Status of the Living-Model Track

The living-model track is **NO-GO**. It is a local, non-production prototype. The current gate manifest records G0 as passed for its narrow approved scope, G1–G8 as not passed, S13 as not started for formal entry, and production authorization as none. Local prototype evidence does not establish real 1C behavior, deployment readiness, or release approval. Details and the handoff: [docs/phase2/S10_RELEASE_HANDOFF.md](docs/phase2/S10_RELEASE_HANDOFF.md); extraction provenance: `docs/phase2/EXTRACTION_NOTE.md`.

The S12 Contract Freeze v2.0 local synthetic implementation is pushed through `705076adaf7e367921812e60a5b1ea13a41107de` (initial synthetic scope: `CREATE_DRAFT`, `POST` and `UNPOST` for purchase receipts). CR123 records 7/7 focused functional tests, 1/1 focused E2E scenario and independent reviews with no BLOCKER/MAJOR, with synthetic-only limits. This does not authorize real COM calls or production use.

## Layout

- `src/business_ai_gateway/` - gateway; `src/business_ai_gateway/phase2/` - living-model modules (package name kept so imports stay stable)
- `tests/`, `tests/phase2/`, `tests/gate_manifest/`, `tests/testlane/` - tests
- `db/phase2/` - PostgreSQL migrations of the living-model track
- `docs/phase2/` - design, plans, decision records, spec bundle
- `scripts/phase2/`, `scripts/phase2_capacity_drill.py`, `scripts/remote/` - tooling
- `testlane/` - local test lanes (1C extension, phase2 MCP)
- `core/DECISION_LOG.md`, `core/LESSONS_LOG.md` - project decision and lessons logs

## Verification and Evidence

Required focused tests are authored and run by the designated test agents after in-scope coding is complete. Harnesses, exact revisions, commands and results are recorded in the linked change records and gate evidence plans. Do not treat a process exit code alone as a passing result: `NOT_RUN`, `SKIP`, missing terminal evidence or an unavailable dependency is not `PASS`. A `PASS` requires explicit terminal PASS evidence correlated to the exact revision and completed harness. Current state and remaining formal acceptance: `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md` and `governance/GATE_MANIFEST.json`.
