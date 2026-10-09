# ERP_MCP — Step-by-Step Installation Guide (Release 1)

**Audience:** Developers, administrators, and 1C system owners who have just downloaded [ERP_MCP](https://github.com/xLZDx/ERP_MCP).  
**Document date:** October 9, 2026.  
**Important:** Release 1 does **not** have blanket production approval. Phase 2 remains under development. Successfully installing a test environment does not authorize connecting customer production systems.

This guide distinguishes three environments:

1. **L1 — Synthetic Fake1C:** Recommended first run; no real 1C system or customer data.
2. **L2 — Your own authorized test 1C database:** Real OData/COM connectivity, a separate approved disposable database, and independent reconciliation with native 1C.
3. **L3 / production:** Hardened gateway, real IAM/ACL, network controls, secret management, and formal acceptance. This is **not a one-click deployment**.

> Do not use the OAuth-disabled demonstration profile with real data. Never direct reset, fault, purge, or test-seed scripts at an existing production database.

## 0. Architecture of the Installation

\`\`\`text
AI / MCP client
    | /mcp; OAuth/OIDC and ACL in a real environment
    v
ERP_MCP gateway -- PostgreSQL (registered sources, grants, audit)
    |            \-- Redis (rate limits)
    v
Read-only OData adapter / protected sidecar
    v
Approved 1C OData publication (HTTPS) -- read-only account
\`\`\`

The synthetic environment uses **Fake1C** in place of a real 1C database. Never confuse L1 functional verification with L2/L3 evidence of accounting accuracy.

## 1. Prerequisites

### Windows 10/11 — recommended first-run platform

- **Git:** \`git --version\` must work in PowerShell.
- **Python 3.12+:** \`py -3.12 --version\`. Follow \`pyproject.toml\` if the supported version changes.
- **uv:** Python environment manager with lock-file support, \`uv --version\`. See the [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
- **Docker Desktop:** Running in **Linux containers** mode; \`docker compose version\` works.
- **PowerShell 5.1 or 7:** The supplied E2E \`.ps1\` scripts primarily target Windows.
- **Free local ports:** The default stack uses \`15432\`, \`16379\`, \`18766\`, \`18767\`, \`18080\`, and \`18000\`. A separate ChatGPT demonstration uses \`18100\` and E2E port offset \`5000\`.
- **Chromium/Playwright:** Only when running browser E2E tests.

Verify these **before cloning**:

\`\`\`powershell
git --version
py -3.12 --version
uv --version
docker version
docker compose version
$PSVersionTable.PSVersion
\`\`\`

If \`docker version\` reports that the daemon is unavailable, start Docker Desktop first. **Do not continue until Docker is ready.**

### Linux and macOS

Python 3.12+, uv, Git, and Docker support the **basic development** path. Windows PowerShell E2E scripts, 1C COM, and the Windows RSV bridge are **not automatically cross-platform**. Use a separate supported Windows host for those features. Linux/macOS alone is not a verified replacement for the L2/COM testbed.

## 2. Clone ERP_MCP from GitHub

Open PowerShell **inside a new, empty directory** and run:

\`\`\`powershell
git clone https://github.com/xLZDx/ERP_MCP.git
Set-Location .\ERP_MCP
git branch --show-current
git status --short
git log -1 --oneline
\`\`\`

The normal onboarding route expects the \`main\` branch and an empty \`git status --short\`. Do not switch to \`phase2/*\` or \`integration/*\` for first-time setup. Development branches and open PRs do not guarantee a compatible, complete installation.

To update an otherwise **clean** clone:

\`\`\`powershell
git pull --ff-only origin main
\`\`\`

If Git reports local modifications, preserve them separately first. **Never use \`reset --hard\` or \`clean -fd\` as a generic repair command.**

## 3. Easiest Start: Fully Synthetic L1 on Windows

This setup configures local Docker/PostgreSQL/Redis, a test identity provider, Fake1C, the sidecar, the gateway, and isolated credentials. It requires **no real 1C data**.

\`\`\`powershell
# From the ERP_MCP repository root
uv sync --locked --all-groups --extra dev
.\scripts\e2e\up.ps1 -Seed baseline
.\scripts\e2e\status.ps1
.\scripts\e2e\test.ps1 -Suite smoke
\`\`\`

Wait until \`up.ps1\` completes. The ready stack normally exposes:

| Service | URL |
| --- | --- |
| Gateway health | \`http://127.0.0.1:18000/healthz\` |
| Gateway readiness | \`http://127.0.0.1:18000/readyz\` |
| MCP endpoint | \`http://127.0.0.1:18000/mcp\` |
| Test Admin UI | \`http://127.0.0.1:18000/admin/\` |

\`/mcp\` is a protocol endpoint, **not a normal HTML web page**. HTTP 200 from \`/healthz\` alone does not prove access to a real 1C system or independently reconciled accounts.

Parameters and randomly generated local secrets are stored under the **Git-ignored** \`.e2e/\` directory. Never share \`.e2e/credentials.json\`, \`.e2e/env.ps1\`, or terminal access tokens.

### Optional browser E2E testing

\`\`\`powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\scripts\e2e\test.ps1 -Suite user
.\scripts\e2e\test.ps1 -Suite admin
\`\`\`

See [E2E Environment](E2E_ENVIRONMENT.md), [Manual User Acceptance](MANUAL_ACCEPTANCE_USER.md), and [Manual Admin Acceptance](MANUAL_ACCEPTANCE_ADMIN.md) for the complete test matrix and expected external restrictions. **Skipped is not passed.**

### Safe shutdown

\`\`\`powershell
.\scripts\e2e\down.ps1
\`\`\`

Do not use \`-Purge\` unless you have explicitly decided to delete **only the disposable** test data; it removes the environment's data and volumes. \`reset.ps1\` also recreates the test schema. Do not execute it without understanding the target.

## 4. Alternative: Development Gateway Without Full E2E

For a Python server and core infrastructure without the full suite:

\`\`\`powershell
Copy-Item .env.development.example .env
uv sync --locked --all-groups --extra dev
docker compose -f compose.development.yml up -d postgres redis
docker compose -f compose.development.yml ps
uv run --locked python scripts/migrate.py
uv run --locked python scripts/doctor.py
uv run --locked uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
\`\`\`

This is **local development**, not a production configuration. \`compose.development.yml\` exposes PostgreSQL on \`5432\` and Redis on \`6379\`; use it only on a trusted workstation with appropriate firewall rules. \`.env.development.example\` includes demo values that are unsafe for production. Check port and credential conflicts. Use a separate working directory; do not place this stack on top of someone else's test environment.

After starting:

\`\`\`powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8000/readyz -UseBasicParsing
\`\`\`

For full verification of separate database roles and the test Admin UI, use the [Manual QA and Environment Guide](QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md), not shared development credentials.

**Linux/macOS:** The corresponding Python/Docker path may work with \`cp\`, \`uv sync\`, and \`uv run\`; do not blindly reuse Windows \`.ps1\` commands.

## 5. Connect Your Own Test 1C Database (L2, Owner Authorization Required)

This is a **separate procedure**, not an extension of the synthetic environment. Confirm that you own or administer an **approved disposable copy** of the 1C database.

1. Prepare a separate 1C 8.3 database for testing. **Do not run tests against a business production database or give the gateway write permissions.**
2. Configure the standard OData publication (\`/odata/standard.odata\`) with **HTTPS** and a least-privilege account. Restrict it to approved gateway hosts. Check \`$metadata\` **manually from an authorized network**, without disclosing credentials.
3. Register the exact permitted hostname and CIDR ranges. Production requires network-layer egress control and connect-time DNS validation; a hostname allowlist alone is not a firewall.
4. Provision credentials through an approved secret provider using **secret references**, not passwords in Git, prompts, URLs, reports, or command-line arguments.
5. Start the gateway, migrations, and private read-only OData sidecar according to the [production contract](../deploy/PRODUCTION.md) and [OData sidecar adapter contract](ADAPTER_CONTRACT_ODATA_SIDECAR.md). For local real-1C E2E, use its [dedicated profile](E2E_ENVIRONMENT.md#real-local-1c-profile-e2e_real1c1): it requires distinct \`E2E_SOURCE_ALLOWED_HOSTS\`, \`E2E_SIDECAR_URL\`, and \`-Seed bootstrap-only\`, **not** Fake1C \`baseline\`.
6. Register the source through the **operator CLI**. Example with preprovisioned secret references:

   \`\`\`powershell
   uv run --locked python scripts/admin.py source-upsert \`
     --source-id sample-1c-l2 \`
     --display-name "Test 1C" \`
     --base-url https://onec-test.example.org/demo/odata/standard.odata \`
     --username-secret sample-1c-l2-user \`
     --password-secret sample-1c-l2-password
   \`\`\`

   These hostnames and secret references are **placeholders**, not a live service. This command does not create secret entries or issue grants. The production administrator uses a separate \`BAG_ADMIN_DATABASE_URL\` and role.

7. First register the verified company, then issue the **minimum necessary** grant to a validated OAuth subject:

   \`\`\`powershell
   uv run --locked python scripts/admin.py company-upsert \`
     --company-id <approved-uuid> \`
     --source-id sample-1c-l2 \`
     --external-ref <exact-1c-organization-id> \`
     --display-name "Test company"

   uv run --locked python scripts/admin.py grant-add \`
     --principal <oidc-subject> \`
     --source-id sample-1c-l2 \`
     --company-id <approved-uuid>
   \`\`\`

   **Release 1 limitation:** Company-scoped grants support discovery, but generic \`onec_read\` requires a source-wide grant unless a specific semantic adapter proves company scoping. **Never widen grants merely to make a request succeed.** Use the approved company-scoped semantic operation or stop.

8. Validate metadata, capabilities, and ten independent standard 1C reports for the actual source, company, and configuration. If the profile is \`UNVALIDATED\`, genuine native evidence is missing, or access has expired, **block the action** instead of guessing values. See [Semantic Profiles](SEMANTIC_PROFILES.md), [Native Report Capture](NATIVE_REPORT_CAPTURE_RUNBOOK.md), and [MVP Acceptance](MVP_SCOPE.md).

### Verified Real-1C Testbed: Separate Auditor Grant (L2/E2E Only)

The historical **disposable** real-1C environment used \`E2E_REAL1C=1\`, \`-Seed bootstrap-only\`, and the correct \`E2E_DIR\`. \`scripts.real1c.lane_setup\` registers the test source and independently provisions a **data-plane source-wide grant** to \`auditor\` **only for \`onec-818ha-reference\`**. An administrative \`AUDITOR\` role does **not** automatically confer source read access. Other source IDs do not receive the grant.

A previously seeded disposable environment can use the idempotent repair:

\`\`\`powershell
$env:E2E_DIR = 'PATH_TO_YOUR_DISPOSABLE_REAL1C_E2E_DIR'
python -m scripts.real1c.lane_setup --repair-auditor-grant
python -m scripts.real1c.verify_install
\`\`\`

\`verify_install\` is read-only. It checks two positive real-1C calls, five negative ACL scenarios, and the corresponding audit evidence. Success is reported as \`REAL1C_L2_INSTALL_SMOKE 7/7 PASS\`. The script refuses execution outside the disposable loopback profile.

**Never use this routine to provision arbitrary customer sources or production access.** It is limited to the \`test/real1c/bootstrap-only\` profile and uses the Admin API instead of directly updating database ACL rows.

During a first run from a remote/noninteractive Windows PowerShell environment, \`ComSpec\` may be absent. The shared E2E helper now verifies the \`%SystemRoot%\System32\cmd.exe\` path and sets the child-process path correctly. This does **not** justify relaxing global security settings.

The measured results from a clean clone on an **existing Windows workstation** are documented in the [October 9 verification report](../reports/FRESH_INSTALL_REAL1C_VERIFICATION_2026-10-09.md). Genuine 1C connectivity and **7/7** source-level MCP ACL/metadata checks were verified. Native accounting reconciliation, installation on a new physical computer, and production Unix deployment were **not** verified.

### Optional COM / RSV Bridge on Windows

COM is a separate, more sensitive option for certain supported 1C configurations. It requires a properly licensed 1C installation and \`V83.COMConnector\`; Windows can use the official per-user registration procedure. Consult the [RSV Data Bridge Runbook](runbooks/RSV_DATA_BRIDGE.md) and [Local Configuration Handoff](../reports/LOCAL_1C_SETUP_HANDOFF.md).

**Do not assume that** \`execute_query\`, \`reveal\`, generic business queries, or exposing an upstream RSV MCP endpoint is safe. Until immutable company boundaries and zero-write guarantees are proven, unsupported COM business operations must remain \`CAPABILITY_UNSUPPORTED\`.

### Later Unix/Linux Gateway (Windows/1C Stays Separate)

After an approved Windows L2 smoke test, **do not move the COM/RSV bridge to Linux**. Deploy only the ERP_MCP gateway and its dependencies on Linux/Unix. Connect to the already authorized 1C publication through a separate private TLS/VPN network.

This requires approved host/SSH access, network ACLs, a browser-accessible production identity provider, TLS certificates, a runtime secret provider, separate PostgreSQL roles, and independent acceptance. \`E2E_REAL1C=1\` is a Windows test profile, **not** a production Unix guide.

A local Windows check does not validate a Unix deployment. Without an exact approved target, do not claim the stage is complete or promise production GO. Follow the [Production Runbook](../deploy/PRODUCTION.md) and [Rollback](../deploy/ROLLBACK.md).

## 6. Connect ChatGPT (Isolated Synthetic Example Only)

To verify MCP integration **without real customer data**, use a clean Windows clone:

\`\`\`powershell
.\scripts\chatgpt\up.ps1
.\scripts\chatgpt\doctor.ps1
.\scripts\chatgpt\install-tunnel-client.ps1
\`\`\`

This starts a separate local gateway at \`http://127.0.0.1:18100/mcp\`. OAuth is disabled **only for fixed Fake1C data on loopback**. A tunnel does not itself provide end-user production authorization. Protect the control-plane API key, select the OpenAI tunnel, and follow the [complete ChatGPT setup guide](CHATGPT_MCP_INTEGRATION.md).

After testing:

\`\`\`powershell
.\scripts\chatgpt\stop-tunnel.ps1
.\scripts\chatgpt\down.ps1
\`\`\`

**Never point the OAuth-disabled demo at a real 1C system.**

## 7. Requirements for Production Deployment

Production rollout is **a separate engineering project and acceptance process**, not merely running \`docker compose up\`:

- Separate production PostgreSQL roles and URLs: \`BAG_DATABASE_URL\` (runtime), \`BAG_ADMIN_DATABASE_URL\` (administrator), and \`BAG_MIGRATION_DATABASE_URL\` (owner); verified forward migrations and rollback.
- Real IdP issuer/audience/JWKS/scopes, source/company ACLs, revocation, and separate Admin OAuth.
- Secrets sourced from an approved file or GCP Secret Manager; **never use the environment secret provider in production**.
- HTTPS, a private sidecar, pinned upstream build and token, precise host/CIDR allowlists, firewall, redirect prevention, and SSRF defenses.
- Append-only audit, Redis cross-replica rate limiting, monitoring, backups/PITR, and tested restoration.
- Genuine native accounting reconciliation at L2/L3, user acceptance, security/load/operations evidence, and formally approved production GO.

Normative references: [Production](../deploy/PRODUCTION.md), [Security](../SECURITY.md), [Rollback](../deploy/ROLLBACK.md), [Release Operations](RELEASE_OPERATIONS.md), and [Definition of Done](DEFINITION_OF_DONE.md).

## 8. Troubleshooting — Start Here

| Symptom | Safe diagnosis or response |
| --- | --- |
| \`docker version\`: daemon unavailable | Start Docker Desktop and select Linux containers |
| \`uv sync --locked\` fails | Verify Python 3.12+, current uv, and package-index connectivity; **do not bypass the lockfile by arbitrary upgrades** |
| \`port already in use\` / \`foreign listener\` | Use \`Get-NetTCPConnection -State Listen -LocalPort 18000\`; do not kill another session's process; isolate clone and port offsets |
| \`/healthz\` works but \`/readyz\` fails | Check DB/Redis, migrations, ACLs/secrets, and the disposable stack logs via \`scripts\e2e\status.ps1\` |
| \`401 / 403\` | Check real OAuth issuer/audience/scope, source/company grants, and separate Admin permissions; never disable OAuth as a workaround |
| \`SEMANTIC_PROFILE_UNVALIDATED\` | Exact mapping and genuine native reports required; never return an invented zero or confident answer |
| \`CAPABILITY_UNSUPPORTED\` | Adapter/register/COM behavior has not been proven; do not enable unrestricted query access |
| \`NEEDS_VALIDATION\` or metadata drift | Distinguish a transport outage from genuine schema change; compare fingerprints and evidence |
| Tunnel unavailable | Run \`chatgpt\doctor.ps1\`, check local gateway and tunnel credentials; demonstration remains Fake1C-only |
| Git status changes after install | Ensure \`.env\`, \`.e2e\`, and \`.chatgpt\` remain outside Git; never commit private credentials |

When reporting an issue to maintainers, provide **no secrets**: operating system, \`git rev-parse --short HEAD\`, Python/uv/Docker versions, exact command, safe error code only, and \`status.ps1\` results. Do not send DSNs, bearer tokens, OData passwords, customer URLs, or real accounting amounts.

## 9. Principles and Lessons Learned

Read [Lessons Learned](LESSONS_LEARNED_RU.md) for documented failures and project decisions concerning security boundaries, source/company scope, capability drift, native reconciliation, local Windows/COM integration, migrations, and test isolation. The existing filename is retained to preserve links while its prose is translated into English.

## 10. What Installation Readiness Means

- **L1 READY:** Local \`up.ps1\`, \`status.ps1\`, and \`smoke\` succeed. This proves **only the synthetic contract demo**.
- **L2 VERIFIED:** A real test database, permissions, OData/COM connection, and independent native reconciliation pass for the same source, company, and configuration.
- **Production GO:** All mandatory gates pass on the exact release HEAD and the accountable owners approve. Implemented code or green L1 tests are not sufficient.

**Phase 2 is not part of this installer.** See the [Phase 2 design/status](phase2/README.md) and [S0–S10 roadmap](phase2/PLAN_PHASE2_RU.md). Living Model capabilities must not be advertised as generally available from \`main\`.
