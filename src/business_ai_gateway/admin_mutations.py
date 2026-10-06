from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from .models import Source
from .semantic import (
    PRESETS_BY_ID,
    canonical_fingerprint,
    find_configuration_preset,
    require_profile_capabilities,
    validate_native_reconciliation_evidence,
)


class AdminMutationError(RuntimeError):
    code = "ADMIN_MUTATION_ERROR"


class AdminConflict(AdminMutationError):
    code = "POLICY_VERSION_CONFLICT"


class AdminNotFound(AdminMutationError):
    code = "NOT_FOUND"


class AdminValidationError(AdminMutationError):
    code = "INVALID_REQUEST"


@dataclass(frozen=True, slots=True)
class AdminActor:
    subject: str
    client_id: str


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _bounded_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdminValidationError(f"{name} must be a JSON object")
    if len(json.dumps(value, ensure_ascii=False, default=str).encode()) > 256_000:
        raise AdminValidationError(f"{name} exceeds 256 KB")
    return value


def _validate_mapping_evidence(value: Any) -> dict[str, Any]:
    evidence = _bounded_object(value or {}, "mapping evidence")
    if set(evidence) - {"evidence_refs", "notes"}:
        raise AdminValidationError(
            "mapping evidence may contain only evidence_refs and notes"
        )
    refs = evidence.get("evidence_refs", [])
    if not isinstance(refs, list) or any(
        not isinstance(ref, str) or not ref.strip() or len(ref) > 2048 for ref in refs
    ):
        raise AdminValidationError("mapping evidence_refs are invalid")
    notes = evidence.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 2048:
        raise AdminValidationError("mapping evidence notes are invalid")
    return {"evidence_refs": refs, "notes": notes}


def _profile_fingerprint(profile: Any, mappings: list[Any]) -> str:
    return canonical_fingerprint(
        {
            "source_id": profile["source_id"],
            "company_id": str(profile["company_id"]) if profile["company_id"] else None,
            "preset_id": profile["preset_id"],
            "profile_name": profile["profile_name"],
            "profile_version": profile["profile_version"],
            "metadata_fingerprint": profile["metadata_fingerprint"],
            "capability_fingerprint": profile["capability_fingerprint"],
            "preset_repository": profile["preset_repository"],
            "preset_upstream_sha": profile["preset_upstream_sha"],
            "profile_json": _json_value(profile["profile_json"]),
            "mappings": [
                {
                    "canonical_concept": row["canonical_concept"],
                    "mapping_json": _json_value(row["mapping_json"]),
                    "evidence_json": _json_value(row["evidence_json"]),
                    "mapping_status": row["mapping_status"],
                    "confidence": row["confidence"],
                }
                for row in mappings
            ],
            "validation_evidence_json": _json_value(
                profile["validation_evidence_json"]
            ),
        }
    )


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _clean_reason(reason: str) -> str:
    value = reason.strip()
    if not value or len(value) > 1000:
        raise AdminValidationError("reason is required and must be <=1000 characters")
    return value


def _clean_key(key: str) -> str:
    value = key.strip()
    if not value or len(value) > 128:
        raise AdminValidationError("idempotency key is required and must be <=128 characters")
    return value


