"""Focused handler-contract tests for S4 R2-US-016.

These tests exercise API validation, identity derivation, replay authorization ordering, and
HTTP outcome mapping with an injected in-memory port. They are not PostgreSQL-backed product
acceptance evidence; tests in the dedicated integration file own TC046-048 durable-store proof.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from starlette.requests import Request

from business_ai_gateway.admin_api import (
    AdminAPI,
    AdminContext,
    AdminRoleBinding,
    _promotion_port_status,
)
from business_ai_gateway.phase2.ports import AcceptanceView, HeadView, Scope, evidence_digest
from business_ai_gateway.phase2.promotion import AttestationView
from business_ai_gateway.phase2.promotion_sql import actor_role_for_subject

SUBJECT = "model-approver@example.test"
SOURCE = "source-a"
TENANT = "tenant-a"
COMPANY = UUID(int=17)
MODEL = "model-test"
REVISION = UUID(int=27)
ACCEPTANCE = UUID(int=37)
EVIDENCE_REF = "private:0123456789abcdef0123456789abcdef"
REVISION_DIGEST = "a" * 64


def _request(body: dict, *, source_id: str = SOURCE) -> Request:
    raw = json.dumps(body).encode("utf-8")
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({
        "type": "http",
        "method": "POST",
        "path": f"/admin/v1/sources/{source_id}/models/{MODEL}/promote",
        "query_string": b"",
        "headers": [(b"x-request-id", str(UUID(int=47)).encode())],
        "path_params": {"source_id": source_id, "model_key": MODEL},
    }, receive)


def _body(**updates) -> dict:
    result = {
        "tenant_id": TENANT,
        "source_id": SOURCE,
        "company_id": str(COMPANY),
        "expected_version": 0,
        "acceptance_id": str(ACCEPTANCE),
        "evidence_ref": EVIDENCE_REF,
        "revision_id": str(REVISION),
    }
    result.update(updates)
    return result


class _Port:
    def __init__(self, *, acceptances=(), head=None, attestation=None):
        self.acceptances = tuple(acceptances)
        self.head = head
        self.attestation = attestation
        self.actor = None
        self.scope = None
        self.authorize_calls = 0
        self.list_calls = 0
        self.attestation_calls = 0
        self.write_calls = 0

    async def authorize_scope(self, scope: Scope, company_id: str):
        self.authorize_calls += 1
        self.scope = scope
        if company_id != str(COMPANY):
            raise AssertionError("unexpected company scope")

    async def list_acceptances(self, actor, scope):
        self.list_calls += 1
        self.actor = actor
        self.scope = scope
        return self.acceptances

    async def find_attestation(self, scope, revision_id, evidence_ref):
        self.attestation_calls += 1
        assert scope == Scope(TENANT, SOURCE)
        assert revision_id == REVISION
        assert evidence_ref == EVIDENCE_REF
        return self.attestation

    async def get_revision_digest(self, scope, revision_id):
        assert scope == Scope(TENANT, SOURCE)
        assert revision_id == REVISION
        return REVISION_DIGEST

    async def is_trusted_reviewer(self, scope, subject):
        raise AssertionError("the product write routine owns trusted-reviewer enforcement")

    async def get_head(self, actor, scope, model_key):
        self.actor = actor
        return self.head

    async def promote_head(self, *args, **kwargs):
        self.write_calls += 1
        raise AssertionError("stale-head test must stop before the durable write")


def _api(monkeypatch, *, binding=AdminRoleBinding("PROFILE_ADMIN", SOURCE), port=None):
    import business_ai_gateway.admin_api as admin_api_module

    token = SimpleNamespace(
        subject=SUBJECT,
        client_id="admin-client",
        scopes=frozenset({"admin"}),
        claims={"groups": []},
    )
    ctx = AdminContext(token=token, groups=frozenset(), bindings=(binding,))
    api = object.__new__(AdminAPI)
    api.authenticate = AsyncMock(return_value=ctx)
    api.runtime = SimpleNamespace(
        model_promotion_db=SimpleNamespace(
            require_pool=lambda: object(), assert_promotion_role=AsyncMock()
        ),
        evidence_provider=SimpleNamespace(
            read_manifest_after_access_gate=AsyncMock(return_value={"document_sha256": "b" * 64})
        ),
        rate_limit=SimpleNamespace(check=AsyncMock()),
    )
    api.mutations = SimpleNamespace(record_admin_event=AsyncMock())
    selected_port = port or _Port()

    class PortFactory:
        def __new__(cls, pool, actor_role, company_id):
            assert pool is not None
            assert company_id == str(COMPANY)
            selected_port.actor = actor_role
            return selected_port

    monkeypatch.setattr(admin_api_module, "PromotionPostgresPort", PortFactory)
    return api, ctx, selected_port


def _attestation() -> AttestationView:
    return AttestationView(
        attestation_id=UUID(int=57),
        revision_id=REVISION,
        proposer="candidate-author",
        observer="independent-reviewer",
        evidence_ref=EVIDENCE_REF,
        evidence_digest=evidence_digest(REVISION_DIGEST, EVIDENCE_REF),
        decision="APPROVE",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        revoked_at=None,
    )


async def test_promotion_body_cannot_supply_trusted_requester_or_approver(monkeypatch):
    api, _, port = _api(monkeypatch)
    request = _request(_body(requester="candidate-author", approver="attacker"))

    response = await api.model_head_promote(request)

    assert response.status_code == 400
    assert port.authorize_calls == 0
    assert port.list_calls == 0
    api.runtime.evidence_provider.read_manifest_after_access_gate.assert_not_awaited()


async def test_profile_admin_scope_is_checked_before_constructing_database_port(monkeypatch):
    api, _, _ = _api(monkeypatch, binding=AdminRoleBinding("PROFILE_ADMIN", "other-source"))
    request = _request(_body())

    response = await api.model_head_promote(request)

    assert response.status_code == 403
    api.runtime.rate_limit.check.assert_not_awaited()
    api.runtime.evidence_provider.read_manifest_after_access_gate.assert_not_awaited()


async def test_authorized_identical_replay_uses_verified_subject_role_before_reading_evidence(monkeypatch):
    actor_role = actor_role_for_subject(SUBJECT)
    recorded = AcceptanceView(
        acceptance_id=ACCEPTANCE,
        model_key=MODEL,
        from_version=0,
        to_version=1,
        accepted_revision=REVISION,
        approver_subject=actor_role,
        independent_evidence_ref=EVIDENCE_REF,
    )
    port = _Port(acceptances=(recorded,))
    api, _, port = _api(monkeypatch, port=port)

    response = await api.model_head_promote(_request(_body()))

    assert response.status_code == 200
    assert json.loads(response.body) == {"outcome": "PROMOTED", "code": None, "new_version": 1}
    assert port.actor == actor_role
    assert SUBJECT not in actor_role
    assert port.authorize_calls == 1
    assert port.list_calls == 1
    assert port.attestation_calls == 0
    api.runtime.evidence_provider.read_manifest_after_access_gate.assert_not_awaited()


async def test_reused_acceptance_id_with_different_arguments_is_conflict(monkeypatch):
    recorded = AcceptanceView(
        acceptance_id=ACCEPTANCE,
        model_key=MODEL,
        from_version=0,
        to_version=1,
        accepted_revision=UUID(int=999),
        approver_subject=actor_role_for_subject(SUBJECT),
        independent_evidence_ref=EVIDENCE_REF,
    )
    port = _Port(acceptances=(recorded,))
    api, _, port = _api(monkeypatch, port=port)

    response = await api.model_head_promote(_request(_body()))

    assert response.status_code == 409
    assert json.loads(response.body) == {"error": "ACCEPTANCE_ID_REUSED"}
    assert port.authorize_calls == 1
    assert port.list_calls == 1
    assert port.attestation_calls == 0
    api.runtime.evidence_provider.read_manifest_after_access_gate.assert_not_awaited()


async def test_non_private_or_unscoped_evidence_reference_is_rejected_before_read(monkeypatch):
    api, _, port = _api(monkeypatch)
    request = _request(_body(evidence_ref="file:///untrusted/path"))

    response = await api.model_head_promote(request)

    assert response.status_code == 400
    assert port.authorize_calls == 0
    assert port.list_calls == 0
    api.runtime.evidence_provider.read_manifest_after_access_gate.assert_not_awaited()


async def test_stale_expected_head_maps_to_http_409_without_durable_write(monkeypatch):
    port = _Port(
        head=HeadView(MODEL, UUID(int=1), 1),
        attestation=_attestation(),
    )
    api, _, port = _api(monkeypatch, port=port)

    response = await api.model_head_promote(_request(_body(expected_version=0)))

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["outcome"] == "REJECTED_CAS"
    assert payload["code"] == "STALE_ACCEPTED_HEAD"
    assert port.authorize_calls == 1
    # The handler authorizes before opening private evidence; the service re-reads scoped
    # acceptances after that I/O so authorization is rechecked before its decision.
    assert port.list_calls == 2
    # The handler preflights the attestation before opening bytes; the service then re-reads it
    # after the evidence I/O to avoid relying on a potentially stale preflight view.
    assert port.attestation_calls == 2
    assert port.write_calls == 0
    api.runtime.evidence_provider.read_manifest_after_access_gate.assert_awaited_once_with(
        SOURCE, COMPANY, "0123456789abcdef0123456789abcdef"
    )


async def test_rollback_with_revoked_attestation_is_denied_without_write(monkeypatch):
    actor_role = actor_role_for_subject(SUBJECT)
    accepted_target = AcceptanceView(
        acceptance_id=UUID(int=67),
        model_key=MODEL,
        from_version=0,
        to_version=1,
        accepted_revision=REVISION,
        approver_subject=actor_role,
        independent_evidence_ref=EVIDENCE_REF,
    )
    revoked = _attestation()
    revoked = AttestationView(
        attestation_id=revoked.attestation_id,
        revision_id=revoked.revision_id,
        proposer=revoked.proposer,
        observer=revoked.observer,
        evidence_ref=revoked.evidence_ref,
        evidence_digest=revoked.evidence_digest,
        decision=revoked.decision,
        expires_at=revoked.expires_at,
        revoked_at=datetime.now(UTC),
    )
    port = _Port(
        acceptances=(accepted_target,),
        head=HeadView(MODEL, UUID(int=77), 2),
        attestation=revoked,
    )
    api, _, port = _api(monkeypatch, port=port)
    body = _body(expected_version=2, acceptance_id=str(UUID(int=78)), to_version=1)
    body.pop("revision_id")

    response = await api.model_head_rollback(_request(body))

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["outcome"] == "REJECTED_REVOKED"
    assert payload["code"] == "EVIDENCE_REVOKED"
    assert port.write_calls == 0
    assert port.authorize_calls == 1
    assert api.runtime.evidence_provider.read_manifest_after_access_gate.await_count == 1


def test_promotion_port_errors_distinguish_conflict_from_unavailable_dependencies():
    assert _promotion_port_status("STALE_ACCEPTED_HEAD") == 409
    assert _promotion_port_status("NOT_A_PROMOTER") == 403
    assert _promotion_port_status("SCOPE_REVOKED") == 403
    assert _promotion_port_status("INVALID_ARGUMENT") == 400
    assert _promotion_port_status("DATABASE_UNAVAILABLE") == 503
