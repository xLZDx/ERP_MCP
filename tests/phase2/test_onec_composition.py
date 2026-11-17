from __future__ import annotations

from dataclasses import replace
from inspect import signature

import pytest

from business_ai_gateway.models import Source
from business_ai_gateway.phase2.backend_budget import PhysicalBackendBudget
from business_ai_gateway.phase2.drift import DriftEventKind
from business_ai_gateway.phase2.onec_composition import (
    RegisteredOneCMetadataComposition,
    classify_observation,
)
from business_ai_gateway.phase2.onec_discovery import MetadataCompleteness
from business_ai_gateway.phase2.ports import Scope
from business_ai_gateway.principal import Principal


XML = (
    b'<e:Edmx xmlns:e="urn:edmx" xmlns:m="urn:edm"><e:DataServices>'
    b'<m:Schema Namespace="Demo"><m:EntityType Name="Org"/><m:EntityType Name="Secret"/>'
    b'<m:EntityContainer Name="Default"><m:EntitySet Name="Catalog_Orgs" '
    b'EntityType="Demo.Org"/></m:EntityContainer></m:Schema>'
    b'</e:DataServices></e:Edmx>'
)
CHANGED_XML = XML.replace(b'Name="Org"', b'Name="Org" Abstract="true"')
SOURCE = Source(
    id="onec-main",
    project="onec",
    kind="onec_odata",
    display_name="Registered ERP",
    base_url="https://erp.example.test/odata",
    username_secret_ref="onec-user",
    password_secret_ref="onec-password",
    read_only=True,
    enabled=True,
    tags=(),
    entity_allow_patterns=(),
    entity_deny_patterns=(),
    row_version=1,
)
PRINCIPAL = Principal(
    subject="metadata-auditor",
    client_id="phase2-tests",
    scopes=frozenset({"onec:read"}),
    groups=frozenset(),
    claims={},
)
ACCEPTED_HASH = "a" * 64


class Registry:
    def __init__(self, state):
        self.state = state
        self.calls = []

    async def require_source(self, principal, source_id):
        self.calls.append((principal.subject, source_id))
        if source_id != self.state["source"].id:
            raise LookupError("SOURCE_NOT_FOUND")
        return self.state["source"]


class ScopeResolver:
    def __init__(self, state):
        self.state = state
        self.calls = 0

    async def resolve_scope(self, principal, source):
        self.calls += 1
        return self.state.get("scope", Scope("tenant-a", source.id))


class MetadataAuthorizer:
    def __init__(self, state):
        self.state = state
        self.calls = []

    async def allow_source_metadata(self, principal, source, *, tenant_id):
        self.calls.append((principal.subject, source.id, tenant_id))
        return not self.state.get("revoked", False)


class EntityAuthorizer:
    def __init__(self, *, deny_secret=False):
        self.deny_secret = deny_secret
        self.calls = []

    def allow_entity(self, principal, source, qualified_name, *, tenant_id):
        self.calls.append((principal.subject, source.id, qualified_name, tenant_id))
        return not (self.deny_secret and "Secret" in qualified_name)


class OneCTransport:
    def __init__(self, state):
        self.state = state
        self.calls = []

    async def get_bytes(self, source, path, *, username, password, accept):
        self.state["trace"].append(("fetch", path))
        self.calls.append((source.id, source.base_url, path, username, password, accept))
        callback = self.state.get("after_fetch")
        if callback is not None:
            callback()
        return self.state.get("xml", XML)


class OneC:
    def __init__(self, state):
        self.state = state
        self.client = OneCTransport(state)
        self.credential_calls = []

    async def credentials(self, source):
        self.credential_calls.append(source.id)
        return "user-secret", "password-secret"


