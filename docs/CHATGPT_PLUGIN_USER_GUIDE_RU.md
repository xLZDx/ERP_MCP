# ERP_MCP_REAL1 in ChatGPT — Historical User Guide

**Status of this guide:** This document describes an earlier authorized test environment and the user's expected troubleshooting flow at that point. It is **not** a live-status report. Recent status checks have produced internal connector errors; verify source availability, current grants and the exact deployed build before relying on any historical "works" statements.

The reference environment uses **read-only** access to an authorized 1C database for **818 HA SRL**. The plugin must not modify business data in 1C.

## 1. Previously Documented Capabilities and Restrictions

| User request | Earlier documented behavior (must be revalidated today) |
| --- | --- |
| "Show ERP_MCP status" | Service status was available |
| "Which sources can I access?" | The real \`onec-818ha-reference\` source and a separately labeled synthetic portfolio were listed |
| "Which companies are available on onec-818ha-reference?" | The authorized 818 HA SRL organization was shown |
| "Check source health", "show capabilities", "find the Counterparty entity" | Not available to the referenced company-only account without the required source-wide permission |
| Real company balances, turnovers, postings, accounts payable and aging | Blocked by semantic-profile validation until the required independent evidence exists |

**A capability shown in this historical table does not mean that it is currently healthy or authorized.**

## 2. Asking Scoped Questions

Specify the approved source \`onec-818ha-reference\` and choose the company from the authorized company list. Provide dates explicitly, for example, "as of August 31, 2026" or "for August 2026". The gateway is responsible for converting dates using the verified source time-zone semantics.

Example request **after a qualified accounting profile has been validated**:

> "How much do we owe each supplier on account 521.1 as of August 31, 2026? Show supplier, account, debit, credit, amount payable and the total."

The gateway must not fabricate an answer while the profile or native accounting evidence remains incomplete.

## 3. Source Health Returns "Error Executing Tool"

An earlier account configuration granted company-level access, not source-wide access. Health checks, capability lists and metadata searches may require broader permission. This is intentional tenant/company isolation: a company-level user is not entitled to inspect another company's source-wide schema.

If source-wide access is genuinely required, the **source owner/administrator** must separately approve and provision it. **Do not broaden grants only to make a 403 disappear.**

An opaque internal error is not proof that the account merely lacks rights; it may also indicate a transport, authentication, connector or source failure. Diagnose it through authorized, sanitized infrastructure evidence.

## 4. "SEMANTIC_PROFILE_UNVALIDATED"

The gateway must not claim it understands supplier accounts and analytic dimensions until the owner has verified the mapping through independent standard 1C reports. The historical R1 validation policy required at least ten original reports covering the relevant accounting operations.

An unverified profile must return a blocked/validation-required outcome, **not a numeric zero that could be mistaken for a real balance**.

Operator action: request independent native 1C reports through the approved accountant capture procedure and validate the semantic profile through the Admin Control Center. See [Accountant Native Report Request](NATIVE_REPORT_ACCOUNTANT_REQUEST_RU.md).

## 5. The Plugin Does Not Respond

1. On the **authorized test workstation**, check the read-only health URL \`http://127.0.0.1:21000/healthz\`. A healthy test gateway should respond with HTTP 200. Health alone does not prove source authorization or accounting correctness.
2. A historical troubleshooting procedure used the following **mutating test-environment restart** from \`D:\Repo\ERP_MCP-integration-candidate\`. This is preserved for provenance, **not authorization to run it now**:

   \`\`\`powershell
   $env:E2E_DIR = 'D:\ERP_MCP_Testbed\real1c_e2e'
   $env:E2E_REAL1C = '1'
   .\scripts\e2e\fault.ps1 -Component gateway -Action restart
   \`\`\`

   A restart changes process state. **Run only after confirming the exact disposable environment, current owner approval, a controlled maintenance window and a rollback plan.** Never execute it against an unknown, shared or production gateway.

3. If ChatGPT asks to reconnect, verify the current approved OAuth/tunnel route. The earlier test connector used a temporary Cloudflare address that could change after tunnel restart. **Do not bypass production authentication by adopting a no-OAuth demonstration link.**

## 6. Explicit Non-Capabilities

The gateway must not create or change source documents, disclose passwords or bearer tokens, or answer queries against unauthorized companies. Data from the synthetic portfolio must remain distinctly labeled and isolated from the genuine 818 HA company.

**Current usage requires a fresh, authenticated status check; this historical guide is not evidence of live availability or production approval.**
