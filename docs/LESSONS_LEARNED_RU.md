# ERP_MCP Release 1 — Lessons Learned and Practical Constraints

**Updated:** October 9, 2026. This document records engineering lessons from the current runbooks, test reports, and repository reviews. It does not replace [SECURITY.md](../SECURITY.md), [the current release scope](SCOPE_FREEZE_BASELINE_2026-10-06.md), or the [Definition of Done](DEFINITION_OF_DONE.md). Every claim that a test passed must name the L1/L2/L3 verification level and the exact Git SHA.

## 1. Separate Demonstrations from Authorized Production Use

**Lesson.** The repository contains working test tools and some genuine Windows/1C experiments. These are not equivalent to an approved production release. Historical reports sometimes contain green CI results and local PASS records even though accounting reconciliation or an external gate remains open.

**Installation rule.** Start only with Fake1C, independent ports, and the test identity provider. Never send real accounting data through a local ChatGPT gateway with OAuth disabled. A separate production review and [release evidence](RELEASE_OPERATIONS.md) are required.

## 2. Source-Wide Permissions Are Different from Company Permissions

**Lesson.** Source-wide metadata and health information have different authorization requirements from company-scoped business data. A grant for one company does not make a generic `onec_read` call safe for company-only access. Until a company predicate is verified, that tool may require broader, source-wide authorization.

**Rule.** Never expand a grant to `all sources` or source-wide access just to eliminate an HTTP 403. Use a semantic operation with a proven source/company scope, or return access denied. Verify the negative case for an unauthorized company before the authorized happy path.

## 3. Genuine Native 1C Reports Cannot Be Replaced with Synthetic Numbers

**Lesson.** Fake1C, seeded JSON, hashes, and even ten passing checks are not independent evidence of 1C balances or journal postings without verifiable file provenance. Early validation sometimes checked only an evidence object's format, not its actual origin. Later reviews identified this as a release-blocking trust boundary.

**Rule.** An independent accounting oracle must be an original standard 1C report produced through a qualified method, bound to the exact source, company, configuration, timestamp, and reporting period. Coverage must be complete, including all six trial-balance totals and rows when required. Preserve an immutable artifact digest and obtain independent accountant approval. Without these, return `EVIDENCE_REQUIRED`, not a fabricated validation.

## 4. Do Not Trust Universal Register Names or SQL/OData Assumptions

**Lesson.** 1C configurations differ significantly in their registers, dimensions, documents, signs, currencies, time zones, account codes, and analytics. Universal entity names and presets cannot guarantee a correct balance; accounts payable for account 521.1 must not be promised without a verified profile for the specific database.

**Rule.** Follow live metadata/probe → capability profile → explicit mapping review → native validation. OData `Balance` and similar methods must be verified against the **exact EntitySet**. If unsupported, return `CAPABILITY_UNSUPPORTED`. If opening balances are unknown, coverage is partial, or currencies are mixed, do not invent a confident zero.

## 5. Transport Failures Are Not Metadata Drift

**Lesson.** Capability observation reviews exposed the risk of treating a transport failure or empty `$metadata` response as a real new schema state. This could incorrectly invalidate known-good semantic mappings.

**Rule.** `timeout` or `connection failed` means unavailable/verification required, not a truthful replacement fingerprint. Preserve the previous known-good fingerprint and verify recovery, retry, and PostgreSQL role-denial behavior. See the [Master Plan](MASTER_PLAN.md) and [Phase 2 scope](PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md).

## 6. Defend 1C Registration Against SSRF at Multiple Layers

**Lesson.** Refusing an arbitrary URL from an AI client is only the beginning. A hostname allowlist alone does not prevent DNS rebinding or proxy routing, and an HTTP redirect can transfer a request to another origin.

**Rule.** Require a registered `source_id`, correct issuer/audience/scope, exact hostname, CIDR and connect-time verification, TLS, an egress firewall, restricted redirects, a private sidecar, and read-only HTTP verbs. Do not expose 1C OData or its sidecar to the public internet. See [Production](../deploy/PRODUCTION.md).

## 7. Private Keys, OAuth, and the Secure MCP Tunnel Are Separate Boundaries

**Lesson.** A network tunnel provides connectivity; it **does not** grant production user privileges. The `development-local` configuration with OAuth disabled is intentionally limited to loopback Fake1C. A private tunnel can work even when the production identity provider is unavailable to a browser.

**Rule.** A real integration needs an end-to-end verifiable identity chain: browser-accessible IdP authorization, correct MCP resource audience, scopes, user grants, a separate administrator audience/scope, and secrets stored outside Git. Do not replace broken authentication with a test bypass. See [ChatGPT Integration](CHATGPT_MCP_INTEGRATION.md).

## 8. Local Windows/COM Installation Does Not Make Arbitrary COM Queries Safe

**Lesson.** A disposable workstation successfully installed 1C 8.3, a Community/Developer License, a per-user registered `V83.COMConnector`, and RSV Data v1.3.0, and verified native metadata and reconnection. However, an RSV audit found a shared token map, privileged `reveal`, extension token writes, and the absence of an immutable company predicate for arbitrary queries.