class AdminMutationService:
    def __init__(self, db, *, production: bool):
        self.db = db
        self.production = production

    async def _reserve(
        self,
        *,
        actor: AdminActor,
        command: str,
        key: str,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        key = _clean_key(key)
        request_fp = _fingerprint(request)
        pool = self.db.require_pool()
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                    SELECT command_name, request_fingerprint, outcome, result_json, detail_code
                    FROM bag.admin_idempotency
                    WHERE actor_subject=$1 AND idempotency_key=$2
                    FOR UPDATE
                    """,
                actor.subject,
                key,
            )
            if row is not None:
                if (
                    row["command_name"] != command
                    or row["request_fingerprint"] != request_fp
                ):
                    raise AdminConflict("idempotency key already used for another request")
                if row["outcome"] == "success":
                    result = row["result_json"]
                    if isinstance(result, str):
                        result = json.loads(result)
                    return dict(result or {})
                raise AdminConflict(
                    f"idempotent request already has outcome {row['outcome']}"
                )
            await conn.execute(
                """
                    INSERT INTO bag.admin_idempotency(
                        actor_subject, idempotency_key, command_name,
                        request_fingerprint, outcome
                    ) VALUES($1,$2,$3,$4,'pending')
                    """,
                actor.subject,
                key,
                command,
                request_fp,
            )
        return None

    async def _record_failure(
        self,
        *,
        actor: AdminActor,
        command: str,
        target_type: str,
        target_id: str | None,
        source_id: str | None,
        company_id: uuid.UUID | None,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
        code: str,
    ) -> None:
        pool = self.db.require_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                    UPDATE bag.admin_idempotency
                    SET outcome='error', detail_code=$3, updated_at=now()
                    WHERE actor_subject=$1 AND idempotency_key=$2
                    """,
                actor.subject,
                idempotency_key,
                code,
            )
            await conn.execute(
                """
                    INSERT INTO bag.admin_audit_events(
                        event_id, request_id, actor_subject, actor_client_id,
                        action, target_type, target_id, source_id, company_id,
                        reason, idempotency_key, outcome, detail_code
                    ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'error',$12)
                    """,
                uuid.uuid4(),
                request_id,
                actor.subject,
                actor.client_id,
                command,
                target_type,
                target_id,
                source_id,
                company_id,
                reason,
                idempotency_key,
                code,
            )

    async def _execute(
        self,
        *,
        actor: AdminActor,
        command: str,
        target_type: str,
        target_id: str | None,
        source_id: str | None,
        company_id: uuid.UUID | None,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
        request: dict[str, Any],
        mutation: Callable[[Any], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        reason = _clean_reason(reason)
        idempotency_key = _clean_key(idempotency_key)
        replay = await self._reserve(
            actor=actor, command=command, key=idempotency_key, request=request
        )
        if replay is not None:
            return replay

        pool = self.db.require_pool()
        try:
            async with pool.acquire() as conn, conn.transaction():
                result = await mutation(conn)
                safe_result = json.loads(json.dumps(result, default=str))
                await conn.execute(
                    """
                        UPDATE bag.admin_idempotency
                        SET outcome='success', result_json=$3::jsonb,
                            detail_code=NULL, updated_at=now()
                        WHERE actor_subject=$1 AND idempotency_key=$2
                        """,
                    actor.subject,
                    idempotency_key,
                    json.dumps(safe_result, ensure_ascii=False),
                )
                await conn.execute(
                    """
                        INSERT INTO bag.admin_audit_events(
                            event_id, request_id, actor_subject, actor_client_id,
                            action, target_type, target_id, source_id, company_id,
                            reason, idempotency_key, before_fingerprint,
                            after_fingerprint, safe_change_json, outcome
                        ) VALUES(
                            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,'success'
                        )
                        """,
                    uuid.uuid4(),
                    request_id,
                    actor.subject,
                    actor.client_id,
                    command,
                    target_type,
                    str(result.get("id", target_id)) if result.get("id", target_id) else None,
                    source_id or result.get("source_id"),
                    company_id,
                    reason,
                    idempotency_key,
                    result.get("before_fingerprint"),
                    _fingerprint(safe_result),
                    json.dumps(safe_result, ensure_ascii=False),
                )
                return safe_result
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            await self._record_failure(
                actor=actor,
                command=command,
                target_type=target_type,
                target_id=target_id,
                source_id=source_id,
                company_id=company_id,
                reason=reason,
                request_id=request_id,
                idempotency_key=idempotency_key,
                code=code,
            )
            raise

    async def create_grant(
        self,
        *,
        actor: AdminActor,
        principal_kind: str,
        principal_id: str,
        source_id: str,
        company_id: uuid.UUID | None,
        effect: str,
        expires_at: Any,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if principal_kind not in {"subject", "group"}:
            raise AdminValidationError("principal_kind must be subject or group")
        if effect not in {"allow", "deny"}:
            raise AdminValidationError("effect must be allow or deny")
        if not principal_id.strip() or not source_id.strip():
            raise AdminValidationError("principal_id and source_id are required")
        request = {
            "principal_kind": principal_kind,
            "principal_id": principal_id,
            "source_id": source_id,
            "company_id": str(company_id) if company_id else None,
            "effect": effect,
            "expires_at": str(expires_at) if expires_at else None,
        }

        async def mutation(conn):
            if company_id is not None:
                valid = await conn.fetchval(
                    """
                    SELECT EXISTS(
                      SELECT 1 FROM bag.companies
                      WHERE company_id=$1 AND source_id=$2 AND enabled=true
                    )
                    """,
                    company_id,
                    source_id,
                )
                if not valid:
                    raise AdminValidationError("company does not belong to enabled source")
            elif not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bag.sources WHERE source_id=$1 AND enabled=true)",
                source_id,
            ):
                raise AdminValidationError("source does not exist or is disabled")
            grant_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO bag.access_grants(
                    grant_id, principal_kind, principal_id, source_id, all_sources,
                    company_id, effect, expires_at, created_by_subject,
                    created_by_client, create_reason
                ) VALUES($1,$2,$3,$4,false,$5,$6,$7,$8,$9,$10)
                """,
                grant_id,
                principal_kind,
                principal_id,
                source_id,
                company_id,
                effect,
                expires_at,
                actor.subject,
                actor.client_id,
                reason,
            )
            return {
                "id": str(grant_id),
                "source_id": source_id,
                "company_id": str(company_id) if company_id else None,
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "effect": effect,
                "row_version": 1,
            }

        return await self._execute(
            actor=actor,
            command="grant.create",
            target_type="access_grant",
            target_id=None,
            source_id=source_id,
            company_id=company_id,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def revoke_grant(
        self,
        *,
        actor: AdminActor,
        grant_id: uuid.UUID,
        expected_version: int,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"grant_id": str(grant_id), "expected_version": expected_version}

        async def mutation(conn):
            row = await conn.fetchrow(
                """
                UPDATE bag.access_grants
                SET revoked_at=now(), revoked_by_subject=$2, revoke_reason=$3,
                    row_version=row_version+1, updated_at=now()
                WHERE grant_id=$1 AND revoked_at IS NULL AND row_version=$4
                RETURNING grant_id, source_id, company_id, row_version
                """,
                grant_id,
                actor.subject,
                reason,
                expected_version,
            )
            if row is None:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM bag.access_grants WHERE grant_id=$1)",
                    grant_id,
                )
                if not exists:
                    raise AdminNotFound("grant not found")
                raise AdminConflict("grant already revoked or version changed")
            return {
                "id": str(row["grant_id"]),
                "source_id": row["source_id"],
                "company_id": str(row["company_id"]) if row["company_id"] else None,
                "row_version": row["row_version"],
                "revoked": True,
            }

        return await self._execute(
            actor=actor,
            command="grant.revoke",
            target_type="access_grant",
            target_id=str(grant_id),
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def create_platform_role(
        self,
        *,
        actor: AdminActor,
        principal_kind: str,
        principal_id: str,
        role_name: str,
        source_id: str | None,
        expires_at: Any,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        allowed = {
            "PLATFORM_ADMIN",
            "SOURCE_ADMIN",
            "ACCESS_ADMIN",
            "PROFILE_ADMIN",
            "AUDITOR",
        }
        if principal_kind not in {"subject", "group"} or role_name not in allowed:
            raise AdminValidationError("invalid platform role binding")
        if role_name == "PLATFORM_ADMIN" and source_id is not None:
            raise AdminValidationError("PLATFORM_ADMIN must be global")
        request = {
            "principal_kind": principal_kind,
            "principal_id": principal_id,
            "role_name": role_name,
            "source_id": source_id,
            "expires_at": str(expires_at) if expires_at else None,
        }

        async def mutation(conn):
            if source_id is not None and not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bag.sources WHERE source_id=$1)", source_id
            ):
                raise AdminValidationError("source does not exist")
            binding_id = uuid.uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.platform_role_bindings(
                        binding_id, principal_kind, principal_id, role_name, source_id,
                        expires_at, created_by_subject, created_by_client, reason
                    ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    binding_id,
                    principal_kind,
                    principal_id,
                    role_name,
                    source_id,
                    expires_at,
                    actor.subject,
                    actor.client_id,
                    reason,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict("active role binding already exists") from exc
                raise
            return {
                "id": str(binding_id),
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "role_name": role_name,
                "source_id": source_id,
                "row_version": 1,
            }

        return await self._execute(
            actor=actor,
            command="platform_role.create",
            target_type="platform_role_binding",
            target_id=None,
            source_id=source_id,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def revoke_platform_role(
        self,
        *,
        actor: AdminActor,
        binding_id: uuid.UUID,
        expected_version: int,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"binding_id": str(binding_id), "expected_version": expected_version}

        async def mutation(conn):
            row = await conn.fetchrow(
                """
                UPDATE bag.platform_role_bindings
                SET revoked_at=now(), updated_at=now(), row_version=row_version+1
                WHERE binding_id=$1 AND revoked_at IS NULL AND row_version=$2
                RETURNING binding_id, role_name, source_id, row_version
                """,
                binding_id,
                expected_version,
            )
            if row is None:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM bag.platform_role_bindings WHERE binding_id=$1)",
                    binding_id,
                )
                if not exists:
                    raise AdminNotFound("role binding not found")
                raise AdminConflict("role binding already revoked or version changed")
            return {
                "id": str(row["binding_id"]),
                "role_name": row["role_name"],
                "source_id": row["source_id"],
                "row_version": row["row_version"],
                "revoked": True,
            }

        return await self._execute(
            actor=actor,
            command="platform_role.revoke",
            target_type="platform_role_binding",
            target_id=str(binding_id),
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def create_company(
        self,
        *,
        actor: AdminActor,
        source_id: str,
        external_ref: str,
        display_name: str,
        legal_name: str | None,
        country_code: str | None,
        is_default: bool,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not external_ref.strip() or not display_name.strip():
            raise AdminValidationError("external_ref and display_name are required")
        request = {
            "source_id": source_id,
            "external_ref": external_ref,
            "display_name": display_name,
            "legal_name": legal_name,
            "country_code": country_code,
            "is_default": is_default,
        }

        async def mutation(conn):
            if not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bag.sources WHERE source_id=$1)", source_id
            ):
                raise AdminValidationError("source does not exist")
            company_id = uuid.uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.companies(
                        company_id, source_id, external_ref, display_name,
                        legal_name, country_code, is_default
                    ) VALUES($1,$2,$3,$4,$5,$6,$7)
                    """,
                    company_id,
                    source_id,
                    external_ref,
                    display_name,
                    legal_name,
                    country_code,
                    is_default,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict("company external_ref already registered") from exc
                raise
            return {
                "id": str(company_id),
                "source_id": source_id,
                "external_ref": external_ref,
                "display_name": display_name,
                "row_version": 1,
            }

        return await self._execute(
            actor=actor,
            command="company.create",
            target_type="company",
            target_id=None,
            source_id=source_id,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def create_source(
        self,
        *,
        actor: AdminActor,
        source_id: str,
        display_name: str,
        base_url: str,
        username_secret_ref: str,
        password_secret_ref: str,
        tags: list[str],
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        candidate = Source(
            id=source_id,
            project="onec",
            kind="onec_auto",
            display_name=display_name,
            base_url=base_url,
            username_secret_ref=username_secret_ref,
            password_secret_ref=password_secret_ref,
            read_only=True,
            enabled=True,
            tags=tuple(tags),
            entity_allow_patterns=(),
            entity_deny_patterns=(),
        )
        candidate.validate_runtime(production=self.production)
        request = {
            "source_id": source_id,
            "display_name": display_name,
            "base_url": base_url,
            "username_secret_ref": username_secret_ref,
            "password_secret_ref": password_secret_ref,
            "tags": tags,
        }

        async def mutation(conn):
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.sources(
                        source_id, project, kind, display_name, base_url,
                        username_secret_ref, password_secret_ref, read_only,
                        enabled, tags
                    ) VALUES($1,'onec','onec_auto',$2,$3,$4,$5,true,true,$6)
                    """,
                    source_id,
                    display_name,
                    base_url,
                    username_secret_ref,
                    password_secret_ref,
                    tags,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict("source_id already exists") from exc
                raise
            return {
                "id": source_id,
                "source_id": source_id,
                "display_name": display_name,
                "base_url": base_url,
                "read_only": True,
                "row_version": 1,
            }

        return await self._execute(
            actor=actor,
            command="source.create",
            target_type="source",
            target_id=source_id,
            source_id=source_id,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def assign_business_role(
        self,
        *,
        actor: AdminActor,
        principal_kind: str,
        principal_id: str,
        role_id: str,
        source_id: str,
        company_id: uuid.UUID | None,
        expires_at: Any,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if principal_kind not in {"subject", "group"}:
            raise AdminValidationError("principal_kind must be subject or group")
        request = {
            "principal_kind": principal_kind,
            "principal_id": principal_id,
            "role_id": role_id,
            "source_id": source_id,
            "company_id": str(company_id) if company_id else None,
            "expires_at": str(expires_at) if expires_at else None,
        }

        async def mutation(conn):
            if not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bag.business_roles WHERE role_id=$1 AND enabled=true)",
                role_id,
            ):
                raise AdminValidationError("business role does not exist or is disabled")
            if company_id is not None and not await conn.fetchval(
                """
                SELECT EXISTS(
                  SELECT 1 FROM bag.companies
                  WHERE company_id=$1 AND source_id=$2 AND enabled=true
                )
                """,
                company_id,
                source_id,
            ):
                raise AdminValidationError("company does not belong to enabled source")
            assignment_id = uuid.uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.business_role_assignments(
                        assignment_id, principal_kind, principal_id, role_id,
                        source_id, company_id, expires_at, created_by_subject,
                        created_by_client, reason
                    ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    """,
                    assignment_id,
                    principal_kind,
                    principal_id,
                    role_id,
                    source_id,
                    company_id,
                    expires_at,
                    actor.subject,
                    actor.client_id,
                    reason,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict("active business role assignment already exists") from exc
                raise
            return {
                "id": str(assignment_id),
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "role_id": role_id,
                "source_id": source_id,
                "company_id": str(company_id) if company_id else None,
                "row_version": 1,
            }

        return await self._execute(
            actor=actor,
            command="business_role.assign",
            target_type="business_role_assignment",
            target_id=None,
            source_id=source_id,
            company_id=company_id,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def revoke_business_role(
        self,
        *,
        actor: AdminActor,
        assignment_id: uuid.UUID,
        expected_version: int,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "assignment_id": str(assignment_id),
            "expected_version": expected_version,
        }

        async def mutation(conn):
            row = await conn.fetchrow(
                """
                UPDATE bag.business_role_assignments
                SET revoked_at=now(), updated_at=now(), row_version=row_version+1
                WHERE assignment_id=$1 AND revoked_at IS NULL AND row_version=$2
                RETURNING assignment_id, role_id, source_id, company_id, row_version
                """,
                assignment_id,
                expected_version,
            )
            if row is None:
                exists = await conn.fetchval(
                    """
                    SELECT EXISTS(
                      SELECT 1 FROM bag.business_role_assignments WHERE assignment_id=$1
                    )
                    """,
                    assignment_id,
                )
                if not exists:
                    raise AdminNotFound("business role assignment not found")
                raise AdminConflict("business role assignment changed or already revoked")
            return {
                "id": str(row["assignment_id"]),
                "role_id": row["role_id"],
                "source_id": row["source_id"],
                "company_id": str(row["company_id"]) if row["company_id"] else None,
                "row_version": row["row_version"],
                "revoked": True,
            }

        return await self._execute(
            actor=actor,
            command="business_role.revoke",
            target_type="business_role_assignment",
            target_id=str(assignment_id),
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def create_capability_override(
        self,
        *,
        actor: AdminActor,
        principal_kind: str,
        principal_id: str,
        capability_key: str,
        source_id: str,
        company_id: uuid.UUID | None,
        effect: str,
        expires_at: Any,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if principal_kind not in {"subject", "group"} or effect not in {"allow", "deny"}:
            raise AdminValidationError("invalid capability override")
        request = {
            "principal_kind": principal_kind,
            "principal_id": principal_id,
            "capability_key": capability_key,
            "source_id": source_id,
            "company_id": str(company_id) if company_id else None,
            "effect": effect,
            "expires_at": str(expires_at) if expires_at else None,
        }

        async def mutation(conn):
            known = await conn.fetchval(
                """
                SELECT EXISTS(
                  SELECT 1 FROM bag.business_role_capabilities WHERE capability_key=$1
                )
                """,
                capability_key,
            )
            if not known:
                raise AdminValidationError("unknown capability")
            if company_id is not None and not await conn.fetchval(
                """
                SELECT EXISTS(
                  SELECT 1 FROM bag.companies
                  WHERE company_id=$1 AND source_id=$2 AND enabled=true
                )
                """,
                company_id,
                source_id,
            ):
                raise AdminValidationError("company does not belong to enabled source")
            override_id = uuid.uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.capability_overrides(
                        override_id, principal_kind, principal_id, capability_key,
                        source_id, company_id, effect, expires_at,
                        created_by_subject, created_by_client, reason
                    ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    """,
                    override_id,
                    principal_kind,
                    principal_id,
                    capability_key,
                    source_id,
                    company_id,
                    effect,
                    expires_at,
                    actor.subject,
                    actor.client_id,
                    reason,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict("active capability override already exists") from exc
                raise
            return {
                "id": str(override_id),
                "principal_kind": principal_kind,
                "principal_id": principal_id,
                "capability_key": capability_key,
                "source_id": source_id,
                "company_id": str(company_id) if company_id else None,
                "effect": effect,
                "row_version": 1,
            }

        return await self._execute(
            actor=actor,
            command="capability_override.create",
            target_type="capability_override",
            target_id=None,
            source_id=source_id,
            company_id=company_id,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def revoke_capability_override(
        self,
        *,
        actor: AdminActor,
        override_id: uuid.UUID,
        expected_version: int,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"override_id": str(override_id), "expected_version": expected_version}

        async def mutation(conn):
            row = await conn.fetchrow(
                """
                UPDATE bag.capability_overrides
                SET revoked_at=now(), updated_at=now(), row_version=row_version+1
                WHERE override_id=$1 AND revoked_at IS NULL AND row_version=$2
                RETURNING override_id, capability_key, source_id, company_id,
                          effect, row_version
                """,
                override_id,
                expected_version,
            )
            if row is None:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM bag.capability_overrides WHERE override_id=$1)",
                    override_id,
                )
                if not exists:
                    raise AdminNotFound("capability override not found")
                raise AdminConflict("capability override changed or already revoked")
            return {
                "id": str(row["override_id"]),
                "capability_key": row["capability_key"],
                "source_id": row["source_id"],
                "company_id": str(row["company_id"]) if row["company_id"] else None,
                "effect": row["effect"],
                "row_version": row["row_version"],
                "revoked": True,
            }

        return await self._execute(
            actor=actor,
            command="capability_override.revoke",
            target_type="capability_override",
            target_id=str(override_id),
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def create_semantic_profile(
        self,
        *,
        actor: AdminActor,
        source_id: str,
        company_id: uuid.UUID | None,
        preset_id: str,
        profile_name: str,
        profile_definition: dict[str, Any],
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        preset = find_configuration_preset(preset_id)
        if preset is None or preset.preset_id not in PRESETS_BY_ID:
            raise AdminValidationError("unknown semantic preset")
        definition_input = _bounded_object(profile_definition, "profile_definition")
        request = {
            "source_id": source_id,
            "company_id": str(company_id) if company_id else None,
            "preset_id": preset.preset_id,
            "profile_name": profile_name,
            "profile_definition": definition_input,
        }

        async def mutation(conn):
            capability_row = await conn.fetchrow(
                """
                SELECT metadata_fingerprint, metadata_supported, drift_status,
                       register_capabilities_json
                FROM bag.source_capabilities WHERE source_id=$1
                """,
                source_id,
            )
            if capability_row is None or not capability_row["metadata_supported"]:
                raise AdminValidationError(
                    "source has no successful live metadata capability record"
                )
            if capability_row["drift_status"] != "STABLE":
                raise AdminValidationError(
                    "source metadata must be acknowledged STABLE before profile creation"
                )
            if company_id is not None and not await conn.fetchval(
                """
                SELECT EXISTS(
                  SELECT 1 FROM bag.companies
                  WHERE source_id=$1 AND company_id=$2 AND enabled=true
                )
                """,
                source_id,
                company_id,
            ):
                raise AdminValidationError("company does not belong to selected source")

            definition = {
                "preset_source": {
                    "repository": preset.upstream_repository,
                    "sha": preset.upstream_sha,
                    "path": preset.upstream_path,
                    "status": preset.status,
                },
                "candidate_entities": [asdict(candidate) for candidate in preset.candidates],
                "operator_definition": definition_input,
            }
            capability_profile = _json_value(
                capability_row["register_capabilities_json"]
            )
            if not isinstance(capability_profile, dict):
                raise AdminValidationError("stored register capability profile is invalid")
            capability_fingerprint = canonical_fingerprint(capability_profile)
            version = await conn.fetchval(
                """
                SELECT coalesce(max(profile_version),0)+1
                FROM bag.semantic_profiles
                WHERE source_id=$1
                  AND company_id IS NOT DISTINCT FROM $2::uuid
                  AND preset_id=$3
                """,
                source_id,
                company_id,
                preset.preset_id,
            )
            profile_id = uuid.uuid4()
            fields = {
                "source_id": source_id,
                "company_id": str(company_id) if company_id else None,
                "preset_id": preset.preset_id,
                "profile_name": profile_name,
                "profile_version": version,
                "metadata_fingerprint": capability_row["metadata_fingerprint"],
                "capability_fingerprint": capability_fingerprint,
                "preset_repository": preset.upstream_repository,
                "preset_upstream_sha": preset.upstream_sha,
                "profile_json": definition,
                "validation_evidence_json": {},
            }
            profile_fingerprint = _profile_fingerprint(fields, [])
            await conn.execute(
                """
                INSERT INTO bag.semantic_profiles(
                    profile_id, source_id, company_id, preset_id, profile_name,
                    profile_version, status, metadata_fingerprint,
                    capability_fingerprint, profile_fingerprint,
                    preset_repository, preset_upstream_sha, profile_json, created_by
                ) VALUES(
                    $1,$2,$3,$4,$5,$6,'DRAFT',$7,$8,$9,$10,$11,$12::jsonb,$13
                )
                """,
                profile_id,
                source_id,
                company_id,
                preset.preset_id,
                profile_name,
                version,
                capability_row["metadata_fingerprint"],
                capability_fingerprint,
                profile_fingerprint,
                preset.upstream_repository,
                preset.upstream_sha,
                json.dumps(definition, ensure_ascii=False),
                actor.subject,
            )
            await conn.execute(
                """
                INSERT INTO bag.semantic_profile_events(
                    event_id, profile_id, actor, action, details_json
                ) VALUES($1,$2,$3,'CREATED',$4::jsonb)
                """,
                uuid.uuid4(),
                profile_id,
                actor.subject,
                json.dumps(
                    {
                        "preset_id": preset.preset_id,
                        "profile_fingerprint": profile_fingerprint,
                    },
                    ensure_ascii=False,
                ),
            )
            return {
                "id": str(profile_id),
                "source_id": source_id,
                "company_id": str(company_id) if company_id else None,
                "preset_id": preset.preset_id,
                "profile_version": version,
                "status": "DRAFT",
                "profile_fingerprint": profile_fingerprint,
            }

        return await self._execute(
            actor=actor,
            command="semantic_profile.create",
            target_type="semantic_profile",
            target_id=None,
            source_id=source_id,
            company_id=company_id,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def add_semantic_mapping(
        self,
        *,
        actor: AdminActor,
        profile_id: uuid.UUID,
        canonical_concept: str,
        mapping_data: dict[str, Any],
        evidence_data: dict[str, Any],
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        allowed_concepts = {"receivable", "payable", "sales", "cash", "inventory", "vat"}
        if canonical_concept not in allowed_concepts:
            raise AdminValidationError("unknown canonical concept")
        mapping = _bounded_object(mapping_data, "mapping")
        evidence = _validate_mapping_evidence(evidence_data)
        required = mapping.get("required_register_capabilities", [])
        if not isinstance(required, list) or any(
            not isinstance(item, dict)
            or set(item) != {"entity_set", "method"}
            or not all(isinstance(item[key], str) and item[key] for key in item)
            for item in required
        ):
            raise AdminValidationError(
                "required_register_capabilities must contain entity_set/method pairs"
            )
        request = {
            "profile_id": str(profile_id),
            "canonical_concept": canonical_concept,
            "mapping": mapping,
            "evidence": evidence,
        }

        async def mutation(conn):
            profile = await conn.fetchrow(
                "SELECT * FROM bag.semantic_profiles WHERE profile_id=$1 FOR UPDATE",
                profile_id,
            )
            if profile is None:
                raise AdminNotFound("semantic profile not found")
            if profile["status"] not in {"DRAFT", "NEEDS_VALIDATION"}:
                raise AdminConflict("mappings can be added only to a draft profile")
            mapping_id = uuid.uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.semantic_mappings(
                        mapping_id, profile_id, canonical_concept, mapping_json,
                        evidence_json, mapping_status, confidence
                    ) VALUES($1,$2,$3,$4::jsonb,$5::jsonb,'CANDIDATE','LOW')
                    """,
                    mapping_id,
                    profile_id,
                    canonical_concept,
                    json.dumps(mapping, ensure_ascii=False),
                    json.dumps(evidence, ensure_ascii=False),
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict(
                        "mapping already exists for this profile/concept"
                    ) from exc
                raise
            await conn.execute(
                """
                UPDATE bag.semantic_profiles
                SET status='NEEDS_VALIDATION'
                WHERE profile_id=$1
                """,
                profile_id,
            )
            profile_full = await conn.fetchrow(
                "SELECT * FROM bag.semantic_profiles WHERE profile_id=$1",
                profile_id,
            )
            mappings = await conn.fetch(
                """
                SELECT * FROM bag.semantic_mappings
                WHERE profile_id=$1 ORDER BY canonical_concept
                """,
                profile_id,
            )
            profile_fingerprint = _profile_fingerprint(profile_full, mappings)
            await conn.execute(
                """
                UPDATE bag.semantic_profiles
                SET profile_fingerprint=$2
                WHERE profile_id=$1
                """,
                profile_id,
                profile_fingerprint,
            )
            await conn.execute(
                """
                INSERT INTO bag.semantic_profile_events(
                    event_id, profile_id, actor, action, details_json
                ) VALUES($1,$2,$3,'MAPPING_ADDED',$4::jsonb)
                """,
                uuid.uuid4(),
                profile_id,
                actor.subject,
                json.dumps(
                    {
                        "canonical_concept": canonical_concept,
                        "mapping_fingerprint": canonical_fingerprint(mapping),
                    },
                    ensure_ascii=False,
                ),
            )
            return {
                "id": str(mapping_id),
                "profile_id": str(profile_id),
                "source_id": profile["source_id"],
                "company_id": (
                    str(profile["company_id"]) if profile["company_id"] else None
                ),
                "canonical_concept": canonical_concept,
                "profile_fingerprint": profile_fingerprint,
                "status": "NEEDS_VALIDATION",
            }

        return await self._execute(
            actor=actor,
            command="semantic_mapping.create",
            target_type="semantic_mapping",
            target_id=None,
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def validate_semantic_profile(
        self,
        *,
        actor: AdminActor,
        profile_id: uuid.UUID,
        validation_evidence_data: dict[str, Any],
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        evidence_input = _bounded_object(
            validation_evidence_data, "validation_evidence"
        )
        cases = validate_native_reconciliation_evidence(evidence_input)
        validation_evidence = {
            "native_reconciliation_cases": [
                {**case, "status": "PASS"} for case in cases
            ],
            "evidence_manifest_fingerprint": canonical_fingerprint(evidence_input),
        }
        request = {
            "profile_id": str(profile_id),
            "validation_evidence": evidence_input,
        }

        async def mutation(conn):
            profile = await conn.fetchrow(
                "SELECT * FROM bag.semantic_profiles WHERE profile_id=$1 FOR UPDATE",
                profile_id,
            )
            if profile is None:
                raise AdminNotFound("semantic profile not found")
            if profile["status"] not in {"DRAFT", "NEEDS_VALIDATION"}:
                raise AdminConflict("only a draft profile can be validated")
            capability_row = await conn.fetchrow(
                """
                SELECT metadata_fingerprint, drift_status, register_capabilities_json
                FROM bag.source_capabilities WHERE source_id=$1
                """,
                profile["source_id"],
            )
            if capability_row is None or capability_row["drift_status"] != "STABLE":
                raise AdminValidationError(
                    "source capabilities are absent or metadata drift is unacknowledged"
                )
            if capability_row["metadata_fingerprint"] != profile["metadata_fingerprint"]:
                raise AdminConflict("profile metadata fingerprint is stale")
            capability_profile = _json_value(
                capability_row["register_capabilities_json"]
            )
            if canonical_fingerprint(capability_profile) != profile[
                "capability_fingerprint"
            ]:
                raise AdminConflict("profile capability fingerprint is stale")
            mappings = await conn.fetch(
                """
                SELECT * FROM bag.semantic_mappings
                WHERE profile_id=$1 ORDER BY canonical_concept
                """,
                profile_id,
            )
            for mapping_row in mappings:
                mapping = _json_value(mapping_row["mapping_json"])
                required = mapping.get("required_register_capabilities", [])
                if not isinstance(required, list):
                    raise AdminValidationError(
                        "mapping required_register_capabilities must be a list"
                    )
                require_profile_capabilities(
                    required,
                    capability_profile,
                    source_id=profile["source_id"],
                    metadata_fingerprint=profile["metadata_fingerprint"],
                )

            updated_profile = dict(profile)
            updated_profile["validation_evidence_json"] = validation_evidence
            profile_fingerprint = _profile_fingerprint(updated_profile, mappings)
            updated = await conn.fetchrow(
                """
                UPDATE bag.semantic_profiles
                SET status='VALIDATED', validated_by=$2, validated_at=now(),
                    validation_evidence_json=$3::jsonb, profile_fingerprint=$4
                WHERE profile_id=$1 AND status IN ('DRAFT','NEEDS_VALIDATION')
                RETURNING profile_id
                """,
                profile_id,
                actor.subject,
                json.dumps(validation_evidence, ensure_ascii=False),
                profile_fingerprint,
            )
            if updated is None:
                raise AdminConflict("profile lifecycle changed during validation")
            await conn.execute(
                """
                INSERT INTO bag.semantic_profile_events(
                    event_id, profile_id, actor, action, details_json
                ) VALUES($1,$2,$3,'VALIDATED',$4::jsonb)
                """,
                uuid.uuid4(),
                profile_id,
                actor.subject,
                json.dumps(
                    {
                        "profile_fingerprint": profile_fingerprint,
                        "metadata_fingerprint": profile["metadata_fingerprint"],
                        "capability_fingerprint": profile["capability_fingerprint"],
                        "case_count": len(cases),
                    },
                    ensure_ascii=False,
                ),
            )
            return {
                "id": str(profile_id),
                "source_id": profile["source_id"],
                "company_id": (
                    str(profile["company_id"]) if profile["company_id"] else None
                ),
                "status": "VALIDATED",
                "profile_fingerprint": profile_fingerprint,
                "case_count": len(cases),
            }

        return await self._execute(
            actor=actor,
            command="semantic_profile.validate",
            target_type="semantic_profile",
            target_id=str(profile_id),
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def retire_semantic_profile(
        self,
        *,
        actor: AdminActor,
        profile_id: uuid.UUID,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"profile_id": str(profile_id)}

        async def mutation(conn):
            row = await conn.fetchrow(
                """
                UPDATE bag.semantic_profiles
                SET status='RETIRED', retired_at=now()
                WHERE profile_id=$1 AND status <> 'RETIRED'
                RETURNING profile_id, source_id, company_id, profile_fingerprint
                """,
                profile_id,
            )
            if row is None:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM bag.semantic_profiles WHERE profile_id=$1)",
                    profile_id,
                )
                if not exists:
                    raise AdminNotFound("semantic profile not found")
                raise AdminConflict("semantic profile already retired")
            await conn.execute(
                """
                INSERT INTO bag.semantic_profile_events(
                    event_id, profile_id, actor, action, details_json
                ) VALUES($1,$2,$3,'RETIRED',$4::jsonb)
                """,
                uuid.uuid4(),
                profile_id,
                actor.subject,
                json.dumps(
                    {"profile_fingerprint": row["profile_fingerprint"]},
                    ensure_ascii=False,
                ),
            )
            return {
                "id": str(profile_id),
                "source_id": row["source_id"],
                "company_id": str(row["company_id"]) if row["company_id"] else None,
                "status": "RETIRED",
                "profile_fingerprint": row["profile_fingerprint"],
            }

        return await self._execute(
            actor=actor,
            command="semantic_profile.retire",
            target_type="semantic_profile",
            target_id=str(profile_id),
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def create_company_scope_mapping(
        self,
        *,
        actor: AdminActor,
        profile_id: uuid.UUID,
        entity_set: str,
        company_property: str,
        literal_kind: str,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if (
            not entity_set
            or "/" in entity_set
            or "\\" in entity_set
            or entity_set.startswith("$")
        ):
            raise AdminValidationError("invalid entity_set")
        if not company_property.isidentifier():
            raise AdminValidationError("company_property must be a single metadata property")
        if literal_kind not in {"guid", "string"}:
            raise AdminValidationError("literal_kind must be guid or string")
        request = {
            "profile_id": str(profile_id),
            "entity_set": entity_set,
            "company_property": company_property,
            "literal_kind": literal_kind,
        }

        async def mutation(conn):
            profile = await conn.fetchrow(
                """
                SELECT profile_id, source_id, company_id, status, metadata_fingerprint
                FROM bag.semantic_profiles
                WHERE profile_id=$1
                """,
                profile_id,
            )
            if profile is None:
                raise AdminNotFound("semantic profile not found")
            if profile["status"] != "VALIDATED":
                raise AdminValidationError("company scope mapping requires VALIDATED profile")
            mapping_id = uuid.uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO bag.company_scope_mappings(
                        scope_mapping_id, profile_id, entity_set,
                        company_property, literal_kind, created_by
                    ) VALUES($1,$2,$3,$4,$5,$6)
                    """,
                    mapping_id,
                    profile_id,
                    entity_set,
                    company_property,
                    literal_kind,
                    actor.subject,
                )
            except Exception as exc:
                if type(exc).__name__ == "UniqueViolationError":
                    raise AdminConflict(
                        "company scope mapping already exists for profile/entity"
                    ) from exc
                raise
            return {
                "id": str(mapping_id),
                "profile_id": str(profile_id),
                "source_id": profile["source_id"],
                "company_id": (
                    str(profile["company_id"]) if profile["company_id"] else None
                ),
                "entity_set": entity_set,
                "company_property": company_property,
                "literal_kind": literal_kind,
                "metadata_fingerprint": profile["metadata_fingerprint"],
            }

        return await self._execute(
            actor=actor,
            command="company_scope_mapping.create",
            target_type="company_scope_mapping",
            target_id=None,
            source_id=None,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )

    async def acknowledge_drift(
        self,
        *,
        actor: AdminActor,
        source_id: str,
        expected_fingerprint: str,
        reason: str,
        request_id: uuid.UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "source_id": source_id,
            "expected_fingerprint": expected_fingerprint,
        }

        async def mutation(conn):
            row = await conn.fetchrow(
                """
                UPDATE bag.source_capabilities
                SET drift_status='STABLE', drift_acknowledged_at=now()
                WHERE source_id=$1
                  AND metadata_fingerprint=$2
                  AND drift_status='DRIFTED'
                RETURNING source_id, metadata_fingerprint, drift_acknowledged_at
                """,
                source_id,
                expected_fingerprint,
            )
            if row is None:
                raise AdminConflict(
                    "source has no unacknowledged drift at expected fingerprint"
                )
            return {
                "id": source_id,
                "source_id": source_id,
                "metadata_fingerprint": row["metadata_fingerprint"],
                "drift_status": "STABLE",
                "drift_acknowledged_at": str(row["drift_acknowledged_at"]),
            }

        return await self._execute(
            actor=actor,
            command="drift.ack",
            target_type="source_capability",
            target_id=source_id,
            source_id=source_id,
            company_id=None,
            reason=reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request=request,
            mutation=mutation,
        )
