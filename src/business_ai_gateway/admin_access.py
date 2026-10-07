"""Bounded policy explanation for one exact principal and one authorized source."""
from __future__ import annotations

import json

from .admin_mutations import AdminValidationError
from .evidence_basis import NATIVE_ONLY_SQL


async def explain_access(pool, *, ctx, kind, principal_id, source_id, entity_set, limit, offset,
                         effect="", inheritance=""):
    if kind not in {"subject", "group"} or not principal_id or len(principal_id) > 512:
        raise AdminValidationError("invalid exact principal")
    if not source_id or not 1 <= limit <= 200 or not 0 <= offset <= 100_000:
        raise AdminValidationError("invalid source or pagination")
    if effect not in {"", "allow", "deny", "none"} or inheritance not in {"", "direct", "inherited"}:
        raise AdminValidationError("invalid policy filter")
    groups_known = kind == "group" or principal_id == ctx.token.subject
    groups = sorted(ctx.groups) if kind == "subject" and groups_known else []
    rows = await pool.fetch(
        """
        WITH explained AS (
          SELECT c.company_id, c.source_id, c.display_name, c.enabled,
                 s.enabled AS source_enabled,
                 coalesce(g.has_deny, false) AS has_deny,
                 coalesce(g.has_allow, false) AS has_allow,
                 coalesce(g.grants, '[]'::jsonb) AS matching_grants,
                 coalesce(g.grant_count, 0) AS grant_count,
                 coalesce(g.has_direct, false) AS has_direct,
                 coalesce(g.has_inherited, false) AS has_inherited,
                 EXISTS (
                   SELECT 1 FROM bag.company_scope_mappings m
                   JOIN bag.semantic_profiles p ON p.profile_id=m.profile_id
                   JOIN bag.source_capabilities sc ON sc.source_id=p.source_id
                   WHERE p.source_id=c.source_id AND (p.company_id=c.company_id OR p.company_id IS NULL)
                     AND p.status='VALIDATED' AND p.metadata_fingerprint=sc.metadata_fingerprint
                     AND sc.drift_status='STABLE' AND m.entity_set=$5
                     AND """
        + NATIVE_ONLY_SQL
        + """
                 ) AS mapping_candidate
          FROM bag.companies c JOIN bag.sources s ON s.source_id=c.source_id
          LEFT JOIN LATERAL (
            SELECT bool_or(a.effect='deny') AS has_deny,
                   bool_or(a.effect='allow') AS has_allow,
                   count(*) AS grant_count,
                   bool_or(a.principal_kind=$1 AND a.principal_id=$2) AS has_direct,
                   bool_or(NOT (a.principal_kind=$1 AND a.principal_id=$2)) AS has_inherited,
                   jsonb_agg(jsonb_build_object(
                     'grant_id', a.grant_id, 'principal_kind', a.principal_kind,
                     'principal_id', a.principal_id, 'effect', a.effect,
                     'scope', CASE WHEN a.company_id IS NULL THEN 'source-wide' ELSE 'company' END,
                     'inheritance', CASE WHEN a.principal_kind=$1 AND a.principal_id=$2
                        THEN 'direct' ELSE 'inherited' END
                   ) ORDER BY a.grant_id) FILTER (WHERE a.evidence_rank<=50) AS grants
            FROM (SELECT a.*, row_number() OVER (ORDER BY (a.effect='deny') DESC, a.grant_id) AS evidence_rank
            FROM bag.access_grants a WHERE (a.source_id=c.source_id OR a.all_sources)
              AND (a.company_id IS NULL OR a.company_id=c.company_id)
              AND a.revoked_at IS NULL AND (a.expires_at IS NULL OR a.expires_at>now())
              AND ((a.principal_kind=$1 AND a.principal_id=$2)
                OR (a.principal_kind='group' AND a.principal_id=ANY($3::text[])))) a
          ) g ON true
          WHERE c.source_id=$4
        )
        SELECT * FROM explained
        WHERE ($6='' OR ($6='deny' AND has_deny) OR ($6='allow' AND has_allow AND NOT has_deny)
                        OR ($6='none' AND NOT has_allow AND NOT has_deny))
          AND ($7='' OR ($7='direct' AND has_direct) OR ($7='inherited' AND has_inherited))
        ORDER BY company_id LIMIT $8 OFFSET $9
        """,
        kind, principal_id, groups, source_id, entity_set, effect, inheritance, limit + 1, offset,
    )
    items = []
    for row in rows[:limit]:
        grants = row["matching_grants"]
        if isinstance(grants, str):
            grants = json.loads(grants)
        active = row["enabled"] and row["source_enabled"]
        decision = "deny" if not active or row["has_deny"] else (
            "allow" if row["has_allow"] else "deny"
        )
        if active and not row["has_deny"] and not groups_known:
            decision = "unknown"
        items.append({
            "company_id": str(row["company_id"]), "source_id": source_id,
            "display_name": row["display_name"], "data_acl": decision,
            "detail_code": "DISABLED_SCOPE" if not active else (
                "EXPLICIT_DENY" if row["has_deny"] else (
                    "GROUP_MEMBERSHIP_UNAVAILABLE" if not groups_known else (
                        "MATCHING_ALLOW" if row["has_allow"] else "NO_ALLOW"
                    )
                )
            ),
            "matching_grants": grants,
            "matching_grant_count": row["grant_count"],
            "grant_evidence_truncated": row["grant_count"] > 50,
            "company_operation": "mapping_candidate_requires_live_checks" if row["mapping_candidate"]
                                 else "unsupported_or_stale_mapping",
            "generic_onec_read": "requires_source_wide_grant",
        })
    return {
        "mode": "exact-id", "principal_kind": kind, "principal_id": principal_id,
        "group_membership": "token_claims" if kind == "subject" and groups_known else (
            "group_policy_projection" if kind == "group" else "not_configured"
        ),
        "items": items, "limit": limit, "offset": offset,
        "next_offset": offset + limit if len(rows) > limit else None,
        "capability_check": "separate_runtime_gate",
    }
