# Admin Control Center — data model and migration plan

**Status:** proposed C3 schema delta. Do not apply to production until the ADR/threat review is accepted.

## 1. Existing schema reused

Reuse without semantic change:
- bag.sources
- bag.companies
- bag.access_grants
- bag.source_capabilities
- semantic profile/mapping/event tables
- bag.audit_events for data-plane access events

Do not create a local users table with passwords.

## 2. Required improvements to access_grants

The current access_grants schema has grant_id, principal, source/all_sources, optional company, effect, expiry and revoked_at, but it does not persist the actor/reason metadata needed for safe browser administration.

Proposed additive columns:
- created_by_subject text
- created_by_client text
- create_reason text
- revoked_by_subject text
- revoke_reason text
- row_version bigint NOT NULL DEFAULT 1
- updated_at timestamptz NOT NULL DEFAULT now()

Existing rows may leave actor/reason null and be labeled "legacy/operator CLI" in UI.

Revocation contract becomes exact grant_id update with expected row_version. Do not remove historical rows.

## 3. Platform role bindings

Proposed table bag.platform_role_bindings:

~~~text
binding_id UUID PK
principal_kind subject|group
principal_id TEXT
role_name PLATFORM_ADMIN|SOURCE_ADMIN|ACCESS_ADMIN|PROFILE_ADMIN|AUDITOR
source_id TEXT NULL
expires_at TIMESTAMPTZ NULL
revoked_at TIMESTAMPTZ NULL
created_by_subject TEXT
created_by_client TEXT
reason TEXT
row_version BIGINT
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
~~~

Rules:
- PLATFORM_ADMIN must be global: source_id NULL.
- source-scoped roles may be global or delegated to one source.
- USER is represented by no admin binding, not a stored privileged role.
- active deny semantics are unnecessary here if role revocation is exact and immediate; if negative bindings are later needed, add them deliberately through another C3 change.

## 4. Business roles

Proposed bag.business_roles:
- role_id text PK;
- display_name;
- description;
- built_in boolean;
- enabled boolean;
- policy_version;
- created_at/updated_at.

Initial built-ins are seeded by migration and immutable from UI.

Proposed bag.business_role_capabilities:
- role_id FK;
- capability_key text;
- PRIMARY KEY(role_id, capability_key).

Proposed bag.business_role_assignments:
- assignment_id UUID PK;
- principal_kind subject|group;
- principal_id;
- role_id;
- source_id;
- company_id nullable;
- expires_at;
- revoked_at;
- actor/reason fields;
- row_version;
- timestamps.

Company/source FK must prove company belongs to source, mirroring access_grants.

## 5. Capability overrides

Proposed bag.capability_overrides:
- override_id UUID PK;
- principal_kind;
- principal_id;
- capability_key;
- source_id;
- company_id nullable;
- effect allow|deny;
- expires_at;
- revoked_at;
- actor/reason;
- row_version;
- timestamps.

Deny overrides role/direct allow. Missing capability permission denies.

Do not add capability rows until an operation-to-capability registry exists in code and tests.

## 6. Admin audit

Proposed append-only bag.admin_audit_events:
- event_id UUID PK;
- occurred_at;
- request_id UUID;
- actor_subject;
- actor_client_id;
- action;
- target_type;
- target_id;
- source_id nullable;
- company_id nullable;
- reason nullable;
- idempotency_key nullable;
- policy_version nullable;
- before_fingerprint nullable;
- after_fingerprint nullable;
- safe_change_json JSONB;
- outcome success|error|denied|conflict;
- detail_code nullable.

Use a no-UPDATE/no-DELETE trigger equivalent to bag.audit_events.

## 7. Idempotency

Proposed bag.admin_idempotency:
- actor_subject;
- idempotency_key;
- command_name;
- request_fingerprint;
- result_ref;
- outcome;
- created_at;
- expires_at;
- PRIMARY KEY(actor_subject, idempotency_key).

This table contains no secrets or raw business data.

## 8. Database roles

Do not let the browser process use business_ai_admin directly.

Recommended new role: business_ai_control_api.

Minimum rights:
- SELECT on approved control-plane tables;
- INSERT/UPDATE only on explicit tables/columns needed for admin commands, or EXECUTE on narrowly reviewed command functions;
- INSERT only on admin_audit_events and admin_idempotency;
- no UPDATE/DELETE on either audit table;
- no access to migration ownership;
- no capability to change DB roles/schema;
- no raw secret values.

business_ai_app remains unchanged and cannot administer.

## 9. Migration sequence

Recommended monotonic sequence after current 007:

- 008_access_grant_admin_provenance.sql
- 009_platform_role_bindings.sql
- 010_business_capability_policy.sql
- 011_admin_audit_idempotency.sql
- 012_control_api_privileges.sql

Actual numbering must be rechecked at implementation HEAD; never reuse a migration number.

## 10. Backfill

- existing access grants: preserve as-is; actor/reason null;
- no automatic platform-admin creation;
- built-in business roles/capabilities may be seeded only when enforcement code is present in the same release slice;
- no attempt to infer users/groups from historical tokens;
- no automatic company discovery backfill unless a source-specific validated mapping exists.

## 11. Rollback / restore analysis

All migrations are additive. Normal rollback is application rollback while leaving new tables/columns inert.

Do not drop tables/columns during rollback. A later cleanup migration is destructive C4 and needs explicit approval.

Before production:
- backup/PITR evidence;
- migration from previous supported schema in CI;
- privilege diff captured;
- restore rehearsal;
- exact migration SHA recorded.

## 12. Data retention

Admin/audit retention is a separate governance decision. Until defined, do not implement automatic deletion. Revocation uses timestamps, not DELETE.
