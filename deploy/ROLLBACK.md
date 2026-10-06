# Production rollback and recovery runbook

This is a controlled procedure template, not evidence that a production recovery has been
performed. A named operator must authorize every production cutover, restore, credential rollback,
or other destructive recovery action. Never overwrite the only copy of a database during recovery.

## 1. Trigger and contain

1. Incident commander records the affected release SHA, gateway/sidecar image digests, deployment
   time, migration versions, source IDs, and observed symptoms in the restricted incident record.
2. If data isolation, authorization, audit integrity, or read-only behavior is uncertain, disable
   the affected source route or gateway immediately. Do not redirect traffic to an unverified
   endpoint or bypass ACL/capability checks.
3. Preserve application, database, IdP, and sidecar evidence. Do not place credentials, tokens,
   request payloads, or raw accounting queries in the incident record.

## 2. Application/image rollback

1. Identify the last approved gateway and sidecar image digests from the release provenance
   artifacts. Do not select `latest` or rebuild an old tag during incident response.
2. Confirm the previous gateway supports the current database schema and active configuration.
   Review migration history and release compatibility notes before changing traffic.
3. With incident commander approval, deploy the previous immutable gateway digest. Roll back the
   sidecar digest only as a compatible pair; preserve the exact upstream SHA and allowlist.
4. Verify liveness/readiness, authenticated deny behavior, ACL isolation, audit writes, and a
   non-sensitive read against an approved test source before restoring traffic gradually.
5. Keep the affected source disabled if verification fails. Record the exact digest and verification
   outcomes; do not claim service recovery from health checks alone.

## 3. Database recovery and migrations

Migrations are forward-only; the repository has no automatic destructive down-migrations. Prefer
rolling the application back when the current schema is backward-compatible. If a migration or data
corruption requires database recovery:

1. Obtain explicit incident commander/database owner approval and identify the recovery point.
2. Restore the approved backup/PITR point into a separate database/cluster. Never restore over the
   current primary as the first action.
3. Validate schema version, required tables, row-count/fingerprint checks, runtime/admin privilege
   separation, audit continuity, and application readiness against the isolated restore.
4. Reconcile data written after the recovery point and document expected data loss. For audit or
   accounting data, obtain the accountable data owner’s sign-off.
5. Cut over only after validation and an approved maintenance window. Keep the original primary
   read-only and recoverable until the incident commander explicitly authorizes retirement.

## 4. Secrets and source configuration rollback

1. Disable a source if its endpoint, capability profile, or credential state is uncertain.
2. Rotate/revoke credentials through the configured secret provider. Restore a previous secret
   version only when the secret owner confirms it remains valid and uncompromised.
3. Re-validate the source hostname against `BAG_SOURCE_HOST_ALLOWLIST` and the sidecar
   `ONEC_ALLOWED_HOSTS`; do not broaden either allowlist as an emergency workaround.
4. Refresh source capabilities and semantic evidence after endpoint/credential changes. Re-enable
   only after fail-closed negative tests and an approved source-specific read pass.

## 5. Closure record

Record incident ID, authorizers, start/end times, old/new image digests, database recovery point,
migration versions, secret version identifiers (never values), sources disabled/re-enabled, evidence
links, residual impact, and follow-up owner. The procedure itself is not considered operationally
validated until rehearsed in a production-like environment and signed off by its operators.
