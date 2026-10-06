from __future__ import annotations

import argparse
import asyncio
import uuid

import asyncpg

from business_ai_gateway.models import Source
from business_ai_gateway.settings import Settings


async def source_upsert(args, conn, *, production: bool):
    candidate = Source(
        id=args.source_id,
        project="onec",
        kind="onec_auto",
        display_name=args.display_name,
        base_url=args.base_url,
        username_secret_ref=args.username_secret,
        password_secret_ref=args.password_secret,
        read_only=True,
        enabled=True,
        tags=tuple(args.tags),
        entity_allow_patterns=tuple(args.allow),
        entity_deny_patterns=tuple(args.deny),
        platform_version_hint=args.platform_version_hint,
        fallback_kind=args.fallback_kind,
        fallback_base_url=args.fallback_base_url,
    )
    candidate.validate_runtime(production=production)

    await conn.execute(
        """
        INSERT INTO bag.sources(
          source_id, project, kind, display_name, base_url,
          username_secret_ref, password_secret_ref, read_only, enabled,
          tags, entity_allow_patterns, entity_deny_patterns,
          platform_version_hint, fallback_kind, fallback_base_url
        )
        VALUES(
          $1,'onec','onec_auto',$2,$3,$4,$5,true,true,$6,$7,$8,$9,$10,$11
        )
        ON CONFLICT(source_id) DO UPDATE SET
          display_name=EXCLUDED.display_name,
          base_url=EXCLUDED.base_url,
          username_secret_ref=EXCLUDED.username_secret_ref,
          password_secret_ref=EXCLUDED.password_secret_ref,
          tags=EXCLUDED.tags,
          entity_allow_patterns=EXCLUDED.entity_allow_patterns,
          entity_deny_patterns=EXCLUDED.entity_deny_patterns,
          platform_version_hint=EXCLUDED.platform_version_hint,
          fallback_kind=EXCLUDED.fallback_kind,
          fallback_base_url=EXCLUDED.fallback_base_url,
          updated_at=now()
        """,
        args.source_id,
        args.display_name,
        args.base_url,
        args.username_secret,
        args.password_secret,
        args.tags,
        args.allow,
        args.deny,
        args.platform_version_hint,
        args.fallback_kind,
        args.fallback_base_url,
    )


async def grant_add(args, conn):
    await conn.execute(
        """
        INSERT INTO bag.access_grants(
          grant_id, principal_kind, principal_id, source_id, all_sources, company_id, effect
        )
        VALUES($1,$2,$3,$4,false,$5,$6)
        """,
        uuid.uuid4(),
        args.kind,
        args.principal,
        args.source_id,
        uuid.UUID(args.company_id) if args.company_id else None,
        args.effect,
    )


async def grant_revoke(args, conn):
    result = await conn.execute(
        """
        UPDATE bag.access_grants
        SET revoked_at=now()
        WHERE principal_kind=$1
          AND principal_id=$2
          AND source_id=$3
          AND company_id IS NOT DISTINCT FROM $4::uuid
          AND revoked_at IS NULL
        """,
        args.kind,
        args.principal,
        args.source_id,
        uuid.UUID(args.company_id) if args.company_id else None,
    )
    print(result)


async def company_upsert(args, conn):
    requested_id = uuid.UUID(args.company_id)
    company_id = await conn.fetchval(
        """
        INSERT INTO bag.companies(
          company_id, source_id, external_ref, display_name, legal_name,
          country_code, is_default
        )
        VALUES($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT(source_id, external_ref) DO UPDATE SET
          display_name=EXCLUDED.display_name,
          legal_name=EXCLUDED.legal_name,
          country_code=EXCLUDED.country_code,
          is_default=EXCLUDED.is_default,
          updated_at=now()
        RETURNING company_id
        """,
        requested_id,
        args.source_id,
        args.external_ref,
        args.display_name,
        args.legal_name,
        args.country_code,
        args.default,
    )
    print(company_id)


async def capability_ack_drift(args, conn):
    row = await conn.fetchrow(
        """
        UPDATE bag.source_capabilities
        SET drift_status='STABLE', drift_acknowledged_at=now()
        WHERE source_id=$1
          AND metadata_fingerprint=$2
          AND drift_status='DRIFTED'
        RETURNING source_id, metadata_fingerprint, drift_acknowledged_at
        """,
        args.source_id,
        args.expected_fingerprint,
    )
    if row is None:
        raise ValueError("source has no unacknowledged drift at the expected fingerprint")
    print(f"acknowledged metadata drift for {row['source_id']}: {row['metadata_fingerprint']}")


