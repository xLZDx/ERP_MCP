"""REQ-007/008: ChangeService re-parses and binds every ProposalPort result before storage."""
from dataclasses import replace
from datetime import timedelta

import pytest

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.types import ChangeKind, Scope
from erp_mcp_s16.contracts import FROZEN_V2_PROPOSAL_KINDS, TokenClass
from erp_mcp_s16.fakes import FakeProposalPort, InMemoryChangeStore
from tests.phase2.s16_helpers import NOW, build_env, raw_create


class CountingStore(InMemoryChangeStore):
    def __init__(self):
        super().__init__()
        self.insert_calls = 0

    def insert_proposal(self, receipt):
        self.insert_calls += 1
        return super().insert_proposal(receipt)


class MutatingProposalPort:
    def __init__(self, inner, mode):
        self.inner, self.mode = inner, mode

    def build(self, requester, raw_request, *, now, expires_at, preview_digest, change_id):
        result = self.inner.build(requester, raw_request, now=now, expires_at=expires_at,
                                  preview_digest=preview_digest, change_id=change_id)
        if type(result) is ErrorCode:
            return result
        proposal, target = result
        if self.mode == "foreign_scope":
            proposal = replace(proposal, scope=Scope("foreign-tenant", "foreign-company", "org-1", "foreign-base"))
        elif self.mode == "foreign_person":
            proposal = replace(proposal, requester_person_id="person-someone-else")
        elif self.mode == "stale_created":
            proposal = replace(proposal, created_at=now - timedelta(seconds=1))
        elif self.mode == "expired":
            proposal = replace(proposal, created_at=now - timedelta(minutes=5),
                               expires_at=now - timedelta(microseconds=1))
        elif self.mode == "foreign_principal":
            proposal = replace(proposal, requester_principal="someone-else")
        elif self.mode == "wrong_change_id":
            proposal = replace(proposal, change_id="different-change-id")
        elif self.mode == "wrong_preview_digest":
            proposal = replace(proposal, preview_digest="f" * 64)
        elif self.mode == "wrong_payload_digest":
            object.__setattr__(proposal, "payload_digest", "f" * 64)
        return proposal, target

    def rollback(self, requester, receipt, *, now, expires_at, preview_digest, change_id):
        return self.inner.rollback(requester, receipt, now=now, expires_at=expires_at,
                                   preview_digest=preview_digest, change_id=change_id)


@pytest.mark.parametrize("mode", [
    "foreign_scope", "foreign_person", "stale_created", "expired", "foreign_principal",
    "wrong_change_id", "wrong_preview_digest", "wrong_payload_digest",
])
def test_malicious_proposal_port_values_are_rejected_before_store_insert(mode):
    store = CountingStore()
    env = build_env(store=store)
    env.change_service.proposal_port = MutatingProposalPort(env.change_service.proposal_port, mode)
    result = env.change_service.propose(env.requester, raw_create(), now=NOW)
    assert result.error is ErrorCode.DIGEST_MISMATCH
    assert store.insert_calls == 0
    assert not store._receipts


def test_wrong_token_class_is_refused_before_proposal_port_or_store():
    store = CountingStore()
    env = build_env(store=store)
    wrong = replace(env.requester, token_class=TokenClass.READ_ONLY)
    result = env.change_service.propose(wrong, raw_create(), now=NOW)
    assert result.error is ErrorCode.NOT_ENTITLED
    assert store.insert_calls == 0
    assert not store._receipts


def test_foreign_request_scope_is_refused_before_proposal_port_or_store():
    store = CountingStore()
    env = build_env(store=store)
    foreign_scope = replace(env.requester.scope, tenant="foreign-tenant")
    result = env.change_service.propose(replace(env.requester, scope=foreign_scope), raw_create(), now=NOW)
    assert result.error in {ErrorCode.TARGET_REJECTED, ErrorCode.SCOPE_MISMATCH}
    assert store.insert_calls == 0
    assert not store._receipts


