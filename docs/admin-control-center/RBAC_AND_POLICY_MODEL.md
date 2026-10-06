# Admin Control Center — RBAC and policy model

**Goal:** separate system administration, data visibility and business capabilities.

## 1. Three independent dimensions

~~~text
WHO MAY ADMINISTER?      WHAT DATA IS VISIBLE?       WHAT MAY BE DONE?
Platform role      x     source/company ACL     x    business capability
~~~

A single field called "role" must never collapse these dimensions.

## 2. Platform roles

Fixed initial roles:

| Role | Purpose |
|---|---|
| PLATFORM_ADMIN | Full control-plane administration, including platform-role bindings |
| SOURCE_ADMIN | Register/update allowed 1C sources, run safe probes, refresh capabilities, acknowledge drift |
| ACCESS_ADMIN | Manage source/company access grants for allowed administrative boundary |
| PROFILE_ADMIN | Manage semantic profile lifecycle and mapping validation |
| AUDITOR | Read control-plane state and audit only |
| USER | No control-plane mutation rights; ordinary MCP use is governed separately |

Recommended implementation: principal bindings to these fixed roles. Role names are not editable in v1.

Scope contract is enforced by the service and the database:

- `PLATFORM_ADMIN` must be global (`source_id IS NULL`).
- `SOURCE_ADMIN`, `ACCESS_ADMIN`, `PROFILE_ADMIN`, and `AUDITOR` must name one source (`source_id IS NOT NULL`).
- No non-platform role has implicit global scope in v1, including AUDITOR.

Delegation may restrict a source role to one or more source IDs; it cannot broaden a role to all sources.

Delegated SOURCE_ADMIN cannot change connection URL or secret references. These changes require
global SOURCE_ADMIN or PLATFORM_ADMIN because repointing an assigned source can otherwise
bypass the technical-source boundary. Labels/tags/enabled state, refresh and drift operations
remain available within the assigned source. Unknown capability keys fail closed even if an
unrecognized override exists in storage.

## 3. Data scope

Data scope continues to use access_grants:
- subject or group;
- source scope;
- optional company scope;
- allow/deny;
- expiry;
- revocation;
- deny precedence.

Company-specific grants do not authorize generic unscoped `onec_read`. Existing company-aware accounting tools use fixed operations with a selected company and validated semantic profile. Admin `company_scope_mappings` are candidate configuration only; they are not consumed by a runtime read route and do not authorize company data access.

## 4. Business capabilities

Initial vocabulary:

### Common read
- source.status.read
- company.list
- metadata.read

### Accounting
- accounting.read
- ar.read
- ap.read
- sales.read
- purchases.read
- bank.read
- cash.read
- inventory.read
- financial_statements.read

### Review workflows
- invoice.reconcile
- month_close.review
- tax.review
- payroll.review
- audit.evidence.read
- executive_summary.read

Capability names are versioned policy identifiers. Unknown capability identifiers fail closed.

## 5. Business role templates

Recommended initial built-in templates:

| Role | Intended capabilities |
|---|---|
| VIEWER | safe common/accounting reads, no review workflows |
| ACCOUNTANT | accounting + AR/AP + bank/cash + inventory + reconciliation + month close |
| SENIOR_ACCOUNTANT | ACCOUNTANT plus broader review capabilities |
| TAX_REVIEWER | accounting reads + tax.review + tax evidence |
| AUDITOR_BUSINESS | accounting reads + audit.evidence.read, no mutation/admin |
| EXECUTIVE | executive_summary.read + financial statements + AR/AP + sales/purchases summaries |
| PAYROLL_REVIEWER | payroll.review + minimum required supporting reads |

These are product templates, not claims that matching MCP tools already exist. A template can become active only when every mapped operation exists and enforces the capability server-side.

## 6. Capability assignments and overrides

Effective capability may come from:
- direct business role assignment to subject;
- group business role assignment;
- direct capability override.

Precedence:
1. explicit active capability DENY;
2. role/direct capability ALLOW;
3. otherwise DENY.

A capability assignment never widens data scope. The user must pass both:
- access grant for the source/company;
- capability check for the requested operation.

## 7. Effective authorization algorithm

For a company-aware operation:

~~~text
validate token/session
  -> derive subject + groups
  -> validate required OAuth/MCP scope
  -> resolve source
  -> resolve company
  -> evaluate source/company ACL
       active explicit deny? DENY
       active allow? continue
       no allow? DENY
  -> resolve required capability
  -> evaluate capability policy
       explicit deny? DENY
       role/direct allow? continue
       otherwise DENY
  -> capability/metadata/profile gate
  -> rate/query budget
  -> adapter call
~~~

Authorization happens before any 1C call.

For a source-wide unscoped operation, company-only ALLOW grants do not authorize access. Any applicable company-scoped access DENY or capability DENY rejects the unscoped request because its result could include that company.

## 8. Platform-admin authorization algorithm

For an admin mutation:

~~~text
valid admin session
  -> admin audience/scope
  -> effective platform role
  -> delegated source boundary if any
  -> step-up requirement if command is sensitive
  -> optimistic concurrency
  -> mutation
  -> append-only admin audit
~~~

MCP business capabilities never grant admin rights.

## 9. Bootstrap and recovery

Initial platform administration cannot depend on the UI before the UI has an administrator.

Bootstrap recommendation:
- use existing operator/CLI path with admin DB credentials to add the first IdP subject/group platform-role binding;
- record exact operator reason/evidence;
- after bootstrap, normal management uses the Admin Control Center;
- emergency break-glass remains CLI/operator-only and is separately audited.

No hard-coded permanent admin subject in source code.

## 10. UI behavior

Users & Groups page shows:
- principal stable ID;
- display alias from IdP resolver when available;
- group memberships only when supplied by trusted directory integration;
- effective platform roles;
- effective data scopes;
- effective business roles/capabilities;
- provenance: direct vs inherited from group;
- deny source.

Access Matrix view:
- rows = principals/groups;
- columns = companies/sources;
- cells = Allow / Deny / Inherited / None / Unsupported-for-data-plane.

Roles & Capabilities page:
- platform roles in a separate tab from business role templates;
- built-in roles immutable in first release;
- unsupported capabilities marked "not enforced" and cannot be assigned.

## 11. Security properties to prove

- USER cannot call any admin mutation;
- AUDITOR cannot mutate;
- SOURCE_ADMIN cannot assign platform roles or grants unless also ACCESS_ADMIN;
- ACCESS_ADMIN cannot register/change endpoint URLs unless also SOURCE_ADMIN;
- PROFILE_ADMIN cannot change grants;
- delegated source admin cannot view/mutate another source;
- business role never bypasses access_grants;
- group allow + subject deny results in deny;
- role allow + capability deny results in deny;
- expired/revoked bindings are ineffective without restart;
- unknown role/capability fails closed.