async def platform_role_add(args, conn):
    binding_id = uuid.UUID(args.binding_id) if args.binding_id else uuid.uuid4()
    row = await conn.fetchrow(
        """
        INSERT INTO bag.platform_role_bindings(
          binding_id, principal_kind, principal_id, role_name, source_id,
          expires_at, created_by_subject, created_by_client, reason
        )
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING binding_id, principal_kind, principal_id, role_name, source_id
        """,
        binding_id,
        args.kind,
        args.principal,
        args.role,
        args.source_id,
        args.expires_at,
        args.created_by,
        args.client_id,
        args.reason,
    )
    print(dict(row))


async def platform_role_revoke(args, conn):
    row = await conn.fetchrow(
        """
        UPDATE bag.platform_role_bindings
        SET revoked_at=now(), updated_at=now(), row_version=row_version+1
        WHERE binding_id=$1
          AND revoked_at IS NULL
        RETURNING binding_id, principal_kind, principal_id, role_name, source_id, revoked_at
        """,
        uuid.UUID(args.binding_id),
    )
    if row is None:
        raise ValueError("platform role binding not found or already revoked")
    print(dict(row))


async def run(args):
    settings = Settings()
    dsn = settings.admin_database_url
    if settings.environment == "production" and not dsn:
        raise RuntimeError(
            "production admin operations require BAG_ADMIN_DATABASE_URL"
        )
    dsn = dsn or settings.database_url

    conn = await asyncpg.connect(dsn)
    try:
        if args.command == "source-upsert":
            await source_upsert(
                args,
                conn,
                production=settings.environment == "production",
            )
        elif args.command == "grant-add":
            await grant_add(args, conn)
        elif args.command == "grant-revoke":
            await grant_revoke(args, conn)
        elif args.command == "company-upsert":
            await company_upsert(args, conn)
        elif args.command == "capability-ack-drift":
            await capability_ack_drift(args, conn)
        elif args.command == "platform-role-add":
            await platform_role_add(args, conn)
        elif args.command == "platform-role-revoke":
            await platform_role_revoke(args, conn)
    finally:
        await conn.close()


def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    source = sub.add_parser("source-upsert")
    source.add_argument("--source-id", required=True)
    source.add_argument("--display-name", required=True)
    source.add_argument("--base-url", required=True)
    source.add_argument("--username-secret", required=True)
    source.add_argument("--password-secret", required=True)
    source.add_argument("--tags", nargs="*", default=[])
    source.add_argument("--allow", nargs="*", default=[])
    source.add_argument("--deny", nargs="*", default=[])
    source.add_argument("--platform-version-hint")
    source.add_argument(
        "--fallback-kind",
        choices=["onec_http_query"],
    )
    source.add_argument("--fallback-base-url")

    for name in ("grant-add", "grant-revoke"):
        grant = sub.add_parser(name)
        grant.add_argument(
            "--kind",
            choices=["subject", "group"],
            default="subject",
        )
        grant.add_argument("--principal", required=True)
        grant.add_argument("--source-id", required=True)
        grant.add_argument("--company-id")
        grant.add_argument("--effect", choices=["allow", "deny"], default="allow")

    company = sub.add_parser("company-upsert")
    company.add_argument("--company-id", required=True)
    company.add_argument("--source-id", required=True)
    company.add_argument("--external-ref", required=True)
    company.add_argument("--display-name", required=True)
    company.add_argument("--legal-name")
    company.add_argument("--country-code")
    company.add_argument("--default", action="store_true")

    drift = sub.add_parser("capability-ack-drift")
    drift.add_argument("--source-id", required=True)
    drift.add_argument("--expected-fingerprint", required=True)

    role_add = sub.add_parser("platform-role-add")
    role_add.add_argument("--binding-id")
    role_add.add_argument("--kind", choices=["subject", "group"], default="subject")
    role_add.add_argument("--principal", required=True)
    role_add.add_argument(
        "--role",
        choices=[
            "PLATFORM_ADMIN",
            "SOURCE_ADMIN",
            "ACCESS_ADMIN",
            "PROFILE_ADMIN",
            "AUDITOR",
        ],
        required=True,
    )
    role_add.add_argument("--source-id")
    role_add.add_argument("--expires-at")
    role_add.add_argument("--created-by", required=True)
    role_add.add_argument("--client-id", default="operator-cli")
    role_add.add_argument("--reason", required=True)

    role_revoke = sub.add_parser("platform-role-revoke")
    role_revoke.add_argument("--binding-id", required=True)

    return p


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
