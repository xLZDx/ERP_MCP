from __future__ import annotations

from uuid import UUID

from .principal import Principal

CAPABILITY_KEYS = frozenset({
    "source.status.read", "company.list", "metadata.read", "accounting.read", "ar.read", "ap.read",
    "sales.read", "purchases.read", "bank.read", "cash.read", "inventory.read", "invoice.reconcile",
    "month_close.review", "financial_statements.read", "tax.review", "audit.evidence.read",
    "executive_summary.read", "payroll.review",
})


class CapabilityDenied(PermissionError):
    code = "CAPABILITY_DENIED"


class CapabilityPolicy:
    POLICY_VERSION = "rbac-v1"

    def __init__(self, db, *, enabled: bool):
        self.db = db
        self.enabled = enabled

    async def require(
        self,
        principal: Principal,
        capability: str,
        *,
        source_id: str,
        company_id: UUID | None = None,
    ) -> str | None:
        if not self.enabled:
            return None
        if capability not in CAPABILITY_KEYS or not source_id:
            raise CapabilityDenied("capability and source are required")

        pool = self.db.require_pool()
        args = (
            principal.subject,
            list(principal.groups),
            source_id,
            company_id,
            capability,
        )
        denied = await pool.fetchval(
            """
            SELECT EXISTS(
              SELECT 1
              FROM bag.capability_overrides o
              WHERE o.capability_key=$5
                AND o.effect='deny'
                AND o.source_id=$3
                AND (o.company_id IS NULL OR $4::uuid IS NULL OR o.company_id=$4::uuid)
                AND o.revoked_at IS NULL
                AND (o.expires_at IS NULL OR o.expires_at > now())
                AND (
                      (o.principal_kind='subject' AND o.principal_id=$1)
                   OR (o.principal_kind='group' AND o.principal_id=ANY($2::text[]))
                )
            )
            """,
            *args,
        )
        if denied:
            raise CapabilityDenied(f"capability denied: {capability}")

        direct_allow = await pool.fetchval(
            """
            SELECT EXISTS(
              SELECT 1
              FROM bag.capability_overrides o
              WHERE o.capability_key=$5
                AND o.effect='allow'
                AND o.source_id=$3
                AND (o.company_id IS NULL OR o.company_id=$4::uuid)
                AND o.revoked_at IS NULL
                AND (o.expires_at IS NULL OR o.expires_at > now())
                AND (
                      (o.principal_kind='subject' AND o.principal_id=$1)
                   OR (o.principal_kind='group' AND o.principal_id=ANY($2::text[]))
                )
            )
            """,
            *args,
        )
        if direct_allow:
            return self.POLICY_VERSION

        role_allow = await pool.fetchval(
            """
            SELECT EXISTS(
              SELECT 1
              FROM bag.business_role_assignments a
              JOIN bag.business_roles r ON r.role_id=a.role_id AND r.enabled=true
              JOIN bag.business_role_capabilities c ON c.role_id=a.role_id
              WHERE c.capability_key=$5
                AND a.source_id=$3
                AND (a.company_id IS NULL OR a.company_id=$4::uuid)
                AND a.revoked_at IS NULL
                AND (a.expires_at IS NULL OR a.expires_at > now())
                AND (
                      (a.principal_kind='subject' AND a.principal_id=$1)
                   OR (a.principal_kind='group' AND a.principal_id=ANY($2::text[]))
                )
            )
            """,
            *args,
        )
        if role_allow:
            return self.POLICY_VERSION
        raise CapabilityDenied(f"capability not granted: {capability}")