def make_composition(*, state=None, audit=None, deny_secret=False):
    state = state or {"source": SOURCE, "scope": Scope("tenant-a", SOURCE.id)}
    events = []
    state["trace"] = events
    registry = Registry(state)
    scope = ScopeResolver(state)
    metadata = MetadataAuthorizer(state)
    entities = EntityAuthorizer(deny_secret=deny_secret)
    onec = OneC(state)

    async def record_audit(event, details):
        if audit is not None:
            await audit(event, details)
        events.append(("audit", event, dict(details)))

    composition = RegisteredOneCMetadataComposition(
        registry=registry,
        onec=onec,
        scope_resolver=scope,
        metadata_authorizer=metadata,
        entity_authorizer=entities,
        audit=record_audit,
        backend_budget=PhysicalBackendBudget(per_backend_limit=2, total_limit=2),
    )
    return composition, state, events, registry, scope, metadata, entities, onec


@pytest.mark.asyncio
async def test_registered_composition_uses_only_registered_read_transport_and_stable_complete_digest():
    composition, _state, events, registry, _scope, _metadata, _entities, onec = make_composition()

    first = await composition.observe(PRINCIPAL, SOURCE.id)
    second = await composition.observe(PRINCIPAL, SOURCE.id)

    assert first.completeness is MetadataCompleteness.COMPLETE
    assert first.fingerprint is not None
    assert first.fingerprint.structural_sha256 == second.fingerprint.structural_sha256
    assert first.fingerprint.tenant_id == "tenant-a"
    assert first.fingerprint.source_id == SOURCE.id
    assert {name for name, _digest in first.fingerprint.objects} == {
        "Demo::EntityType::Org", "Demo::EntityType::Secret",
        "Demo::EntityContainer::Default",
        "Demo::Default::EntitySet::Catalog_Orgs",
    }
    assert registry.calls and all(call == (PRINCIPAL.subject, SOURCE.id) for call in registry.calls)
    assert onec.credential_calls == [SOURCE.id, SOURCE.id]
    assert onec.client.calls == [
        (SOURCE.id, SOURCE.base_url, "$metadata", "user-secret", "password-secret", "application/xml"),
    ] * 2
    assert [event[0] for event in events] == ["audit", "fetch", "audit", "fetch"]
    assert events[0][2]["tenant_id"] == "tenant-a"


def test_registered_composition_boundary_has_no_database_or_sql_collaborator():
    parameters = set(signature(RegisteredOneCMetadataComposition.__init__).parameters) - {"self"}
    assert parameters == {
        "registry", "onec", "scope_resolver", "metadata_authorizer", "entity_authorizer",
        "audit", "backend_budget", "max_metadata_bytes", "scope_resolution_timeout_seconds",
    }
    assert not parameters.intersection({"db", "database", "sql", "query", "connection"})


@pytest.mark.asyncio
async def test_direct_sql_text_cannot_bypass_registered_source_lookup():
    composition, _state, _events, registry, _scope, _metadata, _entities, onec = make_composition()

    with pytest.raises(LookupError, match="SOURCE_NOT_FOUND"):
        await composition.observe(PRINCIPAL, "SELECT * FROM metadata")

    assert registry.calls == [(PRINCIPAL.subject, "SELECT * FROM metadata")]
    assert onec.credential_calls == []
    assert onec.client.calls == []


@pytest.mark.asyncio
async def test_scope_for_different_source_fails_closed_before_audit_credentials_or_transport():
    state = {"source": SOURCE, "scope": Scope("tenant-a", "another-source")}
    composition, _state, events, _registry, _scope, _metadata, _entities, onec = make_composition(state=state)

    with pytest.raises(PermissionError, match="TENANT_SOURCE_SCOPE_DENIED"):
        await composition.observe(PRINCIPAL, SOURCE.id)

    assert events == []
    assert onec.credential_calls == []
    assert onec.client.calls == []