**Rule.** Never expose `execute_query`, `reveal`, unrestricted `query`, or an upstream bridge directly to an AI client. Permit metadata only through a fixed allowlist and ERP_MCP ACL/audit enforcement. Business-data routes require verified zero-write behavior, scope, and native accounting evidence. See the [RSV Runbook](runbooks/RSV_DATA_BRIDGE.md) and [Local Handoff](../reports/LOCAL_1C_SETUP_HANDOFF.md).

## 9. Administrator Roles, Migrations, and Audit Are Separate Trust Boundaries

**Lesson.** Administrator mutations through the ordinary runtime database login, incompatible migration histories, or the ability of an application role to modify trusted capability records undermine the trust model. Reviews highlighted the need for real permission tests and careful reconciliation of migration branches.

**Rule.** Keep separate `BAG_MIGRATION_DATABASE_URL`, `BAG_ADMIN_DATABASE_URL`, and `BAG_DATABASE_URL` credentials. Run forward migrations only with a verified history and rollback plan. The normal runtime role must not modify trusted grants or audit. Test negative privilege cases on a real disposable PostgreSQL instance, not only in mocks. **Never run reset against a working business database.**

## 10. Concurrent Tests and Environments Can Contaminate Each Other

**Lesson.** Concurrent worktrees and E2E processes can conflict over ports, databases, and process identifiers. Early reports also found an unavailable Docker daemon, incorrect test fixture expectations, uninterpreted skipped tests, and green results belonging to a different SHA.

**Rule.** Give each test stack a distinct `E2E_PORT_OFFSET` and `E2E_PROJECT_SUFFIX`. `up.ps1` must refuse a listener belonging to someone else's environment. Run checks against the exact HEAD, record skipped/xfail outcomes, and actually execute the negative cases. Never use `down -Purge` on another session's stack. See [E2E Environment](E2E_ENVIRONMENT.md).

## 11. Observability and Fail-Closed Behavior Mean More Than Metrics

**Lesson.** Implementing HTTP/Redis/PostgreSQL/OData/RSV tracing does not prove crash recovery. Synthetic fault tests are not equivalent to measurements in a production-like environment. Failure to write mandatory audit evidence must block dispatch, not silently return data.

**Rule.** Require real negative proof for DB, Redis, JWKS, secrets, OData, and RSV failures and recovery, including transport timeouts and data redaction. Every critical `audit unavailable` case must deny the operation. Never include raw client queries or credentials in evidence artifacts.

## 12. Phase 2 Must Evolve Without Replacing Facts with Assumptions

**Lesson.** Automatically updating LDM/PDM models, maintaining observation history, and introducing connectors may be useful, but polling cannot guarantee visibility into every intermediate change. An AI model cannot promote `OBSERVED` directly to `ACCEPTED`, and a supposedly native reconciliation reconstructed from the same MCP figures is not independent.

**Rule.** Introduce Phase 2 through its own gates: immutable events, scoped PostgreSQL RLS, optimistic CAS/leases/cursors, drift-vs-failure handling, genuine 1C reports, independent attestation, constrained per-source budgets, and explicit production permits. Until the applicable gates pass, the functionality is **WIP**, even if feature-branch code executes.

See the [Phase 2 Overview](phase2/README.md) and [Phase 2 Plan](phase2/PLAN_PHASE2_RU.md).

## 13. Verify ComSpec and Source Grants Separately on a Fresh Windows Install

**Lesson from the October 9, 2026 verification:** `Start-Process -FilePath $env:ComSpec` can receive an empty value in a remote noninteractive PowerShell session. The E2E helper now checks the standard `cmd.exe` path and restores `ComSpec` within the process. This does not justify lowering ExecutionPolicy or disabling ACLs.

**Second verified case:** The test `AUDITOR` platform role was created successfully, but the new separate test database had no data-plane source grant. `source_health` and `onec_capabilities` returned `AccessDenied`—a correct security outcome, not a broken capability schema. A limited test-only bootstrap for the exact real-1C source and an idempotent repair allowed the authorized positive case to be verified. **7/7** positive and negative checks passed on the real test source. See the [Verification Report](../reports/FRESH_INSTALL_REAL1C_VERIFICATION_2026-10-09.md).

## Checklist Before Any Public Claim of Readiness

- Identify the exact Git SHA, configuration version, and environment level.
- Demonstrate real protected roles/ACLs, read-only boundaries, egress controls, and mandatory audit.
- Supply real L2 native reconciliation from an authorized source; clearly label synthetic L1 evidence.
- Distinguish "implemented," "test passed," "gate approved," and "production authorized."
- Disclose all skipped/NOT_RUN checks, external approvals, and residual risks.
- Keep customer URLs, passwords, bearer tokens, DSNs, and private financial values out of documentation.

**This is operational guidance, not a claim that every listed invariant has achieved production GO.**