def _operation_request(kind):
    if kind == "CREATE_DRAFT":
        return raw_create()
    return {"kind": kind, "request_id": f"s16-{kind.lower()}",
            "parent_change_id": "prior-change", "target_ref": "document-1",
            "target_version": "v1", "reason": "frozen kind contract"}


@pytest.mark.parametrize("kind", ["CREATE_DRAFT", "POST", "UNPOST"])
def test_governed_service_accepts_each_frozen_kind_in_test_lane(kind):
    store = CountingStore()
    env = build_env(store=store)
    target = env.targets.current(env.requester.scope)
    env.targets.put(replace(target, parent_verified=True))

    result = env.change_service.propose(env.requester, _operation_request(kind), now=NOW)

    assert result.error is None, result.error
    assert result.value.proposal.kind.value == kind
    assert store.insert_calls == 1


@pytest.mark.parametrize("kind", ["CREATE_DRAFT", "POST", "UNPOST"])
def test_fake_proposal_port_builds_each_frozen_kind_in_test_lane(kind):
    env = build_env()
    target = env.targets.current(env.requester.scope)
    env.targets.put(replace(target, parent_verified=True))
    port = FakeProposalPort(env.targets, env.principals)

    result = port.build(env.requester, _operation_request(kind), now=NOW,
                        expires_at=NOW + timedelta(minutes=5), preview_digest="0" * 64,
                        change_id="11111111-1111-4111-8111-111111111111")

    assert type(result) is tuple
    assert result[0].kind.value == kind


@pytest.mark.parametrize("entry", ["service", "fake_port"])
@pytest.mark.parametrize("case", ["update", "missing", "unknown", "enum", "integer", "null"])
def test_non_frozen_or_malformed_kind_fails_before_registry_or_side_effects(entry, case, monkeypatch):
    store = CountingStore()
    env = build_env(store=store)
    request = raw_create()
    if case == "update":
        request["kind"] = "UPDATE_DRAFT"
    elif case == "missing":
        request.pop("kind")
    elif case == "unknown":
        request["kind"] = "UNRECOGNIZED"
    elif case == "enum":
        request["kind"] = ChangeKind.CREATE_DRAFT
    elif case == "integer":
        request["kind"] = 1
    else:
        request["kind"] = None

    target_calls = {"current": 0, "resolve_fingerprint": 0}
    principal_calls = {"current": 0}
    for name in target_calls:
        original = getattr(env.targets, name)

        def counted_target(*args, _name=name, _original=original, **kwargs):
            target_calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(env.targets, name, counted_target)
    original_principal = env.principals.current

    def counted_principal(*args, **kwargs):
        principal_calls["current"] += 1
        return original_principal(*args, **kwargs)

    monkeypatch.setattr(env.principals, "current", counted_principal)
    builder_calls = {"count": 0}
    original_build = env.change_service.proposal_port.build

    def counted_build(*args, **kwargs):
        builder_calls["count"] += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(env.change_service.proposal_port, "build", counted_build)
    nonce_count_before = env.nonce_source._counter

    if entry == "service":
        result = env.change_service.propose(env.requester, request, now=NOW)
        error = result.error
    else:
        result = FakeProposalPort(env.targets, env.principals).build(
            env.requester, request, now=NOW, expires_at=NOW + timedelta(minutes=5),
            preview_digest="0" * 64, change_id="11111111-1111-4111-8111-111111111111")
        error = result

    assert error is ErrorCode.SCHEMA_INVALID
    assert target_calls == {"current": 0, "resolve_fingerprint": 0}
    assert principal_calls["current"] == 0
    assert builder_calls["count"] == 0
    assert env.nonce_source._counter == nonce_count_before
    assert store.insert_calls == 0
    assert not store._receipts


def test_frozen_proposal_kind_vocabulary_is_exact_and_immutable():
    assert type(FROZEN_V2_PROPOSAL_KINDS) is frozenset
    assert FROZEN_V2_PROPOSAL_KINDS == frozenset({"CREATE_DRAFT", "POST", "UNPOST"})
    with pytest.raises(AttributeError):
        FROZEN_V2_PROPOSAL_KINDS.add("UPDATE_DRAFT")