@pytest.mark.asyncio
async def test_missing_metadata_grant_is_audited_and_never_reaches_registered_transport():
    state = {"source": SOURCE, "scope": Scope("tenant-a", SOURCE.id), "revoked": True}
    composition, _state, events, _registry, _scope, _metadata, _entities, onec = make_composition(state=state)

    with pytest.raises(PermissionError, match="SOURCE_METADATA_ACCESS_DENIED"):
        await composition.observe(PRINCIPAL, SOURCE.id)

    assert len(events) == 1
    assert events[0][2]["outcome"] == "denied"
    assert events[0][2]["reason"] == "SOURCE_METADATA_ACCESS_DENIED"
    assert onec.credential_calls == []
    assert onec.client.calls == []


@pytest.mark.asyncio
async def test_audit_failure_prevents_credentials_and_registered_transport():
    async def fail_audit(_event, _details):
        raise OSError("audit unavailable")

    composition, _state, _events, _registry, _scope, _metadata, _entities, onec = make_composition(
        audit=fail_audit)

    with pytest.raises(PermissionError, match="AUDIT_WRITE_FAILED"):
        await composition.observe(PRINCIPAL, SOURCE.id)

    assert onec.credential_calls == []
    assert onec.client.calls == []


@pytest.mark.asyncio
async def test_acl_filtered_registered_observation_is_partial_and_hides_denied_entity():
    composition, _state, _events, _registry, _scope, _metadata, entities, _onec = make_composition(
        deny_secret=True)

    result = await composition.observe(PRINCIPAL, SOURCE.id)

    assert result.completeness is MetadataCompleteness.PARTIAL_ACL_FILTERED
    assert result.withheld_objects == 1
    assert result.fingerprint is not None and result.fingerprint.acl_filtered
    assert "Demo::EntityType::Org" in dict(result.fingerprint.objects)
    assert not any("Secret" in name for name, _digest in result.fingerprint.objects)
    assert "Secret" not in repr(result)
    assert any("Secret" in call[2] for call in entities.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("source", MetadataCompleteness.PARTIAL_SOURCE_CHANGED),
        ("scope", MetadataCompleteness.PARTIAL_SCOPE_CHANGED),
        ("revoked", MetadataCompleteness.PARTIAL_ACCESS_REVOKED),
    ],
)
async def test_mid_fetch_source_scope_or_access_change_is_partial_and_keeps_baseline(change, expected):
    state = {"source": SOURCE, "scope": Scope("tenant-a", SOURCE.id)}

    def change_during_fetch():
        if change == "source":
            state["source"] = replace(SOURCE, row_version=2)
        elif change == "scope":
            state["scope"] = Scope("tenant-b", SOURCE.id)
        else:
            state["revoked"] = True

    state["after_fetch"] = change_during_fetch
    composition, _state, _events, _registry, _scope, _metadata, _entities, _onec = make_composition(
        state=state)

    observation = await composition.observe(PRINCIPAL, SOURCE.id)
    decision = classify_observation(observation, ACCEPTED_HASH)

    assert observation.completeness is expected
    assert observation.fingerprint is None
    assert decision.accepted_hash == ACCEPTED_HASH
    assert decision.events == (DriftEventKind.GAP,)
    assert decision.candidate_hash is None
    assert decision.removal_permitted is False


@pytest.mark.asyncio
async def test_changed_complete_digest_warns_without_advancing_accepted_baseline():
    state = {"source": SOURCE, "scope": Scope("tenant-a", SOURCE.id), "xml": XML}
    composition, _state, _events, _registry, _scope, _metadata, _entities, _onec = make_composition(
        state=state)

    first = await composition.observe(PRINCIPAL, SOURCE.id)
    state["xml"] = CHANGED_XML
    changed = await composition.observe(PRINCIPAL, SOURCE.id)
    decision = classify_observation(changed, first.fingerprint.structural_sha256)

    assert changed.completeness is MetadataCompleteness.COMPLETE
    assert decision.events == (DriftEventKind.STRUCTURAL_DRIFT,)
    assert decision.accepted_hash == first.fingerprint.structural_sha256
    assert decision.candidate_hash == changed.fingerprint.structural_sha256
    assert decision.candidate_hash != decision.accepted_hash
