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
          grant_id, principal_kind, principal_id, source_id, all_sources
        )
        VALUES($1,$2,$3,$4,false)
        """,
        uuid.uuid4(),
        args.kind,
        args.principal,
        args.source_id,
    )


async def grant_revoke(args, conn):
    result = await conn.execute(
        """
        UPDATE bag.access_grants
        SET revoked_at=now()
        WHERE principal_kind=$1
          AND principal_id=$2
          AND source_id=$3
          AND revoked_at IS NULL
        """,
        args.kind,
        args.principal,
        args.source_id,
    )
    print(result)


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

    return p


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
